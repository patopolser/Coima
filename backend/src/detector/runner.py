"""
src/detector/runner.py - Orchestrates a detection run end to end.

A run executes every enabled check in parallel against Neo4j, aggregates the
findings into per-entity risk scores, and serialises both to disk. Two flavours
of check coexist behind the same contract: static Cypher checks (a query plus a
params builder) and Python analyzers (a `run(driver, cfg, limit)` callable that
may issue several queries and post-process the rows). Downstream consumers see
identical row dicts from both, so scoring and persistence stay uniform.
"""

from anyio import to_thread
from asyncio import coroutines
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from .analytics import clear_cobid_cache
from .base import run_query
from .checks import get_all_checks
from .date_filter import date_params
from .scoring import build_provider_scores

logger = logging.getLogger(__name__)


def run_detection(driver, cfg: dict, limit: int, max_workers: int = 4) -> dict:
    """
    Run every enabled check in parallel and return {check_key: [rows]}.

    Checks are enabled by default; set `"checks": {"key": false}` in config.json
    to skip one. `max_workers` bounds Neo4j concurrency (default 4). A failing
    check is logged and its key resolves to an empty list, so one broken check
    cannot abort the whole run.
    """
    # Drop any co-bid graph cached by a previous run so this run, which may see
    # freshly scraped data, never reuses a stale graph. The graph is then built
    # once per date window and shared across the analyzer checks that need it.
    clear_cobid_cache()

    checks_cfg = cfg.get("checks", {})
    all_checks = get_all_checks()

    # Bound into every Cypher check so its $date_from/$date_to references
    # resolve even when no window is active; Python analyzers read it from cfg.
    dparams = date_params(cfg)

    enabled = [c for c in all_checks if checks_cfg.get(c["key"], True)]
    skipped = [c["key"] for c in all_checks if not checks_cfg.get(c["key"], True)]

    if skipped:
        logger.info("Skipped (disabled in config): %s", ", ".join(skipped))

    findings: dict = {}

    def _run_single(check: dict) -> tuple[str, list]:
        if callable(check.get("run")):
            rows = check["run"](driver, cfg, limit)
        else:
            params = {**check["params"](cfg, limit), **dparams}
            rows = run_query(driver, check["query"], params)
        logger.info("  [%s] -> %d finding(s)", check["label"], len(rows))
        return check["key"], rows

    effective_workers = min(max_workers, len(enabled)) if enabled else 1

    with ThreadPoolExecutor(max_workers=effective_workers) as pool:
        futures = {pool.submit(_run_single, c): c for c in enabled}
        for future in as_completed(futures):
            try:
                key, rows = future.result()
                findings[key] = rows
            except Exception as exc:
                check = futures[future]
                logger.error("Check '%s' failed: %s", check["key"], exc)
                findings[check["key"]] = []

    return findings


def build_risk_scores(findings: dict, cfg: dict) -> list:
    """
    Aggregate per-provider risk scores by delegating to
    detector.scoring.build_provider_scores. Kept as a thin wrapper so the
    legacy import path (`from src.detector import build_risk_scores`) stays
    valid.
    """
    return build_provider_scores(findings, cfg)


def save_report(findings: dict, cfg: dict, path: str):
    """Serialise findings, summary and risk scores to a JSON report on disk."""
    output = {
        "generated_at": datetime.now().isoformat(),
        "config": cfg,
        "summary": {k: len(v) for k, v in findings.items()},
        "risk_scores": build_risk_scores(findings, cfg),
        "findings": findings,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nReport saved -> {path}")
