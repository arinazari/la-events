# Routine: daily weekend digests

Prompt for the scheduled cloud Routine (claude.ai/code → Routines). Paste the body below
as the routine prompt; repo = this one. Runs **daily** and maintains a rolling set of
**per-weekend** digests for the next ~4 months — each weekend gets its own file, refreshed
every day as new events are announced and lineups firm up.

Configure in the routine's environment (not here): the daily schedule, the target branch
(recommended: a long-lived `claude/digests` branch the routine keeps committing to), the
network policy (outbound to app.ticketmaster.com, ra.co, dice.fm + the domains in
sources.yaml), and `TM_API_KEY`.

> Prereq: validate one manual digest run first (ROADMAP Phase 1). A daily routine pointed
> at an unvalidated pipeline with no `TM_API_KEY` just commits empty weekend files daily.

---

Run the la-events digest per .claude/skills/la-events/SKILL.md, in **weekend-set** mode:

1. **Run the deterministic core:** `python scripts/run_digest.py --days 21`. It fetches the
   structured sources, dedupes, expires past events, scores against taste.yaml + profile.yaml, and
   writes `data/catalog.json` + `data/candidates.json`. Capture its run report (failed/skipped
   sources) for the footer. Degrades gracefully — one dead source never blocks the run. The Phase C
   music layer rides along automatically: if `SPOTIFY_REFRESH_TOKEN` is set it syncs Spotify, then
   folds it with `data/feedback.jsonl` into the scoring (the report prints a `music layer …` line).
2. **Layer in + re-score:** add the sources the core doesn't cover (SKILL Step 2) — the Gmail
   "Events" label if the connector is available, `webfetch`/`squarespace`/`ics` venues from
   sources.yaml (respect the ~15-source budget), and this week's editorial roundups as
   `editorial_mentions` boosts. Then re-run `python scripts/run_digest.py --no-fetch` to re-dedupe
   and re-score the updated catalog and refresh `data/candidates.json`.
3. **Enrich (Phase B):** fan out the `scene-researcher` agent over `data/candidates.json` for
   per-event tags, artist notes, curator's notes, descriptions, and top-10 images. Until that layer
   is wired, synthesize directly with inline artist annotations (SKILL Step 5).
4. Compute the next 16 weekends (Fri–Sun, Thursday-night events fold in as a lead-in),
   starting with the current/upcoming weekend. For each, write/update
   `digests/weekends/YYYY-MM-DD.md`, keyed by that weekend's **Friday**, in the skill's
   digest format but scoped to that weekend:
   - **Near weekends (next ~6):** full digest — top picks first, all categories, ranked from the
     scored `data/candidates.json`.
   - **Far weekends (7–16 out):** announcement-driven only — list just what's actually
     announced / on sale (festivals, tracked artists, fast-sellout on-sales). Leave them
     thin; do NOT pad. They fill in as they approach.
5. Maintain `digests/weekends/index.md`: one row per weekend (date range, # events, the
   single top pick), soonest weekend first. Drop weekends now in the past.
6. Rebuild the dashboard feed: `python scripts/build_dashboard.py` (reads the catalog +
   taste.yaml, writes dashboard/data.json so the dashboard reflects today's catalog).
7. Commit the catalog + all changed weekend files + index + dashboard/data.json with
   message "weekend digests: YYYY-MM-DD (W weekends, N events, M new)".
8. If the Gmail connector is available, email Ari the index plus the nearest weekend's top
   picks — subject "LA Events — weekends ahead ({M/D})". Don't email all 16 files.
9. If any source failed twice in a row, mark it flaky in sources.yaml and note it in the
   nearest weekend file's footer.
10. Do NOT run discover mode in this routine (separate weekly routine / manual).
