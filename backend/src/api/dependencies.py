"""
src/api/dependencies.py - FastAPI dependency injection providers.
"""

from __future__ import annotations

from typing import Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .database.neo4j import get_driver
from .database.sqlite import get_session


def neo4j_driver():
    """Inject the singleton Neo4j driver."""
    return get_driver()


def db_session() -> Generator[Session, None, None]:
    """Inject a SQLAlchemy session, closing it automatically after the request."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()


def settings() -> Settings:
    """Inject the cached application settings."""
    return get_settings()
