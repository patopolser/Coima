"""
spending_spikes.py — Months whose total awarded spending is well above the average
month, expressed in real ARS.

All contract amounts are converted to real ARS (inflation + FX adjusted,
dic-2016=100 base) before aggregation, following the serial_winner.py block. This
matters because under Argentine inflation nominal spending always trends upward, so
nominal totals would flag every recent month. A month is a spike when its real-ARS
spend exceeds the mean monthly spend by the configured multiplier.

The monthly mean is computed PER SOURCE (comprar / contratar), not pooled: public
works (contratar) contracts are orders of magnitude larger than goods/services
(comprar) purchases, so a pooled mean would let a single works contract create false
spikes on one side and mask real spikes on the other. Each row is one anomalous
(month, source) pair compared against that source's own mean.

Informational only (no per-CUIT score). Each row carries the list of processes
awarded that month for that source.
"""

from src.detector.columns import col_string, col_money, col_percentage, col_list_process

QUERY = """
// Reference: most recent IPC level (shared base dic-2016=100)
MATCH (ref_idx:InflationIndex)
WITH max(ref_idx.index_value) AS latest_ipc

MATCH (proc:Process)-[:GENERATES]->(cd:ContractualDocument)
WHERE cd.perfection_date IS NOT NULL
  AND cd.total_amount IS NOT NULL AND cd.total_amount > 0
  AND ($date_from IS NULL OR (proc.opening_date IS NOT NULL AND date(proc.opening_date) >= date($date_from)))
  AND ($date_to   IS NULL OR (proc.opening_date IS NOT NULL AND date(proc.opening_date) <= date($date_to)))

// Real ARS per contract
OPTIONAL MATCH (cd)-[infl:VALUED_AT_INFLATION]->(idx:InflationIndex)
OPTIONAL MATCH (cd)-[fx:VALUED_AT_FX]->(:ExchangeRate)
WHERE 'total_amount' IN fx.amount_fields
WITH latest_ipc, cd, idx, coalesce(proc.source, 'comprar') AS source,
     CASE WHEN coalesce(cd.currency, 'ARS') = 'ARS' THEN infl.ars_historico
          ELSE fx.ars_historico END AS nominal_ars
WITH latest_ipc, cd, source,
     CASE WHEN idx.index_value IS NOT NULL AND idx.index_value > 0
          THEN nominal_ars * latest_ipc / idx.index_value ELSE 0.0 END AS real_ars

// Pass 1: monthly totals only (one row per month+source, no process lists -> cheap).
// Collecting processes here would materialize the whole contract set in heap
// before filtering, which is what blows up memory on a large DB. The mean is taken
// per source so comprar and contratar are never compared against a pooled baseline.
WITH source,
     substring(toString(cd.perfection_date), 0, 7) AS month,
     sum(real_ars)                                 AS monthly_real
WITH source, collect({month: month, spend: monthly_real}) AS rows,
     avg(monthly_real)                             AS mean_spend
UNWIND rows AS r
WITH source, r.month AS month, r.spend AS spend, mean_spend
WHERE mean_spend > 0 AND spend > mean_spend * $spike_multiplier

// Pass 2: gather the processes only for the few (month, source) pairs that are spikes.
CALL (month, source) {
    MATCH (p:Process)-[:GENERATES]->(d:ContractualDocument)
    WHERE d.perfection_date IS NOT NULL
      AND d.total_amount IS NOT NULL AND d.total_amount > 0
      AND substring(toString(d.perfection_date), 0, 7) = month
      AND coalesce(p.source, 'comprar') = source
      AND ($date_from IS NULL OR (p.opening_date IS NOT NULL AND date(p.opening_date) >= date($date_from)))
      AND ($date_to   IS NULL OR (p.opening_date IS NOT NULL AND date(p.opening_date) <= date($date_to)))
    RETURN collect(DISTINCT {process_number: p.process_number, comprar_url: p.source_url}) AS processes
}

CALL () {
    OPTIONAL MATCH (usd:ExchangeRate {currency: 'USD', rate_type: 'BCRA_ESTADISTICAS_CAMBIARIAS'})
    WITH usd ORDER BY usd.observed_date DESC LIMIT 1
    RETURN usd.ars_per_unit AS latest_usd
}

RETURN
    month                                                     AS month,
    source                                                    AS source,
    round(spend, 2)                                           AS real_ars_spend,
    (CASE WHEN latest_usd IS NOT NULL AND latest_usd > 0
          THEN round(spend / latest_usd, 2) ELSE null END)    AS real_usd_spend,
    round(100.0 * (spend - mean_spend) / mean_spend, 1)       AS outlier_pct,
    processes                                                 AS processes,
    'ARS'                                                     AS ars_currency,
    'USD'                                                     AS usd_currency
ORDER BY real_ars_spend DESC
LIMIT $limit
"""

THRESHOLDS = {
    "spike_multiplier": 2.0,
}

CHECK = {
    "key":    "spending_spikes",
    "label":  "Spending Spikes",
    "weight": 0,
    "thresholds": THRESHOLDS,
    "query":  QUERY,
    "params": lambda cfg, limit: {
        "limit":            limit,
        "spike_multiplier": cfg.get("thresholds", {}).get("spike_multiplier", THRESHOLDS["spike_multiplier"]),
    },
    "score_extractors": [],
    "report_headers": ["Month", "Source", "Spend (ARS real)", "Spend (USD)", "Outlier %", "Processes"],
    "report_row": lambda r: [
        r["month"],
        r["source"],
        f"ARS {r['real_ars_spend']:,.0f}",
        f"USD {r['real_usd_spend']:,.0f}" if r.get("real_usd_spend") else "—",
        f"{r['outlier_pct']}%",
        str(len(r["processes"])),
    ],
    "report_title": "SPENDING SPIKES — Months with awarded spending far above the average (real ARS)",
    "ui_meta": {
        "description": (
            "Highlights months whose total awarded spending, in inflation- and FX-adjusted real "
            "ARS, exceeds the average month by the configured multiplier. The average is computed "
            "per source (comprar / contratar) so public-works and goods spending are never pooled "
            "into a single baseline. Informational view of anomalous spending periods with the "
            "underlying processes."
        ),
        "color": "orange",
        "columns": [
            col_string("month",            "Mes"),
            col_string("source",            "Fuente"),
            col_money("real_ars_spend",     "Gasto (ARS real)", currency_key="ars_currency"),
            col_money("real_usd_spend",     "Gasto (USD)",      currency_key="usd_currency"),
            col_percentage("outlier_pct",   "Outlier %"),
            col_list_process("processes",   "Procesos"),
        ],
        "search_fields": ["month", "source"],
    },
    "i18n": {
        "es": {
            "label": "Picos de Gasto",
            "description": (
                "Resalta meses cuyo gasto adjudicado total, en ARS reales (ajustado por "
                "inflación y tipo de cambio), supera al mes promedio por el multiplicador "
                "configurado. El promedio se calcula por fuente (comprar / contratar) para no "
                "mezclar el gasto de obra pública con el de bienes y servicios en una misma "
                "línea base. Vista informativa de períodos de gasto anómalo con los procesos "
                "subyacentes."
            ),
            "columns": {
                "month":          "Mes",
                "source":         "Fuente",
                "real_ars_spend": "Gasto (ARS real)",
                "real_usd_spend": "Gasto (USD)",
                "outlier_pct":    "% Outlier",
                "processes":      "Procesos",
            },
        },
    },
}
