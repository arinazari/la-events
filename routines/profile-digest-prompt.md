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
> **The digest is NOT this step's job** (2026-08 render+voice redesign): the workflow renders the
> deterministic scaffold to `digests/<HASH>/latest.md` and runs the voice pass
> (routines/digest-voice-prompt.md) AFTER you finish. Never write that file here.

Run, for the profile feed hash `<HASH>`:

> **Bounded run — finish, don't be exhaustive.** This is one on-demand click, capped at a small turn
> budget AND a hard wall clock: **the workflow kills this step at 10 minutes** (whatever is merged on
> disk by then still gets committed; unfinished work is simply lost). The deterministic feed
> (`dashboard/data.<HASH>.json` + `data/editor_pool.<HASH>.json`) was ALREADY built by the workflow
> before you started, so the ranking is safe even if you do nothing. Your job is the *thin* LLM layer
> + the digest. **Hard caps:** judge at most **24 events total** — from the top ~40 pool events by
> score, the not-yet-judged/stale ones, highest score first — in at most **2 event-editor batches
> launched together in ONE message so they run in parallel**; at most **1 scene-researcher batch**.
> If more than 24 are unjudged or stale (a scoring change or a reaction can re-select a pile of
> already-judged events at once), take the top 24 and leave the rest — **a backlog is the nightly
> routine's job, never this click's.** The deliverable is the VERDICT layer: merge each editor batch
> the moment it returns (step 1) so a mid-run kill keeps the work, then re-score (step 3). If you're
> low on turns or clock, skip enrichment (step 2) — never the merge or the re-score. Never re-fetch
> the catalog or judge the whole backlog.

1. **Judge the top of the ranking (event-editor) — ≤24 events, ≤2 parallel batches.** Load
   `data/editor_pool.<HASH>.json`. Take the **top ~40 by score** and select the not-yet-judged ones
   with `editor.select_for_verdict` against `data/verdicts/<HASH>.json` (the cache carries the rest —
   only new/changed events cost a call). **Cap the selection at 24** (highest score first; the rest
   is the nightly's backlog). Fan the **event-editor** agent (Task tool) over them in **at most 2
   batches, both launched in one message** so they run concurrently; each record carries the
   deterministic score + reasons + tags + lane, plus its Spotify `affinity_hint` / `profile_affinity`
   when connected. Merge each batch as it returns: `python scripts/merge_verdicts.py <results.json>
   --profile-hash <HASH>` → `data/verdicts/<HASH>.json`. If nothing needs judging, skip.

2. **Enrich the very top picks (scene-researcher) — ≤1 batch, optional.** Only the top ~10–12 cache-miss
   candidates (`enrich.select_for_enrichment`): one **scene-researcher** batch → tags, artist notes,
   curator's notes, descriptions → fold into `data/enrichment.json`.
   Skip entirely if there are no misses, the editor selection was already heavy (>12 judged), or
   you're low on turns or clock.

3. **Re-score with fresh verdicts.** `python scripts/build_profiles.py --only-hash <HASH>` again, so the
   new verdicts fold into each event's **final rank** in `dashboard/data.<HASH>.json`.

4. **Refresh the radar (best-effort).** `python scripts/build_radar.py` → `data/radar.json`.

5. **Stop — the digest is not yours.** The workflow's next steps render the deterministic
   scaffold straight to `digests/<HASH>/latest.md` and run the voice pass
   (routines/digest-voice-prompt.md) over it; a digest ships even if every LLM step dies.
   Leave the changed files (`dashboard/data.<HASH>.json`, `data/verdicts/<HASH>.json`,
   `data/enrichment.json`, `data/images/`) in the working tree. The workflow commits +
   redeploys. Do not commit or push yourself.
