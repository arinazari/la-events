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

1. Read sources.yaml, taste.yaml, and data/catalog.json.
2. Fetch structured sources (scripts/fetch_ticketmaster.py, scripts/fetch_ra.py, DICE),
   the Gmail "Events" label if the connector is available, and this week's editorial
   roundups. Respect the per-run scrape budget in the skill. Degrade gracefully — one dead
   source never blocks the run.
3. Merge into the catalog with the skill's dedupe rules; expire events whose date is now
   in the past; write data/catalog.json.
4. Compute the next 16 weekends (Fri–Sun, Thursday-night events fold in as a lead-in),
   starting with the current/upcoming weekend. For each, write/update
   `digests/weekends/YYYY-MM-DD.md`, keyed by that weekend's **Friday**, in the skill's
   digest format but scoped to that weekend:
   - **Near weekends (next ~6):** full digest — top picks first, all categories, scored
     against taste.yaml.
   - **Far weekends (7–16 out):** announcement-driven only — list just what's actually
     announced / on sale (festivals, tracked artists, fast-sellout on-sales). Leave them
     thin; do NOT pad. They fill in as they approach.
5. Maintain `digests/weekends/index.md`: one row per weekend (date range, # events, the
   single top pick), soonest weekend first. Drop weekends now in the past.
6. Commit the catalog + all changed weekend files + index with message
   "weekend digests: YYYY-MM-DD (W weekends, N events, M new)".
7. If the Gmail connector is available, email Ari the index plus the nearest weekend's top
   picks — subject "LA Events — weekends ahead ({M/D})". Don't email all 16 files.
8. If any source failed twice in a row, mark it flaky in sources.yaml and note it in the
   nearest weekend file's footer.
9. Do NOT run discover mode in this routine (separate weekly routine / manual).
