"""
src/api/routers/detection.py - Detection trigger and metadata endpoints.

POST /api/detection/run     trigger a detection run (blocking, cache-aware).
GET  /api/detection/latest  fetch metadata for the latest completed run.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.i18n.translator import t

from ..dependencies import db_session, neo4j_driver, settings
from ..locale import get_locale
from ..security import trigger_cooldown
from ..services import detection_service

router = APIRouter(prefix="/api/detection", tags=["detection"])


def _parse_date(value: Optional[str], field: str) -> Optional[str]:
    """Validate an optional ISO date (YYYY-MM-DD); raise 400 on a bad value."""
    if not value:
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"{field} must be an ISO date (YYYY-MM-DD)"
        )
    return value


# Triggering a run is expensive (heavy Neo4j queries), so it is rate-limited
# by a cooldown; GET /latest stays unthrottled for the read-only pages.
@router.post("/run", dependencies=[Depends(trigger_cooldown("detection"))])
def run_detection(
    force: bool = False,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(db_session),
    driver=Depends(neo4j_driver),
    cfg=Depends(settings),
):
    """
    Trigger the detection pipeline. Returns cached results when fewer than
    `detection_cache_min_new_tenders` new Process nodes have been ingested
    since the last run; pass `?force=true` to bypass the cache. Passing
    `?date_from=YYYY-MM-DD` and/or `?date_to=YYYY-MM-DD` restricts the run to
    processes opened inside that window and always executes fresh. The
    response is returned only after the run completes.
    """
    df = _parse_date(date_from, "date_from")
    dt = _parse_date(date_to, "date_to")
    if df and dt and df > dt:
        raise HTTPException(status_code=400, detail="date_from must not be after date_to")
    try:
        result = detection_service.run_if_needed(
            db=db, driver=driver, settings=cfg, force=force, date_from=df, date_to=dt
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/latest")
def get_latest(db: Session = Depends(db_session), locale: str = Depends(get_locale)):
    """Return metadata of the most recent successfully completed detection run."""
    run = detection_service.get_latest_run(db)
    if run is None:
        raise HTTPException(status_code=404, detail=t("errors.no_completed_run", locale))
    return run
