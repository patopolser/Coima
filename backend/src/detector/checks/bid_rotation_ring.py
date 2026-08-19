"""
bid_rotation_ring.py — Groups of providers that repeatedly bid against each other
and take turns winning (bid rotation), the textbook fingerprint of a bid-rigging
cartel.

Unlike serial_winner (one provider wins too often) or cover_bidding (a runner-up
shadows the winner in a single process), this looks at the *group* level: a set of
providers that co-bid in many processes, where the wins are spread across several
members rather than concentrated in one. That spread — measured as the normalized
entropy of the win distribution — is what distinguishes a rotation ring from a
dominant incumbent surrounded by cover bidders.

This is a Python analyzer (uses `run`, not `query`): it builds the co-bidding graph
once, isolates dense components, and for each candidate ring pulls the per-process
win outcomes to score the rotation. One finding row per ring member, so every
provider in the ring is attributed the risk.
"""

from src.detector.columns import (
    col_provider, col_quantity, col_percentage, col_list_string,
)
from src.detector.analytics import build_cobid_graph, fetch_process_outcomes
from src.detector.analytics.metrics import normalized_entropy, win_distribution
from src.detector.date_filter import date_params

import networkx as nx

THRESHOLDS = {
    "ring_min_cobid_weight":      3,    # an edge counts only if the pair shares >= N processes
    "ring_min_members":           3,    # a ring needs at least this many providers
    "ring_max_members":           8,    # cartels are small; reject huge transitive blobs
    "ring_min_shared_processes":  5,    # joint processes (>=2 members bidding) the ring must reach
    "ring_min_distinct_winners":  2,    # at least this many members must actually win (else it's a dominator)
    "ring_min_rotation_pct":      45.0, # normalized win entropy, as a percentage
}

# Above this component size we do not enumerate cliques directly (cost guard);
# we first peel the graph to its k-core to shrink it, raising k until it fits.
_CLIQUE_NODE_CAP = 60


def _dense_subgroups(graph, min_mem, max_mem):
    """
    Yield tightly-knit candidate rings: maximal cliques of the strong co-bid graph
    where *every* pair co-bids, sized in [min_mem, max_mem].

    Using cliques instead of connected components is the fix for giant rings: a
    single hub provider connects hundreds of firms transitively into one component,
    but a clique requires all members to repeatedly meet each other — the actual
    shape of a colluding group. For components too large to enumerate cliques on
    safely, peel to the densest k-core first.
    """
    for component in nx.connected_components(graph):
        if len(component) < min_mem:
            continue
        sub = graph.subgraph(component)
        if sub.number_of_nodes() > _CLIQUE_NODE_CAP:
            k = 2
            while sub.number_of_nodes() > _CLIQUE_NODE_CAP and k < sub.number_of_nodes():
                core = nx.k_core(graph.subgraph(component), k=k)
                if core.number_of_nodes() == 0:
                    break
                sub = core
                k += 1
        for clique in nx.find_cliques(sub):
            if min_mem <= len(clique) <= max_mem:
                yield sorted(clique)


def _run(driver, cfg, limit):
    t = cfg.get("thresholds", {})
    min_w   = t.get("ring_min_cobid_weight",     THRESHOLDS["ring_min_cobid_weight"])
    min_mem = t.get("ring_min_members",          THRESHOLDS["ring_min_members"])
    max_mem = t.get("ring_max_members",          THRESHOLDS["ring_max_members"])
    min_sp  = t.get("ring_min_shared_processes", THRESHOLDS["ring_min_shared_processes"])
    min_dw  = t.get("ring_min_distinct_winners", THRESHOLDS["ring_min_distinct_winners"])
    min_rot = t.get("ring_min_rotation_pct",     THRESHOLDS["ring_min_rotation_pct"])
    dates = date_params(cfg)

    # Co-bid graph restricted to strong edges (pairs that repeatedly meet).
    graph = build_cobid_graph(driver, min_shared=min_w, dates=dates)

    rings = []
    seen = set()  # dedupe identical cliques surfaced from overlapping components/cores
    for members in _dense_subgroups(graph, min_mem, max_mem):
        key = tuple(members)
        if key in seen:
            continue
        seen.add(key)

        outcomes = fetch_process_outcomes(driver, members, dates=dates)
        shared_processes = len(outcomes)
        if shared_processes < min_sp:
            continue

        wins = win_distribution(outcomes, members)
        distinct_winners = sum(1 for c in wins.values() if c > 0)
        if distinct_winners < min_dw:
            continue

        rotation_pct = round(100.0 * normalized_entropy(wins.values()), 1)
        if rotation_pct < min_rot:
            continue

        sub = graph.subgraph(members)
        cobid_strength = round(
            sum(d["weight"] for _, _, d in sub.edges(data=True)) / max(sub.number_of_edges(), 1), 1
        )
        rings.append({
            "members": members,
            "wins": wins,
            "shared_processes": shared_processes,
            "rotation_pct": rotation_pct,
            "cobid_strength": cobid_strength,
        })

    # Strongest rings first; emit one row per member. A provider is reported in at
    # most one ring (its strongest), so overlapping cliques don't multiply findings.
    rings.sort(key=lambda r: (r["rotation_pct"], r["cobid_strength"], r["shared_processes"]), reverse=True)

    rows = []
    emitted_members = set()
    ring_id = 0
    for ring in rings:
        members = ring["members"]
        if any(m in emitted_members for m in members):
            continue
        ring_id += 1
        emitted_members.update(members)
        for cuit in members:
            others = [m for m in members if m != cuit]
            rows.append({
                "ring_id":          ring_id,
                "provider_cuit":    cuit,
                "provider_name":    graph.nodes[cuit].get("name", "—"),
                "ring_size":        len(members),
                "shared_processes": ring["shared_processes"],
                "member_wins":      ring["wins"][cuit],
                "rotation_pct":     ring["rotation_pct"],
                "cobid_strength":   ring["cobid_strength"],
                "co_members":       [{"text": f"{m} ({graph.nodes[m].get('name', '—')})"} for m in others],
            })
            if len(rows) >= limit:
                return rows
    return rows


CHECK = {
    "key":    "bid_rotation_ring",
    "label":  "Bid Rotation Ring",
    "weight": 40,
    "thresholds": THRESHOLDS,
    "run":    _run,
    "score_extractors": [
        lambda r: (r.get("provider_cuit"), r.get("provider_name")),
    ],
    "report_headers": ["Ring", "CUIT", "Company", "Members", "Shared", "Wins", "Rotation %"],
    "report_row": lambda r: [
        r["ring_id"], r["provider_cuit"], r["provider_name"][:25],
        r["ring_size"], r["shared_processes"], r["member_wins"], f"{r['rotation_pct']}%",
    ],
    "report_title": "BID ROTATION RING — Providers that repeatedly co-bid and take turns winning",
    "ui_meta": {
        "description": (
            "Detects cartels by analysing the co-bidding network: a small, tightly-knit group "
            "where every member repeatedly bids against the others (a clique, not a loose chain) "
            "and the wins rotate among them. Rotation % is the normalized entropy of the win "
            "distribution inside the ring — high values mean wins are spread evenly across members "
            "(taking turns), the classic bid-rigging pattern that competitive bidding would not "
            "produce by chance."
        ),
        "color": "red",
        "columns": [
            col_provider("provider_cuit", "Provider", name_key="provider_name"),
            col_quantity("ring_size",        "Ring Members"),
            col_quantity("shared_processes", "Shared Processes"),
            col_quantity("member_wins",      "Wins"),
            col_percentage("rotation_pct",   "Rotation %"),
            col_list_string("co_members",    "Other Members"),
        ],
        "search_fields": ["provider_cuit", "provider_name"],
    },
    "i18n": {
        "es": {
            "label": "Anillo de Rotación de Ofertas",
            "description": (
                "Detecta carteles analizando la red de co-licitación: un grupo chico y muy cohesionado "
                "donde cada miembro licita repetidamente contra los demás (un clique, no una cadena "
                "transitiva) y las adjudicaciones se rotan entre ellos. El % de rotación es "
                "la entropía normalizada de cómo se reparten las victorias dentro del anillo: "
                "valores altos significan que los triunfos se distribuyen de forma pareja entre los "
                "miembros (turnándose), el patrón clásico de connivencia que la competencia real no "
                "produciría por azar."
            ),
            "columns": {
                "provider_cuit":    "Proveedor",
                "ring_size":        "Miembros del Anillo",
                "shared_processes": "Procesos Compartidos",
                "member_wins":      "Adjudicaciones",
                "rotation_pct":     "% Rotación",
                "co_members":       "Otros Miembros",
            },
        },
    },
}
