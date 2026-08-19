"""
src/detector/analytics/metrics.py - Pure functions used by the network analyzer checks.

Kept free of any Neo4j or networkx dependency so the cartel-scoring logic can
be unit tested in isolation (see backend/tests/test_metrics.py).
"""

from __future__ import annotations

import math
from typing import Iterable, Mapping


def normalized_entropy(counts: Iterable[float]) -> float:
    """
    Shannon entropy of a distribution, normalized to [0, 1].

    Used to measure how evenly wins are spread across the members of a
    candidate ring. 1.0 means perfectly even (every member wins the same share,
    the textbook rotation pattern); 0.0 means one member takes everything (a
    single dominator, which is the serial_winner / cover_bidding signal rather
    than rotation).

    Zero or empty input returns 0.0. A single nonzero bucket also returns 0.0
    because there is no spread to measure.
    """
    vals = [c for c in counts if c > 0]
    total = sum(vals)
    if total <= 0 or len(vals) <= 1:
        return 0.0
    h = -sum((v / total) * math.log(v / total) for v in vals)
    return h / math.log(len(vals))


def weighted_internal_density(
    n_nodes: int,
    internal_weight: float,
) -> float:
    """
    Average co-bid weight per possible internal pair in a group of `n_nodes`.

    internal_weight is the sum of edge weights strictly inside the group. The
    function returns internal_weight / C(n_nodes, 2); groups of fewer than 2
    nodes return 0.0.

    A high value means the members co-bid with each other far more than a
    loose cluster would, which is the structural fingerprint of a colluding
    community.
    """
    if n_nodes < 2:
        return 0.0
    possible_pairs = n_nodes * (n_nodes - 1) / 2
    return internal_weight / possible_pairs


def win_distribution(outcomes: Iterable[Mapping], members: Iterable[str]) -> dict[str, int]:
    """
    Count wins per member across a list of process-outcome rows.

    outcomes: rows shaped like {"winners": [cuit, ...], ...} (from
              fetch_process_outcomes). A process may have several member
              winners (multi-line awards); each counts once for that member.
    members:  the candidate ring CUITs. The returned dict has an entry for
              every member (0 if they never won) so entropy reflects the full
              group rather than only those who appeared in the outcomes.
    """
    wins = {m: 0 for m in members}
    for row in outcomes:
        for cuit in row.get("winners") or []:
            if cuit in wins:
                wins[cuit] += 1
    return wins
