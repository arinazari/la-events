# Routine: daily weekend digests

Prompt for the scheduled cloud Routine (claude.ai/code → Routines). Paste the body below
as the routine prompt; repo = this one. Runs **daily** and maintains a rolling set of
**per-weekend** digests for the next ~4 months — each weekend gets its own file, refreshed
every day as new events are announced and lineups firm up.

Configure in the routine's environment (not here): the daily schedule, the target branch
(recommended: **`main`** — the Pages workflow then auto-redeploys the dashboard on each push; the
tradeoff is daily digest commits on main, fine for a personal repo), the network policy (outbound to
app.ticketmaster.com, ra.co, dice.fm + the domains in sources.yaml), and `TM_API_KEY` / `POSH_TOKEN`.

> Prereq: validate one manual digest run first (ROADMAP Phase 1). A daily routine pointed
> at an unvalidated pipeline with no `TM_API_KEY` just commits empty weekend files daily.

---

Run the la-events digest per .claude/skills/la-events/SKILL.md, in **weekend-set** mode:

1. **Run the deterministic core:** `python scripts/run_digest.py --days 120`. Fetches the
   structured sources, dedupes, expires past events, scores against taste.yaml + profile.yaml →
   `data/catalog.json` + `data/candidates.json` (wide horizon so far weekends carry announcements).
   Capture the run report (failed/skipped sources) for footers. Degrades gracefully.
2. **Layer in + re-score:** add the sources the core doesn't cover (SKILL Step 2) — the Gmail
   "Events" label if available, `webfetch`/`squarespace`/`ics` venues (≤15-source budget), and this
   week's editorial roundups as `editorial_mentions`. Then `python scripts/run_digest.py --no-fetch`
   to re-dedupe + re-score and refresh `data/candidates.json`.
3. **Enrich:** fan out the `scene-researcher` agent over the cache-miss candidates
   (`enrich.select_for_enrichment`) → per-event tags, artist notes, curator's notes, descriptions,
   and images for the `image_wanted` picks → folded into `data/enrichment.json` (recurring artists
   reuse the cache; verify-or-omit).
4. **Cache images:** `python scripts/cache_images.py` — downloads the hero images into
   `data/images/` so committed/hosted digests don't hotlink-rot. Idempotent.
5. **Render per weekend:** for each of the next ~16 weekends (Fri–Sun; Thursday-night events fold
   in), keyed by the **Friday**, run `python scripts/render_digest.py --from <Fri> --to <Sun>
   --md digests/weekends/<Fri>.md --html digests/weekends/<Fri>.html`. The renderer is day-by-day,
   category-grouped, time-first, with ⭐ picks + curator notes from enrichment. Near weekends fill
   out; far ones stay thin (few candidates) — do NOT pad.
6. Maintain `digests/weekends/index.md`: one row per weekend (date range, # events, top pick),
   soonest first; drop past weekends.
7. Rebuild the dashboard feed: `python scripts/build_dashboard.py`.
8. Commit catalog + `data/enrichment.json` + `data/images/` + the changed weekend `.md`/`.html` +
   index + `dashboard/data.json`, message "weekend digests: YYYY-MM-DD (W weekends, N events, M new)".
9. If a source failed twice in a row, mark it `flaky` in sources.yaml and note it in the nearest
   weekend footer.
10. Do NOT run discover mode here (separate / manual).

> **Delivery — no email (deliberate).** The routine commits the `.md` + `.html` to the branch; do
> NOT email. The planned delivery is a **hosted, bookmarkable page** served from these artifacts,
> with on-page actions (re-scan sources, request an ad-hoc digest from the LLM). See ROADMAP
> "Hosted page". Until it exists, open the committed weekend `.html` directly.
