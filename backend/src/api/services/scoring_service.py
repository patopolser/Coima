"""
src/api/services/scoring_service.py - Build in-memory indexes over findings
and risk scores.

The indexes pivot the raw findings dataset two ways: by CUIT for the company
profile endpoint and by unit code for the contracting-unit endpoints. Both
are expensive to build, so the indexes live in a run-scoped cache that is
rebuilt only when the detection run_id changes.
"""

from __future__ import annotations

import json
import math
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# Column type -> entity namespace. A check is "directed at" a namespace iff it
# exposes at least one column of the matching type; everything downstream
# (indexes, routers, frontend) derives the association from here instead of
# hardcoding per-check lists.
_TYPE_TO_NAMESPACE = {
    "Provider": "provider",
    "Unit": "unit",
    "Authorizer": "authorizer",
}


def _entity_columns_from(columns: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """
    Group a check's column keys by the entity namespace their type maps to.
    Returns e.g. {"provider": ["provider_cuit"], "unit": ["unit_code"]}.
    """
    entity_cols: Dict[str, List[str]] = {}
    for col in columns or []:
        ns = _TYPE_TO_NAMESPACE.get(col.get("type"))
        if ns:
            entity_cols.setdefault(ns, []).append(col["key"])
    return entity_cols


def _name_key_for(columns: List[Dict[str, Any]], id_key: str) -> Optional[str]:
    """Return the name_key declared for the column whose key is id_key, if any."""
    for col in columns or []:
        if col.get("key") == id_key:
            return col.get("name_key")
    return None


@dataclass
class _IndexCache:
    """Holds pre-built indexes keyed to a specific detection run_id."""
    run_id: int
    company_index: Optional[Dict[str, Dict]] = None
    # Per-namespace entity indexes (unit, authorizer, ...), built lazily.
    entity_indexes: Dict[str, Dict[str, Dict]] = field(default_factory=dict)


_cache: Optional[_IndexCache] = None
_cache_lock = threading.Lock()


def _get_cache(run_id: int) -> _IndexCache:
    """Return the cache for run_id, resetting it if the run changed."""
    global _cache
    if _cache is None or _cache.run_id != run_id:
        _cache = _IndexCache(run_id=run_id)
    return _cache


def get_company_index(
    run_id: int,
    findings: Dict[str, List[Dict[str, Any]]],
    risk_scores: List[Dict[str, Any]],
    check_meta: Dict[str, Dict],
) -> Dict[str, Dict]:
    """Return the cached CUIT index for run_id, building it on first access."""
    with _cache_lock:
        cache = _get_cache(run_id)
        if cache.company_index is None:
            cache.company_index = build_company_index(findings, risk_scores, check_meta)
        return cache.company_index


def get_entity_index(
    run_id: int,
    findings: Dict[str, List[Dict[str, Any]]],
    check_meta: Dict[str, Dict],
    entity_type: str,
) -> Dict[str, Dict]:
    """
    Return the cached index for one entity namespace (unit, authorizer, ...),
    building it on first access for the run.
    """
    with _cache_lock:
        cache = _get_cache(run_id)
        if entity_type not in cache.entity_indexes:
            cache.entity_indexes[entity_type] = build_entity_index(
                findings, check_meta, entity_type
            )
        return cache.entity_indexes[entity_type]


def invalidate_index_cache() -> None:
    """Call this after a new detection run completes to force a rebuild."""
    global _cache
    with _cache_lock:
        _cache = None


def build_company_index(
    findings: Dict[str, List[Dict[str, Any]]],
    risk_scores: List[Dict[str, Any]],
    check_meta: Dict[str, Dict],
) -> Dict[str, Dict]:
    """
    Build a CUIT -> {risk_score, findings} index.

    risk_scores: list of {cuit, company, score, flags}.
    check_meta:  key -> {cuit_columns: [...], ...}.
    """
    index: Dict[str, Dict] = {}

    for rs in risk_scores:
        cuit = rs["cuit"]
        if cuit not in index:
            index[cuit] = {"risk_score": rs, "findings": defaultdict(list)}
        else:
            index[cuit]["risk_score"] = rs

    for check_name, rows in findings.items():
        cuit_fields: List[str] = check_meta.get(check_name, {}).get("cuit_columns", [])
        for row in rows:
            for field_name in cuit_fields:
                cuit = row.get(field_name)
                if cuit:
                    if cuit not in index:
                        index[cuit] = {"risk_score": None, "findings": defaultdict(list)}
                    if row not in index[cuit]["findings"][check_name]:
                        index[cuit]["findings"][check_name].append(row)

    return index


def build_entity_index(
    findings: Dict[str, List[Dict[str, Any]]],
    check_meta: Dict[str, Dict],
    entity_type: str,
) -> Dict[str, Dict]:
    """
    Build an entity_id -> {name, total_tenders, findings: {check_key: [rows]}}
    index for one namespace (unit, authorizer, ...).

    A check is associated with the namespace iff it exposes a column of the
    matching type, surfaced as check_meta[key]["entity_columns"][entity_type].
    The display name comes from that column's declared name_key (the id itself
    when there is none, e.g. authorizers).
    """
    index: Dict[str, Dict] = {}

    for check_name, rows in findings.items():
        meta = check_meta.get(check_name, {})
        id_fields: List[str] = meta.get("entity_columns", {}).get(entity_type, [])
        if not id_fields:
            continue
        columns = meta.get("columns", [])

        for row in rows:
            for id_field in id_fields:
                ent_id = row.get(id_field)
                if not ent_id:
                    continue

                name_key = _name_key_for(columns, id_field)
                if ent_id not in index:
                    name = row.get(name_key) if name_key else None
                    index[ent_id] = {
                        "name": name or ent_id,
                        "total_tenders": 0,
                        "findings": defaultdict(list),
                    }
                elif name_key and index[ent_id]["name"] == ent_id:
                    # Backfill a real name if an earlier row lacked one.
                    nm = row.get(name_key)
                    if nm:
                        index[ent_id]["name"] = nm

                # Keep the highest total_tenders seen across checks for the entity.
                tots = row.get("total_tenders") or row.get("total_awarded_in_unit")
                if isinstance(tots, (int, float)):
                    index[ent_id]["total_tenders"] = max(
                        index[ent_id]["total_tenders"], int(tots)
                    )

                if row not in index[ent_id]["findings"][check_name]:
                    index[ent_id]["findings"][check_name].append(row)

    return index


def build_check_meta(check_weight_cfg: Dict[str, int] = None, locale: str = "en") -> Dict[str, Dict]:
    """
    Build {check_key: metadata_dict} from the auto-discovered checks registry,
    optionally overlaid with config-level weight overrides.
    """
    from src.detector.checks import get_all_checks
    from src.i18n.translator import normalize_locale

    loc = normalize_locale(locale)

    def _normalize_columns(columns: list) -> list:
        normalized = []
        for col in columns or []:
            if isinstance(col, dict):
                key = col.get("key")
                if not key:
                    continue
                normalized.append({
                    "type": col.get("type", "String"),
                    "key": key,
                    "label": col.get("label", key),
                    **{k: v for k, v in col.items() if k not in {"type", "key", "label"}},
                })
            elif isinstance(col, (list, tuple)) and len(col) >= 2:
                normalized.append({
                    "type": "String",
                    "key": col[0],
                    "label": col[1],
                })
        return normalized

    _COLOR_CYCLE = [
        "red", "amber", "purple", "orange", "cyan", "rose", "fuchsia",
        "emerald", "slate", "yellow", "indigo", "lime", "pink",
        "violet", "teal", "green",
    ]

    check_weight_cfg = check_weight_cfg or {}
    meta: Dict[str, Dict] = {}

    for i, check in enumerate(get_all_checks()):
        key = check["key"]
        ui = check.get("ui_meta", {})
        color = ui.get("color", _COLOR_CYCLE[i % len(_COLOR_CYCLE)])
        weight = check_weight_cfg.get(key, check.get("weight", 10))

        # Self-contained translations live in the check's own CHECK["i18n"][locale];
        # English (or any unlisted locale) falls back to the check's source strings.
        tr = check.get("i18n", {}).get(loc, {}) if loc != "en" else {}

        columns = _normalize_columns(ui.get("columns", []))
        col_labels = tr.get("columns", {})
        for col in columns:
            if col["key"] in col_labels:
                col["label"] = col_labels[col["key"]]

        cuit_cols = ui.get("cuit_columns", [])
        unit_cols = ui.get("unit_columns", [])
        url_cols = ui.get("url_columns", {})

        if columns:
            if not cuit_cols:
                cuit_cols = [c["key"] for c in columns if c.get("type") == "Provider"]
            if not unit_cols:
                unit_cols = [c["key"] for c in columns if c.get("type") == "Unit"]
            if not url_cols:
                url_cols = {c["key"]: c["url_key"] for c in columns if c.get("url_key")}

        entity_cols = _entity_columns_from(columns)

        meta[key] = {
            "label": tr.get("label") or check["label"],
            "description": tr.get("description") or ui.get("description", ""),
            "color": color,
            "weight": weight,
            "columns": columns,
            "cuit_columns": cuit_cols,
            "unit_columns": unit_cols,
            "entity_columns": entity_cols,
            "url_columns": url_cols,
            "search_fields": ui.get("search_fields", []),
        }

    return meta


def merge_legacy_meta(
    check_meta: Dict[str, Dict],
    findings: Dict[str, List[Dict[str, Any]]],
    check_weight_cfg: Dict[str, int] | None = None,
    locale: str = "en",
) -> Dict[str, Dict]:
    """Populate metadata for legacy checks not present in the registry."""
    check_weight_cfg = check_weight_cfg or {}

    def _titleize(key: str) -> str:
        return key.replace("_", " ").title()

    def _infer_type(key: str, sample: Any) -> str:
        lk = key.lower()
        if "cuit" in lk:
            return "Provider"
        if "uoc" in lk or "unit" in lk:
            return "Unit"
        if "saf" in lk or lk.startswith("org_"):
            return "Organization"
        if "pct" in lk or "rate" in lk:
            return "Percentage"
        if "amount" in lk or "price" in lk:
            return "Money"
        if isinstance(sample, list):
            if sample and isinstance(sample[0], dict):
                sample_keys = set(sample[0].keys())
                if {"process_number", "comprar_url"}.issubset(sample_keys):
                    return "ListProcess"
                if {"currency", "amount"}.issubset(sample_keys):
                    return "ListMoney"
                if {"code", "name"}.issubset(sample_keys):
                    return "ListUnit"
                if {"saf_code", "name"}.issubset(sample_keys):
                    return "ListOrganization"
                if {"type", "contact"}.issubset(sample_keys):
                    return "ListContact"
            return "ListString"
        if isinstance(sample, (int, float)):
            return "Quantity"
        return "String"

    def _find_name_key(key: str, row_keys: set) -> str | None:
        lk = key.lower()
        if lk.endswith("_cuit"):
            prefix = key[: -len("_cuit")]
            for suffix in ("_name", "_company", "_business_name"):
                candidate = f"{prefix}{suffix}"
                if candidate in row_keys:
                    return candidate
        if lk.startswith("cuit"):
            tail = key[len("cuit"):]
            for prefix in ("company", "provider"):
                candidate = f"{prefix}{tail}"
                if candidate in row_keys:
                    return candidate
        if lk.endswith("_code"):
            candidate = key[: -len("_code")] + "_name"
            if candidate in row_keys:
                return candidate
        return None

    for key, rows in findings.items():
        if key in check_meta:
            continue
        if not rows:
            continue

        sample = rows[0]
        if not isinstance(sample, dict):
            continue

        row_keys = set(sample.keys())
        url_cols = {}
        for field in row_keys:
            if field.endswith("_url"):
                base = field[: -len("_url")]
                if base in row_keys:
                    url_cols[base] = field

        columns = []
        cuit_cols = []
        unit_cols = []
        for field in row_keys:
            if field.endswith("_url"):
                continue
            sample_value = sample.get(field)
            col_type = _infer_type(field, sample_value)
            col = {
                "type": col_type,
                "key": field,
                "label": _titleize(field),
            }
            name_key = _find_name_key(field, row_keys)
            if name_key:
                col["name_key"] = name_key
            if field in url_cols:
                col["url_key"] = url_cols[field]
            columns.append(col)
            if col_type == "Provider":
                cuit_cols.append(field)
            if col_type == "Unit":
                unit_cols.append(field)

        from src.i18n.translator import t

        check_meta[key] = {
            "label": _titleize(key),
            "description": t(
                "legacy.description",
                locale,
                default="Legacy check (metadata inferred)",
            ),
            "color": "slate",
            "weight": check_weight_cfg.get(key, 10),
            "columns": columns,
            "cuit_columns": cuit_cols,
            "unit_columns": unit_cols,
            "entity_columns": _entity_columns_from(columns),
            "url_columns": url_cols,
            "search_fields": [c["key"] for c in columns],
        }

    return check_meta


def paginate(items: list, page: int, per_page: int) -> tuple:
    """Return (page_items, page, total_pages, total)."""
    total = len(items)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    return items[start : start + per_page], page, total_pages, total


def filter_rows(
    rows: List[Dict[str, Any]],
    search: Optional[str],
    search_fields: List[str],
) -> List[Dict[str, Any]]:
    """Filter rows where any search_field contains the search string (case-insensitive)."""
    if not search:
        return rows
    sl = search.lower()
    return [r for r in rows if any(sl in str(r.get(f, "")).lower() for f in search_fields)]


def compute_dashboard_stats(
    risk_scores: List[Dict[str, Any]],
    findings: Dict[str, List[Dict[str, Any]]],
    check_meta: Dict[str, Dict],
) -> Dict[str, Any]:
    """
    Compute every stat the Dashboard page needs in a single pass: score
    distribution, top entities, findings by vector and flag co-occurrence.
    """
    buckets = [
        {"bucket": "0-20", "count": 0},
        {"bucket": "21-40", "count": 0},
        {"bucket": "41-60", "count": 0},
        {"bucket": "61-80", "count": 0},
        {"bucket": "81-100", "count": 0},
    ]
    for rs in risk_scores:
        score = rs.get("score", 0)
        idx = min(int(score / 20), 4) if score < 100 else 4
        buckets[idx]["count"] += 1

    sorted_scores = sorted(risk_scores, key=lambda x: x.get("score", 0), reverse=True)
    top_entities = [
        {
            "cuit": rs["cuit"],
            "company": rs.get("company", "-"),
            "score": rs.get("score", 0),
            "flags": rs.get("flags", []),
        }
        for rs in sorted_scores[:10]
    ]

    findings_by_vector = []
    for key, meta in check_meta.items():
        count = len(findings.get(key, []))
        findings_by_vector.append({
            "check": key,
            "label": meta["label"],
            "count": count,
            "weight": meta["weight"],
        })
    findings_by_vector.sort(key=lambda x: x["count"], reverse=True)

    from collections import Counter
    pair_counter: Counter = Counter()
    for rs in risk_scores:
        raw_flags = rs.get("flags", [])
        # Accept both list (new format) and comma-separated string (legacy).
        if isinstance(raw_flags, str):
            flags = [f.strip() for f in raw_flags.split(",") if f.strip()]
        else:
            flags = list(raw_flags)

        # Count individual flag frequencies; true pair co-occurrence would be O(n^2).
        for f in flags:
            pair_counter[f] += 1

    flag_cooccurrence = [
        {"flag": flag, "label": check_meta.get(flag, {}).get("label", flag), "count": cnt}
        for flag, cnt in pair_counter.most_common(15)
    ]

    return {
        "total_entities": len(risk_scores),
        "total_findings": sum(len(v) for v in findings.values()),
        "units_scored": len(build_entity_index(findings, check_meta, "unit")),
        "distribution": buckets,
        "top_entities": top_entities,
        "findings_by_vector": findings_by_vector,
        "flag_cooccurrence": flag_cooccurrence,
    }
