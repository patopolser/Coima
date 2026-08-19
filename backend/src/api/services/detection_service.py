"""
src/api/services/detection_service.py - Detection orchestration with SQLite caching.

Flow for POST /api/detection/run:
  1. Count Process nodes in Neo4j -> tender_count_now.
  2. Load the latest completed run from SQLite.
  3. If the new-tender delta is below the configured threshold AND force is
     false, return the cached run.
  4. Otherwise run all checks, persist findings and risk scores, and return
     the fresh results.

Flags are stored as JSON arrays. Legacy comma-separated string flags are
migrated transparently on read.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from neo4j import Driver
from sqlalchemy.orm import Session

from src.detector.runner import run_detection
from src.detector.scoring import build_all_scores
from src.detector.analytics import compute_cobid_centrality

from ..database.neo4j import count_processes
from ..database.sqlite import DetectionFinding, DetectionRun, RiskScore
from ..config import Settings
from .config_service import get_detection_config
from .scoring_service import invalidate_index_cache

logger = logging.getLogger(__name__)


def _normalize_flags(raw: str | list | None) -> list:
    """Return flags as a list regardless of whether they are stored as JSON or CSV."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return [f.strip() for f in raw.split(",") if f.strip()]


def _serialize_score(s: RiskScore) -> dict:
    """Serialise a RiskScore row, including the smart-scoring fields."""
    try:
        breakdown = json.loads(s.evidence_breakdown) if s.evidence_breakdown else None
    except (json.JSONDecodeError, TypeError):
        breakdown = None
    return {
        "cuit": s.cuit,
        "company": s.company,
        "score": s.score,
        "flags": _normalize_flags(s.flags),
        "entity_type": getattr(s, "entity_type", "provider") or "provider",
        "base_score": getattr(s, "base_score", None) if getattr(s, "base_score", None) is not None else s.score,
        "confidence": getattr(s, "confidence", 0) or 0,
        "evidence_breakdown": breakdown,
    }


def _get_latest_done_run(db: Session) -> Optional[DetectionRun]:
    return (
        db.query(DetectionRun)
        .filter(DetectionRun.status == "done")
        .order_by(DetectionRun.id.desc())
        .first()
    )


def _mark_stale_runs(db: Session) -> None:
    """Mark any stuck 'running' runs as 'error' (typically left over from a crash)."""
    db.query(DetectionRun).filter(DetectionRun.status == "running").update(
        {"status": "error"}
    )
    db.commit()


def _serialize_run(run: DetectionRun, db: Session) -> dict:
    """Build the JSON-serialisable response dict from a DetectionRun and its risk scores."""
    # Provider scores only: the API and dashboard are provider-centric. Unit
    # and authorizer scores share the table via entity_type and are read
    # through get_risk_scores_for_run(entity_type=...).
    risk_scores = (
        db.query(RiskScore)
        .filter(RiskScore.run_id == run.id, RiskScore.entity_type == "provider")
        .order_by(RiskScore.score.desc())
        .all()
    )
    summary = json.loads(run.summary or "{}")
    return {
        "id": run.id,
        "created_at": run.created_at.isoformat() if isinstance(run.created_at, datetime) else str(run.created_at),
        "tender_count": run.tender_count,
        "summary": summary,
        "status": run.status,
        "risk_scores": [_serialize_score(rs) for rs in risk_scores],
    }


def _run_is_windowed(run: Optional[DetectionRun]) -> bool:
    """True if a stored run was executed with an active date window."""
    if run is None:
        return False
    try:
        snap = json.loads(run.config_snapshot or "{}")
    except (json.JSONDecodeError, TypeError):
        return False
    dr = snap.get("date_range") or {}
    return bool(dr.get("from") or dr.get("to"))


def run_if_needed(
    db: Session,
    driver: Driver,
    settings: Settings,
    force: bool = False,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> dict:
    """
    Core detection entry point. Returns cached results when tender growth is
    below the threshold (unless `force=True`), otherwise runs all checks,
    persists findings and scores, and returns fresh results.

    `date_from`/`date_to` (ISO YYYY-MM-DD, either optional) restrict the run
    to processes opened inside the window. A windowed run always executes
    fresh; it is never served from, nor used as, the unwindowed cache, since
    its findings only cover part of the data.
    """
    cfg = get_detection_config(db)
    if date_from or date_to:
        cfg["date_range"] = {"from": date_from, "to": date_to}
    windowed = bool(date_from or date_to)
    tender_count_now = count_processes(driver)

    latest = _get_latest_done_run(db)

    # Skip the cache entirely for windowed runs, and never serve a windowed
    # run as the cache answer to an unwindowed request.
    if not force and not windowed and latest is not None and not _run_is_windowed(latest):
        diff = tender_count_now - (latest.tender_count or 0)
        if diff < settings.detection_cache_min_new_tenders:
            logger.info(
                "Detection cache hit: %d new tenders (threshold=%d)",
                diff,
                settings.detection_cache_min_new_tenders,
            )
            result = _serialize_run(latest, db)
            result["cached"] = True
            return result

    _mark_stale_runs(db)

    run = DetectionRun(
        tender_count=tender_count_now,
        config_snapshot=json.dumps(cfg, default=str),
        status="running",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        logger.info("Starting detection run #%d (tender_count=%d)", run.id, tender_count_now)

        limit = cfg.get("connection", {}).get("limit", settings.neo4j_limit)
        findings: dict = run_detection(driver, cfg, limit)

        # Co-bid centrality is recorded on provider scores as an explanatory
        # feature (broker position in the bidding network). Never fatal to a
        # detection run.
        try:
            features = compute_cobid_centrality(driver)
        except Exception as exc:
            logger.warning("Centrality features unavailable: %s", exc)
            features = {}

        risk_scores: list = build_all_scores(findings, cfg, features=features)

        for check_key, rows in findings.items():
            db.add(
                DetectionFinding(
                    run_id=run.id,
                    check_key=check_key,
                    data=json.dumps(rows, ensure_ascii=False, default=str),
                )
            )

        for rs in risk_scores:
            raw_flags = rs.get("flags", [])
            flags_json = json.dumps(raw_flags) if isinstance(raw_flags, list) else raw_flags
            breakdown = rs.get("evidence_breakdown")
            db.add(
                RiskScore(
                    run_id=run.id,
                    cuit=rs["cuit"],
                    company=rs.get("company", ""),
                    score=rs["score"],
                    flags=flags_json,
                    entity_type=rs.get("entity_type", "provider"),
                    base_score=rs.get("base_score", rs["score"]),
                    confidence=rs.get("confidence", 0),
                    evidence_breakdown=json.dumps(breakdown, ensure_ascii=False) if breakdown is not None else None,
                )
            )

        summary = {k: len(v) for k, v in findings.items()}
        run.summary = json.dumps(summary)
        run.status = "done"
        db.commit()
        db.refresh(run)

        invalidate_index_cache()

        logger.info("Detection run #%d completed. %d companies flagged", run.id, len(risk_scores))

    except Exception as exc:
        logger.exception("Detection run #%d failed: %s", run.id, exc)
        run.status = "error"
        db.commit()
        raise

    result = _serialize_run(run, db)
    result["cached"] = False
    return result


def get_latest_run(db: Session) -> Optional[dict]:
    """Return the most recent completed run's metadata (without the risk scores list)."""
    run = _get_latest_done_run(db)
    if run is None:
        return None
    summary = json.loads(run.summary or "{}")
    return {
        "id": run.id,
        "created_at": run.created_at.isoformat() if isinstance(run.created_at, datetime) else str(run.created_at),
        "tender_count": run.tender_count,
        "summary": summary,
        "status": run.status,
    }


def get_findings_for_run(db: Session, run_id: Optional[int] = None) -> dict:
    """Return {check_key: [rows]} for a given run (or the latest done run)."""
    if run_id is None:
        run = _get_latest_done_run(db)
        if run is None:
            return {}
        run_id = run.id

    rows = (
        db.query(DetectionFinding)
        .filter(DetectionFinding.run_id == run_id)
        .all()
    )
    return {r.check_key: json.loads(r.data) for r in rows}


def get_risk_scores_for_run(
    db: Session,
    run_id: Optional[int] = None,
    entity_type: Optional[str] = "provider",
) -> list:
    """
    Return risk-score dicts for a run (or the latest done run), sorted by
    score desc. Flags are always returned as a list, migrating legacy CSV
    strings transparently.

    `entity_type` defaults to "provider" (the existing provider-centric
    behaviour); pass "unit" or "authorizer" for those namespaces, or None for
    all entities.
    """
    if run_id is None:
        run = _get_latest_done_run(db)
        if run is None:
            return []
        run_id = run.id

    query = db.query(RiskScore).filter(RiskScore.run_id == run_id)
    if entity_type is not None:
        query = query.filter(RiskScore.entity_type == entity_type)
    scores = (
        query
        .order_by(RiskScore.score.desc())
        .all()
    )
    return [_serialize_score(s) for s in scores]
