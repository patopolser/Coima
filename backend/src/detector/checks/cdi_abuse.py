"""
cdi_abuse.py — Contracting units that run a disproportionate share of their
procurement processes as Direct Contracting (Contratación Directa, CDI).

Direct contracting bypasses open competitive bidding, so a unit whose process
mix is dominated by CDI is a strong red flag for competition avoidance. A
process is treated as direct contracting when its process_type_code is 'CDI'
or its selection_procedure text mentions "directa".

Unit-level check (no per-provider score). One row per contracting unit.
"""

from src.detector.columns import col_unit, col_percentage, col_quantity

QUERY = """
MATCH (proc:Process)-[:MANAGED_BY]->(u:ContractingUnit)
WHERE ($date_from IS NULL OR (proc.opening_date IS NOT NULL AND date(proc.opening_date) >= date($date_from)))
  AND ($date_to   IS NULL OR (proc.opening_date IS NOT NULL AND date(proc.opening_date) <= date($date_to)))
WITH u,
     count(DISTINCT proc) AS total_tenders,
     count(DISTINCT CASE
        WHEN proc.process_type_code = 'CDI'
          OR (proc.selection_procedure IS NOT NULL
              AND toLower(proc.selection_procedure) CONTAINS 'directa')
        THEN proc END) AS cdi_processes
WHERE total_tenders >= $min_processes

WITH u, total_tenders, cdi_processes,
     round(100.0 * cdi_processes / total_tenders, 1) AS cdi_pct
WHERE cdi_pct >= $min_pct

RETURN
    u.code                            AS unit_code,
    coalesce(u.name, '—')            AS unit_name,
    total_tenders,
    cdi_processes,
    cdi_pct
ORDER BY cdi_pct DESC, total_tenders DESC
LIMIT $limit
"""

THRESHOLDS = {
    "cdi_min_processes": 10,
    "cdi_min_pct":       60.0,
}

CHECK = {
    "key":    "cdi_abuse",
    "label":  "Direct Contracting Abuse",
    "weight": 15,
    "thresholds": THRESHOLDS,
    "query":  QUERY,
    "params": lambda cfg, limit: {
        "limit":         limit,
        "min_processes": cfg.get("thresholds", {}).get("cdi_min_processes", THRESHOLDS["cdi_min_processes"]),
        "min_pct":       cfg.get("thresholds", {}).get("cdi_min_pct",       THRESHOLDS["cdi_min_pct"]),
    },
    "score_extractors": [],
    "entity_extractors": {
        "unit": [lambda r: (r.get("unit_code"), r.get("unit_name"))],
    },
    "report_headers": ["Unit", "Name", "Total", "CDI", "CDI %"],
    "report_row": lambda r: [
        r["unit_code"], r["unit_name"][:35],
        r["total_tenders"], r["cdi_processes"], f"{r['cdi_pct']}%",
    ],
    "report_title": "DIRECT CONTRACTING ABUSE — Units overusing Contratación Directa",
    "ui_meta": {
        "description": (
            "Flags contracting units that run a disproportionately high percentage of their "
            "procurement processes as Direct Contracting (Contratación Directa), bypassing open "
            "competitive bidding. A high direct-award rate is a classic signal of competition "
            "avoidance and favouritism."
        ),
        "color": "rose",
        "columns": [
            col_unit("unit_code",         "Unit",      name_key="unit_name"),
            col_percentage("cdi_pct",      "CDI %"),
            col_quantity("cdi_processes",  "Direct Contracts"),
            col_quantity("total_tenders",  "Total Processes"),
        ],
        "search_fields": ["unit_code", "unit_name"],
    },
    "i18n": {
        "es": {
            "label": "Abuso de Contratación Directa",
            "description": (
                "Marca unidades contratantes que ejecutan un porcentaje desproporcionadamente "
                "alto de sus procesos como Contratación Directa, evitando la licitación "
                "competitiva abierta. Una tasa elevada de adjudicación directa es una señal "
                "clásica de evasión de competencia y favoritismo."
            ),
            "columns": {
                "unit_code":      "Unidad",
                "cdi_pct":        "% Directa",
                "cdi_processes":  "Contrataciones Directas",
                "total_tenders":  "Procesos Totales",
            },
        },
    },
}
