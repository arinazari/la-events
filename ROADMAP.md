# ROADMAP — la-events

**What this is:** a private events + dining concierge for Ari and friends — *not* a venture.
The bar is "investor-quality" only in the sense of **polish, depth of curation, and the
"an insider made this for me" feeling**. Optimize for that, not for scale/moat/revenue.
City portability matters because friends live in other cities and Ari travels (Berlin next
week → same magic), not for TAM.

Current phase: **Phase A complete; B / C / D in parallel branches.** A.1 (shared scoring/dedupe lib
+ `profile.yaml` lift), A.2 (`run_digest.py` deterministic core), and the routine/`SKILL.md` wiring
are shipped + tested — the by-hand fetch/dedupe/score loop is retired. The remaining phases are
parallel siblings off Phase A: **B** (`scene-researcher` enrichment + beautified `.md`/HTML digest),
**C** (Spotify taste superset + feedback loop), **D** (concierge + night-planner — **shipped on
branch `claude/confident-rubin-7rb7ox`**: travel engine, the planner wired, the concierge front
door, and la-dining's first live query). Each merges to main independently.
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
| Events digest pipeline (fetch → dedupe → score → enrich → synthesize → weekend set → dashboard feed → commit → email) | **Daily** routine (`routines/daily-digest-prompt.md`, commits to `claude/digests`) |
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
- [ ] **`scene-researcher` subagent + enrichment cache** — Tier 1 fan-out over the top ~30–40;
      cache by event-id + artist (the scene graph begins accumulating).
- [ ] **Enriched per-event schema** — add `type/subgenre tags`, `relevance` (★, taste-graph-driven,
      shown in the digest — today it's keyword-based and only in the dashboard feed), `curator_note`,
      `artist_notes`, cleaned `description`, and `image` (top 10). Date/time/venue/ticket-links
      already exist — keep all ticket links, labeled by source.
- [ ] **Two renderers from one enriched dataset**: keep the canonical `.md` (diffable, commits,
      GitHub renders) *and* generate a **rich HTML render** (type-colored tags, ★ relevance, card
      layout, top-10 hero images) emailed via the Gmail connector. Cache the top-10 images into the
      repo so emailed digests don't rot. (Confirmed: HTML email is the visual home; text-only `.md` stays.)
- [ ] Leveled-up `.md` per-event line, e.g.:
      `[house] ★★★★☆ **Title** — artist gloss · Fri 6/19 9pm · El Cid, Silver Lake · $7 · [RA] [DICE] — curator's note.`

## Phase C — Spotify taste superset (Spotify is the *music layer*, never the whole profile)
- [ ] **Spotify sync** — top/followed/recently-played artists + genres → the artist/genre affinity
      vectors, refreshed automatically. (Related-artists + audio-features endpoints were restricted
      for new apps late 2024 — lean on top/followed/recent; confirm what's live when building.)
      OAuth in a stateless repo: store a **refresh token** as a secret like `TM_API_KEY`/`POSH_TOKEN`,
      exchange each run.
- [ ] **Merge three layers into one scoring profile**: Spotify (music affinity, auto) +
      `taste.yaml` (the durable human layer Spotify can't know — settings/format prefs, rep cinema,
      daytime/lifestyle, comedy exception, walkability, north-star, penalties) + feedback
      (went/skipped/loved nudges weights). Spotify *enriches*; it never overwrites `taste.yaml`.
- [ ] **Close the feedback loop** — reactions + implicit signals (clicked ticket link? added to
      calendar?) fold into the weights automatically instead of being hand-merged.

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

## Tabled — deliberately deferred (Ari's call)
- [ ] Explorer / dashboard-page further investment (save-to-calendar exists via ICS; richer PWA waits).
      Dashboard stays alive only as the `build_dashboard.py` feed the daily run already rebuilds.
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
1. **HTML-email as the visual digest home** (Phase B) — ✅ resolved: keep the text-only `.md`
   canonical *and* email a rich HTML render with the top-10 images. Not reviving the dashboard for visuals.
2. **Delivery channels** (Phase B/D) — ✅ resolved: committed `.md` + HTML email + a conversational
   concierge surfaced via **claude.ai / web app** for now; dedicated text number deferred.
3. **Digest cadence** (resolved): **daily** weekend-set, ~4 months out. Revisit if commits get noisy.
4. **Taste weights** (ongoing): `taste.yaml` is yours — edit directly, or react and let the loop fold in.
5. **Dedupe spot checks** (Phase A): eyeball merged records for false merges while tuning the threshold.
6. **Spotify scope** (Phase C): confirm which Spotify data we sync once we see what's live post-2024 limits.
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
