"""
config.py - Central configuration for the COMPR.AR scraper.

Values are resolved in priority order: environment variables (prefixed
`COIMA_`), then `config.yaml` in the working directory, then the defaults
defined here. Import the ready-to-use `settings` singleton:

    from config import settings
    print(settings.neo4j_uri)
"""

from __future__ import annotations

import os
import pathlib

import yaml
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = pathlib.Path(__file__).parent


class Settings:
    """Central configuration object loaded from env vars and config.yaml.

    Rate-limiting defaults to a polite crawl (1s delay, bounded retries) so the
    public source (comprar.gob.ar) is not hammered. These can be tuned via env
    vars or config.yaml. See the "Scraping ethics" section of scraper/README.md.
    """

    # Neo4j connection.
    neo4j_uri:      str = "neo4j://127.0.0.1:7687"
    neo4j_user:     str = "neo4j"
    neo4j_password: str = "password"
    neo4j_max_conn: int = 5

    # Output.
    output_dir:  str = str(BASE_DIR / "output")
    batch_size:  int = 5

    # Input.
    tenders_file: str = str(BASE_DIR / "data" / "tenders.txt")
    contratar_tenders_file: str = str(BASE_DIR / "data" / "tenders_contratar.txt")

    # Default look-back window (in months) for the open-process re-scrape:
    # re-scrape non-terminal processes whose opening date falls within this many
    # months of today.
    rescrape_months: int = 4

    # HTTP / Crawler behaviour.
    # `source` selects the portal scraped in this run: "comprar" (goods and
    # services, comprar.gob.ar) or "contratar" (public works, contratar.gob.ar).
    # Both portals run the same ASP.NET WebForms platform; `base_url` always
    # holds the base URL of the *active* source.
    source: str = "comprar"
    comprar_base_url: str = "https://comprar.gob.ar"
    contratar_base_url: str = "https://contratar.gob.ar"
    base_url: str = "https://comprar.gob.ar"

    def apply_source(self, source: str) -> None:
        """Activate a portal: validates `source` and points `base_url` at it."""
        source = (source or "comprar").strip().lower()
        if source not in ("comprar", "contratar"):
            raise ValueError(f"Unknown source: {source!r} (expected 'comprar' or 'contratar')")
        self.source = source
        self.base_url = self.comprar_base_url if source == "comprar" else self.contratar_base_url

    @property
    def active_tenders_file(self) -> str:
        """Default tenders file for the active source."""
        return self.tenders_file if self.source == "comprar" else self.contratar_tenders_file

    @property
    def progress_filename(self) -> str:
        """Per-source progress file name (comprar keeps the legacy name)."""
        return "progress.json" if self.source == "comprar" else f"progress_{self.source}.json"

    request_timeout: int = 30

    # Solicitud de Provisión (SPR) pages can be slow to render server-side,
    # so they get a longer timeout than ordinary requests.
    spr_request_timeout: int = 90

    # Polite crawl delay between HTTP requests, in seconds.
    # Defaults to 1s of polite crawling. Set to 0 to disable.
    request_delay_seconds: float = 1.0

    # Retry configuration. Bounded retries so transient 5xx/429 back off politely
    # instead of retrying aggressively. Set to 0 to disable.
    max_retries: int = 3
    retry_backoff_factor: float = 0.5
    retry_status_forcelist: list[int] | None = None

    # Rotate User-Agent on every request (anti-bot measure). DEFAULT OFF.
    rotate_user_agent: bool = False

    # Custom User-Agent string (used when rotate_user_agent is False).
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    # Logging.
    log_level: str = "INFO"

    # Economic indicator ingestion.
    economic_indicators_enabled: bool = True
    economic_indicators_start_date: str = "2015-01-01"
    economic_indicators_currencies: list[str] = ["USD", "EUR", "GBP", "BRL", "CHF", "JPY"]

    _yaml_loaded: bool = False

    def __init__(self) -> None:
        self.retry_status_forcelist = [429, 500, 502, 503, 504]
        self._load_yaml()
        self._load_env()

    def _load_yaml(self) -> None:
        """Load values from config.yaml if it exists."""
        yaml_path = pathlib.Path.cwd() / "config.yaml"
        if not yaml_path.exists():
            yaml_path = BASE_DIR / "config.yaml"
        if yaml_path.exists():
            with yaml_path.open("r", encoding="utf-8") as fh:
                data: dict = yaml.safe_load(fh) or {}
            for key, value in data.items():
                if hasattr(self, key):
                    setattr(self, key, value)
            self._yaml_loaded = True

    def _load_env(self) -> None:
        """Override any setting from COIMA_<UPPER_KEY> environment variables."""
        mapping = {
            "COIMA_NEO4J_URI":             ("neo4j_uri",             str),
            "COIMA_NEO4J_USER":            ("neo4j_user",            str),
            "COIMA_NEO4J_PASSWORD":        ("neo4j_password",         str),
            "COIMA_NEO4J_MAX_CONN":        ("neo4j_max_conn",         int),
            "COIMA_OUTPUT_DIR":            ("output_dir",             str),
            "COIMA_BATCH_SIZE":            ("batch_size",             int),
            "COIMA_TENDERS_FILE":          ("tenders_file",           str),
            "COIMA_CONTRATAR_TENDERS_FILE": ("contratar_tenders_file", str),
            "COIMA_SOURCE":                ("source",                 str),
            "COIMA_COMPRAR_BASE_URL":      ("comprar_base_url",       str),
            "COIMA_CONTRATAR_BASE_URL":    ("contratar_base_url",     str),
            "COIMA_RESCRAPE_MONTHS":       ("rescrape_months",        int),
            "COIMA_REQUEST_TIMEOUT":       ("request_timeout",        int),
            "COIMA_SPR_REQUEST_TIMEOUT":   ("spr_request_timeout",    int),
            "COIMA_REQUEST_DELAY":         ("request_delay_seconds",  float),
            "COIMA_MAX_RETRIES":           ("max_retries",            int),
            "COIMA_RETRY_BACKOFF":         ("retry_backoff_factor",   float),
            "COIMA_ROTATE_UA":             ("rotate_user_agent",      lambda v: v.lower() == "true"),
            "COIMA_USER_AGENT":            ("user_agent",             str),
            "COIMA_LOG_LEVEL":             ("log_level",              str),
            "COIMA_ECON_INDICATORS":        ("economic_indicators_enabled", lambda v: v.lower() == "true"),
            "COIMA_ECON_START_DATE":        ("economic_indicators_start_date", str),
            "COIMA_ECON_CURRENCIES":        ("economic_indicators_currencies", lambda v: [c.strip().upper() for c in v.split(",") if c.strip()]),
        }
        for env_key, (attr, cast) in mapping.items():
            raw = os.environ.get(env_key)
            if raw is not None:
                setattr(self, attr, cast(raw))
        # Re-derive base_url after yaml/env may have changed source or the
        # per-source base URLs.
        self.apply_source(self.source)


settings = Settings()
