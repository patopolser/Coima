"""
src/api/services/detection_context.py - Everything derived from the latest
finished detection run, loaded in one place.

Company/unit/authorizer endpoints and the MCP server all need the same bundle:
the run, its findings, its provider risk scores, the localized check metadata
and the run-scoped indexes. This module builds that bundle once per call and
keeps the deserialized findings/scores of the current run in memory (a done
run never changes), so repeated lookups skip the JSON decode of every finding.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..database.sqlite import DetectionRun
from . import detection_service
from .config_service import get_detection_config
from .scoring_service import build_check_meta, get_company_index, get_entity_index, merge_legacy_meta


@dataclass
class DetectionContext:
    run: DetectionRun
    findings: Dict[str, List[Dict[str, Any]]]
    risk_scores: List[Dict[str, Any]]
    check_meta: Dict[str, Dict]
    company_index: Dict[str, Dict]

    def entity_index(self, entity_type: str) -> Dict[str, Dict]:
        """Run-scoped index for a non-provider namespace ('unit', 'authorizer')."""
        return get_entity_index(self.run.id, self.findings, self.check_meta, entity_type)


@dataclass
class _RunData:
    run_id: int
    findings: Dict[str, List[Dict[str, Any]]]
    risk_scores: List[Dict[str, Any]]


_run_data: Optional[_RunData] = None
_lock = threading.Lock()


def _load_run_data(db: Session, run_id: int) -> _RunData:
    global _run_data
    with _lock:
        if _run_data is None or _run_data.run_id != run_id:
            _run_data = _RunData(
                run_id=run_id,
                findings=detection_service.get_findings_for_run(db, run_id),
                risk_scores=detection_service.get_risk_scores_for_run(db, run_id),
            )
        return _run_data


def reset_cache() -> None:
    """Drop the cached run data (tests, or after swapping the SQLite file)."""
    global _run_data
    with _lock:
        _run_data = None


def load_check_meta(db: Session, locale: str, findings: Optional[dict] = None) -> Dict[str, Dict]:
    """Localized check metadata with weight overrides, plus legacy checks found in `findings`."""
    weight_cfg = get_detection_config(db).get("weights", {})
    check_meta = build_check_meta(weight_cfg, locale=locale)
    if findings is not None:
        check_meta = merge_legacy_meta(check_meta, findings, weight_cfg, locale=locale)
    return check_meta


def load_detection_context(db: Session, locale: str = "en") -> Optional[DetectionContext]:
    """Return the context of the latest finished run, or None when there is no run yet."""
    run = detection_service._get_latest_done_run(db)
    if run is None:
        return None
    data = _load_run_data(db, run.id)
    check_meta = load_check_meta(db, locale, data.findings)
    return DetectionContext(
        run=run,
        findings=data.findings,
        risk_scores=data.risk_scores,
        check_meta=check_meta,
        company_index=get_company_index(run.id, data.findings, data.risk_scores, check_meta),
    )
