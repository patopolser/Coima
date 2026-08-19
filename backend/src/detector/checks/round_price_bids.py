"""
round_price_bids.py — Providers with a high percentage of suspiciously round unit prices.

Aggregates across ALL processes: one row per provider showing their global
round-price rate. Only emits rows where the rate exceeds the configured threshold.
"""

from src.detector.columns import col_provider, col_percentage, col_quantity

QUERY = """
// All bid lines with a unit price above the minimum threshold
MATCH (proc:Process)-[:HAS_BID]->(bid:Bid)-[:HAS_BID_LINE]->(bl:BidLine)
MATCH (bid)-[:SUBMITTED_BY]->(prov:Provider)
WHERE bl.unit_price > $min_price
  AND ($date_from IS NULL OR (proc.opening_date IS NOT NULL AND date(proc.opening_date) >= date($date_from)))
  AND ($date_to   IS NULL OR (proc.opening_date IS NOT NULL AND date(proc.opening_date) <= date($date_to)))

// Count how many of each provider's lines are round (integer multiples of N)
WITH prov,
     count(bl) AS total_lines,
     sum(CASE WHEN bl.unit_price = toFloat(toInteger(bl.unit_price))
                   AND toInteger(bl.unit_price) % $round_modulo = 0
              THEN 1 ELSE 0 END) AS round_lines

WHERE total_lines >= $min_lines

WITH prov,
     total_lines,
     round_lines,
     round(100.0 * round_lines / total_lines, 1) AS round_pct

WHERE round_pct >= $min_round_pct

RETURN
    prov.cuit                              AS provider_cuit,
    coalesce(prov.business_name, '—')     AS provider_name,
    round_lines,
    total_lines,
    round_pct
ORDER BY round_pct DESC, total_lines DESC
LIMIT $limit
"""

THRESHOLDS = {
    "round_min_price": 10_000,
    "round_modulo":    10_000,
    "round_min_pct":   90.0,
    "round_min_lines": 5,
}

CHECK = {
    "key":    "round_price_bids",
    "label":  "Round-Price Bids",
    "weight": 5,
    "thresholds": THRESHOLDS,
    "query":  QUERY,
    "params": lambda cfg, limit: {
        "limit":         limit,
        "min_price":     cfg.get("thresholds", {}).get("round_min_price",  THRESHOLDS["round_min_price"]),
        "round_modulo":  cfg.get("thresholds", {}).get("round_modulo",     THRESHOLDS["round_modulo"]),
        "min_round_pct": cfg.get("thresholds", {}).get("round_min_pct",    THRESHOLDS["round_min_pct"]),
        "min_lines":     cfg.get("thresholds", {}).get("round_min_lines",  THRESHOLDS["round_min_lines"]),
    },
    "score_extractors": [
        lambda r: (r.get("provider_cuit"), r.get("provider_name")),
    ],
    "report_headers": ["CUIT", "Company", "Round Lines", "Total Lines", "Round %"],
    "report_row": lambda r: [
        r["provider_cuit"], r["provider_name"][:35],
        r["round_lines"], r["total_lines"], f"{r['round_pct']}%",
    ],
    "report_title": "ROUND-PRICE BIDS — Providers with suspiciously round unit prices",
    "ui_meta": {
        "description": (
            "Flags providers whose bid lines contain a high percentage of round unit prices "
            "(integer multiples of the configured modulo). A classic indicator of fabricated "
            "or coordinated pricing across procurement processes."
        ),
        "color": "yellow",
        "columns": [
            col_provider("provider_cuit", "Provider", name_key="provider_name"),
            col_percentage("round_pct",  "Round %"),
            col_quantity("round_lines",  "Round Lines"),
            col_quantity("total_lines",  "Total Lines"),
        ],
        "search_fields": ["provider_cuit", "provider_name"],
    },
    "i18n": {
        "es": {
            "label": "Ofertas con Precios Redondos",
            "description": (
                "Marca proveedores cuyas líneas de oferta contienen un alto porcentaje de "
                "precios unitarios redondos (múltiplos enteros del módulo configurado). "
                "Indicador clásico de precios fabricados o coordinados entre procesos de "
                "contratación."
            ),
            "columns": {
                "provider_cuit": "Proveedor",
                "round_pct":     "% Redondo",
                "round_lines":   "Líneas Redondas",
                "total_lines":   "Líneas Totales",
            },
        },
    },
}
