# Shadow-eval: is the per-user event-editor layer factorable?

*2026-08-04 · method: `scripts/eval_verdict_shadow.py` over the 4,484 cached verdicts in
`data/verdicts/`, + LLM classification of all 442 score↔tier disagreements, + three
adversarial verification passes (statistics / product / evidence) that corrected the
first-draft reading. Question under test: can the editor's per-(event×profile) LLM pass be
replaced by a richer taste-neutral per-event card × deterministic taste scoring?*

## Corrected findings

**1. Score and tier agree moderately — the editor is a boundary re-ranker, not an orthogonal
signal.** On the only well-powered store (default/Ari, n=4,103): concordance AUC 0.696
(bootstrap CI 0.684–0.709), tier score-means monotone (2.87 / 4.12 / 4.49 / 5.71),
skip-vs-must-see separation strong (0.83). Disagreement concentrates at adjacent tiers
(solid-vs-great 0.563). Lori's 0.538 should not be cited: 93% of her judged scores are 5–6
(≈45% tied pairs, metric ceiling ~0.78), 22/179 of her verdicts are "past event" hygiene
skips sitting on her highest scores, and the CI spans chance. Sub-100-verdict stores are
noise.

**2. The slate-impact numbers measure the verdict *weight*, not verdict *information*.** A
shuffled-tier null control reshapes the slate MORE than real verdicts (symdiff ~300 vs 224;
top-picks overlap 0–1/6) — because `rank_key` is tier-primary and `RANK_TIER_BONUS` (±6)
dwarfs the score sd (1.66), any tier assignment rearranges everything. Real verdicts move
the slate *less* than random ones precisely because tiers correlate with score. Honest
restatement: within the ~4-week judged window, ~11% of slate picks are replaced
(113/1051 — the earlier 224 double-counted the symmetric diff), ~2/3 of day leads change,
5/6 of the hero changes; beyond the judged horizon the editor is inert. Two-zone
`rank_key` under sparse stale coverage is actively dangerous: Lori's 29 stale judged
events monopolize her top-22 site-wide, and one junk row the editor must-see'd
("Verizon offer – Daisy Chain Fields") became her #1.

**3. What the editor actually knows (census of all 442 disagreements):**

| capturable as | share | meaning |
|---|---|---|
| taste-neutral event fact | **75%** (333) | artist draw/stature (208 whys), venue context (114), lineup quality (81), booking rarity (58) — computable ONCE per event on an ingest-time card |
| pipeline hygiene | **13%** (57) | dupes reaching the editor, past/sold-out rows, junk rows, substring artist false-matches ("Ame"), wrong geocode, mis-laned film/watch-party rows — belongs in deterministic code |
| genuinely per-user judgment | **12%** (52) | irreducible taste-crossing; small enough for a thin, taste-change-gated pass |

Sampled whys check out factually (0 false claims in ~40 audited; artist/label facts trace to
`data/enrichment.json` artist_notes — the non-redundant knowledge lives in the
enrichment+editor stack jointly, not the editor alone). Bounded confabulation exists:
~15% of whys cite features the scorer already priced while still applying a nonzero adjust;
tier and adjust are one signal, not two (r=0.83).

**4. Nothing here measures whether the editor's reshaping is an *improvement*.** Every
metric shows change, not quality. The scoreboard for any restructure step is a join
against `data/feedback.jsonl` reactions (n=35 today, growing).

## Concrete defects surfaced (fix regardless of architecture)

- Scorer: substring artist matching produces phantom affinity bumps ("Ame"); a tracked-artist
  match was missed entirely in at least one case; a stray World Cup penalty and a
  wrong-band Spotify match were caught by the editor.
- Catalog: dupes and repeat-run instances reach judging (~175 default verdicts are
  duplicate/repeat suppression); past events survive into pools ("past event" skips);
  junk rows score 5–7 ("Hollywood Palladium @ Hollywood Palladium").
- Ranking: two-zone `rank_key` + stale sparse verdict coverage lets a small stale judged
  set monopolize a profile's head (Lori), and puts editor errors in the #1 slot.

## Architecture verdict

The bucket discipline survives — pay the LLM once per event-fact (ingest card), once per
sentence (cached whys, delta-only), never per click. The pure trait×taste dot product does
NOT: 12% of editor signal is irreducibly per-user, and the whys' factual grounding is real.

Plan, in order, each step scored against feedback.jsonl before the next:
1. **Hygiene pass** (deterministic): dedupe/expiry/junk/false-match fixes — recovers the
   13% for every profile at zero LLM cost, and cleans the concordance measurement.
2. **Event card**: extend enrichment schema with structured draw/rarity/venue-fit/lineup
   fields; scorer consumes them deterministically — absorbs most of the 75%.
3. **Demote verdict weight**: once cards land, replace tier-primary ranking with a bounded
   bonus (the null control shows current weighting amplifies any judgment, including
   stale/wrong ones); keep a thin top-K editor pass gated on taste change for the 12%.
4. **Digest**: scaffold render + parallel cached why-writers (measured separately:
   6m24s cold, delta-only warm) — already the plan.

## Status (2026-08-05)

All three steps landed on this branch, each measured:
1. **Hygiene** — junk gate extended (upsells/placeholders), accent-folded artist matching,
   editor-pool past/junk guards. Lori's junk #1 died; catalog self-healed.
2. **Event card** — draw/rarity/lineup_depth on shared enrichment, one capped scoring term;
   144 cards backfilled from cached prose. Score↔tier concordance on 130 paired events:
   0.382 → 0.611 (+0.23).
3. **Demotion** — rank_key/effective_key off tier-primary onto the one bounded blend
   (RANK_TIER_BONUS ±6 → +3/-5); editor recall capped top-120 (Lori's pool 1290 → 133).
   Shuffled-tier null control no longer hijacks the shelf (real slate 4/6 stable with no
   verdicts at all); feedback join: loved/starred events improve +3.2 mean percentile,
   negative reactions flat. Remaining: keep scoring against feedback.jsonl as it grows.
