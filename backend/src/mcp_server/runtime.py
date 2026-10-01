"""
src/mcp_server/runtime.py - Shared resources for the MCP tools.

The same tools run in two hosts: the stdio process launched by Claude Code /
Codex (`python run.py --mcp`), and the FastAPI app that mounts /mcp. Under
FastAPI the lifespan already opened Neo4j and SQLite; under stdio nothing
has, so everything here initializes lazily and idempotently. Neo4j is
optional: if it is down, the tools over SQLite (scores, findings,
investigations) keep working and the graph tools fail with a clear message.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Any, Iterator, List

from mcp.server.mcpserver.exceptions import ToolError
from neo4j import Driver
from sqlalchemy.orm import Session

from src.api.config import get_settings
from src.api.database import neo4j as neo4j_db
from src.api.database import sqlite as sqlite_db
from src.api.services.detection_context import DetectionContext, load_detection_context

logger = logging.getLogger(__name__)

_init_lock = threading.Lock()

# Hard ceiling for every `limit`-style argument, whatever the caller asks for.
MAX_LIMIT = 200


def _ensure_sqlite() -> None:
    with _init_lock:
        if sqlite_db._engine is None:
            sqlite_db.init_db(get_settings().sqlite_path)


@contextmanager
def db_session() -> Iterator[Session]:
    """A SQLite session that is always closed."""
    _ensure_sqlite()
    session = sqlite_db.get_session()
    try:
        yield session
    finally:
        session.close()


def neo4j_driver() -> Driver:
    """The shared Neo4j driver, connecting on first use. Raises ToolError if unreachable."""
    with _init_lock:
        try:
            return neo4j_db.get_driver()
        except RuntimeError:
            pass
        settings = get_settings()
        try:
            return neo4j_db.init_driver(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
        except Exception as exc:
            neo4j_db.close_driver()
            raise ToolError(
                f"Neo4j is not reachable at {settings.neo4j_uri} ({exc}). "
                "Graph tools need the database running; scores, findings and "
                "investigations still work."
            ) from exc


def locale() -> str:
    return get_settings().mcp_locale


def require_context(db: Session) -> DetectionContext:
    """The latest finished detection run, or a ToolError explaining there is none."""
    ctx = load_detection_context(db, locale())
    if ctx is None:
        raise ToolError(
            "There is no finished detection run yet. Run the detection from the "
            "Coima UI (or POST /api/detection/run) and try again."
        )
    return ctx


def clamp(limit: int, maximum: int = MAX_LIMIT) -> int:
    return max(1, min(limit, maximum))


def page(items: List[Any], offset: int = 0, limit: int = 25) -> dict:
    """Slice a list into an LLM-sized page that says how much was left out."""
    offset = max(0, offset)
    limit = clamp(limit)
    chunk = items[offset : offset + limit]
    return {
        "total": len(items),
        "offset": offset,
        "returned": len(chunk),
        "truncated": offset + len(chunk) < len(items),
        "items": chunk,
    }


def close() -> None:
    neo4j_db.close_driver()
