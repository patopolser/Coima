"""
src/api/routers/risk_scores.py - Risk score listing endpoints.

GET /api/risk-scores       paginated, filterable list of company risk scores.
GET /api/risk-scores/flags distinct flag keys present in the latest run.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..dependencies import db_session
from ..schemas.detection import RiskScoreItem
from ..schemas.common import PaginatedResponse
from ..services import detection_service
from ..services.scoring_service import paginate

router = APIRouter(prefix="/api/risk-scores", tags=["risk-scores"])


@router.get("", response_model=PaginatedResponse[RiskScoreItem])
def list_risk_scores(
    db: Session = Depends(db_session),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
    min_score: int = Query(0, ge=0, le=100),
    max_score: int = Query(100, ge=0, le=100),
    flag: Optional[str] = Query(None),
    sort: str = Query("score"),
    dir: str = Query("desc"),
):
    """
    Return paginated risk scores from the latest detection run.

    Supports filtering by company name or CUIT, by score range, and by flag
    presence. Sorting is allowed on score, cuit or company. Flags are exposed
    as a list to the schema, then joined into a CSV for legacy compatibility
    with RiskScoreItem.
    """
    scores = detection_service.get_risk_scores_for_run(db)

    if search:
        sl = search.lower()
        scores = [s for s in scores if sl in s["cuit"].lower() or sl in (s["company"] or "").lower()]
    if min_score > 0:
        scores = [s for s in scores if s["score"] >= min_score]
    if max_score < 100:
        scores = [s for s in scores if s["score"] <= max_score]
    if flag:
        # Exact membership against a list avoids the substring false positives
        # the old CSV-based filter had (e.g. "bid" matching "bid_rotation_ring").
        scores = [s for s in scores if flag in (s["flags"] or [])]

    valid_sorts = {"score", "cuit", "company"}
    if sort in valid_sorts:
        reverse = dir == "desc"
        scores = sorted(scores, key=lambda x: (x.get(sort) is None, x.get(sort, "")), reverse=reverse)

    for s in scores:
        if isinstance(s["flags"], list):
            s["flags"] = ", ".join(s["flags"])

    items, page, total_pages, total = paginate(scores, page, per_page)

    return PaginatedResponse(
        items=items,
        page=page,
        total_pages=total_pages,
        total=total,
        per_page=per_page,
    )


@router.get("/flags", response_model=List[str])
def list_all_flags(db: Session = Depends(db_session)):
    """Return all distinct flag keys present in the latest run's risk scores."""
    scores = detection_service.get_risk_scores_for_run(db)
    flags = sorted(set(
        f
        for s in scores
        for f in (s["flags"] if isinstance(s["flags"], list) else [])
        if f
    ))
    return flags
