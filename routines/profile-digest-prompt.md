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

> **Bounded run — finish, don't be exhaustive.** This is one on-demand click, capped at a small turn
> budget. The deterministic feed (`dashboard/data.<HASH>.json` + `data/editor_pool.<HASH>.json`) was
> ALREADY built by the workflow before you started, so the ranking is safe even if you do nothing. Your
> job is the *thin* LLM layer + the digest. **Hard caps:** at most **2 event-editor batches** and **1
> scene-researcher batch**, judging only the **top ~40** pool events by score. The single most important
> deliverable is the written digest at step 5 — if you're running low on turns, skip enrichment (step 2)
> and go straight to writing it. Never re-fetch the catalog or judge the whole backlog.

1. **Judge the top of the ranking (event-editor) — ≤2 batches.** Load `data/editor_pool.<HASH>.json`.
   Take the **top ~40 by score** and select the not-yet-judged ones with `editor.select_for_verdict`
   against `data/verdicts/<HASH>.json` (the cache carries the rest — only new/changed events cost a
   call). Fan the **event-editor** agent (Task tool) over them in **at most 2 batches**; each record
   carries the deterministic score + reasons + tags + lane, plus its Spotify `affinity_hint` /
   `profile_affinity` when connected. Merge the verdicts: `python scripts/merge_verdicts.py
   <results.json> --profile-hash <HASH>` → `data/verdicts/<HASH>.json`. If nothing needs judging, skip.

2. **Enrich the very top picks (scene-researcher) — ≤1 batch, optional.** Only the top ~10–12 cache-miss
   candidates (`enrich.select_for_enrichment`): one **scene-researcher** batch → tags, artist notes,
   curator's notes, descriptions → fold into `data/enrichment.json`.
   Skip entirely if there are no misses or you're low on turns.

3. **Re-score with fresh verdicts.** `python scripts/build_profiles.py --only-hash <HASH>` again, so the
   new verdicts fold into each event's **final rank** in `dashboard/data.<HASH>.json`.

4. **Refresh the radar (best-effort).** `python scripts/build_radar.py` → `data/radar.json`.

5. **Write the personalized digest (the key deliverable).** Read `dashboard/data.<HASH>.json` (display
   name in `feed.profile.name`) and write a concise, conversational, **opinionated** narrative digest to
   `digests/<HASH>/latest.md` (overwrite) — the LA-insider voice, ranked to THIS person: top picks across
   the next ~2–3 weeks + weekends ahead, grouped by day, a one-line *why* each, ⭐ on the editor's
   must-sees. Thin feed → a couple of honest lines, don't pad. The dashboard's digest modal loads this.

6. **Stop.** Leave the changed files (`dashboard/data.<HASH>.json`, `data/verdicts/<HASH>.json`,
   `data/enrichment.json`, `data/images/`, `digests/<HASH>/latest.md`) in the working tree. The
   workflow commits + redeploys. Do not commit or push yourself.
