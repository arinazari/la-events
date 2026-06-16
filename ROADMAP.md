# ROADMAP — la-events

Current phase: **1 → 2 transition** (skill + specs built, repo scaffolded, nothing live-tested yet).

## Phase 1 — Skill + manual runs  ✅ built / ⬜ validated
- [x] SKILL.md (digest / discover / flyer / sources modes)
- [x] Source registry seeded (40 sources)
- [x] Fetchers written: TM, RA, 19hz, Goldenvoice, Filmbot, Eventbrite, Posh, generic JSON-LD
- [ ] First live digest run (validates fetchers, RA AREA_ID, output format)
- [ ] TM_API_KEY obtained and set in cloud environment
- [ ] Gmail "Events" label created; first promoter lists joined (6AM, Dirty Epic first)

## Phase 2 — Aggregator infrastructure
- [ ] `scripts/run_digest.py` orchestrator: fetch all → normalize → dedupe → score
      against taste.yaml → write catalog + digest. (Currently the skill does this
      "by hand" each run; the orchestrator makes it deterministic and cheap, with
      Claude only doing the synthesis/writing step on top.)
- [ ] Dedupe module with fuzzy matching + a small test set of known-duplicate events
      (currently inline in the by-hand merge — extract + test it)
- [x] Generic JSON-LD venue fetcher (`fetch_jsonld.py`) — built; few LA targets serve
      static JSON-LD (most are JS-rendered), so prefer per-source API fetchers.
- [ ] DICE fetcher — needs crawl-then-parse of /event detail pages or headless render
- [ ] Standardize all fetchers on America/Los_Angeles for window math (RA/TM use UTC today())
- [ ] SMS ingestion live: stand up the Twilio receiver → `data/inbox.jsonl`; digest run
      consumes unprocessed lines (parse text / MMS flyer, dedupe, mark processed). Spec in
      `sms-ingestion.md` — reuses flyer-capture logic, depends on nothing else.
- [ ] Catalog hygiene: expire past events, track first-seen/last-seen, on-sale alerts
- [ ] Source health checks: standalone sweep that pings every `active` source and marks
      broken ones `flaky`/`dead` *before* a digest silently loses coverage. (Today health
      is only a side effect of digest runs; worth it mainly if digests aren't daily.)
- [ ] Scheduled Routine live: daily run maintains the rolling per-weekend digest set
      (`digests/weekends/`, ~4 months out) + catalog on a long-lived `claude/digests` branch
- [ ] Delivery: digest lands somewhere Ari actually looks (see Decision 3)

### Sources brought online (2026-06-16)
- Live: Ticketmaster, RA, 19hz, Goldenvoice (AEG blob feed), Vidiots (Filmbot API),
  Eventbrite (curated organizers, with auto-harvest mechanism), Posh (authed tRPC explore).
- Posh auth: `POSH_TOKEN` env var = session JWT, ~30-day life. Re-capture when it 401s
  (events.fetchMarketplaceEvents request → x-jwt-token). Durable refresh flow = future work.
- Future source work:
  - [ ] Twilio textblast intake (NEXT) — SMS promoter blasts → catalog + organizer harvest
  - [ ] Posh — durable token refresh (avoid 30-day manual re-capture)
  - [ ] Eventbrite — retry open browse if the AWS WAF CAPTCHA lifts / via headless
  - [ ] Rep cinema holdouts: New Bev (Veezi token), American Cinematheque (no public API)
  - [ ] Eastside comedy (Largo / Dynasty Typewriter / UCB) via per-site APIs (Filmbot playbook)

## Phase 3 — Personalization + frontend
- [ ] Feedback loop: reactions appended to taste.yaml `feedback`, periodically folded
      into weights (eventually: simple learned scoring from thumbs history)
- [ ] Active taste calibration: present small-set / A-B event choices and fold the
      selections into taste.yaml weights. Distinct from the reactive feedback loop above
      (which only learns from digest reactions) — this actively elicits preferences.
- [x] Static dashboard (`dashboard/`): explore + filter the catalog by date, type,
      location, and recommended rating; per-event score explanation ("why?"); installable
      PWA-lite (manifest + offline SW). Feed built by `scripts/build_dashboard.py` from
      catalog + taste.yaml. (Rebuild wired into the digest routine; save-to-calendar
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
4. **Digest cadence** (Phase 2): resolved → **daily**, maintaining the rolling per-weekend
   set (one file per weekend, ~4 months out). Revisit if daily commits prove noisy.
5. **Discover-mode approvals** (weekly): the candidate-source table — approve/reject.
6. **Dedupe spot checks** (Phase 2, early): eyeball merged records for false merges
   (two different events collapsed) — tuning the fuzzy threshold needs human eyes.
7. **PWA go/no-go** (Phase 3): a static dashboard now exists — decide whether it earns
   further investment (save-to-calendar, richer PWA) or digest + dashboard is enough.
   Decide after living with Phase 2 for a few weeks.

### Dining-layer decisions
- **D1. Radar cadence + format**: weekly (recommended, Wed AM) vs. on-demand only; does the
  radar format/length/tone land? Cheapest to change after the first run.
- **D2. Food-taste seeding**: currently minimal and learns from reactions. Switch to an
  explicit profile (cuisines, price, range, dietary) whenever you want sharper picks.
- **D3. Reservation depth**: stay at "hot-list + availability check on shortlist," or invest
  in deeper Resy/OpenTable/Tock integration (harder — no clean public APIs).
- **D4. Cross-layer planner**: should la-dining and la-events combine into a night itinerary
  (dinner → show → afters)? Listed as a Phase-4 events nice-to-have; dining makes it real.
