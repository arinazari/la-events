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

> The **scheduled routine** runs digest mode in *weekend-set* form: one file per weekend in
> `digests/weekends/` for the next ~16 weekends (~4 months), refreshed daily — near weekends
> full, far ones announcement-driven. See `routines/daily-digest-prompt.md`. Interactive
> `/la-events digest [N days]` stays windowed as above.

### Step 1 — Run the deterministic core (`run_digest.py`)

`python scripts/run_digest.py --days 21` does the mechanical work — fetch → normalize → dedupe →
expire → score — and writes `data/catalog.json` (durable, score-free) plus `data/candidates.json`
(the scored, ranked, upcoming top-N). **Don't fetch / dedupe /
score these by hand anymore.** It covers the single-endpoint structured fetchers: Ticketmaster
(`TM_API_KEY`), Resident Advisor, 19hz, Goldenvoice, Vidiots (Filmbot), Posh (`POSH_TOKEN`),
Eventbrite (curated organizers), DICE. It **degrades gracefully** — any fetcher that errors / times
out / is missing its key is listed in the printed run report (carry that into the footer), never
blocking the run.

### Step 2 — Layer in the sources the core doesn't cover yet

Add these to `data/catalog.json` yourself, then re-score in Step 3:

1. **Gmail "Events" label** (when the connector is available) — threads labeled `Events` in the
   last 14 days: promoter blasts (6AM, Dirty Epic, Restless Nites, venue newsletters, SMS-to-email
   forwards). Extract name, date, venue/TBA, lineup, ticket link. Blasts often announce *beyond* the
   window — fold those into "further out, just announced." **When a blast carries an Eventbrite link,
   run the organizer-harvest (Mode 3).**
2. **`webfetch` / `squarespace` / `ics` / JSON-LD venues** in `sources.yaml` not covered by the core
   (McCabe's, Dresden, Harvelle's, Sam First, Junior High, The Smell, Maui Sugar Mill, …) — read the
   rendered calendar at digest time (`scripts/fetch_squarespace.py` / `fetch_ics.py` / `fetch_jsonld.py`
   where applicable, else the WebFetch tool). Budget ~15 sources/run; skip `dead`/`flaky` and note
   them in the footer.
3. **SMS inbox** (`data/inbox.jsonl`, when the Twilio receiver is live) — process `processed == false`
   entries per `sms-ingestion.md`: parse text or the MMS flyer, normalize, tag `source: sms`, mark
   processed. Idempotent on `sid`. (Twilio media URLs expire — fetch during the run.)
4. **Editorial / curation signals as ranking boosts** — web-fetch the weekly roundups (URLs in
   `sources.yaml`, tier: editorial): LAist "Best Things To Do," Time Out LA, We Like LA, Secret LA,
   6AM, Dirty Epic. Do NOT treat them as a catalog — add an `editorial_mentions` entry to matching
   records (the scorer gives +1 each). Only add a NEW event when no structured source has it
   (`source: editorial`). EXCEPTION that should actually fire, not just be permitted: dated
   **market / street-fair / pop-up / block-party / community** finds (a night market in an Eater
   or Secret LA roundup, a one-off flea, a street festival) almost never have a structured source
   — WRITE THOSE BACK as catalog rows (`source: editorial`, category `market`/`community`/
   `food-drink`) so the market lane, dashboard shelves, and editor pool see them. The fixed
   weeklies are already materialized from `recurring.yaml` by `run_digest` — don't duplicate
   those; this is for the one-offs.

### Step 3 — Re-score (`run_digest.py --no-fetch`)

After layering Step 2 in, run `python scripts/run_digest.py --no-fetch` to re-dedupe and re-score the
now-complete catalog and refresh `data/candidates.json`. Dedupe + scoring live in `scripts/lib/`
(`dedupe.py` + `scoring.py`, driven by `profile.yaml` + `taste.yaml`) — one source of truth; **never
hand-score**.

**Music layer (Phase C).** Scoring also folds in a Spotify + feedback affinity layer when present:
`run_digest.py` syncs Spotify (`fetch_spotify.py`, only if `SPOTIFY_REFRESH_TOKEN` is set) and merges
it with the feedback log into one affinity that nudges the score — an on-rotation artist in a lineup,
a high-affinity genre, or a "more like X" / "never show Y" reaction. It **enriches** `taste.yaml`,
never overwrites it; absent (no creds, no feedback) scoring is byte-identical to the taste-only path.
The reasons in `candidates.json` cite it ("Spotify core rotation (Antal)", "more like Four Tet
(your pick)") — carry those into Step 5's *why*. To log a reaction, append a line to
`data/feedback.jsonl` (schema in the file header); it folds in automatically next run.

### Step 4 — Judge the ranking  *(event-editor)*

Step 1/3 also emitted `data/editor_pool.json` — the per-lane set worth LLM ranking-judgment
(`scripts/lib/editor.py` `editor_pool`: top-K per surfaceable lane ∪ a score floor, over the next
~4 weeks). Fan out the **`event-editor`** agent over the not-yet-judged events (`select_for_verdict`,
so only new/changed ones cost a call) in parallel batches, passing `taste.yaml`; each pool record
carries the deterministic score + reasons + tags + lane and — when Spotify is connected — an
`affinity` hint plus the profile's listening lane. The agent returns a per-event **verdict**
(`{tier, lane?, adjust, why, confidence}`) — the judgment the heuristic can't make: headliner draw,
tired formats, sleepers, lane fixes. Merge with `python scripts/merge_verdicts.py <results.json>`
(writes the per-profile store `data/verdicts/default.json`). `assemble()` folds verdicts onto the
slate in Step 6 (tier orders, `adjust` de-clusters, `lane` overrides, `skip` buries); the dashboard
shows the verdict-adjusted **final rank** beside the deterministic score. Verdicts are cached +
committed, so a daily run only judges the delta. *Per-profile:* `build_profiles.py` emits each
profile's own pool (`data/editor_pool.<hash>.json`); run the editor per profile and merge with
`merge_verdicts.py --profile-hash <hash>`.

### Step 5 — Enrich the candidates  *(two tiers: scene-researcher + blurb-writer)*

Both tiers write to the one cache (`data/enrichment.json`), keyed by event-id, write-once:

- **Full head (~100):** fan out **`scene-researcher`** over the cache-miss candidates
  (`select_for_enrichment` — misses + blurb-tier events that climbed into the head, which it
  upgrades) in parallel batches → per-event sub-genre tags, artist notes, a curator's note, and a
  clean description. Fold via `update_cache` (`enriched_tier: full`) — recurring artists are
  researched once, so the scene graph compounds. Verify-or-omit: no invented bios.
- **Cheap blurb tier:** fan out **`blurb-writer`** (haiku, no web tools) over `select_for_blurb`
  applied to `data/blurb_pool.json` (the ranked band below the head) → ONE factual description line
  per event. Fold via `update_blurb_cache` (`enriched_tier: blurb`; never downgrades a full record).
  `select_for_blurb` skips events that already have a cache record OR a usable source `detail`
  (those display the raw detail for free), so only genuine gaps cost a call; the pool's reported
  `overflow` (past the cap) gets the raw-detail fallback, not a call.

The dashboard card surfaces this as **"WHAT IT IS"** (`enrichment.description`, else sanitized
`detail`), distinct from the curator's "why".

### Step 6 — Render + synthesize

`python scripts/render_digest.py --consolidated` is the **primary** invocation: ONE daily digest
(`digests/latest.md`) with the sections (in digest.yaml order) — **Tonight & tomorrow** (the
next-48h actionable slice, compact), **Don't miss** (top ~6 across the window via the ONE
shared top-picks policy, `lib/assemble.top_picks` — same rank + lane/family diversity caps as
the dashboard front page's hero row; priced + urgency-chipped), **What changed** (new/updated
since the last pull; auto-omitted on quiet days),
**Next two weeks** (days 0–13, day-by-day, lane-grouped + tier-scaled), **Weekends ahead**
(days 14–35 compressed to top-4 per weekend + a pointer to its digests/weekends/<Fri>.md file),
**Around town**, and **On the radar** (festivals / big shows /
tracked far-out). Run `python scripts/build_radar.py --md radar-candidates.md` first; it writes
`data/radar.json` (a deterministic signal heuristic — editorial / festival / tracked-artist /
arena), which `--consolidated` reads for the radar tier. The first two sections are the editor
**slate** — `assemble()` over the scored pool + verdicts (day-grouped, lane-diverse,
verdict-ranked). The **windowed `--from <date> --to <date>`** mode is retained as the per-weekend
look-ahead (one file per upcoming weekend, keyed by the Friday — the dashboard's per-weekend view
plugs into it). Either mode emits a canonical Markdown agenda (committable). The per-event
**curator notes + artist glosses come from Step-4 enrichment**, so the insider voice is baked in;
scoring is **precomputed** (read `score`/`rating`/
`reasons` — never hand-score; the taste profile below is just orientation for *why* things rank). On
top of the renderer you add a short conversational intro (fill the `<!-- tier3:intro -->` slot)
plus **the take** — a ONE-sentence high-level teaser written inside the invisible
`<!-- take: -->` comment slot (the feed build lifts it + the doc's date into
`front_page.take`; the dashboard's concierge chat opens with it, display-only — never sent to
the model) — and the sections the renderer doesn't generate (**Around town**, **On the
radar**) plus pinning/judgment. The full digest — NOT a wall of every event.
**Honor `digest.yaml` when present** — the reader's format prefs (`length` · `group_by` · `sections` ·
`max_picks_per_day` · `emphasis` · `tone` · `notes`). They reshape the structure below to taste
(presentation only; ranking is unchanged). `render_digest` already applies the `max_picks_per_day` cap
to the deterministic scaffold; you apply the rest in synthesis. **Token-cost guardrail:** a pref that
materially raises generation cost (`length: detailed`, every-event, big per-pick prose) — flag it and
offer a bounded version rather than silently ballooning the run; small/structural prefs just apply.

**Organize PRIMARILY BY DATE** (a day-by-day agenda is
the spine — it answers "what's on tonight / this weekend" at a glance). Structure:

1. **Tonight & tomorrow** — the next-48h index: top picks per night, one compact line each,
   with the voice pass's one-line *call* (what the move is — or an honest "stay in").
2. **Don't-miss** (3–6, cross-date) — the few worth building a week around; each with its date,
   price, a deterministic urgency chip (tiered pricing / TBA venue / free-RSVP), and a one-line
   *why*. Cross-date, non-chronological.
3. **What changed** — new-to-the-slate and updated events since the last pull, in one place
   (the scaffold omits it automatically when nothing moved).
4. **Day-by-day** — the body. One subsection per day in the window (`### Tonight — Tue 6/16`,
   `### Fri 6/19`, …). Under each day, list that day's on-taste events, best first, each:
   `[Event](link) — Venue (neighborhood) — time — price — short why/artist gloss`.
   - Collapse quiet days and runs ("### Mon 6/22–Thu 6/25 — quieter midweek").
   - Group within the day by **slate lane** (the renderer already does: **Electronic & dance**,
     **Live music**, **Film**, **Comedy & stage**, **Elsewhere**, with afters/day-party/big-room
     chips inline) — the day stays the top-level unit.
   - Tier-scaled: must-see/great get the full two-line entry, solid a compact one-liner, the
     tail one collapsed "Also:" row — the verdict decides how much page an event gets.
   - Lead each day with the electronic/house/techno (the priority lane); film/live/etc. follow.
   - Comedy appears inline on its day ONLY if a `comedians_loved` name is playing.
   - **Daytime/lifestyle on its day too**: recurring markets (from `recurring.yaml` — compute
     which fall on each day; Silver Lake Farmers Market = Tue/Sat is local + high priority) and
     any one-off pop-ups / brand activations / block parties surfaced by the editorial sources
     (Eater LA, UncoverLA). A weekend day might end with a **Daytime/markets** label.
   - Mark warehouse/TBA-location and "lineup TBA"; note 35mm/70mm for film.
5. **Around town** — GENERAL LA context, not ticketed picks: what's in the air citywide
   (e.g. FIFA World Cup 26 matches at SoFi + watch parties, big sports, street fairs, museum
   free days). From the DiscoverLA weekend roundup + LAist. 2–5 short lines.
6. **On the radar** — big events months out, from `festivals.yaml` + a quick live web lookup
   each run. SHORT and plain (no bold/hype), **relevance-driven, not list-driven**: surface an
   item only when there's an actual ticket-timing reason (on-sale/presale opening, prices
   climbing, low stock, selling out, sold out, lineup just dropped). If nothing's time-sensitive,
   a line or two is plenty; dormant entries stay in `festivals.yaml`. Lead most on-taste + urgent.
7. Footer: ops only — sources that failed/were skipped this run, plus any token-expiry banner
   (the renderer already places these; never restate them in the intro).

**ALWAYS hyperlink the event** to its ticket/info URL when the catalog has one (it usually
does — links live on each record). Keep editorial-mention badges inline, e.g. "(LAist pick)".

**Pin named favorites.** When the user has called out a specific event/series/venue as a
recurring favorite (e.g. **Sunset Sessions @ Golden Hour / Level 8** — a rooftop-vinyl-house
night he likes; noted in the `taste.yaml` feedback log), surface it when it's on,
even if its raw score is modest. It's one kind of event he's into — worth including, not the headline.

**Artist-annotation layer (required).** Many lineup names are unknown to the user — so for
picks and notable lineups, add a short parenthetical or em-dash gloss explaining who the
artist/DJ is and WHY it's on-taste: genre, scene, label, or reference point
(e.g. "DJ Minx — Detroit house pioneer, Women on Wax"; "Antal — Rush Hour boss, Dutch
digger, deep/disco selector"; "Yaeji — NY/Korean house-pop, leftfield club"). Anchor to the
his core taste (rooftop/vinyl/groove/European/fabric-style) where it fits. Use your own
knowledge; web-check only genuinely unknown names. Don't annotate household names.

### Taste profile (ranking weights)

- Core lane: rooftop / vinyl / groove / house with a European feel — e.g. Sunset Sessions at
  Golden Hour DTLA is one example. Optimize toward that energy.
- **High**: house / techno / acid / electro DJ events (mainstream AND underground);
  "fabric London"-style club nights / European-leaning lineups; rooftop / sunset / daytime
  open-air house, disco, Balearic, groove; vinyl-only / listening-bar sets; warehouse &
  afterhours parties; rep & arthouse cinema (Vidiots, Vista, Brain Dead, Cinematheque, New Bev)
- **Medium**: small rock/indie/garage/dream-pop club shows (Troubadour, Echo, Zebulon,
  Moroccan, Lodge Room); live-electronic acts; daytime & lifestyle — flea/vintage/design
  markets, farmers markets (esp. Silver Lake/eastside), food & drink pop-ups, brand activations
  / block parties; record fairs / listening bars; craft beer; theater (Pantages + black-box)
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
- `taste.yaml` — ranking config (re-read every run). Has the core taste, weights, and
  `comedians_loved` (the comedy exception list).
- `digest.yaml` — per-person digest FORMAT prefs (`length`/`group_by`/`sections`/`max_picks_per_day`/
  `emphasis`/`tone`); presentation only, not ranking. Read at render + synthesis; `render_digest`
  honors the `max_picks_per_day` cap. Friends get `profiles/<name>/digest.yaml`.
- `festivals.yaml` — the "On the radar" curated list (festivals + big concerts months out);
  refresh status with a live web lookup each digest run.
- `recurring.yaml` — predictable recurring markets/happenings (farmers markets, fleas,
  Smorgasburg). At digest time, compute which occurrences fall in the window and drop them onto
  the right day in the day-by-day. One-off pop-ups/activations are NOT here — those come from
  the editorial webfetch sources (Eater LA, UncoverLA, Secret LA, DiscoverLA).
- `scripts/run_digest.py` — **the deterministic core**: fetch → dedupe → expire → score → writes
  `data/catalog.json` + `data/candidates.json`. `--no-fetch` re-scores after manual layering (Step 3).
  Run this instead of fetching/dedup/scoring by hand.
- `scripts/lib/` — shared modules: `scoring.py` (taste ranking, driven by `profile.yaml` + `taste.yaml`),
  `dedupe.py` (fuzzy merge), `pipeline.py` (transforms), `enrich.py` (enrichment cache), `config.py` (YAML),
  `affinity.py` (Spotify music layer), `feedback.py` (reactions → affinity), `tagging.py` (deterministic
  multi-axis tags — `type`/`genre`/`setting`/`vibe`/`region`, stamped onto every catalog record each run;
  its `VOCAB` is the controlled vocabulary the scene-researcher should refine within). Tested in `scripts/tests/`.
- `scripts/render_digest.py` — enriched candidates → the digest: a canonical Markdown agenda.
- `data/enrichment.json` — the accumulating scene-graph cache (event enrichment + artist notes); grows each run.
- `profile.yaml` — place/person config (ids, geo, scoring weights/terms/thresholds, `scoring.spotify`
  + `scoring.feedback` knobs); the city-portable knob.
- `scripts/fetch_spotify.py` — Spotify sync (Phase C): top/followed/recent → `data/spotify_affinity.json`
  (gitignored). Needs `SPOTIFY_CLIENT_ID`/`SECRET`/`REFRESH_TOKEN`; `--authorize` mints the token once.
- `data/feedback.jsonl` — append-only reaction log (loved/went/skipped/hide + implicit); folds into scoring.
- The structured fetchers below are invoked BY `run_digest.py`; the rest you run during Step 2 layering:
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
