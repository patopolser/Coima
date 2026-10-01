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
from ..services.detection_context import load_detection_context

router = APIRouter(prefix="/api/companies", tags=["companies"])


@router.get("/{cuit}", response_model=CompanyDetail)
def get_company(cuit: str, db: Session = Depends(db_session), locale: str = Depends(get_locale)):
    """
    Return the risk score and all detection findings associated with a CUIT.
    O(1) lookup after the first request of each detection run, courtesy of the
    in-memory index cache.
    """
    ctx = load_detection_context(db, locale)
    if ctx is None:
        raise HTTPException(status_code=404, detail=t("errors.no_detection_run", locale))

    data = ctx.company_index.get(cuit)
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
