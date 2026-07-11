# PLAN — reshape la-events to the actual vision (2026-07-08)

> **Status update (7/11): Track A executed** (un-tabled by Ari) — A1 (random capability
> tokens, v2 salt, migration of all hash-keyed artifacts), A3 (feed location hygiene), and
> A4 (stars + the /react endpoint) are landed on `claude/track-a-execution-vu3gif`.
> **A2 is the one open piece and it gates the rest:** the token map (profiles.yaml) sits in
> the repo, so A1's privacy win is only real once the repo is private — decide GitHub Pro
> vs. Cloudflare Pages (below), flip it, then rotate the tokens once (they appeared in
> public history) and send the 6 links.
>
> **Status update (Ari, 7/8):** **Track A tabled** (revisit later). **Track C dropped** —
> dining and the night-planner-class capability stay: the concierge should remain the broad
> "can do it all" layer, including staying apprised of new/hot restaurants, keeping a
> good-restaurants list, and facilitating multi-event plans (with or without other users).
> **Track B is active** — detailed one level further in `TRACK-B-SPEC.md` before execution.
> Track D unchanged (pending).

Follow-up to `AUDIT-2026-07-07-mission.md` / `AUDIT-2026-07-07-product.md`, incorporating
Ari's restated vision. Three tracks of small PRs: **A** privacy + identity (tokens, private
repo, stars), **B** LLM-first ranking + the product layer, **C** de-scope (the Jenga cuts),
plus a small **D** trust track that serves the artist-discovery core. Each PR is sized and
lists the exact files it touches. Nothing here is a rebuild; the largest single PR is a
medium.

## The vision (acceptance criteria for everything below)

A personal app for Ari (friends second, as a gift): aggregate as many LA events as possible
that might be of interest OR are notable for the city; present them smart and personal — an
LLM curates the weekend, explains who the artists are and why you'd like it (uncover the DJ
*before* the show); make LA feel alive (city-pulse: LA Marathon / Kendrick / seasonal
one-offs, "stay apprised" even when not personally on-taste); a browsable database view;
simple mutual stars among friends; recurring/seasonal browse later. Breadth is a feature.
Dining/night-planner are out. Social beyond stars is out.

Two standing principles from the discussion:
- **LLM ranks, Python bounces and bookkeeps.** Deterministic code does dedupe, dates,
  filtering out clear garbage, caching, and cost gates — it no longer decides what the LLM
  never sees, and keyword weights stop being the ranking authority.
- **The factory pauses.** No new fetchers/pipeline sophistication until Tracks A–C land
  (coverage is already ahead of the product).

---

## Track A — Private for real, identity for free

### A1 — Random capability tokens replace name-derived hashes  (S)
The current access key is `sha256("la-events/v1:" + firstname)[:16]` — derivable by anyone,
which is the whole privacy hole. Swap the hash *input* from username to a random token; the
rest of the machinery is unchanged.
- `profiles.yaml`: add `token:` per profile (`secrets.token_hex(8)`, generated once); bump
  `salt:` to `la-events/v2:` so all old name-derived URLs die at cutover.
- `scripts/build_profiles.py:42-44`: `profile_hash(token, salt)` instead of username; error
  if a profile lacks a token.
- `dashboard/index.html:~1879`: login = visiting `?t=<token>` (stored in localStorage) or
  pasting it once; remove the type-your-name prompt. Friend UX gets *easier*: each friend
  gets one link, texted once, bookmarked.
- `backend/concierge-worker.js:544-600, 931-945`: `resolveProfile` matches token-hashes.
  Side effect that closes the audit's canEdit hole for free: the owner hash is no longer
  derivable, so a random BYOK caller can no longer mint it and edit root `taste.yaml`.
- Migration: regenerate feeds, send 6 links. Done.

### A2 — Repo private + hosting call  (S)
With tokens random, the *site* being public is fine (unguessable capability URLs — the
Google-Docs-link model). The *repo* going private is what hides `profiles.yaml` (the token
map), taste files, and git history.
- **Option 1 (zero work):** GitHub Pro → flip repo to private; Pages keeps serving.
- **Option 2 (no Pro):** add a `wrangler pages deploy dashboard/` step to
  `deploy-dashboard.yml` (Cloudflare Pages, free, private-repo-friendly); update Worker
  `DATA_URL`/`ALLOWED_ORIGIN`.
- **Decision needed from Ari:** which option.

### A3 — Published-data hygiene  (S)
Regardless of hosting: stop shipping precision that display doesn't need.
- `build_dashboard.py` / `build_profiles.py`: round `config.home` coords to ~2 decimals /
  neighborhood centroid in emitted feeds; exact coords stay in the (now-private) repo for
  travel math. Cross-streets: drop from feeds entirely.

### A4 — Stars (the one social feature)  (M)
Token = identity, so this becomes small. A star is simultaneously the social signal and the
first-ever input to the learning loop (double duty).
- Worker: new `POST /react {profile, event_key, kind: star|unstar|hide}`; gate = valid
  profile hash (same as edits); commits one line to `data/reactions.jsonl` AND to that
  profile's `data/feedback.<hash>.jsonl` (star→`loved`, hide→`hide` — the existing tested
  fold-in path picks it up with zero new code).
- `build_dashboard.py`/`build_profiles.py`: fold stars onto events (`stars: ["Lori","Raffi"]`).
- `dashboard/index.html`: star button per card (optimistic locally; friends' stars appear on
  next rebuild — fine at this cadence).
- `render_digest.py`: show "★ Lori" beside starred events in digests.

## Track B — LLM-first ranking + the product Ari actually described

### B1 — Recall flip: the editor judges everything surfaceable  (S)
Today `editor_pool(per_lane=4, floor=4)` (lib/editor.py:83, run_digest.py:167-169) lets the
keyword score decide what the LLM never sees. Change the defaults: judge **all slate-lane
events in the window** (non-slate keeps a small floor). The verdict cache makes this
affordable — one-time backlog of a few hundred judgments (the 7/01 run already proved a
600-verdict day is fine), then the steady-state delta (~50/day) is unchanged.

### B2 — Authority flip: verdicts govern every downstream gate  (S/M)
`assemble.py` is already tier-primary inside the slate. The raw score's remaining authority
is exactly three gates — move each to verdict-aware ordering (`rank_score`):
- enrichment head selection (`run_digest --top 100`) — enrich what the *editor* rates, not
  what keywords rate;
- blurb-pool selection — same;
- dashboard default sort — `final_rank` (score column stays visible as the transparent spine).
Score's remaining jobs: tiebreak, staleness detection, bookkeeping. That's the whole flip —
no scorer rewrite.

### B3 — taste.yaml becomes prompt material; kill the substring bug class  (S)
- `lib/editor.pool_doc`: embed the taste profile verbatim in the pool doc (the editor is now
  the ranker; the human-authored taste narrative is its brief). Keyword weights stay only as
  the coarse filter + tiebreak — documented as such, and no longer worth hand-tuning.
- Whole-token matching for `artists_tracked` in `build_radar.py` + scoring (fixes the
  FISHER-matches-"Fisher and Thames" class; matters less once score is demoted, but radar
  badges still show it).

### B4 — City-pulse lane + the flagship gets its voice  (M — the point-3 concept, delivered)
- `build_radar.py`/`assemble.py`: a `notable` detector — arena gazetteer (already in
  assemble.py) + `festivals.yaml` + civic/seasonal signals — feeding an **Around town**
  section that is deliberately NOT taste-filtered (LA Marathon, Kendrick, River Solstice).
- `render_digest.py`: emit the `around_town` + `dont_miss` scaffolds `digest.yaml` already
  requests (and flip `tests/test_render.py:40`, which currently asserts Don't-miss is
  *absent*).
- `routines/daily-digest-prompt.md`: an explicit step — after rendering, the main agent
  writes the Tier-3 layer onto `digests/latest.md`: short intro, Don't-miss with one-line
  whys, Around-town gloss (this is the step the audit found pointed at the commit step).
  The per-profile digests prove the output; this just runs it on the flagship.

## Track C — De-scope (cuts, in descending size of Jenga removed)

### C1 — Retire la-dining + night-planner  (S — mostly deletions)
Remove: `.claude/skills/la-dining/`, `.claude/agents/night-planner.md`,
`dining-sources.yaml`, `dining-taste.yaml`, `data/dining.json`,
`routines/dining-radar-prompt.md`, `scripts/travel.py`, `scripts/make_ics.py`, dining
routes in the concierge SKILL, dining references in CLAUDE.md/ROADMAP.
Keep: `scripts/lib/geo.py` (pipeline.py imports it — near-home boost + neighborhoods).
**Decision needed:** delete (git history preserves everything — recommended) vs. move to an
`attic/` dir.

### C2 — Retire per-friend Spotify machinery  (S)
Zero friends ever connected; the owner path stays. Remove: Worker `handleSpotify` block
(concierge-worker.js:~1001-1100) + `SPOTIFY_KV` binding, `.github/workflows/spotify-sync.yml`,
`scripts/sync_profiles_spotify.py`, the dashboard "Connect Spotify" affordance.
Keep: `fetch_spotify.py` + the owner affinity layer in `run_digest` (live, working).

### C3 — Worker cost/complexity trim  (S)
- `EFFORT` default max→high; advisor (Opus) opt-in per request instead of on-by-default
  (concierge-worker.js:57-58,130-132).
- **Decision needed:** keep or drop BYOK (`x-anthropic-key`). With tokens as the gate it's
  redundant as an auth path; keep only if you want friends paying their own chat spend.

### C4 — Retire the self-edit diff/"reflected" badge apparatus  (S/M)
Keep the chat self-edit itself (the one feature friends demonstrably use). Remove the
`profile.self_edit` block in `build_profiles.py`, the two-tab diff modal in the dashboard,
and the `fetch-depth: 0` requirement in `build-profiles.yml`/`rebuild-profile.yml`; replace
with a one-line "taste updated <date>" stamp.

### C5 — Docs re-baseline  (S, last)
Rewrite ROADMAP around this plan (it's 2+ weeks stale and self-contradictory per the audit);
update CLAUDE.md layout + PIPELINE.md as the cuts land. `group_picks.py`: keep (small, and
it's the natural engine for a future "who's in?" on top of stars).

## Track D — Trust (small, but it guards the core: uncovering artists is the product)

### D1 — Fix verification polarity + per-artist confidence  (S)
- `.claude/agents/scene-researcher.md:38`: invert — web-verify every concrete claim
  (real names, labels, affiliations) unless the artist is unambiguous-superstar tier; the
  mid-fame band is where confident memory errors live (audit F3: Jayda G, VTSS, Demuir).
- Artist cache entries gain `confidence`; `event-editor.md:86` stops calling cached notes
  "verified".
- Add a plain `pytest scripts/tests` job to CI (currently zero tests run anywhere).

### D2 — Fact-janitor + corrections become possible  (S)
- `lib/enrich.update_cache` (enrich.py:236-238): allow overwriting an artist note (today
  insert-only — errors are literally unfixable).
- A monthly routine step: re-verify the ~30 most-reused/oldest artist bios (189 total —
  one cheap batch), correct in place.

---

## Sequencing

| Week | PRs | Result |
|---|---|---|
| 1 | A1, A2, C1, C2 | Private + token links live; biggest dead weight gone |
| 2 | B1, B2, B4, A4 | LLM is the ranker; flagship digest has its voice + city-pulse; stars live |
| 3 | A3, B3, C3, C4, D1, D2, C5 | Hygiene, trust fixes, docs match reality |

One-time costs: the B1 verdict backlog (a few hundred judgments, one run) and re-sending 6
friend links (A1). Everything else is neutral or cheaper than today.

## Decisions Ari owes the plan
1. **A2:** GitHub Pro (repo private, Pages as-is) vs. Cloudflare Pages deploy.
2. **C1:** delete dining/night-planner outright (recommended; git history keeps it) vs. attic dir.
3. **C3:** keep or drop BYOK.
4. **B1:** green-light the one-time verdict backlog run.
