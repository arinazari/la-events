# Source candidates — Discover mode

_Generated 2026-08-25. Review → approve → fold into `sources.yaml`, then update `last_discovery`._

## Gap-mining (catalog venues with no registry row)

Most recurring venue names already flow in via existing structured pipelines (TM/RA/Goldenvoice/
DICE/19hz) even without their own row — not gaps. Promoter-based gap-mining wasn't usable this
pass (`organizers` is null on every sampled catalog row).

Checked and **no action needed** (already adequately covered):
- Blue Note Los Angeles — already on Ticketmaster (dmaId 324)
- Boardner's by La Belle / Bar Sinister — TM-adjacent ticketing already flows in
- Matriarch LA (Koreatown rooftop-for-hire) — scattered promoters better caught by the existing
  Eventbrite `--scan-catalog` harvest than a dedicated row
- Ostbahnhof, Another Castle, "The Foundry" (underground collectives) — ticket exclusively via RA,
  already inside the active RA source

## Proposed additions

| Name | Category | Method | Endpoint | What it lists | Confidence |
|---|---|---|---|---|---|
| Los Globos | electronic/live_music | dice — extend existing venues: list | slug `los-globos-a6w7` | Silver Lake club — A Club Called Rhonda, house/indie-electronic | High (pattern-match; not yet fetched w/ real Chrome UA) |
| El Cid | live_music | dice — extend existing venues: list | slug `el-cid-ven7` | Echo Park — flamenco/tapas + indie/variety | High (pattern-match; not yet fetched w/ real Chrome UA) |
| In Sheep's Clothing HQ | electronic | dice — extend existing venues: list | slug `in-sheeps-clothing-dn8o` | WeHo vinyl/analog listening-party collective — core-taste fit | High (pattern-match; not yet fetched w/ real Chrome UA) |
| Akbar (Silver Lake) | live_music/electronic | scrape | https://akbarsilverlake.com/upcoming-events/ | Fountain & Sunset DJ bar, in-neighborhood — Funk That! (groove/house), disco-underground, drag | Very high — confirmed server-rendered w/ real dates |
| Whammy! Analog Media | film | scrape | https://www.whammyanalog.com/whammy-events | ~55-seat Echo Park/Silver Lake microcinema — 16mm/found-footage/VHS-era, several/week | Very high — confirmed server-rendered w/ real dates |
| The Comedy Bureau (LA shows) | comedy | ics | https://thecomedybureau.com/?post_type=tribe_events&tribe_events_cat=los-angeles-shows&ical=1&eventDisplay=list | ~40 indie LA comedy shows/week (The Elysian, The Fable, Lyric Hyperion, Largo…) | Very high — real ICS export confirmed |
| CurationsLA | editorial | webfetch | https://curatedla.beehiiv.com/ | Weekly "Events: Week of…" LA roundup + pop-ups/openings, public no-login archive | High |

Ready-to-paste `sources.yaml` snippets (DICE `venues:` extension + 4 new standalone entries) are
in the source-scout agent transcript from this run — ask if you want them regenerated.

## Watch — not yet ticketing

- **ORIGIN Los Angeles** — new Arts District club (613 Imperial St; SBCLTR/Minimal Effort team),
  opening late summer/fall 2026. RA club page provisioned (`ra.co/clubs/296836`) but 0 events.
  Re-probe next Discover pass once it's ticketing.

## Notes for the approval call

- Comedy is a low-priority taste lane (skip except `comedians_loved`) — The Comedy Bureau is
  proposed at `priority: 3` rather than 1/2; say if you'd rather leave it out and hand-check for
  named comedians only.
- CurationsLA is broad/lifestyle like the DiscoverLA weekend roundup — needs the same
  "extract what's on-taste, don't dump the newsletter" discipline at digest time.
- The 3 DICE slugs are high-confidence by pattern/venue-name match (also show up on RA) but
  haven't been fetched with `fetch_dice.py`'s real Chrome UA yet — verify content on first real run.

## Also this pass (already committed, no approval needed)

Eventbrite organizer auto-harvest (`--scan-catalog`, precise per-event signal, not a Discover
proposal per CLAUDE.md): added **Chai Rave**, **it's just noize.**, **Fesser and Friends Inc.**
