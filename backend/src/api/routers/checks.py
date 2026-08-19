"""
src/api/routers/checks.py - Check listing and per-check detail endpoints.

GET /api/checks         list every check with metadata and finding counts.
GET /api/checks/{key}   paginated findings for one check, with search and sort.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.i18n.translator import t

from ..dependencies import db_session
from ..locale import get_locale
from ..schemas.detection import CheckMeta, CheckDetail
from ..services import detection_service
from ..services.config_service import get_detection_config
from ..services.scoring_service import build_check_meta, filter_rows, paginate, merge_legacy_meta

router = APIRouter(prefix="/api/checks", tags=["checks"])


def _get_check_meta_and_findings(db: Session, locale: str = "en"):
    cfg = get_detection_config(db)
    weight_cfg = cfg.get("weights", {})
    check_meta = build_check_meta(weight_cfg, locale=locale)
    findings = detection_service.get_findings_for_run(db)
    check_meta = merge_legacy_meta(check_meta, findings, weight_cfg, locale=locale)
    return check_meta, findings


@router.get("", response_model=List[CheckMeta])
def list_checks(db: Session = Depends(db_session), locale: str = Depends(get_locale)):
    """
    Return metadata for all registered checks together with the finding count
    from the latest detection run.
    """
    check_meta, findings = _get_check_meta_and_findings(db, locale)
    result = []
    for key, meta in check_meta.items():
        rows = findings.get(key, [])
        result.append(CheckMeta(
            key=key,
            total_findings=len(rows),
            **meta,
        ))
    return result


@router.get("/{key}", response_model=CheckDetail)
def get_check(
    key: str,
    db: Session = Depends(db_session),
    locale: str = Depends(get_locale),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
    dir: str = Query("asc"),
):
    """
    Return paginated findings for a specific check key.

    Search runs against the `search_fields` declared in the check's ui_meta;
    sort accepts any column key the check exposes.
    """
    check_meta, findings = _get_check_meta_and_findings(db, locale)

    if key not in check_meta:
        raise HTTPException(
            status_code=404,
            detail=t("errors.check_not_found", locale, key=key),
        )

    meta = check_meta[key]
    rows = findings.get(key, [])

    filtered = filter_rows(rows, search, meta["search_fields"])

    valid_cols = set()
    if meta.get("columns"):
        if isinstance(meta["columns"][0], dict):
            valid_cols = {col["key"] for col in meta["columns"]}
        else:
            valid_cols = {col_key for col_key, _ in meta["columns"]}

    if sort and sort in valid_cols:
        reverse = dir == "desc"
        filtered = sorted(
            filtered,
            key=lambda x: (x.get(sort) is None, x.get(sort, "")),
            reverse=reverse,
        )

    items, page, total_pages, total = paginate(filtered, page, per_page)

    return CheckDetail(
        key=key,
        total_findings=len(rows),
        items=items,
        page=page,
        total_pages=total_pages,
        total=total,
        per_page=per_page,
        **meta,
    )
