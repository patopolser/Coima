"""
contract_splitting.py — A contracting unit awards the same provider many small
contracts in the same month, none individually large but summing to a substantial
amount (fraccionamiento).

Splitting a large purchase into several small direct awards is a classic technique
for staying under the per-contract threshold that would otherwise force open
competitive bidding. Amounts are converted to real ARS (inflation + FX adjusted,
dic-2016=100 base), following serial_winner.py, so the per-contract cap and the
aggregate threshold are comparable across years and currencies.

Aggregation is keyed by source (comprar / contratar) as well, so a provider's small
comprar awards and its small contratar awards in the same month are never summed
into one figure: the two portals run different threshold regimes, and pooling them
would conflate two distinct splitting caps.

One row per (unit, provider, month, source).
"""

from src.detector.columns import col_unit, col_provider, col_string, col_quantity, col_money, col_list_process

QUERY = """
// Reference: most recent IPC level (shared base dic-2016=100)
MATCH (ref_idx:InflationIndex)
WITH max(ref_idx.index_value) AS latest_ipc

MATCH (proc:Process)-[:MANAGED_BY]->(u:ContractingUnit)
MATCH (proc)-[:GENERATES]->(cd:ContractualDocument)-[:AWARDED_TO]->(prov:Provider)
WHERE cd.total_amount IS NOT NULL AND cd.total_amount > 0
  AND cd.perfection_date IS NOT NULL
  AND ($date_from IS NULL OR (proc.opening_date IS NOT NULL AND date(proc.opening_date) >= date($date_from)))
  AND ($date_to   IS NULL OR (proc.opening_date IS NOT NULL AND date(proc.opening_date) <= date($date_to)))

// Real ARS per contract
OPTIONAL MATCH (cd)-[infl:VALUED_AT_INFLATION]->(idx:InflationIndex)
OPTIONAL MATCH (cd)-[fx:VALUED_AT_FX]->(:ExchangeRate)
WHERE 'total_amount' IN fx.amount_fields
WITH latest_ipc, u, prov, proc, cd, idx,
     CASE WHEN coalesce(cd.currency, 'ARS') = 'ARS' THEN infl.ars_historico
          ELSE fx.ars_historico END AS nominal_ars
WITH u, prov, proc, cd,
     CASE WHEN idx.index_value IS NOT NULL AND idx.index_value > 0
          THEN nominal_ars * latest_ipc / idx.index_value ELSE 0.0 END AS real_ars

// Only "small" contracts that individually stay under the splitting cap
WHERE real_ars > 0 AND real_ars <= $max_contract_ars

WITH u, prov, coalesce(proc.source, 'comprar') AS source,
     substring(toString(cd.perfection_date), 0, 7) AS month,
     count(DISTINCT cd)                             AS split_count,
     round(sum(real_ars), 2)                        AS split_total_ars,
     collect(DISTINCT {process_number: proc.process_number, comprar_url: proc.source_url}) AS processes
WHERE split_count >= $min_splits
  AND split_total_ars >= $min_total_ars

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
    month,
    source,
    split_count,
    split_total_ars,
    (CASE WHEN latest_usd IS NOT NULL AND latest_usd > 0
          THEN round(split_total_ars / latest_usd, 2) ELSE null END) AS split_total_usd,
    processes,
    'ARS'                                  AS ars_currency,
    'USD'                                  AS usd_currency
ORDER BY split_total_ars DESC, split_count DESC
LIMIT $limit
"""

THRESHOLDS = {
    "split_max_contract_ars": 5_000_000,
    "split_min_count":        3,
    "split_min_total_ars":    5_000_000,
}

CHECK = {
    "key":    "contract_splitting",
    "label":  "Contract Splitting",
    "weight": 30,
    "thresholds": THRESHOLDS,
    "query":  QUERY,
    "params": lambda cfg, limit: {
        "limit":            limit,
        "max_contract_ars": cfg.get("thresholds", {}).get("split_max_contract_ars", THRESHOLDS["split_max_contract_ars"]),
        "min_splits":       cfg.get("thresholds", {}).get("split_min_count",        THRESHOLDS["split_min_count"]),
        "min_total_ars":    cfg.get("thresholds", {}).get("split_min_total_ars",    THRESHOLDS["split_min_total_ars"]),
    },
    "score_extractors": [
        lambda r: (r.get("provider_cuit"), r.get("provider_name")),
    ],
    "entity_extractors": {
        "unit": [lambda r: (r.get("unit_code"), r.get("unit_name"))],
    },
    "report_headers": ["Unit", "CUIT", "Company", "Month", "Source", "Contracts", "Total (ARS real)", "Total USD"],
    "report_row": lambda r: [
        r["unit_code"], r["provider_cuit"], r["provider_name"][:25],
        r["month"], r["source"], r["split_count"], f"ARS {r['split_total_ars']:,.0f}",
        f"USD {r['split_total_usd']:,.0f}" if r.get("split_total_usd") else "—",
    ],
    "report_title": "CONTRACT SPLITTING — Many small awards to one provider in a single month (real ARS)",
    "ui_meta": {
        "description": (
            "Detects fraccionamiento: a unit awarding the same provider several small contracts "
            "in the same month, each under the splitting cap but together exceeding a substantial "
            "aggregate amount. A classic technique for evading the threshold that would otherwise "
            "trigger open competitive bidding."
        ),
        "color": "orange",
        "columns": [
            col_unit("unit_code",          "Unit",     name_key="unit_name"),
            col_provider("provider_cuit",   "Provider", name_key="provider_name"),
            col_string("month",             "Month"),
            col_string("source",            "Source"),
            col_quantity("split_count",     "Contracts"),
            col_money("split_total_ars",    "Total (ARS real)", currency_key="ars_currency"),
            col_money("split_total_usd",    "Total USD",        currency_key="usd_currency"),
            col_list_process("processes",   "Processes"),
        ],
        "search_fields": ["unit_code", "unit_name", "provider_cuit", "provider_name", "month", "source"],
    },
    "i18n": {
        "es": {
            "label": "Fraccionamiento de Contratos",
            "description": (
                "Detecta fraccionamiento: una unidad que adjudica al mismo proveedor varios "
                "contratos pequeños en el mismo mes, cada uno por debajo del tope de "
                "fraccionamiento pero sumando en conjunto un monto sustancial. Técnica clásica "
                "para evadir el umbral que obligaría a la licitación competitiva abierta."
            ),
            "columns": {
                "unit_code":       "Unidad",
                "provider_cuit":   "Proveedor",
                "month":           "Mes",
                "source":          "Fuente",
                "split_count":     "Contratos",
                "split_total_ars": "Total (ARS real)",
                "split_total_usd": "Total USD",
                "processes":       "Procesos",
            },
        },
    },
}
