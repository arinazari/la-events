# Track B spec — LLM-first ranking + the product layer (fleshed out, pre-execution)

Status of the parent plan (`PLAN-2026-07-08-reshape.md`), per Ari 7/8: **Track A tabled**,
**Track C dropped** (dining + the broad concierge stay — restaurants/multi-event planning are
wanted features), Track D unchanged. This spec details Track B one level deeper before
implementation. Nothing here touches dining, the concierge Worker, or profiles/auth — B is
purely the events ranking + digest pipeline.

Every number below was measured on the live repo on 2026-07-08 (catalog @ 3,379 events)
by running the actual library code, not estimated.

## The one-sentence goal

Stop letting keyword scores decide what the LLM never sees or never voices: the editor judges
everything surfaceable, its verdicts govern every downstream gate, taste.yaml becomes the
editor's brief, and the flagship digest finally gets its intro / Don't-miss / Around-town
voice layer.

## Current ranking authority (measured, for reference)

```
score_pool (keyword scoring)             1,283 events in the 28-day window
  └─ editor_pool(per_lane=4, floor=4)      618 judged (48%)   ← gate 1: score picks the LLM's input
  └─ select_candidates(top_n=100)          100 enriched       ← gate 2: score picks what gets researched
  └─ blurb pool (35d, below head)          everything ≥0      (already recall-oriented — fine)
  └─ dashboard default sort                score              ← gate 3
  └─ slate (assemble)                      tier-primary — already LLM-first *within* what gate 1 admitted
Lane mix in-window: other 555 · live-music 188 · club:underground 156 · club:afters 151 ·
film 123 · comedy 51 · club:day 40 · workshop 14 · club:mainstream 3 · market 2
```

Note the biggest "lane" is `other` (555 events, 43% of the window) — invisible to the slate
today and mostly unjudged. B4's Around-town section is where the notable slice of it
surfaces; the rest stays database-only, which is correct.

---

## B1 — Recall flip: the editor judges everything surfaceable

**Change.** `lib/editor.editor_pool()` gains an "all" mode: `per_lane=0` (new default in
`run_digest.py:168`) means *every* slate-lane event in the window enters the pool; non-slate
lanes (`other/workshop/community/market`, editor.py:47) keep the existing `floor=4` entry so
market stalls don't get judged. `select_for_verdict` / cache / `EDITOR_INPUT_VERSION`
mechanics are untouched.

**Measured impact (live data, 7/8):**
- pool 618 → **774** events (+156);
- one-time backlog of unjudged events: **154** (≈3 normal days of editor spend; the 7/01 run
  already did 607 in one day without issue);
- steady-state daily delta unchanged (~50/day — new events are new events either way).

**Mechanics for the routine:** nothing changes in `daily-digest-prompt.md` except the first
run fans out ~6 editor batches instead of ~1–2. No `EDITOR_INPUT_VERSION` bump (the record
shape is unchanged), so the 1,035 cached verdicts stay valid.

**Files:** `scripts/lib/editor.py` (editor_pool), `scripts/run_digest.py` (default),
`scripts/tests/test_editor.py` (pool-size expectations).
**Rollback:** revert the default. **Risk:** none material.

## B2 — Authority flip: verdicts govern the three remaining gates

**Gate 1 — enrichment head.** `run_digest.py:228` selects the top-100 by keyword score.
Change: order the head by `assemble.rank_score(ev, verdicts)` using the **on-disk verdict
cache** (`data/verdicts/default.json`), loaded at the top of the run. Wrinkle handled: the
routine emits candidates (step 1–2) *before* this run's judging (step 3), so brand-new events
have no verdict yet — `rank_score` falls back to raw score for them (by construction:
tier bonus 0), they get judged this run, and enter the head correctly next run. Acceptable
one-run lag; genuinely hot new events usually score high enough to make the head anyway.

**Gate 2 — blurb pool.** Defined as "below the head" via `head_keys` (run_digest.py:266), so
it follows gate 1 automatically. Zero code.

**Gate 3 — dashboard default sort.** Default the grid to `final_rank` (already computed and
displayed); the score column stays visible as the transparent spine. One small change in
`dashboard/index.html`'s initial sort state.

**Net effect with B1:** every surfaceable in-window event is judged, the slate's tier-primary
key (`assemble.effective_key`) now governs a fully-judged window, and enrichment researches
what the *editor* rates. "LLM ranks, Python bounces and bookkeeps" becomes literally true.

**Files:** `scripts/run_digest.py`, `scripts/lib/pipeline.py` (`select_candidates` gains a
`verdicts=` arg), `dashboard/index.html` (default sort), tests.

## B3 — taste.yaml becomes the editor's brief + matching hygiene

**Taste as prompt material.** `lib/editor.pool_doc()` gains a `taste_profile` block — the
distilled brief (categories, boosts, penalties, `artists_tracked`, comedians_loved, the
header narrative) embedded in the pool doc, exactly like `profile_affinity` already is. The
editor's input becomes hermetic and identical across owner/friend pools (each already carries
its own affinity; per-profile pools embed that profile's taste). **Deliberately NO
`EDITOR_INPUT_VERSION` bump** — existing verdicts were judged by an agent that Read
taste.yaml anyway; a bump would force a 1,035-verdict re-judge for near-zero delta.
Keyword weights in taste.yaml stay only as the coarse filter + tiebreak; documented as such
in the file header (stop hand-tuning them).

**Matching hygiene — the false-positive class, correctly diagnosed.** The radar already does
whole-token matching (build_radar.py:13), yet FISHER still hit "Fisher and Thames" — because
"Fisher" IS a whole token in that title. Token boundaries can't fix name-vs-word ambiguity;
the lineup can. Three changes, one principle (*title text is a last resort; lineup fields are
the evidence*):
1. `build_radar.radar_signals`: tracked-artist match prefers `lineup` when the event has one;
   title-only matches allowed only for names not on an ambiguity list.
2. Reuse the existing `ambiguous_names` lineup-gate mechanism (built for the Spotify matcher,
   per ROADMAP Phase C) for `artists_tracked` in both radar and the scoring boost — seed it
   with the word-like names (FISHER, Drama, …).
3. `lib/enrich.py:154-158`: the ≥5-char *title-substring* rule that attached the DRAMA duo's
   bio to a play called "The Drama" becomes whole-token + lineup-preferred + same ambiguity
   gate. (This ships wrong bios to feeds today — it's a matching bug, so it rides B3 rather
   than Track D.)

**Files:** `scripts/lib/editor.py`, `scripts/build_radar.py`, `scripts/lib/scoring.py`
(tracked boost), `scripts/lib/enrich.py`, `.claude/agents/event-editor.md` (note the embedded
brief), tests for each matcher.

## B4 — Don't-miss + Around-town + the Tier-3 voice on the flagship

This is the original product concept ("LLM curates my weekend, explains the artists, why I'd
like it") plus the city-pulse goal ("stay apprised — LA Marathon, Kendrick, seasonal
one-offs"), landed on `digests/latest.md`.

**B4a — deterministic scaffolds (render layer).**
- `render_digest.py --consolidated` finally honors `digest.yaml`'s `sections:` list (today
  only `max_picks_per_day` applies — render_digest.py:416):
  - **`dont_miss`**: top 5–7 across the window ordered by (must-see tier, then `rank_score`),
    rendered as date · title · venue · one-line-why slot.
  - **`around_town`**: the city-pulse list — deliberately NOT taste-filtered (see B4b),
    compact one-liners, date-grouped, capped ~12.
- Flip `tests/test_render.py:40` (currently asserts Don't-miss is ABSENT by design) to assert
  presence when configured, absence when a profile's digest.yaml omits it.

**B4b — the notable detector (city-pulse data).** Extend `build_radar.py` with a near-window
mode (`--near 14` → `data/around_town.json`): events in the next 14 days firing ≥1 notable
signal *regardless of taste score*. Signals, reusing what exists:
- `BIG_VENUE` gazetteer hit (Kendrick at Crypto.com — already in build_radar.py:36);
- `FEST_TERMS` / multi-day (River Solstice class — build_radar.py:40);
- `editorial_mentions`;
- a new `CIVIC_TERMS` list (marathon, book fair/festival, county fair, parade, fireworks,
  night market, block party, solstice, museum free day, open house, …) — the LA-Marathon/
  USC-book-fair class, which today dies in the `other` lane with score ~0;
- in-window entries from `festivals.yaml` + `recurring.yaml` (the data already curated for
  exactly this).
De-dup rule: an event already surfaced in the day-by-day slate does NOT repeat in
Around-town — the section is *notable things your taste lanes didn't surface*.

**B4c — the Tier-3 synthesis step (the voice).** New explicit step in
`routines/daily-digest-prompt.md` (replacing the dangling "LLM digest layer in step 9"
pointer): after rendering, the main agent edits `digests/latest.md` in place —
1. a 2–4 sentence **intro** (the week's shape, in the insider voice);
2. the **one-line why** for each Don't-miss item (drawn from verdict whys + enrichment —
   mostly assembly, light rewrite);
3. a gloss on Around-town items only where there's something to say.
**Contract (hard):** the agent fills marked slots (`<!-- dont-miss-why: <event_key> -->`,
`<!-- intro -->`) and may not add, remove, or reorder events — the slate stays deterministic
and diffable. Cost: one LLM pass per run, a few K tokens (PIPELINE.md already budgets exactly
this line item; it just never existed). `digest.yaml`'s `length/tone/emphasis` finally apply
to this step.

**Files:** `scripts/render_digest.py`, `scripts/build_radar.py`, `scripts/tests/test_render.py`,
`routines/daily-digest-prompt.md`, `docs/PIPELINE.md` (row becomes true), `digest.yaml`
(comment: sections now honored).

---

## Order, acceptance, and measurement

**Order:** B1 → B2 → B4 (B3 independent, any time). One PR each; B4 may split (a+b scaffold /
c routine) if review is easier.

**Baseline (captured 7/8, to compare after):** flagship digest = 160 rows, 20% glossed, 36%
of ⭐ picks glossed, 0 intro, 0 Don't-miss, 0 Around-town; 48% of the 28-day window judged.

**Acceptance:**
- ≥95% of the in-window slate carries a verdict (B1);
- enrichment head ordered by `rank_score`; dashboard defaults to final rank (B2);
- zero tracked-artist title false-positives on the current catalog's known cases — FISHER/
  "Fisher and Thames", DRAMA/"The Drama" (B3);
- `digests/latest.md` opens with an intro, a Don't-miss where every item has a why, and an
  Around-town section containing civic/notable events that score ≤ the slate floor (B4);
- steady-state editor cost within ~1.2× of today's after the one-time 154-verdict backlog.

## Decisions for Ari before execution
1. **Don't-miss size** (recommend 6) and **Around-town cap** (recommend 12).
2. Seed terms for `CIVIC_TERMS` — anything you want beyond the list in B4b.
3. Confirm **no `EDITOR_INPUT_VERSION` bump** in B3 (recommend: don't — avoids a 1,035-verdict
   re-judge for near-zero benefit).
4. Green-light the **154-verdict one-time backlog** (B1).
