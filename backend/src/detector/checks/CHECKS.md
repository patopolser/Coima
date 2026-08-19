# Coima Detector — Check System

> **Nature of the checks.** Every check below is a **statistical / heuristic indicator**
> over public data, not a determination of wrongdoing. A check hit flags a *pattern that
> may warrant human review*; it is **not proof or an accusation** that any named person or
> company committed a crime or irregularity. Many flagged patterns have legitimate
> explanations. Write all check labels, descriptions, and reports in this spirit — as
> "indicators / signals / patterns", never as assertions of guilt. See
> [DISCLAIMER.md](../../../../DISCLAIMER.md).

## Overview

Each **check** is a single `.py` file in `src/detector/checks/`. It defines one module-level `CHECK` dict that the auto-discovery system picks up at import time. No registration step is needed — create the file and it appears in the API and UI automatically.

Archived check generations live in `old/`, `old_2/`, and `old_3/` subdirectories. These are ignored by the auto-discovery because `pkgutil.iter_modules` only iterates top-level modules.

---

## The Column Type System

Columns describe what data a check returns and how the frontend should render each field. They are defined using factory functions from `src/detector/columns.py`.

Instead of the old `(key, label)` tuple approach, every column is now a typed dict:

```python
{"type": "Percentage", "key": "win_pct", "label": "Win %"}
```

The `type` field drives the frontend renderer. The `key` field names the raw row field returned by the Cypher query.

### Available Column Types

| Factory | Type string | Row value | Rendered as |
| :--- | :--- | :--- | :--- |
| `col_process(key, label, url_key=)` | `Process` | `str` (process number) | Clickable link to comprar.gob.ar |
| `col_provider(key, label, name_key=, url_key=)` | `Provider` | `str` (CUIT) | CUIT linking to `/companies/<cuit>` + name |
| `col_quantity(key, label)` | `Quantity` | `int` | Plain number |
| `col_percentage(key, label)` | `Percentage` | `float` | `"<value>%"` |
| `col_string(key, label)` | `String` | `str` | Plain text |
| `col_money(key, label, currency_key=)` | `Money` | `float` | Compact amount (`"ARS $1.2M"`) with the exact figure in the tooltip |
| `col_date(key, label)` | `Date` | `ISO date string` | Locale date |
| `col_unit(key, label, name_key=)` | `Unit` | `str` (code) | Code linking to `/units/<code>` + name |
| `col_authorizer(key, label)` | `Authorizer` | `str` (name) | Name linking to `/authorizers/<name>` |
| `col_organization(key, label, name_key=)` | `Organization` | `str` (saf_code) | SAF code + name |
| `col_contact(key, label)` | `Contact` | `{type, contact}` | Icon + contact value (`Email` / `Phone` / `Address`) |
| `col_list_process(key, label)` | `ListProcess` | `[{process_number, comprar_url}]` | Comma-separated links |
| `col_list_string(key, label)` | `ListString` | `[str]` | Comma-separated |
| `col_list_money(key, label)` | `ListMoney` | `[{currency, amount}]` | Pills of compact amounts (`"ARS $1M"`, `"USD $500K"`) |
| `col_list_unit(key, label)` | `ListUnit` | `[{code, name}]` | Comma-separated codes |
| `col_list_organization(key, label)` | `ListOrganization` | `[{saf_code, name}]` | Comma-separated |
| `col_list_contact(key, label)` | `ListContact` | `[{type, contact}]` | Pills with contact icons |

**Supplementary key fields** (e.g. `name_key`, `url_key`, `currency_key`) reference *sibling fields in the same row* that provide supporting data. They are not displayed as separate columns — they feed the renderer of their parent column.

---

## CHECK Dict Reference

```python
CHECK = {
    # Required ------------------------------------------------------------------

    "key": str,
    # Unique snake_case identifier. Used as the API endpoint key, config key,
    # and risk-score flag name. Must be unique across all checks.

    "label": str,
    # Human-readable name shown in the UI check list (English source of truth).
    # Spanish text lives in this same file under "i18n" — see "Translations".

    "weight": int,
    # Default risk-score contribution (0–100). This is the source of truth for the
    # default weight; users override it at runtime from the Settings page (stored in
    # SQLite). A weight of 0 means the check is informational and adds no score.

    "thresholds": dict,   # optional
    # Declarative default values for every threshold this check reads, e.g.
    #   {"serial_min_bids": 5, "serial_min_win_pct": 60.0}
    # These are the single source of truth for the check's tunable parameters:
    # they seed the Settings UI and are merged into the effective config. Reference
    # the same values inside `params` (define a module-level THRESHOLDS dict and use
    # it in both places) so there is no duplicated default.

    "query": str,
    # Cypher query. Must RETURN named columns that match the keys used in
    # ui_meta.columns and score_extractors.

    "params": callable,
    # Signature: (cfg: dict, limit: int) -> dict
    # Returns the parameter dict passed to driver.session().run().
    # Always include "limit" and forward it to LIMIT $limit in the query.

    "score_extractors": list[callable],
    # Each callable: (row: dict) -> (cuit: str, name: str)
    # Used to build the per-provider risk score. Return (None, None) or raise
    # to skip a row. Use one extractor per Provider column that contributes
    # to the score (e.g. two for checks that return two providers).

    "entity_extractors": dict[str, list[callable]],   # optional
    # Same shape as score_extractors but for non-provider namespaces, keyed by
    # namespace: {"unit": [...], "authorizer": [...]}. Each callable returns
    # (entity_id, name). Used by the scorer to score units/authorizers.

    # ENTITY TARGETING — IMPORTANT
    # "Who a check is directed at" is derived from its COLUMN TYPES, not from a
    # separate list: a check targets `provider` if it has a Provider column,
    # `unit` if it has a Unit column, `authorizer` if it has an Authorizer column
    # (see _TYPE_TO_NAMESPACE in api/services/scoring_service.py). Everything
    # downstream — the company/unit/authorizer indexes, the list/detail API
    # endpoints, and the frontend detail sections and chips — is derived from
    # this. Adding a typed column is all it takes for a check to show up under
    # that entity; there is no per-check registration anywhere else.
    #
    # INVARIANT: the typed columns and the extractors must agree. If a check
    # scores a unit (entity_extractors["unit"]) it must also expose a Unit
    # column for the same id, and vice versa, so membership (columns) and the
    # score math (extractors) never drift.

    "report_headers": list[str],
    # Column headers for the CLI printed table. Order must match report_row.

    "report_row": callable,
    # Signature: (row: dict) -> list
    # Returns display values for one row of the CLI table.

    "report_title": str,
    # Section header printed above the CLI table.

    "ui_meta": {
        "description": str,
        # One or two sentences explaining what this check detects and why it matters.
        # Also translated in src/i18n/locales/es.json when locale is Spanish.

        "color": str,
        # Tailwind/CSS color name for the badge: "red", "orange", "yellow",
        # "purple", "cyan", "rose", "fuchsia", "emerald", "slate", "indigo", etc.

        "columns": list[dict],
        # Typed column descriptors (see table above). Order determines column order in the UI.

        "search_fields": list[str],
        # Raw row field names that the search bar will match against (case-insensitive substring).
    },

    "i18n": {            # optional but expected for every active check
        "es": {
            "label": str,                       # Spanish check name
            "description": str,                 # Spanish description
            "columns": {"<col_key>": str, ...}, # Spanish label per column key
        },
        # Add more locales as { "<locale>": {...} }. Any locale not listed (and
        # English) falls back to the English source strings above.
    },
}
```

---

## Translations (i18n)

Translations live **inside the check's own `.py` file**, under `CHECK["i18n"]`. There is no
separate JSON catalog for checks — everything a check needs travels with it, so adding or
removing a check is a single-file operation.

**English** uses the source strings in `CHECK["label"]`, `ui_meta["description"]`, and each
column's `label`. **Spanish** (or any other locale) overrides them when the client sends
`Accept-Language: es` (or `?lang=es`). Anything not provided in `i18n` falls back to the
English source string, so partial translations are safe.

### What to translate

| `i18n["es"]` key | Overrides |
| :--- | :--- |
| `label` | `CHECK["label"]` |
| `description` | `ui_meta["description"]` |
| `columns.<col_key>` | The column whose factory `key` is `<col_key>` |

The `<col_key>` must match the column **`key`** field, not the display `label`. Example:
`col_provider("provider_cuit", "Provider", ...)` → `"provider_cuit": "Proveedor"`.

### Example (inside the check file)

```python
CHECK = {
    "key": "my_new_check",
    "label": "My New Check",
    ...
    "i18n": {
        "es": {
            "label": "Mi Nuevo Check",
            "description": "Qué detecta este check y por qué importa.",
            "columns": {
                "provider_cuit": "Proveedor",
                "some_pct": "Tasa",
            },
        },
    },
}
```

### How it is applied

`build_check_meta()` (in `src/api/services/scoring_service.py`) reads `CHECK["i18n"][locale]`
directly while building the API response. Locale `en` returns the source strings unchanged.

Static UI copy (nav, buttons, page titles) lives in
[`frontend/src/i18n/locales/`](../../../../frontend/src/i18n/locales/) and is separate from check metadata.

---

## Adding a New Check — Step by Step

### 1. Write the Cypher query

Write and test the query in Neo4j Browser. Make sure every RETURN alias is a valid Python identifier (no spaces). Add `LIMIT $limit` at the end.

### 2. Choose your column types

For each returned field that should be visible in the UI, pick the appropriate factory from `src/detector/columns.py`. If a field is only needed as supplementary data for another column (e.g. a URL for a Process column), it does **not** need its own column entry — just reference it via `url_key=`.

### 3. Create the file

```python
# src/detector/checks/my_new_check.py

from src.detector.columns import col_provider, col_percentage   # import what you need

QUERY = """
MATCH ...
RETURN prov.cuit AS provider_cuit, ...
LIMIT $limit
"""

THRESHOLDS = {"some_min_pct": 50.0}   # omit if the check has no tunables

CHECK = {
    "key":    "my_new_check",
    "label":  "My New Check",
    "weight": 10,
    "thresholds": THRESHOLDS,
    "query":  QUERY,
    "params": lambda cfg, limit: {
        "limit": limit,
        "min_pct": cfg.get("thresholds", {}).get("some_min_pct", THRESHOLDS["some_min_pct"]),
    },
    "score_extractors": [
        lambda r: (r.get("provider_cuit"), r.get("provider_name")),
    ],
    "report_headers": ["CUIT", "Company", ...],
    "report_row":     lambda r: [r["provider_cuit"], r["provider_name"][:30], ...],
    "report_title":   "MY NEW CHECK — Short description",
    "ui_meta": {
        "description": "What this detects and why it matters.",
        "color": "cyan",
        "columns": [
            col_provider("provider_cuit", "Provider", name_key="provider_name"),
            col_percentage("some_pct", "Rate"),
        ],
        "search_fields": ["provider_cuit", "provider_name"],
    },
    "i18n": {
        "es": {
            "label": "Mi Nuevo Check",
            "description": "Qué detecta este check y por qué importa.",
            "columns": {"provider_cuit": "Proveedor", "some_pct": "Tasa"},
        },
    },
}
```

### 4. That's it — no config or catalog edits

You do **not** edit `config.json`, `es.json`, or the database. The toggle, weight, and
thresholds are derived from this file automatically (see [Configuration](#configuration)),
and the Spanish strings come from `i18n` above. To remove a check, delete the file.

### 5. Verify

Start the API and hit `/api/checks` — your check should appear in the list. Then hit `/api/checks/my_new_check` to see paginated findings.

Test both locales:

```http
GET /api/checks/my_new_check
Accept-Language: en

GET /api/checks/my_new_check
Accept-Language: es
```

---

## Configuration

The active config (which checks are enabled, their weights, and all thresholds) is **derived
from the registered checks** and overlaid with **user overrides stored in SQLite**
(`detection_config` table). There is no required `config.json` for the API and no manual
seeding step.

- **Defaults** come from each `CHECK`: `weight`, `thresholds`, and enabled = `True`.
  See `registry_defaults()` in `src/api/services/config_service.py`.
- **Overrides** are edited from the frontend Settings page and persisted via
  `PUT /api/config`. The effective config is `registry_defaults` merged with the stored
  overrides, so a newly added check appears with its declared defaults even on an existing
  database, and a deleted check simply disappears.
- The `run.py --detect` **CLI** still reads `config.json` directly (separate path); the API
  ignores it for detection config and only uses its `connection` block for Neo4j settings.

---

## Implemented Checks

16 checks are registered today, ordered by risk weight. This table is generated
from the `CHECK` dicts themselves — if it disagrees with the code, the code
wins.

| Key | Label | Color | Weight |
| :--- | :--- | :--- | :--- |
| `cross_agency_proxy` | Cross-Agency Proxy Company | orange | 50 |
| `authorizer_provider_ring` | Authorizer-Provider Ring | red | 45 |
| `bid_rotation_ring` | Bid Rotation Ring | red | 40 |
| `shared_contact_cluster` | Shared-Contact Cluster | fuchsia | 40 |
| `fake_competition` | Fake Competition | red | 35 |
| `authorizer_bias` | Authorizer Bias | red | 30 |
| `contact_hub_multi_provider` | Provider Contact Hub | purple | 30 |
| `contract_splitting` | Contract Splitting | orange | 30 |
| `uoc_favoritism` | UOC Favoritism | fuchsia | 30 |
| `contract_cost_overrun` | Contract Cost Overrun | rose | 25 |
| `cover_bidding` | Cover Bidding | indigo | 20 |
| `serial_winner` | Serial Winner | purple | 20 |
| `cdi_abuse` | Direct Contracting Abuse | rose | 15 |
| `cobid_community` | Co-bidding Community | violet | 15 |
| `round_price_bids` | Round-Price Bids | yellow | 5 |
| `spending_spikes` | Spending Spikes | orange | 0 |

A weight of `0` means the check is informational: it produces findings for
review but contributes nothing to the risk score.
