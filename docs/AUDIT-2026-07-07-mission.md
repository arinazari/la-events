# la-events — ground-up mission audit (2026-07-07)

**Question asked:** from the ground up, what is this project trying to accomplish, and does it
— at the most fundamental level — accomplish it? (Surface bugs and feature nits deliberately
out of scope; a second audit will cover those.)

**Method:** 8 parallel subsystem auditors (spec coherence, coverage, ranking, scene
intelligence, experience, learning loop, operations, portability), every finding then
adversarially re-verified by independent agents against the working tree, committed data, git
history, and the live deployment; a completeness critic then forced four gap audits (owner
consumption, factual accuracy of the LLM layers, absolute economics, privacy). ~50 agent
passes, ~900 tool calls. Every number below was measured, not quoted from docs. One finding
was refuted and two demoted in verification (listed at the end); five late verifications were
rate-limited and were spot-checked by hand instead (marked ◇).

---

## The mission, distilled

From ROADMAP's north star: **not** a taste-filtered calendar aggregator — a **taste-native
scene concierge** that (a) understands LA's underground as a *graph* of
artists/labels/promoters/venues, (b) explains every pick like a knowledgeable friend, and
(c) plans the whole night. "Private events + dining concierge for Ari and friends — not a
venture." Broken into testable promises:

| # | Promise | Verdict |
|---|---|---|
| P1 | Aggregates LA broadly & reliably into one deduped catalog | **partial** — strong core, dead lanes |
| P2 | Taste-native ranking (deterministic + Spotify + feedback + LLM editor, per-friend) | **partial** — strong |
| P3 | Scene intelligence: accumulating graph, every pick explained | **partial** — voice proven, graph & coverage not |
| P4 | One conversational, opinionated daily digest in the insider voice | **partial** — the flagship doc ships without its product layer |
| P5 | Whole-night planning (dinner → show → afters) | **not built in practice** — real code, zero nights ever planned |
| P6 | Coverage grows over time (discover → approve → registry) | **accomplished** |
| P7 | The system learns from reactions | **partial** — self-edit real; reaction loop has never received one signal |
| P8 | Serves friends + city portability | **structural gap** — friends get a degraded shadow; Berlin is not one config file away |
| P9 | Runs itself, cost-bounded, degrades gracefully | **partial** — cost gates proven; "runs itself" was 3 days old at audit |

**Overall verdict: the plumbing thesis is proven; the product thesis is half-proven — and the
half that's missing is the half the north star says is the product.** The deterministic
core, the cost-gated LLM tiering, discovery, and the multi-profile machinery are genuinely
excellent and verified working in production. But the flagship daily artifact is structurally
the "taste-filtered calendar" the mission disclaims, the system cannot tell whether its one
intended reader reads it, the insider facts it ships are unverifiable-by-design once written,
and the first word of the mission — *private* — is currently false for the friends layer.

---

## What fundamentally works (verified)

These are not participation trophies; each was independently re-verified against committed
data or the live deployment.

1. **The tiered execution architecture works exactly as specced, and the cost gates are
   real.** Verdict deltas across committed runs: 607→263→62→52/day against a 1,035-verdict
   store (commit 504a547's "52 judged" matches the store diff exactly); enrichment is
   write-once with prune (1,478 events / 189 artists); `digest_gate` SKIP observed in
   production (Lori's 7/6 stamp). Steady-state LLM burn reconstructs to roughly **$3–8/day at
   API list** — P9's "cost bounded" survives an absolute test.

2. **The editor layer is genuine judgment, not theater.** 1,035 verdicts: tier decoupled from
   score (28 skips scored ≥6), adjusts spread −3..+3 with only 25% at zero, whys that catch
   what the heuristic can't (string-match false positives, duplicate feed pairs, mis-lanes).
   And it's load-bearing: `assemble.py` makes tier the primary slate sort key.

3. **The insider voice is real and mostly earned.** The first ground-truth accuracy check
   ever run on this repo: 24/26 randomly sampled enrichment notes fully correct against
   primary sources — including deep cuts with no room for bluffing (Halo Varga's
   fabric-first-resident claim, B Wade's verbatim tagline, Doc Martin/Sublevel). The verdict
   layer went 15/15 and actively *corrects* upstream data errors. The per-profile digests
   ("Faited runs sound for Eris Drew's crew") are exactly the promised register.

4. **Near-term underground coverage is depth, not garnish.** Next 14 days: 44.5% of events
   from RA/19hz/DICE/Posh/EB, 132 afterhours-flagged, 107 TBA-location records, 273 distinct
   underground venues of which 257 never appear in a TM record. Dedupe is measurably clean:
   86 cross-source merges, only 3 surviving dups (all TBA-venue string cases).

5. **Spotify is live for the owner and provably changes committed output.** 181-artist layer
   on the default feed; 54 events carry explicit "+N Spotify" reasons; editor verdicts cite
   rotation facts that exist nowhere in taste.yaml.

6. **Discovery converts to coverage** (P6, the one clean "accomplished"): registry ~65→88
   sources with dated passes, and conversions that show up as catalog rows (Veezi unlock →
   Vista 45 + New Bev 43 rows; DICE adds; EB organizer harvest with a CI landing fix).

7. **The friend self-edit loop is closed and actually used** — the best consumption evidence
   in the repo: 5 structured taste/profile edits by 3 friends in 12 days, each landing as a
   commit and re-ranking the feed within minutes.

8. **Failures get durable engineering, not patches.** Each of the 6 operational incidents
   produced a structural fix (land-digest.yml fast-forward gate, the subagent fan-out note,
   the self_edit healing).

9. **Two-speed horizon is on** — ROADMAP's "turn it on" checkbox is stale in your favor:
   `--days 120 --far-days 180` runs nightly; catalog reaches 2027-01-01. The Alanis-class
   miss is structurally fixed *for Ticketmaster-rails announcements* (see finding F5 for the
   catch).

---

## Foundational findings

### F1. The flagship digest ships without its product layer — no component owns the insider voice on the primary artifact
The nightly pipeline renders `digests/latest.md` (the ONE daily doc) straight from the
deterministic scaffold and stops. Measured on 7/6: 413 lines, 160 event rows, **20% carry any
why/gloss** (36% of even the ⭐ top picks), no intro, no Don't-miss, no Around-town — while
`digest.yaml` explicitly requests `[dont_miss, day_by_day, around_town, radar]`.
`render_digest.py:415` *disclaims* the job ("shape the LLM digest layer, not this scaffold"),
a test asserts Don't-miss is absent by design, and the routine's step 5 pointer to "the LLM
digest layer in step 9" lands on the commit step. PIPELINE.md budgets a "consolidated
narrative intro — small, every run" that does not exist in any committed artifact. The one
document that fully delivers the promise is the hand-written pre-automation
`digests/2026-06-19.md` — proof the target is reachable, and proof the automated path never
picked it up. Meanwhile the *per-profile* digests (routine step 8) DO get the narrative pass
— the product layer exists, it just skips the flagship. **This is the mission's central
promise (P4) structurally unowned in the automated path: what ships daily is, by the north
star's own definition, the taste-filtered calendar aggregator this project says it is not.**

### F2. There is zero evidence anyone consumes the product — and consumption is unobservable by design
Since the 6/25 import: 0 reactions ever (`data/feedback.jsonl` is 8 comment lines — no signal
from *anyone*, owner or friends, in the system's entire life), 0 owner taste edits, 0 ad-hoc
digests, 0 dining queries, 0 night-planner itineraries or .ics files, 0 flyer captures, 0
owner-initiated profile rebuilds. Delivery is pull-only (email deliberately dropped), there
is no beacon/analytics anywhere, and the Worker chat leaves no repo trace — so the repo
*cannot* answer "does Ari read this." Ari's traceable post-import activity is 100%
builder-shaped (PR merges, CI fixes, manual dispatches) with exactly one consumer-shaped act
(the Spotify connect). ◇ The learning flywheel (P7) is a complete, tested pipeline with zero
lifetime input — the ROADMAP's own unchecked "Like → learn taste" TODO is the missing
emitter. **A concierge nobody measurably talks to, with a taste-learning loop that has never
received a signal, is not yet accomplishing "an insider made this for me" — it's
accomplishing "an insider is ready, in case anyone shows up." The cheapest fix in the repo:
one reaction link in the digest header hitting the existing Worker commit path would create
the first read-receipt and the first feedback record in one stroke.**

### F3. The trust architecture cannot catch its own confident errors — and wrong facts are permanent and replicated
The verification gate is inverted relative to risk: scene-researcher is told "use your own
knowledge first; web-verify only names you don't actually know" — which routes the
maximum-risk mid-fame band (where LLM memory confidently fails) *around* verification — and
event-editor is told cached notes are "verified — don't re-research." Measured: all 3
confirmed false notes (Jayda G's fabricated real name "Jacinda Gulley"; VTSS's invented
"Bicep's Fabric label, T4T LUV NRG co-founder" — stamped `confidence: high`; Demuir's
misattributed award) are mid-fame artists the model "knew"; every deep-cut that forced web
research verified flawless. Sampled error rate ~8% of prose notes (2/26 random + targeted
finds; wide CI, but nonzero and maximally confident in form ◇). Then permanence: artist-cache
writes are *unconditionally* write-once (`enrich.py:236-238` — even the `refresh_days` escape
hatch couldn't fix a bio), 0 corrections across all 6 committed generations of
`enrichment.json`, the false notes ship in all 9 dashboard feeds, and CI runs zero tests of
any kind — no deterministic suite, no output evals. **The product's signature move is the
confident insider fact. Roughly 30 of the 399 committed prose notes likely carry a false one
today, the count grows every run, and nothing in the architecture can notice, flag, or fix
one. For a product whose entire value is "trust the friend who knows the scene," this is the
deepest gap in the repo.**

### F4. "Private" is currently false for the friends layer — live-demonstrated
The mission's first word fails at the architecture level, not as a config oversight.
Demonstrated end-to-end against the live deployment during this audit: public salt
(`la-events/v1:`, hardcoded in the public repo and dashboard JS) + a friend's first name →
16-hex hash → `https://arinazari.github.io/la-events/data.<hash>.json` returns, with zero
auth, that friend's full authored taste narrative (Lori: 4,892 chars) **plus home
neighborhood, named cross-streets, and lat/lon** (Glendale, Brand & Broadway, 34.1469,
-118.2554 — same for Ari, Raffi, Taylor, Dr. Ganesan). The per-hash digest is equally public
(verified 200 during this audit) and is a *named psychographic dossier* ("Lori's LA Events
Digest … Taste: ethnomusicologist ear …"). The one documented safeguard — "swap the username
for something non-obvious" — is void because the username list and the salt live in the same
public repo. ◇ Separately (confirmed in code): any bring-your-own-key caller can commit to
any profile's taste/profile files — including root `taste.yaml` by supplying the derivable
owner hash — via Ari's PAT; the Worker comments call this an accepted tradeoff, but it was
accepted before the "repo is public + salt is public" combination made hashes free to mint.
Genuine containment exists exactly where it matters most: raw Spotify/feedback data is
gitignored and never published. **Either the feeds/digests need real access control (private
repo + auth, or per-friend tokens), or the friends need to have consented to being publicly
profiled with their cross-streets. Today neither is true.**

### F5. Beyond ~3 weeks, the catalog is structurally a Ticketmaster mirror
71.2% of the catalog is TM overall — and past 60 days out it's **94.6%** TM (1,284 of 1,357
events; 45 RA rows are the entire far underground). Root cause is mechanical, not editorial:
`run_digest.py` passes `args: []` for 19hz, DICE, Goldenvoice, Posh, and Eventbrite, so the
routine's `--days 120` never reaches them and they run on their own 14–21-day defaults (19hz
maxes at 13 days out in the catalog while its own listing page carries months-ahead events).
Only TM gets the 180-day far horizon. **The plan-ahead tier the digest and radar sell — the
"weekends ahead" and "on the radar" sections — is mainstream-only by construction. The
underground scene concierge goes blind past three weeks precisely where the mission says it
should see.**

### F6. The insider layer is hardwired to Ari inside shared components — friends' "personalization" is real at the scoring layer, Ari-flavored at the voice layer
`scene-researcher.md:29-32` ("Internalize the lane: house/techno/tech-house…"), `:87`
("Annotate the names *Ari* likely won't know"), and `event-editor.md:41` (same lane) hardcode
Ari's taste into agents that run per-profile. The shared enrichment cache stores
Ari-taste-voiced curator notes (PIPELINE itself classifies them "taste-voiced" and excludes
them from the editor's neutral block) — yet they fold into every friend feed. Smoking gun in
a committed artifact: Lori's 7/6 digest opened "no strong **Ari-shaped** fits before July
10"; Demo is registered "indie + jazz" but got a digest intro about house/groove afters.
Where a profile is fully built the scoring layer genuinely diverges (Lori vs Ari: 12/21
verdicts differ in taste-correct directions) — the deterministic half of P8 works; the
curation half leaks Ari everywhere.

### F7. Whole slices of the promised system have never once run
- **Dining radar:** documented as a weekly Wednesday routine in both CLAUDE.md and ROADMAP's
  cadence table; zero `digests/dining-*.md` have ever existed; `data/dining.json` frozen at
  41 records since import. The "events + dining concierge" is events-only in practice.
- **Night-planner (P5):** real, runnable code (travel.py verified by execution) — and zero
  itineraries, zero .ics, zero group_picks outputs in the entire history. The hero feature
  has never happened.
- **Insider capture lanes:** Gmail promoter blasts, IG flyer capture, and SMS intake — the
  channels sources.yaml itself calls the afterhours backbone, the thing a scene concierge has
  that a scraper doesn't — have contributed **1 event ever** (hand-typed, and it was the
  patched Daisy-Chain miss). Gmail label: still unjoined (Phase 1's last unchecked box);
  `data/inbox.jsonl`: never created; 15 active `scrape` sources: no fetcher, zero rows.

### F8. "Runs itself" had a 3-day track record at audit time, and the run-rate is owner-hours, not dollars
The daily digest landed on main **4 of its first 12 days** (7/01, 7/04–06); both failure
modes were silent (the Routine hanging on an interactive Workflow-tool approval 6/26–6/30;
runs stranding on claude/* branches 7/01–7/03). 12 intervention commits across 6 incidents in
12 days (TM UTC date-roll corrupting 1,353 rows, stale-deploy clobber, self_edit corruption
healed three times, the hang, the stranding, stranded harvests) — roughly 2–3.5 owner-hours a
week of babysitting, against a dollar burn that's fine. The sole scheduler is one external
claude.ai Routine with no missed-run alarm — the system fails silent, and the owner is the
monitoring. Each incident did produce a durable fix, and 7/04–7/07 ran clean — the trajectory
is right; the maturity is a week old. Standing chore: Posh JWT recapture (~9 days left).

---

## Significant findings

- **The scene "graph" is a flat cache, and its compounding is thin so far.** No
  label/promoter/venue entities or edges exist — two flat dicts (events, artists). Of 189
  cached artists, 36 match ≥2 live events (real reuse); 3.1% of catalog events get a cached
  bio folded in; the single most-reused artist ("drama", 7 hits) is 6/7 a title-substring
  false positive (the duo DRAMA's bio attached to a play called "The Drama" — shipping in
  feeds now). Growth is decelerating (83→15→14→0 new artists/run). The voice is proven; the
  accumulating moat the ROADMAP promises is mostly not built.
- **The confidence channel can't represent the errors it exists to flag** ◇: confidence is
  per-event only; artist bios — where 100% of observed errors live — have no confidence field
  at all, and the one event carrying two false claims is stamped `high`.
- **The webfetch/editorial "layer at digest time" lane is unreliable plumbing:** registered
  since 6/16, first real rows 7/4, 6 of 11 active venues covered, and its first big pass
  wrote 118 records that violate the catalog schema (`source` string instead of `sources`
  list, no `links`). Editorial signals: 2 events of 3,379. The two close-to-home venues
  flagged in sources.yaml (Dresden, Harvard & Stone) still have 0 rows.
- **City portability is one config file deep with an LA body:** `profile.yaml`'s
  `city:`/`timezone:` keys are read by **zero code**; `America/Los_Angeles` is hardcoded in
  scoring, pipeline window math, and 7 fetchers; TM's knob is `dmaId` (US-only — cannot
  express Berlin); geo constants, "# LA Events", the 88/88-LA source registry, the dining
  catalog, and the scene graph are all LA-baked. "Berlin next week → same magic" is not
  achievable by the swap-a-file mechanism as designed; honest scope is "portable scoring,
  not portable product" — or plan the real work.
- **Friend experience is a degraded shadow where it counts:** friend verdict stores froze
  6/23–6/25 (Lori: 2 of 3,379 events judged vs Ari's ~700, until her 7/6 edit re-triggered),
  zero friends have connected Spotify, 4 of 7 friend profiles were empty shells at audit,
  and "+1 close to Silver Lake" reasons appear on 1,107 events in Glendale-based Lori's feed.
- **Worker spend defaults are luxury-tier with an open-proxy failure mode** ◇ (spot-checked;
  one auditor claim corrected — prompt caching IS enabled): every chat runs Sonnet at
  `effort: max` with an Opus 4.8 advisor bolted on by default, and if `CONCIERGE_TOKEN` is
  unset the proxy is open to anyone who finds the URL, on Ari's key. Fine at today's ~zero
  volume; structurally uncapped.

## Refuted / demoted in verification (kept for honesty)

- **Refuted:** "every editor-schema change forces a costly full-catalog re-judge, twice in 4
  days" — the two spike days weren't schema-driven; `EDITOR_INPUT_VERSION` changed exactly
  once ever, and the 7/01 spike was the initial backlog.
- **Demoted to the surface-level audit:** ROADMAP is 12 days stale and self-contradictory
  (says Phase E is "pending merge" — it's live on main; says Spotify needs go-live — it's
  running); the "non-obvious usernames" safeguard note (subsumed by F4).

---

## What follows (mission-level sequencing, not a feature list)

1. **Answer "is anyone reading this?" first** — one reaction/👍 link in every digest header,
   through the existing Worker commit path, into `feedback.jsonl`. First read-receipt and
   first learning signal in one stroke. If the answer stays no after a few weeks, that fact
   should re-sequence everything else here.
2. **Give the flagship digest its Tier-3 owner.** The routine already pays for per-profile
   narratives; the consolidated doc needs the same pass (`digest.yaml` already specifies the
   sections; `2026-06-19.md` is the target voice). This closes the gap between what ships
   and the north star's definition of the product.
3. **Fix the trust architecture:** invert the verification polarity (verify mid-fame names
   *especially*), add per-claim/per-artist confidence, make the cache correctable (a periodic
   fact-janitor pass over the artist bios is cheap — 189 entries), and put at least the
   deterministic test suite in CI.
4. **Decide what "private" means, then make it true:** private repo + authenticated Pages, or
   per-friend tokens — or explicit friend consent to public dossiers. Also bind the Worker's
   edit path to an identity, not a caller-supplied hash.
5. **Un-clip the underground horizon:** pass `--days` through to 19hz/DICE/Posh/GV/EB in
   `run_digest.py` (one-line-per-fetcher class of change; deterministic, no LLM cost).
6. **Kill or commit on the never-ran slices:** dining radar, night-planner-in-anger, Gmail
   label, flyer/SMS capture. Each is either wired into real cadence or struck from the
   mission docs — a spec that promises what never runs erodes the rest of its own credibility.

---

*Audit run 2026-07-07 on main @ 9b65bd1, branch `claude/project-audit-mission-goals-ootdz6`.
◇ = adversarial re-verification was rate-limited; claim spot-checked by hand or carried on
the original auditor's cited evidence.*
