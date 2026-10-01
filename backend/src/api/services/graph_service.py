"""
src/api/services/graph_service.py - Entity-centric neighbourhood graphs.

Every graph is built around a single anchor entity and summarises the relevant
2-hop paths in the data model into direct, frontend-friendly edges:

    (Process)-[:GENERATES]->(ContractualDocument)-[:AWARDED_TO]->(Provider) -> WON
    (Process)-[:HAS_BID]->(Bid)-[:SUBMITTED_BY]->(Provider)                 -> BID
    (Process)-[:MANAGED_BY]->(ContractingUnit)                              -> MANAGED
    (ContractualDocument)-[:AUTHORIZED_BY]->(Authorizer)                    -> AUTHORIZED
    (Provider)-[:HAS_ADDRESS|HAS_PHONE|HAS_EMAIL]->(contact)                -> CONTACT

Nodes carry their real Neo4j element_id, so graphs fetched for different
anchors merge seamlessly on the canvas. Each builder returns
`{nodes, edges}`, or None when the anchor entity does not exist. Used by
routers/graph.py and the MCP server.
"""

from __future__ import annotations

from typing import Optional

from neo4j import Driver, NotificationClassification

# Anchor date for a process: opening, else scheduled portal, else gazette publish.
_PROC_ANCHOR = (
    "coalesce(proc.opening_date, proc.scheduled_portal_publish_date, "
    "proc.official_gazette_publish_date)"
)

# Date-range guard shared by every query. `anchor` is bound by the caller.
_DATE_FILTER = (
    "($date_from IS NULL OR (anchor IS NOT NULL AND date(anchor) >= date($date_from))) "
    "AND ($date_to IS NULL OR (anchor IS NOT NULL AND date(anchor) <= date($date_to)))"
)

# ── Provider-anchored queries ──────────────────────────────────────────────
_WON_QUERY = f"""
MATCH (c:Provider {{cuit: $cuit}})
MATCH (proc:Process)-[:GENERATES]->(cd:ContractualDocument)-[:AWARDED_TO]->(c)
WITH c, proc,
     {_PROC_ANCHOR}                                            AS anchor,
     sum(coalesce(cd.total_amount, 0))                         AS won_amount,
     head(collect(DISTINCT coalesce(cd.currency, 'ARS')))      AS currency
WHERE {_DATE_FILTER}
RETURN c, proc, won_amount, currency
"""

_BID_QUERY = f"""
MATCH (c:Provider {{cuit: $cuit}})
MATCH (proc:Process)-[:HAS_BID]->(bid:Bid)-[:SUBMITTED_BY]->(c)
WITH c, proc,
     {_PROC_ANCHOR}                                            AS anchor,
     sum(coalesce(bid.total_amount, 0))                        AS bid_amount,
     head(collect(DISTINCT coalesce(bid.currency, 'ARS')))     AS currency
WHERE {_DATE_FILTER}
RETURN c, proc, bid_amount, currency
"""

# Two-hop contact network: this provider -> a shared Address/Phone/Email ->
# every OTHER provider sharing that same contact. The 1-hop version only
# surfaced dangling contact nodes; this is what actually forms a network and
# makes the "shared only" filter meaningful.
_CONTACTS_QUERY = """
MATCH (c:Provider {cuit: $cuit})-[:HAS_ADDRESS|HAS_PHONE|HAS_EMAIL]->(contact)
WHERE labels(contact)[0] IN ['Address', 'Phone', 'Email']
OPTIONAL MATCH (contact)<-[:HAS_ADDRESS|HAS_PHONE|HAS_EMAIL]-(other:Provider)
               WHERE other.cuit <> $cuit
RETURN contact, collect(DISTINCT other) AS others
"""

# ── Unit-anchored query ────────────────────────────────────────────────────
# Unit -> its processes -> the providers awarded each process.
_UNIT_QUERY = f"""
MATCH (u:ContractingUnit {{code: $code}})
MATCH (proc:Process)-[:MANAGED_BY]->(u)
WITH u, proc, {_PROC_ANCHOR} AS anchor
WHERE {_DATE_FILTER}
OPTIONAL MATCH (proc)-[:GENERATES]->(cd:ContractualDocument)-[:AWARDED_TO]->(prov:Provider)
WITH u, proc, prov,
     sum(coalesce(cd.total_amount, 0))                         AS won_amount,
     head(collect(DISTINCT coalesce(cd.currency, 'ARS')))      AS currency
RETURN u, proc, prov, won_amount, currency
"""

# ── Authorizer-anchored query ──────────────────────────────────────────────
# Authorizer -> documents they signed -> the process and awarded provider.
_AUTHORIZER_QUERY = f"""
MATCH (auth:Authorizer {{full_name: $name}})
MATCH (cd:ContractualDocument)-[:AUTHORIZED_BY]->(auth)
MATCH (proc:Process)-[:GENERATES]->(cd)
WITH auth, proc, cd, {_PROC_ANCHOR} AS anchor
WHERE {_DATE_FILTER}
OPTIONAL MATCH (cd)-[:AWARDED_TO]->(prov:Provider)
WITH auth, proc, prov,
     sum(coalesce(cd.total_amount, 0))                         AS won_amount,
     head(collect(DISTINCT coalesce(cd.currency, 'ARS')))      AS currency
RETURN auth, proc, prov, won_amount, currency
"""


def _contact_label(node) -> str:
    labels = list(node.labels)
    if "Provider" in labels:
        return node.get("business_name", node.get("cuit", "Provider"))
    if "Email" in labels or "Phone" in labels or "Address" in labels:
        return node.get("value", labels[0])
    return labels[0] if labels else "Unknown"


def _provider_node(c, cuit: Optional[str] = None) -> dict:
    cuit = cuit if cuit is not None else c.get("cuit")
    return {
        "id": str(c.element_id),
        "label": c.get("business_name", cuit),
        "group": "Provider",
        "cuit": cuit,
    }


def _process_node(proc) -> dict:
    return {
        "id": str(proc.element_id),
        "label": proc.get("process_number", "Process"),
        "group": "Process",
        "process_number": proc.get("process_number"),
        "source_url": proc.get("source_url"),
        "status": proc.get("status"),
        "opening_date": str(proc.get("opening_date")) if proc.get("opening_date") else None,
    }


def _unit_node(u) -> dict:
    return {
        "id": str(u.element_id),
        "label": u.get("name", u.get("code", "Unit")),
        "group": "ContractingUnit",
        "code": u.get("code"),
        "name": u.get("name"),
    }


def _authorizer_node(auth) -> dict:
    name = auth.get("full_name", "Authorizer")
    return {
        "id": str(auth.element_id),
        "label": name,
        "group": "Authorizer",
        "name": name,
    }


def _fmt_amount(amount, currency: str) -> str:
    """Compact edge label: 1_234_567 -> 'ARS 1.2M' (K/M/B/T suffixes)."""
    if not amount:
        return ""
    for div, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(amount) >= div:
            value = amount / div
            text = f"{value:.0f}" if abs(value) >= 100 else f"{value:.1f}".rstrip("0").rstrip(".")
            return f"{currency} {text}{suffix}"
    return f"{currency} {amount:,.0f}"


def _won_edge(source_id: str, proc_id: str, amount, currency: str, show_earnings: bool) -> dict:
    """Process -> provider WON edge. source_id is the process node id."""
    return {
        "id": f"won-{source_id}-{proc_id}",
        "source": source_id,
        "target": proc_id,
        "kind": "WON",
        "amount": amount,
        "currency": currency,
        "label": _fmt_amount(amount, currency) if show_earnings else "",
    }


def _session(driver):
    # _PROC_ANCHOR references optional date properties (e.g.
    # official_gazette_publish_date) that may be absent on every Process in the
    # current data, which makes Neo4j emit a benign "property key does not
    # exist" notification. coalesce() handles missing keys correctly, so we
    # suppress that UNRECOGNIZED-class notification for this session only.
    return driver.session(
        notifications_disabled_classifications=[NotificationClassification.UNRECOGNIZED]
    )


def _result(nodes: dict, edges: list) -> dict:
    unique_edges = list({e["id"]: e for e in edges}.values())
    return {"nodes": list(nodes.values()), "edges": unique_edges}


def company_graph(
    driver: Driver,
    cuit: str,
    *,
    won_only: bool = False,
    show_bids: bool = True,
    show_earnings: bool = False,
    show_contacts: bool = True,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Optional[dict]:
    """Provider-centric graph: won/bid processes plus the shared-contact network."""
    nodes: dict = {}
    edges: list = []
    provider_id: Optional[str] = None
    params = {"cuit": cuit, "date_from": date_from, "date_to": date_to}

    with _session(driver) as session:
        rec = session.run(
            "MATCH (c:Provider {cuit: $cuit}) RETURN c", cuit=cuit
        ).single()
        if rec is not None:
            c = rec["c"]
            provider_id = str(c.element_id)
            nodes[provider_id] = _provider_node(c, cuit)

        won_proc_ids: set[str] = set()
        for record in session.run(_WON_QUERY, **params):
            proc = record["proc"]
            pid = str(proc.element_id)
            nodes.setdefault(pid, _process_node(proc))
            won_proc_ids.add(pid)
            edges.append(
                _won_edge(provider_id, pid, record["won_amount"], record["currency"], show_earnings)
            )

        if show_bids and not won_only:
            for record in session.run(_BID_QUERY, **params):
                proc = record["proc"]
                pid = str(proc.element_id)
                # Already attached as WON; do not also add a BID edge.
                if pid in won_proc_ids:
                    continue
                nodes.setdefault(pid, _process_node(proc))
                edges.append({
                    "id": f"bid-{provider_id}-{pid}",
                    "source": provider_id,
                    "target": pid,
                    "kind": "BID",
                    "amount": record["bid_amount"],
                    "currency": record["currency"],
                    "label": "",
                })

        if show_contacts:
            for record in session.run(_CONTACTS_QUERY, cuit=cuit):
                contact = record["contact"]
                if contact is None:
                    continue
                contact_id = str(contact.element_id)
                nodes.setdefault(contact_id, {
                    "id": contact_id,
                    "label": _contact_label(contact),
                    "group": list(contact.labels)[0] if contact.labels else "Unknown",
                    "cuit": None,
                })
                # Anchor provider -> shared contact.
                edges.append({
                    "id": f"contact-{provider_id}-{contact_id}",
                    "source": provider_id,
                    "target": contact_id,
                    "kind": "CONTACT",
                    "label": "",
                })
                # Every other provider sharing this contact.
                for other in record["others"]:
                    if other is None:
                        continue
                    oid = str(other.element_id)
                    nodes.setdefault(oid, _provider_node(other))
                    edges.append({
                        "id": f"contact-{oid}-{contact_id}",
                        "source": oid,
                        "target": contact_id,
                        "kind": "CONTACT",
                        "label": "",
                    })

    if provider_id is None:
        return None
    return _result(nodes, edges)


def unit_graph(
    driver: Driver,
    code: str,
    *,
    show_earnings: bool = False,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Optional[dict]:
    """Unit-centric graph: the unit, the processes it manages and the providers awarded them."""
    nodes: dict = {}
    edges: list = []
    unit_id: Optional[str] = None
    params = {"code": code, "date_from": date_from, "date_to": date_to}

    with _session(driver) as session:
        rec = session.run(
            "MATCH (u:ContractingUnit {code: $code}) RETURN u", code=code
        ).single()
        if rec is not None:
            u = rec["u"]
            unit_id = str(u.element_id)
            nodes[unit_id] = _unit_node(u)

        for record in session.run(_UNIT_QUERY, **params):
            proc = record["proc"]
            pid = str(proc.element_id)
            if pid not in nodes:
                nodes[pid] = _process_node(proc)
                edges.append({
                    "id": f"managed-{unit_id}-{pid}",
                    "source": unit_id,
                    "target": pid,
                    "kind": "MANAGED",
                    "label": "",
                })
            prov = record["prov"]
            if prov is not None:
                prov_id = str(prov.element_id)
                nodes.setdefault(prov_id, _provider_node(prov))
                edges.append(
                    _won_edge(prov_id, pid, record["won_amount"], record["currency"], show_earnings)
                )

    if unit_id is None:
        return None
    return _result(nodes, edges)


def authorizer_graph(
    driver: Driver,
    name: str,
    *,
    show_earnings: bool = False,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Optional[dict]:
    """Authorizer-centric graph: the documents they signed, their processes and awarded providers."""
    nodes: dict = {}
    edges: list = []
    auth_id: Optional[str] = None
    params = {"name": name, "date_from": date_from, "date_to": date_to}

    with _session(driver) as session:
        rec = session.run(
            "MATCH (auth:Authorizer {full_name: $name}) RETURN auth", name=name
        ).single()
        if rec is not None:
            auth = rec["auth"]
            auth_id = str(auth.element_id)
            nodes[auth_id] = _authorizer_node(auth)

        for record in session.run(_AUTHORIZER_QUERY, **params):
            proc = record["proc"]
            pid = str(proc.element_id)
            if pid not in nodes:
                nodes[pid] = _process_node(proc)
                edges.append({
                    "id": f"authorized-{auth_id}-{pid}",
                    "source": auth_id,
                    "target": pid,
                    "kind": "AUTHORIZED",
                    "label": "",
                })
            prov = record["prov"]
            if prov is not None:
                prov_id = str(prov.element_id)
                nodes.setdefault(prov_id, _provider_node(prov))
                edges.append(
                    _won_edge(prov_id, pid, record["won_amount"], record["currency"], show_earnings)
                )

    if auth_id is None:
        return None
    return _result(nodes, edges)
