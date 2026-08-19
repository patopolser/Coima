"""
cross_agency_proxy.py — Provider shares contact info with a contracting unit
but wins contracts from OTHER, unrelated units.

Signals an insider-connected shell company that exploits its state-sector
contacts to win contracts across multiple agencies.
"""

from src.detector.columns import col_unit, col_provider, col_list_contact

QUERY = """
// Find contact collisions between a contracting unit and a provider
MATCH (unit:ContractingUnit)-[:HAS_ADDRESS|HAS_PHONE|HAS_EMAIL]->(contact)<-[:HAS_ADDRESS|HAS_PHONE|HAS_EMAIL]-(prov:Provider)

// Provider must have won at least one contract from a DIFFERENT unit
MATCH (proc:Process)-[:GENERATES]->(cd:ContractualDocument)-[:AWARDED_TO]->(prov)
WHERE NOT (proc)-[:MANAGED_BY]->(unit)
  AND ($date_from IS NULL OR (proc.opening_date IS NOT NULL AND date(proc.opening_date) >= date($date_from)))
  AND ($date_to   IS NULL OR (proc.opening_date IS NOT NULL AND date(proc.opening_date) <= date($date_to)))

WITH unit, prov,
     coalesce(unit.code, 'N/A')                            AS unit_code,
     coalesce(unit.name, '—')                              AS unit_name,
     count(DISTINCT cd)                                    AS external_contracts_won,
     collect(DISTINCT {type: labels(contact)[0], contact: contact.value}) AS shared_contacts

RETURN
    unit_code,
    unit_name,
    prov.cuit                              AS provider_cuit,
    coalesce(prov.business_name, '—')     AS provider_name,
    external_contracts_won,
    shared_contacts
ORDER BY external_contracts_won DESC
LIMIT $limit
"""

CHECK = {
    "key":    "cross_agency_proxy",
    "label":  "Cross-Agency Proxy Company",
    "weight": 50,
    "query":  QUERY,
    "params": lambda cfg, limit: {"limit": limit},
    "score_extractors": [
        lambda r: (r.get("provider_cuit"), r.get("provider_name")),
    ],
    "entity_extractors": {
        "unit": [lambda r: (r.get("unit_code"), r.get("unit_name"))],
    },
    "report_headers": ["Unit", "Code", "CUIT", "Company", "External Wins", "Shared Contacts"],
    "report_row": lambda r: [
        r["unit_name"][:30], r["unit_code"],
        r["provider_cuit"], r["provider_name"][:30],
        r["external_contracts_won"],
        "; ".join(f"{c['type']}: {c['contact']}" for c in r["shared_contacts"])[:60],
    ],
    "report_title": "CROSS-AGENCY PROXY — Provider shares state contact info but wins contracts elsewhere",
    "ui_meta": {
        "description": (
            "High alert: a provider is registered with the same contact information "
            "(address, phone, or email) as a contracting unit, yet is winning "
            "contracts from other, unrelated units. Classic insider-connected "
            "shell company pattern."
        ),
        "color": "orange",
        "columns": [
            col_unit("unit_code",          "Unit",     name_key="unit_name"),
            col_provider("provider_cuit",  "Provider", name_key="provider_name"),
            col_list_contact("shared_contacts", "Shared Contacts"),
        ],
        "search_fields": ["unit_code", "unit_name", "provider_cuit", "provider_name"],
    },
    "i18n": {
        "es": {
            "label": "Empresa Proxy Interagencial",
            "description": (
                "Alerta alta: un proveedor está registrado con la misma información de contacto "
                "(dirección, teléfono o correo) que una unidad de contratación, pero gana "
                "contratos de otras unidades no relacionadas. Patrón clásico de "
                "empresa pantalla vinculada a funcionarios."
            ),
            "columns": {
                "unit_code":       "Unidad",
                "provider_cuit":   "Proveedor",
                "shared_contacts": "Contactos Compartidos",
            },
        },
    },
}
