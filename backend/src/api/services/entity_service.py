"""
src/api/services/entity_service.py - Ranked views over the non-provider entity
namespaces (contracting units, authorizers).

Shared by the /api/units and /api/authorizers routers and the MCP server. The
score comes from the smart-scoring risk_scores rows of the namespace; entities
that only appear in findings fall back to the sum of their checks' weights.
"""

from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from . import detection_service
from .detection_context import DetectionContext


def fallback_score(info: dict, check_meta: dict) -> int:
    """Ad-hoc score (sum of weights) when no smart score exists for an entity."""
    return sum(
        check_meta.get(key, {}).get("weight", 0)
        for key, rows in info.get("findings", {}).items()
        if rows
    )


def check_counts(info: dict) -> dict:
    """Map {check_key: finding_count} for an indexed entity."""
    return {key: len(rows) for key, rows in info.get("findings", {}).items() if rows}


def entity_scores(db: Session, run_id: int, entity_type: str) -> Dict[str, dict]:
    """Map {entity_id: smart-score dict} for one namespace of a run."""
    return {
        s["cuit"]: s
        for s in detection_service.get_risk_scores_for_run(db, run_id, entity_type=entity_type)
    }


def rank_entities(db: Session, ctx: DetectionContext, entity_type: str) -> List[Dict[str, Any]]:
    """
    Every indexed entity of the namespace as {id, name, total_tenders,
    risk_score, confidence, has_synergy, check_counts}, highest risk first.
    """
    scores = entity_scores(db, ctx.run.id, entity_type)
    rows = []
    for ent_id, info in ctx.entity_index(entity_type).items():
        smart = scores.get(ent_id)
        rows.append({
            "id": ent_id,
            "name": info["name"],
            "total_tenders": info.get("total_tenders", 0),
            "risk_score": smart["score"] if smart else fallback_score(info, ctx.check_meta),
            "confidence": smart.get("confidence", 0) if smart else 0,
            "has_synergy": bool(smart and (smart.get("evidence_breakdown") or {}).get("multiplier", 1) > 1),
            "check_counts": check_counts(info),
        })
    rows.sort(key=lambda r: r["risk_score"], reverse=True)
    return rows
