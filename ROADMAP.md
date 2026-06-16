# ROADMAP — la-events

Current phase: **1 → 2 transition** (skill built, repo scaffolded, nothing live-tested).

## Phase 1 — Skill + manual runs  ✅ built / ⬜ validated
- [x] SKILL.md (digest / discover / flyer / sources modes)
- [x] Source registry seeded (34 sources)
- [x] TM + RA fetchers written
- [ ] First live digest run (validates fetchers, RA AREA_ID, output format)
- [ ] TM_API_KEY obtained and set in cloud environment
- [ ] Gmail "Events" label created; first promoter lists joined (6AM, Dirty Epic first)

## Phase 2 — Aggregator infrastructure
- [ ] `scripts/run_digest.py` orchestrator: fetch all → normalize → dedupe → score
      against taste.yaml → write catalog + digest. (Currently the skill does this
      "by hand" each run; the orchestrator makes it deterministic and cheap, with
      Claude only doing the synthesis/writing step on top.)
- [ ] Dedupe module with fuzzy matching + a small test set of known-duplicate events
- [ ] DICE fetcher (JSON-LD) and generic JSON-LD venue fetcher driven by sources.yaml
- [ ] Catalog hygiene: expire past events, track first-seen/last-seen, on-sale alerts
- [ ] Scheduled Routine live: daily digest committed to claude/ branch
- [ ] Delivery: digest lands somewhere Ari actually looks (see Decision 3)

## Phase 3 — Personalization + frontend
- [ ] Feedback loop: reactions appended to taste.yaml `feedback`, periodically folded
      into weights (eventually: simple learned scoring from thumbs history)
- [x] Static dashboard (`dashboard/`): explore + filter the catalog by date, type,
      location, and recommended rating; per-event score explanation ("why?"); installable
      PWA-lite (manifest + offline SW). Feed built by `scripts/build_dashboard.py` from
      catalog + taste.yaml. (Wire its rebuild into the digest routine; save-to-calendar
      still TODO.)
- [ ] Artist tracking: cross-reference rekordbox/listening data → artists_tracked
- [ ] On-sale sniper: alerts for tracked artists / New Bev calendar drops / fast sellouts

## Phase 4 — Nice-to-haves (only if Phase 2–3 earn it)
- [ ] SQLite instead of catalog.json if volume demands it
- [ ] Price tracking across ticket links (DICE vs TM fees)
- [ ] Weekend-planner mode: pick a night, get an itinerary (dinner → show → afters)

## Dining layer (la-dining sibling skill)  ✅ scaffolded / ⬜ validated
- [x] la-dining SKILL.md (query / radar / discover / capture modes)
- [x] dining-sources.yaml seeded (Resy, OpenTable, Michelin, Infatuation, Eater, LAT + candidates)
- [x] dining-taste.yaml (minimal, learns from reactions) + data/dining.json + radar routine
- [x] Harvest fetch test (6/16): Infatuation + Resy blog fetch clean; Eater, LA Times,
      Michelin, OpenTable bot-block the fetcher → tagged `fetch: search_only`, harvested via
      domain-scoped web search. Encoded in dining-sources.yaml + SKILL.md fallback rule.
- [ ] First live query run end-to-end (rank + write a record to data/dining.json)
- [ ] First weekly radar (validates digest format/length/tone — Decision D1)
- [ ] Reservation availability: OpenTable/Resy booking widgets don't render via fetch — decide
      whether per-candidate availability needs a headless fetch or stays "set a Notify" advice
- [ ] Decide whether dining + events ever share a "weekend-planner" itinerary (dinner → show)
- [ ] Fold reservation hot-lists into a learned food-taste profile once reactions accumulate

---

## Decision points — Ari's input needed

1. **First live run review** (Phase 1): does the digest format/length/tone land?
   Cheapest moment to change anything.
2. **Taste weights** (ongoing): taste.yaml is yours — edit directly or react in
   sessions and let Claude fold it in.
3. **Delivery channel** (Phase 2): committed markdown? Gmail to inbox? Both? Inbox
   via connector is recommended — meets you where you already look.
4. **Digest cadence** (Phase 2): daily vs Mon/Thu twice-weekly. Recommendation:
   start Thu (weekend planning) + Mon (week ahead), go daily only if you want it.
5. **Discover-mode approvals** (weekly): the candidate-source table — approve/reject.
6. **Dedupe spot checks** (Phase 2, early): eyeball merged records for false merges
   (two different events collapsed) — tuning the fuzzy threshold needs human eyes.
7. **PWA go/no-go** (Phase 3): if the emailed digest fully serves you, the frontend
   may be unnecessary. Decide after living with Phase 2 for a few weeks.

### Dining-layer decisions
- **D1. Radar cadence + format**: weekly (recommended, Wed AM) vs. on-demand only; does the
  radar format/length/tone land? Cheapest to change after the first run.
- **D2. Food-taste seeding**: currently minimal and learns from reactions. Switch to an
  explicit profile (cuisines, price, range, dietary) whenever you want sharper picks.
- **D3. Reservation depth**: stay at "hot-list + availability check on shortlist," or invest
  in deeper Resy/OpenTable/Tock integration (harder — no clean public APIs).
- **D4. Cross-layer planner**: should la-dining and la-events combine into a night itinerary
  (dinner → show → afters)? Listed as a Phase-4 events nice-to-have; dining makes it real.
