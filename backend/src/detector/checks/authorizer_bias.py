"""
authorizer_bias.py — A government authorizer (the official who signs contractual
documents) concentrates a disproportionate share of the contracts they sign on a
single provider.

Monetary thresholds use real ARS (inflation + FX adjusted, dic-2016=100 base),
following the serial_winner.py conversion block, so amounts across years and
currencies are comparable. One row per (authorizer, provider).
"""

from src.detector.columns import col_authorizer, col_provider, col_percentage, col_quantity, col_money

QUERY = """
// Reference: most recent IPC level (shared base dic-2016=100)
MATCH (ref_idx:InflationIndex)
WITH max(ref_idx.index_value) AS latest_ipc

MATCH (cd:ContractualDocument)-[:AWARDED_TO]->(prov:Provider)
MATCH (cd)-[:AUTHORIZED_BY]->(auth:Authorizer)
WHERE cd.total_amount IS NOT NULL AND cd.total_amount > 0
  AND ($date_from IS NULL OR EXISTS {
        MATCH (gp:Process)-[:GENERATES]->(cd)
        WHERE gp.opening_date IS NOT NULL AND date(gp.opening_date) >= date($date_from) })
  AND ($date_to IS NULL OR EXISTS {
        MATCH (gp:Process)-[:GENERATES]->(cd)
        WHERE gp.opening_date IS NOT NULL AND date(gp.opening_date) <= date($date_to) })

// Real ARS per signed contract
OPTIONAL MATCH (cd)-[infl:VALUED_AT_INFLATION]->(idx:InflationIndex)
OPTIONAL MATCH (cd)-[fx:VALUED_AT_FX]->(:ExchangeRate)
WHERE 'total_amount' IN fx.amount_fields
WITH latest_ipc, auth, prov, cd, idx,
     CASE WHEN coalesce(cd.currency, 'ARS') = 'ARS' THEN infl.ars_historico
          ELSE fx.ars_historico END AS nominal_ars
WITH latest_ipc, auth, prov, cd,
     CASE WHEN idx.index_value IS NOT NULL AND idx.index_value > 0
          THEN nominal_ars * latest_ipc / idx.index_value ELSE 0.0 END AS real_ars

WITH auth, prov,
     count(DISTINCT cd)        AS contracts_for_prov,
     round(sum(real_ars), 2)   AS total_real_ars
WHERE contracts_for_prov >= $min_contracts
  AND total_real_ars       >= $min_amount

// Share of everything this authorizer signs that goes to this provider
MATCH (all_cd:ContractualDocument)-[:AUTHORIZED_BY]->(auth)
WHERE ($date_from IS NULL OR EXISTS {
        MATCH (gp:Process)-[:GENERATES]->(all_cd)
        WHERE gp.opening_date IS NOT NULL AND date(gp.opening_date) >= date($date_from) })
  AND ($date_to IS NULL OR EXISTS {
        MATCH (gp:Process)-[:GENERATES]->(all_cd)
        WHERE gp.opening_date IS NOT NULL AND date(gp.opening_date) <= date($date_to) })
WITH auth, prov, contracts_for_prov, total_real_ars,
     count(DISTINCT all_cd) AS total_signed
WITH auth, prov, contracts_for_prov, total_real_ars, total_signed,
     round(100.0 * contracts_for_prov / total_signed, 1) AS bias_pct
WHERE bias_pct >= $bias_pct

CALL () {
    OPTIONAL MATCH (usd:ExchangeRate {currency: 'USD', rate_type: 'BCRA_ESTADISTICAS_CAMBIARIAS'})
    WITH usd ORDER BY usd.observed_date DESC LIMIT 1
    RETURN usd.ars_per_unit AS latest_usd
}

RETURN
    auth.full_name                         AS authorizer,
    auth.document_number                   AS auth_doc,
    prov.cuit                              AS provider_cuit,
    coalesce(prov.business_name, '—')     AS provider_name,
    contracts_for_prov,
    total_signed,
    bias_pct,
    total_real_ars,
    (CASE WHEN latest_usd IS NOT NULL AND latest_usd > 0
          THEN round(total_real_ars / latest_usd, 2) ELSE null END) AS total_real_usd,
    'ARS'                                  AS ars_currency,
    'USD'                                  AS usd_currency
ORDER BY bias_pct DESC, total_real_ars DESC
LIMIT $limit
"""

THRESHOLDS = {
    "bias_min_contracts": 5,
    "bias_min_amount":    10_000_000,
    "bias_pct":           40.0,
}

CHECK = {
    "key":    "authorizer_bias",
    "label":  "Authorizer Bias",
    "weight": 30,
    "thresholds": THRESHOLDS,
    "query":  QUERY,
    "params": lambda cfg, limit: {
        "limit":         limit,
        "min_contracts": cfg.get("thresholds", {}).get("bias_min_contracts", THRESHOLDS["bias_min_contracts"]),
        "min_amount":    cfg.get("thresholds", {}).get("bias_min_amount",    THRESHOLDS["bias_min_amount"]),
        "bias_pct":      cfg.get("thresholds", {}).get("bias_pct",           THRESHOLDS["bias_pct"]),
    },
    "score_extractors": [
        lambda r: (r.get("provider_cuit"), r.get("provider_name")),
    ],
    "entity_extractors": {
        "authorizer": [lambda r: (r.get("authorizer"), r.get("authorizer"))],
    },
    "report_headers": ["Authorizer", "CUIT", "Company", "Contracts", "Total Signed", "Bias %", "Total (ARS real)", "Total USD"],
    "report_row": lambda r: [
        r["authorizer"][:30], r["provider_cuit"], r["provider_name"][:30],
        r["contracts_for_prov"], r["total_signed"], f"{r['bias_pct']}%",
        f"ARS {r['total_real_ars']:,.0f}",
        f"USD {r['total_real_usd']:,.0f}" if r.get("total_real_usd") else "—",
    ],
    "report_title": "AUTHORIZER BIAS — Official concentrates contracts on one provider (real ARS)",
    "ui_meta": {
        "description": (
            "Identifies public officials who authorize a disproportionate share of the contracts "
            "they sign in favour of a single company, above minimum contract-count and real-ARS "
            "amount thresholds. A signal of a captured authorizer or systematic favouritism."
        ),
        "color": "red",
        "columns": [
            col_authorizer("authorizer",       "Authorizer"),
            col_provider("provider_cuit",      "Favored Company", name_key="provider_name"),
            col_percentage("bias_pct",         "Bias %"),
            col_quantity("contracts_for_prov", "Contracts"),
            col_money("total_real_ars",        "Total (ARS real)", currency_key="ars_currency"),
            col_money("total_real_usd",        "Total USD",        currency_key="usd_currency"),
        ],
        "search_fields": ["authorizer", "provider_cuit", "provider_name"],
    },
    "i18n": {
        "es": {
            "label": "Sesgo del Autorizante",
            "description": (
                "Identifica funcionarios públicos que autorizan una proporción desmedida de los "
                "contratos que firman a favor de una sola empresa, por encima de umbrales mínimos "
                "de cantidad de contratos y monto en ARS reales. Señal de un autorizante "
                "capturado o favoritismo sistemático."
            ),
            "columns": {
                "authorizer":        "Autorizante",
                "provider_cuit":     "Empresa Favorecida",
                "bias_pct":          "% Sesgo",
                "contracts_for_prov": "Contratos",
                "total_real_ars":    "Total (ARS real)",
                "total_real_usd":    "Total USD",
            },
        },
    },
}
