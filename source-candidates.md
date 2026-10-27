# Source candidates — Discover mode


_Generated 2026-10-27 (previous pass: 2026-10-13). Eventbrite `--scan-catalog` auto-added 2 organizers (Inland Empire 80s, Masked Superstar Events). Nothing below is in `sources.yaml` yet; approve, then add and bump `last_discovery`._

## New this pass (2026-10-27) — live music / art nights / community

Scout had WebFetch/WebSearch only (no DICE slugs, no JSON-LD visibility).

| Name | Category | Method | Endpoint | What it lists | Rec |
|---|---|---|---|---|---|
| DTLA ArtNight | general | ics | https://www.dtlaartnight.com/artnight.ics | Free monthly gallery/museum night (~50 stops, trolley, free concert, night market). Feed is ONE rolling VEVENT, no RRULE (next 11/5 6pm PT, DTSTART in UTC). Alt: recurring.yaml (first Thu). | ADD p1, high; human call on ICS vs recurring |
| Blue Note Los Angeles | live_music | webfetch | https://www.bluenotejazz.com/la/ | Nightly jazz/R&B/hip-hop, ~4 wks out; likely overlaps TM | ADD p2, high |
| Grand Performances | live_music | squarespace | https://grandperformances.org/events | Free outdoor Jun-Sep season; upcoming[] empty until ~May 2027 | ADD p2, seasonal |
| Skirball Cultural Center | general | webfetch | https://www.skirball.org/calendar | Paginated by 10 days (`/calendar/YYYY-MM-DD`); ~half kids/classes, filter | ADD p3, medium |
| The Bellwether (DTLA) | live_music | webfetch | https://www.thebellwetherla.com/ | ~60 shows to May 2027, mostly TM dupes; value is Camille's room | Optional p3 |
| Oh My Rockness (LA) | live_music | scrape | https://www.ohmyrockness.com/shows?city=los-angeles | Unverified (WebFetch returned NYC) | Needs real-UA check |

Paste-ready YAML for the first four is in the 2026-10-27 scout report (same fields as above).

### Status-change flags
- **Cinespia** (`candidate`): Halloween weekend live (10/30, 10/31) → promote to `active`, drop to p3 after 10/31.
- Echo/Echoplex: TM ticketing, expect heavy dedupe. Zebulon: DICE is the only path.
- Rejected: Jazz at LACMA (skip until May 2027), Getty, LACMA, MOCA, Autry, Natural History Museum, Hotel Cafe (stale), bluewhale.net (dead), Downtown Art Walk (IG-only).
- Unreachable from here: Hammer (503), culture.lacity.gov / calendar.lacity.org / Music Center (403), Hi Hat, Teragram, Broad. Residential-IP probe of `culture.lacity.gov/events/?ical=1` is the next step for library/park series.
- Manual captures: Grand Park Noche de los Muertos Sun 11/1 3-7pm (grandparkla.org/diadelosmuertos).

## New this pass (2026-10-13) — comedy / rep cinema / live / theater

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
