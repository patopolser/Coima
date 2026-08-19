"""
src/detector/analytics - Shared building blocks for Python analyzer checks.

Cypher checks express one pattern as one query. Network and statistical
detection (cartels, bid rotation, contact clusters) needs several queries plus
in-Python post-processing, so those checks use the `run(driver, cfg, limit)`
contract and build on the helpers here. See checks/__init__.py for the
contract.
"""

from .network import (
    LATEST_IPC_MATCH,
    LATEST_USD_MATCH,
    USD_RATE_TYPE,
    real_ars_expr,
    real_usd_expr,
    fetch_latest_usd,
    build_cobid_graph,
    clear_cobid_cache,
    build_contact_graph,
    fetch_provider_stats,
    fetch_process_outcomes,
    compute_cobid_centrality,
)

__all__ = [
    "LATEST_IPC_MATCH",
    "LATEST_USD_MATCH",
    "USD_RATE_TYPE",
    "real_ars_expr",
    "real_usd_expr",
    "fetch_latest_usd",
    "build_cobid_graph",
    "clear_cobid_cache",
    "build_contact_graph",
    "fetch_provider_stats",
    "fetch_process_outcomes",
    "compute_cobid_centrality",
]
