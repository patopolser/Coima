"""
src/api/main.py - FastAPI application entry point.

Wires up routers, CORS, the basic API protections from src/api/security.py,
the MCP server endpoint at /mcp (src/mcp_server), and the lifespan that owns
the Neo4j driver and the SQLite engine. The driver is created once on startup
and torn down on shutdown so request handlers and MCP tools share the
connection pool.
"""

from __future__ import annotations

import logging
import sys
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Ensure project root is on sys.path so `src.*` imports resolve from any cwd.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from .config import get_settings
from .database import neo4j as neo4j_db
from .database import sqlite as sqlite_db
from .routers import detection, risk_scores, checks, companies, units, authorizers, graph, dashboard, scraper, config_router
from .security import BodySizeLimitMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware
from src.mcp_server.http import MCPHttpEndpoint

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    logger.info("Connecting to Neo4j at %s ...", settings.neo4j_uri)
    try:
        neo4j_db.init_driver(
            settings.neo4j_uri,
            settings.neo4j_user,
            settings.neo4j_password,
        )
        logger.info("Neo4j connected.")
    except Exception as exc:
        # Allow startup to continue so detection endpoints can fail gracefully
        # instead of taking the whole API down with them.
        logger.error("Failed to connect to Neo4j: %s", exc)

    logger.info("Initializing SQLite at %s ...", settings.sqlite_path)
    sqlite_db.init_db(settings.sqlite_path)
    logger.info("SQLite ready.")

    async with _mcp_endpoint.lifespan():
        yield

    logger.info("Shutting down. Closing Neo4j driver.")
    neo4j_db.close_driver()


_settings = get_settings()
_mcp_endpoint = MCPHttpEndpoint(token=_settings.mcp_token, extra_hosts=_settings.mcp_allowed_hosts)

app = FastAPI(
    title="Coima API",
    description=(
        "REST API for the Coima corruption-detection platform. "
        "Provides detection runs, risk scores, check findings, company/unit profiles, "
        "graph visualization data, and an MCP server at /mcp for AI agents."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

# Middleware stack, innermost first (add_middleware wraps outward): body cap,
# then rate limit, then CORS (so 429/413 responses still carry CORS headers
# for the cross-origin dev SPA), then security headers on everything.
app.add_middleware(BodySizeLimitMiddleware, max_bytes=_settings.max_body_bytes)
app.add_middleware(RateLimitMiddleware, limit_per_minute=_settings.rate_limit_per_minute)

# CORS comes from COIMA_CORS_ORIGINS (comma-separated; "*" = any, the default;
# empty = same-origin only, the right value behind a reverse proxy serving
# both SPA and API). Credentials are never combined with a wildcard, and the
# API is cookie-free.
_origins = [o.strip() for o in _settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials="*" not in _origins and bool(_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(SecurityHeadersMiddleware)

app.include_router(detection.router)
app.include_router(risk_scores.router)
app.include_router(checks.router)
app.include_router(companies.router)
app.include_router(units.router)
app.include_router(authorizers.router)
app.include_router(graph.router)
app.include_router(dashboard.router)
app.include_router(scraper.router)
app.include_router(config_router.router)

# MCP over Streamable HTTP for AI agents (Claude Code, Codex). Same tools as
# the stdio server started by `python run.py --mcp`.
app.add_route("/mcp", _mcp_endpoint, include_in_schema=False)


@app.get("/api/health", tags=["meta"])
def health():
    """Basic liveness probe."""
    return {"status": "ok"}


@app.get("/api/health/deep", tags=["meta"])
def health_deep():
    """
    Deep health check: verifies Neo4j connectivity and reports the state of
    the latest detection run and the SQLite database.
    """
    from .database.neo4j import get_driver
    from .database.sqlite import get_session
    from .services import detection_service
    import time

    result: dict = {"status": "ok", "components": {}}

    try:
        driver = get_driver()
        with driver.session() as s:
            s.run("RETURN 1")
        result["components"]["neo4j"] = "ok"
    except Exception as exc:
        result["components"]["neo4j"] = f"error: {exc}"
        result["status"] = "degraded"

    try:
        db = get_session()
        run = detection_service._get_latest_done_run(db)
        db.close()
        if run:
            result["components"]["sqlite"] = "ok"
            result["last_detection_run"] = (
                run.created_at.isoformat() if hasattr(run.created_at, "isoformat")
                else str(run.created_at)
            )
            result["last_run_tender_count"] = run.tender_count
        else:
            result["components"]["sqlite"] = "ok"
            result["last_detection_run"] = None
    except Exception as exc:
        result["components"]["sqlite"] = f"error: {exc}"
        result["status"] = "degraded"

    return result
