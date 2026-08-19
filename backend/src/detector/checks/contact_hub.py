"""
contact_hub.py — A single contact node (address, phone or email) shared by an
unusually high number of distinct providers.

Detects "shell company farms": many supposedly independent bidders that all route
through the same address/phone/email, suggesting common control. This is the
many-to-one counterpart to fake_competition (pairwise contact sharing inside one
process). Informational only — it does not contribute to the per-CUIT risk score
(score_extractors is empty) because the finding is about the contact node, not a
single company.
"""

from src.detector.columns import col_string, col_quantity, col_list_string

QUERY = """
MATCH (contact)<-[:HAS_ADDRESS|HAS_PHONE|HAS_EMAIL]-(prov:Provider)
WHERE labels(contact)[0] IN ['Address', 'Phone', 'Email']

WITH contact,
     labels(contact)[0]            AS contact_type,
     count(DISTINCT prov)          AS provider_count,
     collect(DISTINCT prov)        AS providers
WHERE provider_count >= $min_providers

// A reference process URL from any member, for quick navigation
OPTIONAL MATCH (p:Provider)<-[:SUBMITTED_BY]-(:Bid)<-[:HAS_BID]-(proc:Process)
WHERE p IN providers
WITH contact, contact_type, provider_count, providers, proc
ORDER BY proc.scraped_at DESC
WITH contact, contact_type, provider_count, providers, collect(proc)[0] AS proc

RETURN
    contact_type,
    contact.value                                                                 AS contact_value,
    provider_count,
    [pr IN providers | pr.cuit + ' (' + coalesce(pr.business_name, '—') + ')'] AS member_samples,
    proc.source_url                                                               AS ref_url
ORDER BY provider_count DESC
LIMIT $limit
"""

THRESHOLDS = {
    "hub_min_providers": 5,
}

CHECK = {
    "key":    "contact_hub_multi_provider",
    "label":  "Provider Contact Hub",
    "weight": 30,
    "thresholds": THRESHOLDS,
    "query":  QUERY,
    "params": lambda cfg, limit: {
        "limit":         limit,
        "min_providers": cfg.get("thresholds", {}).get("hub_min_providers", THRESHOLDS["hub_min_providers"]),
    },
    "score_extractors": [],
    "report_headers": ["Type", "Contact", "Providers", "Members"],
    "report_row": lambda r: [
        r["contact_type"], r["contact_value"][:40],
        r["provider_count"], ", ".join(r["member_samples"]),
    ],
    "report_title": "CONTACT HUB — Many providers sharing a single contact point",
    "ui_meta": {
        "description": (
            "Detects 'shell company farms': a single address, phone, or email shared by an "
            "unusually high number of distinct providers. Strong indicator of a network of "
            "front companies under common control."
        ),
        "color": "purple",
        "columns": [
            col_string("contact_value",   "Contact"),
            col_string("contact_type",    "Type"),
            col_quantity("provider_count", "Providers"),
            col_list_string("member_samples", "Members"),
        ],
        "search_fields": ["contact_value", "contact_type"],
    },
    "i18n": {
        "es": {
            "label": "Centro de Contacto de Proveedores",
            "description": (
                "Detecta 'granjas de empresas pantalla': una misma dirección, teléfono o correo "
                "compartido por una cantidad inusualmente alta de proveedores distintos. "
                "Indicador fuerte de una red de empresas fachada bajo control común."
            ),
            "columns": {
                "contact_value":  "Contacto",
                "contact_type":   "Tipo",
                "provider_count": "Proveedores",
                "member_samples": "Miembros",
            },
        },
    },
}
