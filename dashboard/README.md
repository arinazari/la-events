# Dashboard — the hosted concierge page

A self-contained, static, install-as-PWA front end for the events catalog. The UI is the
design Ari built in the design tool (a single `index.html` + its `support.js` runtime); the
**backend is unchanged** — `scripts/build_dashboard.py` still scores every event with
`scripts/lib/scoring.py` (the same module the digest uses) and writes `dashboard/data.json`.
The page is a pure viewer: it never scores and never calls an LLM in the browser.

## What's here

```
index.html            the dashboard (design-tool export; edit THIS file directly)
support.js            the "dc-runtime" that renders index.html (loads vendored React/Babel)
vendor/               React 18 + ReactDOM + @babel/standalone, vendored locally (no CDN)
data.json             the feed — built by scripts/build_dashboard.py (committed)
manifest.webmanifest  installable-PWA metadata
sw.js                 offline app-shell cache (PWA)
icon.svg              app icon
```

> **Heads up on the runtime:** this UI is a React app transpiled in the browser by
> `@babel/standalone` (~3 MB, vendored in `vendor/`). That's the cost of hosting a
> design-tool artifact as-is — first paint does a client-side transpile. It works offline
> and needs no CDN, but it is heavier than a hand-written static page. If that ever matters,
> the long-term cleanup is a build step that pre-transpiles (drops Babel from the client).

## How data flows (backend unchanged)

```
data/catalog.json ──┐
data/enrichment.json├─► scripts/build_dashboard.py ─► dashboard/data.json ─► index.html
taste.yaml          │     (scores each event the SAME way the digest does,        (pure viewer)
profile.yaml        │      folds in enrichment, emits config + facets)
sources.yaml ───────┘
```

`index.html` fetches `./data.json` at startup, normalizes the real catalog schema
(`date`+`start`, `price` string, `links[]`, `score`/`rating`/`reasons`, `enrichment`) into its
table, and renders. If `data.json` is unreachable (e.g. opened over `file://`) it falls back
to its bundled sample data, so it never renders blank.

## The two interactive features are static-safe

GitHub Pages serves static files only — no backend, nowhere safe for an API key — so the page
**never calls an LLM**. The design's two AI features were rewired to the repo's existing
patterns (the same approach the previous dashboard used):

- **ASK THE DIGEST** (chat sidebar) → a **local, no-LLM intent parser** (`localSpec()` in
  `index.html`, ported from the old `js/chat.js`). It turns "free house show this weekend near
  me" into a filter over the loaded catalog, instantly and offline.
- **Discover new sources** → a **copy-to-Claude-Code hand-off**. It composes a Discover-mode
  prompt and copies it to the clipboard; you paste it into your Claude Code session, which
  proposes sources. Approval still happens in the repo (the registry's propose → human-approves
  rule). Nothing is auto-written to `sources.yaml`.

## Use it

```bash
# Build the feed from the real catalog (default input: data/catalog.json)
python scripts/build_dashboard.py

# ...or from the bundled demo data while the catalog is still filling up:
python scripts/build_dashboard.py -i data/sample-catalog.json

# View locally (any static server; fetch + service worker need http, not file://)
cd dashboard && python -m http.server 8000   # open http://localhost:8000
# (optional) test the "digest ↗" popup locally:
#   mkdir -p digests && cp "$(ls -1 ../digests/[0-9]*.md | sort | tail -1)" digests/latest.md
```

`data.json` carries an `is_sample` flag; built from `data/sample-catalog.json` the header shows
a **SAMPLE DATA** badge so demo data is never mistaken for the real feed.

## Keeping it fresh

The daily digest routine regenerates the feed and commits it (step 7 of
`routines/daily-digest-prompt.md`):

```bash
python scripts/build_dashboard.py && git add dashboard/data.json
```

## Hosting on GitHub Pages

`.github/workflows/deploy-dashboard.yml` publishes the `dashboard/` folder to Pages on every
push to `main` that touches it (and via manual "Run workflow"). The deploy step also stages the
newest dated digest into the artifact as `digests/latest.md` for the "digest ↗" popup. One-time
setup:

> **Settings → Pages → Build and deployment → Source: GitHub Actions**

The site is served with `dashboard/` as its root, so `index.html` loads `./data.json`,
`./support.js`, and `./vendor/*` relative to itself — no path changes needed.

## Editing the design later

`index.html` is the source of truth — edit it directly (it's plain HTML + an inline component
class; the JS is standard, no JSX). If you'd rather keep iterating in the design tool, edit
there and re-export over `index.html` (keep `support.js` beside it). `support.js` is the
generated runtime; the only hand-edit is the three `vendor/` paths (originally unpkg URLs).

## Upgrade path (optional, later)

To enable real in-page chat / auto-commit, stand up a small service holding the Anthropic +
GitHub keys and POST the composed prompts to it instead of the clipboard hand-off — that
hand-off is the single seam to swap. Public/unlisted Pages is fine until then (the catalog is
public LA events).
