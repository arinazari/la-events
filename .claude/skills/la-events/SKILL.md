---
name: la-events
description: >
  Search, aggregate, and synthesize Los Angeles events into a personalized digest, and
  continuously discover new event sources. Use this skill whenever the user asks "what's
  going on in LA," "what should I do this weekend," "any good shows/parties/raves coming
  up," "events digest," "la-events," or pastes an event flyer / screenshot / promoter
  email or text blast to be cataloged. Also trigger for "find new event sources,"
  "discover sources," or "update the source registry." If the user mentions LA nightlife,
  warehouse parties, afterhours, comedy shows, rep cinema screenings, theater, or live
  music in a planning context, assume they want this skill.
---

# LA Events Aggregator

## Purpose

Aggregate events across Los Angeles from APIs, scrapeable sources, editorial roundups, and
manual captures (flyers, text blasts, promoter emails), then synthesize a digest ranked
against the user's taste profile. Secondary mode: discover and vet new sources to grow the
registry over time.

The user lives in Silver Lake (near Hyperion & Del Mar). Eastside proximity is a plus but
not a requirement — a great party in DTLA or a show at the Bowl beats a mediocre one
around the corner.

## Modes

| Invocation | Mode |
|---|---|
| `/la-events` or `/la-events digest [N days]` | **Digest** — fetch, dedupe, rank, brief |
| `/la-events discover` | **Discover** — hunt for new sources, propose registry additions |
| `/la-events flyer` + pasted image/text | **Capture** — normalize a flyer/blast into a catalog entry |
| `/la-events sources` | Show registry status from `sources.yaml` |

---

## Mode 1 — Digest

Default window: next 7 days (Thu–Sun weighted). If user specifies a window ("this
weekend," "next two weeks"), use that.

### Step 1 — Pull structured sources

Run in parallel where possible:

1. **Ticketmaster Discovery API** — `scripts/fetch_ticketmaster.py` (repo root). Requires `TM_API_KEY`
   env var (free key from developer.ticketmaster.com). Covers TM, TicketWeb, Universe,
   FrontGate. Query LA via `dmaId=324`. Pull `music`, `comedy`, `arts & theatre`
   classifications.
2. **Resident Advisor** — `scripts/fetch_ra.py`. Hits RA's GraphQL endpoint for the LA
   area. Flag events with start times ≥ 10pm as potential afterhours/warehouse.
3. **Gmail "Events" label** (when Gmail connector is available) — search threads labeled
   `Events` received in the last 14 days. These are promoter blasts (6AM, Dirty Epic,
   Restless Nites, venue newsletters, SMS-to-email forwards). Extract event name, date,
   venue/TBA status, lineup, ticket link. Promoter blasts often announce events *beyond*
   the digest window — include a "further out, just announced" section for these.

### Step 2 — Pull editorial/curation signals

Web-fetch the current weekly roundups (URLs in `sources.yaml`, tier: editorial):
LAist "Best Things To Do," Time Out LA this-weekend page, We Like LA, Secret LA recent
posts, 6AM Group weekly LA picks, Dirty Epic weekly picks. Do NOT treat these as the
catalog — extract event mentions and use them as **ranking boosts** (+1 per independent
editorial mention) on events already in the catalog. If an editorial source mentions an
event not captured by any structured source, add it to the catalog with `source: editorial`.

### Step 3 — Scrape registry venues (JSON-LD first)

For each `active` source in `sources.yaml` with `method: jsonld` or `method: scrape`,
fetch the calendar page and extract `schema.org/Event` JSON-LD blocks. Fall back to HTML
parsing only if JSON-LD is absent. Skip sources marked `dead` or `flaky`; note them in the
digest footer so the user knows coverage gaps.

Budget: don't fetch more than ~15 scrape sources per digest run. Prioritize by the
`priority` field in the registry and by category relevance to the request (e.g., a "what
raves this weekend" request prioritizes club/promoter sources over theater).

### Step 4 — Dedupe

Same event frequently appears on RA + DICE + venue site + Ticketmaster. Merge when:
**same venue (fuzzy, normalize "The" / "LA" / abbreviations) + same date + title/headliner
similarity high**. Keep ALL ticket links on the merged record (user may want DICE over TM
for fees). Keep the richest description.

### Step 5 — Rank and synthesize

Score each event against `taste.yaml` (repo root) — the profile summary below is a fallback if taste.yaml is missing. Output the digest as conversational
markdown — NOT a wall of every event. Structure:

1. **Top picks** (3–6 events, any category) — one line each on *why* it's flagged
2. **Electronic / club / afterhours** — include start times; mark warehouse/TBA-location
   events explicitly; note "lineup TBA" vs announced
3. **Live music**
4. **Comedy**
5. **Film** (rep/arthouse screenings — note format if 35mm/70mm)
6. **Theater / arts**
7. **Wildcard** — one or two things outside the profile worth knowing about (big festivals,
   one-off spectacles, Liverpool FC watch-party-worthy fixtures)
8. **Just announced, further out** — from promoter blasts; on-sale dates matter here
9. Footer: sources that failed/were skipped this run

Each line: `Day M/D — Event — Venue (neighborhood) — price if known — [ticket link(s)]`.
Keep editorial-mention badges inline, e.g. "(LAist pick)".

### Taste profile (ranking weights)

- **High**: house / techno / acid / breakbeat / electro DJ events; warehouse and
  afterhours parties; rep & arthouse cinema (Vidiots, Brain Dead, Cinematheque, New Bev,
  Vista, Now Instants-type programming); standup comedy
- **Medium**: live bands (post-punk, electronic-adjacent, experimental); theater
  (Pantages-scale and small black-box both); craft beer events / brewery takeovers /
  beer festivals; record fairs and listening bar events; food events with a music angle
- **Low but include if exceptional**: stadium pop, mainstream EDM festival brands,
  museums/galleries (include openings, skip ongoing exhibitions unless closing soon)
- **Context boosts**: walkable/short drive from Silver Lake (+), Friday/Saturday night (+),
  lineup includes artists in the user's rekordbox/listening orbit if known from
  conversation (+), early-bird tier still available (+)
- **Penalties**: Vegas-style bottle-service clubs (−), 18+ EDM mega-raves (−), anything
  requiring Coachella-tier logistics without Coachella-tier payoff (−)

The profile is a starting point. When the user reacts ("more of this," "never show me X"),
update this section of the skill — treat it as living config.

---

## Mode 2 — Discover (new source hunting)

Run on request, or proactively suggest running it if it hasn't run in 7+ days (check
`last_discovery` in `sources.yaml`).

1. **Gap mining**: scan the current catalog for venues/promoters that appear in event data
   but have no entry in `sources.yaml`. Each is a candidate.
2. **Web sweep**: search combinations like "LA warehouse party this weekend," "los angeles
   underground techno promoter," "LA events newsletter," "best LA event calendars," "new
   venue opening los angeles," plus category-specific sweeps rotating weekly (comedy one
   week, cinema the next...). Look for aggregators, promoters, venues, newsletters not in
   the registry.
3. **Vet each candidate**: check in order — official API? ICS/RSS feed? JSON-LD in event
   pages? Clean scrapeable HTML? Email newsletter signup? IG-only? Record the best
   available method.
4. **Propose, don't auto-add**: present candidates as a short table (name, category, best
   method, sample of what it lists, recommendation). On user approval, append to
   `sources.yaml` with `status: active` (or `status: manual` for IG/SMS-only sources, with
   a note on how to capture them). Update `last_discovery`.
5. IG-only promoters: never scrape Instagram. Register them as `method: manual` with the
   handle, and remind the user these flow in via the flyer-capture mode or by joining
   their text/email list (route to the Gmail "Events" label).

---

## Mode 3 — Flyer / blast capture

Input: screenshot of an IG story/flyer, pasted SMS blast text, or forwarded promoter email.

Extract and normalize: event name, date(s), start/end time, venue (or "TBA — location
drops day-of" — preserve this, it matters), full lineup in billed order, price tiers,
ticket link, promoter, 21+/18+, RSVP mechanics (e.g. "DM for address"). Output the
normalized entry, and if the promoter isn't in `sources.yaml`, offer to add them as a
`manual` source. If the user keeps a running catalog file, append to it.

---

## Files (paths relative to repo root)

- `sources.yaml` — the registry. Read at the start of every mode. Schema documented in
  the file header.
- `scripts/fetch_ticketmaster.py` (repo root) — Discovery API fetcher (needs `TM_API_KEY`)
- `scripts/fetch_ra.py` — RA GraphQL fetcher (no key; verify `AREA_ID` on first run, see
  script header)

## Practical notes

- Scripts need open network access (run locally / Claude Code); the claude.ai sandbox
  allowlist will block ra.co and app.ticketmaster.com — in that environment, use web_fetch
  on source URLs instead of the scripts.
- Always print the digest with dates as `Day M/D` (no leading zeros).
- If a fetch fails, degrade gracefully — never block the digest on one dead source.


> Repo note: registry (`sources.yaml`), taste config (`taste.yaml`), scripts (`scripts/`), catalog (`data/catalog.json`), and digests (`digests/`) all live at repo root. CLAUDE.md has conventions; ROADMAP.md has current phase.
