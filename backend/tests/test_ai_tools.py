"""
Tests for the Fase 3 AI tools (CoimaTools) — pure data shaping, no API/Neo4j.

Run from backend/:  python -m pytest tests/test_ai_tools.py -q
"""

from src.ai.claude_client import CoimaTools, TOOLS, REPORT_PROMPTS, ANALYSIS_GUIDANCE


def _tools():
    company_index = {
        "30-1": {
            "risk_score": {
                "cuit": "30-1", "company": "ACME", "score": 72, "base_score": 45,
                "confidence": 3, "flags": ["bid_rotation_ring", "shared_contact_cluster"],
                "evidence_breakdown": {
                    "checks": [{"check": "bid_rotation_ring", "count": 1, "weight": 40,
                                "intensity": 0.29, "contribution": 11.6}],
                    "synergies": [{"label": "Cartel: rotation + shared ownership",
                                   "keys": ["bid_rotation_ring", "shared_contact_cluster"],
                                   "multiplier": 1.6}],
                    "multiplier": 1.6,
                    "features": {"cobid_degree": 7, "cobid_betweenness": 0.41},
                },
            },
            "findings": {},
        }
    }
    findings = {
        "bid_rotation_ring": [{
            "ring_id": 1, "provider_cuit": "30-1", "provider_name": "ACME",
            "ring_size": 3, "shared_processes": 9, "member_wins": 3, "rotation_pct": 95.0,
            "cobid_strength": 5.0,
            "co_members": [{"text": "30-2 (BETA)"}, {"text": "30-3 (GAMMA)"}],
        }],
        "shared_contact_cluster": [{
            "cluster_id": 1, "provider_cuit": "30-1", "cluster_size": 2,
            "cobid_processes": 4, "distinct_winners": 1,
            "co_members": [{"text": "30-2 (BETA)"}],
            "shared_contacts": [{"text": "Phone:555"}],
        }],
        "authorizer_provider_ring": [{
            "authorizer": "PEREZ JUAN", "unit_code": "101-000", "unit_name": "UOC",
            "provider_cuit": "30-1", "contracts": 6, "authorizer_pct": 55.0,
            "unit_pct": 40.0, "real_ars": 12_000_000,
        }],
    }
    return CoimaTools(company_index, findings)


def test_new_tools_are_registered():
    names = {t["name"] for t in TOOLS}
    assert {"get_entity_risk_breakdown", "get_network_neighborhood"} <= names
    assert "cartel_hypothesis" in REPORT_PROMPTS
    assert "get_network_neighborhood" in ANALYSIS_GUIDANCE


def test_get_entity_risk_breakdown():
    out = _tools().execute_tool("get_entity_risk_breakdown", {"cuit": "30-1"})
    assert out["score"] == 72 and out["base_score"] == 45 and out["confidence"] == 3
    assert out["evidence_breakdown"]["multiplier"] == 1.6
    assert out["evidence_breakdown"]["synergies"][0]["multiplier"] == 1.6


def test_get_entity_risk_breakdown_missing():
    out = _tools().execute_tool("get_entity_risk_breakdown", {"cuit": "99-9"})
    assert "error" in out


def test_get_network_neighborhood_maps_rings_and_centrality():
    out = _tools().execute_tool("get_network_neighborhood", {"cuit": "30-1"})
    assert out["rings"][0]["rotation_pct"] == 95.0
    assert out["rings"][0]["co_members"] == ["30-2 (BETA)", "30-3 (GAMMA)"]
    assert out["contact_clusters"][0]["shared_contacts"] == ["Phone:555"]
    assert out["authorizer_triads"][0]["authorizer"] == "PEREZ JUAN"
    assert out["centrality"] == {"cobid_degree": 7, "cobid_betweenness": 0.41}


def test_get_network_neighborhood_empty():
    out = _tools().execute_tool("get_network_neighborhood", {"cuit": "99-9"})
    assert "message" in out
