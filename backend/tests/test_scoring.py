"""
Tests for the smart scoring engine (detector.scoring).

Run from backend/:  python -m pytest tests/test_scoring.py -q
"""

import math

from src.detector.scoring import (
    intensity,
    matched_syndromes,
    build_provider_scores,
    build_entity_scores,
    build_all_scores,
)


def test_intensity_curve():
    assert intensity(0) == 0.0
    # 1 finding ≈ 0.30 (not pinned to full weight like the old max() bug)
    assert 0.25 < intensity(1) < 0.35
    # caps at 1.0 by ~10 findings and stays there
    assert intensity(10) == 1.0
    assert intensity(50) == 1.0
    assert intensity(3) < intensity(10)


def test_matched_syndromes_requires_full_set():
    assert matched_syndromes({"bid_rotation_ring"}) == []  # partial → no match
    matched = matched_syndromes({"bid_rotation_ring", "shared_contact_cluster"})
    assert any(s["multiplier"] == 1.6 for s in matched)


def _findings(provider_cuit, **per_check_counts):
    """Build a findings dict: each check_key → N rows attributing to provider_cuit."""
    out = {}
    for check_key, n in per_check_counts.items():
        out[check_key] = [
            {"provider_cuit": provider_cuit, "provider_name": "ACME"} for _ in range(n)
        ]
    return out


def test_single_weak_signal_scores_below_full_weight():
    # serial_winner weight is 20; one finding → ~30% intensity → ~6, not 20
    scores = build_provider_scores(_findings("20-1", serial_winner=1), cfg={})
    assert len(scores) == 1
    s = scores[0]
    assert s["cuit"] == "20-1"
    assert s["entity_type"] == "provider"
    assert s["confidence"] == 1
    assert s["score"] < 20
    assert s["score"] == s["base_score"]  # no synergy with a single flag


def test_synergy_boosts_corroborated_signals():
    # bid_rotation_ring (40) + shared_contact_cluster (40) → ×1.6 syndrome
    findings = {
        "bid_rotation_ring": [{"provider_cuit": "C", "provider_name": "X"}],
        "shared_contact_cluster": [{"provider_cuit": "C", "provider_name": "X"}],
    }
    s = build_provider_scores(findings, cfg={})[0]
    assert s["confidence"] == 2
    assert s["evidence_breakdown"]["multiplier"] == 1.6
    assert len(s["evidence_breakdown"]["synergies"]) >= 1
    # synergy makes the final score exceed the un-multiplied base
    assert s["score"] > s["base_score"]


def test_evidence_breakdown_shape_and_weight_override():
    # config weight override should be honored
    cfg = {"weights": {"serial_winner": 50}}
    s = build_provider_scores(_findings("Z", serial_winner=10), cfg=cfg)[0]
    checks = s["evidence_breakdown"]["checks"]
    assert checks[0]["check"] == "serial_winner"
    assert checks[0]["weight"] == 50
    assert checks[0]["intensity"] == 1.0  # 10 findings → full intensity
    assert s["base_score"] == 50


def test_unit_namespace_scoring():
    # cdi_abuse exposes a unit extractor; a unit should be scored under "unit"
    findings = {
        "cdi_abuse": [{"unit_code": "101-000", "unit_name": "UOC Salud", "cdi_pct": 80}],
        "uoc_favoritism": [{"unit_code": "101-000", "unit_name": "UOC Salud",
                            "provider_cuit": "30-1", "provider_name": "P"}],
    }
    units = build_entity_scores(findings, {}, "unit", use_synergy=False)
    assert len(units) == 1
    u = units[0]
    assert u["cuit"] == "101-000"
    assert u["company"] == "UOC Salud"
    assert u["entity_type"] == "unit"
    assert set(u["flags"]) == {"cdi_abuse", "uoc_favoritism"}
    assert u["confidence"] == 2


def test_authorizer_namespace_scoring():
    findings = {
        "authorizer_bias": [{"authorizer": "PEREZ JUAN", "provider_cuit": "30-1", "provider_name": "P"}],
    }
    auths = build_entity_scores(findings, {}, "authorizer", use_synergy=False)
    assert len(auths) == 1
    assert auths[0]["cuit"] == "PEREZ JUAN"
    assert auths[0]["entity_type"] == "authorizer"


def test_build_all_scores_separates_namespaces():
    findings = {
        "serial_winner": [{"provider_cuit": "30-1", "provider_name": "P"}],
        "cdi_abuse": [{"unit_code": "101-000", "unit_name": "UOC", "cdi_pct": 80}],
        "authorizer_bias": [{"authorizer": "PEREZ JUAN", "provider_cuit": "30-1", "provider_name": "P"}],
    }
    scores = build_all_scores(findings, {})
    by_type = {}
    for s in scores:
        by_type.setdefault(s["entity_type"], []).append(s)
    assert set(by_type) == {"provider", "unit", "authorizer"}
    assert by_type["provider"][0]["cuit"] == "30-1"
    assert by_type["unit"][0]["cuit"] == "101-000"
    assert by_type["authorizer"][0]["cuit"] == "PEREZ JUAN"


def test_centrality_feature_recorded_without_changing_score():
    findings = {"serial_winner": [{"provider_cuit": "30-1", "provider_name": "P"}]}
    features = {"30-1": {"cobid_degree": 12, "cobid_betweenness": 0.34}}
    with_feat = build_provider_scores(findings, {}, features=features)[0]
    without_feat = build_provider_scores(findings, {})[0]
    assert with_feat["evidence_breakdown"]["features"] == features["30-1"]
    # recording the feature must not move the numeric score
    assert with_feat["score"] == without_feat["score"]


def test_score_capped_at_100():
    # Many high-weight flags + synergy must still cap at 100
    findings = {
        "bid_rotation_ring": [{"provider_cuit": "C", "provider_name": "X"}] * 10,
        "shared_contact_cluster": [{"provider_cuit": "C", "provider_name": "X"}] * 10,
        "authorizer_provider_ring": [{"provider_cuit": "C", "provider_name": "X"}] * 10,
    }
    s = build_provider_scores(findings, cfg={})[0]
    assert s["score"] == 100
    assert s["base_score"] <= 100
