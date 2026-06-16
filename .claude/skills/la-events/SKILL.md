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
3. **19hz** — `scripts/fetch_19hz.py`. The canonical grassroots LA dance calendar (HTML
   tables). Best single electronic source; carries price tiers + organizer names.
4. **Goldenvoice / AEG** — `scripts/fetch_goldenvoice.py`. Pulls the public Azure-blob JSON
   feed behind goldenvoice.com (Fonda, El Rey, Roxy, Novo, Shrine, Greek). Filters to LA metro.
5. **Vidiots (rep cinema)** — `scripts/fetch_filmbot.py`. Hits the Filmbot/Nightjar REST API
   (`nj/v1`) behind the JS calendar. `--site` flag works for any Nightjar cinema.
6. **Posh** — `scripts/fetch_posh.py`. Authenticated tRPC API (LA explore: Trending / This
   Week|Month). Needs `POSH_TOKEN` env var (session JWT, ~30-day life; re-capture when it 401s).
   Strong afterhours/warehouse + TBA-location coverage; broad, so lean on taste ranking.
7. **Eventbrite (curated organizers)** — `scripts/fetch_eventbrite.py`. The open browse is
   behind an AWS WAF CAPTCHA (unscrapeable) and the search API is retired, SO coverage is via
   a curated list of promoter/organizer pages (in `sources.yaml` under the Eventbrite source's
   `organizers:`). Event + organizer pages are NOT walled. **This list must keep growing** — see
   the harvesting note under Mode 3 and Mode 2.
8. **Generic JSON-LD** — `scripts/fetch_jsonld.py` for any source that serves server-side
   `schema.org/Event` (has a curl HTTP/2 fallback). NOTE: most LA venue calendars are
   JS-rendered (DICE, Lodge Room, Pantages, Zebulon) and return nothing here — prefer a
   source-specific API fetcher (Filmbot pattern) when JSON-LD is absent.
9. **Gmail "Events" label** (when Gmail connector is available) — search threads labeled
   `Events` received in the last 14 days. These are promoter blasts (6AM, Dirty Epic,
   Restless Nites, venue newsletters, SMS-to-email forwards). Extract event name, date,
   venue/TBA status, lineup, ticket link. Promoter blasts often announce events *beyond*
   the digest window — include a "further out, just announced" section for these.
   **When a blast contains an Eventbrite link, also run the organizer-harvest (Mode 3).**

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
   events explicitly; note "lineup TBA" vs announced. This is the priority section — lead
   with rooftop/vinyl/groove/European and proper house+techno (the taste north star).
3. **Live music**
4. **Film** (rep/arthouse screenings — note format if 35mm/70mm)
5. **Comedy** — only if a `comedians_loved` name is playing; otherwise omit the section
   entirely (user is not a general comedy fan).
6. **Theater / arts**
7. **Around town** — GENERAL LA context, not ticketed picks: what's in the air citywide
   (e.g. FIFA World Cup 26 matches at SoFi + watch parties everywhere, big sports, heat
   waves, street fairs, museum free days). Pull from the DiscoverLA weekend roundup + LAist.
   2–5 short lines; this is the "what's going on in LA right now" texture.
8. **On the radar** — big events months out, from `festivals.yaml` + a quick live web lookup
   each run. Keep it SHORT and plain (no bold/hype) and **relevance-driven, not list-driven**:
   surface an item only when there's an actual ticket-timing reason — on-sale/presale opening
   soon, prices climbing, low stock, selling out, sold out, or a lineup just dropped. Don't
   pad it with festivals just because they're curated or were named; if nothing's time-sensitive,
   a couple lines (or one) is plenty. Far-off/dormant entries stay in `festivals.yaml`, not the
   digest. Lead with the most on-taste + most urgent.
9. **Just announced, further out** — from promoter blasts; on-sale dates matter here
10. Footer: sources that failed/were skipped this run

Each line: `Day M/D — [Event](link) — Venue (neighborhood) — price if known`.
**ALWAYS hyperlink the event** to its ticket/info URL when the catalog has one (it usually
does — links live on each record). Keep editorial-mention badges inline, e.g. "(LAist pick)".

**Pin named favorites.** When the user has called out a specific event/series/venue as an
on-taste archetype (e.g. **Sunset Sessions @ Golden Hour / Level 8** — the rooftop-vinyl-house
north star; tracked in `taste.yaml` venues_loved), surface it whenever it's on, even if its raw
score is modest. Don't let the archetype get buried under higher-scoring one-offs.

**Artist-annotation layer (required).** Many lineup names are unknown to the user — so for
picks and notable lineups, add a short parenthetical or em-dash gloss explaining who the
artist/DJ is and WHY it's on-taste: genre, scene, label, or reference point
(e.g. "DJ Minx — Detroit house pioneer, Women on Wax"; "Antal — Rush Hour boss, Dutch
digger, deep/disco selector"; "Yaeji — NY/Korean house-pop, leftfield club"). Anchor to the
taste north star (rooftop/vinyl/groove/European/fabric-style) where it fits. Use your own
knowledge; web-check only genuinely unknown names. Don't annotate household names.

### Taste profile (ranking weights)

- North star: "Sunset Sessions at Golden Hour DTLA" — chill rooftop, vinyl/grooves, house,
  European feel. Optimize toward that energy.
- **High**: house / techno / acid / electro DJ events (mainstream AND underground);
  "fabric London"-style club nights / European-leaning lineups; rooftop / sunset / daytime
  open-air house, disco, Balearic, groove; vinyl-only / listening-bar sets; warehouse &
  afterhours parties; rep & arthouse cinema (Vidiots, Vista, Brain Dead, Cinematheque, New Bev)
- **Medium**: live bands (post-punk, electronic-adjacent, experimental); record fairs /
  listening bars; craft beer events; theater (Pantages-scale and black-box)
- **Low / usually skip**: standup comedy — NOT a general fan; surface only `comedians_loved`
  names (e.g. Stavros Halkias). Stadium pop, mainstream/big-room EDM, museum openings.
- **Context boosts**: rooftop/open-air/sunset (+), vinyl-only or open-to-close set (+),
  European DJs/labels (fabric, Rush Hour, Running Back) / Balearic-disco (+), groove/soulful/
  deep/dub house (+), walkable from Silver Lake (+), Fri/Sat (+), editorial mention (+),
  RA pick (+), early-bird tier left (+)
- **Penalties**: bottle-service clubs (−), 18+ big-room/hardstyle mega-raves (−), far-flung
  (Temecula/Anaheim/OC/SD/Ventura) unless worth the drive (−)
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
   - **Eventbrite organizer auto-harvest** (runs cheaply, do it every Discover pass):
     `python scripts/fetch_eventbrite.py --scan-catalog`. This walks every Eventbrite link
     already in the catalog (many arrive via 19hz/RA ticket links), extracts each event's
     *actual* organizer from its JSON-LD, and appends new promoters to the Eventbrite
     `organizers:` list — deduped. This is how Eventbrite coverage compounds over time.
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

**If the blast/flyer contains an Eventbrite link** (`eventbrite.com/e/...`), also run:
`python scripts/fetch_eventbrite.py --harvest <event_url>`. This extracts that event's
organizer from its JSON-LD and adds the promoter to the Eventbrite `organizers:` list
(deduped), so all of their *future* events get pulled automatically. Parsing one flyer
thus permanently subscribes us to that promoter — the intended way Eventbrite coverage grows.

---

## Files (paths relative to repo root)

- `sources.yaml` — the registry. Read at the start of every mode. Schema documented in
  the file header.
- `taste.yaml` — ranking config (re-read every run). Has the north star, weights, and
  `comedians_loved` (the comedy exception list).
- `festivals.yaml` — the "On the radar" curated list (festivals + big concerts months out);
  refresh status with a live web lookup each digest run.
- `scripts/fetch_ticketmaster.py` — Discovery API fetcher (needs `TM_API_KEY`)
- `scripts/fetch_ra.py` — RA GraphQL fetcher (no key; verify `AREA_ID` on first run)
- `scripts/fetch_19hz.py` — 19hz dance-calendar table scraper
- `scripts/fetch_goldenvoice.py` — Goldenvoice/AEG Azure-blob feed (LA-metro filtered)
- `scripts/fetch_filmbot.py` — Nightjar/Filmbot cinema REST API (`--site`; Vidiots default)
- `scripts/fetch_posh.py` — Posh authenticated tRPC explore (needs `POSH_TOKEN`)
- `scripts/fetch_eventbrite.py` — curated-organizer crawler + `--harvest` / `--scan-catalog`
- `scripts/fetch_jsonld.py` — generic schema.org/Event scraper (curl fallback)

## Practical notes

- Scripts need open network access (run locally / Claude Code); the claude.ai sandbox
  allowlist will block ra.co and app.ticketmaster.com — in that environment, use web_fetch
  on source URLs instead of the scripts.
- Always print the digest with dates as `Day M/D` (no leading zeros).
- If a fetch fails, degrade gracefully — never block the digest on one dead source.


> Repo note: registry (`sources.yaml`), taste config (`taste.yaml`), scripts (`scripts/`), catalog (`data/catalog.json`), and digests (`digests/`) all live at repo root. CLAUDE.md has conventions; ROADMAP.md has current phase.
