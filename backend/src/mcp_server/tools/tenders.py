"""
src/mcp_server/tools/tenders.py - Procurement process search and detail.
"""

from __future__ import annotations

from typing import Annotated, Optional

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from src.api.services import tender_service
from src.api.services.detection_context import load_detection_context

from .. import runtime
from ._common import READ_ONLY, trim_findings


def register(mcp: MCPServer) -> None:
    @mcp.tool(annotations=READ_ONLY)
    def search_tenders(
        text: Annotated[Optional[str], Field(description="Substring of the process number, title or object of procurement")] = None,
        cuit: Annotated[Optional[str], Field(description="Only processes this provider bid on or was awarded")] = None,
        unit_code: Annotated[Optional[str], Field(description="Only processes managed by this contracting unit code")] = None,
        date_from: Annotated[Optional[str], Field(description="ISO date, on the opening date")] = None,
        date_to: Annotated[Optional[str], Field(description="ISO date, on the opening date")] = None,
        limit: Annotated[int, Field(description="Max processes (max 200)")] = 25,
    ) -> dict:
        """Search procurement processes (licitaciones, contrataciones directas...) in Neo4j, newest
        first. Each result has its unit, awarded providers and number of bids."""
        limit = runtime.clamp(limit)
        items = tender_service.search_tenders(
            runtime.neo4j_driver(), text=text, cuit=cuit, unit_code=unit_code,
            date_from=date_from, date_to=date_to, limit=limit,
        )
        return {"returned": len(items), "possibly_more": len(items) == limit, "items": items}

    @mcp.tool(annotations=READ_ONLY)
    def get_tender(
        process_number: Annotated[str, Field(description="Exact process number, e.g. '84/13-2056-LPR24'")],
        max_rows_per_check: Annotated[int, Field(description="Finding rows kept per check (max 200)")] = 20,
    ) -> dict:
        """Everything about one process: data from the portal, contracting unit and organization,
        every bid with amounts, purchase orders with the awarded provider and signing officials,
        pre-award opinions (dictámenes), plus the red-flag findings that reference it."""
        detail = None
        neo4j_error = None
        try:
            detail = tender_service.get_tender(runtime.neo4j_driver(), process_number)
        except ToolError as exc:
            neo4j_error = str(exc)

        findings = {}
        with runtime.db_session() as db:
            ctx = load_detection_context(db, runtime.locale())
            if ctx is not None:
                findings = tender_service.find_tender_findings(ctx.findings, ctx.check_meta, process_number)

        if detail is None and not findings:
            raise ToolError(neo4j_error or f"Process '{process_number}' not found.")
        result = detail or {"process": {"process_number": process_number}}
        if neo4j_error:
            result["neo4j_error"] = neo4j_error
        result["findings"] = trim_findings(findings, runtime.clamp(max_rows_per_check))
        return result
