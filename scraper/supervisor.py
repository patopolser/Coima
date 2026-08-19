"""
supervisor.py - Container entrypoint that turns the CLI scraper into a
backend-controllable service.

Polls `control.json` on the shared volume every few seconds:

  * `command == "run"` and idle  -> start a scrape in a worker thread.
  * `command == "stop"` and busy -> request a graceful stop (the current
    process finishes, the Neo4j batch flushes, progress is preserved).

Owns `run_status.json`: stamps `is_running` true/false and mirrors the live
counters emitted by `main.run_scrape`. The backend only ever reads status and
writes control; it never touches this process.
"""

from __future__ import annotations

import pathlib
import sys
import threading
import time
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import control
from config import settings
from main import refresh_indicators, run_scrape
from utils.logging_config import get_logger, setup_logging

logger = get_logger(__name__)

POLL_SECONDS = 2.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Supervisor:
    """Single-run-at-a-time supervisor driven by the control file."""

    def __init__(self, output_dir: str) -> None:
        self._output_dir = output_dir
        self._thread: threading.Thread | None = None
        self._stop_flag = threading.Event()
        self._current_run: dict | None = None

    @property
    def _is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _on_progress(self, info: dict) -> None:
        """Mirror live counters from run_scrape into run_status.json."""
        run = dict(self._current_run or {})
        run.update({
            "succeeded": info.get("succeeded", 0),
            "failed": info.get("failed", 0),
            "skipped": info.get("skipped", 0),
            "current_process": info.get("current_process"),
        })
        self._current_run = run
        control.write_status(
            self._output_dir,
            is_running=True,
            processes_scraped_count=info.get("processes_scraped_count", 0),
            last_run_target_count=info.get("target", 0),
            current_run=run,
        )

    def _scrape_worker(self, params: dict) -> None:
        """Thread body: run a scrape, then record the final status."""
        started_at = _now_iso()
        self._current_run = {
            "started_at": started_at, "succeeded": 0, "failed": 0,
            "skipped": 0, "current_process": None,
        }
        control.write_status(
            self._output_dir, is_running=True, current_run=self._current_run,
        )
        summary: dict = {}
        try:
            summary = run_scrape(
                params=params,
                on_progress=self._on_progress,
                should_stop=self._stop_flag.is_set,
            )
        except Exception as exc:  # noqa: BLE001 - surface any failure into status
            logger.error("Scrape run crashed: %s", exc, exc_info=True)
            summary = {"error": str(exc)}
        finally:
            last_run = {
                "started_at": started_at,
                "finished_at": _now_iso(),
                "succeeded": summary.get("succeeded", self._current_run.get("succeeded", 0)),
                "failed": summary.get("failed", self._current_run.get("failed", 0)),
                "skipped": summary.get("skipped", self._current_run.get("skipped", 0)),
                "stopped_early": summary.get("stopped_early", self._stop_flag.is_set()),
            }
            if "error" in summary:
                last_run["error"] = summary["error"]
            status = control.read_status(self._output_dir)
            control.write_status(
                self._output_dir,
                is_running=False,
                processes_scraped_count=status.get("processes_scraped_count", 0),
                last_run=last_run,
                current_run=None,
            )
            self._current_run = None
            self._stop_flag.clear()
            logger.info("Scrape run finished: %s", last_run)

    def _start(self, params: dict) -> None:
        if self._is_running:
            logger.info("Start requested but a run is already active. Ignoring.")
            return
        self._stop_flag.clear()
        self._thread = threading.Thread(
            target=self._scrape_worker, args=(params,), daemon=True, name="scrape-worker",
        )
        self._thread.start()
        logger.info("Scrape run started (params=%s).", params)

    def _stop(self) -> None:
        if not self._is_running:
            logger.info("Stop requested but no run is active. Ignoring.")
            return
        self._stop_flag.set()
        logger.info("Graceful stop requested. Finishing current process.")

    def _start_refresh(self) -> None:
        if self._is_running:
            logger.info("Indicator refresh requested but a run is already active. Ignoring.")
            return
        self._stop_flag.clear()
        self._thread = threading.Thread(
            target=self._refresh_worker, daemon=True, name="refresh-worker",
        )
        self._thread.start()
        logger.info("Indicator refresh started.")

    def _refresh_worker(self) -> None:
        """Thread body: refresh economic indicators, then record final status."""
        started_at = _now_iso()
        self._current_run = {
            "started_at": started_at, "kind": "refresh_indicators", "current_process": None,
        }
        control.write_status(
            self._output_dir, is_running=True, current_run=self._current_run,
        )
        last_run = {"started_at": started_at, "kind": "refresh_indicators"}
        try:
            refresh_indicators()
        except Exception as exc:  # noqa: BLE001 - surface any failure into status
            logger.error("Indicator refresh crashed: %s", exc, exc_info=True)
            last_run["error"] = str(exc)
        finally:
            last_run["finished_at"] = _now_iso()
            status = control.read_status(self._output_dir)
            control.write_status(
                self._output_dir,
                is_running=False,
                processes_scraped_count=status.get("processes_scraped_count", 0),
                last_run=last_run,
                current_run=None,
            )
            self._current_run = None
            self._stop_flag.clear()
            logger.info("Indicator refresh finished: %s", last_run)

    def loop(self) -> None:
        """Poll the control file forever, acting on run/stop commands."""
        logger.info("Supervisor started. Watching %s every %.1fs.",
                    control._control_path(self._output_dir), POLL_SECONDS)
        # Initialise an idle status so the backend has something to read.
        control.write_status(
            self._output_dir,
            is_running=False,
            current_run=None,
        )
        while True:
            try:
                cmd = control.read_control(self._output_dir)
                command = cmd.get("command")
                if command == "run":
                    control.clear_control(self._output_dir)
                    self._start(cmd.get("params") or {})
                elif command == "stop":
                    control.clear_control(self._output_dir)
                    self._stop()
                elif command == "refresh_indicators":
                    control.clear_control(self._output_dir)
                    self._start_refresh()
            except Exception as exc:  # noqa: BLE001 - never let the loop die
                logger.error("Supervisor loop error: %s", exc, exc_info=True)
            time.sleep(POLL_SECONDS)


def main() -> None:
    setup_logging(settings.log_level)
    Supervisor(settings.output_dir).loop()


if __name__ == "__main__":
    main()
