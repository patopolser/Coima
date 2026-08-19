"""
authorizer_provider_ring.py — Authorizer + contracting-unit + provider triads where
one official keeps signing for one provider inside one unit, and that relationship
dominates both ends.

This fuses two existing single-axis checks into a directed triad:
  * authorizer_bias  — an official signs a disproportionate share to one provider.
  * uoc_favoritism   — a unit concentrates its spend on one provider.
A triad is flagged only when BOTH hold at once: the provider takes a large share of
everything the authorizer signs AND a large share of everything the unit awards
(by real, inflation-adjusted ARS). That intersection points at an insider channel
that neither check alone proves.

Python analyzer (uses `run`): one query for the triad totals, two for the authorizer
and unit denominators, then the share arithmetic in Python. One row per triad,
attributed to the provider for scoring.
"""

from src.detector.columns import (
    col_provider, col_unit, col_authorizer, col_quantity, col_percentage, col_money,
)
from src.detector.base import run_query
from src.detector.analytics import LATEST_IPC_MATCH, real_ars_expr, fetch_latest_usd
from src.detector.date_filter import date_params, process_date_filter

THRESHOLDS = {
    "triad_min_contracts": 4,            # contracts in the (auth, unit, provider) triad
    "triad_min_amount":    5_000_000,    # min real ARS in the triad
    "triad_min_auth_pct":  40.0,         # share of the authorizer's signed contracts
    "triad_min_unit_pct":  25.0,         # share of the unit's awarded real ARS
}

_REAL = real_ars_expr("cd")

_TRIADS = f"""
{LATEST_IPC_MATCH}
MATCH (proc:Process)-[:MANAGED_BY]->(u:ContractingUnit)
MATCH (proc)-[:GENERATES]->(cd:ContractualDocument)-[:AWARDED_TO]->(prov:Provider)
MATCH (cd)-[:AUTHORIZED_BY]->(auth:Authorizer)
WHERE cd.total_amount IS NOT NULL AND cd.total_amount > 0
  AND {process_date_filter('proc')}
OPTIONAL MATCH (cd)-[infl:VALUED_AT_INFLATION]->(idx:InflationIndex)
OPTIONAL MATCH (cd)-[fx_rel:VALUED_AT_FX]->(:ExchangeRate)
WHERE 'total_amount' IN fx_rel.amount_fields
WITH latest_ipc, auth, u, prov,
     count(DISTINCT cd)        AS contracts,
     sum({_REAL})              AS real_ars
WHERE contracts >= $min_contracts AND real_ars >= $min_amount
RETURN auth.full_name                    AS authorizer,
       u.code                            AS unit_code,
       coalesce(u.name, '—')            AS unit_name,
       prov.cuit                         AS provider_cuit,
       coalesce(prov.business_name, '—') AS provider_name,
       contracts,
       round(real_ars, 2)                AS real_ars
"""

_AUTH_TOTALS = """
MATCH (cd:ContractualDocument)-[:AUTHORIZED_BY]->(auth:Authorizer)
WHERE ($date_from IS NULL OR EXISTS {
        MATCH (gp:Process)-[:GENERATES]->(cd)
        WHERE gp.opening_date IS NOT NULL AND date(gp.opening_date) >= date($date_from) })
  AND ($date_to IS NULL OR EXISTS {
        MATCH (gp:Process)-[:GENERATES]->(cd)
        WHERE gp.opening_date IS NOT NULL AND date(gp.opening_date) <= date($date_to) })
RETURN auth.full_name AS authorizer, count(DISTINCT cd) AS total_contracts
"""

_UNIT_TOTALS = f"""
{LATEST_IPC_MATCH}
MATCH (proc:Process)-[:MANAGED_BY]->(u:ContractingUnit)
MATCH (proc)-[:GENERATES]->(cd:ContractualDocument)-[:AWARDED_TO]->(:Provider)
WHERE cd.total_amount IS NOT NULL AND cd.total_amount > 0
  AND {process_date_filter('proc')}
OPTIONAL MATCH (cd)-[infl:VALUED_AT_INFLATION]->(idx:InflationIndex)
OPTIONAL MATCH (cd)-[fx_rel:VALUED_AT_FX]->(:ExchangeRate)
WHERE 'total_amount' IN fx_rel.amount_fields
RETURN u.code AS unit_code, round(sum({_REAL}), 2) AS unit_real_ars
"""


def _run(driver, cfg, limit):
    t = cfg.get("thresholds", {})
    dates = date_params(cfg)
    params = {
        "min_contracts": t.get("triad_min_contracts", THRESHOLDS["triad_min_contracts"]),
        "min_amount":    t.get("triad_min_amount",    THRESHOLDS["triad_min_amount"]),
        **dates,
    }
    min_auth_pct = t.get("triad_min_auth_pct", THRESHOLDS["triad_min_auth_pct"])
    min_unit_pct = t.get("triad_min_unit_pct", THRESHOLDS["triad_min_unit_pct"])

    triads = run_query(driver, _TRIADS, params)
    if not triads:
        return []

    auth_totals = {r["authorizer"]: r["total_contracts"] for r in run_query(driver, _AUTH_TOTALS, dates)}
    unit_totals = {r["unit_code"]: r["unit_real_ars"] for r in run_query(driver, _UNIT_TOTALS, dates)}
    latest_usd = fetch_latest_usd(driver)

    rows = []
    for tr in triads:
        auth_total = auth_totals.get(tr["authorizer"], 0) or 0
        unit_total = unit_totals.get(tr["unit_code"], 0) or 0
        auth_pct = round(100.0 * tr["contracts"] / auth_total, 1) if auth_total else 0.0
        unit_pct = round(100.0 * (tr["real_ars"] or 0) / unit_total, 1) if unit_total else 0.0
        if auth_pct < min_auth_pct or unit_pct < min_unit_pct:
            continue
        real_ars = tr["real_ars"] or 0
        real_usd = round(real_ars / latest_usd, 2) if latest_usd and latest_usd > 0 else None
        rows.append({
            **tr,
            "authorizer_pct": auth_pct,
            "unit_pct":       unit_pct,
            "real_usd":       real_usd,
            "ars_currency":   "ARS",
            "usd_currency":   "USD",
        })

    rows.sort(key=lambda r: (r["authorizer_pct"] + r["unit_pct"], r["real_ars"]), reverse=True)
    return rows[:limit]


CHECK = {
    "key":    "authorizer_provider_ring",
    "label":  "Authorizer-Provider Ring",
    "weight": 45,
    "thresholds": THRESHOLDS,
    "run":    _run,
    "score_extractors": [
        lambda r: (r.get("provider_cuit"), r.get("provider_name")),
    ],
    "entity_extractors": {
        "unit": [lambda r: (r.get("unit_code"), r.get("unit_name"))],
        "authorizer": [lambda r: (r.get("authorizer"), r.get("authorizer"))],
    },
    "report_headers": ["Authorizer", "Unit", "CUIT", "Company", "Contracts", "Auth %", "Unit %", "Real ARS", "Total USD"],
    "report_row": lambda r: [
        r["authorizer"][:22], r["unit_code"],
        r["provider_cuit"], r["provider_name"][:22],
        r["contracts"], f"{r['authorizer_pct']}%", f"{r['unit_pct']}%",
        f"ARS {r['real_ars']:,.0f}" if r.get("real_ars") else "—",
        f"USD {r['real_usd']:,.0f}" if r.get("real_usd") else "—",
    ],
    "report_title": "AUTHORIZER-PROVIDER RING — Official + unit + provider triads that dominate both ends",
    "ui_meta": {
        "description": (
            "Flags authorizer + contracting-unit + provider triads where one official keeps signing "
            "for one provider in one unit, and that link dominates both sides at once: the provider "
            "takes a large share of everything the authorizer signs AND a large share of the unit's "
            "awarded spending (real, inflation-adjusted ARS). Combining authorizer_bias and "
            "uoc_favoritism into a single triad isolates an insider channel that neither check proves alone."
        ),
        "color": "red",
        "columns": [
            col_authorizer("authorizer", "Authorizer"),
            col_unit("unit_code", "Unit", name_key="unit_name"),
            col_provider("provider_cuit", "Provider", name_key="provider_name"),
            col_quantity("contracts",      "Contracts"),
            col_percentage("authorizer_pct", "Authorizer Share %"),
            col_percentage("unit_pct",        "Unit Share %"),
            col_money("real_ars", "Real ARS", currency_key="ars_currency"),
            col_money("real_usd", "Total USD", currency_key="usd_currency"),
        ],
        "search_fields": ["authorizer", "unit_code", "provider_cuit", "provider_name"],
    },
    "i18n": {
        "es": {
            "label": "Anillo Autorizador-Proveedor",
            "description": (
                "Marca triadas autorizador + unidad de contratación + proveedor donde un mismo "
                "funcionario firma sistemáticamente para un mismo proveedor en una misma unidad, y "
                "ese vínculo domina ambos lados a la vez: el proveedor concentra una porción alta de "
                "todo lo que el autorizador firma Y una porción alta del gasto adjudicado por la "
                "unidad (ARS real, ajustado por inflación). Combinar authorizer_bias y uoc_favoritism "
                "en una sola triada aísla un canal de favoritismo que ningún check prueba por separado."
            ),
            "columns": {
                "authorizer":     "Autorizador",
                "unit_code":      "Unidad",
                "provider_cuit":  "Proveedor",
                "contracts":      "Contratos",
                "authorizer_pct": "% del Autorizador",
                "unit_pct":       "% de la Unidad",
                "real_ars":       "ARS Real",
                "real_usd":       "Total USD",
            },
        },
    },
}
