"""
src/api/services/tender_service.py - Procurement process (Process node)
search and detail straight from Neo4j, plus the detection findings that
reference a process.

Property and relationship names follow scraper/SCHEMA.md:

    (Process)-[:MANAGED_BY]->(ContractingUnit)-[:BELONGS_TO]->(Organization)
    (Process)-[:HAS_BID]->(Bid)-[:SUBMITTED_BY]->(Provider)
    (Process)-[:GENERATES]->(ContractualDocument)-[:AWARDED_TO]->(Provider)
    (ContractualDocument)-[:AUTHORIZED_BY]->(Authorizer)
    (Process)-[:HAS_DICTAMEN]->(Dictamen)-[:PRE_ADJUDICATES|REJECTED]->(Provider)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from neo4j import READ_ACCESS, Driver, NotificationClassification

from ..database.neo4j import to_jsonable

# Anchor date for a process: opening, else scheduled portal, else gazette publish.
_PROC_ANCHOR = (
    "coalesce(proc.opening_date, proc.scheduled_portal_publish_date, "
    "proc.official_gazette_publish_date)"
)

_PROC_SUMMARY = (
    "proc{.process_number, .source, .descriptive_name, .object_of_procurement, "
    ".selection_procedure, .process_type_code, .status, .stage, .opening_date, "
    ".participating_providers_count, .confirmed_offers_count, .source_url}"
)


def _session(driver: Driver):
    # The date coalesce references properties absent on some datasets; Neo4j
    # reports each as an UNRECOGNIZED notification, which is noise here.
    return driver.session(
        default_access_mode=READ_ACCESS,
        notifications_disabled_classifications=[NotificationClassification.UNRECOGNIZED],
    )


def _compact(d: Dict[str, Any]) -> Dict[str, Any]:
    """Drop null properties; scraped nodes leave many optional fields empty."""
    return {k: v for k, v in to_jsonable(d).items() if v is not None}


# Finding fields that referenced a process before checks declared typed columns.
_LEGACY_PROCESS_FIELDS = ("process", "voided_process", "direct_process")


def search_tenders(
    driver: Driver,
    *,
    text: Optional[str] = None,
    cuit: Optional[str] = None,
    unit_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 25,
) -> List[Dict[str, Any]]:
    """
    Processes matching every given filter, newest first. `text` matches the
    process number, descriptive name or object (case-insensitive); `cuit`
    keeps processes the provider bid on or was awarded.
    """
    if cuit:
        match = (
            "MATCH (:Provider {cuit: $cuit})<-[:SUBMITTED_BY|AWARDED_TO]-()"
            "<-[:HAS_BID|GENERATES]-(proc:Process)\n"
            "WITH DISTINCT proc\n"
        )
        if unit_code:
            match += "MATCH (proc)-[:MANAGED_BY]->(:ContractingUnit {code: $unit_code})\n"
    elif unit_code:
        match = "MATCH (proc:Process)-[:MANAGED_BY]->(:ContractingUnit {code: $unit_code})\n"
    else:
        match = "MATCH (proc:Process)\n"

    query = match + f"""
WITH proc, {_PROC_ANCHOR} AS anchor
WHERE ($text IS NULL
       OR toLower(proc.process_number) CONTAINS $text
       OR toLower(coalesce(proc.descriptive_name, '')) CONTAINS $text
       OR toLower(coalesce(proc.object_of_procurement, '')) CONTAINS $text)
  AND ($date_from IS NULL OR (anchor IS NOT NULL AND date(anchor) >= date($date_from)))
  AND ($date_to IS NULL OR (anchor IS NOT NULL AND date(anchor) <= date($date_to)))
WITH proc, anchor
// DESC puts nulls first in Cypher; keep undated processes last.
ORDER BY anchor IS NULL, anchor DESC
LIMIT $limit
OPTIONAL MATCH (proc)-[:MANAGED_BY]->(u:ContractingUnit)
RETURN {_PROC_SUMMARY} AS process,
       u.code AS unit_code, u.name AS unit_name,
       [(proc)-[:GENERATES]->(:ContractualDocument)-[:AWARDED_TO]->(w:Provider)
        | {{cuit: w.cuit, name: w.business_name}}] AS awarded_to,
       COUNT {{ (proc)-[:HAS_BID]->(:Bid) }} AS bid_count
"""
    params = {
        "text": text.lower() if text else None,
        "cuit": cuit,
        "unit_code": unit_code,
        "date_from": date_from,
        "date_to": date_to,
        "limit": limit,
    }
    with _session(driver) as session:
        rows = session.run(query, **params).data()

    out = []
    for row in rows:
        item = _compact(row["process"])
        item["unit"] = {"code": row["unit_code"], "name": row["unit_name"]} if row["unit_code"] else None
        # One provider can hold several documents of the same process.
        item["awarded_to"] = list({w["cuit"]: w for w in row["awarded_to"]}.values())
        item["bid_count"] = row["bid_count"]
        out.append(item)
    return out


_DETAIL_QUERY = """
MATCH (proc:Process {process_number: $process_number})
OPTIONAL MATCH (proc)-[:MANAGED_BY]->(u:ContractingUnit)
OPTIONAL MATCH (u)-[:BELONGS_TO]->(o:Organization)
RETURN proc, u{.code, .name, .source} AS unit, o{.saf_code, .name} AS organization,
       COUNT { (proc)-[:HAS_LINE_ITEM]->() } AS line_item_count
"""

_BIDS_QUERY = """
MATCH (:Process {process_number: $process_number})-[:HAS_BID]->(b:Bid)-[:SUBMITTED_BY]->(p:Provider)
RETURN p.cuit AS cuit, p.business_name AS name, b.status AS status,
       b.total_amount AS total_amount, b.currency AS currency,
       b.rejection_reason AS rejection_reason, b.submitted_at AS submitted_at
ORDER BY b.total_amount
"""

_CONTRACTS_QUERY = """
MATCH (:Process {process_number: $process_number})-[:GENERATES]->(cd:ContractualDocument)
OPTIONAL MATCH (cd)-[:AWARDED_TO]->(p:Provider)
RETURN cd{.document_number, .document_type, .status, .total_amount, .current_amount,
          .currency, .authorization_date, .perfection_date, .variation_pct, .source_url} AS document,
       p.cuit AS cuit, p.business_name AS name,
       [(cd)-[a:AUTHORIZED_BY]->(au:Authorizer)
        | {name: au.full_name, role: a.role, authorized_at: a.authorized_at}] AS authorizers
"""

_DICTAMEN_QUERY = """
MATCH (:Process {process_number: $process_number})-[:HAS_DICTAMEN]->(d:Dictamen)
RETURN d AS dictamen,
       [(d)-[pa:PRE_ADJUDICATES]->(p:Provider)
        | {cuit: p.cuit, name: p.business_name, is_primary: pa.is_primary, merit_order: pa.merit_order}] AS pre_adjudicated,
       [(d)-[r:REJECTED]->(p:Provider)
        | {cuit: p.cuit, name: p.business_name, reasons: r.reasons}] AS rejected,
       [(d)-[e:EVALUATED_BY]->(s:DictamenSigner)
        | {username: s.username, role: e.role, status: e.status}] AS signers
ORDER BY d.sequence
"""


def get_tender(driver: Driver, process_number: str) -> Optional[Dict[str, Any]]:
    """Full picture of one process, or None when it does not exist."""
    params = {"process_number": process_number}
    with _session(driver) as session:
        head = session.run(_DETAIL_QUERY, **params).single()
        if head is None:
            return None
        bids = session.run(_BIDS_QUERY, **params).data()
        contracts = session.run(_CONTRACTS_QUERY, **params).data()
        dictamenes = session.run(_DICTAMEN_QUERY, **params).data()

    process = _compact(head["proc"])
    process.pop("_labels", None)
    return {
        "process": process,
        "unit": head["unit"],
        "organization": head["organization"],
        "line_item_count": head["line_item_count"],
        "bids": [_compact(b) for b in bids],
        "contracts": [
            {
                **_compact(row["document"]),
                "awarded_to": {"cuit": row["cuit"], "name": row["name"]} if row["cuit"] else None,
                "authorizers": to_jsonable(row["authorizers"]),
            }
            for row in contracts
        ],
        "dictamenes": [
            {**_compact(row["dictamen"]), **{k: to_jsonable(row[k]) for k in ("pre_adjudicated", "rejected", "signers")}}
            for row in dictamenes
        ],
    }


def _process_keys(meta: dict) -> tuple[list, list]:
    """(scalar Process column keys, ListProcess column keys) declared by a check."""
    scalar, listed = [], []
    for col in meta.get("columns", []):
        if not isinstance(col, dict):
            continue
        if col.get("type") == "Process":
            scalar.append(col["key"])
        elif col.get("type") == "ListProcess":
            listed.append(col["key"])
    return scalar, listed


def find_tender_findings(
    findings: Dict[str, List[Dict[str, Any]]],
    check_meta: Dict[str, Dict],
    process_number: str,
) -> Dict[str, List[Dict[str, Any]]]:
    """{check_key: rows} of every finding that references the process."""
    matches: Dict[str, List[Dict[str, Any]]] = {}
    for check_key, rows in findings.items():
        scalar, listed = _process_keys(check_meta.get(check_key, {}))
        scalar = scalar + [f for f in _LEGACY_PROCESS_FIELDS if f not in scalar]
        hit = [
            row for row in rows
            if any(row.get(k) == process_number for k in scalar)
            or any(
                isinstance(item, dict) and item.get("process_number") == process_number
                for k in listed
                for item in (row.get(k) or [])
            )
        ]
        if hit:
            matches[check_key] = hit
    return matches
