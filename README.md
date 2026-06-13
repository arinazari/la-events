# la-events

Personal LA events aggregator: pulls from Ticketmaster, Resident Advisor, DICE, Gmail
promoter blasts, venue calendars, and editorial roundups; dedupes into a catalog; emits
a taste-ranked digest. Runs as Claude Code cloud sessions / scheduled Routines.

- Start here: **CLAUDE.md** (orientation + conventions)
- Operating spec: `.claude/skills/la-events/SKILL.md`
- Status + open decisions: **ROADMAP.md**
- Config you edit: `taste.yaml`, `sources.yaml`

Setup: set `TM_API_KEY` in the cloud environment; allow network egress to
app.ticketmaster.com, ra.co, dice.fm + sources.yaml domains; create a Gmail "Events"
label and route promoter newsletters to it.
