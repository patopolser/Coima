"""
src/api/config.py - Centralised settings for the FastAPI backend.

Settings resolution order: environment variables, then a `.env` file, then
defaults seeded from `config.json`. Environment variables use the `COIMA_`
prefix. Detection knobs (checks, thresholds, weights) are no longer read from
`config.json` here; they live as user overrides in SQLite and are served by
services/config_service.py. `config.json` only seeds the Neo4j connection
block for this module and is still consumed by the `run.py --detect` CLI
path.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="COIMA_",
        env_file=".env",
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

    # AI keys (optional; clients fall back to env vars set by third-party libs).
    anthropic_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    serper_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    deepseek_base_url: str = "https://integrate.api.nvidia.com/v1"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_enable_tools: bool = False
    deepseek_temperature: float = 1
    deepseek_top_p: float = 0.95
    deepseek_max_tokens: int = 16384

    detection_cache_min_new_tenders: int = 500


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
    overrides = _load_from_config_json("config.json")
    return Settings(**overrides)
