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

Login is a **personal link** (Track A1): each friend gets `…/?t=<token>` texted once — a random
capability token from `profiles.yaml`, not their name. Opening it signs that device in (the page
hashes the token — SHA-256, salt `la-events/v2:` — and fetches `data.<hash>.json`, the per-profile
feed built by `scripts/build_profiles.py`); the ⚷ popup also accepts a pasted key/link once. An
unknown key stays on the default (Ari's) feed; "log out" returns to it. The active profile persists
in localStorage.

You **create** a profile in the repo (a few friends, not open signup):

```bash
mkdir -p profiles/<name> && cp profiles/demo/taste.yaml profiles/<name>/taste.yaml  # then edit
#  add an entry to profiles.yaml (username = the human id; token = secrets.token_hex(8); name = display)
python scripts/build_profiles.py            # rebuilds data.json + every profile feed
#  commit the new dashboard/data.<hash>.json (the whole dashboard/ folder is published)
#  text the friend their link: https://<site>/?t=<token>
```

**Self-edit (no repo access needed):** once a friend is in their profile, they can tune their taste
by *talking to the concierge* — "more techno, less comedy", "track Peggy Gou". The backend Worker
commits the change to their `profiles/<name>/taste.yaml`; CI (`build-profiles.yml`) re-scores the
feed with the same `build_profiles.py` scorer and redeploys (~1–2 min — the chat says "refresh
shortly"). Requires the backend deployed with a `GITHUB_TOKEN` — see `backend/README.md`.

**Seeing your edits land:** the profile popup's "View taste & profile" opens a read-only modal with a
tab per file (taste + profile). Each shows a **diff** of how the concierge adjusted it and a single
**reflected/pending** badge — whether that change is live in your ranking & digest yet, or still
pending (with an *Update now →* button). It's all baked into the feed by `build_profiles.py` from git
(`profile.self_edit`), so it works on the static page with no backend; a friend's edit reads *pending*
until they hit Update (or the nightly run) regenerates their digest against the new taste.

**Access model:** the Google-Docs-link model — the token is an unguessable random bearer key, so a
capability URL is the whole gate (feed files are still publicly fetchable *if you know the hash*,
which is only derivable from the token). Usernames are just human ids for group planning now, not
keys. Taste *writes* stay low-stakes (every edit is a revertible commit) — the backend's
`CONCIERGE_TOKEN` guards API spend + commit-spam, not the data. `profiles.yaml` is the token map:
it must stay in the private repo, never in `dashboard/`.

Each profile also gets its own **personalized digest** (the daily routine writes `digests/<hash>/latest.md`
from their feed; the popup's "digest ↗" shows it). Until the routine has run for a new profile, the page
shows a "ranked picks are live in the table" placeholder.

## Onboarding — first-run welcome, guide & "What's new"

There are two onboarding surfaces, both authored as Markdown strings in `index.html` and rendered
through the same `renderMarkdown` the digest modal uses (so they match its look exactly — no new styling):

**1. First-run welcome (auto-opens after sign-in).** A short, **stepped** quick-start (`WELCOME` — four
steps: how the picks are made → **set yourself up** (connect the concierge with Ari's token / your own
key → tell it your neighborhood + tastes → connect Spotify) → **refresh your ranks** to fold it all in →
where everything else lives). It **auto-opens the first time someone signs into a profile** — on a fresh sign-in and on a
persisted-login reload (`maybeOnboard`, called from `applyProfile` and, guarded by a logged-in profile,
`componentDidMount`). It **never pops up on the logged-out default view**; the owner/default can preview
it from Settings → ABOUT → quick start. It is keyed per profile in localStorage (`la-onboarded:<hash>`),
and the **"Don't show this again" checkbox is the dismissal**: ticked → the flag is set and it never
auto-opens for that profile again; left un-ticked → closing it just hides it for now and it greets you
again next visit (deliberate — it nags until acknowledged). Re-openable any time from
**Settings → ABOUT → quick start**.

**2. Guide & changelog (manual).** A two-tab modal — **How it works** (the full plain-language tour:
the table, rank-vs-score, the concierge, signing in, tuning taste, installing the PWA) and **What's new**
(a short changelog of friend-facing features), `GUIDE_HOW` / `GUIDE_NEW`. These stay **manual and quiet** —
no auto-open; reached under Settings → ABOUT (*how it works* / *what's new*).

**Where it lives:** the **ABOUT** group in the **⚷ / ☰** settings popup (footer) — *quick start* (re-open
the welcome), *how it works* (tour), *what's new* (changelog). That group sits outside the logged-in /
logged-out branches, so it's reachable whether or not someone is signed in.

**When you ship a friend-facing change, add a bullet to `GUIDE_NEW`** (and a `## <month>` heading when a
new period starts). That's the only upkeep — friends find it under Settings → ABOUT.

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

## Hosting on Cloudflare Pages (Track A2)

`.github/workflows/deploy-dashboard.yml` publishes the `dashboard/` folder to **Cloudflare
Pages** (`https://la-events.pages.dev`) on every push to `main` that touches it (and via manual
"Run workflow"); the feed workflows (refresh-events / build-profiles / spotify-sync /
rebuild-profile) publish through the same shared step, `.github/actions/deploy-pages`. Each
deploy first stages the digests into the artifact (`digests/latest.md` + per-hash dirs) for the
"digest ↗" popup. Cloudflare Pages serves from a private repo on the free plan — that's the
point: the repo (profiles.yaml = the token map, taste files, history) goes private while the
site stays up. One-time setup (repo Actions secrets):

> `CLOUDFLARE_API_TOKEN` (a token with **Cloudflare Pages: Edit**) and `CLOUDFLARE_ACCOUNT_ID`.
> The Pages project is auto-created on the first deploy. GitHub Pages is retired — after the
> repo flips private it turns off by itself (unpublish it manually if flipping later).

The site is served with `dashboard/` as its root, so `index.html` loads `./data.json`,
`./support.js`, and `./vendor/*` relative to itself — no path changes needed (the page is
origin-agnostic; only the Worker's `DATA_URL`/`ALLOWED_ORIGIN`/`PAGE_URL` know the hostname).

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
