"""
src/api/routers/authorizers.py - Authorizer endpoints.

GET /api/authorizers           paginated list with risk scores.
GET /api/authorizers/{name}    detail for a specific authorizer.

Authorizers are an entity namespace in the smart scoring layer: the score,
confidence and evidence breakdown come from risk_scores rows with
entity_type='authorizer'. The per-check findings shown alongside are derived
from the checks' Authorizer-typed columns (see
scoring_service.build_entity_index); nothing here is hardcoded per check.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.i18n.translator import t

from ..dependencies import db_session
from ..locale import get_locale
from ..schemas.detection import AuthorizerDetail, AuthorizerRow
from ..schemas.common import PaginatedResponse
from ..services.detection_context import load_detection_context
from ..services.entity_service import entity_scores, rank_entities
from ..services.scoring_service import paginate

router = APIRouter(prefix="/api/authorizers", tags=["authorizers"])


@router.get("", response_model=PaginatedResponse[AuthorizerRow])
def list_authorizers(
    db: Session = Depends(db_session),
    locale: str = Depends(get_locale),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
):
    ctx = load_detection_context(db, locale)
    if ctx is None:
        return PaginatedResponse(items=[], page=1, total_pages=1, total=0, per_page=per_page)

    rows = [
        AuthorizerRow(
            authorizer=r["id"],
            risk_score=r["risk_score"],
            confidence=r["confidence"],
            has_synergy=r["has_synergy"],
            check_counts=r["check_counts"],
        )
        for r in rank_entities(db, ctx, "authorizer")
    ]

    if search:
        sl = search.lower()
        rows = [a for a in rows if sl in a.authorizer.lower()]

    items, page, total_pages, total = paginate(rows, page, per_page)
    return PaginatedResponse(items=items, page=page, total_pages=total_pages, total=total, per_page=per_page)


@router.get("/{name:path}", response_model=AuthorizerDetail)
def get_authorizer(name: str, db: Session = Depends(db_session), locale: str = Depends(get_locale)):
    ctx = load_detection_context(db, locale)
    if ctx is None:
        raise HTTPException(status_code=404, detail=t("errors.no_detection_run", locale))

    info = ctx.entity_index("authorizer").get(name)
    if info is None:
        raise HTTPException(status_code=404, detail=t("errors.authorizer_not_found", locale, name=name))

    return AuthorizerDetail(
        authorizer=name,
        risk=entity_scores(db, ctx.run.id, "authorizer").get(name),
        findings={k: list(v) for k, v in info.get("findings", {}).items()},
    )
