---
name: la-dining
description: >
  Recommend where to eat in Los Angeles — restaurants, eateries, popups, and food trucks —
  for a given day, occasion, or neighborhood, and track what's trending. Use this skill
  whenever the user asks "where should I eat," "dinner spot for Friday," "good lunch near
  [neighborhood]," "what's the hot new restaurant," "where to take someone for [occasion],"
  "any popups/food trucks worth hitting," "what's trending in LA dining," "la-dining," or
  pastes a popup/restaurant flyer or promoter blast to be cataloged. Also trigger for
  "find new dining sources" or "discover dining sources." Sibling of the la-events skill —
  same conventions, different domain (food, not shows). For shows/parties/film use la-events.
---

# LA Dining Aggregator

## Purpose

Help the user decide where to eat in LA — by **occasion** (date night, group dinner, solo
counter seat, late-night, quick lunch), by **location** (walkable from Silver Lake, or
wherever they'll be), and by **what's trending** (new openings, critics' picks, hard-to-get
tables, notable popups and food trucks). Pulls from reservation platforms and food-critic
editorial, ranks against a light food-taste profile that learns over time, and either
answers a one-off query or emits a weekly "dining radar."

The user lives in Silver Lake (near Hyperion & Del Mar). Eastside proximity is a plus, not a
requirement — a destination meal in Santa Monica or a popup in Frogtown beats a mediocre spot
around the corner. Match the occasion: "walkable Tuesday dinner" and "somewhere special for a
birthday" want very different answers.

## How dining differs from events (read this)

Events are dated rows — they happen once and expire. **Restaurants are persistent entities**:
a place is "good" across many nights, so the catalog stores *restaurants*, each carrying the
**signals** that surfaced it (Eater heatmap, Infatuation Hit List, Michelin star, a new
opening, a hard Resy). Ranking is driven by the **count, recency, and prestige of those
signals** plus taste/occasion/location fit — not by a single date.

**Popups and food trucks are the event-shaped exception**: they're date- and
location-bound. Store them with a `popup` block (date, time, host venue or "location TBA",
ticket/RSVP link) and treat them like a la-events capture. They expire; restaurants don't.

## Modes

| Invocation | Mode |
|---|---|
| `/la-dining` or a natural "where should I eat…" question | **Query** — recommend for a day/occasion/area |
| `/la-dining radar [N days]` | **Radar** — weekly trending digest (new openings, hot tables, popups) |
| `/la-dining discover` | **Discover** — hunt for new dining sources, propose registry additions |
| `/la-dining capture` + pasted flyer/blast | **Capture** — normalize a popup/truck/restaurant into a catalog entry |
| `/la-dining sources` | Show registry status from `dining-sources.yaml` |

Read `dining-sources.yaml` and `dining-taste.yaml` at the start of every mode. The catalog is
`data/dining.json`. Radar outputs go to `digests/dining-YYYY-MM-DD.md` (prefixed so they
don't collide with event digests).

---

## Mode 1 — Query (primary)

The user names some mix of **day/time**, **occasion**, **neighborhood/area or walkability**,
**party size**, **cuisine or vibe**, and **price comfort**. Some of these will be missing —
infer sensible defaults from context and `dining-taste.yaml`, and ask a single clarifying
question only if a true blocker is missing (e.g. occasion vs. area when both would flip the
answer).

### Step 1 — Pull trending/editorial signals (the backbone)

**Harvest the roundup articles, not just deep reviews.** These sites lead with curated
listicles — and that IS the signal. Every run, scan each source's front page + index/guide
pages (the `harvest:` URLs in `dining-sources.yaml`), open the current "hot / new / trending /
best" roundups, and **pull every restaurant named into the candidate set**, tagged with which
list it came from and how recent. A standing restaurant earns its place in the digest by
showing up on these lists — don't wait for a one-off dedicated review.

Web-fetch the relevant editorial/guide sources from `dining-sources.yaml`:

- **Eater LA** — front-page roundups + the **Heatmaps** ("The Hottest New Restaurants,"
  "Where to Eat Right Now") and neighborhood/cuisine guides. RSS catches new posts.
- **The Infatuation LA** — the **guides index** (Hit List, "Best New Restaurants," occasion
  and neighborhood guides — great for "date night in Los Feliz," "dinner with parents").
- **LA Times Food** — front-page "best new / where to eat" roundups, Bill Addison reviews,
  and the **101 Best Restaurants** list. Possible paywall friction — degrade gracefully.
- **Michelin Guide (LA)** — Stars, Bib Gourmand, Green stars, plus their editorial
  articles. Use for "somewhere special" / prestige occasions.
- **Resy & OpenTable (editorial side)** — also harvest their curated roundups here: the
  Resy **Hit List** + "Right This Way" blog, and OpenTable's trending/"best of" lists. Save
  their booking/availability for Step 2.

**Fetch reality (verified 6/16) — three tiers, check the `fetch:` tag.**
- `fetch: ok` — **Infatuation** and the **Resy blog** fetch clean; web-fetch the harvest URLs.
- `fetch: search_only` — **Michelin** and **OpenTable** refuse direct fetch but their roundups
  come through a **domain-scoped web search** (`allowed_domains: [that domain]`) for current
  "best / new / hot" lists; harvest names from the results.
- `fetch: blocked` — **Eater LA** and **LA Times** are denied *both* direct fetch and the
  search crawler in this env (and LAT is paywalled). They're tagged `flaky`; you'll only catch
  them secondhand when a general (un-scoped) search surfaces third-party coverage. **Note the
  coverage gap in the radar footer** — don't silently pretend they were covered.
Re-test the blocked tier if the network policy changes; promote back to `ok`/`search_only`.

Extract: restaurant name, neighborhood, cuisine, price band, the angle (new / best-of /
critic pick / starred / on a hot-list), the list it appeared on, and the source URL.
Cross-reference against the catalog and **merge signals onto existing records** (see Dedupe).
A place named on several independent lists, or freshly opened, ranks higher — that stacking
of roundup mentions is the core ranking signal.

### Step 2 — Reservation availability + hot lists (only when it adds signal)

From the reservations tier (Resy, OpenTable):

- **Resy** — the **Hit List** (curated buzzy spots) and Notify/availability. Resy skews
  toward the harder-to-get, on-trend eastside/independent places the user likely wants.
- **OpenTable** — trending lists, "available now," and broad availability (good for
  larger/older/Westside rooms and last-minute tables).

**Only hit reservation pages for specific candidate restaurants** once you have a shortlist
and the user gave a date/time/party size — to answer "can I actually get in?" Do **not** bulk-
scrape availability; it's slow and impolite. If a place is reservation-only and booked, say
so and note walk-in/bar-seat options or the Notify list. Surface the reservation difficulty
("easy," "books up — set a Notify," "hard — bar seats walk-in only").

### Step 3 — Popups & food trucks

Pull date/location-bound popups and trucks from the catalog (captured via flyer mode or
mentioned in editorial). Include any whose date falls in the query window and that fit the
occasion/area. Preserve "location drops day-of" exactly — it matters. Never scrape Instagram;
IG-only popups flow in via capture mode (see Mode 4).

### Step 4 — Rank and answer

Score candidates against `dining-taste.yaml` (occasion fit, cuisine, price comfort,
walkability/area, signal strength, reservation effort tolerance) and answer conversationally
— a short ranked shortlist, **not** a dump of every option. Structure:

1. **Top pick(s)** for the stated occasion — 1–2, each with a one-line *why* (the angle +
   why it fits *this* ask).
2. **A couple of alternates** — e.g. a safer/easier-reservation option and a wildcard.
3. **If a date/time was given**: a one-line reservation reality check per pick (open on Resy,
   books up, walk-in bar, etc.).
4. **Popup/truck callout** if anything date-relevant is on.

Each line: `Name — neighborhood — cuisine, $–$$$$ — the angle — [reservation/info link]`.
Badge editorial provenance inline, e.g. "(Infatuation Hit List)", "(Bib Gourmand)",
"(LAT 101)". Dates for popups as `Day M/D` (no leading zeros).

---

## Mode 2 — Radar (weekly trending digest)

Scheduled weekly (see `routines/dining-radar-prompt.md`) or on request. Answers "what's new
and trending in LA dining right now," independent of a specific occasion.

1. Pull the editorial/guide sources (Step 1 above) plus the Resy Hit List and any OpenTable
   trending lists. Respect a scrape budget — don't fetch more than ~12 sources per run.
2. Merge into `data/dining.json`: add new restaurants/popups, append fresh signals to
   existing records, update `last_seen`, expire popups whose date has passed.
3. Write `digests/dining-YYYY-MM-DD.md`, conversational and opinionated, structured:
   - **New & noteworthy openings** — places that opened recently, with the angle.
   - **Trending / hard tables** — buzzy spots (multiple signals, Resy Hit List, hard
     reservations) worth knowing about.
   - **Critics' picks this cycle** — fresh Eater/Infatuation/LAT/Michelin entries.
   - **Popups & trucks** — date-bound, `Day M/D`, with location/RSVP and "TBA" preserved.
   - **Eastside watch** — a short Silver Lake / Los Feliz / Echo Park / Highland Park cut,
     since that's the home turf.
   - Footer: sources that failed or were skipped this run.
4. Keep it brief and ranked by `dining-taste.yaml`, not exhaustive. Lead with what's actually
   worth the user's attention.

---

## Mode 3 — Discover (new dining sources)

Run on request, or suggest it if `last_discovery` in `dining-sources.yaml` is 7+ days stale.

1. **Gap mining**: scan the catalog for neighborhoods/cuisines/critics that recur but have no
   dedicated source entry (e.g. a neighborhood newsletter, a specific critic's feed).
2. **Web sweep**: rotate queries like "best new LA restaurants," "LA food newsletter," "LA
   popup dinner series," "best food trucks Los Angeles," "[neighborhood] new restaurant."
   Look for critic newsletters, reservation hot-lists, popup collectives, and trustworthy
   local food writers not already in the registry.
3. **Vet**: official API? RSS/ICS? JSON-LD? Clean scrapeable HTML? Newsletter signup?
   IG-only? Record the best available method. Most dining sources will be `scrape`/`rss`.
4. **Propose, don't auto-add**: present candidates as a short table (name, category, best
   method, what it lists, recommendation). On approval, append to `dining-sources.yaml`.
   Update `last_discovery`. Marking sources flaky/dead is automatic.
5. IG-only food accounts: never scrape Instagram. Register as `method: manual` with the
   handle; they flow in via capture mode or a newsletter signup.

---

## Mode 4 — Capture (popup / truck / restaurant flyer or blast)

Input: a screenshot of a popup flyer / IG story, an SMS or email blast, or a restaurant
announcement.

Extract and normalize: name, type (`popup` / `food_truck` / `restaurant` / `bar` / etc.),
cuisine, neighborhood or **"TBA — location drops day-of"** (preserve it), date(s) and
start/end time for popups, host venue, price/ticket info, reservation or RSVP mechanics
("DM to book," "walk-up," Resy/OpenTable/Tock link), and the operator/handle. Output the
normalized entry and append to `data/dining.json`. If the operator isn't in
`dining-sources.yaml`, offer to add them as a `manual` source.

---

## Catalog schema (`data/dining.json`)

Array of records. Restaurants are persistent; popups/trucks carry a `popup` block and expire.

```json
{
  "id": "kebab-case-slug",
  "name": "Restaurant Name",
  "type": "restaurant | popup | food_truck | bar | bakery | cafe",
  "cuisine": ["..."],
  "neighborhood": "Los Feliz",
  "address": "optional",
  "price": "$ | $$ | $$$ | $$$$",
  "occasion": ["date_night", "group", "solo_counter", "late_night", "quick_lunch", "special"],
  "reservations": {
    "platform": "resy | opentable | tock | walk_in | none",
    "url": "https://…",
    "difficulty": "easy | books_up | hard | walk_in_only"
  },
  "signals": [
    { "source": "eater", "type": "heatmap | review | best_of | hit_list | star | bib | new_opening",
      "label": "Eater Heatmap — Hottest New Restaurants", "url": "https://…", "date": "2026-06-01" }
  ],
  "enrichment": {
    "why_fits": "one-line insider gloss anchored to Ari's palate (the 'why' you'd say to a friend)",
    "vibe": ["patio", "intimate", "counter", "lively", "date-night"],
    "signature": ["known-for dish(es) — only if you're confident; omit otherwise"],
    "pairs_with": "the kind of night/show it sets up (the night-planner's cross-domain hook)",
    "by": "claude", "confidence": "high | med | low", "enriched_at": "2026-06-19"
  },
  "popup": {
    "date": "2026-06-20", "start": "18:00", "end": null,
    "location_tba": false, "host_venue": "…", "rsvp_url": "https://…"
  },
  "first_seen": "2026-06-16",
  "last_seen": "2026-06-16",
  "notes": "anything operationally useful"
}
```

Omit `popup` for standing restaurants. Score = signal strength (count × recency × prestige)
+ taste/occasion/location fit from `dining-taste.yaml`.

**`enrichment`** is the dining analog of the events scene-graph: a short, taste-anchored insider
gloss so the query *and* the night-planner present a pick with real context, not just a signal
badge. Write it when you research a restaurant (query/radar/capture) — `verify-or-omit` on
specifics (chef, dishes): a `signature` you're unsure of stays out (better silent than wrong).
`pairs_with` is what the night-planner reads to slot dinner into the night. Restaurants are
persistent, so the gloss lives **inline** on the record (no separate cache) and is reused every run.

## Dedupe

Restaurants appear across many sources. Merge when **name similarity high + same
neighborhood** (normalize "The", "&"/"and", "LA", apostrophes, accents). On merge: **append
all signals** (don't dedupe away provenance — multiple independent mentions = higher rank),
keep all reservation links, keep the richest description, refresh `last_seen`. Watch for
mini-chains with one name in multiple neighborhoods — those are *different* records.

## Conventions (inherited from the project)

- **Stateless cloud runs**: all state lives in this repo. Read catalog + registry + taste,
  fetch, merge, write back, commit.
- **Editorial = signals, and roundups are first-class.** Critics' lists and hot-lists drive
  what surfaces and how it ranks — including the front-page "best / new / trending" roundup
  articles on every source (the `harvest:` URLs), not just standalone deep reviews. Whenever
  restaurants are requested or presented, those current lists must be considered. The catalog
  is restaurants/popups with their provenance (which list, when) attached; mentions stack.
- **Never scrape Instagram.** IG-only operators are `method: manual` (capture flow).
- **Be polite**: real User-Agent, no bulk reservation scraping, respect rate limits. Check
  availability only for shortlisted candidates with a concrete date/time.
- **Degrade gracefully**: one dead source never blocks an answer; list failures in the radar
  footer and mark repeat offenders `flaky` in `dining-sources.yaml`.
- **Dates in output**: `Day M/D`, no leading zeros.
- **Tone**: conversational, opinionated, brief. Match the occasion. Honest tradeoffs over a
  comprehensive list. `dining-taste.yaml` decides what's worth surfacing, and learns from the
  user's reactions over time (append to its `feedback` log).
- Registry changes from Discover mode are **proposals** — present, get approval, then commit.
  Exception: marking sources flaky/dead is automatic.

## Files (paths relative to repo root)

- `dining-sources.yaml` — the dining source registry (schema in file header).
- `dining-taste.yaml` — food-taste config; minimal by design, learns from reactions.
- `data/dining.json` — the dining catalog (restaurants + popups/trucks).
- `digests/dining-YYYY-MM-DD.md` — radar outputs.
- `routines/dining-radar-prompt.md` — scheduled weekly radar prompt.
