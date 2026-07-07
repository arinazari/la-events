# la-events — the step-back product take (companion to the mission audit)

The question this time is broader than "does the code deliver the spec": **as a product — a
website for Ari and friends to find LA events they'll like, delivered digestibly and fun —
is the design right?** Is the recommendation system the right approach? Is the way the
website works the right shape? Answered from the verified evidence in
`AUDIT-2026-07-07-mission.md` plus a first-hand look at the delivered surfaces.

## The take in three sentences

The system is over-built where it doesn't matter and under-built where it does. The
recommender is already better than a 6-person product needs — the real bottlenecks are that
nothing is ever *delivered* (pull-only), no reaction signal exists for any recommender to
learn from, the product is N parallel solo experiences with no group layer, and the site is
too heavy for the phones it will actually be opened on. The thesis itself is validated — the
insider notes at their best are exactly the product — the factory is just running ~4 phases
ahead of the storefront.

---

## 1. Is the recommendation system optimal?

**The right question first: at this scale, what does "optimal" mean?** Six users, zero
interaction history (not one reaction ever logged), ~900 candidate events in a 2-week window.
This is not a machine-learning problem — collaborative filtering is impossible and
unnecessary at N=6. "Optimal" means: ranks like a knowledgeable friend would, cheaply,
predictably, and *improves as people use it*. Judged that way:

**The architecture family is right; the layer allocation is off.** The design — deterministic
spine for cost/stability, LLM editor for judgment — is a good pattern. But measured on the
live catalog, the deterministic layer's points are 58% generic category weights and ~2%
personal taste lists: it is doing the *cost-bounding* job, not the *taste* job. Taste
actually lives in the LLM layers (editor verdicts + Spotify affinity), and the keyword
machinery underneath is a hand-tuned 2010s feature scorer with the failure modes of one —
substring false positives (FISHER the tracked artist matching "Fisher and Thames," a jazz
duo; DRAMA's bio attached to a play called "The Drama"), synonym blindness, and a
`taste.yaml` that only Ari will ever maintain by hand.

**A structural ceiling worth knowing about:** the editor only judges the pool the
deterministic score selects. Anything the keyword scorer buries never reaches the judge — the
smart layer cannot rescue the coarse layer's false negatives. With a coarse first stage,
that's a real recall ceiling, and it bites hardest for friends whose taste the keyword file
describes worst.

**If you were redesigning the middle layer today, you'd use embeddings.** Embed each event
(title + lineup + venue + tags + enrichment) and each person's taste (their taste narrative +
loved/tracked artists + Spotify artists), rank by similarity. That kills the substring bug
class, handles genre/synonym drift natively, is per-friend by construction (a friend's taste
is just *their* vector — no hand-authored keyword file needed, which directly fixes the
4-of-7-empty-profiles cold-start), and costs pennies at this volume. Keep the explicit,
legible knobs as overrides on top — tracked artists, hide/never-show, distance, price — and
keep the LLM editor as the judgment pass. The honest tradeoff: you lose some of the
transparent "+3 house, +1 rooftop" why-math, which is genuinely nice; keeping hard overrides
explicit preserves most of the legibility where it matters.

**But — and this is the actual answer — the algorithm is not the bottleneck.** Any
recommender (keyword, embedding, or LLM) is flying blind here, because the system has never
received a single reaction. The highest-value "recommender improvement" available is not a
model change; it's:
1. **One-tap reactions on every surface** (digest + site): 👍 / 👎 / "more like this" /
   "never" — the pipeline for folding them in already exists and is tested.
2. **A 60-second friend onboarding** — pick 10 artists you love, swipe 15 sample events —
   instead of "describe your taste to a chatbot," which is why 4 of 7 profiles are empty.
3. **A wildcard slot** — one deliberately off-profile pick per digest, labeled as such.
   Pure-exploitation ranking gets stale, "fun" needs surprise, and wildcard reactions are the
   highest-information training signal you can collect.

Do those three and the current scorer is honestly good enough; do none of them and an
embedding swap won't be felt either.

## 2. Is the way the website works fine?

**The biggest product flaw isn't on the website — it's that nothing ever arrives.** Delivery
is pull-only by explicit decision (email dropped, no push, no notifications). That makes
this a habit product competing against Instagram and RA for an unprompted visit — and the
mission audit found zero evidence anyone visits. For a friends-scale product, **push is the
product**: a short digest (5 picks, the voice, one-tap reactions) that lands where the group
already lives — group text or email, weekly on Thursday ("this weekend") beats daily. The
website's right role is the depth surface behind the push, not the front door. The existing
Worker + commit path can carry the reaction links today.

**The site itself is too heavy for its audience.** Opening it downloads a ~4.7 MB JSON (all
3,379 events, enrichment folded in, whole catalog per profile) and a React app that a ~3 MB
vendored Babel transpiles *in the browser* — roughly 8 MB and seconds of parse before first
paint, on phones, over LTE. Fun dies in the load spinner. The fixes are unglamorous and
deterministic: precompile the JSX (the ROADMAP already lists it), split the feed into an
upcoming-2-weeks core (~300 KB) with the tail lazy-loaded, and serve only fields the UI
renders. Also: 9 × ~4.7 MB feeds re-committed daily is a repo-growth clock worth watching.

**The first-name "login" is the right idea with the wrong consequences.** Charming, zero
friction, correct for a friend group — but as deployed it's simultaneously (a) the privacy
hole (public Pages + public salt = anyone can pull a named taste dossier with home
cross-streets; see mission audit F4), and (b) *not enough identity* to attribute a reaction
to a person, which the learning loop needs. One small move — per-friend links carrying a
private token (or a private site) — fixes both at once without adding real login friction.

**The flagship format is inverted.** `digests/latest.md` is a 160-row reading assignment
with the fun 20% scattered through it; the *per-profile* digests (5–8 picks, each with a
personal why, in the voice) are already the right product and prove it. The 5-pick voice
section should be the front door of every surface — site header, push message, digest top —
with the exhaustive day-by-day as the appendix for planners. Same data, opposite emphasis.

## 3. The missing product: the group

This is "for me and my friends," but what's built is N parallel solo experiences. Nobody can
see that Raffi starred Saturday's warehouse party; there is no "I'm going — who's in?"; no
shared shortlist for a weekend. For a friend group, the social loop is simultaneously the
fun, the retention mechanism, and the learning signal (an "I'm going" is a stronger taste
label than any 👍). The single most fun-generating feature this product could add is seeing
each other's intent — and `group_picks.py` already exists, unused. Even a minimal version
(stars visible to the group + a "who's in" count per event) would change what the product
*is*, from a feed to a plan.

## What I'd do, in order

1. **Weekly push digest with one-tap reactions** into the group's existing channel — this is
   delivery + read-receipts + the first learning signal in one move.
2. **Slim the site to phone speed** (precompiled JS, ~300 KB core feed, lazy tail).
3. **Friend onboarding in 60 seconds** (artists + swipes → profile), replacing hand-authored
   taste files as the default path.
4. **Group visibility** — shared stars and "who's in?" on every event.
5. Only then, if ranking still feels off: **swap the keyword middle layer for embeddings**,
   keeping explicit overrides and the LLM editor.

And one restraint: don't build more factory. Coverage, verdict caching, enrichment, CI
choreography are all ahead of the storefront. Every hour on fetchers right now is an hour the
one measurable problem — nobody demonstrably uses it — doesn't get.
