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
from ..services import detection_service
from ..services.config_service import get_detection_config
from ..services.scoring_service import build_check_meta, get_entity_index, paginate

router = APIRouter(prefix="/api/units", tags=["units"])


def _fallback_score(info: dict, check_meta: dict) -> int:
    """Ad-hoc score (sum of weights) when no smart score exists for a unit."""
    return sum(
        check_meta.get(key, {}).get("weight", 0)
        for key, rows in info.get("findings", {}).items()
        if rows
    )


def _check_counts(info: dict) -> dict:
    """Map {check_key: finding_count} for an indexed unit."""
    return {key: len(rows) for key, rows in info.get("findings", {}).items() if rows}


def _get_run_and_index(db: Session, check_meta: dict):
    """Fetch the latest run and return its cached unit index."""
    run = detection_service._get_latest_done_run(db)
    if run is None:
        return None, {}
    findings = detection_service.get_findings_for_run(db, run.id)
    unit_index = get_entity_index(run.id, findings, check_meta, "unit")
    return run, unit_index


def _unit_scores(db: Session, run_id: int) -> dict:
    """Map {unit_code: smart-score dict} from the unit-namespace risk scores."""
    return {
        s["cuit"]: s
        for s in detection_service.get_risk_scores_for_run(db, run_id, entity_type="unit")
    }


@router.get("", response_model=PaginatedResponse[UnitRow])
def list_units(
    db: Session = Depends(db_session),
    locale: str = Depends(get_locale),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
):
    cfg = get_detection_config(db)
    check_meta = build_check_meta(cfg.get("weights", {}), locale=locale)
    run, unit_index = _get_run_and_index(db, check_meta)
    scores = _unit_scores(db, run.id) if run else {}

    rows = []
    for code, info in unit_index.items():
        smart = scores.get(code)
        risk_score = smart["score"] if smart else _fallback_score(info, check_meta)
        has_synergy = bool(smart and (smart.get("evidence_breakdown") or {}).get("multiplier", 1) > 1)
        rows.append(UnitRow(
            code=code,
            name=info["name"],
            total_tenders=info.get("total_tenders", 0),
            risk_score=risk_score,
            confidence=smart.get("confidence", 0) if smart else 0,
            has_synergy=has_synergy,
            check_counts=_check_counts(info),
        ))

    rows.sort(key=lambda x: x.risk_score, reverse=True)

    if search:
        sl = search.lower()
        rows = [u for u in rows if sl in u.code.lower() or sl in u.name.lower()]

    items, page, total_pages, total = paginate(rows, page, per_page)
    return PaginatedResponse(items=items, page=page, total_pages=total_pages, total=total, per_page=per_page)


@router.get("/{code:path}", response_model=UnitDetail)
def get_unit(code: str, db: Session = Depends(db_session), locale: str = Depends(get_locale)):
    cfg = get_detection_config(db)
    check_meta = build_check_meta(cfg.get("weights", {}), locale=locale)
    run, unit_index = _get_run_and_index(db, check_meta)

    info = unit_index.get(code)
    if info is None:
        raise HTTPException(
            status_code=404,
            detail=t("errors.unit_not_found", locale, code=code),
        )

    risk = _unit_scores(db, run.id).get(code) if run else None

    return UnitDetail(
        code=code,
        name=info["name"],
        total_tenders=info.get("total_tenders", 0),
        risk=risk,
        findings={k: list(v) for k, v in info.get("findings", {}).items()},
    )
