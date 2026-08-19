"""
src/api/services/scraper_service.py - Scraper control over the shared volume.

The scraper runs in its own container with a supervisor that owns
`run_status.json` and watches `control.json` in `settings.scraper_control_dir`
(a volume mounted into both containers). This service only reads the status
file and writes commands; it never touches the scraper process directly.

start/stop are eventually-consistent: they write the desired command and the
supervisor acts on its next poll (~2s). The frontend polls status to reflect
the real state.
"""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
from datetime import datetime, timezone
from typing import Any

CONTROL_FILENAME = "control.json"
STATUS_FILENAME = "run_status.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: pathlib.Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _write_json_atomic(path: pathlib.Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _idle_status() -> dict:
    return {
        "is_running": False,
        "processes_scraped_count": 0,
        "last_run_target_count": 0,
        "current_run": None,
        "last_run": None,
        "updated_at": None,
    }


def get_status(control_dir: str) -> dict:
    """Return the live scraper status, or a safe idle default if absent."""
    status = _read_json(pathlib.Path(control_dir) / STATUS_FILENAME)
    return status or _idle_status()


def is_running(control_dir: str) -> bool:
    return bool(get_status(control_dir).get("is_running"))


def request_start(control_dir: str, params: dict | None = None) -> dict:
    """Write a `run` command for the supervisor to pick up."""
    payload = {"command": "run", "params": params or {}, "requested_at": _now_iso()}
    _write_json_atomic(pathlib.Path(control_dir) / CONTROL_FILENAME, payload)
    return payload


def request_stop(control_dir: str) -> dict:
    """Write a `stop` command for the supervisor to pick up."""
    payload = {"command": "stop", "requested_at": _now_iso()}
    _write_json_atomic(pathlib.Path(control_dir) / CONTROL_FILENAME, payload)
    return payload


def request_refresh_indicators(control_dir: str) -> dict:
    """Write a `refresh_indicators` command for the supervisor to pick up."""
    payload = {"command": "refresh_indicators", "requested_at": _now_iso()}
    _write_json_atomic(pathlib.Path(control_dir) / CONTROL_FILENAME, payload)
    return payload


def request_rescrape_open(control_dir: str, months: int | None = None,
                          source: str | None = None) -> dict:
    """Write a `run` command that re-scrapes open processes from the last N months.

    Reuses the supervisor's `run` path; the scraper reads the non-terminal
    processes from Neo4j instead of the tenders file. `months` defaults to the
    scraper's configured look-back window when None. `source` selects the
    portal ("comprar" when None).
    """
    params: dict = {"rescrape_open": True}
    if months is not None:
        params["rescrape_months"] = months
    if source:
        params["source"] = source
    payload = {"command": "run", "params": params, "requested_at": _now_iso()}
    _write_json_atomic(pathlib.Path(control_dir) / CONTROL_FILENAME, payload)
    return payload
