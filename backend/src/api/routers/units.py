"""
src/api/routers/units.py - Contracting unit endpoints.

GET /api/units          paginated list of contracting units with risk scores.
GET /api/units/{code}   detail for a specific contracting unit.

Uses the run-scoped in-memory index cache so the full findings dataset is
deserialised and indexed once per detection run, not once per request. Which
checks belong to a unit is derived from the checks' Unit-typed columns (see
scoring_service.build_entity_index); nothing here is hardcoded per check.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.i18n.translator import t

from ..dependencies import db_session
from ..locale import get_locale
from ..schemas.detection import UnitDetail, UnitRow
from ..schemas.common import PaginatedResponse
from ..services.detection_context import load_detection_context
from ..services.entity_service import entity_scores, rank_entities
from ..services.scoring_service import paginate

router = APIRouter(prefix="/api/units", tags=["units"])


@router.get("", response_model=PaginatedResponse[UnitRow])
def list_units(
    db: Session = Depends(db_session),
    locale: str = Depends(get_locale),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
):
    ctx = load_detection_context(db, locale)
    ranked = rank_entities(db, ctx, "unit") if ctx else []
    rows = [
        UnitRow(code=r["id"], **{k: v for k, v in r.items() if k != "id"})
        for r in ranked
    ]

    if search:
        sl = search.lower()
        rows = [u for u in rows if sl in u.code.lower() or sl in u.name.lower()]

    items, page, total_pages, total = paginate(rows, page, per_page)
    return PaginatedResponse(items=items, page=page, total_pages=total_pages, total=total, per_page=per_page)


@router.get("/{code:path}", response_model=UnitDetail)
def get_unit(code: str, db: Session = Depends(db_session), locale: str = Depends(get_locale)):
    ctx = load_detection_context(db, locale)
    info = ctx.entity_index("unit").get(code) if ctx else None
    if info is None:
        raise HTTPException(
            status_code=404,
            detail=t("errors.unit_not_found", locale, code=code),
        )

    return UnitDetail(
        code=code,
        name=info["name"],
        total_tenders=info.get("total_tenders", 0),
        risk=entity_scores(db, ctx.run.id, "unit").get(code),
        findings={k: list(v) for k, v in info.get("findings", {}).items()},
    )
