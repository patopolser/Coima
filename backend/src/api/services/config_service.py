"""
src/api/services/config_service.py - Persistent detection configuration in SQLite.

The defaults for every config section are derived entirely from the
registered checks (their `.py` files), never from a hand-written config.json.
This keeps checks fully modular: dropping a `.py` file into checks/ makes its
toggle, weight and thresholds appear automatically; deleting it removes them.

The SQLite row only holds *user overrides*. The effective config returned to
the detector and the API is:

    effective = registry_defaults  <- overridden by ->  stored_overrides

So a newly added check is always present with its declared defaults even if
the stored row predates it, and no manual seeding step is required.

Each check declares its defaults in its CHECK dict:
    "weight":     int                   default risk weight
    "thresholds": {name: value, ...}    default query thresholds (optional)
Enabled defaults to True for every registered check.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from src.detector.checks import get_all_checks

logger = logging.getLogger(__name__)

_EDITABLE_SECTIONS = ("checks", "thresholds", "weights")


def registry_defaults() -> dict:
    """Build the full default config from the registered checks (no file needed)."""
    checks_cfg: dict = {}
    weights_cfg: dict = {}
    thresholds_cfg: dict = {}
    for c in get_all_checks():
        key = c["key"]
        checks_cfg[key] = True
        weights_cfg[key] = c.get("weight", 10)
        thresholds_cfg.update(c.get("thresholds", {}))
    return {"checks": checks_cfg, "weights": weights_cfg, "thresholds": thresholds_cfg}


def _stored_overrides(db: Session) -> dict:
    """Return the raw stored override blob, or {} if missing or corrupt."""
    from ..database.sqlite import DetectionConfig

    row = db.query(DetectionConfig).first()
    if row is None:
        return {}
    try:
        return json.loads(row.data)
    except json.JSONDecodeError:
        logger.warning("Corrupt DetectionConfig row. Ignoring overrides.")
        return {}


def get_detection_config(db: Session) -> dict:
    """
    Return the effective config: registry defaults overlaid with stored
    overrides. New checks appear automatically; removed checks disappear
    automatically.
    """
    cfg = registry_defaults()
    stored = _stored_overrides(db)

    for section in _EDITABLE_SECTIONS:
        override = stored.get(section)
        if isinstance(override, dict):
            cfg.setdefault(section, {}).update(override)

    # Preserve any non-editable sections a user may have stored (e.g. connection).
    for k, v in stored.items():
        if k not in _EDITABLE_SECTIONS:
            cfg[k] = v

    return cfg


def save_detection_config(db: Session, updates: dict) -> dict:
    """
    Merge `updates` (editable sections only) into the stored override blob
    and persist. Returns the full effective config (registry defaults plus
    overrides).
    """
    from ..database.sqlite import DetectionConfig

    stored = _stored_overrides(db)

    for section in _EDITABLE_SECTIONS:
        if section in updates and isinstance(updates[section], dict):
            stored.setdefault(section, {}).update(updates[section])

    blob = json.dumps(stored, ensure_ascii=False)
    row = db.query(DetectionConfig).first()
    if row is None:
        db.add(DetectionConfig(data=blob))
    else:
        row.data = blob
    db.commit()

    return get_detection_config(db)
