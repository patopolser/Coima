"""
logging_config.py - Rich-powered structured logging used across all scraper modules.

Call `setup_logging()` once from main.py; modules obtain their logger via
`get_logger(__name__)`.
"""

from __future__ import annotations

import logging

from rich.console import Console
from rich.logging import RichHandler

_console = Console(stderr=True)
_configured = False


def setup_logging(level: str = "INFO") -> None:
    """
    Configure the root logger with a Rich handler. Call once at application
    startup.

    Args:
        level: Log level string ("DEBUG", "INFO", "WARNING", "ERROR").
    """
    global _configured
    if _configured:
        return

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    handler = RichHandler(
        console=_console,
        rich_tracebacks=True,
        tracebacks_show_locals=False,
        show_path=True,
        markup=True,
    )
    handler.setLevel(numeric_level)

    logging.basicConfig(
        level=numeric_level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[handler],
        force=True,
    )

    # Silence noisy third-party loggers.
    for noisy in ("urllib3", "requests", "neo4j", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Modules should call get_logger(__name__)."""
    return logging.getLogger(name)
