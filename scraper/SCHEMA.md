# Coima — Graph Schema Reference

The Neo4j graph the [scraper](README.md) writes: every node label, every
relationship type, how monetary amounts are linked to economic indicators, and
a few worked Cypher queries.

This is the same graph exported by
[`export_dataset.py`](export_dataset.py) for the public dataset — see
[DATASET_README.md](../DATASET_README.md).

## Portal scoping (schema v2)

The scraper ingests two portals, COMPR.AR and CONTRAT.AR, into the same graph.
Portal-scoped identifiers (UOC codes, SCO numbers, contractual document
numbers) are sequential per UOC and their ranges overlap between portals, so
`ContractingUnit`, `ProcurementRequest`, `ContractualDocument` and
`ContractLine` carry `source` (`comprar` or `contratar`) inside their merge
key. Those composite keys arrived in schema **v2**; a database created before
it is migrated automatically on the first run (`source` is backfilled to
`comprar` and the legacy single-property constraints are dropped). The current
schema version is **v4** — see `_SCHEMA_VERSION` in
[`ingestion/neo4j_client.py`](ingestion/neo4j_client.py) for the changelog.

`Process` numbers are globally unique and stay single-keyed, enforced by a
cross-source guard at ingestion. `Provider` (CUIT), `Organization` (SAF) and
`Authorizer` are deliberately **shared across portals** — that is what makes
cross-portal analysis possible, e.g. a construction firm that also sells goods.

Every `Process` carries a `source` property.

## Pre-award opinions (CONTRAT.AR)

Each dictamen is a `Dictamen` node hanging off its process via
`HAS_DICTAMEN`, keyed by `(process_number, source, sequence)` — the portal
exposes no stable id, so `sequence` is the 1-based order among a process's
opinions. It carries the issue date, recommended winner and pre-award total,
offers count, legal framework and budget imputation, and links out to:

- `(Dictamen)-[:EVALUATED_BY]->(DictamenSigner)` — the evaluation committee.
  Signers live in their own node keyed by portal `username` (a raw CUIT when
  no username is exposed), distinct from the named `Authorizer` registry.
- `(Dictamen)-[:PRE_ADJUDICATES]->(Provider)` — the committee's recommended
  winner per renglón (`is_primary=true`) and merit-ordered runners-up
  (`is_primary=false`), with quantity, unit price and line total.
- `(Dictamen)-[:REJECTED]->(Provider)` — each discarded bidder, with the
  per-requirement rejection reasons (`reasons`) and free-text `justification`.

Provider business names shown on the dictamen grids are resolved to CUITs via
the process's already-scraped providers; the rejected-bidder block exposes the
CUIT directly.

CONTRAT.AR additionally yields official budget per renglón
(`LineItem.subtotal`), contract amount evolution
(`ContractualDocument.current_amount`, `variation_pct`, `revision_type`),
proposal guarantees on `Bid`, and the real opening datetime from the opening
act.

## Node types and relationships


### Node types

| Label | Key property | Description |
|---|---|---|
| `Process` | `process_number` | Central procurement process |
| `Organization` | `saf_code` | Servicio Administrativo Financiero (buying entity) |
| `ContractingUnit` | `(code, source)` | Unidad Operativa de Contrataciones (UOC) |
| `Provider` | `cuit` | Supplier or bidder registered in SIPRO |
| `LineItem` | `(process_number, line_number)` | Renglón declared in the pliego |
| `ProcurementRequest` | `(request_number, source)` | Solicitud de Contratación (SCO) |
| `Bid` | `(process_number, provider_cuit)` | One offer per provider per process |
| `BidLine` | `(process_number, provider_cuit, line_number, alternative_number)` | One renglón × alternative within a bid |
| `ContractualDocument` | `(document_number, source)` | Purchase Order (OC) or Open Purchase Order (OCA) |
| `ContractLine` | `(document_number, source, line_number, alternative_number)` | Renglón inside a purchase order |
| `ProvisionRequest` | `request_number` | Solicitud de Provisión (SPR) — call-off against an OCA |
| `ProvisionRequestLine` | `(request_number, line_number, alternative_number)` | Line item in an SPR |
| `Authorizer` | `full_name` | Government official who signs a document |
| `GDEDocument` | `gde_number` | GDE-system attachment on a process |
| `Penalty` | `(process_number, number)` | Penalty clause in the process |
| `Dictamen` | `(process_number, source, sequence)` | Pre-award opinion (CONTRAT.AR) |
| `DictamenSigner` | `username` | Dictamen committee member (portal username) |
| `InflationIndex` | `(series_id, period)` | Monthly CPI observation (INDEC) |
| `ExchangeRate` | `(currency, observed_date, rate_type)` | Daily FX rate (BCRA) |
| `Address` | `value_key` | Normalized address (shared across entities) |
| `Phone` | `value_key` | Normalized phone number |
| `Email` | `value_key` | Normalized email address |

### Relationships

| From | Relationship | To | Notes |
|---|---|---|---|
| `Process` | `MANAGED_BY` | `ContractingUnit` | |
| `ContractingUnit` | `BELONGS_TO` | `Organization` | |
| `Process` | `HAS_LINE_ITEM` | `LineItem` | |
| `Process` | `HAS_REQUEST` | `ProcurementRequest` | |
| `Process` | `HAS_BID` | `Bid` | |
| `Process` | `HAS_PENALTY` | `Penalty` | |
| `Process` | `HAS_DOCUMENT` | `GDEDocument` | |
| `Process` | `GENERATES` | `ContractualDocument` | |
| `Process` | `INVITES` | `Provider` | CDI/LPU only |
| `Bid` | `SUBMITTED_BY` | `Provider` | |
| `Bid` | `HAS_BID_LINE` | `BidLine` | |
| `BidLine` | `FOR_LINE_ITEM` | `LineItem` | |
| `ContractualDocument` | `HAS_CONTRACT_LINE` | `ContractLine` | |
| `ContractualDocument` | `AWARDED_TO` | `Provider` | |
| `ContractualDocument` | `AUTHORIZED_BY` | `Authorizer` | Properties: `role`, `authorizer_type`, `authorized_at` |
| `ContractualDocument` | `HAS_PROVISION_REQUEST` | `ProvisionRequest` | OCA only |
| `ContractLine` | `FOR_LINE_ITEM` | `LineItem` | |
| `ProvisionRequest` | `HAS_PROVISION_LINE` | `ProvisionRequestLine` | |
| `ProvisionRequest` | `FULFILLED_BY` | `Provider` | |
| `ProvisionRequest` | `AUTHORIZED_BY` | `Authorizer` | |
| `ProvisionRequestLine` | `FOR_LINE_ITEM` | `LineItem` | |
| `Process` | `HAS_DICTAMEN` | `Dictamen` | CONTRAT.AR pre-award opinion |
| `Dictamen` | `EVALUATED_BY` | `DictamenSigner` | Properties: `role`, `status` |
| `Dictamen` | `PRE_ADJUDICATES` | `Provider` | Per renglón; `is_primary`, `merit_order`, prices |
| `Dictamen` | `REJECTED` | `Provider` | Discarded bidder; `reasons`, `justification` |
| `Bid` | `VALUED_AT_INFLATION` | `InflationIndex` | `ars_historico` on rel |
| `BidLine` | `VALUED_AT_INFLATION` | `InflationIndex` | `ars_historico` on rel |
| `ContractualDocument` | `VALUED_AT_INFLATION` | `InflationIndex` | `ars_historico` on rel |
| `ContractLine` | `VALUED_AT_INFLATION` | `InflationIndex` | `ars_historico` on rel |
| `ProvisionRequest` | `VALUED_AT_INFLATION` | `InflationIndex` | `ars_historico` on rel |
| `ProvisionRequestLine` | `VALUED_AT_INFLATION` | `InflationIndex` | `ars_historico` on rel |
| `Bid` | `VALUED_AT_FX` | `ExchangeRate` | Non-ARS nodes only |
| `BidLine` | `VALUED_AT_FX` | `ExchangeRate` | Non-ARS nodes only |
| `ContractualDocument` | `VALUED_AT_FX` | `ExchangeRate` | Non-ARS nodes only |
| `ContractLine` | `VALUED_AT_FX` | `ExchangeRate` | Non-ARS nodes only |
| `ProvisionRequest` | `VALUED_AT_FX` | `ExchangeRate` | Non-ARS nodes only |
| `ProvisionRequestLine` | `VALUED_AT_FX` | `ExchangeRate` | Non-ARS nodes only |
| `Organization` | `HAS_ADDRESS` | `Address` | |
| `Organization` | `HAS_PHONE` | `Phone` | |
| `Organization` | `HAS_EMAIL` | `Email` | |
| `ContractingUnit` | `HAS_ADDRESS` | `Address` | |
| `ContractingUnit` | `HAS_PHONE` | `Phone` | |
| `ContractingUnit` | `HAS_EMAIL` | `Email` | |
| `Provider` | `HAS_ADDRESS` | `Address` | |
| `Provider` | `HAS_PHONE` | `Phone` | |
| `Provider` | `HAS_EMAIL` | `Email` | |

---

---

## Economic Indicators

When `economic_indicators_enabled = true` (the default), the scraper loads two sets of
reference nodes used to contextualize monetary amounts without modifying the raw scraped
values.

### Sources

| Node | Source | Series |
|---|---|---|
| `InflationIndex` | INDEC IPC Nivel General Nacional | `148.3_INIVELNAL_DICI_M_26` |
| `InflationIndex` (2015-2016 fallback) | BCRA variable 27 | Used when INDEC series is absent |
| `ExchangeRate` | BCRA Estadisticas Cambiarias | `Cotizaciones/{codMoneda}` |

### How amounts are linked

Every amount-bearing node (`Bid`, `BidLine`, `ContractualDocument`, `ContractLine`,
`ProvisionRequest`, `ProvisionRequestLine`) receives two economic context relationships
at ingestion time:

- **`VALUED_AT_INFLATION`** links to the `InflationIndex` for the month in which the
  amount was observed. The relationship carries `ars_historico`: the amount converted
  to ARS at the exchange rate valid on that date (for non-ARS amounts) or the amount
  itself (for ARS amounts).

- **`VALUED_AT_FX`** links to the `ExchangeRate` for the specific day and currency.
  Only created for non-ARS amounts.

The `ars_historico` property allows inflation-adjusted comparisons across years using
only the graph, without external lookups.

The observation date used for each node type is:

| Node | Observation date |
|---|---|
| `Bid`, `BidLine` | Process opening date (fallback: portal publish date, gazette date, scraped_at) |
| `ContractualDocument` | Document perfection date (fallback: process opening date chain) |
| `ContractLine` | Parent document perfection date (fallback: process opening date chain) |
| `ProvisionRequest` | SPR creation date (fallback: scraped_at) |
| `ProvisionRequestLine` | Parent SPR creation date (fallback: scraped_at) |

### Nodes missing a same-month index

INDEC publishes each month's IPC with roughly a six-week lag, so amounts from the
current or prior month have no same-month `InflationIndex` node when they are
ingested. The ingestion builder handles this by linking to the nearest-prior index
of the matching series (the relationship's `matching_strategy` is then
`nearest_prior` instead of `same_month`).

---

---

## Useful Cypher Queries

### Count all nodes by label

```cypher
MATCH (n)
RETURN labels(n)[0] AS label, count(*) AS count
ORDER BY count DESC
```

### All expenses for a specific year, adjusted to today's prices

Returns every price-bearing node from a given year, its original amount, the
equivalent ARS at the time, and the real value today using the CPI chain.

```cypher
// Set the target year here
WITH 2022 AS target_year

MATCH (n)-[r:VALUED_AT_INFLATION]->(idx:InflationIndex)
WHERE idx.period_start.year = target_year
  AND r.ars_historico IS NOT NULL

// Resolve today's CPI index
OPTIONAL MATCH (today_idx:InflationIndex {series_id: idx.series_id})
WHERE today_idx.period_start <= date()
  AND today_idx.period_end   >= date()

WITH
  n,
  labels(n)[0]              AS node_type,
  r.ars_historico           AS ars_then,
  idx.index_value           AS cpi_then,
  today_idx.index_value     AS cpi_now

WHERE cpi_then IS NOT NULL AND cpi_now IS NOT NULL

RETURN
  node_type,
  count(n)                              AS quantity,
  round(sum(ars_then), 2)              AS total_ars_historico,
  round(sum(ars_then * cpi_now / cpi_then), 2) AS total_ars_hoy
ORDER BY total_ars_hoy DESC
```

### Providers with the most awarded contracts

```cypher
MATCH (p:Provider)<-[:AWARDED_TO]-(cd:ContractualDocument)
RETURN p.business_name AS provider, p.cuit AS cuit, count(cd) AS contracts,
       sum(cd.total_amount) AS total_awarded
ORDER BY contracts DESC
LIMIT 20
```

### Processes with no bids (deserted or voided)

```cypher
MATCH (proc:Process)
WHERE NOT (proc)-[:HAS_BID]->()
  AND proc.status IS NOT NULL
RETURN proc.process_number, proc.status, proc.descriptive_name
ORDER BY proc.process_number
```

### Full chain: Organization → its processes → awarded providers

```cypher
MATCH (org:Organization)<-[:BELONGS_TO]-(uc:ContractingUnit)<-[:MANAGED_BY]-(proc:Process)
      -[:GENERATES]->(cd:ContractualDocument)-[:AWARDED_TO]->(prov:Provider)
WHERE org.saf_code = 96
RETURN org.name, proc.process_number, cd.document_number,
       cd.total_amount, cd.currency, prov.business_name
ORDER BY proc.process_number
```

---
