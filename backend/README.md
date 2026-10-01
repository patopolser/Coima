# Coima — Backend

FastAPI service and detection engine. It runs the red-flag detectors over the
Neo4j graph the [scraper](../scraper/README.md) fills, turns their hits into
per-provider risk scores, and serves everything the
[frontend](../frontend/README.md) renders.

> Detection output consists of **statistical, heuristic risk indicators**, not
> accusations. See [DISCLAIMER.md](../DISCLAIMER.md).

## How it works

```
Neo4j graph ──> detector/runner ──> findings ──┐
   (scraper)     (one Cypher query              ├──> SQLite (DetectionRun,
                  per check)                    │     DetectionFinding, RiskScore)
                                                │
                 detector/scoring ──> scores ───┘
                                                      │
                                       api/routers ───┴──> JSON for the SPA
```

A **detection run** is the unit of work. `POST /api/detection/run` executes
every enabled check against Neo4j, stores the findings and the derived risk
scores in SQLite under one `run_id`, and marks the run done. Every read
endpoint serves the latest completed run, so the API stays fast and the UI
never waits on Neo4j.

Neo4j is the system of record for procurement data; SQLite holds only derived
state (runs, findings, scores, config overrides, saved investigations).

## Layout

```
backend/
├── run.py                  # CLI: --api (REST server) | --detect (one-shot report) | --mcp (MCP over stdio)
├── config.json             # Detection config for the --detect CLI path only
├── requirements.txt
├── data/
│   └── coima.seed.db       # Schema-only SQLite seed baked into the Docker image
├── tests/                  # pytest: scoring, analyzers, metrics, MCP server
└── src/
    ├── detector/           # Detection engine
    │   ├── checks/         # One file per red flag (auto-discovered) + CHECKS.md
    │   ├── analytics/      # networkx metrics: co-bidding graph, communities
    │   ├── base.py         # Check registry and shared query helpers
    │   ├── columns.py      # Column type metadata consumed by the UI
    │   ├── date_filter.py  # Optional date-window filtering of a run
    │   ├── runner.py       # Executes the enabled checks, collects findings
    │   └── scoring.py      # Findings -> per-provider risk scores
    ├── api/                # FastAPI app
    │   ├── main.py         # App, middleware stack, router wiring
    │   ├── config.py       # Settings (COIMA_* env vars, pydantic-settings)
    │   ├── security.py     # Rate limit, body cap, security headers, cooldowns
    │   ├── dependencies.py # DI providers (Neo4j driver, SQLite session, settings)
    │   ├── locale.py       # Per-request locale resolution
    │   ├── routers/        # HTTP endpoints
    │   ├── services/       # Business logic
    │   ├── schemas/        # Pydantic request/response models
    │   └── database/       # neo4j.py (driver) + sqlite.py (ORM + session)
    ├── mcp_server/         # MCP server for AI agents (tools, prompts, graph schema)
    └── i18n/               # Server-side EN/ES strings for check metadata
```

## Detection checks

Each red flag is one self-contained file in `src/detector/checks/` exporting a
`CHECK` dict: the Cypher query, the UI column metadata, the risk weight, and
EN/ES labels. Files are auto-discovered at import time, so adding or removing
a check is a single-file operation with no registry to update.

16 checks ship today, covering serial winners, bid rotation, cover bidding,
contract splitting, shared-contact clusters, authorizer bias, cost overruns,
and more. The full list and the authoring guide are in
[src/detector/checks/CHECKS.md](src/detector/checks/CHECKS.md).

`scoring.py` aggregates a provider's check hits into a 0-100 risk score with a
confidence level and an evidence breakdown, including synergy bonuses when
several checks that reinforce each other fire on the same entity.

## MCP server for AI agents

`src/mcp_server/` exposes Coima to MCP clients such as Claude Code and Codex.
The agent brings its own model, so Coima needs no AI keys. The same tools are
served over two transports:

| Transport | How | Use it when |
|---|---|---|
| Streamable HTTP | `POST /mcp` on the API (stateless, JSON responses) | The Docker stack or `run.py --api` is running |
| stdio | `python run.py --mcp`, launched by the client | Local development without the API process |

Both read the same Neo4j and SQLite as the API (paths resolve from `backend/`,
whatever the cwd). With Docker, use HTTP: the SQLite file lives in the
`backend_data` volume, which a host-side stdio process cannot see.

**Connecting.** The repo's `.mcp.json` registers the HTTP server for Claude
Code. For stdio, install the backend into a venv and register it:

```bash
python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt
claude mcp add coima-local -- "$PWD/backend/.venv/bin/python" "$PWD/backend/run.py" --mcp
codex mcp add coima-local -- "$PWD/backend/.venv/bin/python" "$PWD/backend/run.py" --mcp
```

Codex over HTTP: in `~/.codex/config.toml`, set `[mcp_servers.coima]` with
`url = "http://localhost:8000/mcp"`. If `COIMA_MCP_TOKEN` is set, add
`bearer_token_env_var = "COIMA_MCP_TOKEN"` (Codex) or
`--header "Authorization: Bearer $COIMA_MCP_TOKEN"` (`claude mcp add`).

**Tools.** Every list is paginated or capped and reports what it left out.

| Group | Tools |
|---|---|
| Detection | `get_detection_status`, `list_checks`, `get_check_findings` |
| Entities | `search_providers`, `search_entities` (units, authorizers), `get_entity_profile`, `get_entity_risk_breakdown` |
| Networks | `get_network_neighborhood`, `list_related_companies`, `get_entity_graph` |
| Processes | `search_tenders`, `get_tender` |
| Graph | `get_graph_schema`, `run_cypher` |
| Cases (write) | `list_investigations`, `get_investigation`, `create_investigation`, `add_subject`, `add_note`, `save_report`, `set_investigation_status` |

All tools are read-only except the case tools, which only add data (nothing
deletes). `run_cypher` runs in a READ-access Neo4j transaction, so the database
itself rejects writes; it also has a 30s timeout and row and size caps.
Prompts: `investigate_company` and one `report_<type>` per report kind
(executive summary, timeline, network analysis, cartel hypothesis), shown in
Claude Code as `/mcp__coima__<name>`.

Investigation cases live in SQLite (`investigations`, `investigation_subjects`,
`investigation_notes`, `investigation_reports`). Databases created before the
MCP server may still have an unused `investigation_messages` table from the
removed chat; it is harmless.

## Endpoints

| Group | Endpoints |
|---|---|
| Detection | `POST /api/detection/run`, `GET /api/detection/latest` |
| Risk scores | `GET /api/risk-scores`, `GET /api/risk-scores/flags` |
| Checks | `GET /api/checks`, `GET /api/checks/{key}` |
| Entities | `GET /api/companies/{cuit}`, `GET /api/units`, `GET /api/units/{code}`, `GET /api/authorizers`, `GET /api/authorizers/{name}` |
| Graph | `GET /api/graph/company/{cuit}`, `GET /api/graph/unit/{code}`, `GET /api/graph/authorizer/{name}` |
| Dashboard | `GET /api/dashboard/stats` |
| MCP | `POST /mcp` (Streamable HTTP; see [MCP server](#mcp-server-for-ai-agents)) |
| Scraper control | `GET /api/scraper/status`, `POST /api/scraper/{start,stop,rescrape-open,refresh-indicators}` |
| Meta | `GET /api/health`, `GET /api/health/deep` |

Interactive docs at `/docs` while the server is running.

## Scraper control

The backend and the scraper run as **separate processes/containers**. The
backend never spawns the scraper: it writes `control.json` into a shared
directory and reads back `run_status.json`, which the scraper's supervisor
loop polls every ~2s. Point both at the same directory via
`COIMA_SCRAPER_CONTROL_DIR` (backend) and `COIMA_OUTPUT_DIR` (scraper).

## Configuration

All settings use the `COIMA_` env prefix; see [`.env.example`](../.env.example)
for the full list. The ones the backend cares about most:

| Variable | Default | Purpose |
|---|---|---|
| `COIMA_NEO4J_URI` | `bolt://localhost:7687` | Graph database |
| `COIMA_NEO4J_USER` / `COIMA_NEO4J_PASSWORD` | `neo4j` / `password` | Credentials |
| `COIMA_SQLITE_PATH` | `data/coima.db` | Derived state store |
| `COIMA_SCRAPER_CONTROL_DIR` | `/data/scraper-output` | Shared control/status directory |
| `COIMA_CORS_ORIGINS` | `*` | Comma-separated allowed origins; empty = same-origin only |
| `COIMA_RATE_LIMIT_PER_MINUTE` | `240` | Per-IP requests per 60s window (`0` disables) |
| `COIMA_TRIGGER_COOLDOWN_SECONDS` | `60` | Min gap between expensive triggers (`0` disables) |
| `COIMA_MAX_BODY_BYTES` | `1000000` | Request body cap (`0` disables) |
| `COIMA_MCP_TOKEN` | — | If set, `/mcp` requires `Authorization: Bearer <token>` |
| `COIMA_MCP_ALLOWED_HOSTS` | — | Extra `Host` values `/mcp` accepts besides localhost (comma-separated, e.g. `coima.lan:*`) |
| `COIMA_MCP_LOCALE` | `es` | Language of check labels in MCP tool output (`es` / `en`) |

Which checks are enabled, their weights and their thresholds are derived from
the registered checks and overlaid with user overrides edited from the
Settings page and stored in SQLite. The `run.py --detect` CLI path is separate
and reads `config.json` directly instead.

## Running

```bash
pip install -r requirements.txt

python run.py --api            # REST API on http://localhost:8000
python run.py --detect         # one-shot detection pass -> JSON report
python run.py --help           # full flag reference
```

Tests:

```bash
python -m pytest -q            # from backend/
```

The tests are pure data-shaping tests: no Neo4j and no network calls, so they
run anywhere.
