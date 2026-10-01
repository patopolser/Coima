# Coima: guide for AI agents

Coima is anti-corruption intelligence for Argentine federal public procurement
(COMPR.AR / CONTRAT.AR): a scraper fills a Neo4j graph, detectors flag
suspicious patterns, and risk scores rank providers, contracting units and
officials. Module docs: `README.md`, `backend/README.md`, `scraper/SCHEMA.md`.

## Investigating with the `coima` MCP server

The `coima` MCP server (HTTP at `http://localhost:8000/mcp` when the Docker
stack runs; see `backend/README.md` for stdio) is the way to query the data.
Do not write ad-hoc scripts against Neo4j or SQLite for investigations.

1. `get_detection_status` to see what data exists.
2. Find the entity: `search_providers`, `search_entities` (units, officials),
   `search_tenders`.
3. Understand it: `get_entity_profile`, `get_entity_risk_breakdown`.
4. Map the network: `get_network_neighborhood`, `list_related_companies`,
   `get_entity_graph`.
5. Check the evidence: `get_tender` on the processes the findings cite;
   `run_cypher` (read `get_graph_schema` first) for anything else.
6. Keep the case: `list_investigations` / `get_investigation` to resume,
   `create_investigation`, `add_subject`, `add_note` as findings appear,
   `save_report` at the end.

A red flag is a lead for human review, not proof of wrongdoing (see
`DISCLAIMER.md`). Cite CUITs, process numbers, amounts and dates, and separate
what the data shows from what it suggests.

## Working on the code

- Backend tests: `cd backend && python -m pytest -q`.
- MCP tools live in `backend/src/mcp_server/tools/`; shared query logic lives
  in `backend/src/api/services/` so the REST API and the MCP server stay in sync.
