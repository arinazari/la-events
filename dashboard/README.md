# Dashboard — the hosted concierge page

A self-contained, static, install-as-PWA interface for the events catalog. Three views,
no framework, no build step:

- **Explore** — search / filter / present every event in the catalog (date, type,
  neighborhood, recommended rating, free-only), with per-event "why?" scoring, ticket
  links, enrichment (curator notes, type/sub-genre tags, hero images when present), and
  one-click add-to-calendar (`.ics`). Star events to plan around them.
- **Plan** — a chatbox concierge. It works in two tiers:
  1. a **local assistant** (no LLM) that parses your ask ("this weekend near me, house,
     top-rated") and answers instantly from the loaded catalog, and
  2. an **agent hand-off** that composes a precise concierge/night-planner prompt (your
     ask + the dashboard's filter context + your starred anchors) for your Claude Code
     session to turn into a sequenced dinner → show → afters itinerary.
- **Settings** — view and tune the taste/scoring/source config (`taste.yaml`,
  `profile.yaml`, `sources.yaml`), stage edits, preview a change-set, and hand it to the
  agent to apply + commit. Plus pipeline actions (refresh events, discover sources).

## Architecture — static + Claude Code hand-off

GitHub Pages serves static files only (no backend, nowhere safe to hold an API key), so the
page never calls an LLM or writes YAML directly. Instead it **composes** the right prompt and
hands it to the agent that already maintains this repo (your Claude Code session). The agent
does the work — builds the plan, edits the YAML — and **commits back**; the daily routine /
Pages redeploy then surface the results here. This keeps every secret out of the browser and
fits the repo's "all state lives in the repo" rule.

The hand-off is isolated to **one seam**, `js/handoff.js`:

```js
export const BACKEND_URL = "";   // empty = copy-and-paste hand-off (current)
```

Point `BACKEND_URL` at a small service that holds the Anthropic + GitHub keys and every
action POSTs there instead (real in-page streaming chat + auto-commit) — no other code
changes. The upgrade path is designed in; the static mode ships today.

## How it fits together

```
data/catalog.json ──┐
data/enrichment.json├─► scripts/build_dashboard.py ─► dashboard/data.json ─► index.html + js/*
taste.yaml          │     (scores each event the SAME way the digest does,        (static viewer)
profile.yaml        │      folds in enrichment, emits a config snapshot)
sources.yaml ───────┘
```

- **`scripts/build_dashboard.py`** reads the catalog + taste/profile/sources, scores every
  event via `scripts/lib/scoring.py` (the same module the digest uses, so ratings can't
  drift), folds in any cached scene-researcher enrichment, and writes `dashboard/data.json`
  with three parts: `events[]` (scored + enriched), `config` (the editable knobs for
  Settings), and the facets/metadata the filters need.
- **`index.html` / `js/*.js` / `styles.css`** are a pure viewer. The dashboard never scores
  — re-run the build script to refresh ratings/data.

`data.json` is committed so the page works on GitHub Pages without a backend.

### Files

```
index.html            app shell + tab nav
styles.css            dark, nightlife-leaning theme
js/app.js             entry: load feed, wire tabs, lazy-mount views
js/data.js            feed load + shared state + format helpers (the real catalog schema)
js/explore.js         the filterable event grid
js/chat.js            Plan view: local query engine + agent hand-off composer
js/settings.js        Settings view: config editing + change-set + hand-off
js/handoff.js         THE seam — compose prompt → copy/open Claude Code (or POST a backend)
js/ics.js             client-side .ics export
sw.js                 offline app-shell cache (PWA)
manifest.webmanifest  installable PWA metadata
```

## Use it

```bash
# Build the feed from the real catalog (default input: data/catalog.json)
python scripts/build_dashboard.py

# ...or from the bundled demo data while the catalog is still filling up:
python scripts/build_dashboard.py -i data/sample-catalog.json

# View locally (any static server; modules + fetch + SW need http, not file://)
cd dashboard && python -m http.server 8000
# open http://localhost:8000
```

`data.json` carries an `is_sample` flag; when built from `data/sample-catalog.json` the
header shows a **SAMPLE DATA** badge so demo data is never mistaken for the real feed.

## Keeping it fresh

The daily digest routine regenerates the feed and commits it (step 7 of
`routines/daily-digest-prompt.md`):

```bash
python scripts/build_dashboard.py && git add dashboard/data.json
```

Settings edits and plan requests flow the other way: the page hands the agent a prompt, the
agent commits the change, and the next build/redeploy reflects it.

## Hosting on GitHub Pages

`.github/workflows/deploy-dashboard.yml` publishes the `dashboard/` folder to Pages on every
push to `main` that touches it (and via manual "Run workflow"). One-time setup:

> **Settings → Pages → Build and deployment → Source: GitHub Actions**

The site is served with `dashboard/` as its root, so it loads `./data.json` and `./js/*`
relative to itself — no path changes needed. A web manifest + service worker make it
installable and openable offline on a phone.

> **Auth note:** Pages serves a public URL. The catalog is public LA events and the taste
> config is mildly personal but low-stakes, so the page ships unlisted/public for now. Real
> auth (private to Ari + friends) becomes relevant if/when the `BACKEND_URL` upgrade lands —
> that's the natural place to add it.
