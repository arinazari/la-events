# PIPELINE — when each component runs, and how it stays cheap

The orchestration map for la-events: every entry point, what it runs, what it costs, and the gate
that stops it running needlessly. Source of truth for "when does X happen" — it used to live spread
across the routine prompt, five workflows, the Worker, and the dashboard JS.

## The one principle

**The catalog `content_version` is the heartbeat. Every downstream stage compares against it (or a
signature derived from it) and no-ops when its input hasn't changed.** Adds/drops/reschedules AND
price / lineup / door-time / sold-out changes all move it; merely re-seeing an unchanged event does
not. So both the automatic (nightly) and on-demand (button) paths are cheap by construction — work
only happens where something actually changed.

## Triggers (every entry point)

| Trigger | Fires | Runs | LLM cost | Gate that prevents waste |
|---|---|---|---|---|
| **Daily routine** (`routines/daily-digest-prompt.md`) | scheduled (cron) → commits `main` | fetch → dedupe → score → editor → enrich → render consolidated + weekend look-aheads → build all feeds → per-profile narratives → commit → deploy | editor (delta only), enrich (misses only), consolidated intro, per-profile narratives (gated) | editor=`select_for_verdict`, enrich=`select_for_enrichment` write-once, narratives=`digest_gate`, both subagents pinned Sonnet |
| **Owner "Refresh events DB"** | page → Worker `/refresh-events` → `refresh-events.yml` | deterministic: fetch → catalog → default feed → render consolidated → commit → deploy | **none** | Worker **debounce** (`REFRESH_MIN_MINUTES`, default 15) → 429 if pulled recently |
| **User "Update my ranking & digest"** | page → Worker `/rebuild-profile` → `rebuild-profile.yml` | deterministic feed (commit), then full LLM pass (editor + enrich + narrative) for **one** profile | medium (1 profile, Sonnet) | client enables only when `feedStale ‖ tasteDirty` + busy-lock; deterministic feed lands even if the LLM step times out |
| **Concierge taste/profile self-edit** | Worker commits YAML → `build-profiles.yml` (path filter) | deterministic re-score of that one feed → commit → deploy | **none** (defers the narrative to Update) | path-filtered to `profiles/**/taste.yaml` + `profiles.yaml`; client marks the profile "dirty" |
| **Spotify connect** | Worker `/spotify/callback` → `dispatchSync` → `spotify-sync.yml` | sync that profile's listening → rebuild its feed → deploy | **none** | per-connect; token never leaves Cloudflare |

On-demand, never scheduled: ad-hoc `/la-events digest`, `night-planner`, `source-scout`/Discover,
flyer capture. They read the live catalog and don't run the nightly machinery.

## The freshness clock — `catalog_meta.json`

`run_digest` writes it after every fetch; `build_dashboard` republishes it beside the feeds.

```jsonc
{
  "version":         "…",   // identity hash (venue|date|title) — "is this a different SET of events"
  "content_version": "…",   // identity + price|start|lineup|status — "did anything the user sees move"
  "count":           2081,
  "fetched_at":      "…Z",  // UTC; the dashboard's "last data pull" + the refresh-debounce clock
  "added":           5,     // this run's delta — drives the digest line + dashboard "what changed"
  "updated":         2,
  "changes":         [ { "title": …, "fields": ["price","start"] }, … ]   // bounded sample
}
```

Who reads it:
- **Dashboard staleness badge** — `isFeedStale()` compares the feed's `catalog_content_version` to
  the live `content_version`; different → "Update my ranking & digest" lights. (Falls back to the
  identity version for a feed built before content_version existed — reads stale once, self-heals.)
- **Refresh completion poll** — keys off `fetched_at` advancing (a refresh always republishes it),
  not the version (which wouldn't move on a no-change refresh — that was the spinning-button bug).
- **"What changed" readout** — `added`/`updated`/`changes`, tap to itemize.
- **Digest freshness line** — `render_digest` prints "Updated <when> · N new · M updated" or
  "Checked <when> · no new or changed events", and badges events 🆕 new / ↻ updated inline.

Per-event stamps (`first_seen`, `updated_at`, `changed_fields`) are written by
`pipeline.diff_catalog` and persisted on the catalog record.

## The self-edit reflected signal — "did my taste change land yet?"

Separate from the *catalog* clock above: when the concierge edits a profile's
`taste.yaml`/`profile.yaml` (a commit), the dashboard shows a **diff** of the change and
whether it's **reflected** in that profile's latest *data enrichment* (its committed
event-editor verdicts + narrative digest). Both are derived from git **at build time** by
`build_profiles.py` and baked into each feed's `profile.self_edit.{taste,profile}` block —
no backend; the static page just renders it.

```jsonc
"self_edit": { "taste": {
  "history":   [ { "date": "2026-06-23", "summary": "track Peggy Gou" } ],  // non-automated commits only
  "diff":      "…unified diff…",      // pending changes (enrich→HEAD), else the latest applied change
  "diff_kind": "pending|applied|none",
  "reflected": true,                  // file identical between last enrichment commit and HEAD (content-based)
  "enriched_at": "2026-06-23"
}, "profile": { … } }
```

- **reflected** is content-based (`git diff <last-enrichment-commit>..HEAD -- <file>` is empty),
  so an edit-then-revert correctly reads as reflected. `enrich_paths` per profile =
  `digests/<hash>/latest.md` + `data/verdicts/<hash>.json` — the per-profile narrative + verdicts that
  **only the full LLM pass writes**; their last-commit *is* "the most recent enrichment". Same bar for
  everyone, **owner included**: we deliberately do NOT count the consolidated `digests/latest.md`,
  because a cheap deterministic Refresh re-renders it without re-running the LLM, which would flip the
  owner green before the AI reprocessed their taste. The page treats `reflected === false` as the
  authoritative **taste-dirty** state that
  lights "Update my ranking & digest" (the localStorage flag is just the optimistic pre-CI bridge).
- **Timing.** A concierge edit → `build-profiles.yml` re-ranks the feed → it bakes **pending**.
  Clicking **Update** (`rebuild-profile.yml`) runs the LLM pass, commits the enrichment, then
  rebuilds the feed once more in the same commit so it bakes **reflected** immediately — ranking and
  enrichment are one step from the user's view. Nightly is eventually-correct (a same-day edit reads
  pending until the next Update or the following night). Needs `fetch-depth: 0` on those workflows
  (a shallow clone has no diff); degrades to no-badge when history is unavailable.

## Per-stage run conditions & no-op behavior

| Stage | Runs | No-ops when | Cost tier |
|---|---|---|---|
| fetch + dedupe + expire + score (`run_digest`) | every routine run / refresh | — (always; deterministic, cheap). Merge is **freshest-wins** for price/time/lineup/status, so in-place updates land | none |
| **event-editor** (Tier 1 verdicts) | routine + per-user rebuild | event already judged at this score (`select_for_verdict`) | Sonnet, delta only |
| **scene-researcher** (Tier 1 full enrichment, top-100 head) | routine + per-user rebuild | event already full-tier in `enrichment.json` (write-once; a blurb-tier event in the head is *re-selected* to upgrade) | Sonnet, misses + upgrades only |
| **blurb-writer** (Tier 2 cheap enrichment, band below head) | routine | event already has any cache record OR usable source `detail` (`select_for_blurb`) | Haiku, gaps only, no web |
| consolidated narrative intro | every routine run | — (cheap; the slate is deterministic, only a short intro is LLM) | small |
| **per-profile narrative** | routine + per-user rebuild | feed signature unchanged (`digest_gate decide` → SKIP) | gated; one narrative per *changed* feed |
| `build_dashboard` / `build_profiles` | end of routine / on edit | — (deterministic) | none |
| renderers (`render_digest`) | every routine run | — (deterministic) | none |

## Cost ledger — where tokens go, and the bound on each

1. **Nightly editor** — only new/score-drifted events are judged; cached + committed per profile. Sonnet.
2. **Nightly enrichment (two tiers)** — *full* (scene-researcher, top-100 head): write-once on
   event-id + artist; recurring artists researched once; Sonnet. *blurb* (blurb-writer, the bounded
   band below the head): one description line, write-once, and only for events with no record AND no
   usable source `detail` — so events carrying a source description cost **0** (raw-detail fallback);
   Haiku, no web. Both amortize to the daily delta. The blurb pool is capped (`--blurb-top`); the
   reported overflow gets raw detail or nothing, never a call.
3. **Per-profile narratives** — regenerated only when that feed's top-N picks moved (`digest_gate`).
   On a quiet day this is **0 LLM calls**; it scales with *changed* friends, not all friends.
4. **Consolidated intro** — small, every run (the body is deterministic slate).
5. **Owner refresh** — **no LLM**, and debounced so a rapid re-click doesn't re-sweep sources.
6. **Per-user rebuild** — Sonnet; gated client-side to "stale or taste-dirty"; the deterministic feed
   commits first so a timed-out LLM step still leaves the ranking fresh.
7. **BYOK concierge chat** — the friend's own key/spend; may opt into Opus per request.

## On-demand vs automatic — quick guide

- **Happens automatically (nightly):** full fetch, re-rank, enrichment, all digests, all feeds.
- **Owner clicks Refresh:** intra-day catalog refresh for everyone (deterministic; others then see
  their feed flagged stale and self-update). Debounced.
- **User clicks Update:** that one person's full LLM re-rank + digest, against the latest catalog.
- **User edits taste/profile via concierge:** that one feed re-scores in ~1–2 min (deterministic);
  the narrative refreshes on their next Update (or the nightly gate, when picks move).
- **User connects Spotify:** that one feed re-ranks to their listening.

## Knobs

| Knob | Where | Default | Effect |
|---|---|---|---|
| `REFRESH_MIN_MINUTES` | Worker env | 15 | refresh debounce window |
| `model` input | `rebuild-profile.yml` / Worker `body.model` (BYOK) | `sonnet` | escalate a rebuild / chat to Opus when it matters |
| `event-editor` / `scene-researcher` `model:` | agent frontmatter | `sonnet` | nightly subagent tier |
| `blurb-writer` `model:` | agent frontmatter | `haiku` | cheap-tier description writer (no web tools) |
| `--top` | `run_digest` | 100 | full-enrichment head size (scene-researcher) |
| `--blurb-window` / `--blurb-top` | `run_digest` | 35d / 0 | blurb (cheap-tier) pool span (the real bound) + optional safety cap (0 = off, cover the whole window) |
| `refresh_days` | `select_for_verdict` / `select_for_enrichment` | `None` (write-once) | optional periodic re-judge / re-research |
| `--top-n` | `digest_gate` | 25 | how many picks define a digest's signature |

## File map

- `scripts/run_digest.py` — the deterministic core; writes `catalog_meta.json` + the delta.
- `scripts/lib/catalog_meta.py` — `version` / `content_version` / delta.
- `scripts/lib/pipeline.py` — `content_index` + `diff_catalog` (the change set + per-event stamps).
- `scripts/lib/dedupe.py` — `merge` (freshest-wins volatile fields).
- `scripts/lib/editor.py` / `enrich.py` — the delta/write-once selection that bounds LLM cost.
- `scripts/render_digest.py` — the freshness line + 🆕/↻ markers.
- `scripts/digest_gate.py` — per-profile regen gate + honest freshness stamp.
- `scripts/build_profiles.py` — per-profile feeds + the `profile.self_edit` diff/reflected block (from git).
- `backend/concierge-worker.js` — `/refresh-events` (debounced) + `/rebuild-profile` + BYOK model.
- `.github/workflows/{refresh-events,rebuild-profile,build-profiles,spotify-sync,deploy-dashboard}.yml`.
- `dashboard/index.html` — staleness badge, "what changed" readout, refresh/update buttons, taste/profile diff modal.
- `routines/daily-digest-prompt.md` — the nightly orchestration.
