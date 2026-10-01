"""
src/mcp_server/tools/network.py - Collusion networks around a provider and
compact entity graphs from Neo4j.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Annotated, Literal, Optional

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from src.api.services import graph_service

from .. import runtime
from ._common import READ_ONLY

# Cartel checks whose rows are one-per-provider with a `co_members` list.
_GROUP_CHECKS = {
    "bid_rotation_ring": ("ring_id", ["ring_size", "shared_processes", "member_wins", "rotation_pct", "cobid_strength"]),
    "shared_contact_cluster": ("cluster_id", ["cluster_size", "cobid_processes", "distinct_winners"]),
    "cobid_community": ("community_id", ["community_size", "density", "cohesion_pct"]),
}

# co_members cells render as "CUIT (Business name)".
_MEMBER_RE = re.compile(r"^\s*(\S+)\s+\((.*)\)\s*$")


def _flatten(item):
    """A UI list cell ({text}, {type, contact} or a scalar) as a plain string."""
    if not isinstance(item, dict):
        return item
    if "text" in item:
        return item["text"]
    if "type" in item or "contact" in item:
        return f"{item.get('type', '')}:{item.get('contact', '')}"
    return item


def _rows_for(ctx, check_key: str, cuit: str) -> list:
    return [r for r in ctx.findings.get(check_key, []) if r.get("provider_cuit") == cuit]


def network_neighborhood(ctx, cuit: str) -> dict:
    out: dict = {"cuit": cuit}
    names = {"bid_rotation_ring": "rings", "shared_contact_cluster": "contact_clusters", "cobid_community": "communities"}
    for check_key, (id_field, fields) in _GROUP_CHECKS.items():
        items = []
        for row in _rows_for(ctx, check_key, cuit):
            item = {f: row.get(f) for f in [id_field, *fields]}
            item["co_members"] = [_flatten(m) for m in row.get("co_members") or []]
            if check_key == "shared_contact_cluster":
                item["shared_contacts"] = [_flatten(m) for m in row.get("shared_contacts") or []]
            items.append(item)
        out[names[check_key]] = items
    out["authorizer_triads"] = [
        {k: row.get(k) for k in ("authorizer", "unit_code", "unit_name", "contracts", "authorizer_pct", "unit_pct", "real_ars")}
        for row in _rows_for(ctx, "authorizer_provider_ring", cuit)
    ]
    rs = (ctx.company_index.get(cuit) or {}).get("risk_score") or {}
    out["centrality"] = (rs.get("evidence_breakdown") or {}).get("features")

    if not any(out[k] for k in ("rings", "contact_clusters", "communities", "authorizer_triads", "centrality")):
        out["message"] = "No cartel-network signals for this company in the latest run."
    return out


def related_companies(ctx, cuit: str, limit: int) -> dict:
    """Providers that share a ring, contact cluster or co-bidding community with `cuit`."""
    related: dict = {}
    for check_key, (id_field, _) in _GROUP_CHECKS.items():
        for row in _rows_for(ctx, check_key, cuit):
            for member in row.get("co_members") or []:
                text = _flatten(member)
                m = _MEMBER_RE.match(str(text))
                other, name = (m.group(1), m.group(2)) if m else (str(text), None)
                if other == cuit:
                    continue
                entry = related.setdefault(other, {"cuit": other, "name": name, "links": []})
                entry["name"] = entry["name"] or name
                entry["links"].append({"check": check_key, "group_id": row.get(id_field)})
    ranked = sorted(related.values(), key=lambda e: len(e["links"]), reverse=True)
    for e in ranked:
        e["link_count"] = len(e["links"])
    return {"cuit": cuit, **runtime.page(ranked, 0, limit)}


def compact_graph(graph: dict, max_nodes: int) -> dict:
    """
    Re-key Neo4j element ids to short n1, n2... ids, drop UI-only fields and
    cap the node count (anchor first), so the graph fits in a model context.
    """
    nodes = graph["nodes"]
    kept = nodes[:max_nodes]
    short = {n["id"]: f"n{i + 1}" for i, n in enumerate(kept)}
    out_nodes = []
    for n in kept:
        node = {"id": short[n["id"]], "type": n.get("group"), "label": n.get("label")}
        for key in ("cuit", "code", "name", "process_number", "status", "opening_date", "source_url"):
            if n.get(key) not in (None, "") and n.get(key) != node["label"]:
                node[key] = n[key]
        out_nodes.append(node)
    out_edges = [
        {
            "source": short[e["source"]],
            "target": short[e["target"]],
            "kind": e["kind"],
            **({"amount": e["amount"], "currency": e.get("currency")} if e.get("amount") else {}),
        }
        for e in graph["edges"]
        if e["source"] in short and e["target"] in short
    ]
    return {
        "node_counts": dict(Counter(n.get("group") for n in nodes)),
        "edge_counts": dict(Counter(e["kind"] for e in graph["edges"])),
        "truncated": len(nodes) > len(kept),
        "nodes": out_nodes,
        "edges": out_edges,
    }


def register(mcp: MCPServer) -> None:
    @mcp.tool(annotations=READ_ONLY)
    def get_network_neighborhood(
        cuit: Annotated[str, Field(description="Provider CUIT")],
    ) -> dict:
        """A provider's collusion network from the cartel checks: bid-rotation rings, shared-contact
        clusters (same phone/email/address), co-bidding communities, authorizer-unit-provider triads
        and co-bidding centrality."""
        with runtime.db_session() as db:
            return network_neighborhood(runtime.require_context(db), cuit)

    @mcp.tool(annotations=READ_ONLY)
    def list_related_companies(
        cuit: Annotated[str, Field(description="Provider CUIT")],
        limit: Annotated[int, Field(description="Max companies returned (max 200)")] = 20,
    ) -> dict:
        """Other providers grouped with this one by the cartel checks (same ring, contact cluster or
        co-bidding community), most-linked first. Good next candidates to investigate."""
        with runtime.db_session() as db:
            return related_companies(runtime.require_context(db), cuit, limit)

    @mcp.tool(annotations=READ_ONLY)
    def get_entity_graph(
        entity_type: Annotated[Literal["provider", "unit", "authorizer"], Field(description="Anchor entity type")],
        entity_id: Annotated[str, Field(description="Provider CUIT, unit code or authorizer full name (exact)")],
        won_only: Annotated[bool, Field(description="Provider only: keep just the processes it won")] = False,
        include_bids: Annotated[bool, Field(description="Provider only: include processes it bid on")] = True,
        include_contacts: Annotated[bool, Field(description="Provider only: include shared phone/email/address links to other providers")] = True,
        date_from: Annotated[Optional[str], Field(description="ISO date; filter by process opening date")] = None,
        date_to: Annotated[Optional[str], Field(description="ISO date; filter by process opening date")] = None,
        max_nodes: Annotated[int, Field(description="Node cap (max 500)")] = 150,
    ) -> dict:
        """Graph from Neo4j around one entity: processes it won/bid/managed/signed, awarded providers
        with amounts, and (for providers) the shared-contact network."""
        driver = runtime.neo4j_driver()
        if entity_type == "provider":
            graph = graph_service.company_graph(
                driver, entity_id, won_only=won_only, show_bids=include_bids,
                show_contacts=include_contacts, show_earnings=True, date_from=date_from, date_to=date_to,
            )
        elif entity_type == "unit":
            graph = graph_service.unit_graph(driver, entity_id, show_earnings=True, date_from=date_from, date_to=date_to)
        else:
            graph = graph_service.authorizer_graph(driver, entity_id, show_earnings=True, date_from=date_from, date_to=date_to)
        if graph is None:
            raise ToolError(f"No {entity_type} '{entity_id}' in Neo4j.")
        return {"anchor": {"type": entity_type, "id": entity_id}, **compact_graph(graph, runtime.clamp(max_nodes, 500))}
