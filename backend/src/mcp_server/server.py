"""
src/mcp_server/server.py - The Coima MCP server.

One MCPServer instance serves both transports:
  stdio            `python run.py --mcp` (Claude Code / Codex launch it locally)
  Streamable HTTP  mounted by src/api/main.py at /mcp (Docker stack)
"""

from __future__ import annotations

import logging

from mcp.server import MCPServer

from . import prompts, runtime, tools

mcp = MCPServer(
    "coima",
    title="Coima",
    description="Anti-corruption intelligence over Argentine public procurement data.",
    instructions=prompts.INSTRUCTIONS,
    version="1.0.0",
)

for group in tools.ALL:
    group.register(mcp)
prompts.register(mcp)


def run_stdio() -> None:
    """Serve over stdin/stdout. Logs go to stderr so they never corrupt the protocol."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    try:
        mcp.run("stdio")
    finally:
        runtime.close()
