"""
src/mcp_server/tools/entities.py - Providers, contracting units and
authorizers: ranked search, profiles and risk-score breakdowns.
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from src.api.services.entity_service import entity_scores, rank_entities
from src.detector.scoring import matched_syndromes

from .. import runtime
from ._common import READ_ONLY, trim_findings

EntityType = Literal["provider", "unit", "authorizer"]


def provider_rows(ctx, query: Optional[str], min_score: int, flag: Optional[str]) -> list:
    rows = ctx.risk_scores
    if query:
        ql = query.lower()
        rows = [s for s in rows if ql in s["cuit"].lower() or ql in (s["company"] or "").lower()]
    if min_score:
        rows = [s for s in rows if s["score"] >= min_score]
    if flag:
        rows = [s for s in rows if flag in (s["flags"] or [])]
    return [
        {k: s.get(k) for k in ("cuit", "company", "score", "confidence", "flags")}
        for s in rows
    ]


def entity_profile(db, ctx, entity_type: str, entity_id: str, max_rows: int) -> dict:
    max_rows = runtime.clamp(max_rows)
    if entity_type == "provider":
        data = ctx.company_index.get(entity_id)
        if data is None:
            raise ToolError(f"CUIT {entity_id} does not appear in the latest detection run.")
        rs = data.get("risk_score") or {}
        return {
            "entity_type": "provider",
            "id": entity_id,
            "name": rs.get("company"),
            "risk": {k: rs.get(k) for k in ("score", "base_score", "confidence", "flags")} if rs else None,
            "findings": trim_findings(data.get("findings", {}), max_rows),
        }

    info = ctx.entity_index(entity_type).get(entity_id)
    if info is None:
        raise ToolError(
            f"No {entity_type} '{entity_id}' in the latest detection run. "
            "Use search_entities to find the exact id."
        )
    risk = entity_scores(db, ctx.run.id, entity_type).get(entity_id) or {}
    return {
        "entity_type": entity_type,
        "id": entity_id,
        "name": info["name"],
        "total_tenders": info.get("total_tenders", 0),
        "risk": {k: risk.get(k) for k in ("score", "base_score", "confidence", "flags")} if risk else None,
        "findings": trim_findings(info.get("findings", {}), max_rows),
    }


def risk_breakdown(db, ctx, entity_type: str, entity_id: str) -> dict:
    if entity_type == "provider":
        rs = (ctx.company_index.get(entity_id) or {}).get("risk_score")
    else:
        rs = entity_scores(db, ctx.run.id, entity_type).get(entity_id)
    if not rs:
        raise ToolError(f"No risk score for {entity_type} '{entity_id}' in the latest detection run.")
    flags = set(rs.get("flags") or [])
    return {
        "entity_type": entity_type,
        "id": entity_id,
        "name": rs.get("company"),
        "score": rs.get("score"),
        "base_score": rs.get("base_score"),
        "confidence": rs.get("confidence"),
        "flags": rs.get("flags"),
        "matched_syndromes": [
            {"label": s["label"], "checks": sorted(s["keys"]), "multiplier": s["multiplier"]}
            for s in matched_syndromes(flags)
        ],
        "evidence_breakdown": rs.get("evidence_breakdown"),
    }


def register(mcp: MCPServer) -> None:
    @mcp.tool(annotations=READ_ONLY)
    def search_providers(
        query: Annotated[Optional[str], Field(description="Substring of the CUIT or company name")] = None,
        min_score: Annotated[int, Field(ge=0, le=100, description="Only providers scoring at least this (0-100)")] = 0,
        flag: Annotated[Optional[str], Field(description="Only providers flagged by this check key")] = None,
        offset: int = 0,
        limit: Annotated[int, Field(description="Rows per page (max 200)")] = 25,
    ) -> dict:
        """Providers (suppliers) ranked by risk score in the latest run, with their flags.
        Use it to find a company's CUIT by name or to list the riskiest suppliers."""
        with runtime.db_session() as db:
            ctx = runtime.require_context(db)
            return runtime.page(provider_rows(ctx, query, min_score, flag), offset, limit)

    @mcp.tool(annotations=READ_ONLY)
    def search_entities(
        entity_type: Annotated[Literal["unit", "authorizer"], Field(description="'unit' = contracting unit (UOC), 'authorizer' = signing official")],
        query: Annotated[Optional[str], Field(description="Substring of the unit code/name or authorizer name")] = None,
        offset: int = 0,
        limit: Annotated[int, Field(description="Rows per page (max 200)")] = 25,
    ) -> dict:
        """Contracting units or authorizing officials ranked by risk, with finding counts per check."""
        with runtime.db_session() as db:
            ctx = runtime.require_context(db)
            rows = rank_entities(db, ctx, entity_type)
            if query:
                ql = query.lower()
                rows = [r for r in rows if ql in r["id"].lower() or ql in (r["name"] or "").lower()]
            return runtime.page(rows, offset, limit)

    @mcp.tool(annotations=READ_ONLY)
    def get_entity_profile(
        entity_type: EntityType,
        entity_id: Annotated[str, Field(description="Provider CUIT, unit code or authorizer full name (exact)")],
        max_rows_per_check: Annotated[int, Field(description="Finding rows kept per check (max 200); totals are always reported")] = 20,
    ) -> dict:
        """Risk score and every red-flag finding where the entity appears, grouped by check."""
        with runtime.db_session() as db:
            ctx = runtime.require_context(db)
            return entity_profile(db, ctx, entity_type, entity_id, max_rows_per_check)

    @mcp.tool(annotations=READ_ONLY)
    def get_entity_risk_breakdown(
        entity_type: EntityType,
        entity_id: Annotated[str, Field(description="Provider CUIT, unit code or authorizer full name (exact)")],
    ) -> dict:
        """Why an entity scores what it scores: per-check contributions, synergy multiplier and
        matched syndromes (co-occurring patterns), confidence (independent evidence vectors) and,
        for providers, co-bidding network centrality."""
        with runtime.db_session() as db:
            ctx = runtime.require_context(db)
            return risk_breakdown(db, ctx, entity_type, entity_id)
