"""
src/api/routers/config_router.py - Detection config endpoints.

GET /api/config   return the active config plus the registered-check catalog.
PUT /api/config   merge checks/thresholds/weights into the stored overrides.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.detector.checks import get_all_checks

from ..dependencies import db_session
from ..locale import get_locale
from ..services.config_service import get_detection_config, save_detection_config

router = APIRouter(prefix="/api/config", tags=["config"])


def _build_available_checks(all_checks, cfg: dict, locale: str) -> list:
    checks_cfg = cfg.get("checks", {})
    weights_cfg = cfg.get("weights", {})
    loc = locale if locale in ("en", "es") else "en"

    result = []
    for c in all_checks:
        key = c["key"]
        tr = c.get("i18n", {}).get(loc, {}) if loc != "en" else {}
        result.append({
            "key":              key,
            "label":            tr.get("label") or c["label"],
            "default_weight":   c.get("weight", 10),
            "color":            c.get("ui_meta", {}).get("color", "slate"),
            "description":      tr.get("description") or c.get("ui_meta", {}).get("description", ""),
            "enabled":          checks_cfg.get(key, True),
            "weight":           weights_cfg.get(key, c.get("weight", 10)),
            "check_thresholds": c.get("thresholds", {}),
        })
    return result


@router.get("")
def read_config(db: Session = Depends(db_session), locale: str = Depends(get_locale)):
    """
    Return the active detection config plus a list of all registered checks
    with their default weights, so the frontend can build the configuration
    UI.
    """
    cfg = get_detection_config(db)
    available_checks = _build_available_checks(get_all_checks(), cfg, locale)

    return {
        "checks":           cfg.get("checks", {}),
        "thresholds":       cfg.get("thresholds", {}),
        "weights":          cfg.get("weights", {}),
        "available_checks": available_checks,
    }


@router.put("")
def update_config(body: dict, db: Session = Depends(db_session), locale: str = Depends(get_locale)):
    """
    Merge the supplied checks/thresholds/weights into the stored config and
    return the full updated config (same shape as GET). Only those three
    editable sections are touched; connection settings are preserved.
    """
    updated = save_detection_config(db, body)
    available_checks = _build_available_checks(get_all_checks(), updated, locale)

    return {
        "checks":           updated.get("checks", {}),
        "thresholds":       updated.get("thresholds", {}),
        "weights":          updated.get("weights", {}),
        "available_checks": available_checks,
    }
