# Design brief — la-events front page, de novo concept (feed to Claude Design)

**What this is:** a ground-up design concept for `dashboard/index.html`'s home view,
designed from what the product actually is — an *editor with judgment* (tiers + written
whys), an *accumulating scene graph* (artist/scene intelligence), and a *city pulse*
(stay-apprised breadth) — rather than from a taxonomy of categories. The current front page
is a ranked table; a linear list has no opinion. This page should feel like it was **made
this morning, for you, by someone who knows the city**.

---

## Lead concept — "THE MARQUEE": your daily city edition

**Metaphor:** a great city paper's front page, printed fresh daily for a readership of one
(plus friends). Not a feed, not a grid — an *edition*. Editions have judgment (something
leads), rhythm (daily), voice (decks and captions), and an end (finite, digestible — the
opposite of an infinite scroll). Every mechanism below already exists in the data; the
paper metaphor just finally shows it.

### The page, top to bottom

**1 · Masthead.** "LA — Thursday, July 10 · Edition No. 34" + one status line ("Updated 6am ·
182 new listings"). The edition number is the fun: it says *this is today's paper*, a ritual,
not an app you check. (Binds: `catalog_meta.json` fetched_at/added; edition no. = days since
launch.)

**2 · The Lead.** ONE story above the fold — the single highest-conviction thing in the next
~72h, full-bleed card: headline-set title, a real *deck* (2–3 sentences of the insider why),
date/venue/price, tier badge. Category-agnostic by design: a 70mm Nolan print leads over a
club night if the editor says so — that's judgment-led hierarchy, the anti-list. Two or
three **secondary front-page stories** sit beside/below it at half size.
(Binds: `verdict.tier` + `score+adjust` pick the lead; deck = `enrichment.curator_note` ∥
`verdict.why`.)

**3 · The Wire.** A thin ticker strip — city-pulse one-liners in newsroom register, visually
a wire service, explicitly *not ranked for you*: "LA Marathon closes Sunset Sun AM ·
Bowl season opens tonight · HARD Summer single-days on sale." Tap → detail.
(Binds: `around_town.json` signals + `festivals.yaml` on-sale statuses.)

**4 · Dispatches — this week's storylines (the real functional change).** The middle of the
page is 3–5 *beats that change daily*, not fixed sections: emergent groupings written as
headlines over clusters —
- "Saturday's warehouse circuit is stacked" (5 afters cluster on one night)
- "August rep calendars just dropped" (a burst of 🆕 in one lane)
- "Two tracked artists announced LA dates" (radar tracked-signal cluster)
- "Quiet week for bands — the action is outdoors" (an honest thin-lane note)
Each dispatch = headline + one voice sentence + its 3–6 events as compact rows. Organization
is *narrative*, computed from what's actually happening — density spikes, 🆕 bursts,
tracked-artist hits, weekend shape — so the page is different every day, which is what makes
it fun to open. (Binds: deterministic clustering over `lane`/`iso_date`/`first_seen`/radar
signals proposes the clusters; the existing Tier-3 voice pass writes the headlines — same
slot-marker contract as the digest, LLM voices but never selects.)

**5 · The Scene Pages.** The back half: a short column per *scene you run in* — not
categories but taste-communities the scene graph already models: *Vinyl & groove · Warehouse
& afters · Rep cinema · The band rooms*. Each column: its week in 3–4 rows, its **standing
rituals** folded in as a footer line ("every Sunday: vinyl open-air · Mondays: very good
mondays"), and its tracked-artist chips. Recurring/seasonal events live *inside their scene*
as rituals rather than in a separate section — a scene is a place you return to; its rhythm
belongs to it. (Binds: `lane`/`tags` map to scenes; rituals = `recurring.yaml` + the ≥3-dates
same-title+venue residency detector; chips = `enrichment.artist_notes`.)

**6 · Coming Attractions.** The horizon as a poster row — month-labeled cards (Aug · Sep ·
Nov) for festivals/tours worth planning around, with on-sale urgency flags. (Binds:
`radar.json`.)

**7 · The Back Page.** One quiet link: "All 3,600 listings →" — the Everything table (the
database view, unchanged). The paper is finite; the archive is behind it.

**Marginalia (small, everywhere):** artist names as tappable "who's this" chips with the
insider bio; ★ marks in the margin where a friend starred something (Track A-ready); a tiny
"corrections" box for ↻ changed listings — the newspaper joke that's also real function.

### Why this concept fits the mission
- **"An insider made this for me"** → an edition *is* authorship; the layout itself claims
  judgment. A grid claims neutrality — wrong message.
- **Digestible & fun** → editions end. Front page + dispatches + scene pages ≈ 25 events
  shown with voice, everything else one tap deeper.
- **City feels alive** → the Wire + daily-changing dispatches make the city read as weather:
  something is always moving, and the page proves it moved *today*.
- **Uncover artists** → who's-this chips + scene pages put the graph where your eyes are.

---

## Alternate concepts (if the Marquee doesn't land)

**A · "THE CONSTELLATION" — the city as a living map.** Night-dark stylized LA (abstract
neighborhood constellation, not a street map — the gazetteer's ~60 venues/neighborhoods as
points), events as lights: brightness = tier, color = scene, pulse = tonight. A time scrubber
sweeps tonight → weekend → next month and the lights re-arrange. Tap a glow → the card with
the why. Organization is *spatial + temporal*, no lists anywhere above the fold. Strongest
possible "LA feels alive"; the most novel visually; the most build risk (canvas/SVG scene,
though static-friendly since coords are in `lib/geo.py`'s gazetteer).

**B · "THE CIRCUIT" — scenes as characters.** The home page is 4–6 scene cards, each a
living entity with a *form meter* ("Vinyl & groove: strong week"), its lead pick, its
rituals, and its tracked artists — like following teams rather than reading listings. The
deepest embrace of the scene-graph moat (nobody else can render this page); weakest on
one-off/city-pulse content, which would need a small wire strip anyway.

---

## Build notes (for whoever wires the chosen design)
Already in the feed: tiers, whys, lanes, final_rank, artist notes, 🆕/↻, freshness. Small
wiring regardless of concept: stage `around_town.json`/`radar.json` beside the feed; fold
`recurring.yaml` + the residency detector into a `standing[]` block; fold `festivals.yaml`
`status:` into radar items. Marquee-specific: a deterministic dispatch-cluster proposer +
Tier-3 headlines (reuses the digest's slot-marker contract). Constellation-specific:
venue/neighborhood coords exported from `lib/geo.py` into the feed.
