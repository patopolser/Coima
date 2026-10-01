"""
Tests for the MCP server (src/mcp_server): every tool is called through an
in-memory MCP client against a synthetic detection run in a temp SQLite file.
Neo4j is never contacted; the Cypher helpers are tested against a fake driver.

Run from backend/:  python -m pytest tests/test_mcp_server.py -q
"""

import json

import anyio
import pytest
from mcp import Client
from mcp.server.mcpserver.exceptions import ToolError

from src.api.database import sqlite as sqlite_db
from src.api.services import detection_context, scoring_service, tender_service
from src.mcp_server.server import mcp
from src.mcp_server.tools import cypher, network

RING = {
    "ring_id": 1, "provider_cuit": "30-1", "provider_name": "ACME",
    "ring_size": 3, "shared_processes": 9, "member_wins": 3, "rotation_pct": 95.0,
    "cobid_strength": 5.0,
    "co_members": [{"text": "30-2 (BETA)"}, {"text": "30-3 (GAMMA)"}],
}
CLUSTER = {
    "cluster_id": 7, "provider_cuit": "30-1", "provider_name": "ACME", "cluster_size": 2,
    "cobid_processes": 4, "distinct_winners": 1,
    "co_members": [{"text": "30-2 (BETA)"}],
    "shared_contacts": [{"type": "Phone", "contact": "555"}],
}
TRIAD = {
    "authorizer": "PEREZ JUAN", "unit_code": "101-000", "unit_name": "UOC CENTRAL",
    "provider_cuit": "30-1", "provider_name": "ACME", "contracts": 6,
    "authorizer_pct": 55.0, "unit_pct": 40.0, "real_ars": 12_000_000,
}
COVER = {"process_number": "84/13-2056-LPR24", "provider_cuit": "30-2", "provider_name": "BETA"}
BREAKDOWN = {
    "checks": [{"check": "bid_rotation_ring", "count": 1, "weight": 40, "contribution": 11.6}],
    "multiplier": 1.6,
    "features": {"cobid_degree": 7, "cobid_betweenness": 0.41},
}


@pytest.fixture(autouse=True)
def seeded_db(tmp_path):
    sqlite_db.init_db(str(tmp_path / "coima.db"))
    detection_context.reset_cache()
    scoring_service.invalidate_index_cache()
    db = sqlite_db.get_session()
    run = sqlite_db.DetectionRun(tender_count=120, status="done", summary="{}")
    db.add(run)
    db.flush()
    for key, rows in {
        "bid_rotation_ring": [RING],
        "shared_contact_cluster": [CLUSTER],
        "authorizer_provider_ring": [TRIAD],
        "cover_bidding": [COVER],
    }.items():
        db.add(sqlite_db.DetectionFinding(run_id=run.id, check_key=key, data=json.dumps(rows)))
    db.add(sqlite_db.RiskScore(
        run_id=run.id, cuit="30-1", company="ACME", score=72, base_score=45, confidence=3,
        flags=json.dumps(["bid_rotation_ring", "shared_contact_cluster"]),
        evidence_breakdown=json.dumps(BREAKDOWN),
    ))
    db.add(sqlite_db.RiskScore(run_id=run.id, cuit="30-2", company="BETA", score=20, flags="[]"))
    db.add(sqlite_db.RiskScore(
        run_id=run.id, cuit="101-000", company="UOC CENTRAL", score=33,
        flags=json.dumps(["authorizer_provider_ring"]), entity_type="unit",
    ))
    db.commit()
    db.close()
    yield
    detection_context.reset_cache()
    scoring_service.invalidate_index_cache()
    sqlite_db._engine = None


def call(name: str, args: dict | None = None):
    """Call a tool through a real MCP client; return (is_error, parsed JSON or text)."""
    async def go():
        async with Client(mcp) as client:
            return await client.call_tool(name, args or {})

    result = anyio.run(go)
    text = result.content[0].text
    try:
        return result.is_error, json.loads(text)
    except json.JSONDecodeError:
        return result.is_error, text


def ok(name: str, args: dict | None = None):
    is_error, data = call(name, args)
    assert not is_error, data
    return data


# ── registry ──────────────────────────────────────────────────────────────

def test_tools_and_prompts_are_registered_with_hints():
    async def go():
        async with Client(mcp) as client:
            return (await client.list_tools()).tools, (await client.list_prompts()).prompts

    tools, prompts = anyio.run(go)
    by_name = {t.name: t for t in tools}
    writes = {"create_investigation", "add_subject", "add_note", "save_report", "set_investigation_status"}
    assert {"get_entity_profile", "run_cypher", "get_tender", "get_network_neighborhood"} <= set(by_name)
    assert not {"search_web", "lookup_afip", "query_neo4j"} & set(by_name)
    for name, tool in by_name.items():
        assert tool.annotations.read_only_hint is (name not in writes), name
    assert {"investigate_company", "report_cartel_hypothesis"} <= {p.name for p in prompts}


# ── detection / entities ──────────────────────────────────────────────────

def test_detection_status_and_checks():
    status = ok("get_detection_status")
    assert status["tender_count"] == 120
    assert status["findings_per_check"]["bid_rotation_ring"] == 1
    assert status["scored_providers"] == 2

    checks = {c["key"]: c for c in ok("list_checks")["checks"]}
    assert checks["bid_rotation_ring"]["total_findings"] == 1
    assert "provider" in checks["bid_rotation_ring"]["targets"]


def test_check_findings_search_and_unknown_check():
    page = ok("get_check_findings", {"check_key": "bid_rotation_ring", "search": "acme"})
    assert page["total"] == 1 and page["items"][0]["ring_id"] == 1

    is_error, text = call("get_check_findings", {"check_key": "nope"})
    assert is_error and "list_checks" in text


def test_search_providers_filters_and_paginates():
    page = ok("search_providers", {"min_score": 50})
    assert [r["cuit"] for r in page["items"]] == ["30-1"]

    page = ok("search_providers", {"limit": 1})
    assert page["total"] == 2 and page["returned"] == 1 and page["truncated"] is True


def test_entity_profile_provider_and_unit():
    prof = ok("get_entity_profile", {"entity_type": "provider", "entity_id": "30-1"})
    assert prof["risk"]["score"] == 72
    assert prof["findings"]["bid_rotation_ring"]["total"] == 1

    unit = ok("get_entity_profile", {"entity_type": "unit", "entity_id": "101-000"})
    assert unit["name"] == "UOC CENTRAL" and unit["risk"]["score"] == 33

    is_error, _ = call("get_entity_profile", {"entity_type": "provider", "entity_id": "99-9"})
    assert is_error


def test_search_entities_ranks_units_and_authorizers():
    units = ok("search_entities", {"entity_type": "unit"})
    assert units["items"][0]["id"] == "101-000" and units["items"][0]["risk_score"] == 33

    auth = ok("search_entities", {"entity_type": "authorizer", "query": "perez"})
    assert auth["items"][0]["id"] == "PEREZ JUAN"


def test_risk_breakdown_reports_syndromes():
    out = ok("get_entity_risk_breakdown", {"entity_type": "provider", "entity_id": "30-1"})
    assert out["score"] == 72 and out["base_score"] == 45 and out["confidence"] == 3
    assert out["evidence_breakdown"]["multiplier"] == 1.6
    assert out["matched_syndromes"][0]["checks"] == ["bid_rotation_ring", "shared_contact_cluster"]


# ── network ───────────────────────────────────────────────────────────────

def test_network_neighborhood_maps_rings_and_centrality():
    out = ok("get_network_neighborhood", {"cuit": "30-1"})
    assert out["rings"][0]["rotation_pct"] == 95.0
    assert out["rings"][0]["co_members"] == ["30-2 (BETA)", "30-3 (GAMMA)"]
    assert out["contact_clusters"][0]["shared_contacts"] == ["Phone:555"]
    assert out["authorizer_triads"][0]["authorizer"] == "PEREZ JUAN"
    assert out["centrality"] == {"cobid_degree": 7, "cobid_betweenness": 0.41}

    assert "message" in ok("get_network_neighborhood", {"cuit": "99-9"})


def test_related_companies_come_from_real_cartel_checks():
    out = ok("list_related_companies", {"cuit": "30-1"})
    top = out["items"][0]
    assert top["cuit"] == "30-2" and top["name"] == "BETA" and top["link_count"] == 2
    assert {link["check"] for link in top["links"]} == {"bid_rotation_ring", "shared_contact_cluster"}


def test_compact_graph_rekeys_and_caps_nodes():
    graph = {
        "nodes": [
            {"id": "4:x:1", "group": "Provider", "label": "ACME", "cuit": "30-1"},
            {"id": "4:x:2", "group": "Process", "label": "P-1", "process_number": "P-1"},
            {"id": "4:x:3", "group": "Process", "label": "P-2", "process_number": "P-2"},
        ],
        "edges": [
            {"id": "a", "source": "4:x:1", "target": "4:x:2", "kind": "WON", "amount": 10, "currency": "ARS"},
            {"id": "b", "source": "4:x:1", "target": "4:x:3", "kind": "BID", "amount": 0},
        ],
    }
    out = network.compact_graph(graph, max_nodes=2)
    assert [n["id"] for n in out["nodes"]] == ["n1", "n2"]
    assert out["edges"] == [{"source": "n1", "target": "n2", "kind": "WON", "amount": 10, "currency": "ARS"}]
    assert out["truncated"] is True and out["node_counts"] == {"Provider": 1, "Process": 2}


# ── tenders ───────────────────────────────────────────────────────────────

def test_find_tender_findings_uses_typed_process_columns():
    findings = {
        "cover_bidding": [COVER],
        "contract_splitting": [{"processes": [{"process_number": "X-1"}, {"process_number": "X-2"}]}],
    }
    meta = {
        "cover_bidding": {"columns": [{"type": "Process", "key": "process_number"}]},
        "contract_splitting": {"columns": [{"type": "ListProcess", "key": "processes"}]},
    }
    assert tender_service.find_tender_findings(findings, meta, "84/13-2056-LPR24") == {"cover_bidding": [COVER]}
    assert list(tender_service.find_tender_findings(findings, meta, "X-2")) == ["contract_splitting"]


def test_get_tender_falls_back_to_findings_without_neo4j(monkeypatch):
    from src.mcp_server import runtime

    def no_neo4j():
        raise ToolError("Neo4j is not reachable")

    monkeypatch.setattr(runtime, "neo4j_driver", no_neo4j)
    out = ok("get_tender", {"process_number": "84/13-2056-LPR24"})
    assert out["neo4j_error"] == "Neo4j is not reachable"
    assert out["findings"]["cover_bidding"]["rows"] == [COVER]


# ── cypher ────────────────────────────────────────────────────────────────

def test_prepare_query_limit_handling():
    assert cypher.prepare_query("MATCH (n) RETURN n;", 100).endswith("LIMIT 101")
    assert cypher.prepare_query("MATCH (n) RETURN n LIMIT 5", 100) == "MATCH (n) RETURN n LIMIT 5"
    assert "LIMIT" not in cypher.prepare_query("CALL db.labels()", 100)
    with pytest.raises(ToolError):
        cypher.prepare_query("LOAD CSV FROM 'http://x' AS r RETURN r", 100)


class _FakeRecord(dict):
    pass


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def keys(self):
        return list(self._rows[0]) if self._rows else []

    def __iter__(self):
        return iter(_FakeRecord(r) for r in self._rows)


class _FakeSession:
    def __init__(self, driver):
        self.driver = driver

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute_read(self, work):
        self.driver.timeout = getattr(work, "timeout", None)
        tx = type("Tx", (), {"run": lambda _self, query, params: self.driver.run(query, params)})()
        return work(tx)


class _FakeDriver:
    def __init__(self, rows):
        self.rows = rows
        self.session_kwargs = None
        self.query = None
        self.timeout = None

    def session(self, **kwargs):
        self.session_kwargs = kwargs
        return _FakeSession(self)

    def run(self, query, params):
        self.query = query
        return _FakeResult(self.rows)


def test_run_read_query_uses_read_access_and_flags_truncation():
    from neo4j import READ_ACCESS

    driver = _FakeDriver([{"n": i} for i in range(6)])
    out = cypher.run_read_query(driver, "MATCH (n) RETURN n", None, limit=5)
    assert driver.session_kwargs["default_access_mode"] == READ_ACCESS
    assert driver.query.endswith("LIMIT 6") and driver.timeout == cypher.QUERY_TIMEOUT_SECONDS
    assert out["row_count"] == 5 and out["truncated"] is True and out["columns"] == ["n"]


# ── investigations ────────────────────────────────────────────────────────

def test_investigation_lifecycle():
    case = ok("create_investigation", {
        "title": "ACME ring",
        "subjects": [{"type": "company", "id": "30-1", "name": "ACME"}],
    })
    inv_id = case["id"]
    assert case["status"] == "open" and case["subjects"][0]["id"] == "30-1"

    ok("add_subject", {"investigation_id": inv_id, "type": "unit", "id": "101-000"})
    ack = ok("add_note", {"investigation_id": inv_id, "text": "Rotates wins with 30-2 in 9 processes."})
    assert ack["note_count"] == 1 and "notes" not in ack
    ok("save_report", {"investigation_id": inv_id, "report_type": "executive_summary", "content": "# Summary"})
    ok("set_investigation_status", {"investigation_id": inv_id, "status": "in_progress"})

    full = ok("get_investigation", {"investigation_id": inv_id})
    assert full["status"] == "in_progress"
    assert [s["type"] for s in full["subjects"]] == ["company", "unit"]
    assert full["notes"][0]["text"].startswith("Rotates")
    assert full["reports"][0]["content"] == "# Summary"
    assert "chat_history" not in full

    assert [c["id"] for c in ok("list_investigations", {"search": "30-1"})["items"]] == [inv_id]

    is_error, _ = call("add_note", {"investigation_id": "inv_missing", "text": "x"})
    assert is_error


# ── HTTP transport ────────────────────────────────────────────────────────

def test_http_endpoint_requires_token_and_local_host():
    from contextlib import asynccontextmanager

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.mcp_server.http import MCPHttpEndpoint

    endpoint = MCPHttpEndpoint(token="s3cret")

    @asynccontextmanager
    async def lifespan(_app):
        async with endpoint.lifespan():
            yield

    app = FastAPI(lifespan=lifespan)
    app.add_route("/mcp", endpoint)
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
    headers = {"Accept": "application/json, text/event-stream"}

    with TestClient(app, base_url="http://localhost:8000") as client:
        assert client.post("/mcp", json=body, headers=headers).status_code == 401
        auth = {**headers, "Authorization": "Bearer s3cret"}
        resp = client.post("/mcp", json=body, headers=auth)
        assert resp.status_code == 200 and resp.json()["result"]["serverInfo"]["name"] == "coima"
        assert client.post("/mcp", json=body, headers={**auth, "Host": "evil.example"}).status_code == 421
