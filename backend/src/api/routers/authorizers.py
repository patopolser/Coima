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
from ..services import detection_service
from ..services.config_service import get_detection_config
from ..services.scoring_service import build_check_meta, get_entity_index, paginate

router = APIRouter(prefix="/api/authorizers", tags=["authorizers"])


def _fallback_score(info: dict, check_meta: dict) -> int:
    """Ad-hoc score (sum of weights) when no smart score exists."""
    return sum(
        check_meta.get(key, {}).get("weight", 0)
        for key, rows in info.get("findings", {}).items()
        if rows
    )


def _check_counts(info: dict) -> dict:
    """Map {check_key: finding_count} for an indexed authorizer."""
    return {key: len(rows) for key, rows in info.get("findings", {}).items() if rows}


def _get_run_and_index(db: Session, check_meta: dict):
    """Fetch the latest run and return its cached authorizer index."""
    run = detection_service._get_latest_done_run(db)
    if run is None:
        return None, {}
    findings = detection_service.get_findings_for_run(db, run.id)
    index = get_entity_index(run.id, findings, check_meta, "authorizer")
    return run, index


def _authorizer_scores(db: Session, run_id: int) -> dict:
    return {
        s["cuit"]: s
        for s in detection_service.get_risk_scores_for_run(db, run_id, entity_type="authorizer")
    }


@router.get("", response_model=PaginatedResponse[AuthorizerRow])
def list_authorizers(
    db: Session = Depends(db_session),
    locale: str = Depends(get_locale),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
):
    cfg = get_detection_config(db)
    check_meta = build_check_meta(cfg.get("weights", {}), locale=locale)
    run, index = _get_run_and_index(db, check_meta)
    if run is None:
        return PaginatedResponse(items=[], page=1, total_pages=1, total=0, per_page=per_page)

    scores = _authorizer_scores(db, run.id)

    rows = []
    for name, info in index.items():
        smart = scores.get(name)
        risk_score = smart["score"] if smart else _fallback_score(info, check_meta)
        has_synergy = bool(smart and (smart.get("evidence_breakdown") or {}).get("multiplier", 1) > 1)
        rows.append(AuthorizerRow(
            authorizer=name,
            risk_score=risk_score,
            confidence=smart.get("confidence", 0) if smart else 0,
            has_synergy=has_synergy,
            check_counts=_check_counts(info),
        ))

    rows.sort(key=lambda x: x.risk_score, reverse=True)

    if search:
        sl = search.lower()
        rows = [a for a in rows if sl in a.authorizer.lower()]

    items, page, total_pages, total = paginate(rows, page, per_page)
    return PaginatedResponse(items=items, page=page, total_pages=total_pages, total=total, per_page=per_page)


@router.get("/{name:path}", response_model=AuthorizerDetail)
def get_authorizer(name: str, db: Session = Depends(db_session), locale: str = Depends(get_locale)):
    cfg = get_detection_config(db)
    check_meta = build_check_meta(cfg.get("weights", {}), locale=locale)
    run, index = _get_run_and_index(db, check_meta)
    if run is None:
        raise HTTPException(status_code=404, detail=t("errors.no_detection_run", locale))

    info = index.get(name)
    if info is None:
        raise HTTPException(status_code=404, detail=t("errors.authorizer_not_found", locale, name=name))

    risk = _authorizer_scores(db, run.id).get(name)

    return AuthorizerDetail(
        authorizer=name,
        risk=risk,
        findings={k: list(v) for k, v in info.get("findings", {}).items()},
    )
