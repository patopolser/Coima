# Coima graph schema (Neo4j 5)

Curated from scraper/SCHEMA.md for agents writing Cypher. Schema version v4.
`Provider` (CUIT), `Organization` (SAF) and `Authorizer` are shared across the
COMPR.AR and CONTRAT.AR portals; every `Process` has `source` = `comprar` or
`contratar`.

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
| `ProvisionRequest` | `request_number` | Solicitud de Provisión (SPR), call-off against an OCA |
| `ProvisionRequestLine` | `(request_number, line_number, alternative_number)` | Line item in an SPR |
| `Authorizer` | `full_name` | Government official who signs a document |
| `GDEDocument` | `gde_number` | GDE-system attachment on a process |
| `Penalty` | `(process_number, number)` | Penalty clause in the process |
| `Dictamen` | `(process_number, source, sequence)` | Pre-award opinion (CONTRAT.AR) |
| `DictamenSigner` | `username` | Dictamen committee member (portal username) |
| `InflationIndex` | `(series_id, period)` | Monthly CPI observation (INDEC) |
| `ExchangeRate` | `(currency, observed_date, rate_type)` | Daily FX rate (BCRA) |
| `Address` / `Phone` / `Email` | `value_key` | Normalized contact value, shared across entities |

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
| `Process` | `HAS_DICTAMEN` | `Dictamen` | CONTRAT.AR only |
| `Bid` | `SUBMITTED_BY` | `Provider` | |
| `Bid` | `HAS_BID_LINE` | `BidLine` | |
| `BidLine` / `ContractLine` / `ProvisionRequestLine` | `FOR_LINE_ITEM` | `LineItem` | |
| `ContractualDocument` | `HAS_CONTRACT_LINE` | `ContractLine` | |
| `ContractualDocument` | `AWARDED_TO` | `Provider` | |
| `ContractualDocument` / `ProvisionRequest` | `AUTHORIZED_BY` | `Authorizer` | |
| `ContractualDocument` | `HAS_PROVISION_REQUEST` | `ProvisionRequest` | OCA only |
| `ProvisionRequest` | `HAS_PROVISION_LINE` | `ProvisionRequestLine` | |
| `ProvisionRequest` | `FULFILLED_BY` | `Provider` | |
| `Dictamen` | `EVALUATED_BY` | `DictamenSigner` | role, status |
| `Dictamen` | `PRE_ADJUDICATES` / `REJECTED` | `Provider` | See key properties |
| `Provider` / `Organization` / `ContractingUnit` | `HAS_ADDRESS` / `HAS_PHONE` / `HAS_EMAIL` | `Address` / `Phone` / `Email` | |
| amount-bearing nodes | `VALUED_AT_INFLATION` / `VALUED_AT_FX` | `InflationIndex` / `ExchangeRate` | See Money |

### Key properties

- `Process`: process_number, source, descriptive_name, object_of_procurement,
  selection_procedure, process_type_code (e.g. LPR, LPU, CDI), modality, stage,
  status, opening_date, scheduled_portal_publish_date,
  official_gazette_publish_date, participating_providers_count,
  confirmed_offers_count, currencies, source_url.
  Anchor date idiom: `coalesce(p.opening_date, p.scheduled_portal_publish_date, p.official_gazette_publish_date)`.
- `Provider`: cuit, business_name, status, category.
- `Bid`: process_number, provider_cuit, status, rejection_reason, submitted_at,
  total_amount, currency.
- `BidLine`: line_number, alternative_number, description, unit_price,
  total_per_line, offered_quantity, is_adjudicated.
- `ContractualDocument` (OC / OCA / CON): document_number, document_type,
  status, authorization_date, perfection_date, total_amount, current_amount,
  variation_pct, currency, source_url.
- `ContractingUnit`: code, source, name, province. `Organization`: saf_code, name.
- `Authorizer`: full_name (upper-case). `AUTHORIZED_BY` carries role,
  authorizer_type, authorized_at.
- `LineItem`: process_number, line_number, description, quantity, subtotal
  (official budget, CONTRAT.AR).
- `Dictamen`: process_number, source, sequence. `PRE_ADJUDICATES` carries
  is_primary, merit_order and prices; `REJECTED` carries reasons and
  justification.
- `Address` / `Phone` / `Email`: value, value_key (normalized, shared between
  every entity that uses it).

### Money

Amounts are stored as scraped, in their own currency. Every amount-bearing node
links to `InflationIndex` via `VALUED_AT_INFLATION`, whose `ars_historico`
property is the amount in ARS at the time; non-ARS amounts also link to
`ExchangeRate` via `VALUED_AT_FX`.

### Example queries

```cypher
// Processes a provider won, with amounts
MATCH (p:Process)-[:GENERATES]->(cd:ContractualDocument)-[:AWARDED_TO]->(:Provider {cuit: $cuit})
RETURN p.process_number, p.descriptive_name, cd.total_amount, cd.currency
ORDER BY cd.total_amount DESC

// Providers that share a phone, email or address
MATCH (a:Provider)-[:HAS_PHONE|HAS_EMAIL|HAS_ADDRESS]->(c)<-[:HAS_PHONE|HAS_EMAIL|HAS_ADDRESS]-(b:Provider)
WHERE a.cuit < b.cuit
RETURN a.cuit, a.business_name, b.cuit, b.business_name, labels(c)[0] AS via, c.value

// How often two providers bid on the same process, and who won
MATCH (p:Process)-[:HAS_BID]->(:Bid)-[:SUBMITTED_BY]->(:Provider {cuit: $a}),
      (p)-[:HAS_BID]->(:Bid)-[:SUBMITTED_BY]->(:Provider {cuit: $b})
OPTIONAL MATCH (p)-[:GENERATES]->(:ContractualDocument)-[:AWARDED_TO]->(w:Provider)
RETURN p.process_number, collect(DISTINCT w.cuit) AS winners
```
