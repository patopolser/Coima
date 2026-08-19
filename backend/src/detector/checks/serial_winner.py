"""
serial_winner.py — Providers that win an outsized proportion of the processes
they bid on, and have accumulated significant contract value.

One row per provider. Bid count = distinct processes with at least one bid.
Win amount is broken down by currency (ListMoney) plus nominal and real ARS totals
derived from VALUED_AT_INFLATION relationships (ars_historico on the relationship,
index_value on the InflationIndex node; both series share the dic-2016=100 base).
"""

from src.detector.columns import col_provider, col_quantity, col_percentage, col_list_money, col_money

QUERY = """
// Reference: most recent IPC level across all InflationIndex nodes (shared base dic-2016=100)
MATCH (ref_idx:InflationIndex)
WITH max(ref_idx.index_value) AS latest_ipc

// All processes where this provider submitted at least one bid
MATCH (proc:Process)-[:HAS_BID]->(bid:Bid)-[:SUBMITTED_BY]->(prov:Provider)
WHERE ($date_from IS NULL OR (proc.opening_date IS NOT NULL AND date(proc.opening_date) >= date($date_from)))
  AND ($date_to   IS NULL OR (proc.opening_date IS NOT NULL AND date(proc.opening_date) <= date($date_to)))
WITH prov, count(DISTINCT proc) AS total_bids, latest_ipc

// Processes this provider won (has an awarded contractual document)
MATCH (won_proc:Process)-[:GENERATES]->(cd:ContractualDocument)-[:AWARDED_TO]->(prov)
WHERE ($date_from IS NULL OR (won_proc.opening_date IS NOT NULL AND date(won_proc.opening_date) >= date($date_from)))
  AND ($date_to   IS NULL OR (won_proc.opening_date IS NOT NULL AND date(won_proc.opening_date) <= date($date_to)))

WITH prov,
     total_bids,
     latest_ipc,
     count(DISTINCT won_proc)                                   AS total_wins,
     round(100.0 * count(DISTINCT won_proc) / total_bids, 1)   AS win_pct

WHERE total_bids >= $min_bids
  AND win_pct   >= $min_win_pct

// Awarded CDs with amounts — collect per-currency totals and ARS equivalents
MATCH (won_proc2:Process)-[:GENERATES]->(cd2:ContractualDocument)-[:AWARDED_TO]->(prov)
WHERE cd2.total_amount IS NOT NULL AND cd2.total_amount > 0
  AND ($date_from IS NULL OR (won_proc2.opening_date IS NOT NULL AND date(won_proc2.opening_date) >= date($date_from)))
  AND ($date_to   IS NULL OR (won_proc2.opening_date IS NOT NULL AND date(won_proc2.opening_date) <= date($date_to)))

// Inflation link exists for all documents; ars_historico is set only for ARS amounts
OPTIONAL MATCH (cd2)-[infl:VALUED_AT_INFLATION]->(idx:InflationIndex)
// FX link exists only for non-ARS; restrict to the relationship that covers total_amount
OPTIONAL MATCH (cd2)-[fx_rel:VALUED_AT_FX]->(:ExchangeRate)
WHERE 'total_amount' IN fx_rel.amount_fields

WITH prov, total_bids, total_wins, win_pct, latest_ipc,
     cd2.currency                                                  AS currency,
     sum(cd2.total_amount)                                         AS amount_sum,
     sum(
       CASE WHEN idx.index_value IS NOT NULL AND idx.index_value > 0
            THEN
              CASE WHEN coalesce(cd2.currency, 'ARS') = 'ARS' THEN infl.ars_historico
                   ELSE fx_rel.ars_historico END
              * latest_ipc / idx.index_value
            ELSE null END
     )                                                             AS real_ars_sum

WITH prov, total_bids, total_wins, win_pct,
     collect({currency: coalesce(currency, 'ARS'), amount: round(amount_sum, 2)}) AS total_won,
     round(sum(real_ars_sum), 2)        AS total_real_ars

CALL () {
    OPTIONAL MATCH (usd:ExchangeRate {currency: 'USD', rate_type: 'BCRA_ESTADISTICAS_CAMBIARIAS'})
    WITH usd ORDER BY usd.observed_date DESC LIMIT 1
    RETURN usd.ars_per_unit AS latest_usd
}

RETURN
    prov.cuit                             AS provider_cuit,
    coalesce(prov.business_name, '—')    AS provider_name,
    total_bids,
    total_wins,
    win_pct,
    total_won,
    total_real_ars,
    (CASE WHEN latest_usd IS NOT NULL AND latest_usd > 0
          THEN round(total_real_ars / latest_usd, 2) ELSE null END) AS total_real_usd,
    'ARS'                                 AS ars_currency,
    'USD'                                 AS usd_currency
ORDER BY win_pct DESC, total_wins DESC
LIMIT $limit
"""

def _fmt_ars(val):
    return f"ARS {val:,.0f}" if val else "—"

THRESHOLDS = {
    "serial_min_bids":    5,
    "serial_min_win_pct": 60.0,
}

CHECK = {
    "key":    "serial_winner",
    "label":  "Serial Winner",
    "weight": 20,
    "thresholds": THRESHOLDS,
    "query":  QUERY,
    "params": lambda cfg, limit: {
        "limit":        limit,
        "min_bids":     cfg.get("thresholds", {}).get("serial_min_bids",    THRESHOLDS["serial_min_bids"]),
        "min_win_pct":  cfg.get("thresholds", {}).get("serial_min_win_pct", THRESHOLDS["serial_min_win_pct"]),
    },
    "score_extractors": [
        lambda r: (r.get("provider_cuit"), r.get("provider_name")),
    ],
    "report_headers": ["CUIT", "Company", "Bids", "Wins", "Win %", "Total Won", "Real ARS", "Total USD"],
    "report_row": lambda r: [
        r["provider_cuit"], r["provider_name"][:35],
        r["total_bids"], r["total_wins"], f"{r['win_pct']}%",
        " / ".join(f"{m['currency']} {m['amount']:,.0f}" for m in (r["total_won"] or [])),
        _fmt_ars(r.get("total_real_ars")),
        f"USD {r['total_real_usd']:,.0f}" if r.get("total_real_usd") else "—",
    ],
    "report_title": "SERIAL WINNER — Providers winning an outsized share of contested processes",
    "ui_meta": {
        "description": (
            "Identifies providers that win a disproportionately high percentage of the "
            "procurement processes they bid on. Repeated, concentrated winning — especially "
            "across large monetary amounts — is a strong indicator of bid tailoring or "
            "insider advantage."
        ),
        "color": "purple",
        "columns": [
            col_provider("provider_cuit",   "Provider",      name_key="provider_name"),
            col_quantity("total_bids",       "Bids"),
            col_quantity("total_wins",       "Wins"),
            col_percentage("win_pct",        "Win %"),
            col_list_money("total_won",      "Total Won"),
            col_money("total_real_ars",      "Total Real",      currency_key="ars_currency"),
            col_money("total_real_usd",      "Total USD",       currency_key="usd_currency"),
        ],
        "search_fields": ["provider_cuit", "provider_name"],
    },
    "i18n": {
        "es": {
            "label": "Ganador Serial",
            "description": (
                "Identifica proveedores que ganan un porcentaje desproporcionadamente alto de "
                "los procesos de contratación en los que participan. Ganancias repetidas y "
                "concentradas, especialmente en montos elevados, son un indicador fuerte de "
                "licitación a medida o ventaja de información privilegiada."
            ),
            "columns": {
                "provider_cuit":     "Proveedor",
                "total_bids":        "Ofertas",
                "total_wins":        "Victorias",
                "win_pct":           "% Victoria",
                "total_won":         "Total Ganado",
                "total_real_ars":    "Total Real",
                "total_real_usd":    "Total USD",
            },
        },
    },
}
