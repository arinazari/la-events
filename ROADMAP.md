# ROADMAP — la-events

**What this is:** a private events + dining concierge for Ari and friends — *not* a venture.
The bar is "investor-quality" only in the sense of **polish, depth of curation, and the
"an insider made this for me" feeling**. Optimize for that, not for scale/moat/revenue.
City portability matters because friends live in other cities and Ari travels (Berlin next
week → same magic), not for TAM.

Current phase: **Phases A–D complete (all on `main`).** A (foundation / `run_digest.py` deterministic
core / routine + `SKILL.md` wiring), B (enrichment cache + scene graph, dual `.md`/`.html` renderer,
image caching — *no email*), C (Spotify taste superset + feedback loop), and D (concierge +
night-planner: travel engine, the planner wired, the concierge front door, la-dining's first live
query) are shipped + tested. Next: the **Hosted page** (delivery + on-page actions — see below), the
Gmail "Events" label, and the Spotify go-live (set `SPOTIFY_*`).
Phase 1 done: 10 live fetchers, RA AREA_ID 23, catalog ~700 events, weekend + windowed digests
shipped, dashboard live. Read this file + `CLAUDE.md` + the two `SKILL.md` files before any
non-trivial task.

---

## North star — the product thesis

Not a taste-filtered calendar aggregator (that's table stakes — RA/DICE/TM are catalogs too).
The thing only this has: a **taste-native scene concierge** that understands LA's underground
as a *graph* of artists / labels / promoters / venues, explains every pick like a knowledgeable
friend ("Antal — Rush Hour boss, Dutch digger, deep/disco selector"), and plans the whole night
(dinner → show → afters). The aggregation is plumbing; the **curation + context + the LA-insider
voice** is the product. LLMs are what make being that insider — for every pick, every run —
possible at all; that's the "why now."

---

## Execution architecture — how Claude Code builds + runs this

Organizing principle: **mechanical work in Python (cheap, deterministic, testable); taste /
curation / prose in Claude; fan the parallelizable Claude work out to subagents** so daily runs
stay fast and the main context doesn't bloat. Today Claude does fetch + dedupe + score "by hand"
each run — non-deterministic, slow, token-heavy. The three tiers fix that.

- **Tier 0 — Deterministic core (`scripts/run_digest.py`, no LLM).** Fetch all sources in
  parallel → normalize → dedupe → expire → score against the profile. **One shared, tested
  scoring/dedupe module** (today the ranking logic is duplicated in `SKILL.md` prose *and*
  `build_dashboard.py` — they will drift). Emits a ranked, deduped catalog + a candidate set.
  Burns ~no tokens; safe to run daily.
- **Tier 1 — Enrichment fan-out (`scene-researcher` subagents, top ~30–40 only).** Orchestrator
  spawns several in parallel, each taking a batch and returning per event: type/sub-genre tags,
  **artist notes** (who each name is, why on-taste), a **curator's note** (the opinionated take),
  a cleaned **description**, and for the **top 10 an image**. Subagents because: parallel, and
  **context-isolated** (each burns its own window on web research, hands back only the struct).
  **Cache enrichment on event-id + artist** — artists recur nightly, so the *scene graph
  accumulates* instead of re-researching Antal every day. That cache *is* the growing LA-insider
  knowledge base.
- **Tier 2 — Synthesis (main agent, one creative step).** Takes the enriched, scored, annotated
  set and writes the digest in the single "LA insider" voice. The only place the prose persona lives.

**Agent types** (`.claude/agents/`): `scene-researcher` (Tier 1 enrichment), `source-scout`
(on-demand discovery), `night-planner` (events × dining itinerary). The `la-events` / `la-dining`
SKILLs become orchestrators that call them. **Concierge** = the main conversational interface
(natural-language ask → right mode/agent); the primary way Ari interacts.

### Run cadence

| Layer | Cadence |
|---|---|
| Events digest pipeline (fetch → dedupe → score → enrich → render per weekend → dashboard feed → commit) | **Daily** routine (`routines/daily-digest-prompt.md`, commits to `main`; no email) |
| Dining radar | **Weekly** Wed AM routine (`routines/dining-radar-prompt.md`) |
| Fetchers | within each digest run (daily) |
| `build_dashboard.py` | end of each daily run |
| Spotify taste sync | rides along with the daily run (once built) |
| Discover / `source-scout`, flyer, ad-hoc digest, concierge, night-planner | **on demand** |

### What's hardcoded (Phase A target)

Two tiers. **Config-file hardcodes are fine** (intended, editable): `taste.yaml`, `sources.yaml`
(DICE slug list, Eventbrite `organizers:`), `festivals.yaml`, `recurring.yaml`. **Code hardcodes
are the problem** — scattered city/person knobs that pin us to LA + Ari and cause scoring drift:
- `fetch_ticketmaster.py` → `LA_DMA = "324"`
- `fetch_ra.py` → `DEFAULT_AREA = 23`
- `build_dashboard.py` → `NEAR_SILVERLAKE` set, the `GROOVE/EU/PENALTY/FAR` term lists,
  `CATEGORY_WEIGHT`, score→star thresholds
- "Home = Silver Lake (Hyperion & Del Mar)" baked into prose + near-home logic

Phase A lifts these into a **`profile.yaml`** (`{ dma_id, ra_area_id, home_coords,
near_home_neighborhoods, scoring_weights }`) — one move that both kills the drift and seeds
portability.

---

## Phase 1 — Skill + manual runs  ✅
- [x] Both SKILLs (events: digest/discover/flyer/sources; dining: query/radar/discover/capture)
- [x] Source registry seeded (~65 sources incl. the live-music bar/restaurant lane)
- [x] 10 live fetchers: TM, RA, 19hz, Goldenvoice, Filmbot, Eventbrite, Posh, JSON-LD, DICE,
      Squarespace, ICS/Tockify
- [x] First live digests (RA AREA_ID 23 confirmed; 6/16 windowed + 6/19 weekend shipped)
- [x] Static dashboard live (build feed + PWA-lite + per-event "why?" + ICS export)
- [ ] Gmail "Events" label created; first promoter lists joined (6AM, Dirty Epic first)

## Phase A — Foundation (the unlock — almost everything stands on this)
- [x] **Shared scoring + dedupe module** — `scripts/lib/{scoring,dedupe,config}.py`, both tested
      (`scripts/tests/`); `build_dashboard.py` now imports it (output byte-identical to baseline).
      The `SKILL.md` prose + `run_digest.py` retire onto this module next (A.2).
- [x] **`profile.yaml` config lift** — ids/geo/weights/terms/thresholds moved out of Python into
      `profile.yaml`; the scorer and the TM/RA fetchers read it (fallback to verbatim defaults).
      Fixes drift; seeds city portability. `taste.yaml` stays the human content layer.
- [x] **`scripts/run_digest.py` deterministic core** — fetch-all → normalize → merge+dedupe →
      expire → stamp seen → score → emit candidate set. Pure transforms in `scripts/lib/pipeline.py`
      (tested); thin CLI orchestrator runs the fetchers as subprocesses and degrades gracefully
      (missing key/error/timeout → run report, never blocks). Emits `data/catalog.json` (durable,
      score-free) + `data/candidates.json` (runtime, gitignored; flags top `images` as
      `image_wanted` — the scene-researcher contract). Verified: 697→686 (dupes collapsed), idempotent.
- [x] Catalog hygiene in the core: expires past events, maintains first-/last-seen, window math
      standardized on `America/Los_Angeles` (zoneinfo) — all in `run_digest`/`pipeline`.
- [x] **Wire `run_digest.py` into the daily routine + `SKILL.md`** — done: SKILL Mode 1 is now
      Step 1 (run core) → 2 (layer Gmail/webfetch/editorial) → 3 (`--no-fetch` re-score) → 4 (enrich)
      → 5 (synthesize from the precomputed `candidates.json`). Routine + CLAUDE.md updated to match;
      the by-hand fetch/dedupe/score loop is retired.

## Phase B — Enrichment + beautified digest (the visible quality jump)
- [x] **`scene-researcher` + enrichment cache** — `scripts/lib/enrich.py`: stable `event_key`, the
      accumulating events/artists scene graph (`data/enrichment.json`), miss-detection + merge +
      `update_cache` (artists researched once). Validated by a real agent run over 8 live candidates
      (Bradley Zero→Rhythm Section, Eddie C→Endless Flight, Chris Lake→Black Book, DJ Minx/Casmalia placed).
- [x] **Enriched per-event schema** — `type` + `subgenres`/`label_orbit`/`energy`/`setting`/`sounds_like`,
      `artist_notes`, `curator_note`, `description`, `image` (image_wanted picks). ★ relevance reads the
      precomputed candidate `rating`. All ticket links preserved on the candidate.
- [x] **Two renderers from one enriched dataset** — `scripts/render_digest.py` → canonical `.md`
      (Don't-miss + day-by-day, type tag, ★, linked title, curator note + gloss) **and** a rich
      emailable `.html` (type chips, ★, curator notes, hero images, inline CSS). Tested; can't drift.
- [x] **Image caching** — `scripts/cache_images.py` + `scripts/lib/images.py`: download hero images
      to `data/images/`, set `image.cached`; the renderer prefers the cached copy (`--asset-prefix`
      for hosted serving). Verified live (Goldenvoice posters cached; graceful on blocked CDNs).
- [x] **Routine wiring (no email)** — `routines/daily-digest-prompt.md` now runs core → layer →
      enrich → `cache_images` → `render_digest --from/--to` per weekend (.md + .html) → commit.
      Email intentionally dropped in favor of the **Hosted page** (below). **Phase B complete.**

## Phase C — Spotify taste superset (Spotify is the *music layer*, never the whole profile)
**Built + tested (fixtures); not yet validated against a live Spotify account — needs the
`SPOTIFY_*` secrets set + accounts/api.spotify.com on the network allowlist + Decision 6 below.**
- [x] **Spotify sync** — `scripts/fetch_spotify.py`: OAuth refresh-token flow (store
      `SPOTIFY_REFRESH_TOKEN` like `TM_API_KEY`/`POSH_TOKEN`, exchange each run; `--authorize` mints it
      once). Pulls top (long/medium/short) + followed + recently-played — the endpoints still open to
      new apps post-2024 — and folds them via `lib/affinity.build_affinity` into a weighted, tiered
      `data/spotify_affinity.json` (gitignored). Degrades gracefully (no creds → SKIP, never blocks).
      **Live-validated (2026-06): 190 artists / 39 core from a real account.** Two realities recorded:
      (a) Spotify now returns simplified artist objects (no `genres`/`popularity`) + 403s `/v1/artists`
      for new apps → the Spotify *genre* layer is empty (genres come from feedback); (b) auto-pulled
      artist lists need tighter matching than the hand-curated `artists_tracked` — done (title+lineup,
      whole-token, `ambiguous_names` lineup-gate; 18→8 matches, all true).
- [x] **Merge three layers into one scoring profile** — `lib/scoring.score_event` now takes an
      `affinity` arg (threaded through `pipeline` + `run_digest` + `build_dashboard`); Spotify
      (auto) + `taste.yaml` (human spine) + feedback combine in the one scorer. Spotify *enriches* —
      with no affinity present, scoring is byte-identical to the taste-only path. Mechanism in
      `profile.yaml` `scoring.spotify` + `scoring.feedback`.
- [x] **Close the feedback loop** — `data/feedback.jsonl` (append-only reactions) + `lib/feedback.py`
      aggregate loved/went/skipped/**hide** into the same affinity automatically (no hand-merge):
      "more like X" clears a tier, "never show Y" forces a `hidden` down-rank. Implicit-signal *capture*
      (clicked-ticket / added-calendar) — the schema's there, but emitting them depends on the Phase B
      HTML-email / dashboard delivery surfaces, so wiring the emitters rides with B/D.
- [ ] **Go-live (needs Ari)**: create the Spotify app, mint the refresh token (`--authorize`), set the
      three secrets, allowlist the Spotify domains; then confirm Decision 6 (which signals to sync) and
      eyeball the first run's `Spotify …` reasons to tune `scoring.spotify` weights.

## Phase D — Concierge + night-planner (the experience / hero feature)  ✅ (branch claude/confident-rubin-7rb7ox)
- [x] **Conversational concierge as primary interface** — `.claude/skills/concierge/SKILL.md`: the
      NL front door that reads taste, routes an open-ended/cross-domain ask ("free Friday, chill,
      walkable, no techno") to the right mode/agent (digest / dining query / night-planner / capture /
      discover), and answers in one LA-insider voice. Surface = claude.ai / this conversation (resolved
      delivery decision); dedicated text number still later.
- [x] **`night-planner` agent fusing la-events × la-dining** — `.claude/agents/night-planner.md` made
      operational (has `Bash`): rescore via `run_digest.py --no-fetch` → anchor; dinner from
      `dining.json` (affordability-aware) → show (taste-ranked) → afters; sequenced with **real travel
      times** via `scripts/travel.py`; reservation reality on the shortlist; itinerary w/ booking links.
- [x] **Travel/timing engine** — `scripts/lib/geo.py` + `scripts/travel.py` (tested): offline rough LA
      drive/walk times from an LA gazetteer (58 neighborhoods + 63 venues) + a congestion model,
      overridable in `profile.yaml` (`home.coords`, `geo.travel`). Resolves neighborhoods, event
      venues, AND dining restaurants (augmented from `dining.json`).
- [x] **Advance la-dining just enough to feed the planner** — first live **query** run end-to-end
      (harvest → merge → rank): see dining section. Explicit food-taste profile seeded (affordability
      policy + signal weights); `restaurants_loved` pending Ari's list. Not the full dining build-out.

## On-demand — `source-scout` discovery agent (your call, never scheduled)
Runs explicit strategies, returns a proposal table (approve → append to `sources.yaml`):
- [ ] **Gap-mine** the catalog — venues/promoters in event data with no registry entry.
- [ ] **Linktree / link-in-bio crawl** — given an IG handle or its Linktree URL, harvest the
      *public* ticketing/calendar links behind it (DICE/RA/EB/venue). The legit way into the
      Instagram gap **without scraping IG** — the standout strategy.
- [ ] **Venue-site probe** — auto-detect the best ingestion method (JSON-LD? ICS? Squarespace
      `?format=json-pretty`? DICE slug? See Tickets? Filmbot/Nightjar?) and return fetcher + config.
- [ ] **Directory sweep** — RA area pages, DICE city index, 19hz organizer column, EB organizer
      pages → unregistered venues/promoters.
- [ ] Subsumes the old "source health check" idea: a scout pass can also ping `active` sources and
      flag broken ones before a digest silently loses coverage.

## Delivery — Hosted page (the new primary surface; supersedes email)
A **hosted, bookmarkable page** Ari opens to see the catalog, plan a night, and tune taste.
- **Static core, wired:** the committed weekend `.html` + `dashboard/data.json` deploy to GitHub
  Pages (`.github/workflows/deploy-dashboard.yml`). `render_digest --asset-prefix` points cached
  images at the served base, so the digests are self-contained.
- [x] **Interactive home shipped (static + Claude Code hand-off)** — the dashboard is now a 3-view
  app (`dashboard/`): **Explore** (search/filter/present every event — reworked to the real catalog
  schema + enrichment + save-for-plan), **Plan** (a chatbox: a local no-LLM query engine over the
  loaded catalog *plus* an agent hand-off that composes a concierge/night-planner prompt), and
  **Settings** (edit taste/scoring/sources, preview a change-set, hand off to apply+commit; pipeline
  actions for refresh/discover). `build_dashboard.py` now emits an enrichment-folded `events[]` + a
  `config` snapshot for Settings.
- **Decision resolved — how page actions trigger agent runs:** **static-first + claude.ai/code
  hand-off** (Ari's call, 2026-06). The page never holds a key or writes YAML; it composes the exact
  prompt and the existing agent commits results back (routine/Pages redeploy surfaces them). Isolated
  to one seam (`js/handoff.js`, `BACKEND_URL`) so a backend can drop in later with no rewrite.
- [x] **LLM concierge backend wired (2026-06-19)** — the chat now has a **Concierge (LLM)** mode
  (default) ⇄ **Fast filter** (the no-LLM heuristic) toggle. Concierge mode POSTs to `BACKEND_URL`;
  a reference Cloudflare Worker (`backend/`) holds `ANTHROPIC_API_KEY`, grounds on the live
  `data.json` (events + dining + taste), and answers/recommends/plans. The page falls back to Fast
  filter if the backend is unset/down, so nothing breaks. **Needs Ari to deploy it** (wrangler +
  key) and set the URL/token via the chat's "connect" affordance — see `backend/README.md`.
- **Remaining (the upgrade, not blocking):** stand up that backend + choose **auth** (shared token
  vs Cloudflare Access — "private to Ari + friends"); optional streaming + auto-commit of plans.
  Public/unlisted Pages + Fast-filter fallback is fine until then (catalog = public events).
- **Subsumes the tabled dashboard** — this *is* the explorer, evolved into the interactive home.
- [x] **Front end swapped to the design-tool UI (2026-06-18, branch `claude/exciting-feynman-v6vqo6`)** —
  the hand-written 3-view app was replaced by Ari's uploaded design (a single `dashboard/index.html` +
  its `support.js` "dc-runtime"). **Backend unchanged**: `build_dashboard.py` + `lib/scoring.py` still
  produce `dashboard/data.json` and the page stays a pure viewer. The design's two claude.ai-only
  features were rewired to the repo's patterns — chat ("ASK THE DIGEST") → local no-LLM intent parser
  (`localSpec`), Discover → copy-to-Claude-Code hand-off. React/ReactDOM/`@babel/standalone` vendored
  locally (off unpkg); PWA + deploy workflow carried over (deploy stages `digests/latest.md`).

### Dashboard follow-ups (TODO — from the front-end swap)
- [ ] **Pre-transpile build step** — the new UI is a React app transpiled *in the browser* by
  `@babel/standalone` (~3 MB vendored). Add a build step that compiles `index.html` ahead of time and
  ships plain JS, dropping Babel + the first-paint transpile cost from the client.
- [ ] **Per-event ICS export** — re-port the one-click add-to-calendar (was `dashboard/js/ics.js`;
  regressed in the swap).
- [ ] **Save / bookmark events** — let Ari star events to a personal shortlist (localStorage; the seed
  for "plan around these"). Was `save-for-plan` in the prior front end; not in the new design yet.
- [ ] **Like → learn taste** — per-event 👍/👎 (or "more like this" / "never show") that feeds the
  existing feedback loop (`data/feedback.jsonl` → `lib/feedback.py` → affinity, Phase C). Closes the
  implicit-signal-capture gap noted in Phase C (emitting reactions waited on a dashboard surface); on
  static Pages it rides the hand-off seam — compose the `feedback.jsonl` append for the agent to commit.

## Tabled — deliberately deferred (Ari's call)
- → Explorer / dashboard page is **no longer tabled** — it evolves into the **Hosted page** (above).
- [ ] Flyer-forwarding bot + Twilio SMS/MMS intake (`sms-ingestion.md`). Capture-by-hand still works.
- [ ] On-sale sniper / price tracking across ticket links (DICE vs TM fees). Nice-to-have.
- [ ] SQLite instead of `catalog.json` if volume ever demands it.

---

## Sources — reference

### Brought online (2026-06-16)
- Live (structured fetchers): Ticketmaster, RA, 19hz, Goldenvoice (AEG blob feed), Vidiots
  (Filmbot API), Eventbrite (curated organizers + auto-harvest), Posh (authed tRPC explore),
  DICE (venue pages), Squarespace (`?format=json-pretty`), ICS/Tockify. Catalog ~700 events.
- Live-music bar/restaurant/listening lane (25+ venues): structured where possible (DICE:
  Zebulon/Gold Diggers/The Mint/Townhouse/The Virgil/2220/Permanent Records/Grand Star;
  Squarespace: Junior High/Vibrato/The Smell; ICS: Maui Sugar Mill). Heterogeneous own-site rooms
  (McCabe's, Dresden, Harvelle's, Sam First, Alva's, Venice West…) → `method: webfetch`. IG-only
  (1642, Gold Line, General Lee's) → `method: manual`.
- Posh auth: `POSH_TOKEN` = session JWT, ~30-day life; re-capture on 401. Durable refresh = future.

### Open source work (route through `source-scout` / Discover)
**Fetcher field-extraction tightening** (from the live smoke test — `run_digest` wiring + normalize
were validated; these are per-fetcher *under-extraction*, not normalize bugs):
- [x] `normalize_record` now reads `afterhours_flag` (was dropped → RA afterhours 0%; now ~36%);
      `fetch_ra.py` now emits the `venue.area` neighborhood it already queried (was discarded).
- [x] `fetch_ticketmaster.py`: extract `attractions` → lineup (0% → 91%). Price: the TM Discovery
      API returns **0% `priceRanges`** for LA (verified) — unavailable at the source, not a bug;
      `normalize_record` now synthesizes `$lo-hi` / "free" from a range whenever one *is* present.
- [note] `fetch_dice.py`: DICE's venue JSON-LD now ships `offers: []` and no `performer` field
      (artists are in the event title) — price unrecoverable, lineup best parsed at enrichment. Not a bug.
- [ ] DICE/19hz lineup-from-title: parse the comma-separated title into a lineup at enrichment
      (scene-researcher), where judgment can tell an artist list from a festival/residency name.
- [ ] Venue→neighborhood map: RA area is city-level ("Los Angeles"); 19hz has none — derive a finer
      neighborhood from the venue for the near-home boost + display.
- [ ] Wire `method: webfetch` venues into the digest run (read rendered calendars at digest time)
- [ ] Bar Franca / Somerville: find the right Squarespace events collection slug (json-pretty → 0)
- [ ] Silverlake Lounge: DICE slug valid but 0 upcoming — re-check (many indies book via See Tickets)
- [ ] See Tickets US (Troubadour/Largo/Catalina): MusicEvent JSON-LD behind a headless render
- [ ] Zebulon JS-render gap (e.g. Mama's Gun midweek) — needs a real fetcher
- [ ] Rep cinema holdouts: New Bev (Veezi token), American Cinematheque (no public API)
- [ ] Eastside comedy (Largo / Dynasty Typewriter / UCB) via per-site APIs (Filmbot playbook)
- [ ] Eventbrite — retry open browse if the AWS WAF CAPTCHA lifts / via headless
- [ ] Posh — durable token refresh (avoid 30-day manual re-capture)

---

## Dining layer (la-dining sibling) — NOT tabled; feeds the night-planner
- [x] SKILL (query/radar/discover/capture), `dining-sources.yaml`, `dining-taste.yaml`,
      `data/dining.json` (15 seed records), weekly radar routine
- [x] Harvest fetch test (6/16): Infatuation + Resy blog fetch clean; Eater/LAT/Michelin/OpenTable
      bot-block → `fetch: search_only` / `blocked`, harvested via domain-scoped web search
- [x] **First live query run end-to-end** (rank + write a record) — the bit the night-planner needs.
      DONE (Phase D, 6/17): harvested Infatuation Eastside Hit List + Silver Lake, Resy blog, Michelin
      Bib Gourmand → +14 restaurants to `data/dining.json` (15→29), home-turf-heavy + Bib value; all
      new neighborhoods resolve in the travel engine. Eater LA + LA Times still blocked in-env (gap noted).
- [ ] First weekly radar (validates format/length/tone — Decision D1)
- [ ] Reservation availability: booking widgets don't render via fetch — headless vs. "set a Notify"
- [ ] Fold reservation hot-lists into a learned food-taste profile once reactions accumulate

---

## Decision points — Ari's input needed
1. **Visual digest home** (Phase B) — ✅ resolved + revised: text-only `.md` canonical + a rich `.html`.
   Email is **dropped**; the `.html` now feeds the **Hosted page** (above) instead of an inbox.
2. **Delivery channels** (Phase B/D) — ✅ built: committed `.md`/`.html` → a **hosted bookmarkable page**
   (`dashboard/`, not email) with an on-page concierge (Plan view) + Settings + refresh/discover actions,
   via static + claude.ai/code hand-off. Open upgrade: a `BACKEND_URL` service for in-page chat + auth.
   Dedicated text number still deferred.
3. **Digest cadence** (resolved): **daily** weekend-set, ~4 months out. Revisit if commits get noisy.
4. **Taste weights** (ongoing): `taste.yaml` is yours — edit directly, or react and let the loop fold in.
5. **Dedupe spot checks** (Phase A): eyeball merged records for false merges while tuning the threshold.
6. **Spotify scope** (Phase C): the sync is built on top-artists (long/medium/short) + followed +
   recently-played (genres ride along on the artist objects). Confirm that's the right set once it
   runs live, and how hard the music layer should weigh vs. the `taste.yaml` spine (`scoring.spotify`
   tier points — currently a deliberately modest nudge: core +2, capped +4/event).
7. **Discover/source-scout approvals** (on demand): the candidate-source table — approve/reject.

### Dining-layer decisions
- **D1. Radar cadence + format**: weekly (Wed AM) vs. on-demand; does the format/length/tone land?
- **D2. Food-taste seeding**: ✅ resolved (Phase D) → **explicit profile**. `dining-taste.yaml` now
  carries an affordability policy + raised Michelin-Bib/Resy/food-blog signal weights; `restaurants_loved`
  + cuisines/dietary/price still need Ari's list (marked TODO in the file).
- **D3. Reservation depth**: "hot-list + availability check on shortlist" vs. deeper Resy/OpenTable/Tock.
- **D4. Cross-layer planner** (Phase D): ✅ built — `night-planner` combines la-dining + la-events into
  a travel-timed night itinerary (dinner → show → afters). This is why dining isn't tabled.
</content>
</invoke>
