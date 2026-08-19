"""
fake_competition.py — Processes where 2+ providers share contact information.

A process has fake competition when bidders that should be independent
share an address, phone, or email — indicating they may be controlled
by the same person or organization.
"""

from src.detector.columns import col_process, col_provider, col_list_contact

QUERY = """
MATCH (proc:Process)-[:HAS_BID]->(:Bid)-[:SUBMITTED_BY]->(prov1:Provider)
MATCH (proc)-[:HAS_BID]->(:Bid)-[:SUBMITTED_BY]->(prov2:Provider)
WHERE prov1.cuit < prov2.cuit
  AND ($date_from IS NULL OR (proc.opening_date IS NOT NULL AND date(proc.opening_date) >= date($date_from)))
  AND ($date_to   IS NULL OR (proc.opening_date IS NOT NULL AND date(proc.opening_date) <= date($date_to)))

// Find shared contact nodes between the two providers
MATCH (prov1)-[:HAS_ADDRESS|HAS_PHONE|HAS_EMAIL]->(contact)<-[:HAS_ADDRESS|HAS_PHONE|HAS_EMAIL]-(prov2)

WITH proc, prov1, prov2,
     collect(DISTINCT {type: labels(contact)[0], contact: contact.value}) AS shared_contacts
WHERE size(shared_contacts) > 0

RETURN
    proc.process_number                    AS process_number,
    proc.source_url                        AS process_url,
    prov1.cuit                             AS provider1_cuit,
    coalesce(prov1.business_name, '—')    AS provider1_name,
    prov2.cuit                             AS provider2_cuit,
    coalesce(prov2.business_name, '—')    AS provider2_name,
    shared_contacts
ORDER BY process_number DESC
LIMIT $limit
"""

CHECK = {
    "key":    "fake_competition",
    "label":  "Fake Competition",
    "weight": 35,
    "query":  QUERY,
    "params": lambda cfg, limit: {"limit": limit},
    "score_extractors": [
        lambda r: (r.get("provider1_cuit"), r.get("provider1_name")),
        lambda r: (r.get("provider2_cuit"), r.get("provider2_name")),
    ],
    "report_headers": ["Process", "CUIT 1", "Company 1", "CUIT 2", "Company 2", "Shared Contacts"],
    "report_row": lambda r: [
        r["process_number"],
        r["provider1_cuit"], r["provider1_name"][:30],
        r["provider2_cuit"], r["provider2_name"][:30],
        "; ".join(f"{c['type']}: {c['contact']}" for c in r["shared_contacts"])[:60],
    ],
    "report_title": "FAKE COMPETITION — Bidders sharing contact info in the same process",
    "ui_meta": {
        "description": (
            "Detects processes where two or more distinct providers submitted bids "
            "while sharing at least one contact point (address, phone, or email). "
            "A strong indicator of coordinated bidding or shell-company cartels."
        ),
        "color": "red",
        "columns": [
            col_process("process_number",  "Process",    url_key="process_url"),
            col_provider("provider1_cuit", "Provider 1", name_key="provider1_name"),
            col_provider("provider2_cuit", "Provider 2", name_key="provider2_name"),
            col_list_contact("shared_contacts", "Shared Contacts"),
        ],
        "search_fields": ["process_number", "provider1_cuit", "provider1_name",
                          "provider2_cuit", "provider2_name"],
    },
    "i18n": {
        "es": {
            "label": "Competencia Falsa",
            "description": (
                "Detecta procesos en los que dos o más proveedores distintos presentaron "
                "ofertas compartiendo al menos un punto de contacto (dirección, teléfono o "
                "correo). Indicador fuerte de ofertas coordinadas o cárteles de empresas pantalla."
            ),
            "columns": {
                "process_number": "Proceso",
                "provider1_cuit": "Proveedor 1",
                "provider2_cuit": "Proveedor 2",
                "shared_contacts": "Contactos Compartidos",
            },
        },
    },
}
