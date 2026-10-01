"""
src/mcp_server/tools/cypher.py - Graph schema and read-only Cypher.

Read-only is enforced by Neo4j itself: queries run inside a READ-access
transaction, so any write clause is rejected by the server rather than by a
keyword blacklist. On top of that a few read-side escape hatches that reach
outside the database (LOAD CSV, apoc load/export/import) are refused.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Any, Optional

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from neo4j import READ_ACCESS, NotificationClassification, unit_of_work
from neo4j.exceptions import Neo4jError
from pydantic import Field

from src.api.database.neo4j import to_jsonable

from .. import runtime
from ._common import READ_ONLY

_SCHEMA_DOC = Path(__file__).resolve().parent.parent / "schema.md"

QUERY_TIMEOUT_SECONDS = 30
MAX_ROWS = 500
# Serialized size cap (characters) so one wide query cannot flood the context.
MAX_OUTPUT_CHARS = 120_000

_TRAILING_LIMIT = re.compile(r"\bLIMIT\s+(\d+|\$\w+)\s*$", re.IGNORECASE)
_RETURN = re.compile(r"\bRETURN\b", re.IGNORECASE)
_EXTERNAL_IO = re.compile(r"\bLOAD\s+CSV\b|\bapoc\.(load|export|import)\.", re.IGNORECASE)


def read_session(driver):
    """READ-access session; Neo4j itself rejects any write attempted in it."""
    # Optional properties (e.g. dates absent on every node) trigger benign
    # "property key does not exist" notifications that only flood the logs.
    return driver.session(
        default_access_mode=READ_ACCESS,
        notifications_disabled_classifications=[NotificationClassification.UNRECOGNIZED],
    )


def prepare_query(query: str, limit: int) -> str:
    """Strip a trailing ';' and append LIMIT limit+1 unless the query already ends in one."""
    q = query.strip().rstrip(";").strip()
    if _EXTERNAL_IO.search(q):
        raise ToolError("LOAD CSV and apoc load/export/import are not allowed.")
    if _RETURN.search(q) and not _TRAILING_LIMIT.search(q):
        # One extra row tells us whether the result was cut.
        q = f"{q}\nLIMIT {limit + 1}"
    return q


def run_read_query(driver, query: str, params: Optional[dict], limit: int) -> dict:
    limit = runtime.clamp(limit, MAX_ROWS)
    text = prepare_query(query, limit)

    @unit_of_work(timeout=QUERY_TIMEOUT_SECONDS)
    def work(tx):
        result = tx.run(text, params or {})
        keys = list(result.keys())
        rows: list[Any] = []
        for record in result:
            rows.append(record)
            if len(rows) > limit:
                break
        return keys, [to_jsonable(dict(r)) for r in rows]

    try:
        with read_session(driver) as session:
            keys, rows = session.execute_read(work)
    except Neo4jError as exc:
        raise ToolError(f"Cypher error ({exc.code}): {exc.message}") from exc

    truncated = len(rows) > limit
    rows = rows[:limit]
    size = 0
    for i, row in enumerate(rows):
        size += len(json.dumps(row, default=str))
        if size > MAX_OUTPUT_CHARS:
            rows, truncated = rows[:i], True
            break
    return {"columns": keys, "row_count": len(rows), "truncated": truncated, "rows": rows}


def graph_schema(driver) -> dict:
    with read_session(driver) as session:
        labels = [r["label"] for r in session.run("CALL db.labels() YIELD label RETURN label ORDER BY label")]
        rel_types = [r["t"] for r in session.run(
            "CALL db.relationshipTypes() YIELD relationshipType AS t RETURN t ORDER BY t"
        )]
        # Single-label and single-type counts are answered from the count store.
        node_counts = {
            label: session.run(f"MATCH (n:`{label}`) RETURN count(n) AS c").single()["c"]
            for label in labels
        }
        rel_counts = {
            t: session.run(f"MATCH ()-[r:`{t}`]->() RETURN count(r) AS c").single()["c"]
            for t in rel_types
        }
    return {"node_counts": node_counts, "relationship_counts": rel_counts}


def register(mcp: MCPServer) -> None:
    @mcp.tool(annotations=READ_ONLY)
    def get_graph_schema() -> dict:
        """The Neo4j data model (node labels, keys, key properties and relationships) plus live
        counts per label and relationship type. Read it before writing Cypher for run_cypher."""
        out: dict = {"schema": _SCHEMA_DOC.read_text(encoding="utf-8")}
        try:
            out.update(graph_schema(runtime.neo4j_driver()))
        except ToolError as exc:
            out["neo4j_error"] = str(exc)
        return out

    @mcp.tool(annotations=READ_ONLY)
    def run_cypher(
        query: Annotated[str, Field(description="Read-only Cypher. Use $params for values instead of string concatenation.")],
        params: Annotated[Optional[dict], Field(description="Query parameters")] = None,
        limit: Annotated[int, Field(description="Max rows returned (max 500). Appended as LIMIT unless the query ends with one.")] = 100,
    ) -> dict:
        """Run a read-only Cypher query against the procurement graph for questions the other tools
        do not cover (aggregations, custom paths, time series). Writes are rejected by the database.
        Times out after 30s; prefer anchored MATCHes on keys (Process.process_number, Provider.cuit,
        ContractingUnit.code, Authorizer.full_name)."""
        return run_read_query(runtime.neo4j_driver(), query, params, limit)
