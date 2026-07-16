# Routine: daily weekend digests

Prompt for the scheduled cloud Routine (claude.ai/code → Routines). Paste the body below
as the routine prompt; repo = this one. Runs **daily** and maintains a rolling set of
**per-weekend** digests for the next ~4 months — each weekend gets its own file, refreshed
every day as new events are announced and lineups firm up.

Configure in the routine's environment (not here): the daily schedule, the network policy (outbound to
app.ticketmaster.com, ra.co, dice.fm + the domains in sources.yaml), `TM_API_KEY` / `POSH_TOKEN`, and
**pre-approval for the fan-out tools** — allow the Agent/Task tool (and the Workflow tool, if you use it)
so an unattended run doesn't block on an "Allow Claude to run a workflow/agent?" prompt and hang in
*Running* (see the scheduled-run note below).

**Branch mechanics — how a run reaches `main`.** There is NO target-branch setting on a routine
(an earlier version of this header claimed one; it doesn't exist, which is why runs silently
stranded 7/1–7/4). A scheduled session clones the default branch but may only push to
`claude/*`-prefixed branches — a prompt saying "push to main" cannot override that, so every run
lands on its own `claude/<session>-<suffix>` branch. The **`land-digest.yml`** workflow closes the
gap: when a `claude/*` tip is a `digest:` commit that purely extends main, CI fast-forwards main
to it and redeploys Pages (fast-forward only — main can be extended, never rewritten; a run based
on a stale main skips harmlessly and the next morning's run lands). The alternative — the
per-repo "Allow unrestricted branch pushes" toggle under the routine's Permissions — would let an
unattended session push anything to any branch; leave it OFF and let the workflow do the landing.

> Prereq: validate one manual digest run first (ROADMAP Phase 1). A daily routine pointed
> at an unvalidated pipeline with no `TM_API_KEY` just commits empty weekend files daily.

---

Run the la-events digest per .claude/skills/la-events/SKILL.md, in **weekend-set** mode:

> **Scheduled-run note (unattended).** Where a step says to *fan out* an agent — the `event-editor`
> in Step 3, and `scene-researcher` / `blurb-writer` in Step 4 — spawn them as **direct parallel
> subagents** (several Agent/Task calls in one turn). Do **NOT** reach for the **Workflow** tool here:
> it raises an interactive "Allow Claude to run a workflow?" approval that a scheduled run cannot
> answer, so the run stalls in *Running* indefinitely (and never commits). Plain parallel subagents
> need no such gate; if you must use Workflow, pre-approve it in the routine's environment (above).

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
4. **Enrich — two tiers (hybrid coverage).** Both write to `data/enrichment.json`, keyed the same,
   so the dashboard reads one place; both are write-once cached (only the daily delta costs calls).
   - **Full head (~100):** fan out the `scene-researcher` agent over the cache-miss candidates in
     `data/candidates.json` (`enrich.select_for_enrichment` — misses + any blurb-tier event that
     climbed into the head, which it upgrades) → per-event tags, artist notes, curator's notes, and
     descriptions (recurring artists reuse the cache; verify-or-omit; `enriched_tier: full`).
   - **Cheap blurb tier:** fan out the `blurb-writer` agent over `enrich.select_for_blurb` applied to
     `data/blurb_pool.json` (the ranked band below the head). It writes ONE factual description line
     per event, no web/artist research (haiku, Read/Write only). `select_for_blurb` already skips
     events that have any cache record OR a usable source `detail` (those display raw detail for
     free), so only genuine gaps cost a call. Fold results with `enrich.update_blurb_cache`
     (`enriched_tier: blurb`; never downgrades a full record). The blurb-pool `overflow` (events
     past the cap, in the run report) intentionally gets no blurb — they fall back to raw detail.
   - Then **prune**: `python scripts/prune_enrichment.py` drops enrichment entries for events that
     have since expired (cache hygiene — artist bios are kept, the durable scene knowledge).
   Optional periodic refresh: pass `refresh_days` to `select_for_enrichment` to re-research full
   entries older than N days (default: write-once, no cost).
5. **Render.** First the radar tier: `python scripts/build_radar.py --md radar-candidates.md` →
   `data/radar.json` (festivals/big shows/tracked far-out) AND `data/around_town.json` (the
   near-window city-pulse set — civic/arena/festival signals regardless of taste score). Then the
   **primary consolidated daily digest**: `python scripts/render_digest.py --consolidated --md
   digests/latest.md` — ONE doc whose sections follow the root **`digest.yaml`** `sections:` list
   (Track B4, the renderer now honors it): **Don't miss** (the top ~6 across the window,
   tier-primary, whys prefilled from curator notes/verdicts), the day-by-day body (next 14 days +
   the weekends in days 15–35, Thu–Sun), **Around town** (city-pulse, NOT taste-ranked, de-duped
   against the slate), and **on the radar**. All slate content is the editor slate (assemble over
   the scored pool + verdicts); ⭐ = the editor's must-sees. Also keep the
   **per-weekend look-ahead** (backend option for the dashboard's per-weekend view): for each of the
   next ~16 weekends keyed by the **Friday**, `python scripts/render_digest.py --from <Fri> --to <Sun>
   --md digests/weekends/<Fri>.md`. Near weekends fill out; far
   ones stay thin — do NOT pad.
5b. **Voice pass (Tier-3) on the consolidated digest — the insider layer.** Edit
   `digests/latest.md` in place, filling ONLY the marked slots:
   - replace `<!-- tier3:intro -->` with a 2–4 sentence intro in the LA-insider voice — the
     week's shape, what kind of stretch it is, where the heat is;
   - tighten each **Don't miss** why at its `<!-- tier3:why <key> -->` marker (the scaffold
     prefills verdict/curator text — rewrite for voice and brevity, don't template);
   - optionally give an **Around town** item a one-line gloss at its `<!-- tier3:gloss -->`
     marker, only where you genuinely have something to say.
   **HARD RULE: never add, remove, or reorder events or sections** — the slate is deterministic
   and diffable; this pass adds voice, not selection. Honor `digest.yaml` `length`/`tone`/
   `emphasis`. One pass, a few K tokens (see docs/PIPELINE.md cost ledger).
6. Maintain `digests/weekends/index.md`: one row per weekend (date range, # events, top pick),
   soonest first; drop past weekends.
7. **Sync Spotify, rebuild ALL dashboard feeds (deterministic — free), then gate the LLM layer.**
   - First, if the per-profile music layer is configured (env `SPOTIFY_SYNC_URL` +
     `SPOTIFY_SYNC_TOKEN` — the concierge Worker), `python scripts/sync_profiles_spotify.py`
     (SKIPs cleanly if unset).
   - Then `python scripts/build_profiles.py` — the default `dashboard/data.json` AND every
     per-profile feed `dashboard/data.<hash>.json`, each scored against **its own** music layer,
     folding in that profile's **cached** verdicts (`data/verdicts/<hash>.json`) → verdict + final
     rank beside each score, emitting per-profile editor pools `data/editor_pool.<hash>.json` and
     the `profile.self_edit` diff/reflected block. The deterministic re-rank is free and runs
     nightly for **everyone**, so every table stays current (new events in, expired out).
   - Then gate the expensive layer: `python scripts/profile_refresh_gate.py --json
     data/refresh_gate.json` — one decision per profile: **REFRESH** (their taste.yaml /
     profile.yaml / digest.yaml / feedback log changed since their last enrichment, or never
     enriched), **SKIP** (config unchanged — the catalog moving does NOT count), or **OWNER**.
     **Policy (2026-07): the per-profile LLM pass — event-editor verdicts + the narrative digest —
     does not rerun nightly on catalog movement.** It runs tonight only for REFRESH profiles;
     everyone else refreshes it themselves via the dashboard's **Update** button
     (`rebuild-profile.yml`; the page nudges with a popup once their curated layer is 3+ days old).
8. **Per-profile LLM pass — ONLY the gate's REFRESH profiles (plus the owner copy).**
   - **Owner (OWNER decision) — copy, never prose, never a stub:** its taste IS the root taste, so
     run `cp digests/latest.md digests/<hash>/latest.md` (the committed file must always BE the
     full digest — GitHub and locally-served dashboards read it directly), then STAMP:
     `python scripts/digest_gate.py stamp --feed dashboard/data.<hash>.json --md digests/<hash>/latest.md`
   - **Each REFRESH profile — the single-profile slice** (same contract and caps as
     `routines/profile-digest-prompt.md`): judge its editor pool `data/editor_pool.<hash>.json`
     (top ~40 by score, `editor.select_for_verdict` against `data/verdicts/<hash>.json`, ≤2
     `event-editor` batches) → `python scripts/merge_verdicts.py <results.json> --profile-hash
     <hash>` → re-fold with `python scripts/build_profiles.py --only-hash <hash>` → write the
     personalized narrative digest to `digests/<hash>/latest.md` — conversational, opinionated,
     ranked to THAT person: top picks across the next ~2–3 weekends, grouped by day, a one-line
     *why* each; thin feed → a couple of honest lines, don't pad. **Honor
     `feed.profile.digest_prefs`** if present (`length` · `group_by` · `sections` ·
     `max_picks_per_day` · `emphasis` · `tone` · `notes`). Then STAMP with digest_gate as above.
   - **SKIP profiles: no LLM work.** No editor batches, no narrative rewrite, no digest_gate
     decide/freshness-line rewrite — their verdicts + digest stay as-committed so their "last
     refreshed" dates stay truthful. Their feed was already re-ranked deterministically in step 7;
     new events simply carry no verdict until their taste changes or they hit Update — that's the
     designed behavior, not staleness to fix.
   The dashboard's profile popup reads `digests/<hash>/latest.md`. Friends' feeds still re-rank
   within ~1–2 min of a concierge self-edit via CI (build-profiles.yml), and that same edit opens
   this gate on the following night, so an edited taste always gets the full LLM treatment within
   a day even if they never click Update.
9. Commit catalog + **`data/catalog_meta.json`** (the version stamp the dashboard's staleness
   check keys off — written by `run_digest`) + `data/enrichment.json` + `data/verdicts/` (only the
   refreshed profiles' files change) + **`digests/latest.md`** (the consolidated digest) +
   `radar-candidates.md` + the changed weekend `.md` + index + **all `dashboard/data*.json`** feeds
   (the deterministic re-rank touches every one nightly)
   + **`dashboard/catalog_meta.json`** (published by `build_dashboard`) + the refreshed
   **`digests/<hash>/latest.md`** files + their digest-gate sidecars
   **`digests/<hash>/latest.md.meta.json`** (signature/regenerated/checked stamps), message
   "digest: YYYY-MM-DD (N events, M new, K updated; P profiles refreshed)".
10. If a source failed twice in a row, mark it `flaky` in sources.yaml and note it in the nearest
   weekend footer.
11. Do NOT run discover mode here (separate / manual).

> **Delivery — no email (deliberate).** The routine commits the `.md` to the branch; do
> NOT email. The planned delivery is a **hosted, bookmarkable page** served from these artifacts,
> with on-page actions (re-scan sources, request an ad-hoc digest from the LLM). See ROADMAP
> "Hosted page". Until it exists, open the committed weekend `.md` directly.
>
> **Operational nudges ride in the digest, not your inbox** (consistent with no-email):
> `render_digest --consolidated` auto-adds a **Posh-token re-auth banner** at the top of
> `digests/latest.md` when `POSH_TOKEN` is within 5 days of expiry (or already dead) —
> Posh has no token refresh, so the JWT must be re-captured by hand ~monthly. It's automatic
> (reads the token's own expiry; no action in this routine). Sanity-check anytime with
> `python scripts/posh_token_status.py`.
