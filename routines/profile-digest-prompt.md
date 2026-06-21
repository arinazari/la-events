# Routine: on-demand per-profile LLM digest refresh

Prompt for the **rebuild-profile** workflow (`.github/workflows/rebuild-profile.yml`), which a user
triggers from the dashboard's **"Update my ranking & digest"** button (→ concierge Worker →
`repository_dispatch` "rebuild-profile"). It re-runs the *LLM* ranking + digest pass — the
event-editor verdicts and the personalized narrative — for ONE profile against the latest catalog,
so a user gets the full editor treatment on demand instead of waiting for the nightly routine.

Scope is a single profile, identified by its **feed hash** `<HASH>` (the name of its
`dashboard/data.<hash>.json`; the page only knows the hash, never the username). This is the
single-profile slice of `routines/daily-digest-prompt.md` steps 3–9 — read that for the full
contract; this file is the scoped version.

> The workflow has already (a) synced this profile's Spotify into `data/spotify/<HASH>.json` if it's
> connected, and (b) made the catalog + `data/catalog_meta.json` current. You start from there.
> **Do NOT `git commit` or `git push`** — leave every changed file in the working tree; the workflow
> commits and deploys. Degrade gracefully: if a step has nothing to do, skip it; never block the run.

Run, for the profile feed hash `<HASH>`:

1. **Score the feed + emit its editor pool.** `python scripts/build_profiles.py --only-hash <HASH>`.
   This writes `dashboard/data.<HASH>.json` (scored against this profile's own taste + music layer,
   folding any existing `data/verdicts/<HASH>.json`) and its judging pool `data/editor_pool.<HASH>.json`.

2. **Judge the ranking (event-editor).** Load `data/editor_pool.<HASH>.json`. Select the not-yet-judged
   events with `editor.select_for_verdict` against `data/verdicts/<HASH>.json` (only new / score-drifted
   events cost a call — the cache carries the rest). Fan out the **event-editor** agent (Task tool, in
   parallel batches) over that set, passing this profile's taste; each record already carries the
   deterministic score + reasons + tags + lane, plus its Spotify `affinity_hint` and `profile_affinity`
   when connected. Collect the per-event verdicts (`{tier, lane?, adjust, why, confidence}`) into a
   results JSON and merge: `python scripts/merge_verdicts.py <results.json> --profile-hash <HASH>` →
   `data/verdicts/<HASH>.json`. If nothing needs judging, skip to step 4.

3. **Enrich the top picks (scene-researcher), bounded.** For this profile's top cache-miss candidates
   only (`enrich.select_for_enrichment`, keep it to the top ~20 to bound cost), fan out the
   **scene-researcher** agent → tags, artist notes, curator's notes, descriptions, and images for the
   `image_wanted` picks → fold into the shared `data/enrichment.json` (recurring artists reuse the
   cache; verify-or-omit). Then `python scripts/cache_images.py` (idempotent). Skip if no misses.

4. **Re-score with fresh verdicts.** `python scripts/build_profiles.py --only-hash <HASH>` again, so
   the new verdicts fold into each event's **final rank** in `dashboard/data.<HASH>.json`.

5. **Refresh the radar (best-effort).** `python scripts/build_radar.py` → `data/radar.json` (shared
   far-out festival/big-show set; fine to reuse across profiles).

6. **Write the personalized digest.** Read the rebuilt `dashboard/data.<HASH>.json` (the display name is
   in `feed.profile.name`) and write a concise, conversational, **opinionated** narrative digest to
   `digests/<HASH>/latest.md` (overwrite) — the same LA-insider voice as the consolidated digest, but
   ranked to THIS person: their top picks across the next ~2–3 weeks + weekends ahead, grouped by day,
   a one-line *why* each, ⭐ on the editor's must-sees. If their feed is thin, a couple of honest lines
   is fine — don't pad. This is the file the dashboard's digest modal loads for this profile.

7. **Stop.** Leave the changed files (`dashboard/data.<HASH>.json`, `data/verdicts/<HASH>.json`,
   `data/enrichment.json`, `data/images/`, `digests/<HASH>/latest.md`) in the working tree. The
   workflow commits + redeploys. Do not commit or push yourself.
