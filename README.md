# la-events

Personal Los Angeles events aggregator + taste-ranked, enriched digest — built and run as
Claude Code sessions / scheduled Routines.

**The model:** everything is state in this repo. Any run — whether you trigger it in a
session or it runs on a schedule — does the same thing: read the repo (catalog, taste,
sources, enrichment) → fetch → dedupe → score → enrich → render → **commit back**. Nothing
lives outside git.

## What it does

- **Aggregates** from structured fetchers (Ticketmaster, Resident Advisor, 19hz, Goldenvoice,
  Vidiots, Posh, Eventbrite, DICE), plus editorial roundups (ranking signals only), the Gmail
  "Events" label, and manual captures (flyers / promoter blasts).
- **Dedupes** into `data/catalog.json` — one record per real event, all ticket links kept.
- **Scores** each event against `taste.yaml` (your preferences) + `profile.yaml` (place/scoring
  mechanics) — one shared module, so the digest and dashboard never disagree.
- **Enriches** the top picks via the `scene-researcher` agent: sub-genre tags, who each artist is
  and why they fit, a curator's note, a clean description, and a hero image. Artist research is
  cached in `data/enrichment.json` and reused — the "scene graph" compounds each run.
- **Renders** a day-by-day digest (`scripts/render_digest.py`): a canonical `.md` and a rich
  `.html` (type tags, ★ relevance, inline ⭐ picks, cached images).
- **Discovers** new sources on demand (`source-scout`): propose → you approve → `sources.yaml`.

## The pipeline

```
run_digest.py        fetch → normalize → dedupe → expire → score   → data/catalog.json + data/candidates.json
scene-researcher ×N  enrich the top candidates (parallel)          → data/enrichment.json  (scene graph, grows)
cache_images.py      download hero images                           → data/images/
render_digest.py     enriched candidates → the digest              → .md + .html
```

## Getting a digest — two ways, same pipeline

- **Interactively:** open a Claude Code session on this repo and ask `/la-events` (or "what's on
  this weekend"). It runs the pipeline and writes the files. `/la-events discover | flyer | sources`
  for the other modes.
- **Scheduled routine:** `routines/daily-digest-prompt.md` runs the pipeline **daily** and maintains
  a rolling set of **per-weekend** digests (`digests/weekends/YYYY-MM-DD.{md,html}` + `index.md`),
  ~4 months out. You set this up once in **claude.ai → Routines** (schedule, secrets, network); it
  commits to **`main`**, which auto-republishes the dashboard (see below).

The `.html` is the visual version (images, color-coded tags, picks); the `.md` is the canonical,
diffable text. **No email** — the `.html` is the artifact the planned hosted page will serve.

## What's live now vs. next

- **Live:** the deterministic core, the worker agents, the enrichment scene-graph, the day-grouped
  dual renderer, image caching, and the static **dashboard** (`dashboard/`) — a filterable catalog
  view that **auto-deploys to GitHub Pages** on any push to `main` touching `dashboard/**`.
- **Next:** a **taste layer from Spotify** + a reaction-driven feedback loop (taste learns over time),
  and an **interactive hosted page** — the bookmarkable daily digest *with on-page actions* (trigger a
  source re-scan, ask the LLM for an ad-hoc digest). It supersedes the basic dashboard. See `ROADMAP.md`.

## Setup

- Secrets (env vars, never committed): `TM_API_KEY` (free, developer.ticketmaster.com) and
  `POSH_TOKEN` (~30-day Posh session JWT).
- Allow network egress to app.ticketmaster.com, ra.co, dice.fm + the domains in `sources.yaml`.
- Schedule the routine (`routines/daily-digest-prompt.md`) → commits to `main` → the Pages workflow
  redeploys the dashboard.
- Optional / future: Gmail "Events" label (promoter blasts), Twilio SMS receiver (`sms-ingestion.md`).

## Tuning it

- **`taste.yaml`** — what you like (genres, tracked artists, loved venues, the pinned series, the
  comedy exception). Edit directly anytime; re-read every run.
- **`profile.yaml`** — place + scoring mechanics (DMA/area ids, home geo, weights, term matchers,
  thresholds). The city-portable knob — swap it to point the engine at another city.

## Docs

- **CLAUDE.md** — orientation + conventions (start here)
- `.claude/skills/la-events/SKILL.md` — operating spec (the contract); `la-dining/` is the food sibling
- **ROADMAP.md** — current phase (A + B complete), the hosted-page direction, open decisions
- `scripts/lib/` + `scripts/tests/` — the tested core (scoring, dedupe, pipeline, enrich, images)
