# PROPOSAL — Programs vs. dated picks: one display model (2026-07-29)

**Status: proposal — awaiting Ari's call on the decision points at the bottom.**
Prompted by Ari (2026-07-29): movies shouldn't be featured except at opening — and even
then in the digest + a dedicated movie section, never the front page; theater, movies,
markets, and festivals (anything repeating/seasonal) should share ONE display treatment,
distinct from music events; big concerts should get that treatment too.

## What already exists (so we don't rebuild it)

The 2026-07-21/25 work shipped the building blocks, but not the unified model:

- **Series consolidation** (`lib/series.py`) — one card per program; films group
  cross-venue by core title, everything else by title+venue. Every rep card carries a
  full per-night dates board (`series` summary → the ALL DATES board).
- **Now running** shelf — opened runs with ≥3 remaining nights at ~weekly density
  spanning ≥14 days leave the dated surfaces; closing-fortnight re-entry.
- **The marquee** — a dedicated full-page movies view (Now playing / Opens soon /
  One-night screenings), client-only over data already in the feed.
- **Festivals & big shows** — the watch-list view over `festivals.yaml`
  (`front_page.festivals`), status chips (on sale / lineup pending / annual watch).

What's *not* true today, versus the ask:

1. **Movies still reach the front page** three ways: the hero row (a film run in its
   closing fortnight re-enters the dated pool, and `top_picks` has no type exclusion),
   the "Movies, comedy & theater" shelf (film is interleaved in), and "Now running"
   (film runs qualify by construction).
2. **The program treatment is fragmented**: theater seasons + standing markets →
   Now running; festivals → a separate view + radar; big concerts → dated cards on the
   "Arenas & halls" shelf; movies → all of the above plus the marquee. Four surfaces,
   four looks, one underlying idea.
3. **Big concerts are displayed like club nights** — dated pick cards — even though
   the shelf's own design note says they're "stay informed" items: announced months
   out, bought early, attended later. They behave like festivals, not like Fridays.

## The model — two display classes

Every feed row gets a deterministic, server-stamped **`program_class`**:

| class | what | examples | today's home |
|---|---|---|---|
| `dated` | one-off nights you pick a date for | club nights, small/mid live music, comedy, one-off plays | hero + lane shelves (unchanged) |
| `film` | any film program (runs AND one-nighters) | The Odyssey run, a New Bev one-off | culture shelf + hero + Now running |
| `run` | opened multi-night non-film runs / seasons | a Pantages season, a play's 3-week run | Now running |
| `recurring` | standing weekly+ cadence | Silverlake Flea, MUZIQUE Fridays | Now running (flagged "revisit") |
| `big-show` | arena/hall concerts (`live-music:big`) | an Usher stadium date | Arenas & halls shelf |
| `festival` | festivals.yaml + festival-tagged catalog rows | Portola, HARD Summer | Festivals view + radar |

**Class 1 (`dated`) keeps the current card treatment** — hero eligibility, lane
shelves, digest day sections. **Everything else is a *program*: one shared card
grammar** — a status chip (*Opens Fri 8/14* · *Thru Sun 9/6 · 12 nights* ·
*Every Sunday* · *On sale now* · *Sat 11/14 · on sale*), the span/cadence line, and
the dates board in the detail. Programs are ranked by **urgency** (closing-soonest /
opening-soonest / date-soonest), not by the two-zone rank that buries far-out seasons.

## Surface changes

### Front page
- **Hero + lane shelves draw from `dated` only.** Films excluded entirely — no
  closing-fortnight re-entry (that's marquee + digest news, not a front-page card).
  `live-music:big` leaves the shelves; the "Arenas & halls" shelf is retired.
  "Movies, comedy & theater" becomes **"Comedy & theater"** (one-offs only; a play's
  multi-night run is a program). "Markets, art & more" keeps only one-off art/
  community events — standing markets move to the program band.
- **One program band replaces "Now running"**, same component, three urgency-ordered
  rows (a row hides when empty):
  - **Now running** — opened `run` + `recurring` (theater seasons, standing markets),
    closing-soonest, cadence-aware labels ("4 Fridays", "Every Sunday").
  - **Big shows & festivals** — `big-show` + `festival`, soonest-first, on-sale
    status chips. The existing "Festivals & big shows" view becomes this row's
    full-page expansion and absorbs big-show reps (the view's name already
    anticipated this).
  - **The marquee →** — a door only. Zero film cards on the front page, ever.

### The marquee (movies)
Unchanged as a view — it becomes the *only* site surface where film cards render.
Openings surface as **Opens soon → Now playing**, which is exactly the "feature at
first release" moment.

### Digest
- Films leave the day-by-day body and Don't-miss. One **"On the marquee"** block:
  runs opening this week + (decision 3) notable one-night screenings. Openings are
  the only moment a film is *featured*; the marquee page carries the rest.
- Big shows + festivals consolidate in "On the radar" (this also closes the ROADMAP
  gap — the digest still doesn't read `festivals.yaml`; wire `load_festivals` into
  `build_radar`/`render_digest` in the same pass).
- Theater/market runs get a compact "Now running" digest block (span + closing
  dates), out of the day sections except opening/closing nights.

## Implementation shape (small, mostly server)

- `lib/assemble.py` (or a thin `lib/programs.py`): `program_class(ev)` from lane +
  tags + series summary — the same signals `_is_running` already reads. Stamped on
  every feed row by `build_dashboard`/`build_profiles`.
- `build_dashboard.build_front_page`: split the pool by class instead of the single
  `_is_running` carve-out; hero/shelves ← `dated`; emit `front_page.programs`
  ({nowrunning, bigshows} key-lists). `top_picks` itself stays untouched — the
  front-page caller filters its pool, and the digest's Don't-miss caller filters
  film the same way ("one policy, per-call knobs", per the 7/20 resolution).
- Client: render the program band with the existing run-card component; retire the
  film path from shelves/hero; festivals view gains the big-show reps.
- `render_digest`: the "On the marquee" + "Now running" blocks; radar folds
  festivals.yaml.
- Nothing changes in the catalog, dedupe, scoring, or verdict layers — this is
  presentation-layer routing over already-computed data.

## Decision points (Ari)

1. **Movie openings in Don't-miss?** Proposal says no — openings appear only in the
   digest's "On the marquee" block. Alternative: a truly exceptional opening (e.g.
   a 70mm event run) may still take a Don't-miss slot.
2. **Big concerts fully out of the hero?** Strict reading: yes — an arena date is a
   program, full stop. Softer knob: a *tracked-artist / high-affinity* big show stays
   hero-eligible (the Alanis lesson cuts this way — that's exactly the show a person
   must not miss seeing featured). Recommend the softer knob.
3. **One-night rep screenings** (New Bev/Cinematheque one-offs): digest-featured, or
   marquee-only? They ARE their own opening night. Recommend: marquee + a single
   digest line in "On the marquee", never a full entry.
4. **Program band vs. three separate surfaces** — proposal folds Now running +
   big-shows into one band with the marquee as a door. Alternative: keep Now running
   as-is and only add a big-shows row. Recommend the unified band (one grammar).
