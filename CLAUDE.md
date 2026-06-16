# CLAUDE.md — la-events

LA events aggregator + personalized digest for Ari. Built collaboratively in claude.ai
(June 2026); this repo is the source of truth going forward. Read ROADMAP.md for current
phase and open decisions before starting any non-trivial task.

## What this project does

1. **Aggregates** LA events from structured pipelines (Ticketmaster Discovery API, RA
   GraphQL, DICE, Gmail "Events" label), JSON-LD/scrape venue sources, and editorial
   roundups (used as ranking signals, NOT catalog rows).
2. **Dedupes** into `data/catalog.json` (one record per real-world event, all ticket
   links preserved).
3. **Ranks** against `taste.yaml` and emits a conversational digest to `digests/`.
4. **Discovers** new sources over time (propose → human approves → `sources.yaml`).

The full operating spec lives in `.claude/skills/la-events/SKILL.md` — read it before
working on digest/discover/flyer behavior. It is the contract; this file is orientation.

## Layout

```
.claude/skills/la-events/SKILL.md   # operating spec (digest/discover/flyer modes)
sources.yaml                        # source registry — schema documented in file header
taste.yaml                          # ranking config — user-editable, re-read every run
festivals.yaml                      # "on the radar" curated festivals/big-shows + live lookups
recurring.yaml                      # predictable recurring markets/fleas/farmers markets
scripts/fetch_ticketmaster.py       # needs TM_API_KEY env var
scripts/fetch_ra.py                 # unofficial GraphQL; verify AREA_ID once (see header)
data/catalog.json                   # deduped event store (committed = the state)
digests/YYYY-MM-DD.md               # digest outputs
routines/daily-digest-prompt.md     # prompt for the scheduled cloud routine
```

## Hard requirements & conventions

- **Stateless cloud runs**: all state lives in this repo. A run reads catalog + registry,
  fetches, merges, writes back, commits. Never assume anything outside the repo persists.
- **Secrets**: env vars only (`TM_API_KEY`). Never commit keys.
- **Never scrape Instagram.** IG-only sources are `method: manual` (flyer-capture flow).
- **Degrade gracefully**: one dead source never blocks a digest; list failures in the
  digest footer and mark repeat offenders `flaky` in sources.yaml.
- **Editorial sources are signals, not catalogs** — they boost rank; only add their
  events to the catalog when no structured source has them.
- **Dedupe key**: fuzzy (venue + date + title/headliner). Merge keeps all ticket links
  and the richest description.
- **Dates in output**: `Day M/D`, no leading zeros (Ari's standing convention).
- **Politeness**: respect rate limits (TM ≤5 req/s; RA small pages, real UA, ≤10 pages).
- **Digest tone**: conversational, opinionated, brief. Top picks first with a one-line
  *why*. Not an exhaustive dump — taste.yaml decides what's worth surfacing.
- Source registry changes from Discover mode are **proposals** — present them, get
  approval, then commit. Exception: marking sources flaky/dead is automatic.
- **Eventbrite = curated organizers** (open browse is WAF-CAPTCHA'd, search API retired).
  Coverage lives in the Eventbrite source's `organizers:` list in sources.yaml and must keep
  growing: `fetch_eventbrite.py --harvest <event_url>` when a blast/flyer carries an EB link,
  and `--scan-catalog` each Discover pass. Harvest adds only the event's *own* organizer (from
  JSON-LD), never recommended/related ones (auto-adding an event's organizer is allowed; it's a
  precise, high-confidence signal, not a Discover-style proposal).

## Working style

Ari is technical, direct, and allergic to sycophancy. Give honest tradeoffs, don't pad.
Iterate in small commits with clear messages. When a structural/architectural question
comes up, flag it for discussion rather than silently making a big design decision —
he wants input at the decision points listed in ROADMAP.md.

## Cloud session notes

- Network: this project needs outbound access to app.ticketmaster.com, ra.co, dice.fm,
  plus the domains in sources.yaml. Configure the environment accordingly (limited
  networking blocks everything by default).
- Gmail access comes via the Gmail connector when available; the "Events" label holds
  promoter blasts. If the connector isn't available in a session, skip that source and
  note it in the digest footer.
- Daily digest is intended to run as a scheduled Routine using
  routines/daily-digest-prompt.md; commit digest + updated catalog to a claude/ branch.
