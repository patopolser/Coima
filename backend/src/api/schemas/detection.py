"""
src/api/schemas/detection.py - Pydantic models for the detection endpoints.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel


class RiskScoreItem(BaseModel):
    cuit: str
    company: str
    score: int
    flags: Union[str, List[str]]
    # Smart-scoring fields are optional so legacy rows and older runs still
    # validate against this schema.
    entity_type: str = "provider"
    base_score: Optional[int] = None
    confidence: int = 0
    evidence_breakdown: Optional[Dict[str, Any]] = None


class DetectionRunSummary(BaseModel):
    id: int
    created_at: str
    tender_count: int
    summary: Dict[str, int]
    status: str


class DetectionRunResponse(DetectionRunSummary):
    risk_scores: List[RiskScoreItem]
    cached: bool = False


class CheckMeta(BaseModel):
    key: str
    label: str
    description: str
    color: str
    weight: int
    columns: List[Any]
    cuit_columns: List[str]
    unit_columns: List[str]
    # Column keys grouped by the entity namespace they target
    # (e.g. {"provider": [...], "unit": [...], "authorizer": [...]}).
    entity_columns: Dict[str, List[str]] = {}
    url_columns: Dict[str, str]
    search_fields: List[str]
    total_findings: int


class CheckDetail(CheckMeta):
    items: List[Dict[str, Any]]
    page: int
    total_pages: int
    total: int
    per_page: int


class UnitRow(BaseModel):
    code: str
    name: str
    total_tenders: int
    risk_score: int
    confidence: int = 0
    has_synergy: bool = False
    # {check_key: finding_count} for the checks that target this unit.
    check_counts: Dict[str, int] = {}


class UnitDetail(BaseModel):
    code: str
    name: str
    total_tenders: int
    risk: Optional[RiskScoreItem] = None
    # {check_key: [finding rows]} for the checks that target this unit.
    findings: Dict[str, List[Dict[str, Any]]] = {}


class CompanyDetail(BaseModel):
    cuit: str
    risk_score: Optional[RiskScoreItem]
    findings: Dict[str, List[Dict[str, Any]]]


class AuthorizerRow(BaseModel):
    authorizer: str
    risk_score: int
    confidence: int = 0
    has_synergy: bool = False
    # {check_key: finding_count} for the checks that target this authorizer.
    check_counts: Dict[str, int] = {}


class AuthorizerDetail(BaseModel):
    authorizer: str
    risk: Optional[RiskScoreItem] = None
    # {check_key: [finding rows]} for the checks that target this authorizer.
    findings: Dict[str, List[Dict[str, Any]]] = {}
