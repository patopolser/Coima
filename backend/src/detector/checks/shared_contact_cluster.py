"""
shared_contact_cluster.py — Clusters of providers linked through shared contact
data (address / phone / email) that ALSO bid against each other.

This generalizes two existing checks and combines their signals:
  * fake_competition  — a *pair* sharing a contact inside *one* process.
  * contact_hub       — many providers on a *single* contact node.
Here we take the transitive closure of contact sharing (connected components of
the contact graph) and then confirm collusion by intersecting with the co-bidding
graph: a cluster is flagged only when its members not only share contacts but also
turn up bidding in the same processes. Common ownership plus joint bidding is a far
stronger signal than either alone.

Python analyzer (uses `run`). One finding row per cluster member.
"""

from src.detector.columns import (
    col_provider, col_quantity, col_list_string, col_list_contact,
)
from src.detector.analytics import build_contact_graph, fetch_process_outcomes
from src.detector.date_filter import date_params

import networkx as nx

THRESHOLDS = {
    "cluster_min_members":          2,   # a contact cluster needs at least this many providers
    "cluster_min_cobid_processes":  1,   # processes where >=2 cluster members jointly bid
}


def _parse_contact(raw):
    """Contacts arrive as 'Type:value' (e.g. 'Email:a@b.com'). Split into
    {type, contact} so the UI renders them with the contact icon, like
    fake_competition."""
    label, _, value = str(raw).partition(":")
    return {"type": label, "contact": value}


def _run(driver, cfg, limit):
    t = cfg.get("thresholds", {})
    min_mem   = t.get("cluster_min_members",         THRESHOLDS["cluster_min_members"])
    min_cobid = t.get("cluster_min_cobid_processes", THRESHOLDS["cluster_min_cobid_processes"])

    dates = date_params(cfg)
    contact_graph = build_contact_graph(driver)

    clusters = []
    for component in nx.connected_components(contact_graph):
        if len(component) < min_mem:
            continue
        members = sorted(component)

        # Confirm the contact cluster also bids together.
        outcomes = fetch_process_outcomes(driver, members, dates=dates)
        cobid_processes = len(outcomes)
        if cobid_processes < min_cobid:
            continue

        # Distinct shared contacts inside the cluster (for the evidence column).
        sub_contact = contact_graph.subgraph(members)
        shared_contacts = set()
        for _, _, d in sub_contact.edges(data=True):
            shared_contacts.update(d.get("contacts", []))

        # How many of the cluster's members ever win — pure ownership shells often
        # field cover bidders that never win.
        winners = set()
        for row in outcomes:
            winners.update(w for w in (row.get("winners") or []) if w in component)

        clusters.append({
            "members": members,
            "cobid_processes": cobid_processes,
            "shared_contacts": sorted(shared_contacts),
            "distinct_winners": len(winners),
        })

    clusters.sort(key=lambda c: (c["cobid_processes"], len(c["members"])), reverse=True)

    rows = []
    for cluster_id, cl in enumerate(clusters, start=1):
        members = cl["members"]
        for cuit in members:
            others = [m for m in members if m != cuit]
            rows.append({
                "cluster_id":       cluster_id,
                "provider_cuit":    cuit,
                "provider_name":    contact_graph.nodes[cuit].get("name", "—"),
                "cluster_size":     len(members),
                "cobid_processes":  cl["cobid_processes"],
                "distinct_winners": cl["distinct_winners"],
                "shared_contacts":  [_parse_contact(c) for c in cl["shared_contacts"][:12]],
                "co_members":       [{"text": f"{m} ({contact_graph.nodes[m].get('name', '—')})"} for m in others][:20],
            })
            if len(rows) >= limit:
                return rows
    return rows


CHECK = {
    "key":    "shared_contact_cluster",
    "label":  "Shared-Contact Cluster",
    "weight": 40,
    "thresholds": THRESHOLDS,
    "run":    _run,
    "score_extractors": [
        lambda r: (r.get("provider_cuit"), r.get("provider_name")),
    ],
    "report_headers": ["Cluster", "CUIT", "Company", "Size", "Co-bid Procs", "Winners"],
    "report_row": lambda r: [
        r["cluster_id"], r["provider_cuit"], r["provider_name"][:25],
        r["cluster_size"], r["cobid_processes"], r["distinct_winners"],
    ],
    "report_title": "SHARED-CONTACT CLUSTER — Contact-linked providers that also bid together",
    "ui_meta": {
        "description": (
            "Builds the transitive cluster of providers connected through shared address/phone/email "
            "and confirms collusion by checking they also bid in the same processes. Generalizes "
            "fake_competition (a contact-sharing pair in one process) and contact_hub (one contact, "
            "many providers) to whole ownership clusters that jointly participate in tenders — a "
            "strong indicator of shell companies under common control simulating competition."
        ),
        "color": "fuchsia",
        "columns": [
            col_provider("provider_cuit", "Provider", name_key="provider_name"),
            col_quantity("cluster_size",     "Cluster Size"),
            col_quantity("cobid_processes",  "Co-bid Processes"),
            col_quantity("distinct_winners", "Distinct Winners"),
            col_list_contact("shared_contacts", "Shared Contacts"),
            col_list_string("co_members",       "Other Members"),
        ],
        "search_fields": ["provider_cuit", "provider_name"],
    },
    "i18n": {
        "es": {
            "label": "Cluster de Contacto Compartido",
            "description": (
                "Construye el cluster transitivo de proveedores conectados por dirección/teléfono/email "
                "compartido y confirma la connivencia verificando que además licitan en los mismos "
                "procesos. Generaliza fake_competition (un par que comparte contacto en un proceso) y "
                "contact_hub (un contacto, muchos proveedores) a clusters de propiedad común que "
                "participan juntos en licitaciones: indicio fuerte de empresas pantalla bajo control "
                "común simulando competencia."
            ),
            "columns": {
                "provider_cuit":    "Proveedor",
                "cluster_size":     "Tamaño del Cluster",
                "cobid_processes":  "Procesos Co-licitados",
                "distinct_winners": "Ganadores Distintos",
                "shared_contacts":  "Contactos Compartidos",
                "co_members":       "Otros Miembros",
            },
        },
    },
}
