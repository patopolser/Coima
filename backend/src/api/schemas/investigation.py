"""
src/api/schemas/investigation.py - Pydantic models for the investigation endpoints.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel

AIModel = Literal["claude", "gemini", "deepseek"]


class SubjectSchema(BaseModel):
    type: Literal["company", "tender"]
    id: str
    name: str
    detail_url: Optional[str] = None


class NoteSchema(BaseModel):
    id: str
    created_at: str
    text: str


class ChatMessageSchema(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_results: Optional[List[Dict[str, Any]]] = None
    created_at: str


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
    chat_history: List[ChatMessageSchema]
    reports: List[ReportSchema]


class CreateInvestigationRequest(BaseModel):
    title: str
    subjects: List[SubjectSchema] = []
    context_snapshot: Dict[str, Any] = {}


class AddSubjectRequest(BaseModel):
    type: Literal["company", "tender"]
    id: str
    name: str = ""
    detail_url: Optional[str] = None


class AddNoteRequest(BaseModel):
    text: str


class ChatRequest(BaseModel):
    message: str
    model: AIModel = "claude"


class ReportRequest(BaseModel):
    type: Literal["executive_summary", "timeline", "network_analysis", "cartel_hypothesis"] = "executive_summary"
    model: AIModel = "claude"


class UpdateStatusRequest(BaseModel):
    status: Literal["open", "in_progress", "closed", "archived"]
