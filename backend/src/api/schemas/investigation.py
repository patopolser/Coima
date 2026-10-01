"""
src/api/schemas/investigation.py - Pydantic models for investigation cases.

Cases are created and fed by AI agents through the MCP server
(src/mcp_server/tools/investigations.py).
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel

SubjectType = Literal["company", "tender", "unit", "authorizer"]
InvestigationStatus = Literal["open", "in_progress", "closed", "archived"]


class SubjectSchema(BaseModel):
    type: SubjectType
    id: str
    name: str = ""
    detail_url: Optional[str] = None


class NoteSchema(BaseModel):
    id: str
    created_at: str
    text: str


class ReportSchema(BaseModel):
    id: str
    type: str
    content: str
    created_at: str


class InvestigationSummary(BaseModel):
    id: str
    title: str
    status: str
    created_at: str
    updated_at: str
    subjects: List[SubjectSchema]


class InvestigationDetail(InvestigationSummary):
    context_snapshot: Dict[str, Any]
    notes: List[NoteSchema]
    reports: List[ReportSchema]
