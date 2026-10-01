"""
src/api/config.py - Centralised settings for the FastAPI backend.

Settings resolution order: environment variables, then a `.env` file, then
defaults seeded from `config.json`. Environment variables use the `COIMA_`
prefix. Detection knobs (checks, thresholds, weights) are no longer read from
`config.json` here; they live as user overrides in SQLite and are served by
services/config_service.py. `config.json` only seeds the Neo4j connection
block for this module and is still consumed by the `run.py --detect` CLI
path.

Relative paths (`.env`, `config.json`, `sqlite_path`) resolve against the
backend/ directory, not the process cwd, so the MCP server behaves the same
whether Claude Code / Codex launch it from the repo root or from backend/.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _backend_path(path: str) -> str:
    """Anchor a relative path at backend/; absolute paths pass through."""
    return path if os.path.isabs(path) else str(BACKEND_DIR / path)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="COIMA_",
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"
    neo4j_limit: int = 50_000_000

    sqlite_path: str = "data/coima.db"

    config_path: str = "config.json"

    # Shared volume holding control.json / run_status.json (written by the
    # scraper supervisor, read here). Must match the scraper container's
    # COIMA_OUTPUT_DIR so both point at the same directory.
    scraper_control_dir: str = "/data/scraper-output"

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Comma-separated list of allowed CORS origins. "*" allows any origin
    # (the default, convenient for the Vite dev server). Empty disables
    # cross-origin access entirely, which is the right setting when a reverse
    # proxy serves the SPA and the API from the same origin.
    cors_origins: str = "*"

    # Basic API protections (see src/api/security.py); 0 disables each one.
    # Max requests per client IP per 60s sliding window.
    rate_limit_per_minute: int = 240
    # Min seconds between accepted runs of an expensive trigger endpoint
    # (detection run, scraper start/rescrape/indicator refresh).
    trigger_cooldown_seconds: int = 60
    # Max accepted request body size in bytes.
    max_body_bytes: int = 1_000_000

    detection_cache_min_new_tenders: int = 500

    # MCP server (src/mcp_server). Locale for check names/descriptions in tool
    # output. The token is optional: when set, the HTTP transport at /mcp
    # requires `Authorization: Bearer <token>`; stdio never needs it.
    mcp_locale: str = "es"
    mcp_token: Optional[str] = None
    # Extra Host headers accepted by /mcp besides localhost (DNS-rebinding
    # guard), comma-separated, e.g. "backend:*,coima.example.org".
    mcp_allowed_hosts: str = ""

    @field_validator("sqlite_path", "config_path")
    @classmethod
    def _anchor_relative(cls, value: str) -> str:
        return _backend_path(value)


def _load_from_config_json(path: str) -> dict:
    """Read the connection block from config.json as env-style overrides."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
        conn = cfg.get("connection", {})
        overrides: dict = {}
        if "uri" in conn:
            overrides["neo4j_uri"] = conn["uri"]
        if "user" in conn:
            overrides["neo4j_user"] = conn["user"]
        if "password" in conn:
            overrides["neo4j_password"] = conn["password"]
        if "limit" in conn:
            overrides["neo4j_limit"] = conn["limit"]
        return overrides
    except Exception:
        return {}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance, seeded from config.json as fallback."""
    overrides = _load_from_config_json(_backend_path("config.json"))
    return Settings(**overrides)
