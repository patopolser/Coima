"""
src/detector/analytics/network.py - Graph and value helpers shared by the Python analyzer checks.

Everything here is a thin layer over src.detector.base.run_query: each function
runs one Cypher query and returns plain Python structures (a networkx.Graph or
a dict), so analyzers can compose them and post-process without
reimplementing the graph traversals that the existing Cypher checks already
encode.

Two graphs are built from the procurement data:

  * co-bidding graph: providers are nodes; an edge means two providers bid in
    the same process, weighted by how many processes they share. This is the
    substrate for cartel and bid-rotation detection.
  * contact graph: providers are nodes; an edge means they share an address,
    phone or email (same edge logic as fake_competition.py and contact_hub.py),
    weighted by the number of shared contacts.

real_ars_expr centralises the inflation/FX-to-real-ARS Cypher expression that
is otherwise copy-pasted across serial_winner, authorizer_bias,
contract_splitting, uoc_favoritism and spending_spikes, so value-weighting
stays consistent.
"""

from __future__ import annotations

import threading

import networkx as nx

from src.detector.base import run_query
from src.detector.date_filter import NO_WINDOW, process_date_filter


# Anchor for the most recent IPC level across all InflationIndex nodes (shared
# dic-2016 = 100 base). Bind once at the top of a query, then carry
# `latest_ipc` through the WITH chain.
LATEST_IPC_MATCH = """
MATCH (ref_idx:InflationIndex)
WITH max(ref_idx.index_value) AS latest_ipc
"""


USD_RATE_TYPE = "BCRA_ESTADISTICAS_CAMBIARIAS"

# Single-row anchor for the latest official BCRA USD rate (ARS per 1 USD).
# OPTIONAL MATCH inside the subquery guarantees one returned row
# (latest_usd = null when no ExchangeRate USD node exists), preventing a
# cartesian product from eliminating every incoming row in the caller query.
LATEST_USD_MATCH = """
CALL () {
    OPTIONAL MATCH (usd:ExchangeRate {currency: 'USD', rate_type: 'BCRA_ESTADISTICAS_CAMBIARIAS'})
    WITH usd ORDER BY usd.observed_date DESC LIMIT 1
    RETURN usd.ars_per_unit AS latest_usd
}
"""


def real_usd_expr(real_ars: str = "total_real_ars", latest_usd: str = "latest_usd") -> str:
    """Today's-USD value of an already-computed real-ARS amount (official BCRA rate)."""
    return (
        f"(CASE WHEN {latest_usd} IS NOT NULL AND {latest_usd} > 0 "
        f"THEN round({real_ars} / {latest_usd}, 2) ELSE null END)"
    )


def fetch_latest_usd(driver) -> float | None:
    """Return the latest official BCRA USD rate (ARS per 1 USD), or None if unavailable."""
    rows = run_query(
        driver,
        "MATCH (usd:ExchangeRate {currency: 'USD', rate_type: $rt}) "
        "RETURN usd.ars_per_unit AS rate ORDER BY usd.observed_date DESC LIMIT 1",
        {"rt": USD_RATE_TYPE},
    )
    return rows[0]["rate"] if rows else None


def real_ars_expr(node: str, amount_field: str = "total_amount", latest_ipc: str = "latest_ipc") -> str:
    """
    Cypher snippet that yields the inflation-adjusted ARS value of
    `amount_field`, given an amount-bearing `node` (e.g. a ContractualDocument
    alias) already in scope together with its `[:VALUED_AT_INFLATION]->(idx)`
    and `[:VALUED_AT_FX]->()` optional matches.

    Usage (the caller owns the OPTIONAL MATCHes and the WITH chain):

        OPTIONAL MATCH (cd)-[infl:VALUED_AT_INFLATION]->(idx:InflationIndex)
        OPTIONAL MATCH (cd)-[fx_rel:VALUED_AT_FX]->(:ExchangeRate)
        WHERE 'total_amount' IN fx_rel.amount_fields
        WITH ..., {real} AS real_ars

    The nominal ARS value (pre-inflation) is the inner coalesce over infl/fx
    ars_historico; this helper applies the latest_ipc / idx.index_value
    reindexing on top of it.
    """
    nominal = (
        f"(CASE WHEN coalesce({node}.currency, 'ARS') = 'ARS' "
        f"THEN infl.ars_historico ELSE fx_rel.ars_historico END)"
    )
    return (
        f"(CASE WHEN idx.index_value IS NOT NULL AND idx.index_value > 0 "
        f"THEN {nominal} * {latest_ipc} / idx.index_value ELSE null END)"
    )


# Per-run cache for the co-bidding graph. The graph is the single most
# expensive query in a detection run (an O(processes x bids^2) self-join over
# every HAS_BID) and three callers want it at different `min_shared` cut-offs
# within the same run (cobid_community @2, bid_rotation_ring @3,
# compute_cobid_centrality @2). We build ONE base graph per date window at the
# floor below, cache it, and let each caller filter edges by weight in Python
# (cheap). clear_cobid_cache() is called at the start of every run so a run
# with fresh data never reuses a stale graph. The lock makes the two analyzer
# threads that race for the same base build it once, not twice.
_COBID_BASE_MIN_SHARED = 2
_cobid_cache: dict[tuple, nx.Graph] = {}
_cobid_lock = threading.Lock()


def clear_cobid_cache() -> None:
    """Drop any cached co-bidding base graphs. Call once at the start of a run."""
    with _cobid_lock:
        _cobid_cache.clear()


def _cobid_cache_key(dates: dict | None) -> tuple:
    d = dates or NO_WINDOW
    return (d.get("date_from"), d.get("date_to"))


def _build_cobid_graph_raw(driver, min_shared: int, dates: dict | None) -> nx.Graph:
    """Run the co-bid self-join and materialise a networkx graph (uncached)."""
    query = f"""
    MATCH (proc:Process)-[:HAS_BID]->(:Bid)-[:SUBMITTED_BY]->(p1:Provider)
    MATCH (proc)-[:HAS_BID]->(:Bid)-[:SUBMITTED_BY]->(p2:Provider)
    WHERE p1.cuit < p2.cuit
      AND {process_date_filter('proc')}
    WITH p1, p2, count(DISTINCT proc) AS shared
    WHERE shared >= $min_shared
    RETURN p1.cuit                            AS a,
           coalesce(p1.business_name, '—')   AS a_name,
           p2.cuit                            AS b,
           coalesce(p2.business_name, '—')   AS b_name,
           shared
    """
    rows = run_query(driver, query, {"min_shared": min_shared, **(dates or NO_WINDOW)})
    g = nx.Graph()
    for r in rows:
        g.add_node(r["a"], name=r["a_name"])
        g.add_node(r["b"], name=r["b_name"])
        g.add_edge(r["a"], r["b"], weight=r["shared"], shared=r["shared"])
    return g


def _filter_by_weight(base: nx.Graph, min_shared: int) -> nx.Graph:
    """Return a fresh graph keeping only edges with weight >= min_shared.
    Nodes follow their edges (an isolated node is dropped), matching the
    semantics of querying the graph directly at that cut-off."""
    g = nx.Graph()
    for u, v, d in base.edges(data=True):
        if d["weight"] >= min_shared:
            g.add_node(u, **base.nodes[u])
            g.add_node(v, **base.nodes[v])
            g.add_edge(u, v, **d)
    return g


def build_cobid_graph(driver, min_shared: int = 1, dates: dict | None = None) -> nx.Graph:
    """
    Co-bidding graph: an undirected edge (p1, p2) with weight equal to the
    number of distinct processes in which both providers submitted a bid.
    Nodes carry the provider's business name. Only pairs sharing at least
    `min_shared` processes are kept.

    `dates` is the optional run window ({date_from, date_to}); when set, only
    processes opened inside it count toward the co-bid weight.

    Within a run the heavy query is executed once per date window (at
    `_COBID_BASE_MIN_SHARED`) and cached; callers asking for a higher cut-off
    are served by filtering that base in memory. A caller needing a lower
    cut-off than the base bypasses the cache and queries directly, so
    correctness never depends on call order.
    """
    if min_shared < _COBID_BASE_MIN_SHARED:
        return _build_cobid_graph_raw(driver, min_shared, dates)

    key = _cobid_cache_key(dates)
    with _cobid_lock:
        base = _cobid_cache.get(key)
        if base is None:
            base = _build_cobid_graph_raw(driver, _COBID_BASE_MIN_SHARED, dates)
            _cobid_cache[key] = base

    # Always hand back a fresh graph so concurrent callers never share state
    # with the cached base or with each other.
    return _filter_by_weight(base, min_shared)


def build_contact_graph(driver) -> nx.Graph:
    """
    Contact graph: an undirected edge (p1, p2) when two providers share at
    least one Address, Phone or Email node (same edge semantics as
    fake_competition.py). Edge weight is the number of distinct shared
    contacts and nodes carry the business name.
    """
    query = """
    MATCH (p1:Provider)-[:HAS_ADDRESS|HAS_PHONE|HAS_EMAIL]->(c)
          <-[:HAS_ADDRESS|HAS_PHONE|HAS_EMAIL]-(p2:Provider)
    WHERE p1.cuit < p2.cuit AND labels(c)[0] IN ['Address', 'Phone', 'Email']
    WITH p1, p2,
         count(DISTINCT c)                                            AS shared,
         collect(DISTINCT labels(c)[0] + ':' + coalesce(c.value, '')) AS contacts
    RETURN p1.cuit                            AS a,
           coalesce(p1.business_name, '—')   AS a_name,
           p2.cuit                            AS b,
           coalesce(p2.business_name, '—')   AS b_name,
           shared,
           contacts
    """
    rows = run_query(driver, query, {})
    g = nx.Graph()
    for r in rows:
        g.add_node(r["a"], name=r["a_name"])
        g.add_node(r["b"], name=r["b_name"])
        g.add_edge(r["a"], r["b"], weight=r["shared"], shared=r["shared"],
                   contacts=r.get("contacts", []))
    return g


def fetch_provider_stats(driver) -> dict:
    """
    Per-provider participation summary keyed by CUIT:
        {cuit: {"name": str, "bids": int, "wins": int}}

    bids: distinct processes the provider bid in.
    wins: distinct processes the provider was awarded (has a
          ContractualDocument).
    """
    query = """
    MATCH (proc:Process)-[:HAS_BID]->(:Bid)-[:SUBMITTED_BY]->(p:Provider)
    WITH p, count(DISTINCT proc) AS bids
    OPTIONAL MATCH (won:Process)-[:GENERATES]->(:ContractualDocument)-[:AWARDED_TO]->(p)
    RETURN p.cuit                          AS cuit,
           coalesce(p.business_name, '—') AS name,
           bids,
           count(DISTINCT won)             AS wins
    """
    rows = run_query(driver, query, {})
    return {
        r["cuit"]: {"name": r["name"], "bids": r["bids"], "wins": r["wins"]}
        for r in rows
    }


def compute_cobid_centrality(driver, min_shared: int = 2, betweenness_sample_cap: int = 400) -> dict:
    """
    Centrality of each provider in the co-bidding network, keyed by CUIT:
        {cuit: {"cobid_degree": int, "cobid_betweenness": float}}

    degree:      number of distinct co-bidding partners (weighted edges
                 collapsed).
    betweenness: how often the provider lies on shortest paths between others.
                 A high value flags a *broker* bridging otherwise separate
                 bidding groups, a useful cartel-coordination signal. On large
                 graphs betweenness is approximated by sampling
                 `betweenness_sample_cap` source nodes (networkx `k`
                 parameter) to bound cost.

    Computed once per detection run and fed to the scorer as a recorded
    feature; it does not change the numeric score on its own.
    """
    graph = build_cobid_graph(driver, min_shared=min_shared)
    if graph.number_of_nodes() == 0:
        return {}

    degree = dict(graph.degree())
    n = graph.number_of_nodes()
    if n > betweenness_sample_cap:
        betw = nx.betweenness_centrality(graph, k=betweenness_sample_cap, weight=None, seed=42)
    else:
        betw = nx.betweenness_centrality(graph, weight=None)

    return {
        cuit: {
            "cobid_degree": int(degree.get(cuit, 0)),
            "cobid_betweenness": round(float(betw.get(cuit, 0.0)), 4),
        }
        for cuit in graph.nodes()
    }


def fetch_process_outcomes(driver, cuits: list[str], dates: dict | None = None) -> list[dict]:
    """
    For a set of providers, return one row per process they jointly
    participated in, listing which of them bid and which of them won. Used by
    ring analyzers to measure how wins are distributed across a candidate
    cartel (rotation vs. single dominator).

        [{"process_number": str, "bidders": [cuit, ...], "winners": [cuit, ...]}, ...]

    Only processes with at least 2 of the given providers bidding are
    returned. `dates` is the optional run window; when set, only processes
    opened inside it are returned.
    """
    if not cuits:
        return []
    query = f"""
    MATCH (proc:Process)-[:HAS_BID]->(:Bid)-[:SUBMITTED_BY]->(p:Provider)
    WHERE p.cuit IN $cuits
      AND {process_date_filter('proc')}
    WITH proc, collect(DISTINCT p.cuit) AS bidders
    WHERE size(bidders) >= 2
    OPTIONAL MATCH (proc)-[:GENERATES]->(:ContractualDocument)-[:AWARDED_TO]->(w:Provider)
    WHERE w.cuit IN $cuits
    RETURN proc.process_number          AS process_number,
           bidders,
           collect(DISTINCT w.cuit)     AS winners
    """
    return run_query(driver, query, {"cuits": cuits, **(dates or NO_WINDOW)})
