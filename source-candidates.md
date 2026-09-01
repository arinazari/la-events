# Source candidates — Discover mode

_Generated 2026-09-01 (previous pass: 2026-08-25). Review → approve → fold into `sources.yaml`,
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
