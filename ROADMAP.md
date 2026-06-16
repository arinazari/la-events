# ROADMAP — la-events

Current phase: **1 → 2 transition** (skill + specs built, repo scaffolded, nothing live-tested yet).

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

## Phase 3 — Personalization + frontend
- [ ] Feedback loop: reactions appended to taste.yaml `feedback`, periodically folded
      into weights (eventually: simple learned scoring from thumbs history)
- [ ] Active taste calibration: present small-set / A-B event choices and fold the
      selections into taste.yaml weights. Distinct from the reactive feedback loop above
      (which only learns from digest reactions) — this actively elicits preferences.
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
4. **Digest cadence** (Phase 2): resolved → **daily**, maintaining the rolling per-weekend
   set (one file per weekend, ~4 months out). Revisit if daily commits prove noisy.
5. **Discover-mode approvals** (weekly): the candidate-source table — approve/reject.
6. **Dedupe spot checks** (Phase 2, early): eyeball merged records for false merges
   (two different events collapsed) — tuning the fuzzy threshold needs human eyes.
7. **PWA go/no-go** (Phase 3): if the emailed digest fully serves you, the frontend
   may be unnecessary. Decide after living with Phase 2 for a few weeks.
