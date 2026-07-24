# Audit — 2026-07-24 front-end redesign: dropped / broken / worsened features

**Context.** The "Front end redesign: new front page, detail modal, settings — live-wired"
(commits `392a7f7` + `9d3b70b`, 2026-07-24) rewrote `dashboard/index.html` from ~5314 lines to
~1370. It is **not** a framework swap — old and new both run the same `dc-runtime` (React under
`support.js`); it is a template rewrite of the app's logic block. In the rewrite a large set of
features that had been carefully re-ported after the *previous* swap (the 2026-07-16 landing-page
redesign; see ROADMAP "Redesign follow-ups" and "Dashboard follow-ups") were dropped or reduced to
stub toasts.

The redesign touched **only** `dashboard/{index.html,support.js,sw.js}` — no `backend/` or
`scripts/` changes. So there is **no new backend bloat**: the losses were dropped *front-end
wiring* to backend capabilities that still exist (calendar, spotify, stars, digest staging all
remained live server-side). See "Client runtime & weight" below.

This doc has three parts: what the restore branch fixed (two passes), what remains open
(prioritized), and an exhaustive binding-level appendix of record.

## Restore pass 1 (branch `claude/redesign-feature-restore-audit-6265e5`)

| Feature | What was wrong | Restored |
|---|---|---|
| **Digest reader** | `openDigest` was a stub toast ("opens here in the app") | Real reader: fetches `./digests/<hash>/latest.md` (falls back to the house `latest.md`), renders with the shared markdown renderer (sticky day headers, ⭐ top-picks, `code`-chipped times, H1 date), section jump-nav, download-as-`.md`. |
| **"The take" label** | Front-page dispatch hard-labeled the snippet **"The take"** — the exact label the 2026-07-20 decision removed | Descriptive headline: the take *sentence* is now the headline under "TODAY'S DIGEST · \<date\>". |
| **Concierge template text** | No starter prompts; thin welcome; replies rendered as plain text; a vestigial "Fast filter" line for a mode that no longer exists | Tappable starter-prompt chips + tap-to-fill `code` examples, a capability welcome (with the day's take folded in), replies render markdown, stale copy fixed. |
| **Spotify** | Settings row was a dead status line reading `META.music.layer` | Real Connect / Disconnect against the Worker's `/spotify/login · /status · /disconnect`, status-polled (signed-in only). |
| **Calendar feed** | Flattened to a copy of a bare `/calendar.ics` URL; `calendar-core.js` no longer loaded | Full modal restored: TOP PICKS / ★ Starred toggle, rating / per-day / lookahead / weekday / tri-state category+genre facets, live preview, Google/Apple/copy subscribe + `.ics` snapshot. |

## Restore pass 2 (same branch, second sweep)

| Feature | What was wrong | Now |
|---|---|---|
| **Explore faceted filters** | The entire filter system was gone (only text search + 3 sorts) | FILTERS panel: tri-state ✓/✕/off chips over category, genre, vibe, setting, neighborhood, region, source (vocab from `tag_facets` + live counts); date range (5 presets + native from/to inputs); active-count chip; reset. |
| **Clickable tags** | Tag chips were inert | Every tag chip (lead, shortlist, scenes, Explore rows, detail) routes to Explore — facet values become include-filters, anything else becomes search. |
| **Sortable columns** | Only date/title/match | Neighborhood, category and source headers sortable again; `source` back in the search haystack. |
| **Real event photos** | `parseEvent` ignored the feed's `image` field entirely | https-gated `image` renders as a lead-card photo column, shortlist/scene thumbs, and a detail banner (594 events currently carry images). |
| **Welcome / tour / changelog** | All three stubbed to toasts | Real again: 4-step quick-start stepper (auto-opens once per profile, `la-onboarded:<hash>`, "don't show again"), two-tab HOW IT WORKS / WHAT'S NEW guide with content **rewritten for the redesigned UI**, changelog updated. Settings also gains "today's digest — read ↗". |
| **Star → taste boost** | The Worker's star→`loved` learning fold exists but the redesign's chip POST sent no artists/title, so **stars never taught taste** | Star/unstar POSTs now carry `title` + lineup `artists` + `genres`. |
| **"Show less like this" → backend** | Local-only visual sink; no learning | Now also POSTs `/react` kind `less` → the Worker appends feedback kind `skipped` (−0.5 soft negative, `lib/feedback.py` already ranks with it). Undo stays local (a one-time −0.5 stands; capped once per event). Worker gained the `less` kind + optional `genres` (VERSION `2026-07-24-react2`; **needs `npx wrangler deploy`** — until then the page's `less` POSTs 400 harmlessly). |
| **Artist intel** | Stub button ("in the full app") | **Retired deliberately per Ari** — button removed; lineup Spotify/SoundCloud links + artist bios remain. Noted in the changelog. |
| Small fixes | — | Weekend lens clamps to today (Sat/Sun no longer shows finished nights); `fmtStamp` coerces zone-less CI stamps to UTC; Enter submits login; reactions reset on login/logout (they're per-person); welcome auto-opens on fresh sign-in; "Undefined" dropped from filter vocab; dead `chatGuideOpen` state removed. |

All verified headless (zero console errors): filters narrow 2652 → 390 (category) → 100
(+weekend preset) → reset 2652; tag-click routes + filters; star payload carries
artists/genres; `less` POSTs; welcome/guide/changelog open; photos render (the sandbox blocks
external image hosts; they load on Pages).

## Client runtime & weight — findings

- **The in-browser-Babel story is over.** The redesigned page ships plain JS — dc-runtime
  evaluates the template directly; Babel would only ever lazy-load **from a CDN** for JSX
  `x-import` modules, which this page doesn't use. The vendored `@babel/standalone`
  (**2.98 MB**) was referenced by nothing → **deleted** from the repo + Pages artifact. The
  ROADMAP "pre-transpile build step" TODO was obsolete as written and is closed with a note.
- **`support.js` growth (1513 → 1841 lines) is framework, not app.** The added subsystems are
  dc-runtime features (stream tracker, design-mode postMessage, canvas background, blob
  bundling, comment stripping). It is generated (`dc-runtime/src/*.ts`, source not in this
  repo) — not hand-trimmable, and at 68 KB it is not the problem.
- **The real client weight is the feed**: `data.json` is **7.6 MB raw / 0.9 MB gzipped**, and
  the page fetches it `cache:'no-store'` on **every** boot. Boot payload otherwise: support.js
  68 KB + React vendor 144 KB + calendar-core 20 KB. Recommended fix (not built — architectural):
  a slim boot feed (front page + head) with the full catalog lazy-loaded for Explore, **or**
  content-versioned feed URLs (`data.json?v=<catalog_content_version>`) with normal HTTP
  caching. Also pre-existing repo weight: 11 committed per-profile feeds ≈ 84 MB.

## Still open — prioritized

**Flagged for a product decision (structural — not silently changed):**

1. **The front page ignores the server-side slate.** OLD rendered `front_page.shelves`/`hero`
   (the shared `assemble.top_picks` "ONE Don't-miss policy" from ROADMAP). NEW recomputes
   everything client-side from raw deterministic `score`; the editor's `final_rank` ordering
   is honored **nowhere** (rank ⇄ score duality is also gone — only a synthetic match %
   remains). Rebuilding the front page onto the server slate is a real design decision — needs
   Ari's call before anyone "fixes" it.

**HIGH (real daily-use losses):**

2. **Mobile card layout** — OLD had a phone card list with inline expand; NEW mobile shows the
   min-width-720px table with horizontal scroll.
3. **Concierge streaming + stop + honest status** — replies no longer stream (single POST, no ■
   stop); the connection dot now means "credentials typed", not "backend answered ping"; the
   `MIN_BACKEND_VERSION` stale-Worker warnings are gone (incl. the Starred-calendar
   version gate).
4. **Concierge offline engine + chat-drives-the-table** — the no-LLM Fast-filter mode, the
   dining/plan composers, and the chat→Explore filter bridge have no counterpart.

**MEDIUM:**

5. **Rep-cinema showtimes** rows (per-venue time chips, per-showtime ticket links) — gone;
   time-labeled links are filtered out of the detail's ticket buttons.
6. **Series "Also showing"** — non-rep series nights are dropped at parse with no recovery
   affordance (lossy for rep-cinema runs).
7. **Update-flow robustness** — the re-rank job is in-memory (a reload orphans the spinner);
   OLD persisted jobs (`la-updating-<hash>`), used digest-signature baselines, 35-min cap, and
   4-signal Update-available logic (NEW checks only catalog content_version); the 3-day refresh
   nudge is gone.
8. **Owner tools** — the owner-only "Refresh events database" (`/refresh-events`) row is a
   static toast; owner/friend settings gating is flattened.
9. **Digest extras** — past-digest archive (`digests/index.json`), email-digest composer, and
   prose **entity links** (event mentions → card popup) are gone; a friend with no personal
   digest silently reads the house digest.
10. **Per-profile connection store** — OLD scoped concierge creds per profile
    (`la-conn:<hash>`, 45-day TTL, legacy-key migration); NEW uses one shared
    `la-concierge-cfg` for the device — stranded old creds, cross-profile sharing.
11. **ICS export richness** — per-event .ics lost DTEND (+3h), DESCRIPTION
    (lineup/why/price/link), all-day fallback, line folding.
12. **Sample/offline data** — the bundled 56-event demo + sample digest are gone; a failed
    feed fetch leaves an empty page.

**LOW / cosmetic:** per-device view persistence (`la-view`); "Around town" shelf; full star
names (avatars only now); NEW-badge only on the lead card; venue-name address trimming; ticket
links capped at 4 without URL dedupe; direction-toggle on sorts; Explore 400-row cap; total
catalog count no longer shown; login busy/error states; Enter-to-save in the API modal; toast
richness details in the appendix.

## Recommendation

Item 1 needs a decision, not code. Items 2–4 are the next real pass (mobile cards and
streaming are self-contained; the offline engine is the largest). 5–12 are independent,
mid-size re-ports — 5, 6 and 11 are the cheapest of them. The client-weight follow-up worth
scheduling is the slim-boot-feed / versioned-URL change.

---

# Appendix of record — exhaustive feature inventory (binding-level)

Method: mechanical set-diff of every `{{ binding }}`, Component method, state key,
localStorage key and endpoint string in OLD (pre-redesign, 5,314 lines) vs NEW, then grouped
by feature; plus a walk of every OLD markup section. Rows marked **restored@HEAD** landed in
pass 1 (commits `4131a88`/`7ab90a9`); **restored@WT** rows were audited in the working tree
and landed as pass 2 (commit `5df8c2c`) — the "Small fixes" in pass 2 above additionally
resolved the welcome-on-fresh-login, weekend-clamp, `fmtStamp`, Enter-to-submit,
reactions-reset, search-source and `chatGuideOpen` items called out in rows below after the
snapshot was taken.

## Feature table — user-visible

| Feature | What it did (1 line) | OLD evidence (line refs + key bindings/handlers) | NEW status | Notes |
|---|---|---|---|---|
| Front page: server-curated shelves | Rendered `META.front_page` hero + per-lane shelves + fixed shelves; page never re-ranked | L310–368, L4984–5112; `fpShelves`, `sh.cards/seeAll`, `mkCard`, `resolve(keys)`, `byKey` | **Partial (redesigned)** | NEW front is client-computed: `poolFor(lens)` sorts by raw `score` desc; lead + shortlist(4) + `SCENES` buckets via `sceneOf()`. Server `front_page.shelves`/`hero` rank order is unused except hero keys feeding dispatch chips. The two-zone near/ahead shelf split and assemble-slate ordering no longer drive the page. |
| "Don't miss" hero row + tier badges | Hero grid w/ photos; `MUST-SEE` tier chip on shelf cards (from editor verdict) | L328–360, L5040–5089; `c.tier/tierBg`, `TIER_BG` | **Partial** | NEW: single "lead" card (rank 01) + `c.mustSee` badge computed client-side (lane's top pick with `score>=6` or `verdict.tier==='must-see'`). Verdict tier no longer the sole source. |
| "Around town" shelf | Fixed near-city-pulse shelf from `FP.around` keys | L5103–5110 | **Gone** | No equivalent surface; those keys in the feed are now dead. |
| "On the radar" shelf | Fixed plan-ahead shelf from server `FP.radar` (build_radar/festivals.yaml set) | L5103–5110 | **Partial** | NEW radar is a client heuristic: next 6 upcoming events with `on-sale`/`just announced` badges or `firstSeen` ≥ last fetch. Server-curated festival radar keys unused. |
| Shelf "see all →" → prefiltered Explore | Jumped to Explore filtered to the shelf's id-list (`filtered` mechanism) | `fpSeeAll` L2212–2220, `sh.seeAll` | **Partial (replaced)** | NEW `sc.onAll` opens a dedicated **scene page** (`openScene`) — new surface, not the table; the id-list `filtered` mechanism is gone entirely. |
| FRONT/EXPLORE tabs + sample gating | Header view switch; hidden (`hasFront`) when feed lacks `front_page` | L216–221, L4642–4645 | **Equivalent** | NEW tabs + mobile bottom nav (new). Gating dropped — Front always shows (fine, front is client-computed now). |
| Per-device view persistence | Remembered Front vs Explore per device (`la-view`), restored on load | `setView` L2196–2199 | **Gone** | NEW always boots on `view:'front'`; no `la-view` key. |
| Explore date-range picker | Custom dual month-grid calendars for start/end | L227–270; `openCalStart/End`, `buildCalendar`, `pickDay`, `shiftMonth`, `cal.cells` | **Restored@WT (different form)** | Filter panel has native `<input type="date">` from/to + preset chips. The hand-built month-grid popover is gone (cosmetic). |
| Range preset bubble | today / weekend / 10d / 30d / 2mo / all presets; label in header | L273–287; `bubbleOpts`, `setRange`, `SPAN_DAYS`, `rangeLabel` | **Restored@WT (different form)** | `exDateChips` presets: All / Tonight / This weekend / Next 2 wks / Next month. Lost presets: 10-day (old default) and 2-month. Default window changed: OLD next-10-days; NEW all upcoming. |
| Column sorting (7 keys, direction toggle) | date/title/hood/cat/**rank**/score/source sortable, asc↔desc toggle | L426–507, `setSort` L2125–2131, `sortedRows`, `arrow*` | **Partial→mostly restored@WT** | NEW: 6 sortable headers (date/title/hood/cat/match/source). Still missing: **rank** sort (see next row) and direction toggling. |
| Rank column + rank⇄score duality + verdict tooltip | `#final_rank` (editor's slate order) beside raw 1–9 score; tooltip showed verdict tier + why; rank default sort collapsed series | L504, L551–568, `effRank`, `ev.rankNum/rankTitle` | **Gone** | NEW shows only synthetic `matchPct` (52–98%) everywhere; "rank" on cards is just the position index. **The editor's `final_rank` ordering is honored nowhere** — all surfaces sort by deterministic `score`. Verdict survives only as must-see badge + `why` fallback text. |
| Column filter menus (7 tri-state axes) | Header dropdowns: hood+region, cat/genre/vibe/setting, source; ✓ keep → ✕ hide → clear; per-axis clear; blue active icons | L428–521; `openFilterMenu`, `toggleFilterVal`, `passesColFilters`, `distinctVals`, `colFilters`, `*Menu`, `clear*` | **Restored@WT (different form)** | Unified FILTERS panel: header `☰ FILTERS (n)` chip, 7 tri-state axes (`exRows`/`triRow`/`exCycle`/`exPass`), same ✓/✕/off cycle, facet vocab from `META.tag_facets` + counts, reset-all + "clear filters ×". Enabled by `parseEvent` re-adding `genres/vibes/settings/regions` arrays. Not persisted across reloads (OLD didn't persist either). Per-axis "clear" links absent (only global reset) — cosmetic. |
| Mobile filter/sort bottom sheets | Dedicated mobile sheets: sort list + 7-section filter sheet w/ "Show N events" apply | L372–419; `toggleMobileFilter/Sort`, `mobileFilterSections` | **Partial** | Mobile now uses the same header sort chips + FILTERS panel as desktop (responsive, not sheets). Functionality restored@WT; the bottom-sheet UX is gone (cosmetic). |
| Mobile card list w/ inline expand | Phone layout: cards expanding in place with full detail | L674–798 (`m-card`, `ev.expanded`) | **Gone (replaced)** | NEW mobile shows the same table (min-width 720px, horizontal scroll — a worse phone reading experience) and opens the detail modal on tap. |
| Desktop expanded-row detail | Click row → inline expansion without leaving the table | L527–668; `toggle()`, `ev.expanded/caret/rowBg` | **Replaced** | Row click opens the detail modal. Same information reach (minus items below); the stay-in-table skim flow is gone. |
| Search | Free-text over title/venue/hood/cat/genre/**source**/lineup, scoped within active filters | L299–305, L4655–4656 | **Equivalent** | NEW searches the same haystack (`source` re-added post-snapshot); typing auto-switches to Explore (new nicety). Works together with filters. |
| Active-filter summary chip + reset | Header chip showing chat/see-all filter label with ×; footer "reset · show all" | L293–298, L809–811; `hasFilter/filterSummary/onReset` | **Restored@WT (different form)** | `FILTERS (n)` count + "n filters active" + "clear filters ×" + panel "reset all". The chat-driven summary label is gone with the chat-filter feature itself. |
| Explore row cap | OLD rendered all matching rows | L4649–4658 | **Changed** | NEW slices to 400 rows. With ~3.3k events, date-sorted browsing beyond 400 requires filters/search. |
| Detail: venue display + maps | Maps link with address-tail-trimmed label, hood suppressed when generic/duplicated | `detailFields` L4193–4222, `venueDisplay` L4179–4185 | **Partial** | NEW detail: map-pin link + raw `venue · hood · price`. No address-tail trimming, no hood suppression; TBA gating kept. |
| Detail: venue interior photos link | ▣ → Google Images "interior" search | L618–620 | **Equivalent** | NEW "see venue ↗" → image search. Same function, different param + label. |
| Detail: price / when / afterhours pill | Distinct pieces; purple `afterhours` chip | L625–632 | **Partial (cosmetic)** | NEW folds afterhours into the price string as text; no pill. When-line kept ("Tonight ·" prefix added — nice). |
| Ticket links: labeled, deduped, domain-mapped | Multi-link buttons deduped by URL+label, labels from domain map, "All LA showtimes" for films | `ticketLinks/linkLabel/ticketFields` L1619–1674 | **Partial** | NEW: feed label-carrying links minus time-like labels, capped at 4; fallback single button labeled by source. Lost: URL/label dedupe, domain-based labels, `showtimesUrl`. |
| SHOWTIMES chip rows | Per-venue rows of time chips (per-showtime links), sold-out struck | L633–643, L1022–1032; `sg.*`, `st.*` | **Gone** | Time-labeled links are filtered out of `ticketLinks`; only `e.url` survives. Rep-cinema showtime buying lost. |
| Series: "Also showing" + sibling nights | Run's other nights as dated chips, "N nights · M theaters" badge; date views kept every night, rank views collapsed | L653–663, L1033–1043; `sd.*`, `ev.hasSeries/seriesChipRows`, `collapseSeries` | **Gone (lossy)** | NEW `_applyFeed` **drops non-rep series members at parse**: date-sorted Explore shows one night per run, and no affordance recovers the others. `series` summary object not parsed. |
| Lineup rows + artist bios | Per-artist rows, LLM bios matched via `_artistNorm` | L586–607, `artistRowsFor` L1723–1744 | **Equivalent** | NEW detail lineup with `ln.bio`. Note-only artists (bio names not in billing) no longer appended as extra rows — minor. |
| Listen links: Spotify / SoundCloud | Direct artist page via `META.artist_links`, else artist-scoped search with qualifier strip; SoundCloud people search; links gated to music-ish events | `spotifyFor/spotifySearch/_searchName/soundcloudSearch` L1703–1717 | **Partial** | NEW keeps the direct `artist_links` hit. Fallbacks degraded: plain search URLs (no artist scope, no qualifier strip). Gating gone — every lineup string gets glyphs. |
| ✦ Artist intel | Sent a grounded ask (bill + bios) to the concierge | `askArtists` L1757–1785 | **Gone (deliberately retired)** | Pass 2 removed the stub button per Ari's decision; noted in GUIDE_NEW changelog. |
| Add to calendar (.ics) | Full RFC 5545 export: DTEND (+3h), all-day fallback, DESCRIPTION (lineup/why/price/rating/URL), escaping + folding | `buildICS/…/downloadICS` L1787–1859 | **Partial** | NEW `icsFor`: minimal VEVENT — TZID DTSTART only, **no DTEND, no DESCRIPTION, no all-day fallback, no folding**; UID from server key (better). Imports fine but events land with unknown duration and no context. |
| Star (server-side social save) | ☆/★ button; optimistic `STAR_LOCAL` w/ revert-on-failure + toasts; POST `/react` with `title`+`artists`; gated to logged-in; per-profile reset | L1861–1915; `toggleStar`, `starOn`, `adjustedStars` | **Restored+ (changed semantics)** | NEW "+ chip": POST restored **with `title`+`artists`+`genres`** (richer than OLD). Remaining deltas: no failure revert (fire-and-forget), no star toast, logged-out taps silently stay local; reactions keyed by client `id` (embeds array index — a feed reorder can orphan saved reactions). Per-profile reset restored post-snapshot. |
| Friends' star names | "★ Lori, You" badge with full names | `computedBadges` L1595–1617 | **Partial** | NEW shows initial-avatars (WHO column + card chip clusters) — visual upgrade but **full names are gone** (no tooltip); the detail "Starred by <names>" line was removed. |
| "Show less like this" | — (did not exist) | — | **New in NEW** | Sinks the event in sorts (never hides); pass 2 added the soft `/react` learning signal + toast. Front-page empty state offers `resetReactions`. |
| Clickable tag chips → Explore | Tags jumped into Explore with a real column filter (`exploreByTag`) | `tagChips/tagClickProps` L1580–1594, `exploreByTag` L2226–2242 | **Restored@WT** | `tagsFor` chips carry `onTag` → `tagFilter`: recognized facet value → include-filter + opens panel; unrecognized → search text. Wired on all card/row/detail tag sites. |
| NEW / just-announced badge | Green `NEW` on any card with `firstSeen ≥` last fetch | `c.isNew` L5070 | **Partial** | NEW: `JUST ANNOUNCED` on the lead card + radar rows only; shortlist/scene/explore rows don't surface newness. |
| Real event photos | Structured-source images on hero cards, background-image with injection guard | `.fpc-image` L84–92, `mkCard` L5045–5049, `parseEvent` L4460 | **Restored@WT (broader)** | https-gated `image` re-parsed; lead photo column, shortlist/scene thumbs, detail banner. OLD limited photos to hero-only by design — NEW shows them on all card surfaces; minor design divergence to sanity-check with Ari. |
| Poster-gradient imagery | — (did not exist) | — | **New in NEW** | `posterFor` category-hue gradient behind the `imagery:"subtle"` prop (default off); coexists with real photos. |
| Digest reader modal | Styled markdown reader, sticky day headers, ⭐ picks, jump-nav, download | L910–961 + `renderMarkdown` L2733–2851 | **Restored@HEAD** | Jump-nav + download + day-sticky headers present. |
| Digest access points | Header "curated digest for *you* ↗" always visible | L215, `digestUser` | **Partial** | NEW: dispatch "Read the full digest →" (only when the feed has a take) + settings "today's digest · read ↗". No always-visible header link; Explore has no digest entry point. |
| Email digest | mailto: composer (typed address, never stored) | L920/943–948, L3196–3209 | **Gone** | No email affordance in the NEW digest modal. |
| Past-digest archive | Dropdown over deploy-staged `digests/index.json`, view past docs, ✓ current, dated download names | L921–937, `loadDigestIndex`, `selectDigestEntry` | **Gone** | NEW never fetches `index.json`; only `latest.md`. |
| Digest prose entity links | Event mentions in prose became tappable spans opening the event card (alias index, day steering, place-name blocklist) | L2497–2724: `digestEntityMap`, `linkDigestEntities`, `onDigestBodyClick` | **Gone** | NEW renders plain prose. The digest → card popup bridge is fully absent. |
| Digest "update available" chip | Toolbar chip mirroring update state, click = run Update | L938–941 | **Gone** | No update affordance inside the digest modal. |
| Missing per-profile digest placeholder | Synthesized "No personalized digest yet — hit Update" doc | `loadDigestFor` L4567–4577 | **Changed** | NEW silently falls back to the **house** digest — a friend with no digest reads the default with no explanation. |
| The take | One-sentence teaser in chat welcome; structural `front_page.take` preferred, digest-lede heuristic fallback, placeholder-guarded | L1497–1513, `reseedTake/teaserOf/digestLede` | **Restored@HEAD (structural path only)** | Dispatch headline + "Today's read · <date>" in the chat welcome. The lede-heuristic fallback for take-less digests is gone (no take → no dispatch), and the welcome is seeded once into the persisted thread — a stale take can sit in an old thread. |
| Concierge panel form | Persistent desktop sidebar: drag-resize (280–620px), collapse to strip | L113–163; `startResize`, `toggleCollapse`, `sidebarW` | **Changed** | NEW: right-rail strip; chat is a modal slide-over (400px/100vw). No resize, no persistent side-by-side reading. |
| Concierge ⇄ Fast-filter mode toggle | Two modes; Fast filter = instant offline engine; persisted | L134–140, `modeOpts`, `setChatMode` | **Gone** | Single LLM mode. `la-chat-mode` key dead. |
| Offline local engine (filter/dining/plan) | No-LLM NL parsing → table filter + composed replies; dining picks from `META.dining`; plan composer + **night-planner prompt to clipboard** | L3928–4332: `localSpec`, `applySpec`, `runLocal`, `composeFilterReply/DiningReply/PlanReply`, `buildPlanPrompt` | **Gone** | NEW chat without creds answers only "I'm not connected yet…". Dining dataset, plan composer, clipboard hand-off — no counterpart. |
| Chat drives the table | Concierge/local replies set filtered ids + sort + flipped to Explore | `runLocal` L4151–4165 | **Gone** | NEW chat is conversation-only; it cannot filter or navigate the page. |
| Streaming replies + stop | NDJSON stream, throttled live bubble, ■ stop (AbortController), heartbeats | `askBackend`/`_readChatStream` L3415–3494, `stopLLM` | **Gone** | NEW `sendChat` is a single JSON POST; thinking dots only; no stop. |
| Backend health ping + truthful status pill | POST `{ping:true}` on load/switch/open; pill green only when ping ok | `pingBackend` L3504–3518, `backendReady` | **Gone** | NEW `conDot` = **credentials present in state** — green even if the token is wrong or the Worker is down; first failure discovered when a message errors. |
| MIN_BACKEND_VERSION stale-build warnings | Version fingerprint vs `MIN_BACKEND_VERSION`; amber "old build" pill; stale-aware error text; saved-calendar `star1` gate | L1519–1527, `backendStale*` L3524–3534 | **Gone** | No version concept in NEW. The calendar modal's own probe still maps 405 → "redeploy" note, but the **Starred-calendar version gate is gone** — a stale Worker would silently serve PICKS for a Starred URL. |
| Worker error-body detail in chat errors | Parsed `{error, detail}`; 401 guidance; one-time hint; re-ping | L3425–3437, L4095–4126 | **Partial** | NEW surfaces `backend error <status>` + a 401 message; does not read the error body, never re-pings. |
| taste-edit acknowledgement | `taste_changed` → persisted per-profile dirty flag feeding Update-available | `setTasteDirty*` L3872–3888 | **Partial** | NEW appends a chat notice. No persisted dirty flag — Update-available won't reflect an un-folded taste edit after reload. |
| Rotating placeholder examples | Cross-fading example prompts pre-first-use | L156–158, `PH_EXAMPLES` | **Partial** | NEW: static placeholder + starter chips + tap-to-fill welcome examples. Rotation gone (cosmetic). |
| Greeting how-to collapse | Full how-to until first message (`la-chat-used`), then "see what I can do ▸" | `chatGuideOpen`, `GREET_*` | **Changed** | NEW welcome is one persisted thread message; starter chips hide after first user message. Vestigial state key removed post-snapshot. |
| Chat thread persistence | — (OLD thread in-memory) | — | **New in NEW** | `la-chat-v1` keeps last 40 messages across reloads. |
| Chat input ergonomics | Multiline textarea (Shift+Enter) | L157 | **Partial (cosmetic)** | NEW single-line input; Enter submits; no multiline. |
| Connection modal (key/Opus/token) | Draft semantics (applied on Save), `sk-ant-` validation, live status incl. stale warning, key-prefix display, autofocus, Enter-to-save | L1219–1268; `saveApiSettings` | **Restored@HEAD (simplified)** | NEW keeps key/switch/Opus/token/Save. Lost: draft semantics (toggles mutate live state; Close without Save keeps flips for the session), format validation, live ping status, key-prefix display, autofocus, Enter-to-save. |
| Per-profile connection store + TTL + migration | Conn per profile (`la-conn:<hash>`, 45-day TTL, `touchConn`), `migrateLegacyConn` folded legacy keys | L3264–3319 | **Gone (replaced by one shared store)** | NEW uses a single `la-concierge-cfg` for every profile on the device: no scoping, no TTL, **no migration** — existing users' saved creds are stranded; everyone re-enters once. |
| Login | Password-type input, Enter submits, busy `…`, inline error, display name from feed `profile.name`, full profile-switch orchestration (`applyProfile`) | L866–875, `submitProfile/applyProfile` L3549–3592 | **Partial** | NEW `doLogin`: plain-text input, errors as toasts, no busy state; display name = typed username (an OLD-format persisted profile `{hash,name}` shows the fallback "Ari" — misleading for friends). Post-login: feed + digest + Spotify + welcome (Enter-to-submit and fresh-login welcome fixed post-snapshot); no ping/index/nudge orchestration. |
| Logout | Cleared profile, restored default feed/digest, conn reloaded | `logoutProfile` | **Equivalent** | Resets state + reloads house feed/digest (+ reactions reset post-snapshot). |
| Ranks & Digest update flow | Job persisted (`la-updating-<hash>`) surviving reload (`reattachJobs`), digest-signature + receipt baselines, 15s poll, 35-min cap, completion toasts distinguishing rewrite vs no-op, dirty-flag clearing, double-click guard | L3831–3926, L3684–3770 | **Partial** | NEW: receipt-baseline only, 6s poll, 6-min cap then "Still building…", reload feed on success. Job in-memory — **a reload orphans the spinner** (and the poll keeps running if you log out mid-update). Elapsed ticker + progress bar + header "re-ranking · m:ss" pill (new) present. |
| Update-available logic (4 signals) | catalog version ∪ taste-dirty ∪ digest-behind-feed ∪ curated-layer-behind | L3859–3926, L3068–3090 | **Partial (1 of 4)** | NEW compares only catalog `content_version` — reads "Current" almost always; the layer-behind signal that actually drove the button is gone. `catalog_meta` fetched once at boot, never re-checked. |
| Update badge + settings title | Blue dot on ☰ whenever update actionable/in flight | L813, `updateBadge` | **Gone (repurposed)** | NEW gear dot = "logged in". In-flight state visible via the header pill instead. |
| Refresh nudge (3-day popup) | Auto-popup when curated layer ≥3 days old; once/day snooze; Update-now | L1172–1194, L3053–3168 | **Gone** | Nothing nudges a stale curated layer; combined with weakened Update-available, friends will silently sit on stale verdicts/digests. |
| Owner: Refresh events DB | Owner-only row firing `/refresh-events`, persisted job, poll on `catalog_meta.fetched_at` | L827–836, `refreshEvents` L3808–3826, `isOwner` | **Stubbed** | NEW "Events database" row → informational toast; `/refresh-events` unreachable from UI; owner/friend distinction fully flattened. |
| "What changed" readout | Colored count; click → toast itemizing `catalog_meta.changes` (titles + fields) | L893, `showChanges` L3650–3662 | **Partial** | NEW static "X added · Y updated" — not clickable, no itemized fields, no color. |
| "Last data pull" row | Live `catalog_meta.fetched_at` (fresh after refresh) | L890–892 | **Partial** | NEW shows the **feed's baked** `catalog_fetched_at` — goes stale relative to live catalog_meta. |
| "Last site update" row | `document.lastModified` = actual deploy time | L894 | **Repurposed** | NEW shows `META.generated_at` (feed build time, same as `dbSynced`) — the label now lies about what it shows. |
| `fmtStamp` UTC coercion | Zone-less ISO stamps coerced to UTC | L3245–3257 | **Fixed post-snapshot** | NEW now coerces zone-less stamps to UTC again. |
| Spotify connect/status | Row + status modal; OAuth via Worker; poll; **stale-feed hint** ("ranking built without it" via `META.music`); modal-confirmed disconnect | L1196–1217, L3594–3633, L4896–4917 | **Restored@HEAD (minus hints)** | Row-inline Connect/Disconnect, status poll kept. Lost: the modal (disconnect is one accidental tap), the feed-reflection warning, the no-backend explanation case. |
| Taste & profile modal | Tabs; **state badge** updating→pending→reflected + "Update now →" CTA; diff captioned by `diff_kind`; RECENT ADJUSTMENTS history; raw YAML views | L1060–1120, L4846–4895 | **Partial** | NEW: tabs + diff coloring + synthesized profile rows. Lost: the pending/reflected state machine (banner **always** claims LIVE), the in-modal Update CTA, edit history, raw YAML texts. |
| Guide / What's-new modal | Two-tab modal, long-form markdown | L1122–1137, texts L2907–2986 | **Restored@WT** | Full modal + content rewritten for the new UI (incl. an honest "the redesign, restored" changelog + Artist-intel retirement note). |
| Welcome / first-run onboarding | 4-step wizard, auto-open once per profile, manual reopen | L1139–1170, L2992–3051 | **Restored@WT** | Steps rewritten for the new UI; same `la-onboarded:` key (old dismissals honored). Fresh-login auto-open fixed post-snapshot. |
| Calendar feed modal | Picks/Starred tabs, tri-state facets, preview, subscribe, snapshot | L1270–1356, `calVals` L1917–2122 | **Restored@HEAD** | Near-line-for-line port. Still lost vs OLD: the `savedNeedsRedeploy` version gate, active-tab border highlight, the "subscribe again after changing settings" footnote (cosmetic). Saved list = server stars ∪ this device's chip taps. |
| Footer | "N shown · M entries in catalog", "reset · show all", ⚷/☰ trigger + badge | L806–906 | **Gone (relocated)** | Counts → Explore count line + front "See all N events →" (upcoming-only; **total catalog count no longer shown anywhere**); reset → filters panel; settings → header gear. |
| Toast | Plain 4.2s message | L1358–1361 | **Upgraded** | NEW toast supports an UNDO action slot, 5s. |
| Keyboard: Escape | Closed **all** open modals in one press | L4590 | **Equivalent (better)** | NEW closes one layer per press in priority order incl. welcome/guide first. |
| Keyboard: Enter submits | Login, API-key, token, digest email inputs | L870, L1240, L1257, L945 | **Partial** | NEW: chat + login (fixed post-snapshot). API/token inputs still mouse-only. |
| URL/hash routing | None | — | **Equivalent (none)** | Deep-linking an event/view impossible in both. |

## Feature table — internal / infrastructure

| Feature | What it did | OLD evidence | NEW status | Notes |
|---|---|---|---|---|
| Boot sequence | Migrate conn → conn read → feed+digest+index → freshness → ping → reattach jobs → placeholder ticker → onboarding → nudge; `defaultSort` applied | `componentDidMount` L4584–4625 | **Partial** | NEW: reactions + cfg + profile → feed + digest + one-shot catalog_meta → listeners → chat restore → onboarding. No ping, no job reattach, no freshness re-poll, no nudge, no defaultSort. |
| Bundled sample data | 56-event demo + sample digest; page browsable offline/first-deploy | L1366–1441, L2411–2476 | **Gone** | NEW: failed feed fetch leaves an empty page ("unavailable"). |
| `parseEvent` field coverage | `genres/vibe/setting/region/nearHome`, `image`, `rating`, `final_rank`, `series` object, `seriesRank`, `showtimesUrl`, `whyCurated`, `desc` | L4366–4465 | **Mostly restored@WT** | Re-added axes + `image`. Still dropped: `rating` (OLD put "Recommended: n/5" into ICS), `final_rank`, `series` summary + `seriesRank`, `showtimesUrl`, `nearHome`. |
| Series collapse strategy | View-time collapse — rank views deduped, date views kept all nights | `collapseSeries` L2155–2167 | **Changed (lossy)** | Parse-time drop of non-rep nights (see Series row). |
| Reactions vs STAR_LOCAL | Session-scoped optimistic map, reset on profile switch, keyed by server `event_key` | L1866, L3574 | **Changed** | `la-fp-reactions-v1`: persisted, keyed by client `id` (embeds array index — a feed reorder can orphan/misattach reactions). Per-profile reset restored post-snapshot. |
| Job persistence keys | `la-updating-<hash>`, `la-refreshing` + `reattachJobs` | L3684–3724 | **Gone** | In-memory `state.updating` only. |
| Digest signature probe | `fetchDigestSig` distinguishing "digest rewritten" from "receipt only" | L3689–3707 | **Gone** | Poll keys on `rebuilt.<hash>.json` alone. |
| localStorage inventory | `la-view`, `la-chat-mode`, `la-chat-used`, `la-profile`, `la-conn:<h>`, `la-cal:<h>`, `la-onboarded:<h>`, `la-dirty-<h>`, `la-last-visit-<h>`, `la-nudge-shown-<h>`, `la-updating-<h>`, `la-refreshing` (+5 legacy migrated) | throughout | **Changed** | NEW: `la-profile`, `la-cal:<h>`, `la-onboarded:<h>` kept; new `la-concierge-cfg`, `la-fp-reactions-v1`, `la-chat-v1`. All others orphaned (stale values remain in browsers, unread). |
| Backend/endpoint surface | Chat POST (+ping), `/react`, `/calendar.ics`, `/spotify/*`, `/refresh-events`, `/rebuild-profile`; static feeds, catalog_meta, digests + index.json + archive, rebuilt receipts | throughout | **Partial** | NEW drops: ping body, `/refresh-events`, both `index.json`s, archive fetches, digest-sig probe. Chat body: OLD `{messages(7), stream:true,…}` → NEW `{messages(12),…}` (no stream flag). |
| Props / data-props tweaks | `$preview` 1280×860; `density`; `defaultSort` rank/score/date; `showScoreBar` | L1364 | **Changed** | NEW: `$preview` 1440×940; density + defaultSort gone; `showScoreBar` → `matchDisplay` (both/pct/off); new `imagery`, `glow`, `showChips`, `chipAdd`. |
| PWA / service worker / head | manifest, sw.js, icon, theme-color, support.js + calendar-core.js | L1–18 | **Equivalent** | Byte-identical head blocks; calendar-core re-loaded at HEAD (un-orphaned from the sw cache); sw CACHE v9. |
| Responsive plumbing | `viewportW` rAF resize; 720px breakpoint; `100dvh` | L4594–4601 | **Equivalent** | NEW boolean `isMobile` on resize. |
| Front "weekend" lens window | Weekend = remainder-of-weekend (start clamped to today) | `weekendRange` L2176–2182 | **Fixed post-snapshot** | NEW now clamps the weekend window start to today. |
| Markdown renderers | `renderMarkdown` (digest chrome) + `renderChatHtml` + `inlineMd` | L2478–2872 | **Equivalent** | Ported essentially verbatim (minus entity-linking hook). |
| Score color / segments | Perceptual ramp + 9-segment bar | L1550–1563 | **Equivalent** | Same ramp; presentation via `matchPct` (see Rank row). |

## Set-diff leftovers

Every OLD-only binding/handler/state/localStorage/endpoint maps to a row above, except these
residuals, listed so nothing is silently dropped: `toggleDigestPicks`/`digestPickCount`
(vestigial in OLD itself — no markup bound it); `starsLine` (computed but unused in OLD; its
NEW counterpart was likewise removed); `count` ("N / M events", superseded by
`exploreCountLabel`); `onSendRef`/`send` (chat aliases); `fpStopClick`/`mapsStop`/`ar.stop`/
`lk.stop` (stopPropagation plumbing, replaced by inline handlers); OLD class fields
`ALL`/`BACKEND_TOKEN`/`TODAY_MD`/`WEEK_END`/`TEN_END`/`MONTH1` (sample data + date anchors,
covered above); DOM ids mis-extracted as storage keys (`la-api-key-input`, `la-login-input`,
`la-token-input`, `la-chat-input`, `la-chat-thread`); path artifacts (`'/5'` from the ICS
rating string, `'/artists'` Spotify scope, the SVG namespace, archive/poll/owner-refresh URLs
— all covered in their feature rows).
