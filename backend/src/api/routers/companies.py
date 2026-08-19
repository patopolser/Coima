"""
src/api/routers/companies.py - Company profile endpoint.

GET /api/companies/{cuit}   risk score plus grouped findings for a company.

Uses the run-scoped in-memory index cache so the full findings dataset is
deserialised and indexed once per detection run, not once per request.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.i18n.translator import t

from ..dependencies import db_session
from ..locale import get_locale
from ..schemas.detection import CompanyDetail
from ..services import detection_service
from ..services.config_service import get_detection_config
from ..services.scoring_service import build_check_meta, get_company_index, merge_legacy_meta

router = APIRouter(prefix="/api/companies", tags=["companies"])


@router.get("/{cuit}", response_model=CompanyDetail)
def get_company(cuit: str, db: Session = Depends(db_session), locale: str = Depends(get_locale)):
    """
    Return the risk score and all detection findings associated with a CUIT.
    O(1) lookup after the first request of each detection run, courtesy of the
    in-memory index cache.
    """
    cfg = get_detection_config(db)
    weight_cfg = cfg.get("weights", {})
    check_meta = build_check_meta(weight_cfg, locale=locale)

    run = detection_service._get_latest_done_run(db)
    if run is None:
        raise HTTPException(status_code=404, detail=t("errors.no_detection_run", locale))

    findings = detection_service.get_findings_for_run(db, run.id)
    risk_scores = detection_service.get_risk_scores_for_run(db, run.id)
    check_meta = merge_legacy_meta(check_meta, findings, weight_cfg, locale=locale)

    company_index = get_company_index(run.id, findings, risk_scores, check_meta)

    data = company_index.get(cuit)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail=t("errors.company_not_found", locale, cuit=cuit),
        )

    return CompanyDetail(
        cuit=cuit,
        risk_score=data["risk_score"],
        findings={k: list(v) for k, v in data["findings"].items()},
    )
