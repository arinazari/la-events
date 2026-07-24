# Audit — 2026-07-24 front-end redesign: dropped / broken / worsened features

**Context.** The "Front end redesign: new front page, detail modal, settings — live-wired"
(commits `392a7f7` + `9d3b70b`, 2026-07-24) rewrote `dashboard/index.html` from ~5314 lines to
~1370. It is **not** a framework swap — old and new both run the same `dc-runtime` (React under
`support.js`); it is a template rewrite of the app's logic block. In the rewrite a large set of
features that had been carefully re-ported after the *previous* swap (the 2026-07-16 landing-page
redesign; see ROADMAP "Redesign follow-ups" and "Dashboard follow-ups") were dropped or reduced to
stub toasts.

The redesign touched **only** `dashboard/{index.html,support.js,sw.js}` — no `backend/` or
`scripts/` changes. So there is **no new backend bloat**: the losses are dropped *front-end wiring*
to backend capabilities that still exist (calendar, spotify, stars, digest staging all remained
live server-side). See "Backend / weight" at the end.

## Restored in this pass (branch `claude/redesign-feature-restore-audit-6265e5`)

| Feature | What was wrong | Restored |
|---|---|---|
| **Digest reader** | `openDigest` was a stub toast ("opens here in the app") | Real reader: fetches `./digests/<hash>/latest.md` (falls back to the house `latest.md`), renders with the shared markdown renderer (sticky day headers, ⭐ top-picks, `code`-chipped times, H1 date), section jump-nav, download-as-`.md`. |
| **"The take" label** | Front-page dispatch hard-labeled the snippet **"The take"** — the exact label the 2026-07-20 decision removed | Descriptive headline: the take *sentence* is now the headline under "TODAY'S DIGEST · \<date\>". |
| **Concierge template text** | No starter prompts; thin welcome; replies rendered as plain text; a vestigial "Fast filter" line for a mode that no longer exists | Tappable starter-prompt chips + tap-to-fill `code` examples, a capability welcome (with the day's take folded in), replies render markdown, stale copy fixed. |
| **Spotify** | Settings row was a dead status line reading `META.music.layer` | Real Connect / Disconnect against the Worker's `/spotify/login · /status · /disconnect`, status-polled (signed-in only). |
| **Calendar feed** | Flattened to a copy of a bare `/calendar.ics` URL; `calendar-core.js` no longer loaded | Full modal restored: TOP PICKS / ★ Starred toggle, rating / per-day / lookahead / weekday / tri-state category+genre facets, live preview, Google/Apple/copy subscribe + `.ics` snapshot. |

All five verified end-to-end in headless Chromium with zero console errors.

## Still outstanding — NOT yet restored (prioritized for triage)

These were confirmed present in the pre-redesign build and are gone/stubbed/worse in the new one.
Ranked by impact for a power user (you). None are started.

### HIGH

1. **Explore faceted filtering — the whole system is gone.** The old Explore had
   neighborhood + region menus, category/genre/vibe/setting menus, a source filter, a date-range
   picker (two month-grids), a quick-range bubble, an active-filter summary + reset, and clickable
   tags that filtered the table. New Explore has only free-text search + 3 sorts (match/date/title).
   This is the single biggest loss. (Note: the *calendar* modal now has category/genre tri-state
   chips again, but the Explore table itself still can't filter.)
2. **Artist intel — stubbed.** Detail modal's "✦ Artist intel" button called `askArtists()` (asked
   the concierge for a rundown on the bill); it's now `showToast('… in the full app')`. Button
   still shows, does nothing.
3. **Concierge offline "Fast filter" mode — gone.** The old concierge had a mode switch:
   Concierge (LLM) vs **Fast filter** (instant offline keyword search that filtered the Explore
   table, no connection needed). New concierge has no offline path and can't drive any table filter
   (there are no filters left to drive). *(The misleading copy is fixed; the capability is not.)*
4. **Mobile filter + sort bottom-sheets — gone.** Old mobile had dedicated filter/sort sheets;
   new mobile has neither.

### MEDIUM

5. **Real event poster images silently ignored.** Old parsed `image` from the feed and painted it
   on hero cards. New `parseEvent` never reads any image field; `posterFor` only ever paints a CSS
   gradient (and only when the `imagery` prop = `subtle`, default `off`). The `image` field in
   `data.json` is now dead.
6. **Welcome / Tour / Changelog modals — stubbed** to toasts (`openWelcome`, `openTour`,
   `openChangelog`). First-run onboarding, the how-it-works guide, and what's-new are gone.
7. **Rep-cinema showtimes — gone.** Old grouped multi-screening times, each its own ticket link.
   New renders none — a real loss for the Film scene.
8. **Series / "Also showing" — gone, and lossy.** New `_applyFeed` actively drops non-rep series
   members (`filter(e => !(e.seriesKey && !e.seriesRep))`) with no "also showing" affordance to
   recover them, so series siblings vanish from the catalog view.
9. **Explicit ★ Star affordance vs. the "chip".** Server-side stars still POST to `/react` (via the
   header "chip"), so the mechanism survives — but the labeled "★ Star" button and the sense that
   you're building a shared, calendar-feeding shortlist are gone. (The Starred calendar tab is now
   back via this pass; the per-event Star button is not.)
10. **Concierge replies richness.** Now render markdown (fixed this pass) but still can't embed
    event cards/links the way the old rich-HTML replies could.
11. **Owner-only "refresh all sources & rebuild shared DB".** The old owner (Ari) had an admin
    "refresh events" that rebuilt the shared catalog for everyone. New settings only expose the
    per-profile re-rank; the owner-level source refresh is gone from the UI. Role-gated settings
    (owner vs friend vs logged-out) are largely flattened.

### LOW

12. Rank (# position) + raw Score columns collapsed into a single MATCH %.
13. Detail "afterhours" pill folded into the price string; ticket links capped at 4; venue image
    link replaced by a generic Google-image search.
14. "What changed" is a static string, not the clickable "what moved on the last pull" detail.
15. Resizable/collapsible concierge sidebar → fixed-width slide-over.

## Backend / weight

- **No new backend bloat from the redesign.** It changed only `dashboard/` files. `backend/`
  (`concierge-worker.js`, 98 KB) and `scripts/` are untouched; the endpoints the new UI stopped
  calling (`/calendar.ics`, `/spotify/*`, `/react`) were never removed — this pass re-wires them.
- **Client runtime got heavier while shipping fewer features.** `support.js` (the dc-runtime)
  grew 1513 → 1841 lines in the swap. Not app bloat (it's the framework), but worth noting the
  trade went the wrong way. Babel was correctly dropped from the SW shell.
- **Orphan fixed.** `calendar-core.js` was still cached by `sw.js` but no longer loaded — dead
  weight. This pass re-loads it (un-orphaned).
- **Pre-existing, not redesign-related:** the 11 committed `dashboard/data.<hash>.json` per-profile
  feeds (~7.6 MB each, ~84 MB) and `data/enrichment.json` predate the redesign. Out of scope here,
  but a candidate for the long-discussed "don't commit built feeds" / tokenized-fetch cleanup.

## Recommendation

The five in the table are done. Of the rest, **#1 (Explore filters)** is the one most worth a
dedicated pass — it's the biggest day-to-day capability loss and the most work. #2, #5, #6 are
comparatively cheap re-ports. Suggest triaging #1–#6 next; the LOW items are polish.
