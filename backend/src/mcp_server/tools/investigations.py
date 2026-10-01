"""
src/mcp_server/tools/investigations.py - Persistent investigation cases.

The only tools that write. They let an agent keep a case (subjects, notes,
reports) in Coima's SQLite across sessions instead of losing its work when
the conversation ends. Nothing here deletes data.
"""

from __future__ import annotations

from typing import Annotated, List, Optional

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from src.api.schemas.investigation import InvestigationStatus, SubjectSchema, SubjectType
from src.api.services import investigation_service as svc

from .. import runtime
from ._common import READ_ONLY, WRITES_CASE

REPORT_TYPES = ("executive_summary", "timeline", "network_analysis", "cartel_hypothesis")


def _found(detail, investigation_id: str):
    if detail is None:
        raise ToolError(f"Investigation '{investigation_id}' not found. Use list_investigations.")
    return detail


def _ack(detail) -> dict:
    """Short confirmation after a write, instead of echoing every note and report back."""
    return {
        "id": detail.id,
        "title": detail.title,
        "status": detail.status,
        "updated_at": detail.updated_at,
        "subjects": [s.model_dump(exclude={"detail_url"}) for s in detail.subjects],
        "note_count": len(detail.notes),
        "report_count": len(detail.reports),
    }


def register(mcp: MCPServer) -> None:
    @mcp.tool(annotations=READ_ONLY)
    def list_investigations(
        status: Optional[InvestigationStatus] = None,
        search: Annotated[Optional[str], Field(description="Substring of the title or of a subject id/name")] = None,
    ) -> dict:
        """Investigation cases stored in Coima, most recently updated first."""
        with runtime.db_session() as db:
            cases = svc.list_investigations(db, status=status, search=search)
            return {"total": len(cases), "items": [c.model_dump() for c in cases]}

    @mcp.tool(annotations=READ_ONLY)
    def get_investigation(investigation_id: str) -> dict:
        """A case with its subjects, every note and every saved report. Read it before continuing
        an investigation so earlier findings are not repeated."""
        with runtime.db_session() as db:
            return _found(svc.get_investigation(db, investigation_id), investigation_id).model_dump()

    @mcp.tool(annotations=WRITES_CASE)
    def create_investigation(
        title: str,
        subjects: Annotated[Optional[List[SubjectSchema]], Field(description="Entities under investigation: type is company (id = CUIT), tender (id = process number), unit (id = unit code) or authorizer (id = full name)")] = None,
    ) -> dict:
        """Open a new investigation case. Returns it with its id."""
        with runtime.db_session() as db:
            return _ack(svc.create_investigation(db, title=title, subjects=subjects or [], context_snapshot={}))

    @mcp.tool(annotations=WRITES_CASE)
    def add_subject(
        investigation_id: str,
        type: SubjectType,
        id: Annotated[str, Field(description="CUIT, process number, unit code or authorizer full name")],
        name: str = "",
    ) -> dict:
        """Add an entity to a case (ignored if already there)."""
        with runtime.db_session() as db:
            subject = SubjectSchema(type=type, id=id, name=name)
            return _ack(_found(svc.add_subject(db, investigation_id, subject), investigation_id))

    @mcp.tool(annotations=WRITES_CASE)
    def add_note(
        investigation_id: str,
        text: Annotated[str, Field(min_length=1, description="Finding, hypothesis or lead, citing CUITs, process numbers, amounts and dates")],
    ) -> dict:
        """Record a finding in the case's intelligence log."""
        with runtime.db_session() as db:
            return _ack(_found(svc.add_note(db, investigation_id, text), investigation_id))

    @mcp.tool(annotations=WRITES_CASE)
    def save_report(
        investigation_id: str,
        report_type: Annotated[str, Field(description=f"One of {', '.join(REPORT_TYPES)}, or another short snake_case label")],
        content: Annotated[str, Field(min_length=1, description="The report in Markdown")],
    ) -> dict:
        """Store a finished Markdown report in the case."""
        with runtime.db_session() as db:
            report = svc.add_report(db, investigation_id, report_type, content)
            if report is None:
                raise ToolError(f"Investigation '{investigation_id}' not found. Use list_investigations.")
            return {"id": report.id, "investigation_id": investigation_id, "type": report.type, "created_at": report.created_at}

    @mcp.tool(annotations=WRITES_CASE)
    def set_investigation_status(investigation_id: str, status: InvestigationStatus) -> dict:
        """Move a case to open, in_progress, closed or archived."""
        with runtime.db_session() as db:
            return _ack(_found(svc.set_status(db, investigation_id, status), investigation_id))
