# REVIEW — how restaurants fold into the system (2026-07-16)

Scope: trace every path a restaurant takes through the repo, assess what's sound vs.
broken, and propose ranked updates. Context: the 7/8 reshape decision **kept** dining
("the concierge should remain the broad 'can do it all' layer — staying apprised of
new/hot restaurants, keeping a good-restaurants list, facilitating multi-event plans"),
and the 7/7 audit's F7 said **kill or commit** on the never-ran slices. This review is
the "commit" plan for dining.

---

## 1. The map — where restaurants live and who reads them

**Stores (all committed):**
- `data/dining.json` — 41 records (38 restaurants, 2 bars, 1 bakery, **0 popups**).
  40/41 carry a full `enrichment` block (`why_fits` / `vibe` / `signature` /
  `pairs_with`) — the dining analog of the events scene graph, inline on the record.
- `dining-sources.yaml` — 9 sources. Fetch reality: Infatuation + Resy blog + L.A. TACO
  `ok`; Michelin + OpenTable + LA Mag `search_only`; Eater LA + LA Times + Thrillist
  `blocked` in-env. Tock still `candidate`, never vetted. `last_discovery: 2026-06-17`.
- `dining-taste.yaml` — the explicit food profile (Phase D): affordability policy
  (Bib-over-$$$$ for a normal night), `restaurants_loved` + `favorites_policy`
  (favorites = a read on the palate, not default picks), occasion presets,
  signal weights, and an inline `feedback: []` list.

**Producers (how records get in):**
- **la-dining SKILL** (query / radar / discover / capture) — entirely LLM-at-run-time:
  WebFetch/search harvest of roundup articles → merge signals onto records → rank
  against `dining-taste.yaml`. No Python fetcher, no tested merge/dedupe/score code —
  the SKILL prose *is* the pipeline.
- **Weekly radar routine** (`routines/dining-radar-prompt.md`) — the intended refresh
  cadence. See finding F1.

**Consumers:**
- **night-planner agent** — the hero path. Reads `dining.json` + `dining-taste.yaml`
  for the dinner slot; leans on `enrichment` (`why_fits` = the gloss, `pairs_with` =
  the cross-domain hook); `scripts/travel.py` augments the geo gazetteer with
  restaurant→neighborhood from `dining.json`, so restaurants resolve in travel timing.
- **concierge SKILL** — reads `dining-taste.yaml` up front, routes dining asks to
  la-dining, plan asks to night-planner; honors dietary/banned/affordability.
- **`build_dashboard.py`** (`scripts/build_dashboard.py:179`) — passes a **trimmed**
  dining list into every profile feed: name/type/cuisine/neighborhood/price/occasion/
  reservation/notes. **Drops `enrichment` and `signals` entirely.** Unranked
  (catalog order).
- **concierge Worker** (`backend/concierge-worker.js:502`) — grounds chat on
  `feed.dining` (sent whole) for answer/recommend/plan.
- **dashboard local engine** (`dashboard/index.html:2571`) — dining/plan intent regex →
  `composeDiningReply` / `composePlanReply` (dinner + show + afters from the feed),
  plus the night-planner hand-off prompt.

The **design** is coherent: restaurants-as-persistent-entities with stacking editorial
signals, one taste file, one catalog, three consumption surfaces. The **operation** is
where it breaks down.

---

## 2. Findings

### F1 — The refresh loop has never run; "trending" is frozen at seed time
Zero `digests/dining-*.md` have ever existed. `data/dining.json`: every `last_seen` is
2026-06-16/17, and **all 44 signals date from the two seeding days**. A month on, the
"stay apprised of new/hot restaurants" promise is serving June's hot lists. This
compounds: ranking is defined as *signal count × recency × prestige*, and the
night-planner is instructed to "lead with newer + well-recommended spots" — with a
frozen catalog both silently degrade into re-serving the seed set, which is exactly
what `favorites_policy` was written to prevent.

### F2 — The best data never reaches the dashboard/Worker
`build_dashboard.py` strips `enrichment` (the insider gloss on 40/41 records) and
`signals` (provenance + recency — the core ranking input) from the dining passthrough.
So the Worker plans dinner from name/hood/price/cuisine/notes, and the page's
`composeDiningReply` shows raw `notes` instead of `why_fits`. The catalog is 41 records
and "sent whole" to the Worker anyway — trimming away the two richest fields saves
nothing and costs the voice.

### F3 — No ranking exists anywhere in code
"Score = signal strength + taste/occasion/location fit" lives only in SKILL prose. The
feed passthrough is catalog-ordered; the Worker and the local engine pick from an
unranked list. At 41 records this is survivable; after the radar starts appending
weekly it won't be, and the Worker's send-it-whole grounding will want a cap — which
requires an order.

### F4 — Dining reactions have no capture path
Events have `log_feedback.py` → `data/feedback.jsonl` → `lib/feedback.py` → affinity,
fed by the concierge's path 1. Dining has an inline `feedback: []` in
`dining-taste.yaml` that **nothing writes and nothing reads** — `log_feedback.py`
accepts only artists/genres, and the concierge's three capture paths are all
events-shaped. "Learns from reactions over time" (the file's own header) is currently
unimplementable: a "Santo was perfect" / "too far" / "never again" has nowhere to go.

### F5 — All mechanics are LLM-by-hand — the pattern Phase A retired for events
Merge/dedupe ("name similarity high + same neighborhood"), signal appending,
`last_seen` refresh, popup expiry: all executed by Claude editing JSON per prose spec.
This is the exact "non-deterministic, slow, token-heavy" loop the events side replaced
with tested `scripts/lib/` code. Popup expiry is moot today (0 popups) but structural.

### F6 — The popup/truck lane is schema-only
Capture mode, the `popup` block, `location_tba` handling, the manual-source entry — all
built; zero popups ever captured. Same root cause as the events-side Gmail/SMS gaps
(the intake lanes never went live). Either a capture lane gets exercised or the radar
should stop promising a "Popups & trucks" section it can never fill.

### F7 — Doc + registry drift
`docs/PIPELINE.md` — the orchestration map — contains **zero** mention of dining: no
radar cadence, no passthrough, no cost gate. `last_discovery` is 29 days stale against
the SKILL's own "suggest Discover at 7+ days." The radar routine still says "email the
radar body to Ari" although email was dropped project-wide for the hosted page.

### F8 — Per-profile dining doesn't exist (flag, not necessarily a bug)
Friends get their own events taste/Spotify/verdicts/digests, but every profile's feed
carries the same owner-flavored dining list, and `group_picks.py` is events-only — a
group *dinner* has no taste-matrix support. Probably correct scope for now ("not a
venture"), but it's an asymmetry worth a conscious decision, especially since the
Worker grounds every friend's chat on Ari's `restaurants_loved`-shaped catalog.

---

## 3. Proposals (ranked)

### P0 — Turn the refresh loop on (commit, per the audit)
1. **Schedule the weekly radar for real** and run it once now. First run: harvest the
   `ok`/`search_only` sources, append fresh signals, refresh `last_seen`, write the
   first `digests/dining-YYYY-MM-DD.md`, note the Eater/LAT/Thrillist gap in the
   footer. This single act un-freezes F1 and finally answers open decision **D1**
   (cadence/format/tone) with a real artifact instead of a spec.
   Update the routine prompt: drop the email step (deliver = commit + dashboard, same
   as events), keep the ~12-fetch budget.
2. **Signal decay in presentation**: when surfacing "trending," treat signals older
   than ~60–90 days as lapsed provenance ("was on the June Hit List"), not current
   buzz. Costs nothing once recency is honored (P1.4 makes it mechanical).

### P1 — Cheap plumbing with immediate quality payoff
3. **Fix the passthrough** (`build_dashboard.py`): include `enrichment.why_fits`,
   `vibe`, `signature`, `signals` (label + date, latest 3), and `reservations.difficulty`.
   Have `composeDiningReply` and the Worker grounding prefer `why_fits` over `notes`.
   ~20 lines; the Worker and the page instantly speak with the insider gloss they
   already paid for.
4. **A deterministic `dining_rank`** (small function, `scripts/lib/dining.py`):
   recency-weighted signal score (weights from `dining-taste.yaml.signal_weights`) +
   favorites nudge per `favorites_policy` + eastside proximity tiebreak. Stamp it on
   the passthrough, sort by it, and let the Worker cap grounding when the catalog
   grows. This is the tested implementation of the score the SKILL already specifies —
   scoring-drift prevention, same argument as Phase A.
5. **Unify dining feedback into the one loop**: extend `log_feedback.py` with
   `--restaurants` (same kinds: loved/went/skipped/hide), same `data/feedback.jsonl`.
   A tiny folder surfaces restaurant reactions to the query/planner (hide = hard
   filter, loved = favorites-tier nudge) and the concierge's path 1 covers dining
   asks. Retire the dead inline `feedback: []` in `dining-taste.yaml`. Append-only,
   reversible, consistent with events.
6. **Move merge/dedupe/expire into `lib/dining.py` + tests**: normalize-name+
   neighborhood key, signal append (keep all provenance), `last_seen` refresh, popup
   expiry. The radar routine calls it instead of hand-editing JSON. Note: this is
   *dining's* Phase-A discipline, not new events-pipeline sophistication — it doesn't
   violate the "factory pauses" rule, but flagging it since that call is Ari's.

### P2 — Coverage and surface
7. **Run Discover** (29 days overdue): vet Tock; re-test the blocked tier (network
   policy may have changed since 6/17); obvious candidates to vet — LAist Food,
   KCRW Good Food, Smorgasburg LA (the popup/truck anchor, which would also give F6 a
   real feed), neighborhood newsletters. Proposals only, per convention.
8. **A "good-restaurants list" surface on the dashboard** — Ari asked for exactly this
   in the 7/8 decision. A simple dining view over the feed (filter by neighborhood /
   occasion / price, `why_fits` + booking link per row) makes the list *visible*
   instead of chat-only. Front-end work during Track B, so decision-sized — but it's
   the most direct answer to "keeping a good-restaurants list."
9. **Document dining in `docs/PIPELINE.md`**: radar cadence, the passthrough, the
   freshness story, cost gate (radar is LLM-driven; weekly + ~12 fetches is the gate).

### Explicitly not proposed
- Deeper Resy/OpenTable availability automation (D3) — widgets don't render headless;
  the "state difficulty + link, set a Notify" pattern is honest and cheap. Keep.
- Per-profile dining taste files — defer until a friend actually asks about food
  (F8 decision below).
- Events-style structured fetchers for dining editorial — the sources are listicle
  HTML, the LLM harvest *is* the right tool; only the mechanics around it should be
  deterministic.

---

## 4. Decisions for Ari
1. **Radar go-live** (P0.1): weekly Wed, commit + dashboard delivery, no email — OK?
2. **`lib/dining.py`** (P1.4/P1.6): fine to build during the factory pause, or wait
   for Track B to land?
3. **Dashboard dining view** (P2.8): want it now (it touches the Track-B-era front
   end), or after Track B?
4. **F8**: keep dining owner-flavored for all profiles for now?
5. **F6**: commit to a popup lane (Smorgasburg source + first captures) or trim the
   "Popups & trucks" radar section until one exists?
