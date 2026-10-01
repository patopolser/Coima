"""
src/api/database/neo4j.py - Singleton Neo4j driver.

Initialised once during the FastAPI lifespan and shared across every request,
so the driver's connection pool is reused instead of being rebuilt per call.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

from neo4j import Driver, GraphDatabase
from neo4j.graph import Node, Path, Relationship

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


def to_jsonable(value: Any) -> Any:
    """
    Convert a Neo4j result value into plain JSON-friendly Python: nodes and
    relationships become property dicts tagged with their labels/type, paths
    become node/relationship lists, temporals become ISO strings.
    """
    if isinstance(value, Node):
        return {"_labels": sorted(value.labels), **{k: to_jsonable(v) for k, v in value.items()}}
    if isinstance(value, Relationship):
        return {"_type": value.type, **{k: to_jsonable(v) for k, v in value.items()}}
    if isinstance(value, Path):
        return {
            "nodes": [to_jsonable(n) for n in value.nodes],
            "relationships": [to_jsonable(r) for r in value.relationships],
        }
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if hasattr(value, "iso_format"):
        return value.iso_format()
    if isinstance(value, (_dt.date, _dt.time, _dt.datetime)):
        return value.isoformat()
    if isinstance(value, _dt.timedelta):
        return str(value)
    return value
