# CLAUDE.md — la-events

LA events aggregator + personalized digest for Ari. Built collaboratively in claude.ai
(June 2026); this repo is the source of truth going forward. Read ROADMAP.md for current
phase and open decisions before starting any non-trivial task.

## What this project does

1. **Aggregates** LA events from structured pipelines (Ticketmaster Discovery API, RA
   GraphQL, DICE, Gmail "Events" label), JSON-LD/scrape venue sources, editorial roundups
   (ranking signals, NOT catalog rows), and manual captures — pasted flyers and promoter
   SMS/MMS blasts (see `sms-ingestion.md`).
2. **Dedupes** into `data/catalog.json` (one record per real-world event, all ticket
   links preserved).
3. **Ranks** with a deterministic score against `taste.yaml`, refined by a thin **`event-editor`**
   LLM verdict layer (per-event tier + optional lane + small bounded `adjust`, cached per profile in
   `data/verdicts/`), then emits a consolidated conversational digest to `digests/`.
4. **Discovers** new sources over time (propose → human approves → `sources.yaml`).
5. **Converses + plans** — a natural-language **concierge** (`.claude/skills/concierge/SKILL.md`)
   is the primary interface (route an open-ended ask to the right mode/agent), and a
   **`night-planner`** agent fuses events × dining into a sequenced, travel-timed dinner → show →
   afters itinerary. This is the experience layer (ROADMAP Phase D).

The full operating spec lives in `.claude/skills/la-events/SKILL.md` — read it before
working on digest/discover/flyer behavior. It is the contract; this file is orientation.

## How sources are fetched

The structured path is orchestrated by `scripts/run_digest.py` (fetch → dedupe → expire → score →
`data/catalog.json` + `data/candidates.json`); the other two paths Claude layers in at digest time
(SKILL Step 2). Three ingestion paths — each source's `method` in `sources.yaml` says which:
- **Structured fetchers** (`scripts/fetch_*.py`) — APIs / JSON feeds / parseable pages: TM, RA,
  19hz, Goldenvoice, Filmbot, Eventbrite, Posh, **DICE** (dice.fm/venue/<slug> — MusicEvent JSON-LD
  under a Place's `event` key, real Chrome UA required), **Squarespace** (`?format=json-pretty`),
  **ICS/Tockify**. They emit normalized event JSON; the run merges + dedupes into `data/catalog.json`.
- **`webfetch`-at-digest** — venues with no JSON-LD/feed and heterogeneous CMSs (McCabe's, The
  Dresden, Harvelle's, Sam First, Alva's, …) and editorial roundups: read the rendered page via the
  WebFetch tool during the digest run rather than maintaining brittle per-CMS scrapers.
- **`manual`** — IG-only / flyer / SMS (1642, Gold Line, General Lee's, promoter blasts). Never
  scrape IG; capture via flyer mode or the Gmail "Events" label / Twilio inbox.

## Dining layer (sibling skill)

A parallel **la-dining** layer recommends *where to eat* — restaurants, eateries, popups,
and food trucks — by day/occasion/neighborhood, and tracks what's trending. It mirrors the
events conventions but is its own skill with its own registry/taste/catalog (restaurants are
persistent entities, not dated rows; popups/trucks are the event-shaped exception). Sources:
Resy + OpenTable (hot-lists + availability) and Michelin / The Infatuation / Eater / LA Times
(editorial signals) + food blogs (L.A. TACO, LA Mag, Thrillist — Phase D). Spec:
`.claude/skills/la-dining/SKILL.md`. Modes: query (primary), radar (weekly digest), discover,
capture. The query also **feeds the `night-planner`** with restaurant picks. Food-taste is now an
explicit profile (`dining-taste.yaml`): an affordability policy (Michelin/Bib value over $$$$
unless special) + `restaurants_loved`; ranking honors it.

## Layout

```
.claude/skills/la-events/SKILL.md   # events operating spec (digest/discover/flyer/sources modes)
.claude/skills/la-dining/SKILL.md   # dining operating spec (query/radar/discover/capture)
.claude/skills/concierge/SKILL.md   # concierge — NL front door routing to the modes/agents (primary interface)
.claude/agents/                     # worker agents: event-editor (ranking verdicts), scene-researcher (full enrichment,
                                    #   top-100 head), blurb-writer (cheap one-line descriptions for the band below the head),
                                    #   night-planner (events×dining itinerary), source-scout (discovery)
sources.yaml                        # events source registry — schema in file header
dining-sources.yaml                 # dining source registry — schema in file header
taste.yaml                          # events ranking config — user-editable, re-read each run
profiles.yaml                       # per-person taste registry for the dashboard profile-switcher (schema in header)
profiles/<name>/taste.yaml          # a friend's hand-authored taste profile (build_profiles.py emits their feed)
dining-taste.yaml                   # food-taste config — minimal, learns from reactions
festivals.yaml                      # "on the radar" curated festivals/big-shows + live lookups
radar-candidates.md                 # build_radar.py output: reviewable far-out candidates → curate into festivals.yaml
recurring.yaml                      # predictable recurring markets/fleas/farmers markets
sms-ingestion.md                    # Twilio SMS/MMS → catalog spec (manual-capture automation)
profile.yaml                        # place/person config (ids, geo, scoring weights/terms) — city-portable knob
scripts/run_digest.py               # deterministic core: fetch→dedupe→expire→tag→score→catalog+candidates+editor_pool.json
scripts/lib/                        # shared modules: scoring, dedupe, pipeline, enrich, images, config,
                                    #   affinity (Spotify), feedback (reactions→affinity), geo (travel),
                                    #   tagging (deterministic multi-axis tags: type/genre/setting/vibe/region),
                                    #   editor (event-editor verdict store + judging pool + Spotify affinity hints +
                                    #     a read-only taste-neutral `scene` block folded from the shared enrichment),
                                    #   assemble (the digest slate: lanes + elastic fill/cliff/diversity-floor) — tested
scripts/merge_verdicts.py           # fold event-editor results JSON → per-profile data/verdicts/<hash>.json
scripts/build_radar.py              # deterministic "on the radar" set (festival/big-venue/tracked/editorial) → data/radar.json
scripts/render_digest.py            # scored pool + verdicts → digest slate (Markdown). `--consolidated` = one daily doc
                                    #   (next 2 wks + weekends ahead + radar); `--from/--to` = per-weekend look-ahead
scripts/travel.py                   # night-planner travel CLI: rough LA drive/walk times (lib/geo.py + dining.json)
scripts/make_ics.py                 # turn a night-planner itinerary into a calendar .ics (lib/ics.py)
scripts/log_feedback.py             # concierge: append a reaction to data/feedback.jsonl (the learned loop)
scripts/fetch_*.py                  # 11 source fetchers (run BY run_digest, or in Step-2 layering):
                                    #   ticketmaster (TM_API_KEY), ra, 19hz, goldenvoice, filmbot,
                                    #   eventbrite, posh (POSH_TOKEN), dice, squarespace, ics, jsonld
scripts/fetch_spotify.py            # Phase C: Spotify sync (SPOTIFY_* creds) → data/spotify_affinity.json
scripts/sync_profiles_spotify.py    # per-profile Spotify: pull friends' connected accounts (via the concierge
                                    #   Worker) → data/spotify/<hash>.json (gitignored); routine + spotify-sync CI
scripts/build_dashboard.py          # builds dashboard/data.json from catalog + taste.yaml + profile.yaml
                                    #   (--profile-hash loads that profile's own Spotify/feedback music layer)
scripts/build_profiles.py           # per-profile dashboard feeds (data.<hash>.json) — reuses build_dashboard's scorer
data/catalog.json                   # deduped events store (committed = the state)
data/candidates.json                # scored, ranked top-N (full-enrichment head) (runtime; gitignored)
data/blurb_pool.json                # cheap-tier (blurb-writer) candidate band below the head (runtime; gitignored)
data/editor_pool*.json              # event-editor judging pool, per profile (runtime; gitignored)
data/radar.json                     # "on the radar" set for the consolidated digest (runtime; gitignored)
data/verdicts/<hash>.json           # event-editor verdicts, per profile (committed; only the delta is judged each run)
data/enrichment.json                # scene-graph cache: per-event enrichment (full + blurb tiers) + artist notes (committed; grows each run)
data/spotify_affinity.json          # Spotify music-affinity artifact (runtime; gitignored)
data/feedback.jsonl                 # append-only reaction log (committed); folds into scoring each run
data/inbox.jsonl                    # SMS receiver appends here; digest consumes (runtime-created)
data/dining.json                    # dining catalog: restaurants + popups/trucks
digests/latest.md                   # PRIMARY consolidated daily digest (next 2 wks + weekends ahead + on the radar)
digests/<hash>/latest.md            # per-profile personalized digest (the dashboard profile popup reads this)
digests/weekends/YYYY-MM-DD.md      # per-weekend look-ahead digests, day-grouped (~4 mo out) + index.md
digests/YYYY-MM-DD.md               # ad-hoc windowed events digests
digests/dining-YYYY-MM-DD.md        # dining radar outputs
routines/daily-digest-prompt.md     # scheduled events-digest routine prompt
routines/dining-radar-prompt.md     # scheduled weekly dining-radar routine prompt
dashboard/                          # static PWA-lite catalog view; feed via scripts/build_dashboard.py
docs/PIPELINE.md                    # orchestration map: when each component runs (auto vs on-demand) +
                                    #   the content_version "clock" + cost gates (read for freshness/cost work)
```

## Hard requirements & conventions

- **Stateless cloud runs**: all state lives in this repo. A run reads catalog + registry,
  fetches, merges, writes back, commits. Never assume anything outside the repo persists.
- **Secrets**: env vars only — `TM_API_KEY` (Ticketmaster), `POSH_TOKEN` (Posh session JWT,
  ~30-day life; re-capture when it 401s), the **Spotify** trio `SPOTIFY_CLIENT_ID` /
  `SPOTIFY_CLIENT_SECRET` / `SPOTIFY_REFRESH_TOKEN` (Phase C music layer — the refresh token is
  long-lived; mint it once via `fetch_spotify.py --authorize`), and the Twilio auth token if the
  SMS receiver is live (digest needs it to fetch MMS media). Never commit keys.
- **Never scrape Instagram.** IG-only sources are `method: manual` (flyer-capture flow).
- **Degrade gracefully**: one dead source never blocks a digest; list failures in the
  digest footer and mark repeat offenders `flaky` in sources.yaml.
- **Editorial sources are signals, not catalogs** — they boost rank; only add their
  events to the catalog when no structured source has them.
- **Dedupe key**: fuzzy (venue + date + title/headliner). Merge keeps all ticket links
  and the richest description.
- **Dates in output**: `Day M/D`, no leading zeros (Ari's standing convention).
- **Politeness**: respect rate limits (TM ≤5 req/s; RA small pages, real UA, ≤10 pages).
- **Digest tone**: conversational, opinionated, brief. Top picks first with a one-line
  *why*. Not an exhaustive dump — taste.yaml decides what's worth surfacing.
- Source registry changes from Discover mode are **proposals** — present them, get
  approval, then commit. Exception: marking sources flaky/dead is automatic.
- **Eventbrite = curated organizers** (open browse is WAF-CAPTCHA'd, search API retired).
  Coverage lives in the Eventbrite source's `organizers:` list in sources.yaml and must keep
  growing: `fetch_eventbrite.py --harvest <event_url>` when a blast/flyer carries an EB link,
  and `--scan-catalog` each Discover pass. Harvest adds only the event's *own* organizer (from
  JSON-LD), never recommended/related ones (auto-adding an event's organizer is allowed; it's a
  precise, high-confidence signal, not a Discover-style proposal).

## Working style

Ari is technical, direct, and allergic to sycophancy. Give honest tradeoffs, don't pad.
Iterate in small commits with clear messages. When a structural/architectural question
comes up, flag it for discussion rather than silently making a big design decision —
he wants input at the decision points listed in ROADMAP.md.

## Cloud session notes

- Network: this project needs outbound access to app.ticketmaster.com, ra.co, dice.fm,
  plus the domains in sources.yaml. The Phase C Spotify sync also needs accounts.spotify.com
  (token exchange) + api.spotify.com (top/followed/recent). Configure the environment
  accordingly (limited networking blocks everything by default).
- Gmail access comes via the Gmail connector when available; the "Events" label holds
  promoter blasts. If the connector isn't available in a session, skip that source and
  note it in the digest footer.
- Daily digest runs as a scheduled Routine using routines/daily-digest-prompt.md: it builds the
  consolidated daily digest (`digests/latest.md` — next 2 weeks + weekends ahead + on the
  radar) plus a rolling set of per-weekend look-ahead digests (`digests/weekends/`, ~4 months out),
  and commits them + the updated catalog + per-profile verdicts (`data/verdicts/`) to `main` (the
  Pages workflow then redeploys the dashboard).
