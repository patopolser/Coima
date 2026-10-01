"""MCP tool groups; each module exposes register(mcp)."""

from . import cypher, detection, entities, investigations, network, tenders

ALL = (detection, entities, network, tenders, cypher, investigations)
