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

## The chat: Concierge (LLM) ⇄ Fast filter

The chat has two modes, toggled in its header (default **Concierge**):

- **Concierge (LLM)** — a real conversational concierge that **answers questions**, recommends,
  and plans a night. Because the page is static (no API key in the browser), it POSTs to a
  `BACKEND_URL` — a small Cloudflare Worker that holds the Anthropic key and grounds the model on
  the live feed. **Deploy it + connect it** (see `backend/README.md`; tap "connect" in the chat
  header to set the URL/token). Until then, Concierge mode transparently falls back to ↓.
  Or **bring your own key**: *Settings (☰) → Claude API key* opens a modal with a `sk-ant-…` field +
  an on/off switch (and the shared access token below it). With the switch **on**, your key is stored
  in your browser and sent to the Worker per request — it pays for your messages and connects the
  concierge without the shared token; **off** falls back to the token (no silent failover — if a live
  key errors, flip it off and the token takes over). The header pill shows which API you're on. See
  `backend/README.md` → Auth.
- **Fast filter** — a **local, no-LLM intent parser** (`localSpec()` in `index.html`). Turns
  "free house show this weekend near me" into a filter over the loaded catalog, instantly and
  offline; also fuses events × dining into a rough plan and a night-planner hand-off prompt. This
  is the fallback whenever the backend is unset/unreachable, so the chat never dead-ends.

**Discover new sources** → a **copy-to-Claude-Code hand-off** (composes a Discover-mode prompt,
copies it; you paste it into Claude Code, which proposes sources — approval still happens in the
repo). Nothing is auto-written to `sources.yaml`.

## Profiles (per-person taste)

The **"prof"** link in the footer opens a popup: type a username and the page loads that person's
taste profile + digest. It works by hashing the username (SHA-256, salt `la-events/v1:`) and
fetching `data.<hash>.json` — the per-profile feed built by `scripts/build_profiles.py`. Blank or
unknown stays on the default (Ari's) feed; "log out" returns to it. The active profile persists in
localStorage.

You **create** a profile in the repo (a few friends, not open signup):

```bash
mkdir -p profiles/<name> && cp profiles/demo/taste.yaml profiles/<name>/taste.yaml  # then edit
#  add an entry to profiles.yaml (username = the key they type; name = display name)
python scripts/build_profiles.py            # rebuilds data.json + every profile feed
#  commit the new dashboard/data.<hash>.json (the whole dashboard/ folder is published)
```

**Self-edit (no repo access needed):** once a friend is in their profile, they can tune their taste
by *talking to the concierge* — "more techno, less comedy", "track Peggy Gou". The backend Worker
commits the change to their `profiles/<name>/taste.yaml`; CI (`build-profiles.yml`) re-scores the
feed with the same `build_profiles.py` scorer and redeploys (~1–2 min — the chat says "refresh
shortly"). The popup also shows their taste YAML read-only. Requires the backend deployed with a
`GITHUB_TOKEN` — see `backend/README.md`.

**This is obfuscation, not security:** the username is a public, guessable-if-known bearer key, and
each feed file is publicly fetchable. Taste *writes* are low-stakes too (every edit is a revertible
commit) — the backend's `CONCIERGE_TOKEN` guards API spend + commit-spam, not the data. Pick
non-obvious usernames. Still deferred (see ROADMAP): per-profile Spotify affinity.

Each profile also gets its own **personalized digest** (the daily routine writes `digests/<hash>/latest.md`
from their feed; the popup's "digest ↗" shows it). Until the routine has run for a new profile, the page
shows a "ranked picks are live in the table" placeholder.

## Guide & "What's new" (friend onboarding)

The **"? how it works"** chip next to the header title opens a two-tab modal: **How it works** (a
plain-language tour — the table, rank-vs-score, the concierge, signing in, tuning taste, installing the
PWA) and **What's new** (a short changelog of friend-facing features). Both are authored as Markdown
strings in `index.html` (`GUIDE_HOW` / `GUIDE_NEW`) and rendered through the same `renderMarkdown` the
digest modal uses, so they match its look exactly — no new styling.

**Surfacing, two tiers (the gate is `localStorage['la-guide-seen']` vs the `GUIDE_VERSION` constant):**
- A **true first-timer** (no stored version) gets *How it works* auto-opened once — light onboarding.
- A **returning visitor** with a stale version is *not* interrupted: a subtle blue dot appears on the
  "? how it works" chip, and the footer's **last site update** date becomes a link (both open *What's new*).
  The dot/link clear once they open the guide (`la-guide-seen` is rewritten to the current version).

**When you ship a friend-facing change, add a bullet to `GUIDE_NEW` and bump `GUIDE_VERSION`** — that lights
the dot (and re-links "last site update") for everyone on their next visit, without popping a modal at them.

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

## Upgrade path

The LLM **Concierge backend** is the realized version of this (see `backend/`): deploy the
Worker, set the Anthropic key, connect the URL/token. Still open as future work: streaming
responses, auto-committing generated plans back to the repo, and real auth (Cloudflare Access).
Public/unlisted Pages + the Fast-filter fallback is fine until then (the catalog is public LA
events).
