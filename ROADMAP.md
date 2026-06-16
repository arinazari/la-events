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
      (currently inline in the by-hand merge — extract + test it)
- [x] Generic JSON-LD venue fetcher (`fetch_jsonld.py`) — built; few LA targets serve
      static JSON-LD (most are JS-rendered), so prefer per-source API fetchers.
- [ ] DICE fetcher — needs crawl-then-parse of /event detail pages or headless render
- [ ] Standardize all fetchers on America/Los_Angeles for window math (RA/TM use UTC today())
- [ ] Catalog hygiene: expire past events, track first-seen/last-seen, on-sale alerts
- [ ] Scheduled Routine live: daily digest committed to claude/ branch
- [ ] Delivery: digest lands somewhere Ari actually looks (see Decision 3)

### Sources brought online (2026-06-16)
- Live: Ticketmaster, RA, 19hz, Goldenvoice (AEG blob feed), Vidiots (Filmbot API),
  Eventbrite (curated organizers, with auto-harvest mechanism).
- Future source work:
  - [ ] Twilio textblast intake (NEXT) — SMS promoter blasts → catalog + organizer harvest
  - [ ] Posh — auth-based (account follows); no anonymous LA feed exists
  - [ ] Eventbrite — retry open browse if the AWS WAF CAPTCHA lifts / via headless
  - [ ] Rep cinema holdouts: New Bev (Veezi token), American Cinematheque (no public API)
  - [ ] Eastside comedy (Largo / Dynasty Typewriter / UCB) via per-site APIs (Filmbot playbook)

## Phase 3 — Personalization + frontend
- [ ] Feedback loop: reactions appended to taste.yaml `feedback`, periodically folded
      into weights (eventually: simple learned scoring from thumbs history)
- [ ] PWA frontend (NCCN Navigator playbook): feed UI, category/date/neighborhood
      filters, save-to-calendar, score-explanation per event
- [ ] Artist tracking: cross-reference rekordbox/listening data → artists_tracked
- [ ] On-sale sniper: alerts for tracked artists / New Bev calendar drops / fast sellouts

## Phase 4 — Nice-to-haves (only if Phase 2–3 earn it)
- [ ] SQLite instead of catalog.json if volume demands it
- [ ] Price tracking across ticket links (DICE vs TM fees)
- [ ] Weekend-planner mode: pick a night, get an itinerary (dinner → show → afters)

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
