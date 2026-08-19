"""
uoc_favoritism.py — A contracting unit (UOC) concentrates a disproportionate
share of its awarded spending on a single provider.

The unit-level mirror of authorizer_bias.py: instead of the official who signs,
it looks at the purchasing unit that manages the process. Concentration is measured
by value — the provider's share of the unit's total awarded spending — because a
supplier can capture a large share of the money with relatively few contracts.
All amounts use real ARS (inflation + FX adjusted, dic-2016=100 base) so they are
comparable across years and currencies. One row per (unit, provider).
"""

from src.detector.columns import col_unit, col_provider, col_percentage, col_quantity, col_money

QUERY = """
// Reference: most recent IPC level (shared base dic-2016=100)
MATCH (ref_idx:InflationIndex)
WITH max(ref_idx.index_value) AS latest_ipc

MATCH (proc:Process)-[:MANAGED_BY]->(u:ContractingUnit)
MATCH (proc)-[:GENERATES]->(cd:ContractualDocument)-[:AWARDED_TO]->(prov:Provider)
WHERE cd.total_amount IS NOT NULL AND cd.total_amount > 0
  AND ($date_from IS NULL OR (proc.opening_date IS NOT NULL AND date(proc.opening_date) >= date($date_from)))
  AND ($date_to   IS NULL OR (proc.opening_date IS NOT NULL AND date(proc.opening_date) <= date($date_to)))

// Real ARS per awarded contract
OPTIONAL MATCH (cd)-[infl:VALUED_AT_INFLATION]->(idx:InflationIndex)
OPTIONAL MATCH (cd)-[fx:VALUED_AT_FX]->(:ExchangeRate)
WHERE 'total_amount' IN fx.amount_fields
WITH latest_ipc, u, prov, cd, idx,
     CASE WHEN coalesce(cd.currency, 'ARS') = 'ARS' THEN infl.ars_historico
          ELSE fx.ars_historico END AS nominal_ars
WITH latest_ipc, u, prov, cd,
     CASE WHEN idx.index_value IS NOT NULL AND idx.index_value > 0
          THEN nominal_ars * latest_ipc / idx.index_value ELSE 0.0 END AS real_ars

WITH latest_ipc, u, prov,
     count(DISTINCT cd)        AS contracts_for_prov,
     round(sum(real_ars), 2)   AS total_real_ars
WHERE contracts_for_prov >= $min_contracts
  AND total_real_ars       >= $min_amount

// Unit-wide totals (count + real ARS) across every provider
MATCH (proc2:Process)-[:MANAGED_BY]->(u)
MATCH (proc2)-[:GENERATES]->(all_cd:ContractualDocument)-[:AWARDED_TO]->(:Provider)
WHERE all_cd.total_amount IS NOT NULL AND all_cd.total_amount > 0
  AND ($date_from IS NULL OR (proc2.opening_date IS NOT NULL AND date(proc2.opening_date) >= date($date_from)))
  AND ($date_to   IS NULL OR (proc2.opening_date IS NOT NULL AND date(proc2.opening_date) <= date($date_to)))
OPTIONAL MATCH (all_cd)-[ai:VALUED_AT_INFLATION]->(aidx:InflationIndex)
OPTIONAL MATCH (all_cd)-[afx:VALUED_AT_FX]->(:ExchangeRate)
WHERE 'total_amount' IN afx.amount_fields
WITH latest_ipc, u, prov, contracts_for_prov, total_real_ars, all_cd, aidx,
     CASE WHEN coalesce(all_cd.currency, 'ARS') = 'ARS' THEN ai.ars_historico
          ELSE afx.ars_historico END AS a_nominal_ars
WITH u, prov, contracts_for_prov, total_real_ars,
     count(DISTINCT all_cd) AS total_awarded_in_unit,
     sum(CASE WHEN aidx.index_value IS NOT NULL AND aidx.index_value > 0
              THEN a_nominal_ars * latest_ipc / aidx.index_value ELSE 0.0 END) AS unit_real_ars
WITH u, prov, contracts_for_prov, total_real_ars, total_awarded_in_unit,
     CASE WHEN unit_real_ars > 0 THEN round(100.0 * total_real_ars / unit_real_ars, 1)
          ELSE 0.0 END AS concentration_pct
WHERE concentration_pct >= $min_pct

CALL () {
    OPTIONAL MATCH (usd:ExchangeRate {currency: 'USD', rate_type: 'BCRA_ESTADISTICAS_CAMBIARIAS'})
    WITH usd ORDER BY usd.observed_date DESC LIMIT 1
    RETURN usd.ars_per_unit AS latest_usd
}

RETURN
    u.code                                 AS unit_code,
    coalesce(u.name, '—')                 AS unit_name,
    prov.cuit                              AS provider_cuit,
    coalesce(prov.business_name, '—')     AS provider_name,
    contracts_for_prov,
    total_awarded_in_unit,
    concentration_pct,
    total_real_ars,
    (CASE WHEN latest_usd IS NOT NULL AND latest_usd > 0
          THEN round(total_real_ars / latest_usd, 2) ELSE null END) AS total_real_usd,
    'ARS'                                  AS ars_currency,
    'USD'                                  AS usd_currency
ORDER BY concentration_pct DESC, total_real_ars DESC
LIMIT $limit
"""

THRESHOLDS = {
    "uoc_min_contracts": 3,
    "uoc_min_amount":    5_000_000,
    "uoc_min_pct":       10.0,
}

CHECK = {
    "key":    "uoc_favoritism",
    "label":  "UOC Favoritism",
    "weight": 30,
    "thresholds": THRESHOLDS,
    "query":  QUERY,
    "params": lambda cfg, limit: {
        "limit":         limit,
        "min_contracts": cfg.get("thresholds", {}).get("uoc_min_contracts", THRESHOLDS["uoc_min_contracts"]),
        "min_amount":    cfg.get("thresholds", {}).get("uoc_min_amount",    THRESHOLDS["uoc_min_amount"]),
        "min_pct":       cfg.get("thresholds", {}).get("uoc_min_pct",       THRESHOLDS["uoc_min_pct"]),
    },
    "score_extractors": [
        lambda r: (r.get("provider_cuit"), r.get("provider_name")),
    ],
    "entity_extractors": {
        "unit": [lambda r: (r.get("unit_code"), r.get("unit_name"))],
    },
    "report_headers": ["Unit", "Name", "CUIT", "Company", "Contracts", "Total Awarded", "Concentration %", "Total (ARS real)", "Total USD"],
    "report_row": lambda r: [
        r["unit_code"], r["unit_name"][:25],
        r["provider_cuit"], r["provider_name"][:25],
        r["contracts_for_prov"], r["total_awarded_in_unit"], f"{r['concentration_pct']}%",
        f"ARS {r['total_real_ars']:,.0f}",
        f"USD {r['total_real_usd']:,.0f}" if r.get("total_real_usd") else "—",
    ],
    "report_title": "UOC FAVORITISM — Unit concentrates its awards on one provider (real ARS)",
    "ui_meta": {
        "description": (
            "Identifies contracting units that direct a disproportionate share of their awarded "
            "spending (real ARS) to a single company, above minimum contract-count and amount "
            "thresholds. A signal of a captured purchasing unit or systematic favouritism toward "
            "one supplier."
        ),
        "color": "fuchsia",
        "columns": [
            col_unit("unit_code",              "Unit",            name_key="unit_name"),
            col_provider("provider_cuit",       "Favored Company", name_key="provider_name"),
            col_percentage("concentration_pct", "Spending Share %"),
            col_quantity("contracts_for_prov",  "Contracts"),
            col_quantity("total_awarded_in_unit", "Unit Total"),
            col_money("total_real_ars",          "Total (ARS real)", currency_key="ars_currency"),
            col_money("total_real_usd",          "Total USD",        currency_key="usd_currency"),
        ],
        "search_fields": ["unit_code", "unit_name", "provider_cuit", "provider_name"],
    },
    "i18n": {
        "es": {
            "label": "Favoritismo de UOC",
            "description": (
                "Identifica unidades contratantes que dirigen una proporción desmedida de su "
                "gasto adjudicado (ARS reales) a una sola empresa, por encima de umbrales "
                "mínimos de cantidad de contratos y monto. Señal de una unidad de compras "
                "capturada o favoritismo sistemático hacia un proveedor."
            ),
            "columns": {
                "unit_code":             "Unidad",
                "provider_cuit":         "Empresa Favorecida",
                "concentration_pct":     "% del Gasto",
                "contracts_for_prov":    "Contratos",
                "total_awarded_in_unit": "Total Unidad",
                "total_real_ars":        "Total (ARS real)",
                "total_real_usd":        "Total USD",
            },
        },
    },
}
