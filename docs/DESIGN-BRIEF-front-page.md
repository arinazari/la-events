# Design brief — la-events front page (feed to Claude Design)

**What this is:** a re-design brief for `dashboard/index.html`'s home view. The current front
page is a linear ranked table — a database view. The product's judgment layer (editor tiers,
insider whys, city-pulse, radar) now exists in the data; the front page should *show the
judgment*, not the spreadsheet. Paste the sections below into Claude Design as the brief;
each module lists the data it binds to (already in `dashboard/data.json` unless noted).

## Principles (apply to everything)

1. **Emphasis by judgment, not position in a list.** The editor's tier is the visual
   hierarchy: must-sees are big, solids are rows, skips don't render on the home view.
   The linear all-events table stays — demoted to an "Everything" tab (the database view).
2. **The voice is a design material.** The one-line whys ("SMD pairing Servito and Kendig is
   a real one…") are the most differentiated asset — set them as readable card copy, not
   truncated grey metadata.
3. **Two visual registers, honestly separated:** *ranked for you* (taste sections) vs.
   *around the city* (not taste-ranked — city-pulse, visibly muted/neutral so the two are
   never confused).
4. **Phone-first.** Rails scroll horizontally, cards are thumb-sized, the page is useful in
   the first viewport (today + don't-miss) without scrolling.

## Modules, in page order

### 1. "Tonight / This weekend" lead
Time is the first question. A compact hero band: **Tonight** (top 3–4 by `final_rank` where
`iso_date` = today), then **Fri / Sat / Sun** chips that jump-scroll to those days. Each item:
time chip, title, venue·hood, tier dot.
*Binds to:* `events[].iso_date/start/final_rank/verdict.tier`.

### 2. Don't-miss shelf (the editorial cards)
The 6-slot shelf as large cards — date chip, linked title, venue, **the why as the card
body**, tier badge (`must-see` styled hottest). This is the same selection the digest's
Don't-miss section makes: tier-primary, multi-night runs collapsed.
*Binds to:* `events[]` sorted (verdict.tier, score+adjust); why = `enrichment.curator_note`
∥ `verdict.why`.

### 3. Lane rails (the type groupings)
Replace the single list with horizontal rails per lane, each ranked by `final_rank` within
the lane: **Electronic & dance** (optionally sub-chipped underground / afters / day /
mainstream — the `lane` field), **Live music**, **Film & rep cinema**, **Comedy & stage**.
Rail cards are mid-size: title, venue, date/time, one-line gloss when present, 🆕/↻ badges.
*Binds to:* `events[].lane` / `tags.type`, `final_rank`, `enrichment.description`,
`first_seen/updated_at`.

### 4. Around town — the city pulse (NOT taste-ranked)
The "make LA feel alive" strip: LA Marathon, an arena tour, a night market, a block fest.
Visually distinct from the taste sections (neutral palette, smaller rows, a "so you stay
apprised" caption), date-grouped one-liners with signal chips (*civic · festival · arena ·
editorial*).
*Binds to:* `data/around_town.json` (small wiring: stage it beside the feed at deploy, or
fold into `data.json` at build).

### 5. Plan ahead — On the radar
Month-grouped horizon (Aug · Sep · Nov…): festivals, big tours, tracked artists. Cards carry
urgency chips where known (**on sale · lineup pending · selling fast**) — ticket-deadline
urgency is the reason this section exists.
*Binds to:* `data/radar.json` signals (same staging note as #4); urgency states from
`festivals.yaml` `status:` (small wiring to fold in).

### 6. Standing plans — repeating & seasonal (new function)
The requested recurring/seasonal browse: a grid of *cadence cards*, keyed by rhythm rather
than date — "**Every Monday** · very good mondays @ Gold Diggers", "**Sundays, open air** ·
Sunday Sessions vinyl", "**Weekend mornings** · flea/farmers markets", "**Seasonal** ·
Bowl season · Dodgers homestands · Knott's Scary Farm (Oct)". A card opens the run's
upcoming dates.
*Binds to:* `recurring.yaml` (exists, not yet in the feed) + a small residency detector the
build already half-has (`collapse_runs` groups same title+venue across dates; ≥3 dates ≈ a
standing plan). Smallest real build item in this brief — flag it as such.

### 7. The scene layer, surfaced ("who's this?")
Anywhere an artist with a cached bio appears, their name is a chip → tap/hover shows the
insider note ("Antal — Rush Hour boss, Dutch digger"). This is the uncover-the-artist-
before-the-show feature made visible; it also makes the accumulating scene graph *felt*.
*Binds to:* `events[].enrichment.artist_notes[]` (already folded into every feed).

### 8. Ambient state (small, everywhere)
- **Freshness line** in the header: "Updated Tue 7/9 · 182 new" (`catalog_meta.json`).
- **New since last visit** filter chip (`first_seen` vs. a localStorage timestamp).
- **Stars** (Track A, design for it now): a star affordance on every card; friends' stars
  render as tiny avatars/initials — "★ Lori" — the one social element.

## What NOT to change
The Explore/"Everything" table (the database view), the per-event expanded detail (ICS
export, why-math, links), the digest popup, Settings. This brief is the home view only.

## Build-note summary (for whoever wires the design)
Already in the feed: tiers/whys/lanes/final_rank/artist notes/freshness/🆕. Small wiring:
stage `around_town.json` + `radar.json` next to the feed (or fold at build), fold
`recurring.yaml` + a ≥3-dates residency detector into a `standing[]` block, fold
`festivals.yaml` `status:` into radar items. Nothing here needs new LLM output.
