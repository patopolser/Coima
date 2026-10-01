# Security Policy

## Reporting a vulnerability

If you discover a security vulnerability in Coima, please report it **privately**. Do not
open a public issue for security problems.

- Email: polserpatricio@gmail.com
- Please include: a description of the issue, steps to reproduce, affected component
  (scraper / backend / frontend / infra), and any relevant logs (with secrets redacted).

You can expect an acknowledgement within a reasonable time. Please give us a chance to
release a fix before any public disclosure.

## Scope

This is a self-hosted application. The most relevant security concerns are:

- **Secrets handling.** API keys and the Neo4j password are read from environment
  variables (`COIMA_*`). Never commit a real `.env` file; only `.env.example` is tracked.
- **MCP endpoint.** `POST /mcp` lets AI agents read detection results, run read-only
  Cypher (enforced by a READ-access Neo4j transaction) and write investigation notes and
  reports. It only accepts `localhost` Host headers by default; set `COIMA_MCP_TOKEN` to
  also require a bearer token. Coima itself calls no third-party AI provider.
- **Exposure.** The backend and Neo4j browser are intended for trusted/local deployment.
  Do not expose them to the public internet without authentication and a reverse proxy.

## Out of scope

- The accuracy of detection results (these are heuristic indicators — see
  [DISCLAIMER.md](DISCLAIMER.md)).
- Vulnerabilities in the upstream data source (comprar.gob.ar).
