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
calendar-core.js      calendar-subscription core (filter + iCalendar builder) — shared VERBATIM
                      with the Worker's GET /calendar.ics (backend/ imports this file), so the
                      modal's preview always matches what a subscribed calendar receives. Serves
                      both the taste-ranked "Top picks" calendar and the starred "Saved" one (keys=)
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
profile.yaml        │      folds in enrichment, emits config + facets,
sources.yaml        │      lifts front_page.take from the digest's take slot —
digests/latest.md ──┘      why the workflows render the digest BEFORE the feed)
```

`index.html` fetches `./data.json` at startup, normalizes the real catalog schema
(`date`+`start`, `price` string, `links[]`, `score`/`rating`/`reasons`, `enrichment`) into its
table, and renders. If `data.json` is unreachable (e.g. opened over `file://`) it falls back
to its bundled sample data, so it never renders blank.

## Views: Front (default) ⇄ Explore

The page opens on the **Front page** — an editorial home rendered from the feed's
`front_page` block (built server-side by `build_dashboard.build_front_page` with the SAME
`rank_key` that orders the table's final rank — the page never re-ranks):

- A **time lens** (*tonight · this weekend · next 2 weeks · plan ahead*) that re-scopes
  everything below. The feed ships each lens's hero list plus rank-ordered shelf key-lists;
  the client only date-windows and slices — selection, never re-sorting.
- **Don't miss** — the hero row, selected server-side by the ONE shared top-picks policy
  (`lib/assemble.top_picks` — the same helper, order, and lane/family diversity caps as the
  flagship digest's "Don't miss" shelf), so it can't be five club nights and can't disagree
  with the digest on policy.
  Shelf cards badge only the editor's rare **must-see** flag: the front page IS the top of
  the ranking, so "great" is the baseline there and goes unbadged (a badge on every card is
  no badge at all) — and the hero row badges nothing, since its own label already says it.
  Full tiers remain visible in Explore's rank tooltip. Card copy follows the same rule:
  the curated why (curator note / editor's line), else the factual blurb — never the
  scorer's "+1 …" reasons, which live in Explore and the detail modal's WHY IT'S RANKED.
- **Shelves per lane** — warehouse & underground / afters / day parties / big rooms / live
  music / film / comedy & stage / elsewhere, plus fixed **Around town** and **On the radar**
  shelves when the runtime sets exist. Card click → a detail modal (what/why/lineup/links/
  add-to-calendar); *see all →* jumps into Explore pre-filtered via the same `filtered`
  id-list mechanism the chat uses.

**Explore** is the original table (search, facets, date range, rank/score sort), one click
away in the header switch; the choice persists per device (`la-view` in localStorage). A feed
without `front_page` (e.g. the bundled sample) opens straight in Explore and hides the switch.
Events carry a stable `key` (server `event_key`) — the front-page join id, and the anchor for
future feedback reactions.

## The chat: Concierge (LLM) ⇄ Fast filter

The chat has two modes, toggled in its header (default **Concierge**):

- **Concierge (LLM)** — a real conversational concierge that **answers questions**, recommends,
  and plans a night. Because the page is static (no API key in the browser), it POSTs to a
  `BACKEND_URL` — a small Cloudflare Worker that holds the Anthropic key and grounds the model on
  the live feed. **Deploy it + connect it** (see `backend/README.md`; the URL is the `BACKEND_URL`
  constant in `index.html`, and "connect" in the chat header sets the token). Until then,
  Concierge mode transparently falls back to ↓.
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

**The welcome wraps the take** — the thread opens on ONE concierge message: the greeting, then
the day's take ("For Fri 7/17: …" — the voice pass's ONE-sentence teaser, carried structurally
as `front_page.take = {text, date}`; the date shown is the digest's own date, so it visibly
reads as today's take when it is and honestly dated when stale), then the how-to with its
tap-to-fill examples. Feeds without a structural take fall back to the digest-lede heuristic
(`digestLede()`), clipped to one sentence. The how-to renders full-size until this device
sends its first message, then tucks behind a *see what I can do ▸* toggle (`chatGuideOpen` /
`la-chat-used`). The welcome is ALL client-side chrome: it *looks* like the LLM's first
message but none of it is ever sent — not as history and not as any side field (the old
`opener` is retired by design; the model grounds on the feed data alone). A profile with no
digest yet just gets no take line.

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
shortly"). Requires the backend deployed with a `GITHUB_TOKEN` — see `backend/README.md`.

**Seeing your edits land:** the profile popup's "View taste & profile" opens a read-only modal with a
tab per file (taste + profile). Each shows a **diff** of how the concierge adjusted it and a single
**reflected/pending** badge — whether that change is live in your ranking & digest yet, or still
pending (with an *Update now →* button). It's all baked into the feed by `build_profiles.py` from git
(`profile.self_edit`), so it works on the static page with no backend; a friend's edit reads *pending*
until they hit Update (or the nightly run) regenerates their digest against the new taste.

**This is obfuscation, not security:** the username is a public, guessable-if-known bearer key, and
each feed file is publicly fetchable. Taste *writes* are low-stakes too (every edit is a revertible
commit) — the backend's `CONCIERGE_TOKEN` guards API spend + commit-spam, not the data. Pick
non-obvious usernames. Still deferred (see ROADMAP): per-profile Spotify affinity.

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
Worker, set the Anthropic key, point `BACKEND_URL` at it, connect the token. Still open as
future work: streaming
responses, auto-committing generated plans back to the repo, and real auth (Cloudflare Access).
Public/unlisted Pages + the Fast-filter fallback is fine until then (the catalog is public LA
events).
