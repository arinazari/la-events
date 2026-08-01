# Assessment — revamping ranking/enrichment with machine learning (2026-08-01)

Ari's ask: *"Revamping the whole ranking/enrichment algorithm to be done by machine learning.
What would break/need to be updated, how would it affect user/admin experience, and costs?"*

This is the impact analysis, not an implementation plan. Numbers below were measured on the
live repo on 2026-08-01 (catalog @ 3,855) unless marked as estimates. Verdict: **a wholesale
ML replacement is the wrong move today — the binding constraint is training data (8 explicit
reactions), the biggest costs are generative and can't be ML'd away, and it would reverse the
Track B decision that just shipped. A staged hybrid (learn the weights under the LLM judge,
distill the judge for pre-screening) captures most of the upside at a fraction of the
breakage.** Details and the staged path at the end.

---

## 1. What "the ranking/enrichment algorithm" actually is

Three distinct layers — an ML revamp means something different for each:

| Layer | What it does | Mechanism | ML-replaceable? |
|---|---|---|---|
| **Deterministic score** | coarse filter + tiebreak (demoted by Track B) | `lib/scoring.score_event`: hand-set weights over interpretable features (category, tracked artists, venue, terms, geo, day, Spotify/feedback affinity) → `score` + human-readable `reasons[]` | Yes — this is the classic learning-to-rank shape |
| **Editor verdicts** (Tier 1) | THE ranker since Track B | `event-editor` LLM judges every surfaceable event → `{tier, lane?, adjust, why, confidence}`, cached per profile in `data/verdicts/` (3,810 cached; delta-only ~50/day) | Partially — tier/lane/adjust are predictable labels; **`why` is not** (generative, rendered verbatim) |
| **Enrichment** (Tiers 1–2) + voice (Tier 3) | scene intelligence + prose | `scene-researcher` (web research → artist notes, curator notes), `blurb-writer` (one-liners), Tier-3 intro/whys/take, per-profile narratives | **No** — this is text generation + web research. Classical ML has no output here; "ML for enrichment" can only mean cheaper LLMs or caching, both already done |

So the real question decomposes into: (a) replace the deterministic scorer with a learned
model, (b) replace/augment the editor with a learned classifier, (c) enrichment stays LLM
regardless. Anyone selling "the whole algorithm becomes ML" is implicitly keeping the LLM
for everything users actually read.

## 2. The data reality — the binding constraint

Supervised taste-learning needs labeled interactions. What exists today:

| Signal | Volume | Usable for |
|---|---|---|
| `data/feedback.jsonl` (owner) | **8 lines** | nothing — two orders of magnitude short |
| Stars (`react` → `feedback.<hash>.jsonl`) | shipped 2026-07-21, trickle so far | the future seed; star→loved already folds into affinity |
| Implicit signals (`clicked_ticket`, `added_calendar`) | **schema exists, emitters never wired** | nothing until wired |
| Spotify affinity (owner) | 190 artists / 39 core | already folded into scoring deterministically; it's a feature, not a label |
| Editor verdicts | **3,810** (62 must-see / 646 great / 1,461 solid / 1,641 skip) | distillation — learning to *mimic the editor*, not Ari |
| Profiles | 10 total; **6 have empty taste.yaml and zero interactions** | cold start is the norm, not the edge case |

Rule of thumb: a linear model over ~20 features wants 150–300 labeled examples to beat
hand-set weights; GBDT/LTR wants thousands. **Personal-taste ML is data-starved for at least
months** even after signal capture is wired. The one dataset that is large enough today
(3,810 verdicts) teaches a model to imitate Sonnet's judgment — its ceiling is the current
editor, it inherits the editor's mistakes, and it goes stale as taste.yaml evolves (verdicts
were judged against past briefs). That's useful for *cost* (pre-screening), not for
*replacing* the judge.

## 3. What breaks — layer by layer

### 3a. Replacing the deterministic scorer with a learned model

The scorer isn't a private function; `score` + `reasons[]` is a contract with ~15 consumers.

**Contract breaks (code that must change):**
- **`reasons[]` disappears** unless the model stays linear/additive. Consumers: the
  dashboard's per-event "why?" expander, the editor record (`editor._RECORD_FIELDS` ships
  score+reasons to the LLM as context), digest debugging. A GBDT gives you SHAP values, not
  "+2 tracked artist (Antal)". Linear model over the existing features keeps reasons
  renderable (`+1.7 learned: rooftop/vinyl`) — this single choice decides most of the blast
  radius.
- **Score-scale calibration is everywhere.** `profile.yaml scoring.rating_thresholds`
  ([8,5],[6,4]…), `assemble.DEFAULT_SLATE.gap: 3` (cliff cut), `RANK_TIER_BONUS` ±6 (blend
  bounds), `editor_pool floor=4`, `slate_fill min_guarantee_score=2`, `render TIER_RATING`
  fallback for unjudged events. A learned score on a different scale silently breaks every
  one; you either anchor the model's output to the current scale or re-derive ~8 knobs.
- **`select_for_verdict` staleness**: a verdict re-judges when `score_at_judge` moves. A
  retrain shifts *every* score → **invalidates all 3,810 verdicts → a full re-judge run**
  (~150 editor batches, ~$25–40 and a very long night) *per retrain* unless staleness is
  redefined (freeze the base score as the drift key, or bucket scores). Must be designed
  around, not discovered.
- **The taste self-edit loop** (the deployed product for friends): concierge → structured
  YAML patch → `build-profiles.yml` re-scores in ~1–2 min → `self_edit` diff + reflected
  badge. All of it assumes *file → deterministic re-score*. An ML model only honors it if
  taste.yaml terms remain the feature vocabulary (learned weights over hand-declared
  features). A model trained purely on behavior makes "track Peggy Gou" a no-op — the flow
  that makes friends' profiles editable dies.
- **Stateless-cloud-run + dependency footprint**: the pipeline is deliberately
  stdlib-only Python today (no requirements.txt, no numpy). ML adds the repo's first real
  dependency (sklearn or lightgbm) across the nightly routine + 6 CI workflows
  (build-profiles, rebuild-profile, refresh-events, deploy, spotify-sync, land-digest), a
  committed model artifact (JSON weights, never pickle), pinned seeds for reproducibility,
  and a training script + eval harness that don't exist.
- **Tests**: ~10 of 32 test files assert exact scoring/slate/render behavior
  (test_scoring, test_assemble, test_render, test_front_page, test_build_profiles,
  test_pipeline, test_editor…). They become fixture-pinned (test against a committed model
  version) or tolerance-based; the "dashboard and digest can never drift" invariant must be
  re-proven.
- Downstream re-scorers that quietly depend on the same function: `build_dashboard`,
  `build_profiles`, `group_picks` (multi-person planning), `night-planner`
  (`run_digest --no-fetch`), `digest_gate` signatures.

### 3b. Replacing the editor with a learned classifier

- **Tier vocabulary is load-bearing product semantics**, not just ordering: front-page
  marquee routing (`build_dashboard.py:249` — must-see/great → "Sets and shows", else FYI),
  judged-skips surfacing *only* in the FYI table (`:368`), digest tier-scaled display
  (full/compact/"Also:" via `TIER_RATING`), `rank_key`'s two-zone sort, `top_picks`
  skip-exclusion. A classifier *can* emit tiers — but errors here aren't a worse sort order,
  they're events landing in the wrong product surface.
- **`why` cannot be learned.** It renders verbatim in digest compact lines, Don't-miss
  shelves, and the dashboard verdict display, and it is the product thesis ("explains every
  pick like a knowledgeable friend"). Killing the editor but keeping whys means keeping an
  LLM pass per surfaced event — which erases most of the claimed savings.
- **The whole cost-gate architecture inverts.** `profile_refresh_gate`, the Update button,
  the nudge popup, `digest_gate`, rebuilt-receipts, the "reflected" badge — all exist
  because the LLM layer is *expensive and gated*. An ML re-rank is free and could run
  nightly for all 10 profiles. That's a genuine architectural simplification — but only
  worth it if the classifier is good, which returns to §2 (it would be trained to mimic the
  editor, per-profile signal doesn't exist yet).
- Retired/rewritten: `merge_verdicts.py`, `EDITOR_INPUT_VERSION` machinery,
  `.claude/agents/event-editor.md`, routine steps 3+8, the committed
  `data/verdicts/<hash>.json` stores, the PIPELINE.md cost ledger.
- Note: the **lane override** is the one editor output that genuinely fits a classifier
  (it's a fact call, not taste — ROADMAP already plans to move lanes into shared
  enrichment). Tier/adjust are taste; lane is classification.

### 3c. Enrichment

Not replaceable by ML — artist notes, curator notes, blurbs, the narrative digest, and the
Tier-3 voice are text generation grounded in web research. The only ML-adjacent upgrades:
embeddings for artist-name matching (a cleaner fix for the FISHER/"Fisher and Thames" class
than the ambiguity lists) and a learned tagger (the deterministic `tagging.py` rules work
and are debuggable; silver-labeling a classifier from them adds opacity for little gain).
Everything else here is already cost-optimized: write-once caches, delta-only selection,
Haiku for the cheap tier.

## 4. User & admin experience impact

**Ari (owner/admin):**
- *Loses (full replacement):* the transparent score spine ("the score stays the transparent
  spine" is a design principle on the dashboard); read-the-reasons debugging; edit-YAML →
  predictable-effect; git-revert-as-rollback for ranking behavior (still works for a model
  artifact, but "revert to last Tuesday's weights" is a blunter tool than reverting a term
  list); stability — every retrain reshuffles the global ranking ("why did everything move
  overnight?" — needs a "ranking model updated" line in What changed).
- *Gains (if signals get wired):* ranking that tracks actual behavior instead of hand
  curation; zero-cost nightly personalization for every profile; weights that stop needing
  hand-tuning (though Track B already demoted hand-tuning — the LLM absorbs that job now).
- *New admin surface:* training/eval scripts, retrain cadence decisions, drift monitoring,
  a dependency stack, and a new failure mode — **silent quality degradation**. A bad
  retrain doesn't throw; it just quietly makes the digest worse. Nothing in the current
  test suite would catch it.

**Friends:**
- *Cold start gets worse, not better.* 6 of 10 profiles have empty taste and zero
  interactions — for them a behavioral model has literally nothing, and the system falls
  back to… the current content-based path. ML changes nothing for the majority of users
  until they generate months of reactions.
- *Self-edit UX regresses* under full replacement: "more techno, less comedy" via the
  concierge currently produces a visible diff and a re-ranked feed in minutes. "The model
  will eventually learn from your stars" is a strictly worse story. (Hybrid keeps this: see
  §6.)
- *One real win:* the free nightly re-rank could give friends verdict-quality *ordering*
  without the Update-button dance — the gate exists only because LLM judging costs money.

**Both:** the insider voice — whys, artist notes, narratives — is untouched or dies. There
is no ML version of it. Any revamp that keeps the product keeps the LLM.

## 5. Costs

### Current LLM spend (steady state, estimated from measured volumes)

Sonnet 5 $3/$15 per MTok (intro $2/$10 through 2026-08-31), Haiku 4.5 $1/$5. Volumes:
~50 new/changed events/day (Track B measurement), 176 full + 1,641 blurb enrichments
accumulated, whys avg 107 chars.

| Line | Est. tokens/day | Est. $/day |
|---|---|---|
| event-editor (delta ~50 events, ~2 batches) | ~60–90k in / ~8k out | $0.30–0.60 |
| scene-researcher (head misses, web-heavy) | ~150–400k in / ~8k out | $0.50–2.00 |
| blurb-writer (Haiku, gaps only) | ~25k in / 4k out | ~$0.05 |
| Tier-3 voice + consolidated + orchestration session | varies w/ caching | $1–3 |
| per-profile passes (gate-REFRESH only) | usually 0 | $0 most nights; ~$0.3–1 per Update |
| **Total** | | **≈ $2–6/day ≈ $60–180/mo** |

(Caveat: the nightly routine runs as a scheduled claude.ai/code session — subscription-side
— while `rebuild-profile.yml` burns the metered `ANTHROPIC_API_KEY`. Token math is the same
either way; whose meter it hits differs.)

### What ML would actually save

- The **only** ranking line ML can cut is the editor's ~$10–20/mo, and only partially
  (pre-screen obvious skips/solids; uncertain events still go to the LLM): **~$5–12/mo**.
- Scene research, blurbs, voice, narratives — the other ~80% of spend — are generative and
  stay. Already delta-gated and write-once cached; there is no ML dividend there.
- ML run cost itself: ~zero (linear/GBDT trains in seconds on CPU in CI). Embeddings, if
  added: Anthropic has no embeddings API, so it's a new vendor (e.g. Voyage) or a local
  model in CI — pennies per month either way, but a new secret + network-allowlist entry +
  supply-chain surface.
- **Build cost is the real cost.** Full replacement: feature pipeline, training + eval
  harness, backtesting, migrating ~15 consumers + ~10 test files, re-calibrating 8 knobs,
  redesigning verdict staleness — realistically 2–4 weeks of focused sessions, high
  regression risk on a system that currently works. Staged hybrid (§6): ~2–3 sessions per
  stage, each independently shippable and revertible.
- Hidden operational cost to design around: retrain → global score shift → 3,810-verdict
  re-judge (~$25–40/retrain) unless staleness is keyed to the frozen base score.

**Net: as a cost project, ML fails on its own terms** — worst case it *adds* cost (re-judge
churn) while saving $10/mo. The only honest motivations are quality (needs data first) and
the free-nightly-personalization architecture win.

## 6. What ML is actually good for here — the staged hybrid

Keeps Track B's thesis (the LLM is the taste judge and the voice; that's the product),
preserves every downstream contract, and lets ML do the two jobs it's genuinely suited for:
learning *weights* from behavior and learning *cheap approximations* of the judge.

- **Stage 0 — wire the signals (prerequisite, no ML).** The 👎/hide affordance (the `/react`
  Worker path already accepts `hide`; the dashboard never sends it), `clicked_ticket` /
  `added_calendar` emitters (schema shipped in Phase C, emitters never built), and keep
  stars flowing. Without this, every ML conversation is theater. Also the only stage that
  improves the *current* system immediately (hide already folds into affinity at −10).
- **Stage 1 — learned weights over the existing features** (once ~150–300 labeled
  interactions exist). Logistic/linear on the exact feature set `score_event` already
  computes; taste.yaml terms stay the feature vocabulary, so the concierge self-edit loop
  keeps working; output stays additive, so `reasons[]` survives verbatim in shape
  ("+1.7 learned: groove/vinyl"); weights ship as committed JSON with graceful fallback to
  hand weights when absent. Byte-level compatibility with every consumer; per-profile
  weights only where that profile has signal.
- **Stage 2 — distill the editor into a pre-screen.** GBDT (or even logistic) on the 3,810
  verdicts predicting skip-vs-surface + a confidence. Uses: (a) don't spend LLM calls
  judging near-certain skips (cuts the editor delta ~40–60%), (b) give the far tail and
  friends' unjudged events a pseudo-tier *ordering* nightly for free, clearly marked as
  provisional — the LLM still judges everything that surfaces, and writes every why.
  Low-confidence → LLM, always.
- **Stage 3 (optional) — embedding similarity as one more feature.** Event text ↔ taste
  narrative / loved-artist centroid; catches semantic matches the keyword terms miss, and
  fixes the ambiguous-name matching class more robustly than the grow-a-list approach.
  Defer until Stages 1–2 prove out; it's the stage that adds an external dependency.

Explicitly rejected: replacing `score_event` wholesale (breaks the self-edit contract and
the transparency spine for ~$0 of savings), replacing the editor (the whys are the product;
tier-routing errors land events in wrong product surfaces), any ML for enrichment
(generative), per-profile models for empty profiles (nothing to learn from).

## 7. Decisions for Ari

1. **What's the actual goal?** Cost → wrong tool (see §5; the savings ceiling is ~$12/mo).
   Quality/personalization → right goal, wrong order: signals first (Stage 0). "It should
   be ML" as architecture taste → flag that this reverses Track B's one-sentence goal
   deliberately, three weeks after shipping it.
2. **Green-light Stage 0?** It's small, improves today's system, and is the prerequisite
   for everything else. (Recommend: yes, immediately.)
3. **Stage 1 scope when data arrives** — shared weights + per-profile deltas (recommended)
   vs. fully per-profile (data-starved for friends).
4. **Retrain/staleness policy** — freeze the hand score as `score_at_judge`'s drift key so
   retrains never trigger mass re-judges (recommended), and a "ranking model updated" line
   in What changed.
5. **Stage 3 vendor** — embeddings mean a new external dependency (no Anthropic embeddings
   API); yes/no can wait.
