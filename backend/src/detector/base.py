"""
src/detector/base.py - Shared primitives used by every detector module.

Holds three things that the rest of the package leans on: config loading, safe
nested-dict access, and a retrying Neo4j query runner. The runner opens a fresh
session per query so memory is released between checks (long-running detection
sessions otherwise accumulate result buffers in the driver).
"""

import json
import sys
import time
from neo4j.exceptions import TransientError

try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False


DEFAULT_CONFIG_PATH = "config.json"


def load_config(path: str) -> dict:
    """Load a JSON config file. Missing file falls back to defaults; bad JSON aborts."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Config file not found: {path}. Using defaults.")
        return {}
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in config file: {e}")
        sys.exit(1)


def get(cfg: dict, *keys, default=None):
    """Safe nested dict access: get(cfg, 'connection', 'uri', default='...')"""
    val = cfg
    for key in keys:
        if not isinstance(val, dict):
            return default
        val = val.get(key, default)
    return val if val is not None else default


def run_query(driver, query: str, params: dict, retries: int = 3) -> list:
    """
    Run a Cypher query with bounded retries on TransientError.

    Each attempt uses its own session so the driver releases buffered results
    between queries; this matters during detection runs that issue dozens of
    queries back-to-back. Backoff is linear (2s, 4s, 6s) and a final failure
    returns an empty list rather than raising, so one flaky check cannot abort
    the whole run.
    """
    for attempt in range(1, retries + 1):
        try:
            with driver.session() as session:
                return session.run(query, **params).data()
        except TransientError as e:
            if attempt == retries:
                print(f"\n  WARNING: query failed after {retries} attempts: {e.message}")
                return []
            wait = attempt * 2
            print(f"\n  Memory error (attempt {attempt}/{retries}), retrying in {wait}s...")
            time.sleep(wait)
    return []
