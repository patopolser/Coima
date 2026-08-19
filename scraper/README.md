# Coima — Scraper

Reads Argentine public procurement processes from
[comprar.gob.ar](https://comprar.gob.ar) (goods and services) and
[contratar.gob.ar](https://contratar.gob.ar) (public works), and ingests them
into the Neo4j graph the [backend](../backend/README.md) analyzes.

The full graph model — every node label, relationship, and the
economic-indicator linking — lives in [SCHEMA.md](SCHEMA.md).

## Overview

The scraper takes a list of process numbers, finds each one on the portal,
walks its detail page and every relevant sub-page (comparative offers table,
purchase orders, open purchase orders, provision requests, pre-award
opinions), extracts structured data, and writes it into Neo4j.

All writes use Cypher `MERGE`, so the scraper is **idempotent**: re-running it
over the same processes updates existing nodes instead of duplicating them.
Runs are resumable, and it only reads pages a member of the public can already
open in a browser.

## Layout

```
scraper/
├── main.py                  # CLI entry point and scrape orchestration
├── supervisor.py            # Service loop: backend-controllable scraping
├── control.py               # File-based control channel (control.json / run_status.json)
├── export_dataset.py        # Export the raw public graph for redistribution
├── config.py                # Settings: env vars + config.yaml + defaults
│
├── data/
│   ├── tenders.txt              # Input: COMPR.AR process numbers, one per line
│   └── tenders_contratar.txt    # Input: CONTRAT.AR process numbers
│
├── output/                      # Auto-created
│   ├── progress.json            # Resume state (COMPR.AR)
│   └── progress_contratar.json  # Resume state (CONTRAT.AR)
│
├── scraper/                 # Page parsers and data models
│   ├── models.py            # Pydantic models for every node type and relationship
│   ├── session.py           # HTTP session: VIEWSTATE handling, UA, retries
│   ├── search.py            # Search form POST + detail-URL extraction
│   ├── process_page.py      # Process detail page
│   ├── offers_page.py       # Comparative offers table -> Providers, Bids, BidLines
│   ├── oc_page.py           # Purchase orders (OC) and open purchase orders (OCA)
│   ├── spr_page.py          # Provision requests (SPR)
│   ├── acta_page.py         # Opening act (real opening datetime)
│   └── dictamen_page.py     # Pre-award opinion (CONTRAT.AR)
│
├── ingestion/               # Neo4j ingestion layer
│   ├── neo4j_client.py      # Driver wrapper: schema setup, migrations, batch ingest
│   ├── cypher_queries.py    # Cypher builders and the schema/constraint definitions
│   ├── price_entities.py    # Shared metadata for amount-bearing nodes
│   └── economic_indicators.py  # INDEC CPI and BCRA FX fetch + linking
│
└── utils/
    ├── logging_config.py    # Rich-powered structured logger
    └── parsers.py           # Date, float, string, URL and process-number helpers
```

## Installation

Requires Python 3.10+ and a reachable Neo4j instance.

```bash
pip install -r requirements.txt
```

## Usage

```bash
python main.py                              # scrape COMPR.AR with all defaults
python main.py --tenders data/my_list.txt   # custom input file
python main.py --batch-size 10              # larger Neo4j write batch
python main.py --log-level DEBUG            # verbose output

python main.py --source contratar           # scrape CONTRAT.AR instead
python main.py --source contratar --rescrape-open

python main.py --setup-schema-only          # apply constraints/indexes and exit
python main.py --force-schema               # re-apply schema even if already set up
python main.py --reset-progress             # ignore saved progress, start over
python main.py --refresh-indicators         # re-fetch inflation/FX data and exit

# Re-scrape open (non-terminal) processes from the last N months, read from
# Neo4j, bypassing the tenders file and saved progress.
python main.py --rescrape-open
python main.py --rescrape-open --rescrape-months 6

python main.py --help                       # full reference
```

Terminal states excluded from `--rescrape-open`: `Adjudicado`, `Adjudicado con
doc. contractuales generados`, `Desierto`, `Dejado Sin Efecto`. Every other
state (including null/unknown) counts as open.

### Backend-controlled mode

`supervisor.py` is the container entrypoint that turns the CLI into a service
the backend can drive. It polls `control.json` on the shared volume every ~2s:
a `run` command starts a scrape in a worker thread, a `stop` command requests a
graceful stop (the current process finishes, the Neo4j batch flushes, progress
is preserved). It owns `run_status.json`, which mirrors the live counters.

The backend only ever writes control and reads status — it never spawns this
process. Both sides must point at the same directory (`COIMA_OUTPUT_DIR` here,
`COIMA_SCRAPER_CONTROL_DIR` on the backend). All writes are atomic, so a reader
never sees a half-written file.

```bash
python supervisor.py
```

## Tenders file format

One process number per line. Inline `//` comments and blank lines are ignored;
the file is read as UTF-8 with BOM tolerance.

```
96-0043-LPR21        // SAF 96, LPR type, year 2021
14/3-0093-LPR24      // Sub-unit UOC: 14 slash 3
101-0001-CDI26
```

Format: `{saf_code}-{sequence}-{type}{year_2digit}`, with sub-unit UOCs written
as `{saf}/{sub}-{sequence}-{type}{year_2digit}`.

## Configuration

Resolution order: **environment variables** (`COIMA_*`) → **`config.yaml`** in
the working directory or the scraper directory → **defaults** in `config.py`.
A `.env` file in the working directory is loaded automatically if present.

| Setting | Env var | Default | Description |
|---|---|---|---|
| `neo4j_uri` | `COIMA_NEO4J_URI` | `neo4j://127.0.0.1:7687` | Neo4j Bolt URI |
| `neo4j_user` | `COIMA_NEO4J_USER` | `neo4j` | Neo4j username |
| `neo4j_password` | `COIMA_NEO4J_PASSWORD` | `password` | Neo4j password |
| `neo4j_max_conn` | `COIMA_NEO4J_MAX_CONN` | `5` | Connection pool size |
| `output_dir` | `COIMA_OUTPUT_DIR` | `output/` | Progress + control/status directory |
| `batch_size` | `COIMA_BATCH_SIZE` | `5` | Processes per Neo4j write transaction |
| `source` | `COIMA_SOURCE` | `comprar` | Portal to scrape: `comprar` or `contratar` |
| `tenders_file` | `COIMA_TENDERS_FILE` | `data/tenders.txt` | Input file (COMPR.AR) |
| `contratar_tenders_file` | `COIMA_CONTRATAR_TENDERS_FILE` | `data/tenders_contratar.txt` | Input file (CONTRAT.AR) |
| `comprar_base_url` | `COIMA_COMPRAR_BASE_URL` | `https://comprar.gob.ar` | COMPR.AR base URL |
| `contratar_base_url` | `COIMA_CONTRATAR_BASE_URL` | `https://contratar.gob.ar` | CONTRAT.AR base URL |
| `rescrape_months` | `COIMA_RESCRAPE_MONTHS` | `4` | Look-back window for `--rescrape-open` |
| `request_timeout` | `COIMA_REQUEST_TIMEOUT` | `30` | HTTP timeout in seconds |
| `spr_request_timeout` | `COIMA_SPR_REQUEST_TIMEOUT` | `90` | Longer timeout for slow SPR pages |
| `request_delay_seconds` | `COIMA_REQUEST_DELAY` | `1.0` | Polite crawl delay (`0` disables) |
| `max_retries` | `COIMA_MAX_RETRIES` | `3` | HTTP retry count (`0` disables) |
| `retry_backoff_factor` | `COIMA_RETRY_BACKOFF` | `0.5` | Seconds between retries (doubles each attempt) |
| `rotate_user_agent` | `COIMA_ROTATE_UA` | `false` | Cycle User-Agent on every request |
| `user_agent` | `COIMA_USER_AGENT` | Chrome 124 UA | Fixed User-Agent string |
| `log_level` | `COIMA_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |
| `economic_indicators_enabled` | `COIMA_ECON_INDICATORS` | `true` | Load inflation/FX nodes and link amounts |
| `economic_indicators_start_date` | `COIMA_ECON_START_DATE` | `2015-01-01` | First date for the indicator fetch |
| `economic_indicators_currencies` | `COIMA_ECON_CURRENCIES` | `USD,EUR,GBP,BRL,CHF,JPY` | FX currencies to fetch |

Example `config.yaml`:

```yaml
neo4j_uri: neo4j://192.168.1.10:7687
neo4j_password: mypassword
batch_size: 10
request_delay_seconds: 1.5
log_level: DEBUG
economic_indicators_currencies: "USD,EUR"
```

## Multi-portal support

Both portals run the same ASP.NET WebForms platform, so the pipeline is shared.
`--source contratar` switches the base URL, the default tenders file and the
progress file. Every `Process` carries a `source` property, and the nodes whose
identifiers are only unique within a portal carry `source` in their merge key.

`Provider` (CUIT), `Organization` (SAF) and `Authorizer` stay **shared across
portals**, which is what enables cross-portal analysis — for example, a
construction firm that also sells goods.

CONTRAT.AR additionally yields the official budget per renglón, contract amount
evolution, proposal guarantees, the real opening datetime, and the full
pre-award opinion (dictamen). See [SCHEMA.md](SCHEMA.md) for the details.

## Pipeline

`ScrapeOrchestrator` runs one process number end to end; a fresh instance is
created per process.

```
Process number
    │
    ▼
ProcessFinder.find()            POST BuscarAvanzado.aspx -> detail page URL
    │
    ▼
ProcessPageParser.parse()       Process, Organization (SAF), ContractingUnit (UOC),
                                LineItems, ProcurementRequests (SCO), Penalties,
                                GDEDocuments; INVITES for CDI/LPU processes
    │
    ├── Status Deserted or Voided -> STOP (no offer or award data)
    │
    ├── OffersPageParser.parse()   -> Providers, Bids, BidLines
    │
    ├── OCPageParser.parse()       -> ContractualDocument, ContractLines, Authorizers
    │     (one per purchase order; the OCA variant adds SPR links)
    │        └── SPRPageParser.parse() -> ProvisionRequest, lines, Authorizers
    │
    └── (CONTRAT.AR) ActaPageParser / DictamenPageParser
                                   -> real opening datetime, Dictamen + committee
    │
    ▼
ProcessResult -> Neo4jClient.ingest_batch()
```

Results accumulate in memory until `batch_size` processes are ready, then flush
in one write transaction per process, with retries on transient errors (up to 3
attempts, exponential back-off). A final flush runs after the loop.

## Resume, progress and schema setup

Completed process numbers are recorded in the per-source progress file in
`output/`. On restart they are skipped. This is purely operational state for
resuming interrupted runs — Neo4j remains authoritative thanks to `MERGE`.

Constraints, indexes and economic-indicator nodes are applied once per
database. A `_SchemaMeta` marker node records the applied version, so repeat
runs start instantly. `--force-schema` re-applies it; older databases are
migrated automatically (see [SCHEMA.md](SCHEMA.md)).

## Scraping ethics and rate limiting

Coima scrapes **public** data that the portals publish for citizen consultation
(the "Ciudadano" preview pages), under Argentina's public-procurement and
freedom-of-information framework. The scraper is designed as a polite,
good-faith client:

- It only reads pages a member of the public can already open in a browser. It
  does **not** authenticate, bypass access controls, or submit data.
- A **1 second crawl delay** is enabled by default, with bounded, backing-off
  retries on transient errors (429/5xx), so the portal is never hammered.
- Writes are idempotent and runs are resumable, so re-runs do not generate
  redundant traffic.

Please keep it that way: do not disable the delay for bulk runs, honour the
source's terms of use and `robots.txt`, and slow down further if you ever see
`429` responses. If you run a public deployment, set an identifiable
`COIMA_USER_AGENT` with a contact address.

## Exporting the dataset

`export_dataset.py` writes a redistributable snapshot of the **raw public
graph** — no detection results, no risk scores. Identity-document fields of
officials are redacted by default.

```bash
python export_dataset.py            # -> output/dataset/
```

See [DATASET_README.md](../DATASET_README.md) for the format, provenance and
license of that snapshot.
