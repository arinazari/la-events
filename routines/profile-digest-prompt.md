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
> budget AND a hard wall clock: **the workflow kills this step at 8 minutes** (whatever is on disk
> by then still gets committed — the workflow merges any batch results you didn't get to;
> unfinished work is simply lost). The deterministic feed
> (`dashboard/data.<HASH>.json` + `data/editor_pool.<HASH>.json`) was ALREADY built by the workflow
> before you started, so the ranking is safe even if you do nothing. Your job is the *thin* LLM layer
> + the digest. **Hard caps:** judge at most **24 events total** — from the top ~40 pool events by
> score, the not-yet-judged/stale ones, highest score first — in at most **4 event-editor batches
> launched together in ONE message so they run in parallel**; at most **1 scene-researcher batch**.
> If more than 24 are unjudged or stale (a scoring change or a reaction can re-select a pile of
> already-judged events at once), take the top 24 and leave the rest — **a backlog is the nightly
> routine's job, never this click's.** The deliverable is the VERDICT layer: merge the editor batches
> as soon as they return (step 1), then re-score (step 3). If you're
> low on turns or clock, skip enrichment (step 2) — never the merge or the re-score. Never re-fetch
> the catalog or judge the whole backlog.

1. **Judge the top of the ranking (event-editor) — ≤24 events, ≤4 parallel batches.** Run
   `python scripts/editor_batches.py --profile-hash <HASH> --top 40 --cap 24 --batches 4`: it takes
   the **top ~40 pool events by score**, selects the not-yet-judged/stale ones
   (`editor.select_for_verdict` against this profile's verdict store — only new/changed events cost
   a call), **caps at 24** (highest score first; the rest is the nightly's backlog), and writes ≤4
   self-contained batch files to `data/editor_batches/<HASH>/`, printing ONE JSON line
   (`selected`, `judging`, `backlog`, `batches[]`, `merge`). If `judging` is 0, skip to step 2.
   Otherwise launch one **event-editor** agent (Task tool) per batch file, **all in one message** so
   they run concurrently, and tell each ONLY its batch-file path — the file carries the records, the
   taste brief, the Spotify lane, and its `results_path`. **If the workflow says this run's judging
   tier is `opus`, pass `model: "opus"` on each event-editor Task call** (the agent is pinned to
   sonnet otherwise). Each agent writes its verdicts to its `results_path` and replies with one
   summary line; don't ask for the JSON back or cat the files. Then run the printed `merge` command
   (`python scripts/merge_verdicts.py data/editor_batches/<HASH>/*.results.json --profile-hash
   <HASH>`) → this profile's verdict store.

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
