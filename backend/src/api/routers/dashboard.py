"""
src/api/routers/dashboard.py - Dashboard stats endpoint.

GET /api/dashboard/stats   pre-computed stats for the frontend dashboard.

Returns every aggregation the Dashboard page needs in one request so the
frontend does not have to fetch thousands of rows and recompute them
client-side.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..dependencies import db_session, neo4j_driver
from ..locale import get_locale
from ..services import detection_service
from ..services.config_service import get_detection_config
from ..services.scoring_service import build_check_meta, compute_dashboard_stats, merge_legacy_meta

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _count_processes(driver) -> int:
    """Total Process nodes in the graph, independent of any detection run."""
    try:
        with driver.session() as session:
            rec = session.run("MATCH (p:Process) RETURN count(p) AS total").single()
            return rec["total"] if rec else 0
    except Exception:
        return 0


@router.get("/stats")
def get_dashboard_stats(
    db: Session = Depends(db_session),
    locale: str = Depends(get_locale),
    driver=Depends(neo4j_driver),
):
    """
    Return pre-aggregated dashboard statistics from the latest detection run.

    Response shape:
        total_entities      providers scored in the latest run
        total_findings
        units_scored        contracting units with unit-level findings
        total_processes     Process nodes in the graph (run-independent)
        last_run_at         ISO timestamp or null
        distribution        [{bucket, count}, ...] across 5 score buckets
        top_entities        top 10 [{cuit, company, score, flags}, ...]
        findings_by_vector  [{check, label, count, weight}, ...]
        flag_cooccurrence   top 15 [{flag, label, count}, ...]
    """
    cfg = get_detection_config(db)
    weight_cfg = cfg.get("weights", {})
    check_meta = build_check_meta(weight_cfg, locale=locale)

    run = detection_service._get_latest_done_run(db)
    if run is None:
        return {
            "total_entities": 0,
            "total_findings": 0,
            "units_scored": 0,
            "total_processes": _count_processes(driver),
            "last_run_at": None,
            "distribution": [],
            "top_entities": [],
            "findings_by_vector": [],
            "flag_cooccurrence": [],
        }

    risk_scores = detection_service.get_risk_scores_for_run(db, run.id)
    findings = detection_service.get_findings_for_run(db, run.id)
    check_meta = merge_legacy_meta(check_meta, findings, weight_cfg, locale=locale)

    stats = compute_dashboard_stats(risk_scores, findings, check_meta)
    stats["total_processes"] = _count_processes(driver)
    stats["tender_count"] = run.tender_count or 0
    stats["last_run_at"] = (
        run.created_at.isoformat() if hasattr(run.created_at, "isoformat") else str(run.created_at)
    )
    return stats
