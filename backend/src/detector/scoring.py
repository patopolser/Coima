"""
src/detector/scoring.py - Entity risk scoring with syndrome synergy.

The original scorer summed each check's weight times a log-intensity term and
treated every signal as independent. That misses the core intuition of
corruption analysis: a single weak signal is noise, but several corroborating
signals on the same entity form a syndrome. This module adds three pieces on
top of the original recipe:

  * intensity:  logarithmic curve, 1 finding is roughly 30% of the weight and
                10 findings saturate at 100%. The previous code clamped with
                max(1.0, ...) which pinned every flagged check to full weight,
                defeating the curve; the fix uses min().
  * synergy:    predefined combinations of checks that, when co-occurring on the
                same entity, multiply the score (a cartel is rotation plus
                shared contacts, not either alone).
  * confidence: how many independent vectors corroborate, reported separately
                from severity so the UI can distinguish a single loud finding
                from many quiet ones.

build_provider_scores is a drop-in replacement for the body of the original
build_risk_scores. The returned dicts keep the cuit/company/score/flags keys
and add base_score, confidence, entity_type and evidence_breakdown.
"""

from __future__ import annotations

import math

from .checks import get_all_checks


# If an entity's set of flagged checks is a superset of `keys`, the syndrome
# matches. The largest matched multiplier wins (multipliers do not stack, to
# avoid runaway scores). Unknown keys simply never match.
SYNDROMES = [
    {
        "label": "Cartel: rotation + shared ownership",
        "keys": {"bid_rotation_ring", "shared_contact_cluster"},
        "multiplier": 1.6,
    },
    {
        "label": "Cartel: rotation confirmed by community structure",
        "keys": {"bid_rotation_ring", "cobid_community"},
        "multiplier": 1.25,
    },
    {
        "label": "Shell competition: fake competition + shared contacts",
        "keys": {"fake_competition", "shared_contact_cluster"},
        "multiplier": 1.45,
    },
    {
        "label": "Cover bidding around a serial winner",
        "keys": {"serial_winner", "cover_bidding"},
        "multiplier": 1.4,
    },
    {
        "label": "Insider channel: dominance + authorizer/unit triad",
        "keys": {"serial_winner", "authorizer_provider_ring"},
        "multiplier": 1.5,
    },
    {
        "label": "Insider proxy: cross-agency win + shared contacts",
        "keys": {"cross_agency_proxy", "shared_contact_cluster"},
        "multiplier": 1.4,
    },
]


def intensity(count: int) -> float:
    """
    Logarithmic intensity in [0, 1]:
        1  finding  -> ~0.30
        3  findings -> ~0.58
        10 findings -> 1.0 (capped)
    """
    if count <= 0:
        return 0.0
    return min(1.0, math.log2(count + 1) / math.log2(11))


def matched_syndromes(flags: set[str]) -> list[dict]:
    """Return the syndromes whose key set is fully present in `flags`."""
    return [s for s in SYNDROMES if s["keys"] <= flags]


def _effective_weights(cfg: dict) -> dict:
    weights_cfg = cfg.get("weights", {})
    check_weights = {c["key"]: c["weight"] for c in get_all_checks()}
    return {**check_weights, **weights_cfg}


def _extractors_for(check: dict, entity_type: str) -> list:
    """
    Return the extractors a check exposes for a given entity namespace.

    Providers use the original `score_extractors`. Other namespaces (unit,
    authorizer) come from the optional `entity_extractors` map:
        "entity_extractors": {"unit": [lambda r: (code, name)], ...}
    A check contributes to an entity's score only if it exposes an extractor
    for that namespace.
    """
    if entity_type == "provider":
        return check.get("score_extractors", [])
    return check.get("entity_extractors", {}).get(entity_type, [])


def build_entity_scores(
    findings: dict,
    cfg: dict,
    entity_type: str = "provider",
    *,
    use_synergy: bool = True,
    features: dict | None = None,
) -> list:
    """
    Aggregate risk for one entity namespace (provider, unit or authorizer).

    The entity id is always carried in `cuit` (the risk_scores key column)
    regardless of namespace; `entity_type` disambiguates. Returned dicts are
    sorted by score desc and shaped as:
        {cuit, company, entity_type, score, base_score, confidence, flags,
         evidence_breakdown: {checks:[...], synergies:[...], multiplier, features?}}

    use_synergy applies the provider syndromes (off for unit/authorizer for
    now). features is an optional {entity_id: {feature: value}} dict recorded
    in the breakdown (e.g. co-bid centrality); it is record-only and does not
    change the score.
    """
    weights = _effective_weights(cfg)
    features = features or {}

    # Count findings per (entity_id, check_key), tracking the best name seen.
    per_entity: dict[str, dict] = {}
    for check in get_all_checks():
        key = check["key"]
        extractors = _extractors_for(check, entity_type)
        if not extractors:
            continue
        for row in findings.get(key, []):
            for extractor in extractors:
                try:
                    ent_id, name = extractor(row)
                except Exception:
                    continue
                if not ent_id:
                    continue
                entry = per_entity.setdefault(ent_id, {"_name": name})
                if name and not entry.get("_name"):
                    entry["_name"] = name
                entry[key] = entry.get(key, 0) + 1

    result = []
    for ent_id, data in per_entity.items():
        name = data.get("_name", "")
        breakdown = []
        base_total = 0.0
        flags = []

        for check_key, count in data.items():
            if check_key.startswith("_"):
                continue
            weight = weights.get(check_key, 0)
            # Informational checks (weight 0) contribute nothing and do not
            # flag the entity; they exist purely for the UI.
            if weight == 0:
                continue
            inten = intensity(count)
            contribution = weight * inten
            base_total += contribution
            flags.append(check_key)
            breakdown.append({
                "check": check_key,
                "count": count,
                "weight": weight,
                "intensity": round(inten, 3),
                "contribution": round(contribution, 2),
            })

        flag_set = set(flags)
        synergies = matched_syndromes(flag_set) if use_synergy else []
        multiplier = max((s["multiplier"] for s in synergies), default=1.0)

        evidence = {
            "checks": sorted(breakdown, key=lambda b: b["contribution"], reverse=True),
            "synergies": [
                {"label": s["label"], "keys": sorted(s["keys"]), "multiplier": s["multiplier"]}
                for s in synergies
            ],
            "multiplier": multiplier,
        }
        feat = features.get(ent_id)
        if feat:
            evidence["features"] = feat

        result.append({
            "cuit": ent_id,
            "company": name,
            "entity_type": entity_type,
            "score": min(round(base_total * multiplier), 100),
            "base_score": min(round(base_total), 100),
            "confidence": len(flag_set),
            "flags": flags,
            "evidence_breakdown": evidence,
        })

    return sorted(result, key=lambda x: x["score"], reverse=True)


def build_provider_scores(findings: dict, cfg: dict, features: dict | None = None) -> list:
    """Provider-namespace scoring with syndrome synergy (the default scorer)."""
    return build_entity_scores(findings, cfg, "provider", use_synergy=True, features=features)


def build_all_scores(findings: dict, cfg: dict, features: dict | None = None) -> list:
    """
    Score every entity namespace and return them in one list (each row carries
    its `entity_type`). Providers get synergy plus centrality features; units
    and authorizers get base intensity scoring plus confidence.
    """
    scores = build_entity_scores(findings, cfg, "provider", use_synergy=True, features=features)
    scores += build_entity_scores(findings, cfg, "unit", use_synergy=False)
    scores += build_entity_scores(findings, cfg, "authorizer", use_synergy=False)
    return scores
