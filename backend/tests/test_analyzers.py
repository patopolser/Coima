"""
Logic tests for the network analyzer checks using a fake Neo4j driver.

These exercise the in-Python graph logic (connected components, rotation entropy,
contact/co-bid intersection) without a live database, by returning canned rows for
each underlying query. Run from backend/:

    python -m pytest tests/test_analyzers.py -q
"""

from src.detector.checks import bid_rotation_ring, shared_contact_cluster


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def data(self):
        return self._rows


class _Session:
    def __init__(self, responder):
        self._responder = responder

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, **params):
        return _Result(self._responder(query, params))


class FakeDriver:
    """Routes each query to canned rows based on a substring in the Cypher text."""
    def __init__(self, responder):
        self._responder = responder

    def session(self):
        return _Session(self._responder)


def _cobid_pairs(members, shared):
    """Fully-connected co-bid pairs among `members`, each sharing `shared` processes."""
    rows = []
    for i, a in enumerate(members):
        for b in members[i + 1:]:
            rows.append({"a": a, "a_name": f"co {a}", "b": b, "b_name": f"co {b}", "shared": shared})
    return rows


def test_bid_rotation_ring_flags_rotating_trio():
    members = ["A", "B", "C"]

    def responder(query, params):
        if "SUBMITTED_BY]->(p1" in query:          # build_cobid_graph
            return _cobid_pairs(members, shared=4)
        if "AS bidders" in query:                   # fetch_process_outcomes
            # 6 shared processes, wins evenly rotated A,B,C → high entropy
            wins = ["A", "B", "C", "A", "B", "C"]
            return [
                {"process_number": f"P{i}", "bidders": members, "winners": [w]}
                for i, w in enumerate(wins)
            ]
        return []

    rows = bid_rotation_ring._run(FakeDriver(responder), {"thresholds": {}}, limit=100)

    # One row per member of the single ring
    assert {r["provider_cuit"] for r in rows} == {"A", "B", "C"}
    assert all(r["ring_size"] == 3 for r in rows)
    assert all(r["shared_processes"] == 6 for r in rows)
    # Even rotation across 3 members → rotation_pct at the ceiling
    assert all(r["rotation_pct"] == 100.0 for r in rows)


def test_bid_rotation_ring_ignores_single_dominator():
    members = ["A", "B", "C"]

    def responder(query, params):
        if "SUBMITTED_BY]->(p1" in query:
            return _cobid_pairs(members, shared=4)
        if "AS bidders" in query:
            # A wins everything → only 1 distinct winner → below ring_min_distinct_winners
            return [
                {"process_number": f"P{i}", "bidders": members, "winners": ["A"]}
                for i in range(6)
            ]
        return []

    rows = bid_rotation_ring._run(FakeDriver(responder), {"thresholds": {}}, limit=100)
    assert rows == []  # a dominant incumbent is serial_winner's job, not a rotation ring


def test_bid_rotation_ring_does_not_form_giant_ring_from_hub():
    # A hub H co-bids strongly with 12 leaves, but the leaves never co-bid with
    # each other. Connected-components would sweep all 13 into one ring; cliques
    # only see size-2 (H, leaf) groups, which fall below ring_min_members → none.
    hub = "H"
    leaves = [f"L{i}" for i in range(12)]

    def responder(query, params):
        if "SUBMITTED_BY]->(p1" in query:          # build_cobid_graph: star edges only
            return [{"a": hub, "a_name": "hub", "b": leaf, "b_name": leaf, "shared": 5}
                    for leaf in leaves]
        if "AS bidders" in query:
            return []
        return []

    rows = bid_rotation_ring._run(FakeDriver(responder), {"thresholds": {}}, limit=1000)
    assert rows == []


def test_bid_rotation_ring_caps_ring_size():
    # 10 providers all co-bidding with each other (a clique of 10) must be rejected:
    # cartels are small, ring_max_members defaults to 8.
    members = [f"P{i}" for i in range(10)]

    def responder(query, params):
        if "SUBMITTED_BY]->(p1" in query:
            return _cobid_pairs(members, shared=4)
        if "AS bidders" in query:
            return [{"process_number": f"P{i}", "bidders": members, "winners": [members[i % 10]]}
                    for i in range(20)]
        return []

    rows = bid_rotation_ring._run(FakeDriver(responder), {"thresholds": {}}, limit=1000)
    assert rows == []  # clique of 10 > ring_max_members (8)


def test_shared_contact_cluster_requires_cobid_confirmation():
    members = ["X", "Y"]

    def responder(query, params):
        if "contacts" in query and "HAS_ADDRESS" in query:   # build_contact_graph
            return [{"a": "X", "a_name": "Empresa X", "b": "Y", "b_name": "Empresa Y",
                     "shared": 2, "contacts": ["Phone:555", "Email:a@b.com"]}]
        if "SUBMITTED_BY]->(p1" in query:                    # build_cobid_graph
            return _cobid_pairs(members, shared=1)
        if "AS bidders" in query:                            # fetch_process_outcomes
            return [{"process_number": "P1", "bidders": members, "winners": ["X"]}]
        return []

    rows = shared_contact_cluster._run(FakeDriver(responder), {"thresholds": {}}, limit=100)
    assert {r["provider_cuit"] for r in rows} == {"X", "Y"}
    assert all(r["cluster_size"] == 2 for r in rows)
    assert all(r["cobid_processes"] == 1 for r in rows)
    assert all(r["distinct_winners"] == 1 for r in rows)


def test_shared_contact_cluster_skips_contact_only_no_cobid():
    members = ["X", "Y"]

    def responder(query, params):
        if "contacts" in query and "HAS_ADDRESS" in query:
            return [{"a": "X", "a_name": "Empresa X", "b": "Y", "b_name": "Empresa Y",
                     "shared": 1, "contacts": ["Email:a@b.com"]}]
        if "SUBMITTED_BY]->(p1" in query:
            return []          # they never co-bid
        if "AS bidders" in query:
            return []
        return []

    rows = shared_contact_cluster._run(FakeDriver(responder), {"thresholds": {}}, limit=100)
    assert rows == []  # sharing a contact without ever bidding together is not flagged
