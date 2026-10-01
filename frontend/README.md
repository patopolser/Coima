# Coima — Frontend

React + Vite single-page app. It reads the [backend](../backend/README.md) API
and renders the dashboard, risk scores, check findings, entity profiles, the
graph explorer and scraper control.

> Everything shown is a **statistical, heuristic risk indicator**, never an
> accusation. See [DISCLAIMER.md](../DISCLAIMER.md). The `DisclaimerBanner`,
> the per-page `LegalNote` and the layout footer exist to keep that visible
> next to the data; do not remove them when adapting the UI.

## Stack

| Concern | Choice |
|---|---|
| Build / dev server | Vite 5 |
| UI | React 18 + React Router 6 |
| Server state | TanStack Query 5 (caching, pagination, retries) |
| Charts | Recharts |
| Graph explorer | Cytoscape + fcose layout |
| i18n | i18next + react-i18next (EN/ES) |
| Markdown (AI reports) | react-markdown + remark-gfm |

No CSS framework and no component library: styling is one hand-written
stylesheet (`src/index.css`) built on CSS custom properties, plus a small set
of local primitives.

## Layout

```
frontend/
├── index.html
├── vite.config.js          # Dev server on :5173, proxies /api -> :8000
└── src/
    ├── main.jsx            # Entry: QueryClient + i18n bootstrap
    ├── App.jsx             # Routes, layout shell, legal footer
    ├── index.css           # All styling (CSS custom properties)
    ├── api/client.js       # Single fetch wrapper + one function per endpoint
    ├── pages/              # One file per route (see below)
    ├── components/
    │   ├── layout/         # Navbar, LanguageSwitcher, DisclaimerBanner
    │   ├── ui/index.jsx    # Primitives: RiskBadge, ScoreBar, FlagPill,
    │   │                   #   ConfidenceMeter, SearchBar, Pagination,
    │   │                   #   EmptyState, LoadingScreen, Skeleton
    │   ├── EvidenceBreakdown.jsx
    │   ├── LegalNote.jsx
    │   └── ProviderSearch.jsx
    ├── hooks/              # useLang (t + locale), useCheckLabels
    ├── utils/
    │   ├── checkColumns.jsx  # Renders finding tables from backend column metadata
    │   ├── money.js          # Compact amounts (ARS $2.5B) + exact tooltip
    │   └── ids.js            # base64url encoding for ids with slashes in routes
    └── i18n/               # i18next setup + en.json / es.json
```

## Pages

| Route | Page | What it shows |
|---|---|---|
| `/` | Dashboard | KPIs, findings by vector, latest run, run trigger |
| `/providers` | Providers | Ranked risk scores, flag filters, search |
| `/companies/:cuit` | CompanyDetail | One provider: score, evidence breakdown, findings |
| `/units` `/units/:code` | Units | Contracting units (UOC) and their profile |
| `/authorizers` `/authorizers/:name` | Authorizers | Officials who signed contractual documents |
| `/checks/:key` | CheckDetail | Every finding of one detector, paginated |
| `/graph` | GraphExplorer | Cytoscape relationship browser around an entity |
| `/scraper` | Scraper | Run state, progress, start/stop |
| `/settings` | Settings | Toggle checks, tune weights and thresholds |

## Data-driven finding tables

Finding tables are not hand-written per check. The backend ships column
metadata with every check (key, label, type, optional `currency_key`), and
`utils/checkColumns.jsx` maps each type to a renderer: `Money` (compact with
exact tooltip), `Date`, `Percentage`, `Provider`, `Authorizer`, `Contact`,
`ListString`, `ListMoney`, and so on.

Consequence: **a new detection check gets a working UI with no frontend
change**, as long as it declares its columns. Adding a new column *type* is
the only case that needs a change here.

## Internationalization

`src/i18n/` holds `en.json` and `es.json`; the choice persists in
`localStorage` under `coima_lang` and is sent to the API so server-side check
labels come back in the same language. Use the `useLang` hook when a component
needs both `t` and the locale for number/date formatting.

Every user-facing string goes through i18next. Keep both locale files in sync,
and keep the wording framed as indicators rather than accusations (see
[CONTRIBUTING.md](../CONTRIBUTING.md)).

## Running

```bash
npm install
npm run dev        # http://localhost:5173, /api proxied to :8000
npm run build      # production bundle -> dist/
npm run preview    # serve the built bundle locally
```

The dev server expects the backend on `http://127.0.0.1:8000`; change the
proxy target in `vite.config.js` if yours listens elsewhere. In Docker the
built bundle is served by nginx, which proxies `/api` to the backend
container instead.
