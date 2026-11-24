# Source candidates — Discover mode

_Generated 2026-11-24 (previous pass: 2026-10-13). Review → approve → fold into `sources.yaml`,
then update `last_discovery`. Nothing below is in the registry yet except the Eventbrite auto-harvest._

## New this pass (2026-11-24) — electronic / live-jazz / art-performance / editorial

Three `source-scout` sweeps (WebFetch/WebSearch) + real-UA re-probes from the session (curl,
`fetch_dice.py`, TM Discovery). "Verified" = fetched today with dated rows on/after 11/24.

### Fetcher gap found (not a new source — a fix)

- **Blue Note Los Angeles (Hollywood, 6372 W Sunset)** — TM Discovery has **109 upcoming events**
  for venue id `KovZ917AYC-` (TicketWeb-backed; Kenny Garrett 11/26–29, Robert Glasper residency
  12/10–13, David Murray 12/21), and **0 are in the catalog**. Cause confirmed: the venue record
  has no DMA, so `fetch_ticketmaster.py`'s `dmaId=324` query returns `totalElements: 0` for it,
  while `venueId=KovZ917AYC-` returns all 109. Suggested fix: a small `extra_venue_ids:` list on
  the TM registry row that the fetcher queries by `venueId` in addition to the DMA sweep
  (also `KovZ917AVIl`, "B-Side at Blue Note Los Angeles", 1 event). Same class of hole may explain
  The Upstairs LA (TM id 90459, flagged 9/1). **Needs a go-ahead — it is a fetcher change.**
  Fallback if you'd rather not: `webfetch` row on https://www.bluenotejazz.com/la/ (p2).

### Proposed additions

| Name | Category | Method | Endpoint | What it lists (verified) | Rec |
|---|---|---|---|---|---|
| The LA Raver (upgrade existing `candidate` row) | electronic | webfetch (was `gmail`) | https://www.thelaraver.com/archive → `/p/<M>-<D>-los-angeles-rave-itinerary` | Public beehiiv archive, curl 200, weekly Wed issues 10/7→11/18. Per-day tables (event, venue, genre, ticket platform) + an "Afters" section. Carries Shotgun/Posh-only events absent from the catalog (Raw Cuts @ Under The Bridge 11/20, Seafood Rave, SXTCY, Dirty Laundry). Signal + gap-filler; venues often TBA | **ADD (p1), High** |
| Kiss Kiss Bang Bang (Koreatown) | electronic | dice | slug `kiss-kiss-bang-bang-la-w79p` | `fetch_dice.py` verified: 3 events — Club Joon 11/28, Paradisco 12/12 + 12/19. Overlaps RA/19hz partly | **ADD slug, High** |
| CAP UCLA (Nimoy / Royce / Freud) | multi | webfetch | https://cap.ucla.edu/calendar | ~25 dated shows through 5/2027: SPELLLING 12/12, Kronos 1/31, Helado Negro + Sō Percussion 2/10, Wild Up 2/20. No year on cards; no ICS/JSON-LD (curl-confirmed) | ADD (p2), High |
| REDCAT (DTLA) | theater | webfetch | https://www.redcat.org/calendar | Mindy Seu 12/11–12, Beckett "The Last Tape" 1/28–30, Perfume Genius × Kate Wallich 2/18–27. Month/day only; no feed (curl-confirmed) | ADD (p2), High |
| LAjazz.com Quick Calendar | live_music | webfetch | https://lajazz.com/ | Day-grouped jazz aggregator, ~3 days ahead + a few far rows. Only source seen carrying no-feed rooms (General Lee's jam, World Stage, Baked Potato, Cadenza). Fill/cross-check, not a catalog | ADD (p3), Med-high |
| 13ThingsLA (Hijinx Arts) | editorial | rss — signal only | https://hijinxarts.substack.com/feed | Valid RSS (20 items), weekly art-openings roundup, latest 11/17. Partly paywalled → headline-level signal | ADD (p3) |
| LA Insider — This Week in LA | editorial | rss — signal only | https://www.lainsider.news/feed | Valid RSS (20 items), Thursday art/culture roundup with venue + run dates in item body, latest 11/19 | ADD (p3) |
| Hammer Museum programs | multi | webfetch | https://hammer.ucla.edu/programs-events | Talks, UCLA Archive screenings, *A Page of Madness* w/ live benshi 12/5. Noisy (tours, kids Art Lab); no feed | Optional (p3) |
| Hotel Ziggy (WeHo) | live_music | ics | https://hotelziggy.com/?post_type=tribe_events&ical=1&eventDisplay=list | Valid ICS but only 2 events (We Found New Music 11/25, JUCCY 11/28). `TZID=UTC` is really local wall time → −8h bug unless handled | Optional (p3) |
| The Redwood Bar and Grill (DTLA) | live_music | webfetch | https://www.theredwoodbar.com/calendar | Month grid, punk/garage; ~41 rows already arrive via RA/19hz — gain is free/non-RA nights only | Optional (p3) |
| CurationsLA events feed | multi | rss | https://www.curationsla.com/feed.xml | ~50 events, no ticket URLs, UTC dates; mostly duplicates TM/RA. (Separate from the beehiiv newsletter row pending since 8/25) | Skip-leaning |
| Techno Airlines (LA) | electronic | webfetch | https://www.technoairlines.com/events/los-angeles | RA-derived (ticket buttons are ra.co links) — cross-check only | Skip |

Paste-ready YAML for every row is in the 2026-11-24 scout reports — ask to have it regenerated.

### Backlog verification (pending items re-tested today with `fetch_dice.py`, real Chrome UA)

| Slug | Result | Rec |
|---|---|---|
| `los-globos-a6w7` (pending 8/25) | **7 events** (Black Wednesday 11/25, Twerk Giving 11/27…) | verified → add |
| `el-cid-ven7` (pending 8/25) | **30 events** (Poom Poom Tuesday 11/24, ezcodylee 11/25…) | verified → add |
| `high-tide-6nk3` (pending 10/6) | **4 events** (Uplift 12/3, El Rumbón 12/5, Salsa con Sazón 12/11) | verified → add |
| `in-sheeps-clothing-dn8o` (pending 8/25) | 0 events | drop / re-check later |
| `golden-hour--level-8-g8w2` (pending 10/6) | 0 events | drop |
| `the-silverlake-lounge-wb2v` (commented out in registry) | 0 events | stays out |

### Status-change flags
- **Sunday Sessions LA** (pending 10/6, p1): page now shows a single date (Sun 11/29, venue TBA, Shotgun). Still worth adding, thin over winter.
- **Silverlake Flea** (`recurring.yaml`): silverlakeflea.com now says **1900 N Vermont Ave, Sat & Sun 9am–3:30pm** (next 11/28–29); the registry has 4561 W Colorado Blvd, Fri/Sat/Sun. Looks like a move to Los Feliz — **human call**, then update `recurring.yaml`.
- **Los Feliz Flea** (`candidate`): still running through 12/26 → promote to `active` (repeat of the 10/6 rec).
- **The Airliner**: theairliner.com redirects to a for-sale page; barairliner.com's calendar is stale (newest item NYE 2025), but RA/DICE still list nights there (Reflections 11/28, dublab 12/19). No first-party source.
- **Oh My Rockness** (`candidate`): the LA URL served NYC content — verify before wiring.
- **Restless Nites** (`candidate`): page is JS-rendered, no events in static HTML (curl 200, no JSON-LD).
- **Stage Red** (12 catalog rows) is in Fontana — out-of-area, not a source question.

### Unresolved — the Shotgun gap
Shotgun is the one platform the structured sources miss (LA Raver's 11/18 issue lists several
Shotgun-only events not in the catalog). **shotgun.live returned HTTP 429 to every request from
this environment** (scout and curl both), so no method could be confirmed. If a venue/organizer
page exposes Event JSON-LD, a `fetch_shotgun.py` with a curated slug list would mirror the DICE
design. Needs a probe from another network. Tixr (Day Trip, Space Yacht) 403s likewise. Until
then The LA Raver row is the practical catcher.

### Holiday-market one-offs (no feed; one-time capture if wanted)
A Current Affair 12/5–6 · In Todo craft fair 12/5 (Silver Lake) · Chocolate Dispensary night market
Sat 12/5, 12/12, 12/19 (Echo Park) · DTLA Proud holiday night market 12/6 · Unique LA 12/12–13 ·
MAUM Market 12/19 (ROW DTLA) · Merry Melrose Sundays 11/29–12/27 (existing Melrose Trading Post row).

### Rejected this pass
Pacific Electric (fully TM-backed, 25 rows already), Bu Tea Den (scattered ticketing, techno nights
via RA/19hz), The Miracle Theater, The Lexington (covered via Blind Tiger row + RA), Blue Whale
(no calendar yet — re-check Q1), Amoeba in-stores (none dated), Jazz at LACMA / Getty / Hammer JazzPOP
(seasonal, revisit April), Skylight, Book Soup, JANM, NHM, LACMA (`?ical=1` returns HTML, not ICS —
curl-confirmed), Skirball, Beer Paper LA (dead), Darling, Verse, Keys (no dated rows), Partiful, Luma,
Humanitix, Vinyl Room @ Palladium (TM). Beer/food lane: no viable source found. No new IG-only finds.

### Also this pass (already committed, no approval needed)
Eventbrite `--scan-catalog`: added **Vintage Synthesizer Museum**.

## Previous pass (2026-10-13) — comedy / rep cinema / live / theater

Scout had WebFetch/WebSearch only (no DICE slugs verifiable). Eventbrite `--scan-catalog`: no new organizers.
Not yet in `sources.yaml` — approve, then add and bump `last_discovery`.

| Name | Category | Method | Endpoint | What it lists | Rec |
|---|---|---|---|---|---|
| The Comedy Bureau (LA shows) | comedy | ics | https://thecomedybureau.com/?post_type=tribe_events&tribe_events_cat=los-angeles-shows&ical=1&eventDisplay=list | ~25 LA venues (Fable, Edendale, Scribble, Lyric Hyperion, Pack, UCB Franklin, Mayan…). **30-event cap/request → fetch_ics needs `&tribe-bar-date=` date-stepping (~every 3 days) + UID dedupe**; drop Online/non-LA | ADD (p1), High |
| Whammy! Analog Media | film | scrape/webfetch | https://www.whammyanalog.com/whammy-events | 16mm/VHS/found-footage screenings, ~18 through 11/6; no year in dates, no ticket links; skip workshops | ADD (p2), check JSON-LD on event page |
| Akbar (Silver Lake) | live_music | webfetch | https://akbarsilverlake.com/upcoming-events/ | Disco/funk/drag nights, month-bound (Oct posted) | ADD (p2) |
| A Noise Within (Pasadena) | theater | scrape | https://www.anoisewithin.org/upcoming-events/ | Per-performance rows + ticket links; ~15 rows already in catalog (likely TM) | ADD (p3) |
| Geffen Playhouse | theater | webfetch | https://www.geffenplayhouse.org/shows/ | Run ranges only; low taste weight | Optional |
| L.A. Rep-port (Battleship Pretension) | editorial | webfetch signal / newsletter | https://battleshippretension.com/ | Weekly rep-cinema roundup; 403 to WebFetch (unverified) | Optional signal |

Full paste-ready YAML snippets for these are in the 2026-10-13 scout report (notes carry fetch caveats above).

### Status-change flags
- **Lodge Room** (`flaky`): page now reads cleanly via WebFetch (Oct–Nov, real artists) → recommend `active`, method `webfetch`.
- **Harvard & Stone** (`flaky`): contradicts the 10/6 "dead" rec — page lists current dates 10/13–10/27 plus a few stale prior-month cells. Keep `flaky` or `active` with a past-date filter. **Human call.**
- **Lumiere Cinema** (`candidate`): Veezi token unrecoverable → `scrape` lumieretickets.com schedule (unconfirmed).
- Echo/Echoplex confirmed active (links are all TM → expect heavy dedupe). American Cinematheque stays flaky.
- Rejected: Lyric Hyperion (calendar abandoned; covered by Comedy Bureau), Secret Movie Club (no upcoming), Peppermint Club/Comedy Chateau (via TM), Ice House (no calendar). Unreachable, retry with real UA: Flappers, UCB LA, Bootleg, Satellite, Hi Hat, Ace.

## New this pass (2026-10-06)

Scout had WebFetch/WebSearch only: DICE slugs below are **unverified** (DICE 403s WebFetch) — run
`fetch_dice.py` with the real UA before merging.

| Name | Category | Method | Endpoint | What it lists | Confidence |
|---|---|---|---|---|---|
| Sunday Sessions LA (Vinyl Only) | electronic | webfetch | https://www.sundaysessions.la/events | Weekly vinyl-only open-air house/tech Sunday series, 1746 N Spring St DTLA; ~8 dated Sundays (10/11–11/29) w/ lineups + Shotgun links. RA/19hz carry only 1 wk w/ venue "TBA". Core taste. | High — **ADD** (priority 1) |
| High Tide (DTLA) | electronic | dice `high-tide-6nk3` | dice.fm/venue/high-tide-6nk3 | Vinyl nights/day parties/disco; ~4 rows already in catalog via RA/19hz | Medium-high (verify) |
| Golden Hour @ Level 8 | electronic | dice `golden-hour--level-8-g8w2` | dice.fm/venue/golden-hour--level-8-g8w2 | Sunset Sessions rooftop (named favorite); Level 8 already via Eventbrite organizer | Medium (may be 0) |
| ROW DTLA events | market | webfetch | https://www.rowdtla.com/events | Vintage fairs, sample sales, pop-ups; noisy (workshops) | Medium (priority 3) |
| LA/Smorgasburg record fairs | market | recurring.yaml | — | Monthly record fair; venue/cadence sources disagree (Smorgasburg 3rd Sun at ROW most reliable) | Low-medium — human call |
| HOUSE·LA | editorial | webfetch (signal) | https://housemusicla.com/ | Deep/afro-house calendar; overlaps RA/19hz | Low — skip |

Ready-to-paste snippets: `high-tide-6nk3` and `golden-hour--level-8-g8w2` under the DICE `venues:` list;
new `webfetch` rows for Sunday Sessions (`status: candidate`, priority 1) and ROW DTLA (priority 3).

### Status-change flags
- **Los Feliz Flea** (`candidate`): server-rendered dated Saturdays through 11/7 → promote to `active`.
- **Harvard & Stone** (`flaky`): only a past 9/28 entry on the calendar; escalate-to-dead date (9/22) passed → recommend `dead`.
- **Bar Franca** (`candidate`): Squarespace calendar abandoned (newest 12/14/24) → downgrade to `manual`.
- **Eater LA** (`flaky`): WebFetch refuses outright; keep flaky.
- Rejected: LP Vinyl Bar, Homage Brewing, Grand Central Market, downtownla.com, STILE/Somewhere Special. Re-probe Circle Bar (503).
- Gap-mine: Moroccan Lounge (via TM), Dusty Vinyl (via LOVE&REVENGE EB organizer) already covered; nothing else actionable.

## Still pending from 2026-09-01 / 2026-08-25 (unapproved)

(see prior sections below)

then update `last_discovery`._

## Still pending from 2026-08-25 (nobody has approved/merged these yet)

| Name | Category | Method | Endpoint | What it lists | Confidence |
|---|---|---|---|---|---|
| Los Globos | electronic/live_music | dice — extend existing venues: list | slug `los-globos-a6w7` | Silver Lake club — A Club Called Rhonda, house/indie-electronic | High (pattern-match; not yet fetched w/ real Chrome UA) |
| El Cid | live_music | dice — extend existing venues: list | slug `el-cid-ven7` | Echo Park — flamenco/tapas + indie/variety | High (pattern-match; not yet fetched w/ real Chrome UA) |
| In Sheep's Clothing HQ | electronic | dice — extend existing venues: list | slug `in-sheeps-clothing-dn8o` | WeHo vinyl/analog listening-party collective — core-taste fit | High (pattern-match; not yet fetched w/ real Chrome UA) |
| Akbar (Silver Lake) | live_music/electronic | scrape | https://akbarsilverlake.com/upcoming-events/ | Fountain & Sunset DJ bar, in-neighborhood — Funk That! (groove/house), disco-underground, drag | Very high — confirmed server-rendered w/ real dates |
| Whammy! Analog Media | film | scrape | https://www.whammyanalog.com/whammy-events | ~55-seat Echo Park/Silver Lake microcinema — 16mm/found-footage/VHS-era, several/week | Very high — confirmed server-rendered w/ real dates |
| The Comedy Bureau (LA shows) | comedy | ics | https://thecomedybureau.com/?post_type=tribe_events&tribe_events_cat=los-angeles-shows&ical=1&eventDisplay=list | ~40 indie LA comedy shows/week (The Elysian, The Fable, Lyric Hyperion, Largo…) | Very high — real ICS export confirmed |
| CurationsLA | editorial | webfetch | https://curatedla.beehiiv.com/ | Weekly "Events: Week of…" LA roundup + pop-ups/openings, public no-login archive | High |

Ready-to-paste `sources.yaml` snippets are in the 2026-08-25 source-scout transcript — ask if you
want them regenerated.

**Resolved since last pass:** ORIGIN Los Angeles (the Arts District club noted as "not yet
ticketing" on 8/25) is now selling via Eventbrite and was picked up automatically by today's
`fetch_eventbrite.py --scan-catalog` organizer-harvest — no longer needs a manual add.

## New this pass (2026-09-01)

### Gap-mining

Sampled venue/organizer frequency across the catalog (3,928 events) against `sources.yaml`.
**Every recurring venue/promoter found is already covered** by an active structured source —
mostly Resident Advisor and 19hz. Checked and confirmed no action needed: 1720, The Bridge, Que
Sera, El Cid, The Redwood Bar And Grill, Community (Berlin), Dirt Dog Compound, Boomtown Brewery,
Sound Nightclub, Academy Nightclub, The Spotlight, Exchange, Time Nightclub (Costa Mesa); Stereo
Punks, Hump Events, Midnight Lovers, Azure SoCal, Into The Woods LA, Green Life Ent, Factory 93,
FNGRS CRSSD, Brownies & Lemonade, Melt Collective, Lights Down Low, TUNNEL. A genuinely useful
negative result — RA + 19hz are carrying the electronic/warehouse lane well; no new dedicated
fetcher would add meaningful incremental coverage there right now.

### Proposed additions

| Name | Category | Method | Endpoint | What it lists | Confidence |
|---|---|---|---|---|---|
| The Upstairs LA (DTLA comedy club) | comedy | eventbrite | https://www.eventbrite.com/o/the-upstairs-comedy-club-108469330261 | New DTLA club (opened 5/1/26, debuted with Dave Chappelle); regular showcases. Has a TM venue page (id 90459, TicketWeb-backed) but 0 rows currently reach the catalog via TM — same FrontGate-style propagation gap already documented elsewhere. Also sells via Tixr. | Medium-high |
| Centerfold Market (Fairfax vintage/maker flea) | market | eventbrite | https://www.eventbrite.com/e/centerfold-market-tickets-1988367028307 | Curated pop-up flea at 716 N Fairfax Ave (LouLou Brazill & Violet Getty). Dated, irregular listings — not weekly, so a fetched source rather than a `recurring.yaml` cadence. Organizer `/o/...` URL not yet resolved — needs one `fetch_eventbrite.py --harvest` pass on the event URL. | Medium |
| DoLA (dolosangeles.com) | editorial | gmail (newsletter) | https://dolosangeles.com/p/newsletter | Broad LA "what to do" aggregator/newsletter (concerts, comedy, LGBTQ+, food/drink) that surfaced independently across multiple unrelated searches this pass. Site hard-403s WebFetch (bot wall, same symptom as KCRW) — don't scrape directly; subscribe + route via Gmail "Events" label instead. Likely heavy overlap with LAist/Time Out/Secret LA — low-priority supplemental signal at best. | Low-medium |

Ready-to-paste `sources.yaml` snippets are in the 2026-09-01 source-scout transcript — ask if you
want them regenerated.

### Status-change flags for existing entries

- **Harvard & Stone** (`flaky`, escalate-to-`dead` 2026-09-22): re-probed today — `/events/` now
  shows current September 2026 dates (stale-cache symptom from 7/17–8/22 appears cleared). One
  oddity: listed a "Sept 31" entry (nonexistent date) — a recurring-event date-generation quirk.
  Recommend one more clean automated fetch to confirm before flipping back to `active`.
- **Dirty Epic** (`flaky`, parked-domain note): re-probe today returned no retrievable content —
  inconclusive, leave as `flaky`.
- **Restless Nites** (`candidate`, "verify current activity on first run"): not re-verified this
  pass — still open for a future Discover run.

### Open questions for the approval call

- **The Upstairs LA**: also worth a look on the Ticketmaster side — it has a TM venue ID (90459)
  that isn't surfacing rows; may be a `fetch_ticketmaster.py` filter issue rather than a true
  white-label gap, separate from just adding the Eventbrite organizer.
- **Centerfold Market**: needs one `fetch_eventbrite.py --harvest <event URL>` run to resolve the
  organizer URL before it can be added as a standing source.
- **DoLA**: judgment call — a third general-aggregator newsletter given LAist + Time Out + Secret
  LA + Discover LA already cover this lane. Lean toward skipping unless it turns up something
  unique.
- No IG-only finds this pass requiring the flyer-capture reminder.

## Also this pass (already committed, no approval needed)

Eventbrite organizer auto-harvest (`--scan-catalog`, precise per-event signal, not a Discover
proposal per CLAUDE.md): added **Soundflow LA**, **The Regent Theater**, **UPEND**, **Enfuze**,
**ITAI & Friends**, **City Of Monterey Park**, **Wasted Presents**, **ORIGIN**, **SBCLTR**,
**COSRAVES**.
