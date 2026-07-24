# ROADMAP — la-events

> **Course correction (2026-07-08)** — a ground-up audit + product re-think reset priorities;
> where anything below conflicts, the newer docs win: `docs/AUDIT-2026-07-07-mission.md`,
> `docs/AUDIT-2026-07-07-product.md`, `docs/PLAN-2026-07-08-reshape.md`, `docs/TRACK-B-SPEC.md`.
> - **Track B — EXECUTING**: LLM-first ranking (the editor judges everything surfaceable;
>   verdicts govern the enrichment head / blurb pool / dashboard rank; taste.yaml becomes the
>   editor's brief, keyword weights demoted to coarse filter + tiebreak) plus the flagship
>   digest's product layer (Don't-miss · Around-town city-pulse · the Tier-3 voice pass).
> - **Track A — PENDING (next up)**: random capability tokens replace name-derived feed hashes,
>   repo goes private, published coords rounded, mutual stars (which double as the first
>   feedback-loop signal).
> - **Track C — DROPPED**: la-dining, night-planner, and the broad concierge STAY — hot-restaurant
>   radar, a good-restaurants list, and multi-event plans are wanted features, not scope creep.
> - The factory pauses: no new fetchers/pipeline sophistication until Tracks B + A land.

**What this is:** a private events + dining concierge for Ari and friends — *not* a venture.
The bar is "investor-quality" only in the sense of **polish, depth of curation, and the
"an insider made this for me" feeling**. Optimize for that, not for scale/moat/revenue.
City portability matters because friends live in other cities and Ari travels (Berlin next
week → same magic), not for TAM.

Current phase: **Phases A–D complete (all on `main`).** A (foundation / `run_digest.py` deterministic
core / routine + `SKILL.md` wiring), B (enrichment cache + scene graph, dual `.md`/`.html` renderer,
image caching — *no email*), C (Spotify taste superset + feedback loop), and D (concierge +
night-planner: travel engine, the planner wired, the concierge front door, la-dining's first live
query) are shipped + tested. **Phase E — the thin-editor ranking layer + the consolidated daily
digest — is built on branch `claude/laughing-ramanujan-vdxv38` (see Phase E below), pending merge.**
Next: the **Hosted page** (delivery + on-page actions — see below), the
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
each run — non-deterministic, slow, token-heavy. The tiers below fix that.

- **Tier 0 — Deterministic core (`scripts/run_digest.py`, no LLM).** Fetch all sources in
  parallel → normalize → dedupe → expire → score against the profile. **One shared, tested
  scoring/dedupe module** (today the ranking logic is duplicated in `SKILL.md` prose *and*
  `build_dashboard.py` — they will drift). Emits a ranked, deduped catalog + a candidate set.
  Burns ~no tokens; safe to run daily.
- **Tier 1 — Ranking judgment (`event-editor` subagents).** A thin LLM editor judges the
  already-scored candidates and returns a per-event **verdict** — a tier (must-see/great/solid/skip),
  an optional lane override, a small bounded score `adjust`, a one-line *why*, a confidence. It is a
  *delta on top of* the deterministic score, never a re-sort from scratch: the heuristic sets the
  spine, the editor catches what the heuristic can't (de-clustering a five-deep lineup, a
  mainstream-vs-afters lane call, a Spotify-affinity nudge). Verdicts are **cached + committed per
  profile** (`data/verdicts/<hash>.json`), so a daily run only judges the *delta* (new/changed
  events). They drive two surfaces: the digest **slate** (`lib/assemble.py` — merit fill + score-gap
  cliff + per-lane diversity floor, no firm caps) and the dashboard's **final rank** beside the score.
- **Tier 2 — Enrichment fan-out (`scene-researcher` subagents, top ~30–40 only).** Orchestrator
  spawns several in parallel, each taking a batch and returning per event: type/sub-genre tags,
  **artist notes** (who each name is, why on-taste), a **curator's note** (the opinionated take),
  a cleaned **description**, and for the **top 10 an image**. Subagents because: parallel, and
  **context-isolated** (each burns its own window on web research, hands back only the struct).
  **Cache enrichment on event-id + artist** — artists recur nightly, so the *scene graph
  accumulates* instead of re-researching Antal every day. That cache *is* the growing LA-insider
  knowledge base.
- **Tier 3 — Synthesis (main agent, one creative step).** Takes the enriched, scored, annotated
  set and writes the digest in the single "LA insider" voice. The only place the prose persona lives.

**Agent types** (`.claude/agents/`): `event-editor` (Tier 1 ranking judgment), `scene-researcher`
(Tier 2 enrichment), `source-scout` (on-demand discovery), `night-planner` (events × dining
itinerary). The `la-events` / `la-dining` SKILLs become orchestrators that call them. **Concierge** = the main conversational interface
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
- [ ] **HIGH PRIORITY — KCRW via the newsletter loophole (Ari, 2026-07-17).** kcrw.com is
      hard-bot-walled (Vercel checkpoint, 429s every datacenter fetch — re-verified 7/17), but its
      events coverage rides its newsletter: subscribe **"5 Things to Do in LA"** (kcrw.com/newsletters)
      with the digest Gmail account and route it to the **"Events" label** — the existing Gmail
      intake parses it like a promoter blast, no scraping, immune to the wall. Unique value: the
      free cultural long tail (Summer Nights @ CAAM/The Broad, Grand Performances) TM/Goldenvoice
      miss. Needs Ari (one signup + a Gmail filter); registry entry `KCRW Presents` stays
      `candidate` with the residential-IP probe documented as the secondary unlock path.

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
      score-free) + `data/candidates.json` (runtime, gitignored; the scored, ranked top-N for
      enrichment). Verified: 697→686 (dupes collapsed), idempotent.
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
      `artist_notes`, `curator_note`, `description`. ★ relevance reads the
      precomputed candidate `rating`. All ticket links preserved on the candidate.
- [x] **Markdown renderer from the enriched dataset** — `scripts/render_digest.py` → canonical `.md`
      (day-by-day, type tag, ★, linked title, curator note + gloss). Tested; can't drift. (Phase B also
      shipped a rich emailable `.html` renderer + hero-image caching `scripts/cache_images.py` /
      `lib/images.py`; **removed 6/25** as dead weight — no email ever shipped, the dashboard reads
      `.md`, and the cached images were never rendered anywhere. The `scene-researcher` no longer
      spends search calls hunting image URLs.)
- [x] **Routine wiring (no email)** — `routines/daily-digest-prompt.md` now runs core → layer →
      enrich → `render_digest --from/--to` per weekend (.md) → commit.
      Email intentionally dropped in favor of the **Hosted page** (below). **Phase B complete.**
- [x] **Per-day floor in the weekend render (follow-up, surfaced 6/17)** — `render_digest` used to
      pull from the *global* top-N candidate set, so quiet days starved: the first live weekend run
      surfaced only 2 of ~12 on-taste Sunday events (Hawtin's LACMA solstice set aside, the rest fell
      below the global cut while Fri had 56). **Addressed (Phase E):** `render_digest.build_slate_cands`
      now runs `lib/assemble.py` over the scored pool — it fills each in-window day toward a per-day
      target and guarantees a per-lane diversity floor, so every day is covered, not just the globally
      top-scored ones (no more hand-pulling quiet days from the catalog).

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

## Phase E — Thin-editor ranking + consolidated digest  (branch `claude/laughing-ramanujan-vdxv38`)
The ranking-judgment tier (above) made real, plus one daily digest replacing the per-weekend-only output.
- [x] **`event-editor` agent + per-profile verdict store** — `.claude/agents/event-editor.md` (Tier-1
      judgment, sibling of `scene-researcher`); `scripts/lib/editor.py` plumbs the judging pool
      (`editor_pool`, non-slate lanes skipped), the per-profile verdict cache (`data/verdicts/<hash>.json`,
      committed), delta/staleness selection (`select_for_verdict` — only new or score-drifted events cost
      a call), and validation (clamps `adjust`, defaults confidence). `scripts/merge_verdicts.py` folds an
      agent's results back into the store. Validated by a real 28-event agent run (caught a substring
      false-match, duplicate feed pairs, a Chris-Lake mis-lane — proof the editor adds what the heuristic misses).
- [x] **Slate assembler** — `scripts/lib/assemble.py`: lanes (club → mainstream/afters/day/underground
      via tags + an arena gazetteer + a price proxy; non-club = `tags.type`), an **elastic slate** (merit
      fill to a per-day target, a score-gap *cliff* cut, a per-lane diversity *floor* — no firm caps; a
      `mute` mood knob), and two ranking keys: a tier-primary `effective_key` for the slate vs. an additive
      `rank_score` (score + adjust + bounded tier bonus) for the dashboard's global `final_rank`. Tested.
- [x] **Spotify surfaced to the editor** — each judging record carries an `affinity_hint` (matched
      artists + tier/weight, high-affinity genres) and the batch a `profile_affinity` summary, so the
      editor treats listening history as a first-class signal — per profile (the music layer the LLM can use).
- [x] **Consolidated daily digest** — `scripts/build_radar.py` (deterministic "on the radar" set:
      editorial / festival / tracked-artist / arena signals, ranked) + `render_digest.py --consolidated`
      → ONE doc (`digests/latest.md`): next 14 days day-by-day · weekends ahead (days 15–35,
      Thu–Sun) · on the radar. The windowed `--from/--to` mode is **retained** as the per-weekend
      look-ahead (a future dashboard view). Live end-to-end dry run
      (2026-06-20): fresh fetch (3421 catalog) → radar (336) → consolidated (82 + 78 + 18), both renderers
      well-formed; the run caught + fixed a radar month-grouping bug (rank-sorted items now date-sorted before grouping).
- [x] **Dashboard score ⇄ rank column** — `build_dashboard.py` attaches each event's verdict + lane and a
      `final_rank` (over upcoming, via `rank_score`); `dashboard/index.html` shows the deterministic score
      (number + colored bar gauge) AND the verdict-adjusted final rank in one column, sortable by either
      (tier-colored rank label). The score stays the transparent spine; rank shows the editor's overlay.
- [x] **Consolidated digest reaches the dashboard (staging wiring)** — the header affordance that opens
      "curated digest for <name> ↗" already shipped on `main`, and `loadDigestFor` already fetched
      `digests/<hash>/latest.md` per profile / `digests/latest.md` for the default. The missing link was
      *staging*: the deploy published the newest **dated** digest as `dashboard/digests/latest.md`, so the
      new consolidated digest never reached the page. `stage_digests.py` (+ the two inline-staging
      workflows, build-profiles / spotify-sync) now publish the **consolidated** `digests/latest.md` as the
      default + owner digest, falling back to newest dated; dated files still feed the "past digests" dropdown.
- [x] **Cross-source festival dedupe** — `lib/dedupe.py` festival path: same date + matching festival core
      name (organizer "X presents:" prefix + year/edition/format/ticket-tier filler stripped) + loosely-
      related venues (shared token, or one side TBA) merges festivals that list under different names AND
      venue strings across sources (e.g. "HARD Summer 2026"@ra vs "HARD Summer Music Festival"@fgtix).
      Festival-ness is a property of the pair; one-sided cases demand an identical core. Validated on the
      live catalog: 6 new merges, all genuinely the same event, zero false merges.
- [ ] **Land on `main`** — merge the branch; the first scheduled routine run then judges the live delta,
      commits `digests/latest.md` + the per-profile verdicts, and the Pages workflow redeploys.
- [ ] **Per-profile editor pass** — `build_profiles.py` already emits each profile's own judging pool
      (`data/editor_pool.<hash>.json`); run the editor + `merge_verdicts.py --profile-hash <hash>` per
      friend to give them the full editor treatment (else their feeds rank deterministically against their
      own music and pick up verdicts next run).
- [ ] **Wire `editor.prune_verdicts` into the routine** — the prune helper exists and is tested
      (`lib/editor.py`), but nothing operational calls it: the daily routine runs only
      `prune_enrichment.py`, so orphaned keys accumulate in `data/verdicts/<hash>.json` as merged /
      expired events leave the catalog. Harmless today (every verdict read is a miss-tolerant
      `.get()`) — just unbounded growth in a committed file. Surfaced by the 2026-07-16
      dedupe-fix review.

## Phase F — Horizon expansion (the 6-month plan-ahead tier)
**Why now (the canonical miss):** Lori saw on *Bandsintown* that Alanis Morissette plays LA in
November and bought tickets — a tracked-artist-worthy show ~5 months out that a per-artist app
caught while we were blind past 3 weeks. The daily run fetches a flat 21-day window, so festivals,
big tours, and theater seasons never enter the catalog until they're nearly here. (Same root cause
as the Daisy Chain Fields miss; the festival geo-waiver shipped 2026-06-23 is brick #1 of this tier.)

**The key insight — extending the horizon is cheap.** The expensive (LLM) tiers are already
windowed and independent of catalog size: the editor judges `--editor-window 28`, enrichment is
top ~30–40 only. So going to 6 months is mostly a *deterministic* fetch/catalog change, **not** an
LLM-cost explosion — as long as the editor/enrich windows stay near-horizon and the far tail is
deterministic-only (radar). The digest already *renders* "weekends ahead (~4 mo)"; this feeds it.

**The shape — two-speed, not uniform.** Most sources (DICE/19hz/Squarespace/venue-webfetch) only
publish ~2–6 weeks out, so a uniform 180-day fetch buys nothing from them. The far tail is inherently
TM (date-windowed) + Goldenvoice (full feed already) + RA + theater seasons + festival ticketers.
  - **Near (~21–35d): full fidelity** — all sources, full editor + enrichment, day-by-day. (today)
  - **Far (35d–6mo): deterministic plan-ahead** — only far-publishing sources, gated to radar-worthy
    scale (festival / big-venue / tracked-artist / on-sale), **no per-event LLM**, feeds catalog →
    radar + weekend look-aheads. Can run **weekly** (far events don't move nightly; `content_version`
    gate makes no-ops cheap).

- [x] **Phase 1 — two-speed fetch + the TM truncation fix (2026-06-23).** `run_digest.py`
      `--far-days N` reaches the wide horizon for `far: True` sources (Ticketmaster); near sources keep
      `--days`. `fetch_ticketmaster.py` now **date-windows** the query (`--chunk-days`, default 30) so a
      wide range doesn't silently hit the API's <1000-results/query cap (the 21-day default stays one
      window). Ghost-detection (`flag_stale`) deliberately stays on the near window so far events aren't
      flagged unlisted before their feeds list them. Off by default (behaviour-preserving); tested.
- [ ] **Turn it on in the routine** — add `--far-days ~180` to the daily run (or a separate **weekly**
      far-sweep routine, the cheaper option). Confirm the first live run's TM volume + windowing.
- [ ] **Per-artist "tour radar" (the Bandsintown lesson)** — for tracked / high-affinity artists,
      surface ANY announced LA-area date at any horizon. Mostly free already: the far TM sweep +
      `build_radar`'s `tracked` signal does this once the artist is in `artists_tracked`/Spotify. The
      Alanis case also wants her in Lori's tracked list (a taste-content nudge, not architecture).
- [ ] **Widen RA to the far window** — mark `far: True` once its pagination/rate-limits are vetted past
      ~2 months (RA caps at ≤10 small pages); far RA coverage is thin, so low priority.
- [ ] **Dashboard far-tail UX** — default the grid to near-term with a "plan ahead / on the radar"
      section; cap each per-profile feed's far tail to radar-worthy so feeds don't balloon × N profiles.
- [ ] **Volume watch** — a 6-month catalog may finally trip the tabled **SQLite** swap (below); revisit
      `catalog.json` diff size + feed weight after the first wide run.

**Decisions — Ari's input:** (1) **two-speed vs uniform** (recommend two-speed); (2) **far-tail filter**
— radar-signal-gated vs keep-everything; (3) **cadence** — far sweep weekly (lean) vs daily; (4) **far
horizon** — 6 mo, or further for festivals/theater seasons.

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
- **Static core, wired:** the committed `digests/latest.md` + `dashboard/data.json` deploy to GitHub
  Pages (`.github/workflows/deploy-dashboard.yml`); the dashboard renders the Markdown digest.
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
- **Remaining (not blocking):** the backend **code** is done (chat + taste self-edit, see below) —
  what's left is for Ari to **deploy** it (wrangler + secrets). **Auth chosen: shared `CONCIERGE_TOKEN`**
  (Cloudflare Access remains an option later); optional streaming + auto-commit of plans.
  Public/unlisted Pages + Fast-filter fallback is fine until then (catalog = public events).
- [x] **Profiles — per-person taste switcher (2026-06-19)** — a "prof" link (footer) opens a popup;
  a friend types a username (acts as the key) → the page SHA-256s it (salt `la-events/v1:`, same as
  `scripts/build_profiles.py`) and loads that profile's feed `dashboard/data.<hash>.json` (its own
  taste + digest). Profiles are **hand-authored** in the repo: `profiles/<name>/taste.yaml` + an entry
  in `profiles.yaml`; `build_profiles.py` emits each feed reusing `build_dashboard.py`'s scorer (so a
  profile's ranking can't drift from the digest). Blank/unknown stays on the default (Ari's) feed.
  **Obfuscation, not security** — usernames are publicly-fetchable bearer keys (fine for a few friends).
  (a) per-profile **digest generation**, (b) concierge-per-profile + **friend self-edit**, and (c)
  **per-profile Spotify** are now built — see below. Profiles re-rank the *same* catalog (sourced to Ari's
  taste), so full personalization eventually wants per-profile source coverage too.
- [x] **Per-profile Spotify — the music layer per friend (2026-06-20)** — closes deferred (c). Each
  profile now scores against ITS OWN music layer: the scorer threads a feed-hash through
  `lib/feedback.merged_affinity` → `data/spotify/<hash>.json` + `data/feedback.<hash>.jsonl` (no hash =
  the canonical owner layer; byte-identical when absent). Onboarding is **full web-OAuth + Worker KV**
  (Ari's call): a "Connect Spotify" button in the profile popup → the concierge Worker's `/spotify/login`
  → token stored in Cloudflare KV keyed by hash → an authed sync (`sync_profiles_spotify.py`, called by
  the daily routine + a `spotify-sync` CI job on the Worker's `repository_dispatch`) pulls only RAW
  payloads (token never leaves CF) and folds them via the one tested `lib/affinity.build_affinity` →
  per-profile feed. The affinity artifact is **gitignored** (a friend's listening; only the derived feed
  ships). **Needs Ari to deploy**: Spotify app + redirect URI, `wrangler kv namespace create SPOTIFY_KV`,
  Worker secrets (`SPOTIFY_CLIENT_ID/SECRET`, `SPOTIFY_SYNC_TOKEN`, `STATE_SECRET`), and repo secrets
  (`SPOTIFY_SYNC_URL` + `SPOTIFY_SYNC_TOKEN`) — see `backend/README.md`. Known privacy tradeoff: feed
  hashes are public, so connect-gating is the shared `CONCIERGE_TOKEN` (obfuscation, not security); a
  per-feed "hide Spotify reasons" toggle is a future nicety.
- [x] **Friend taste self-edit via the concierge (2026-06-19)** — in a profile, the concierge chat now
  *edits your taste by talking to it* ("more techno, less comedy", "track Peggy Gou"). The Worker
  (`backend/`) grounds chat on the profile's feed and, when `GITHUB_TOKEN` is set, exposes a
  `propose_taste_change` tool: it applies a **structured patch** to `profiles/<name>/taste.yaml`,
  validates it re-parses, and commits. A new CI job (`.github/workflows/build-profiles.yml`) re-scores
  that feed with the shared `build_profiles.py` scorer and redeploys — **commit + CI rebuild, ~1–2 min,
  zero scorer drift, git = rollback** (chosen over edge re-scoring). The popup also shows your taste YAML
  read-only. Security relaxed by design (taste writes are low-stakes/revertible): `CONCIERGE_TOKEN` guards
  API spend + commit-spam, and the GitHub PAT is repo-scoped Contents-only. **Needs Ari to deploy the
  Worker + set the 3 secrets** (`backend/README.md`).
- [x] **Profile / MECHANISM self-edit via the concierge (2026-06-20)** — the concierge can now also edit
  `profile.yaml` (location + scoring dials), not just `taste.yaml` (content). Both surfaces: the Worker
  gained a second structured tool `propose_profile_change` (home/coords, `category_weights`, and the
  near-home / penalty / boost / far term lists — source ids, rating thresholds, and the numeric
  Spotify/feedback/travel knobs deliberately left to hand-editing), and the conversational concierge
  (`SKILL.md` path 3) does the same for Ari's root file. Owner → root `profile.yaml`; friend → their own
  `profiles/<name>/profile.yaml` (created on first edit). The one non-obvious bit: `lib/scoring.py`
  resolves each scoring key **all-or-nothing** (profile → taste → default), so a first edit
  **materializes the full effective list/map** (seeded from root `profile.yaml` = the defaults verbatim,
  so no duplicated constants in JS) before applying the delta — otherwise a partial write silently drops
  the rest. Worker-only change + docs (no scorer/build touch); same CI rebuild + `git = rollback`
  safety as taste. Node-tested (`applyProfilePatchDoc`). Rides the same Worker deploy.
- [x] **Per-profile digests (2026-06-19)** — the daily routine now (step 7) rebuilds *every* feed
  with `build_profiles.py` (friends' feeds stay fresh as the catalog changes, not only on self-edit),
  and (step 8) writes a personalized narrative digest per profile to `digests/<hash>/latest.md`.
  Both deploy workflows stage `digests/<hash>/latest.md → dashboard/digests/<hash>/latest.md`; the
  page already loads it (placeholder until the first routine run). Owner profiles ≈ the default digest.
- [x] **Header = "curated digest for &lt;name&gt;" (2026-06-20)** — the dashboard header now reads
  *curated digest for me and my friends* (logged out) / *…for &lt;name&gt;* (logged in), and the name
  is the click-target that opens that person's digest (the deterministic, pre-built `latest.md`).
  Aesthetic + wiring only; on-demand generation of a missing digest is deferred until the
  digest-rebuild work lands (it changes whether generation should be edge/Worker vs client-side).
- **Subsumes the tabled dashboard** — this *is* the explorer, evolved into the interactive home.
- [x] **Front end swapped to the design-tool UI (2026-06-18, branch `claude/exciting-feynman-v6vqo6`)** —
  the hand-written 3-view app was replaced by Ari's uploaded design (a single `dashboard/index.html` +
  its `support.js` "dc-runtime"). **Backend unchanged**: `build_dashboard.py` + `lib/scoring.py` still
  produce `dashboard/data.json` and the page stays a pure viewer. The design's two claude.ai-only
  features were rewired to the repo's patterns — chat ("ASK THE DIGEST") → local no-LLM intent parser
  (`localSpec`), Discover → copy-to-Claude-Code hand-off. React/ReactDOM/`@babel/standalone` vendored
  locally (off unpkg); PWA + deploy workflow carried over (deploy stages `digests/latest.md`).

- [x] **Digest + landing-page redesign (2026-07-16, branch `claude/digest-landing-page-redesign`)** —
  the consolidated digest restructured (day sections group by slate LANE with afters/day-party/big-room
  chips — the raw source category had been filing warehouse bills under "Other"; tier-scaled entries:
  full / compact / collapsed "Also:" row per the verdict; Don't-miss priced + urgency-chipped, blurbs
  no longer repeated verbatim in the day body; NEW sections **Tonight & tomorrow** (tier3:call slot)
  and **What changed**; Fri/Sat **tier3:blueprint** night-sketch slots; radar rows carry tier3:gloss
  slots; "Weekends ahead" compressed to top-4 + a link to the per-weekend file (now staged/published);
  ops banners moved to the footer). Root cause fixes underneath: Ticketmaster's capitalized segment
  names never matched the tagger ("other" was 65% of the catalog → now ~1%), and detail-blob keywords
  could retype concerts. AND the dashboard now opens on a **Front page** — a time lens
  (tonight/weekend/2wk/ahead) + a Don't-miss hero row + per-lane shelves, all computed
  server-side (`build_dashboard.build_front_page`, same rank_key as final_rank; the page
  never re-ranks); the table demoted to **Explore** (header switch, per-device persistence).
  (As first shipped this page also opened with a "The Take" lede card and tier-badged the hero;
  since revised — the take moved into the concierge chat as a dated one-sentence teaser (#92 +
  the follow-ups below), and the hero unbadged (#93).) Every
  feed event now carries its stable `key` (event_key) — the join id, and the anchor for feedback
  reactions when that lands.

### Redesign follow-ups (from the 2026-07-16 review) — ✅ both shipped 2026-07-20
- [x] **One "Don't miss" policy across surfaces** — resolved as SAME (the "one policy" reading):
  `lib/assemble.top_picks` (next to `slate_fill`/`rank_key`) is now THE shelf definition —
  rank_key order (the exact expression `final_rank` is stamped from), judged skips out, one
  night per program, and the shared `TOP_PICKS_*` diversity knobs (2-per-lane / 3-per-family,
  N=6). Both `render_digest._dont_miss_events` and `build_front_page`'s hero run it, so the
  digest shelf now gets the hero's diversity too (five club nights can't fill it; live-music/
  film picks displace the 4th-best club bill). If Ari prefers the shelves deliberately
  different, the knobs are per-call args — change one caller, not the policy. Composes with
  the taxonomy revamp: the family cap spans `live-music:*` exactly like `club:*`.
- [x] **Emit "The Take" structurally** — revised per Ari (2026-07-20): the take is NOT the
  digest intro lifted verbatim — it's a dedicated **one-sentence, high-level teaser** the
  voice pass writes into an invisible `<!-- take: … -->` slot under the digest header
  (distinct from the 2–4 sentence `tier3:intro`). `build_dashboard --digest` lifts it into
  each feed as `front_page.take = {text, date}` — the date is the digest's own date, so the
  chat welcome shows it's genuinely today's read, honestly stale otherwise; `build_profiles`
  points each friend's build at their OWN `digests/<hash>/latest.md` (no slot → `take: null`;
  never Ari's teaser). The page prefers the structural take for the chat welcome
  (`seedTake`); the `digestLede()` heuristic survives only as the fallback, clipped to one
  sentence. **Display-only by design**: the take renders as if the concierge said it but is
  NEVER sent to the model — the `opener` system-prompt field is removed (page + Worker); the
  concierge stays grounded on the feed data alone.

### Dashboard follow-ups (TODO — from the front-end swap)
- [x] **Pre-transpile build step** — OBSOLETE as written (2026-07-24): the redesigned front end
  ships plain JS (dc-runtime `support.js` evaluates the template directly; no in-browser Babel),
  and the dead ~3 MB vendored `@babel/standalone` is deleted. The surviving client-weight item is
  the feed: `data.json` (~7.9 MB raw, ~1 MB gzipped) re-fetched `no-store` each boot — fix is a
  slim boot feed + lazy full catalog, or content-versioned feed URLs with normal caching.
- [x] **Content-versioned feed fetch (2026-07-24)** — the page now loads `catalog_meta.json`
  first (161 B, no-store) and fetches the big feed as `data[.<hash>].json?v=<content_version>`
  with normal HTTP caching: unchanged catalog → the browser serves its cached copy / a cheap 304
  instead of re-downloading ~7.6 MB every boot. Post-rebuild reloads bust with `?v=<now>` (a
  profile rebuild changes the feed without moving the catalog version).
- [ ] **Slim boot feed (VERY HIGH per Ari, 2026-07-24)** — the deeper fix: `build_dashboard`
  emits a small boot feed (front_page + config + the slate head, ~a few hundred KB) that paints
  the front page immediately, with the full catalog lazy-loaded only when Explore/search needs
  it. Composes with the versioned URLs above. Touches build_dashboard/build_profiles emit + the
  page's loadFeedFor; keep the "one policy" invariant — the boot feed must carry the same
  front_page block, not a re-derived one.
- [x] **Per-event ICS export** — re-ported the one-click add-to-calendar (was `dashboard/js/ics.js`;
  regressed in the swap). Now an "Add to calendar ↓" button in each event's expanded detail row;
  self-contained RFC 5545 builder on the `Component` class (floating LA-local times, 3-hr default,
  all-day fallback, lineup/curator-note/price/rating/link in the description).
- [x] **Calendar subscription** (2026-07-20; saved-events added 2026-07-21) — Settings → **Calendar
  feed**: a subscribable iCalendar polled by Google/Apple so it stays current, in two modes via a
  source toggle — **Top picks** (the profile's taste-ranked events) and **Saved** (the starred
  shortlist). The Worker serves `GET /calendar.ics?p=<hash>&…` (unauthenticated — it only re-serves
  the public feed): picks mode takes min rating / per-day cap / horizon / weekdays / include-exclude
  type+genre chips in the query string; the **Starred** calendar takes `saved=1` and resolves the
  profile's stars server-side from the feed's `stars` field — a stable url (the earlier `keys=`
  event-list is kept as a legacy/snapshot fallback). `dashboard/calendar-core.js` is the ONE filter/ICS builder, loaded by the page (live
  preview + one-shot `.ics` snapshot) and imported by the Worker, so preview and subscription can't
  drift. Subscription URLs use explicit `TZID=America/Los_Angeles` (+VTIMEZONE) — a deliberate
  divergence from the floating-local one-shot exports, since polled feeds cross clients. Build
  `2026-07-21-cal2`. Track A: the URL carries the feed hash; when capability tokens replace hashes,
  `p=` inherits that swap.
- [x] **Save / bookmark events → server-side stars** (2026-07-21) — shipped first as a per-browser
  localStorage shortlist, then reworked to **server-side stars** (Ari's call: saves must be shared,
  not per-device). A **☆ Star** on the Explore row / mobile card / front-page detail POSTs to the
  Worker's `POST /react`, which commits to `data/reactions.jsonl`; CI folds `stars: [{name,hash}]`
  onto every feed, so a star is **mutual** — "★ Lori" shows on the card + in digests for everyone —
  AND it's the seed of the learning loop (star→`loved` into `feedback.<hash>.jsonl`, ranked by the
  existing fold). The Starred calendar reads server stars via a stable `?saved=1` (no re-subscribe).
  Ported from Track A "A4: stars" (`claude/track-a-execution-vu3gif`), reactions.jsonl schema kept
  identical for a clean merge; the tokenization/private-repo parts of Track A stay out of scope.
- [~] **Like → learn taste** — largely shipped via **stars** (2026-07-21): the ☆ Star's server commit
  also appends a `loved`/`hide` line to `data/feedback.<hash>.jsonl` (`POST /react`), which the existing
  `lib/feedback.py` → affinity fold ranks with — the star IS the "more like this" signal, no separate
  👍/👎 needed. Remaining: an explicit **👎 / never-show** surface (the `hide` kind exists in `/react`
  but the dashboard only sends `star`/`unstar`; wire a hide affordance if wanted). No hand-off seam
  needed anymore — the Worker commits directly.
- [ ] **In-app taste editing (direct YAML)** — the profile popup is now slim (signed-in · log out +
  a "View your taste profile →" link) and opens a dedicated **read-only** taste modal (2026-06-20).
  Making it *editable in-page* means a Worker save path: POST the full YAML → validate (re-parses +
  required keys like `categories`) → commit to the profile's taste file (owner → root `taste.yaml`,
  friend → own `profiles/<name>/taste.yaml`), gated exactly like `propose_taste_change` and
  git-revertible. **Deferred by choice (2026-06-20)** — kept read-only so the structured-patch safety
  holds and there's no browser-side commit; the concierge chat stays the edit path. Pick this up if
  free-text editing is wanted (mind: it loosens "structured-patch-only" to arbitrary valid YAML, and
  needs a Worker redeploy).
- [x] **Taste/profile self-edit *diff* + "reflected?" badge (2026-06-25)** — the read-only modal is now a
  two-tab view (**Taste | Profile**, profile.yaml surfaced for the first time) that shows, per file: a
  colored **diff** of how the concierge adjusted it + a recent-edits list, and one **reflected/pending**
  badge — is the change live in your ranking & digest, or not yet (with an *Update now →* CTA that fires
  the existing per-profile rebuild). All static-first: `build_profiles.py` bakes a `profile.self_edit`
  block (diff + content-based `reflected`, derived from git — the file vs. the last enrichment commit)
  into each feed; the page just renders it, and `isTasteDirty()` now treats that baked flag as
  authoritative (one pending state shared with the Settings "Update" button — ranking + enrichment read
  as one thing, per Ari). `build-profiles`/`rebuild-profile` checkout `fetch-depth: 0`; the latter
  rebuilds the feed after committing enrichment so an Update flips pending→reflected immediately.
- [x] **Role-gated settings (2026-06-20)** — the gear menu branches by who's signed in. The **owner**
  (ari; `owner: true` in `profiles.yaml`, propagated into the feed's `profile` block by
  `build_profiles.py` and read on the page as `META.profile.owner`) keeps **Refresh events** +
  **Discover new sources**. A signed-in **friend** instead gets: a **Claude API key** field (BYOK —
  now wired, see below), **Spotify connect** (placeholder; the real flow is
  on another branch), **View taste profile** (the read-only modal), and **Log out**. **Logged-out**
  shows only a **Log in** affordance plus a data-freshness readout — **last data pull** (feed
  `generated_at`) and **last site update** (`document.lastModified`, i.e. the Pages deploy time).
  Refresh/Discover are no longer exposed to non-owners.
  - [x] **Bring-your-own-key (BYOK), 2026-06-20** — the Claude API key field is now live (was a stub).
    The key is stored in-browser and sent to the concierge Worker per request (`x-anthropic-key`);
    the Worker spends it instead of the owner's `ANTHROPIC_API_KEY`. A valid personal key also
    satisfies the Worker's access gate, so a friend can run the concierge on their own key without the
    shared `CONCIERGE_TOKEN`. A managed on/off switch picks key vs. shared token (no silent failover —
    if a live key errors, the user flips it off and the token takes over). Taste self-edit is open to
    own-key callers too (Ari's call) — the commit uses the owner's `GITHUB_TOKEN`, so a friend can teach
    their taste on their own key; accepted tradeoff is that any valid key can trigger a revertible commit.
    Needs the Worker redeployed (`npx wrangler deploy`) to take effect; see `backend/README.md` → Auth.
  - [ ] **Tabled (Ari's call, 2026-06-20):** also let a signed-in friend **view their profile
    details** and **their reactions / feedback history** from settings. Deferred until the feedback
    surface (👍/👎 → `data/feedback.jsonl`, the Like→learn item above) lands so there's a history to show.
- [x] **Live refresh / per-user re-rank with staleness indicator (2026-06-20)** — the catalog is now
  *versioned* (`scripts/lib/catalog_meta.py`): `run_digest` writes `data/catalog_meta.json`
  (a stable hash over each event's venue|date|title — ignores volatile seen-stamps), `build_dashboard`
  stamps every feed with the `catalog_version` it was scored against AND republishes
  `dashboard/catalog_meta.json`. The dashboard fetches that live file each load and compares: when a
  profile's feed is behind, the settings panel's **"Update my ranking & digest"** button lights up
  (and shows the new DB pull time); when in sync it's disabled ("up to date"). The **owner** also gets
  **"Refresh events database"** (re-fetch all sources → rebuild catalog + default feed → republish the
  version — applies to everyone; per-user feeds are intentionally left stale so each person self-regens).
  Both buttons POST to the concierge Worker (`/refresh-events`, `/rebuild-profile`), which fires
  `repository_dispatch` → new workflows (`refresh-events.yml`, `rebuild-profile.yml`) rebuild +
  redeploy — same seam as `spotify-sync`. Needs the Worker deployed with `GITHUB_TOKEN`
  (Contents: write — same token taste self-edit / spotify-sync already use, no extra scope);
  degrades to a clear "connect the backend" toast otherwise. `build_profiles
  --only-hash` lets the rebuild target a profile by its public feed hash (the page never knows the username).
  - **refresh-events** is deterministic (fetch → catalog → default feed → version), so it's cheap and
    needs only the source secrets. **rebuild-profile** runs the **full LLM pass** for that one profile —
    `anthropics/claude-code-action` executes `routines/profile-digest-prompt.md` (event-editor verdicts +
    scene-researcher enrichment + the personalized narrative digest), so the per-user button gives the
    same quality as the nightly routine, on demand. It needs `ANTHROPIC_API_KEY` as a repo Actions secret
    and costs tokens / a few minutes per click; it syncs that profile's Spotify first so a single-profile
    build keeps its music layer. (Owner nuance: the owner's *displayed* digest is the shared consolidated
    one — refreshed nightly / on a full refresh — while their feed ranking updates on click like everyone.)
- [x] **Per-profile LLM refresh is taste-gated + user-driven, not nightly (2026-07-15)** — friends'
  curated layer (per-profile event-editor verdicts + narrative digest) no longer reruns every night
  as the catalog moves; the **deterministic feed re-rank stays nightly for everyone** (free — new
  events in, expired out, cached verdicts folded), so only the paid layer waits. It refreshes on
  exactly two signals: **their config changed** (taste/profile/digest-prefs/feedback since their
  last enrichment — `scripts/profile_refresh_gate.py`, the git-derived nightly gate, same
  content-based bar as the reflected badge) or **they hit Update** (the existing rebuild-profile
  path, unchanged). SKIP profiles' verdicts/digests stay as-committed (honest "last refreshed"
  dates). The dashboard adds a **refresh-nudge popup**: once a signed-in profile's curated layer
  (`self_edit.enriched_at`) is 3+ days old — or the person returns after 3+ days away with an
  Update pending — it explains the model (table nightly; curated layer on taste-change/Update) and
  offers the Update; snoozes a day on "Not now", never fires logged-out or over the first-run
  tour. The popup is deliberately short, with a "How this works" expander for the detail; a
  **persistent** blue dot on the ☰ settings icon + an "update available" chip in the digest modal
  (both keyed to `layerBehind()` — curated layer older than the latest events) show whenever a
  pass is waiting, no snooze. Default + owner + consolidated digest keep the full nightly
  treatment. (docs/PIPELINE.md is the reference. Note: the Update's LLM pass runs on the repo's
  `ANTHROPIC_API_KEY`, not a friend's BYOK key — BYOK covers the Worker paths (chat, self-edit);
  forwarding a browser-held key into public-repo CI would risk exposure. Revisit after Track A.)

## Tabled — deliberately deferred (Ari's call)
- → Explorer / dashboard page is **no longer tabled** — it evolves into the **Hosted page** (above).
- [ ] Flyer-forwarding bot + Twilio SMS/MMS intake (`sms-ingestion.md`). Capture-by-hand still works.
- [ ] On-sale sniper / price tracking across ticket links (DICE vs TM fees). Nice-to-have.
- [ ] SQLite instead of `catalog.json` if volume ever demands it.
- [ ] **Shared lane corrections** (surfaced by the 2026-07-17 taxonomy revamp; Ari wants lanes
      standardized across profiles). Tags + deterministic lanes are already one shared, taste-neutral
      vocabulary — but the event-editor's *lane override* is stored per profile
      (`data/verdicts/<hash>.json`, ~165 overrides), so the same event can sit in different lanes on
      different profiles' feeds when their editors disagree. A lane correction is a FACT call
      (headliner draw, a nostalgia night's character), not taste — so move it into the shared
      enrichment layer (`data/enrichment.json` scene facts, cross-profile by design): the editor
      still *proposes* a lane, `merge_verdicts` folds it into enrichment instead of the verdict
      store, `event_lane` reads it as a deterministic input, and per-profile verdicts keep only the
      taste fields (tier/adjust/why). Migration: one pass folding existing verdict-lane overrides
      into enrichment (conflicts → most-recent judged_at wins), then strip `lane` from the verdict
      contract + event-editor.md. Small, contained; do it alongside the next editor-contract bump.

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
