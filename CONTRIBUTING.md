# Contributing to Coima

Thanks for your interest in contributing. Coima is a civic-tech, anti-corruption
transparency project. Contributions of code, documentation, checks, and bug reports are
welcome.

## Before you start

- Read the [README](README.md), the [DISCLAIMER](DISCLAIMER.md), and the
  [check-authoring reference](backend/src/detector/checks/CHECKS.md).
- By contributing you agree that your contribution is licensed under the project license
  ([AGPL-3.0](LICENSE)).

## Ground rules

1. **Non-accusatory framing.** This project surfaces *statistical indicators*, not
   accusations. Any user-facing text, check description, label, or report wording must
   describe **patterns / signals / risk indicators**, never assert that a named person or
   company is guilty of a crime or wrongdoing. PRs that introduce accusatory language will
   be asked to reword.
2. **Respect the data source.** Scraping must stay polite (see the rate-limit settings in
   `scraper/config.py` and the scraping-ethics section of
   [scraper/README.md](scraper/README.md)). Do not add features that hammer
   comprar.gob.ar or circumvent access controls.
3. **No secrets in commits.** Never commit real API keys, passwords, or a populated
   `.env`. Use `.env.example` for templates.
4. **Personal data.** Be conservative with personal data. Do not add fields that expose
   document numbers or other sensitive personal identifiers beyond what is necessary and
   already public.

## Development setup

See [README.md](README.md) ("Local development") for backend, frontend, and scraper
setup, and each module's own README for its layout and tests. The Python code targets
3.10+ and a 100-character line length; match the style of the file you are editing.

Backend tests (pure data shaping, no Neo4j and no network):

```bash
cd backend && python -m pytest -q
```

## Adding a detection check

Detection checks are single self-contained files in `backend/src/detector/checks/`.
Follow the step-by-step guide in
[CHECKS.md](backend/src/detector/checks/CHECKS.md). Include a Spanish `i18n` block and
keep descriptions framed as indicators.

## Pull requests

- Keep PRs focused and describe the motivation.
- Update documentation when you change behavior.
- For new checks, explain the heuristic, its known false positives, and the legitimate
  explanations a flagged pattern might have.
