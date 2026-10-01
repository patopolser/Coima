# Coima

Anti-corruption intelligence platform for Argentine public procurement
([comprar.gob.ar](https://comprar.gob.ar) and
[contratar.gob.ar](https://contratar.gob.ar)).

*Leer en [español](LEEME.md).*

> **Important — read first.** Coima analyzes **public** procurement data and produces
> **statistical, heuristic risk indicators**. Its checks, scores, flags and findings
> highlight *patterns that may warrant review*; they are **not accusations and not proof**
> that any person or company committed any crime or irregularity. See
> [DISCLAIMER.md](DISCLAIMER.md) before using the software or the data.

## Live demo

A public instance runs at **[coima-demo.com](https://coima-demo.com)**. It serves
**real data** scraped from the official portals, but with **entity names censored**:
buyers, suppliers and officials are shown under stable pseudonyms, so the patterns
and risk indicators are genuine while no real name is attributed to any finding.
The demo is read-only and does not expose scraper control or the MCP server.

## Objective

Public procurement data is published process by process, with no way to see
patterns across buyers, suppliers, and time. Coima scrapes that data into a
graph, runs a battery of red-flag detectors over it (serial winners, anomalous
competition patterns, bid-rotation indicators, possible contract splitting,
shared-contact clusters, authorizer-bias indicators, etc.), assigns risk scores
to providers, and exposes everything through a dashboard and through an
[MCP server](#investigating-with-ai-agents-mcp) that AI agents such as Claude
Code and Codex use to investigate the data.

The goal is to turn scattered tender records into queryable, prioritized
**leads for human review** by journalists and auditors — not to label anyone as
guilty (see [DISCLAIMER.md](DISCLAIMER.md)).

## How it works

```
comprar.gob.ar ──┐
                 ├──> scraper ──> Neo4j graph ──> detectors ──> risk scores ──> UI
contratar.gob.ar ┘                (system of      (one Cypher    (SQLite)
                                   record)         query each)
```

1. The **scraper** walks each procurement process and its sub-pages, and writes
   the result into Neo4j with `MERGE`, so runs are idempotent and resumable. It
   also loads INDEC inflation and BCRA exchange-rate nodes, so amounts can be
   compared across years.
2. Neo4j is the **system of record**: every entity (process, buyer, supplier,
   bid, purchase order, official) is a node, and each detector is a graph query
   over their relationships.
3. A **detection run** executes every enabled check, stores its findings and the
   derived per-provider risk scores in SQLite under one run id, and marks the
   run done.
4. The **API** serves the latest completed run, so the UI is fast and never
   waits on Neo4j.

## Modules

| Folder | What it is | Read more |
|---|---|---|
| `scraper/` | Scrapes both procurement portals and ingests structured data into Neo4j. Runs as a one-shot CLI or as a backend-controllable supervisor. | [scraper/README.md](scraper/README.md) · [SCHEMA.md](scraper/SCHEMA.md) |
| `backend/` | FastAPI service and detection engine: runs the detectors, computes risk scores, serves entity profiles and graph data, exposes the MCP server for AI agents, and controls the scraper. | [backend/README.md](backend/README.md) · [CHECKS.md](backend/src/detector/checks/CHECKS.md) |
| `frontend/` | React + Vite single-page app: dashboard, risk scores, check findings, entity profiles, graph explorer, scraper control. | [frontend/README.md](frontend/README.md) |
| `infra/` | Docker Compose, per-service Dockerfiles and the nginx config that ties the four pieces together. | — |

The backend and the scraper run as **separate containers** and coordinate
through a shared volume (`control.json` / `run_status.json`); the backend never
spawns the scraper process directly.

## Quick start (Docker)

```bash
cp .env.example .env          # optional — defaults work out of the box
docker compose --env-file .env -f infra/docker-compose.yml up --build
```

Then open:

- Frontend: http://localhost:8080
- API docs: http://localhost:8000/docs
- Neo4j browser: http://localhost:7474 (user `neo4j`, password from `.env`)

Stop with `Ctrl+C`; `docker compose ... down` to remove containers (volumes
persist). Add `-v` to also wipe the Neo4j data and scraper progress.

> This stack is meant for **local/trusted use**: it publishes Neo4j and the
> backend to the host and leaves the admin surface open. Do not expose it to
> the internet as-is — see [SECURITY.md](SECURITY.md).

## Investigating with AI agents (MCP)

Coima ships an [MCP](https://modelcontextprotocol.io) server, so you can
investigate from **Claude Code** or **Codex** with your own subscription: no
AI keys to configure in Coima. The agent gets tools to rank and profile
providers, units and officials, explain risk scores, map collusion networks,
inspect processes, run read-only Cypher, and keep investigation cases (notes
and reports) that persist across sessions.

With the Docker stack running, the server is at `http://localhost:8000/mcp`.

- **Claude Code**: open the repo; the project's [`.mcp.json`](.mcp.json)
  registers `coima` automatically (approve it on first use, check with `/mcp`).
  From elsewhere: `claude mcp add --transport http coima http://localhost:8000/mcp`.
- **Codex**: add to `~/.codex/config.toml`:

  ```toml
  [mcp_servers.coima]
  url = "http://localhost:8000/mcp"
  ```

Then ask, for example, *"Investigate CUIT 30-12345678-9 and record what you
find"*. Running without Docker, setting a bearer token, and the full tool list
are in [backend/README.md](backend/README.md#mcp-server-for-ai-agents).

## Controlling the scraper

Open the **Scraper** page in the frontend. It shows whether a run is active,
how many processes have been scraped in total, and how many the last run
targeted, with **Start** / **Stop** buttons. Under the hood:

- `POST /api/scraper/start` writes a `run` command; the scraper supervisor
  picks it up within ~2s and starts scraping.
- `POST /api/scraper/stop` writes a `stop` command; the current process
  finishes, the Neo4j batch flushes, and progress is saved (graceful,
  resumable).
- `GET /api/scraper/status` reads the live `run_status.json`.

### Seeding existing scrape progress

The scraper resumes from `progress.json` in its output volume; a fresh volume
starts from zero. To carry over an existing progress file:

```bash
docker compose -f infra/docker-compose.yml cp \
  scraper/output/progress.json scraper:/data/scraper-output/progress.json
```

(or `docker cp <progress.json> <scraper-container>:/data/scraper-output/`).

## Local development (no Docker)

```bash
# Backend — http://localhost:8000
cd backend && pip install -r requirements.txt && python run.py --api

# Frontend — http://localhost:5173, proxies /api to :8000
cd frontend && npm install && npm run dev

# Scraper — one-shot CLI, or the backend-controllable service loop
cd scraper && pip install -r requirements.txt
python main.py --help
python supervisor.py
```

For local runs set `COIMA_NEO4J_URI` / `COIMA_NEO4J_PASSWORD` and, for the
backend↔scraper file channel, point both at the same directory via
`COIMA_OUTPUT_DIR` (scraper) and `COIMA_SCRAPER_CONTROL_DIR` (backend).

Per-module setup, layout and testing details are in each module's README.

## Configuration

All settings use the `COIMA_` env prefix; see [`.env.example`](.env.example)
for the full list, and the module READMEs for what each service reads.

Detection config (which checks are enabled, their weights and thresholds) is
derived from the registered checks and overlaid with user overrides edited from
the Settings page and stored in SQLite. The `run.py --detect` CLI path is
separate and reads `backend/config.json` directly instead.

## Data sources

- **Procurement:** [comprar.gob.ar](https://comprar.gob.ar) (goods and services)
  and [contratar.gob.ar](https://contratar.gob.ar) (public works) — Argentina's
  public procurement portals, "Ciudadano" pages. Scraping is polite by default;
  see the scraping-ethics section of [scraper/README.md](scraper/README.md).
- **Inflation (CPI):** INDEC IPC Nivel General Nacional.
- **Exchange rates:** BCRA Estadisticas Cambiarias.

The scraped dataset (raw public graph, without detection results) may be
published separately under its own license; see
[DATASET_README.md](DATASET_README.md).

## Legal and ethics

- Results are **heuristic indicators, not accusations**. Read [DISCLAIMER.md](DISCLAIMER.md).
- Right of reply / correction / takedown: see [DISCLAIMER.md](DISCLAIMER.md) §5.
- Contributors must keep all wording framed as indicators — see
  [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
- Security issues: see [SECURITY.md](SECURITY.md).

## License

Coima is licensed under the **GNU Affero General Public License v3.0**
(AGPL-3.0). See [LICENSE](LICENSE). The AGPL requires that anyone who runs a
modified version as a network service also make the corresponding source
available. The software is provided "AS IS", without warranty of any kind.
