# Coima — Frontend

React + Vite single-page app. It reads the [backend](../backend/README.md) API
and renders the dashboard, risk scores, check findings, entity profiles, the
graph explorer and scraper control.

> Everything shown is a **statistical, heuristic risk indicator**, never an
> accusation. See [DISCLAIMER.md](../DISCLAIMER.md). Three pieces keep that
> visible; do not remove them when adapting the UI:
> - `TermsGate`: blocking terms of use. No page mounts (or fetches) until the
>   current `TERMS_VERSION` (`src/legal/terms.js`) is accepted; bump it when the
>   terms text changes and everyone is asked again.
> - `RiskCaveat`: the one-line caveat next to every score, plus the tooltip on
>   the "Risk" / "Signals" column headers.
> - The footer links to `/terms` and to the correction contact.

## Stack

| Concern | Choice |
|---|---|
| Build / dev server | Vite 5 |
| UI | React 18 + React Router 6 |
| Server state | TanStack Query 5 (caching, pagination, retries) |
| Graph explorer | Cytoscape + fcose layout |
| i18n | i18next + react-i18next (EN/ES) |
| Motion | Own helper over the Web Animations API (`src/motion/`) |

No CSS framework and no component library: styling is hand-written CSS on
custom properties (`src/styles/tokens.css`), plus a small set of local
primitives. Light theme only.

## Design rules

The reference prototype and the design consult live in
[docs/design/](../docs/design/). In short:

- **One focal point per screen**; the accent color marks one next action.
- **Concrete titles, no decorative text.** Detail goes behind a tooltip or a
  disclosure ("How it's computed", "Configure"); nothing is removed, only folded.
- **Defined reading order.** Sections carry `data-reveal="1..n"` and rise in
  that order (`Reveal`), so the animation walks the eye along the path.
- **Risk is always level + score** ("High 72"), cut-offs 40/60/80.
- **Glass for chrome only** (navbar, menus, modals). Data sits on opaque white.

## Motion

Every movement goes through `src/motion/` (Web Animations API, no dependency),
and everything collapses to no motion under `prefers-reduced-motion`:

| Piece | Use |
|---|---|
| `PageTransition` | Route fade, scroll reset, focus to `<main>` |
| `Reveal` / `useReveal` | Reading-order entrance of `data-reveal` sections |
| `useAnimatedList` | Staggered entrance of new rows, FLIP on reorder |
| `usePresence` | Keeps modals, menus, tooltips mounted through their exit |
| `Disclosure` | Animated expand / collapse |
| `AnimatedValue` | Crossfade between real values (never counts from zero) |
| `useGlassPointer` | Specular highlight that follows the pointer on glass |

Durations and curves live in `src/styles/tokens.css` and are mirrored in
`src/motion/tokens.js`.

## Layout

```
frontend/
├── index.html
├── vite.config.js          # Dev server on :5173, proxies /api -> :8000
└── src/
    ├── main.jsx            # Entry: QueryClient + i18n bootstrap
    ├── App.jsx             # Routes, layout shell, terms gate, 404
    ├── index.css           # Component styles
    ├── styles/             # tokens.css, glass.css, motion.css
    ├── motion/             # Animation helper (see Motion)
    ├── legal/terms.js      # TERMS_VERSION + acceptance storage
    ├── api/client.js       # Single fetch wrapper + one function per endpoint
    ├── pages/              # One file per route (see below)
    ├── components/
    │   ├── layout/         # Navbar, Footer, LanguageSwitcher
    │   ├── legal/          # TermsGate, terms text, RiskCaveat
    │   ├── brand/          # Logo mark, star loader, 404 crescent
    │   ├── entity/         # EntityDetail: shared provider/unit/official profile
    │   ├── ui/             # RiskBadge, ScoreBar, InfoTip, Menu, Switch,
    │   │                   #   SearchBar, Pagination, states, Toast
    │   └── ProviderSearch.jsx  # Autocomplete (providers, units, officials)
    ├── hooks/              # useLang (t + locale), useCheckLabels
    ├── utils/
    │   ├── dates.js          # Short localized dates
    │   ├── checkColumns.jsx  # Renders finding tables from backend column metadata
    │   ├── money.js          # Compact amounts (ARS $2.5B) + exact tooltip
    │   └── ids.js            # base64url encoding for ids with slashes in routes
    └── i18n/               # i18next setup + en.json / es.json
```

## Pages

| Route | Page | What it shows |
|---|---|---|
| `/` | Dashboard | KPIs, highest risk, detectors; re-run in the "…" menu |
| `/providers` | Providers | Ranked risk scores, detector filter, search |
| `/companies/:cuit` | CompanyDetail | Score, signals by contribution, evidence |
| `/units` `/units/:code` | Units | Contracting units (UOC) and their profile |
| `/authorizers` `/authorizers/:name` | Authorizers | Officials who signed contractual documents |
| `/checks/:key` | CheckDetail | Every finding of one detector, paginated |
| `/graph` | GraphExplorer | Cytoscape relationship browser around an entity |
| `/scraper` | Scraper | Run state, progress, start/stop |
| `/settings` | Settings | Toggle checks, tune weights and thresholds |
| `/terms` | Terms | Terms of use (readable before accepting) |
| `*` | NotFound | 404 |

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
