"""
run.py - CLI entry point.

Three modes are supported:
  --api       run the FastAPI REST backend via uvicorn.
  --detect    run the standalone Neo4j detection pipeline and write a JSON report.
  --mcp       serve the MCP server over stdio (what Claude Code / Codex launch).

With no flag the parser help is printed.
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def run_api(host="0.0.0.0", port=8000, reload=False):
    import uvicorn
    print(f"Starting Coima FastAPI backend on http://{host}:{port}")
    print(f"  API docs: http://{host}:{port}/docs")
    uvicorn.run(
        "src.api.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


def run_mcp():
    # Nothing may be printed here: stdout is the MCP protocol channel.
    from src.mcp_server.server import run_stdio
    run_stdio()


def run_detection(config_path, output_path, limit, uri, user, password):
    from src.detector import load_config, get, GraphDatabase, run_detection, save_report

    cfg = load_config(config_path)
    uri = uri or get(cfg, "connection", "uri", default="bolt://localhost:7687")
    user = user or get(cfg, "connection", "user", default="neo4j")
    password = password or get(cfg, "connection", "password", default="password")
    limit = limit or get(cfg, "connection", "limit", default=500)

    print("Connecting to Neo4j...")
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        print(f"   Connected to {uri}")
        print(f"   Config: {config_path}")

        print("\nRunning detection steps...")
        findings = run_detection(driver, cfg, limit)

        save_report(findings, cfg, output_path)

    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)
    finally:
        if 'driver' in locals():
            driver.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Coima Application Runner")
    parser.add_argument("--api", action="store_true", help="Run the FastAPI REST backend")
    parser.add_argument("--detect", action="store_true", help="Run the Neo4j corruption detection script")
    parser.add_argument("--mcp", action="store_true", help="Serve the MCP server over stdio (Claude Code / Codex)")

    parser.add_argument("--port", type=int, default=None, help="Server port (default: 8000)")
    parser.add_argument("--host", default="0.0.0.0", help="Server host")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for --api (dev only)")

    parser.add_argument("--config", default="config.json", help="Path to config.json for detection")
    parser.add_argument("--output", default="data/coima.json", help="Path to save output report")
    parser.add_argument("--limit", type=int, default=None, help="Override row limit from config")
    parser.add_argument("--uri", default=None, help="Override Neo4j URI from config")
    parser.add_argument("--user", default=None, help="Override Neo4j username from config")
    parser.add_argument("--password", default=None, help="Override Neo4j password from config")

    args = parser.parse_args()

    if args.mcp:
        run_mcp()
    elif args.detect:
        run_detection(args.config, args.output, args.limit, args.uri, args.user, args.password)
    elif args.api:
        port = args.port or 8000
        run_api(host=args.host, port=port, reload=args.reload)
    else:
        parser.print_help()
