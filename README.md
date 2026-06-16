# la-events

Personal Los Angeles events aggregator + taste-ranked digest, built and run as Claude Code
cloud sessions / scheduled Routines. All state lives in this repo: a run reads the catalog
and source registry, fetches, dedupes, ranks against your taste profile, and commits the
updated catalog + digests back.

## What it does

- **Aggregates** from structured pipelines (Ticketmaster, Resident Advisor, DICE, the Gmail
  "Events" label), JSON-LD / scraped venue calendars, editorial roundups (ranking signals
  only), and manual captures — pasted flyers and promoter **SMS/MMS** blasts (`sms-ingestion.md`).
- **Dedupes** into `data/catalog.json` (one record per real event, all ticket links kept).
- **Ranks** against `taste.yaml` and writes conversational digests.
- **Discovers** new sources over time (propose → you approve → `sources.yaml`).

## Output

- **Scheduled routine** maintains a rolling set of **per-weekend** digests for the next
  ~4 months in `digests/weekends/` (one file per weekend + `index.md`), refreshed daily.
- **Ad-hoc**: `/la-events` (or `/la-events digest [N days]`) for a windowed digest any time;
  `/la-events discover | flyer | sources` for the other modes.
- **Dashboard** (`dashboard/`): static, filterable PWA-lite view of the catalog (by
  date/type/location/rating, with a per-event "why?" score), built by
  `scripts/build_dashboard.py` and deployable to GitHub Pages.

## Setup

- Set `TM_API_KEY` in the cloud environment (free key from developer.ticketmaster.com).
- Allow network egress to app.ticketmaster.com, ra.co, dice.fm + the domains in `sources.yaml`.
- Create a Gmail "Events" label and route promoter newsletters to it.
- Optional: stand up the Twilio SMS receiver (`sms-ingestion.md`) to ingest text blasts.
- Schedule the daily digest as a Routine using `routines/daily-digest-prompt.md`
  (commit to a `claude/digests` branch; see ROADMAP Decision 4 for cadence).

## Docs

- **CLAUDE.md** — orientation + conventions (start here)
- `.claude/skills/la-events/SKILL.md` — operating spec (the contract)
- **ROADMAP.md** — current phase + open decisions
- `sms-ingestion.md` — Twilio SMS/MMS → catalog spec
- `taste.yaml`, `sources.yaml` — config you edit
