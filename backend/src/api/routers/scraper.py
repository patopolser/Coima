"""
src/api/routers/scraper.py - Scraper control endpoints.

GET  /api/scraper/status                live scraper state (running, scraped count, last-run target).
POST /api/scraper/start                 request a scrape run (eventually consistent).
POST /api/scraper/stop                  request a graceful stop (eventually consistent).
POST /api/scraper/rescrape-open         re-scrape non-terminal processes from the last N months.
POST /api/scraper/refresh-indicators    request an inflation/FX indicator refresh.

The actual scraping runs in a separate container; this router only reads
`run_status.json` and writes `control.json` on the shared volume.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..dependencies import settings
from ..security import trigger_cooldown
from ..services import scraper_service

router = APIRouter(prefix="/api/scraper", tags=["scraper"])

# One shared cooldown for the three run-starting endpoints (start, rescrape,
# indicator refresh); /stop stays exempt so a run can always be halted.
_scrape_cooldown = trigger_cooldown("scraper")


class StartRequest(BaseModel):
    reset_progress: bool = False
    batch_size: int | None = None
    log_level: str | None = None
    source: Literal["comprar", "contratar"] | None = None


class RescrapeOpenRequest(BaseModel):
    months: int | None = None
    source: Literal["comprar", "contratar"] | None = None


@router.get("/status")
def get_status(cfg=Depends(settings)):
    """Return the current scraper status from the shared status file."""
    return scraper_service.get_status(cfg.scraper_control_dir)


@router.post("/start", status_code=202, dependencies=[Depends(_scrape_cooldown)])
def start(body: StartRequest | None = None, cfg=Depends(settings)):
    """Request a scrape run. 409 if one is already running."""
    if scraper_service.is_running(cfg.scraper_control_dir):
        raise HTTPException(status_code=409, detail="A scrape run is already in progress.")
    params = {k: v for k, v in (body.model_dump() if body else {}).items() if v is not None}
    scraper_service.request_start(cfg.scraper_control_dir, params)
    return {"accepted": True, "command": "run", "params": params}


@router.post("/stop", status_code=202)
def stop(cfg=Depends(settings)):
    """Request a graceful stop. 409 if nothing is running."""
    if not scraper_service.is_running(cfg.scraper_control_dir):
        raise HTTPException(status_code=409, detail="No scrape run is currently active.")
    scraper_service.request_stop(cfg.scraper_control_dir)
    return {"accepted": True, "command": "stop"}


@router.post("/rescrape-open", status_code=202, dependencies=[Depends(_scrape_cooldown)])
def rescrape_open(body: RescrapeOpenRequest | None = None, cfg=Depends(settings)):
    """Re-scrape non-terminal processes from the last N months. 409 if a run is active."""
    if scraper_service.is_running(cfg.scraper_control_dir):
        raise HTTPException(status_code=409, detail="A scrape run is already in progress.")
    months = body.months if body else None
    source = body.source if body else None
    scraper_service.request_rescrape_open(cfg.scraper_control_dir, months, source)
    return {"accepted": True, "command": "run",
            "params": {"rescrape_open": True, "months": months, "source": source}}


@router.post("/refresh-indicators", status_code=202, dependencies=[Depends(_scrape_cooldown)])
def refresh_indicators(cfg=Depends(settings)):
    """Request a refresh of inflation/FX indicators. 409 if a run is active."""
    if scraper_service.is_running(cfg.scraper_control_dir):
        raise HTTPException(status_code=409, detail="A scrape run is already in progress.")
    scraper_service.request_refresh_indicators(cfg.scraper_control_dir)
    return {"accepted": True, "command": "refresh_indicators"}
