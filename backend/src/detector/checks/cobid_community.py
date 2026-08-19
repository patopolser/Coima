"""
cobid_community.py — Communities in the co-bidding network whose members bid
together far more densely than the rest of the market.

Where bid_rotation_ring targets the *behavioural* signal (who wins), this is the
*structural* companion: it partitions the whole co-bidding graph into communities
(Louvain modularity) and flags those whose internal co-bid density is abnormally
high. A tight community is a candidate bidding bloc worth investigating even before
looking at win patterns, and it gives investigators the broader cluster around any
detected ring.

Python analyzer (uses `run`). One finding row per member of a flagged community.
Weight is modest so it informs/explores rather than dominating the score; the
strong cartel signal lives in bid_rotation_ring and shared_contact_cluster.
"""

from src.detector.columns import (
    col_provider, col_quantity, col_percentage, col_list_string,
)
from src.detector.analytics import build_cobid_graph
from src.detector.analytics.metrics import weighted_internal_density
from src.detector.date_filter import date_params

import networkx as nx

THRESHOLDS = {
    "community_min_edge_weight": 2,    # ignore one-off co-bids when building the graph
    "community_min_members":     4,    # only communities of at least this size
    "community_max_members":     40,   # skip giant blobs (likely whole-market, not a bloc)
    "community_min_density":     1.5,  # avg internal co-bid weight per possible pair
}


def _run(driver, cfg, limit):
    t = cfg.get("thresholds", {})
    min_w   = t.get("community_min_edge_weight", THRESHOLDS["community_min_edge_weight"])
    min_mem = t.get("community_min_members",     THRESHOLDS["community_min_members"])
    max_mem = t.get("community_max_members",     THRESHOLDS["community_max_members"])
    min_den = t.get("community_min_density",     THRESHOLDS["community_min_density"])

    graph = build_cobid_graph(driver, min_shared=min_w, dates=date_params(cfg))
    if graph.number_of_edges() == 0:
        return []

    communities = nx.community.louvain_communities(graph, weight="weight", seed=42)

    flagged = []
    for nodes in communities:
        if not (min_mem <= len(nodes) <= max_mem):
            continue
        sub = graph.subgraph(nodes)
        internal_weight = sum(d["weight"] for _, _, d in sub.edges(data=True))
        density = weighted_internal_density(len(nodes), internal_weight)
        if density < min_den:
            continue
        members = sorted(nodes)
        n = len(members)
        # Edge coverage: fraction of possible internal pairs that actually co-bid.
        cohesion_pct = round(100.0 * sub.number_of_edges() / (n * (n - 1) / 2), 1)
        flagged.append({
            "members": members,
            "density": round(density, 2),
            "cohesion_pct": cohesion_pct,
        })

    flagged.sort(key=lambda c: (c["density"], c["cohesion_pct"]), reverse=True)

    rows = []
    for comm_id, comm in enumerate(flagged, start=1):
        members = comm["members"]
        for cuit in members:
            others = [m for m in members if m != cuit]
            rows.append({
                "community_id":   comm_id,
                "provider_cuit":  cuit,
                "provider_name":  graph.nodes[cuit].get("name", "—"),
                "community_size": len(members),
                "density":        comm["density"],
                "cohesion_pct":   comm["cohesion_pct"],
                "co_members":     [{"text": f"{m} ({graph.nodes[m].get('name', '—')})"} for m in others][:20],
            })
            if len(rows) >= limit:
                return rows
    return rows


CHECK = {
    "key":    "cobid_community",
    "label":  "Co-bidding Community",
    "weight": 15,
    "thresholds": THRESHOLDS,
    "run":    _run,
    "score_extractors": [
        lambda r: (r.get("provider_cuit"), r.get("provider_name")),
    ],
    "report_headers": ["Community", "CUIT", "Company", "Size", "Density", "Cohesion %"],
    "report_row": lambda r: [
        r["community_id"], r["provider_cuit"], r["provider_name"][:25],
        r["community_size"], r["density"], f"{r['cohesion_pct']}%",
    ],
    "report_title": "CO-BIDDING COMMUNITY — Tightly interconnected bidding blocs",
    "ui_meta": {
        "description": (
            "Partitions the co-bidding network into communities (Louvain modularity) and flags "
            "those whose members bid with each other much more densely than the market at large. "
            "Density is the average number of shared processes per possible pair inside the "
            "community; cohesion % is how many of those pairs actually co-bid. A dense, cohesive "
            "community is a candidate bidding bloc and the natural neighbourhood around any rotation ring."
        ),
        "color": "violet",
        "columns": [
            col_provider("provider_cuit", "Provider", name_key="provider_name"),
            col_quantity("community_size", "Community Size"),
            col_quantity("density",        "Density"),
            col_percentage("cohesion_pct", "Cohesion %"),
            col_list_string("co_members",  "Other Members"),
        ],
        "search_fields": ["provider_cuit", "provider_name"],
    },
    "i18n": {
        "es": {
            "label": "Comunidad de Co-licitación",
            "description": (
                "Particiona la red de co-licitación en comunidades (modularidad de Louvain) y marca "
                "aquellas cuyos miembros licitan entre sí mucho más densamente que el mercado en "
                "general. La densidad es el promedio de procesos compartidos por par posible dentro "
                "de la comunidad; la cohesión % es cuántos de esos pares realmente co-licitaron. Una "
                "comunidad densa y cohesiva es un posible bloque de licitación y el vecindario "
                "natural alrededor de un anillo de rotación."
            ),
            "columns": {
                "provider_cuit":  "Proveedor",
                "community_size": "Tamaño de Comunidad",
                "density":        "Densidad",
                "cohesion_pct":   "% Cohesión",
                "co_members":     "Otros Miembros",
            },
        },
    },
}
