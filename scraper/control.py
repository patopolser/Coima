"""
control.py - File-based control channel between the backend and the scraper supervisor.

Both live in separate containers sharing one volume (`settings.output_dir`).
The backend writes `control.json` (the desired command) and reads
`run_status.json` (the live state). The scraper supervisor does the inverse.

All writes are atomic (tmp file plus `os.replace`) so a reader never observes
a half-written file, and all reads tolerate a missing or partially-written
file.
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


def _control_path(output_dir: str) -> pathlib.Path:
    return pathlib.Path(output_dir) / CONTROL_FILENAME


def _status_path(output_dir: str) -> pathlib.Path:
    return pathlib.Path(output_dir) / STATUS_FILENAME


def _read_json(path: pathlib.Path) -> dict:
    """Read a JSON object, returning {} if absent or unparseable."""
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        # Tolerate a transient partial write; the caller retries on next poll.
        return {}


def _write_json_atomic(path: pathlib.Path, data: dict[str, Any]) -> None:
    """Write a JSON object atomically (tmp file in the same dir + os.replace)."""
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


def read_control(output_dir: str) -> dict:
    """Return the current control command dict, or {} if none.

    Shape: ``{"command": "run"|"stop", "params": {...}, "requested_at": iso}``.
    """
    return _read_json(_control_path(output_dir))


def write_control(output_dir: str, command: str, params: dict | None = None) -> dict:
    """Write a control command (`run` or `stop`) and return it."""
    payload = {
        "command": command,
        "params": params or {},
        "requested_at": _now_iso(),
    }
    _write_json_atomic(_control_path(output_dir), payload)
    return payload


def clear_control(output_dir: str) -> None:
    """Mark the current command as consumed so it is not re-applied."""
    _write_json_atomic(_control_path(output_dir), {"command": None, "consumed_at": _now_iso()})


def read_status(output_dir: str) -> dict:
    """Return the live run-status dict, or a safe idle default if absent."""
    status = _read_json(_status_path(output_dir))
    if not status:
        return {
            "is_running": False,
            "processes_scraped_count": 0,
            "last_run_target_count": 0,
            "current_run": None,
            "last_run": None,
            "updated_at": None,
        }
    return status


def write_status(output_dir: str, **fields: Any) -> dict:
    """Merge `fields` into the current status, stamp `updated_at`, persist."""
    status = _read_json(_status_path(output_dir))
    status.update(fields)
    status["updated_at"] = _now_iso()
    _write_json_atomic(_status_path(output_dir), status)
    return status
