"""
src/mcp_server/tools/detection.py - Detection run status, check catalogue and
per-check findings.
"""

from __future__ import annotations

from typing import Annotated, Optional

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from src.api.services import detection_service
from src.api.services.scoring_service import filter_rows

from .. import runtime
from ._common import READ_ONLY


def detection_status(db) -> dict:
    run = detection_service.get_latest_run(db)
    if run is None:
        return {"run": None, "message": "No finished detection run yet."}
    ctx = runtime.require_context(db)
    return {
        "run_id": run["id"],
        "created_at": run["created_at"],
        "tender_count": run["tender_count"],
        "findings_per_check": {k: len(v) for k, v in sorted(ctx.findings.items()) if v},
        "scored_providers": len(ctx.risk_scores),
        "units_with_findings": len(ctx.entity_index("unit")),
        "authorizers_with_findings": len(ctx.entity_index("authorizer")),
    }


def check_catalogue(ctx) -> list:
    return [
        {
            "key": key,
            "label": meta.get("label"),
            "description": meta.get("description"),
            "weight": meta.get("weight"),
            "targets": sorted(meta.get("entity_columns", {})),
            "columns": [c["key"] for c in meta.get("columns", []) if isinstance(c, dict)],
            "total_findings": len(ctx.findings.get(key, [])),
        }
        for key, meta in ctx.check_meta.items()
    ]


def check_findings(ctx, check_key: str, search: Optional[str], sort: Optional[str],
                   descending: bool, offset: int, limit: int) -> dict:
    meta = ctx.check_meta.get(check_key)
    if meta is None:
        raise ToolError(f"Unknown check '{check_key}'. Call list_checks for the valid keys.")
    rows = filter_rows(ctx.findings.get(check_key, []), search, meta.get("search_fields", []))
    if sort:
        rows = sorted(rows, key=lambda r: (r.get(sort) is None, r.get(sort, "")), reverse=descending)
    return {"check": check_key, "label": meta.get("label"), **runtime.page(rows, offset, limit)}


def register(mcp: MCPServer) -> None:
    @mcp.tool(annotations=READ_ONLY)
    def get_detection_status() -> dict:
        """Latest finished detection run: id, date, tenders analysed, findings per check and how
        many providers/units/authorizers were scored. Call this first to know what data exists."""
        with runtime.db_session() as db:
            return detection_status(db)

    @mcp.tool(annotations=READ_ONLY)
    def list_checks() -> dict:
        """Catalogue of red-flag checks (bid rotation rings, cover bidding, contract splitting, ...):
        key, label, description, scoring weight, entity types it targets, row columns and how many
        findings it produced in the latest run."""
        with runtime.db_session() as db:
            return {"checks": check_catalogue(runtime.require_context(db))}

    @mcp.tool(annotations=READ_ONLY)
    def get_check_findings(
        check_key: Annotated[str, Field(description="Check key from list_checks, e.g. 'bid_rotation_ring'")],
        search: Annotated[Optional[str], Field(description="Case-insensitive text matched against the check's searchable columns (CUIT, names, process numbers...)")] = None,
        sort: Annotated[Optional[str], Field(description="Column key to sort by")] = None,
        descending: bool = True,
        offset: int = 0,
        limit: Annotated[int, Field(description="Rows per page (max 200)")] = 25,
    ) -> dict:
        """Finding rows of one check in the latest run, filterable and paginated."""
        with runtime.db_session() as db:
            ctx = runtime.require_context(db)
            return check_findings(ctx, check_key, search, sort, descending, offset, limit)
