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

1. **Run the deterministic core:** `python scripts/run_digest.py --days 120 --far-days 180`.
   Fetches the structured sources, dedupes, expires past events, scores against taste.yaml +
   profile.yaml → `data/catalog.json` + `data/candidates.json` plus the editor judging pool
   `data/editor_pool.json`. **Two-speed horizon:** near sources fetch 120 days; far-capable sources
   (Ticketmaster) reach `--far-days` (180 ≈ 6 months) so festivals, big tours, and theater seasons
   land early on the radar — the TM fetcher date-windows internally so the wide pull doesn't hit the
   Discovery API's 1000-results/query cap (which was silently truncating even the 120-day pull).
   Ghost-detection stays on the near (120d) window, so far events aren't flagged unlisted before
   their feeds list them. Capture the run report (failed/skipped sources) for footers. Degrades
   gracefully. The Phase C music layer rides along: if `SPOTIFY_REFRESH_TOKEN` is set it syncs
   Spotify and folds it with `data/feedback.jsonl` into the scoring (report prints a `music layer …` line).
2. **Layer in + re-score:** add the sources the core doesn't cover (SKILL Step 2) — the Gmail
   "Events" label if available, `webfetch`/`squarespace`/`ics` venues (≤15-source budget), and this
   week's editorial roundups as `editorial_mentions`. Then `python scripts/run_digest.py --no-fetch`
   to re-dedupe + re-score and refresh `data/candidates.json` + `data/editor_pool.json`.
3. **Judge the ranking (event-editor):** fan out the `event-editor` agent over the not-yet-judged
   events in `data/editor_pool.json` (`editor.select_for_verdict` — only new/changed events cost a
   call), passing `taste.yaml`; each record carries the deterministic score + reasons + tags + lane,
   plus a Spotify `affinity` hint + the profile's listening lane when connected. Collect the per-event
   verdicts (`{tier, lane?, adjust, why, confidence}`) and merge: `python scripts/merge_verdicts.py
   <results.json>` → `data/verdicts/default.json`. These drive the slate (render) and the dashboard's
   final rank. Cached + committed, so only the delta is judged each day.
4. **Enrich:** fan out the `scene-researcher` agent over the cache-miss candidates
   (`enrich.select_for_enrichment`) → per-event tags, artist notes, curator's notes, descriptions,
   and images for the `image_wanted` picks → folded into `data/enrichment.json` (recurring artists
   reuse the cache; verify-or-omit). Then **prune**: `python scripts/prune_enrichment.py` drops
   enrichment entries for events that have since expired (cache hygiene — artist bios are kept,
   they're the durable scene knowledge). Optional periodic refresh: pass `refresh_days` to
   `select_for_enrichment` to re-research entries older than N days (default: write-once, no cost).
5. **Cache images:** `python scripts/cache_images.py` — downloads the hero images into
   `data/images/` so committed/hosted digests don't hotlink-rot. Idempotent.
6. **Render.** First the radar tier: `python scripts/build_radar.py --md radar-candidates.md` →
   `data/radar.json` (festivals/big shows/tracked far-out). Then the **primary consolidated daily
   digest**: `python scripts/render_digest.py --consolidated --md digests/latest.md --html
   digests/latest.html` — ONE doc with three sections: the next 14 days day-by-day, the weekends in
   days 15–35 (Thu–Sun), and **on the radar**. All of it is the editor **slate** (assemble over the
   scored pool + verdicts); ⭐ = the editor's must-sees, curator notes from enrichment. Also keep the
   **per-weekend look-ahead** (backend option for the dashboard's per-weekend view): for each of the
   next ~16 weekends keyed by the **Friday**, `python scripts/render_digest.py --from <Fri> --to <Sun>
   --md digests/weekends/<Fri>.md --html digests/weekends/<Fri>.html`. Near weekends fill out; far
   ones stay thin — do NOT pad.
7. Maintain `digests/weekends/index.md`: one row per weekend (date range, # events, top pick),
   soonest first; drop past weekends.
8. **Sync per-profile Spotify, then rebuild the dashboard feeds.** First, if the per-profile
   music layer is configured (env `SPOTIFY_SYNC_URL` + `SPOTIFY_SYNC_TOKEN` — the concierge
   Worker), `python scripts/sync_profiles_spotify.py`: pulls each friend who connected Spotify
   into `data/spotify/<hash>.json` (gitignored; the token stays in the Worker). SKIPs cleanly if
   unset. Then `python scripts/build_profiles.py` — builds the default `dashboard/data.json` (root
   taste + Ari's Spotify/feedback) AND every per-profile feed `dashboard/data.<hash>.json` (one per
   entry in `profiles.yaml`), each scored against **its own** music layer, so friends' feeds stay
   fresh as the catalog changes. Each feed folds in that profile's verdicts (`data/verdicts/<hash>.json`) → each event's verdict + **final rank** beside its score, and emits the profile's editor pool `data/editor_pool.<hash>.json`. To give friends the full editor treatment, judge those per profile (`event-editor` → `merge_verdicts.py --profile-hash <hash>`) and re-run build_profiles; otherwise their feeds rank deterministically against their own music and pick up verdicts next run.
9. **Per-profile digests (regenerate only when picks moved — saves tokens, but always honest):**
   for each profile in `profiles.yaml`, first GATE on whether its picks actually changed:
   `python scripts/digest_gate.py decide --feed dashboard/data.<hash>.json --md digests/<hash>/latest.md`
   - Prints **SKIP** → the profile's top picks haven't moved since the last regeneration, so the
     prose would say the same thing. **Do NOT call the LLM.** The gate has already refreshed the
     digest's one-line freshness stamp to "regenerated <when> · checked <today> · no new picks since",
     so the reader still sees clearly that it was checked and nothing changed.
   - Prints **REGENERATE** (picks changed, or no prior digest) → read the feed `dashboard/data.<hash>.json`
     (the `<hash>` is also in `feed.profile.hash`) and write a concise personalized digest to
     `digests/<hash>/latest.md` — same conversational, opinionated voice as the consolidated digest,
     ranked to THAT person's taste: their top picks across the next ~2–3 weekends, grouped by day, a
     one-line *why* each. Keep it tight; if their feed is thin, a couple of honest lines is fine
     (don't pad). Then STAMP so the gate records the new signature + writes the freshness line:
     `python scripts/digest_gate.py stamp --feed dashboard/data.<hash>.json --md digests/<hash>/latest.md`
   The dashboard's profile popup reads `digests/<hash>/latest.md`. (An `owner: true` profile shares the
   root taste.yaml, so its digest ≈ the default — expected.) Friends' feeds re-rank within ~1–2 min of a
   self-edit via CI; their *narrative* digest refreshes here only when their picks actually move.
10. Commit catalog + **`data/catalog_meta.json`** (the version stamp the dashboard's staleness
   check keys off — written by `run_digest`) + `data/enrichment.json` + `data/verdicts/` +
   `data/images/` + **`digests/latest.{md,html}`** (the consolidated digest) + `radar-candidates.md`
   + the changed weekend `.md`/`.html` + index + **all `dashboard/data*.json`** (default + profile
   feeds) + **`dashboard/catalog_meta.json`** (published by `build_dashboard`) +
   **`digests/<hash>/latest.md`** + the digest-gate sidecars **`digests/<hash>/latest.md.meta.json`**
   (signature/regenerated/checked stamps), message "digest: YYYY-MM-DD (N events, M new, K updated)".
11. If a source failed twice in a row, mark it `flaky` in sources.yaml and note it in the nearest
   weekend footer.
12. Do NOT run discover mode here (separate / manual).

> **Delivery — no email (deliberate).** The routine commits the `.md` + `.html` to the branch; do
> NOT email. The planned delivery is a **hosted, bookmarkable page** served from these artifacts,
> with on-page actions (re-scan sources, request an ad-hoc digest from the LLM). See ROADMAP
> "Hosted page". Until it exists, open the committed weekend `.html` directly.
