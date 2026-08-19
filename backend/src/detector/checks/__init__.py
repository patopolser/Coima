"""
checks/__init__.py — Auto-discovers all check modules in this folder.

Each module must expose a `CHECK` dict. A check is run in one of two ways:

  1. Cypher check (original contract): provide `query` + `params`. The runner executes the
     single Cypher query and returns its rows.
  2. Python analyzer: provide `run` instead of `query`/`params`. The runner calls
     `run(driver, cfg, limit)` and uses its return value. The analyzer may issue several
     queries (via src.detector.base.run_query) and post-process in Python — needed for
     network/graph and statistical detection that cannot be expressed as one query.

Both styles must return a list of row dicts, so scoring, persistence and UI are identical.

Keys:
    key              str       — unique identifier used in config/output
    label            str       — human-readable name for the progress line
    weight           int       — default risk score weight (can be overridden in config.json)
    query            str       — Cypher query string         (Cypher check only)
    params           callable  — (cfg, limit) -> dict params (Cypher check only)
    run              callable  — (driver, cfg, limit) -> list[dict]  (Python analyzer only)
    score_extractors list      — list of (row -> (cuit, name)) callables; empty for unit-level checks
    report_headers   list      — column headers for the printed table
    report_row       callable  — row -> list of display values
    report_title     str       — section header printed above the table

To add a new check: create a new .py file in this folder that sets a
module-level `CHECK` dict and it will be picked up automatically.
"""

import importlib
import pkgutil
from pathlib import Path

# Internal list of all discovered checks — populated at import time
_CHECKS: list[dict] = []

def _discover():
    pkg_dir = Path(__file__).parent
    for finder, module_name, _ in pkgutil.iter_modules([str(pkg_dir)]):
        module = importlib.import_module(f".{module_name}", package=__name__)
        check = getattr(module, "CHECK", None)
        if check is not None and isinstance(check, dict) and "key" in check:
            _CHECKS.append(check)

_discover()


def get_all_checks() -> list[dict]:
    """Return the list of all discovered CHECK dicts, in file-system order."""
    return list(_CHECKS)
