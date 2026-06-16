# Routine: weekly dining radar

Prompt for the scheduled cloud Routine (claude.ai/code → Routines). Paste as the routine
prompt; repo = this one. Suggested cadence: weekly (e.g. Wednesday AM, ahead of weekend
planning). Separate from the events daily-digest routine.

---

Run the la-dining radar per .claude/skills/la-dining/SKILL.md (Mode 2):

1. Read dining-sources.yaml, dining-taste.yaml, and data/dining.json.
2. Pull editorial/guide signals (Eater LA heatmaps + RSS, The Infatuation LA Best New /
   Hit List, LA Times Food / 101, Michelin LA) and the Resy Hit List + OpenTable trending.
   Respect the ~12-source scrape budget. Do NOT bulk-scrape reservation availability.
3. Merge into data/dining.json: add new restaurants/popups, append fresh signals to existing
   records (keep all provenance), refresh last_seen, expire popups whose date has passed.
4. Write digests/dining-YYYY-MM-DD.md in the radar format: New & noteworthy openings /
   Trending & hard tables / Critics' picks this cycle / Popups & trucks (Day M/D, preserve
   "location TBA") / Eastside watch / footer of failed-or-skipped sources. Brief, opinionated,
   ranked by dining-taste.yaml — not exhaustive.
5. Commit catalog + digest with message "dining radar: YYYY-MM-DD (N tracked, M new)".
6. If the Gmail connector is available, email the radar body to Ari, subject
   "LA Dining Radar — {weekday} {M/D}".
7. If any source failed twice in a row, mark it flaky in dining-sources.yaml and note it.
8. Do NOT run discover mode in this routine (separate / manual).
