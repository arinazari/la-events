# Routine: daily digest

Prompt for the scheduled cloud Routine (claude.ai/code → Routines). Paste as the routine
prompt; repo = this one; schedule per ROADMAP Decision 4.

---

Run the la-events digest per .claude/skills/la-events/SKILL.md:

1. Read sources.yaml, taste.yaml, and data/catalog.json.
2. Fetch structured sources (scripts/fetch_ticketmaster.py, scripts/fetch_ra.py, DICE),
   the Gmail "Events" label if the connector is available, and this week's editorial
   roundups. Respect the per-run scrape budget in the skill.
3. Merge into the catalog with dedupe rules; expire past events; write data/catalog.json.
4. Score against taste.yaml and write digests/YYYY-MM-DD.md in the skill's digest format
   (window: next 7 days, plus "just announced, further out" from promoter blasts).
5. Rebuild the dashboard feed: `python scripts/build_dashboard.py` (reads the catalog +
   taste.yaml, writes dashboard/data.json so the dashboard reflects today's catalog).
6. Commit catalog + digest + dashboard/data.json with message
   "digest: YYYY-MM-DD (N events, M new)".
7. If the Gmail connector is available, email the digest body to Ari, subject
   "LA Events — {weekday} {M/D}".
8. If any source failed twice in a row, mark it flaky in sources.yaml and note it.
9. Do NOT run discover mode in this routine (separate weekly routine / manual).
