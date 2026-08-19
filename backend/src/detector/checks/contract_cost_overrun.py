"""
contract_cost_overrun.py — Public-works (contratar) contracts whose amount grew
well beyond the originally awarded figure through ampliaciones.

A contract awarded at one price and then expanded via "Ampliación" revisions is a
classic obra-pública red flag (sobrecosto): the competitive stage prices a small
contract, then the real cost balloons under modifications that never faced open
competition. The Argentine public-works regime caps modifications (commonly around
±20%); a contract whose current amount exceeds its original by more than the
configured percentage is an indicator worth human review.

The signal is contratar-specific: it relies on the portal's "Importe Vigente"
(current_amount) and "Porcentaje Variación" (variation_pct) fields, which COMPR.AR
does not expose. variation_pct is the portal's own figure (already a percentage,
e.g. 30.0 = 30%); when absent it is derived from current vs original amount.

One row per ContractualDocument. Targets the awarded provider and the managing unit.
"""

from src.detector.columns import (
    col_process,
    col_unit,
    col_provider,
    col_string,
    col_money,
    col_percentage,
)

QUERY = """
MATCH (proc:Process)-[:GENERATES]->(cd:ContractualDocument)-[:AWARDED_TO]->(prov:Provider)
MATCH (proc)-[:MANAGED_BY]->(u:ContractingUnit)
WHERE coalesce(proc.source, 'comprar') = 'contratar'
  AND cd.total_amount IS NOT NULL AND cd.total_amount > 0
  AND (cd.variation_pct IS NOT NULL OR cd.current_amount IS NOT NULL)
  AND ($date_from IS NULL OR (proc.opening_date IS NOT NULL AND date(proc.opening_date) >= date($date_from)))
  AND ($date_to   IS NULL OR (proc.opening_date IS NOT NULL AND date(proc.opening_date) <= date($date_to)))

// Prefer the portal's own variation figure; fall back to current vs original.
WITH proc, u, prov, cd,
     CASE WHEN cd.variation_pct IS NOT NULL THEN cd.variation_pct
          WHEN cd.current_amount IS NOT NULL AND cd.current_amount > 0
               THEN round(100.0 * (cd.current_amount - cd.total_amount) / cd.total_amount, 1)
          ELSE null END                                          AS overrun_pct
WHERE overrun_pct IS NOT NULL AND overrun_pct >= $min_overrun_pct

RETURN
    proc.process_number                    AS process,
    proc.source_url                        AS process_url,
    u.code                                 AS unit_code,
    coalesce(u.name, '—')                 AS unit_name,
    prov.cuit                              AS provider_cuit,
    coalesce(prov.business_name, '—')     AS provider_name,
    cd.document_number                     AS document_number,
    round(cd.total_amount, 2)              AS original_amount,
    round(coalesce(cd.current_amount, cd.total_amount), 2) AS current_amount,
    overrun_pct,
    coalesce(cd.currency, 'ARS')          AS currency
ORDER BY overrun_pct DESC, current_amount DESC
LIMIT $limit
"""

THRESHOLDS = {
    "overrun_min_pct": 20.0,
}

CHECK = {
    "key":    "contract_cost_overrun",
    "label":  "Contract Cost Overrun",
    "weight": 25,
    "thresholds": THRESHOLDS,
    "query":  QUERY,
    "params": lambda cfg, limit: {
        "limit":          limit,
        "min_overrun_pct": cfg.get("thresholds", {}).get("overrun_min_pct", THRESHOLDS["overrun_min_pct"]),
    },
    "score_extractors": [
        lambda r: (r.get("provider_cuit"), r.get("provider_name")),
    ],
    "entity_extractors": {
        "unit": [lambda r: (r.get("unit_code"), r.get("unit_name"))],
    },
    "report_headers": ["Process", "Unit", "CUIT", "Company", "Doc", "Original", "Current", "Overrun %"],
    "report_row": lambda r: [
        r["process"], r["unit_code"], r["provider_cuit"], r["provider_name"][:25],
        r["document_number"],
        f"{r['currency']} {r['original_amount']:,.0f}",
        f"{r['currency']} {r['current_amount']:,.0f}",
        f"{r['overrun_pct']}%",
    ],
    "report_title": "CONTRACT COST OVERRUN — Public-works contracts expanded well beyond the awarded amount",
    "ui_meta": {
        "description": (
            "Detects public-works (contratar) contracts whose current amount exceeds the "
            "originally awarded amount by more than the configured percentage, driven by "
            "ampliaciones. Large overruns on a contract that was competed at a lower price are a "
            "classic obra-pública red flag, since the modification regime is normally capped."
        ),
        "color": "rose",
        "columns": [
            col_process("process",          "Process",  url_key="process_url"),
            col_unit("unit_code",            "Unit",     name_key="unit_name"),
            col_provider("provider_cuit",    "Provider", name_key="provider_name"),
            col_string("document_number",    "Doc"),
            col_money("original_amount",     "Original", currency_key="currency"),
            col_money("current_amount",      "Current",  currency_key="currency"),
            col_percentage("overrun_pct",    "Overrun %"),
        ],
        "search_fields": ["process", "unit_code", "unit_name", "provider_cuit", "provider_name", "document_number"],
    },
    "i18n": {
        "es": {
            "label": "Sobrecosto de Contrato",
            "description": (
                "Detecta contratos de obra pública (contratar) cuyo importe vigente supera al "
                "monto originalmente adjudicado en más del porcentaje configurado, por efecto de "
                "ampliaciones. Sobrecostos grandes sobre un contrato que se compitió a un precio "
                "menor son una señal clásica de obra pública, ya que el régimen de modificaciones "
                "suele estar topeado."
            ),
            "columns": {
                "process":         "Proceso",
                "unit_code":       "Unidad",
                "provider_cuit":   "Proveedor",
                "document_number": "Doc",
                "original_amount": "Original",
                "current_amount":  "Vigente",
                "overrun_pct":     "% Sobrecosto",
            },
        },
    },
}
