"""
src/api/database/neo4j.py - Singleton Neo4j driver.

Initialised once during the FastAPI lifespan and shared across every request,
so the driver's connection pool is reused instead of being rebuilt per call.
"""

from __future__ import annotations

from typing import Optional

from neo4j import Driver, GraphDatabase

_driver: Optional[Driver] = None


def init_driver(uri: str, user: str, password: str) -> Driver:
    """Create and verify the global Neo4j driver. Call once on startup."""
    global _driver
    _driver = GraphDatabase.driver(uri, auth=(user, password))
    _driver.verify_connectivity()
    return _driver


def get_driver() -> Driver:
    """Return the initialised driver. Raises if init_driver() was not called."""
    if _driver is None:
        raise RuntimeError("Neo4j driver has not been initialized. Call init_driver() first.")
    return _driver


def close_driver() -> None:
    """Close the driver. Call on application shutdown."""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


def count_processes(driver: Driver) -> int:
    """Return the current count of Process nodes in the graph. Used for cache checks."""
    with driver.session() as session:
        result = session.run("MATCH (p:Process) RETURN count(p) AS cnt")
        record = result.single()
        return record["cnt"] if record else 0
