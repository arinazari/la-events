# Repository audit: performance, redundancy, and obsolete code

**Status: proposals recorded; implementation has not been authorized by saving this document.**

This is the shared audit and work tracker for Codex, Claude Code, and the repository owner. Keep findings, decisions, validation, and implementation progress here rather than in a workspace-only file or separate agent-specific plans.

## Provenance and how to use this document

- Original audit: **2026-10-07**, at commit [`6c61c4d09e162f4ee20bdf3a86c57abf82fdfb08`](https://github.com/arinazari/la-events/tree/6c61c4d09e162f4ee20bdf3a86c57abf82fdfb08).
- Repository HEAD when this record was added: `34c38dcfedc9e762a79edda256ac8f528fbc9ed1`. The checkout has advanced since the audit.
- The earlier report was saved outside the repository and did not survive into the current workspace. This record restores its findings and measurements from the audit conversation. It is not a new audit of the later HEAD.
- All measurements and source line numbers below refer to the original audit baseline. Relative links open the current file; locate the named function/step and revalidate it before acting. A finding may already have been addressed by intervening changes.
- The original review made no application changes. Recording this document and its agent-instruction pointers also makes no application, dependency, data, or workflow changes.

Before implementing an item, read its evidence and risks, compare it with current code, and update its status. Implement only the scope requested by the user; this backlog is not blanket approval. After work, record the actual change, checks and results, and commit/PR reference. Preserve historical measurements and label new ones with their revision and conditions.

Use the stable IDs below in discussions and commits. Statuses: `Proposed` (not yet revalidated at current HEAD), `Confirmed` (revalidated, still unimplemented), `In progress`, `Done` (implemented with evidence), `Deferred`, or `Not applicable` (explain why). Add decisions to the log at the end; do not silently delete findings.

## Shared work tracker

Priorities are recommendations: **P1** protects correct updates and published behavior; **P2** improves performance or maintainability. Every item starts as `Proposed`, including originally reproduced bugs, because current HEAD has not been re-audited.

| ID | Priority | Proposal | Status | Validation / decision / commit |
| --- | --- | --- | --- | --- |
| A01 | P1 | Merge changed cache entries instead of restoring stale complete files | Proposed | — |
| A02 | P1 | Preserve queued user updates and shorten the deployment lock | Proposed | Depends on shared-writer safety in A01 |
| A03 | P1 | Replace two old digest stagers with the existing canonical script | Proposed | — |
| A04 | P1 | Retry concurrent reaction-write conflicts against fresh state | Proposed | — |
| A05 | P2 | Anchor the Spotify callback's rebuild dispatch | Proposed | — |
| A06 | P2 | Store series summaries once per series | Proposed | — |
| A07 | P2 | Add a slim boot feed; consider shared facts plus profile overlays | Proposed | — |
| A08 | P2 | Target profile/Spotify rebuilds and preserve state on sync failure | Proposed | — |
| A09 | P2 | Score once, derive date windows, and reuse prepared match inputs | Proposed | — |
| A10 | P2 | Reduce fuzzy-dedupe work without weakening matching rules | Proposed | — |
| A11 | P2 | Use bounded concurrency for independent source fetches | Proposed | — |
| A12 | P2 | Make Worker retrieval compact, relevant, and bounded | Proposed | — |
| A13 | P2 | Page Explore rows and cache derived lists | Proposed | — |
| A14 | P2 | Repair personalized/offline feed caching | Proposed | — |
| A15 | P2 | Implement the intended price edge cache | Proposed | — |
| A16 | P1 | Share a correctly zoned LA date helper | Proposed | — |
| A17 | P2 | Reuse the tested calendar primitives for per-event export | Proposed | — |
| A18 | P2 | Make the generated frontend runtime reproducible before pruning it | Proposed | — |
| A19 | P2 | Review obsolete artifacts, helper candidates, and stale documentation | Proposed | Manual/external usage must be checked before deletion |
| A20 | P2 | Run existing regression suites automatically in CI | Proposed | — |

## Evidence and measurement limits

Original audit validation:

- **515 Python tests passed.** Backend suites passed **20 edit, 26 calendar, and 6 star-fold tests**.
- Catalog: **3,618 records**, including **59 unlisted** records; each dashboard feed contained **3,559 events**.
- Default feed: **8,960,034 bytes raw / 1,091,666 bytes gzip**. Eighteen default/profile feeds totaled **159,813,376 bytes**, about 160 MB decimal.
- The audit used source inspection, local benchmarks, in-memory payload projections, and mocked Worker/network behavior. Payload projections were not complete application implementations.
- Timings were measured on the original cloud machine and data, not production. Instrumentation supplied call counts separately from uninstrumented wall times.
- Dashboard calculation timings excluded real React/DOM rendering, layout, painting, and user-device costs.
- Live Actions runs, paid model calls, production writes, production Worker memory, and live source-fetch speedups were not exercised.

These are historical results, not checks rerun when this record was added. Before implementing a performance proposal, repeat relevant measurements at the selected revision. Do not add percentage savings from overlapping optimizations together.

## Reliability fixes

### A01 — Merge produced cache changes instead of restoring old complete files

**Evidence:** [rebuild-profile.yml](../.github/workflows/rebuild-profile.yml), baseline lines 224–241, copies whole enrichment and verdict files aside, fetches/resets to current main, and restores the older whole-file snapshots. It restores `data/verdicts/default.json` even during friend work that did not change that store. [land-digest.yml](../.github/workflows/land-digest.yml), baseline line 40, uses a separate concurrency group, so the Pages lock does not serialize routine landing with the rebuild.

**Consequence:** another writer's new entries can be overwritten. This is a source-confirmed race scenario, not evidence that a particular production entry was lost.

**Proposal:** record the base and entries actually changed by this run; merge those deltas against fresh main; preserve unrelated/newer entries; retry competing pushes after a fresh merge. Carry default verdict changes only for owner work. Do not swallow a failed fetch/reset and continue as if it succeeded.

**Acceptance / risk:** test two independently updated snapshots, including a friend rebuild racing owner/routine work. Entry conflict rules need explicit precedence. Removing global locks before shared writes are safe increases the risk.

### A02 — Preserve queued requests and keep publishing serialization short

**Evidence:** [rebuild-profile.yml](../.github/workflows/rebuild-profile.yml), baseline line 31, and four other workflows share workflow-level `group: pages`. The lock includes model stages with 8-minute editor and 10-minute voice timeouts. Default GitHub concurrency replaces an existing pending run when another arrives; `cancel-in-progress: false` protects the running run, not every pending request.

**Proposal:** where supported by the target GitHub version, consider `queue: max` as an initial safeguard, understanding its 100-pending-run limit. Then separate per-profile processing, a coordinated shared writer, and a short deployment-only lock. Publish fresh main. Preserve the existing newest-main checkout behavior, and review rebuild/refresh steps that omit explicit `ref: main`.

**Acceptance / risk:** different users' requests must receive a result or explicit failure, rather than disappear before creating a receipt. Per-profile locks alone do not protect shared files or main-branch writes; resolve A01 first. Verify the target platform's current [concurrency contract](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).

### A03 — Delete the two old digest-staging implementations

**Evidence:** [build-profiles.yml](../.github/workflows/build-profiles.yml), baseline lines 88–109, and [spotify-sync.yml](../.github/workflows/spotify-sync.yml), baseline lines 76–96, contain shell staging implementations instead of calling [stage_digests.py](../scripts/stage_digests.py). Other publishing workflows already use the tested script.

The old blocks omit dated archive files and history indexes. A temporary-directory comparison confirmed the canonical script creates root and 17 profile `index.json` files absent from the shell output. The owner's latest digest copy existed at audit time; this is not a claim of a then-current owner-latest 404.

**Proposal / acceptance:** replace both blocks with `python3 scripts/stage_digests.py`; retain one staging policy. Compare the staged latest, history/index, weekend, and owner/friend paths. Low implementation risk; existing script tests should protect behavior.

### A04 — Recover from concurrent reaction-write conflicts

**Evidence:** [concierge-worker.js](../backend/concierge-worker.js), `handleReact` at baseline lines 1659–1665, reads/folds/writes the shared reactions file without conflict recovery. `ghPutFile` at line 800 discards HTTP error status. An offline mocked-GitHub test of simultaneous stars produced one success and one 502 after a 409 conflict.

**Proposal:** preserve status and use bounded re-read/re-fold retries with backoff/jitter for conflicts. Recompute the fold against the fresh SHA; repeating the stale PUT will not help. Do not retry authentication failures unchanged. Later batching or serialization is optional, not required for the first fix.

**Acceptance:** simultaneous valid reactions must survive; idempotent repeats remain no-ops; exhausted retries return a truthful failure. The audit made no remote writes.

### A05 — Anchor Spotify's background rebuild dispatch

**Evidence:** [concierge-worker.js](../backend/concierge-worker.js), Spotify callback at baseline line 1276, calls `dispatchSync` and returns immediately without awaiting it or registering `ctx.waitUntil`. Chat already anchors detached work elsewhere.

**Proposal:** pass request context into Spotify handling and use `ctx.waitUntil`, or await dispatch and handle its status accurately. This was a static runtime-lifetime risk, not a deployed failure reproduction. Verify the response lifecycle and failure handling with a delayed dispatch mock.

## Performance enhancements

### A06 — Store each series summary once

**Evidence:** [build_dashboard.py](../scripts/build_dashboard.py), baseline lines 721–728, attaches the entire run summary to every series member. There were **943 member summaries for 214 unique series**. Summary values occupied **1,736,491 compact bytes**, versus **165,772 bytes** stored once.

**Measured proposal:** a top-level map keyed by `series_key` reduced a compact full feed from about **6.20 MB to 4.63 MB**, approximately **25% raw and 10% gzip**. Resolve references in the dashboard parser ([index.html](../dashboard/index.html), baseline line 1551). Parsing/allocation benefits were not benchmarked in a browser.

**Acceptance / risk:** keep every night's links, venues, sold-out flags, and the summary for whichever member survives a date filter. Update consumers together and accept the old shape during rollout if needed. Minifying generated JSON offers an additional raw-size reduction, but must be weighed against readable diffs and should not be confused with gzip savings.

### A07 — Ship a slim boot feed, then consider shared factual data

**Evidence:** [index.html](../dashboard/index.html), `loadFeedFor` at baseline line 1665, fetches/parses all events before useful event content. All front-page windows together referenced only **276 of 3,559 event keys**. Keeping those rows plus every top-level metadata/config/dining/artist-links field yielded about **730 KB compact /193 KB gzip**, approximately **81% less gzip** than the equivalently compact full feed. [ROADMAP.md](../ROADMAP.md), baseline line 587, already prioritizes this work.

**Proposal:** first emit the existing server-derived `front_page` and its referenced rows as a boot feed; load the complete catalog for Explore, broad search, calendar selection, or missing deep links. Then consider a versioned shared factual catalog with smaller per-profile overlays for scores, reasons, verdicts, personalized lanes, and series representatives. Titles, dates, venues, links, tags, and series were identical across all 18 feeds at the audited snapshot.

**Acceptance / risk:** global counts, search, and exports must not silently use the partial dataset. Keep the single server selection policy. Taste-voiced enrichment belongs in a profile layer even when today's values happen to match. Boot loading is a medium-sized change; a catalog/overlay split is a separate, larger design decision.

### A08 — Rebuild and sync only affected profiles; preserve music on transient failure

**Evidence:** [build-profiles.yml](../.github/workflows/build-profiles.yml), baseline line 68, and [spotify-sync.yml](../.github/workflows/spotify-sync.yml), baseline line 59, sync/rebuild the fleet for individual changes. Even the step called "Sync this profile" in [rebuild-profile.yml](../.github/workflows/rebuild-profile.yml), baseline line 88, syncs everyone. Existing flags support targeting: `build_profiles.py --only-hash` and `sync_profiles_spotify.py --only`. The Spotify callback sends a profile hash the workflow ignores.

**Proposal:** target the requested hash for Spotify connections and user rebuilds; map changed taste/feedback files to profiles. Reserve fleet builds for nightly, registry/catalog changes, and shared policy updates. Reuse common loaded inputs across profile builds. Avoid rebuilding default and owner scoring separately from identical root inputs, and inject profile metadata before serializing rather than reopening every large output.

**Reliability caveat:** the sync script says failures preserve the previous music layer, but its affinity artifacts are transient. [feedback.py](../scripts/lib/feedback.py), `merged_affinity` at baseline lines 193–202, returns no Spotify layer if the artifact is absent; the following rebuild can then score taste-only. Preserve the prior feed or defer that profile's rebuild on transient sync failure. Distinguish a failure from a genuine missing/disconnected Spotify account.

**Acceptance / risk:** verify owner/root routing, individual Spotify and feedback inputs, keep-last teaser behavior, and unchanged unrelated feeds. One original root build with editor pool took **2.155 s**; a whole-fleet speedup was not measured.

### A09 — Score once and derive candidate, editor, and blurb windows

**Evidence:** [run_digest.py](../scripts/run_digest.py), baseline lines 339, 359, and 384, scores the catalog three times. [pipeline.py](../scripts/lib/pipeline.py), `score_pool` at baseline lines 667–675, scores an event before rejecting it by date. Each pass scored 3,559 rows even when the 28-day result contained only 1,851.

**Measured proposal:** three equivalent passes for all/28/35-day windows took **2.504 s**; one complete scoring pass followed by the same date selections took **0.780 s**, with exact list/dict equality: **69% less time in that scoring stage**, not the entire pipeline.

Prepare normalized tracked/loved names, ambiguity sets, merged genres, configuration, and thresholds once per profile/build. The original profile showed **336,422 name-normalization calls** in one scoring pass. A bounded in-memory cache (`maxsize=8192`) around the pure name normalizer cut the three-pass experiment to **1.447 s**, also preserving outputs, with **1,005,755 hits /3,511 misses**. This is an alternative/secondary optimization; do not add its percentage to score-once savings.

**Acceptance / risk:** preserve selection policies, ordering, inclusive end dates, reasons, and configuration precedence. Derive separate views where callers stamp reactions or mutate rows; do not accidentally share mutable state. Invalidate prepared data when profile, affinity, or enrichment changes.

### A10 — Reduce fuzzy-dedupe work with conservative indexes

**Evidence:** [dedupe.py](../scripts/lib/dedupe.py), `dedupe` at baseline line 462, took **6.393 s** uninstrumented on the already-deduped 3,618-row catalog, finding zero merges. Separate profiling counted **112,427 pair checks**, **136,060 SequenceMatcher ratios**, and **1,255,194 normalization calls**. Date buckets already avoid a naive all-catalog quadratic loop, but dense dates still incur extensive pair work.

**Proposal:** cache pure normalized strings and venue comparisons; prepare title/venue/headliner/link features per row; resolve exact identities early; narrow fuzzy candidates conservatively; reuse repeated title-similarity calculations. Consider incremental dedupe only after proving candidate selection preserves equivalence cases.

**Acceptance / risk:** retain TBA/secret-venue, festival, companion, shared venue-page, headliner, cross-source, film-showtime, and rich-link rules. Never disable dedupe merely because one baseline input produced zero merges. This has more correctness risk than score reuse; require regression fixtures and catalog comparisons.

### A11 — Overlap independent source fetching with bounded concurrency

**Evidence:** [run_digest.py](../scripts/run_digest.py), `fetch_all` at baseline lines 126–141, invokes each fetcher synchronously, although architecture documents describe parallel fetching. There were 12 configured fetchers. Their serial timeout ceilings summed to **1,520 s (25m20s)**; this is a ceiling, not measured typical runtime. Spotify sync is also sequential with a 60-second request timeout.

**Proposal:** start with a small pool, e.g. 3–4 independent fetchers, retain per-host pacing and TM/RA limits, collect individual errors, and merge results in configured source order. Targeting Spotify profiles takes priority over parallelizing unnecessary fleet work.

**Acceptance / risk:** one failed source must still degrade gracefully. Keep deterministic merge order and aggregate host limits. Live end-to-end speedups were not measured.

### A12 — Make Worker retrieval compact, relevant, and bounded

**Evidence:** [concierge-worker.js](../backend/concierge-worker.js), `groupFeedMatrix` at baseline lines 1162–1173, re-fetches the caller feed after chat already loaded it, fetches friends sequentially, and retains full parsed feeds to return only 40 compact rows. Each feed was about 8.96 MB raw, and group input had no runtime size bound. Production heap impact was not measured.

**Grounding defect:** `buildSystem` at baseline lines 730–739 sorts by date and keeps the first 220 events. With a frozen Oct 7 local date, the **64,375-character** prompt ended **Friday Oct 9**, omitting Saturday/Sunday despite the weekend-planning contract. Raising the cap alone would increase cost without fixing relevance.

**Proposal:** reuse the loaded caller feed; deduplicate/limit names; fetch compact profile projections with bounded concurrency; retrieve relevant events by requested dates, type, or artist. A read-only search tool can preserve candidate coverage beyond prompt limits. Keep stable persona/profile context cacheable separately from changing events.

**Further redundancy:** resolve profile once per self-edit request and reuse fetched YAML. A friend taste+mechanism change required eight sequential GitHub requests and two commits/build triggers at audit time. Fetch independent inputs together; consider one atomic multi-file commit only after read reuse is sound. Group events by canonical `key` rather than `_normTok`/`_evId`, which duplicate an identity already present on every current feed row.

**Acceptance / risk:** validate weekend and distant-date questions and retain personalized verdicts. Use canonical keys with an old-feed fallback only if that compatibility is actually required. Compact retrieval is a medium change; request-local reuse and bounds are smaller steps.

### A13 — Page Explore results and cache derived data

**Evidence:** [index.html](../dashboard/index.html), baseline line 4186, builds up to **1,200 card objects** per render and recomputes facets around line 4240. Search at line 2334 and job-clock updates at line 2952 update the whole component. A warmed harness using the actual component/feed measured Explore calculations at **18.61 ms median /23.40 ms p95**, excluding browser rendering/layout.

**Proposal:** paginate or virtualize rows; prepare searchable text and facet vocabularies on feed changes; memoize filtered/sorted rows; isolate elapsed-time updates. Paging may capture the benefit with less complexity than virtualization.

**Acceptance / risk:** preserve counts, sort/filter behavior, expanded cards, focus, and accessibility. Measure actual browser interaction before claiming user-visible latency improvements.

### A14 — Repair personalized and offline feed caching

**Evidence:** [sw.js](../dashboard/sw.js), baseline line 39, caches default `/data.json` but never stores personalized feed responses. [index.html](../dashboard/index.html), `loadMeta` at baseline line 1649, loses the version offline, then requests a bare feed URL that misses the previously cached `?v=` URL. Executing the actual worker with mocked networking reproduced both misses; writes also are detached from the fetch event's lifetime.

**Proposal / acceptance:** recognize default and profile feed paths; retain a last successful feed/version fallback; bound stored versions; anchor cache writes with `event.waitUntil`; prevent failed responses from overwriting good entries. Test an online load followed by offline restart for default and personalized feeds. Keep profile boundaries and honest freshness indicators.

### A15 — Implement the advertised price edge cache

**Evidence:** [concierge-worker.js](../backend/concierge-worker.js), `handlePrices` at baseline lines 1593–1606, promises a five-minute edge cache but provides no application cache for the upstream request. Returning `Cache-Control` alone does not establish edge caching of Worker-generated responses. Two mocked identical requests fetched upstream twice; actual production upstream/CDN caching was not inspected.

**Proposal / acceptance:** cache successful normalized results under canonical query keys with accurate checked-at timestamps; do not cache upstream failures. Verify cache hits, expiration, and CORS behavior without conflating browser caching with Worker edge caching.

## Correctness and cleanup proposals

### A16 — Use one LA date helper across chat and group planning

**Evidence:** [concierge-worker.js](../backend/concierge-worker.js), `buildSystem` at baseline line 627 and group planning at line 1157, uses UTC `toISOString()` dates labeled as LA. The calendar route already uses a correctly zoned `Intl.DateTimeFormat` at line 1798.

**Reproduction:** frozen `2026-10-08T02:00Z` is Oct 7, 7 p.m. LA. The system prompt says Oct 8 and excludes an Oct 7 show.

**Proposal / acceptance:** share the zoned date helper for local-day decisions. Test UTC/LA midnight boundaries and daylight-saving changes. Keep timestamps representing instants in UTC; changing local-day filtering does not mean converting all audit timestamps to date-only LA values.

### A17 — Replace duplicate per-event ICS helpers with shared primitives

**Evidence:** [index.html](../dashboard/index.html), baseline lines 1692–1730, implements older escaping/folding/time logic. [calendar-core.js](../dashboard/calendar-core.js), baseline lines 298–319, already provides tested UTF-8 octet folding and broader time parsing, and explicitly notes the old export's character-count divergence. [lib/ics.py](../scripts/lib/ics.py) is the Python counterpart.

**Proposal / acceptance:** reuse the JavaScript calendar primitives through a small single-event adapter, preserving one-event semantics, stable identifiers, time zones, and intended durations. Test non-ASCII titles, all-day events, time ranges, and midnight rollover. Cross-language implementations may remain necessary; share conformance cases instead of trying to delete a required runtime implementation.

### A18 — Make the frontend runtime reproducible before pruning it

**Evidence:** [support.js](../dashboard/support.js), baseline line 158, fetches the full 385 KB HTML again, parses it at line 45, and compiles the template around line 1624. It is described as generated from `dc-runtime`, but the generator was absent from the repository.

**Proposal:** pin/vendor the generator or establish a reproducible build, compile once for production, and consider excluding unused design-editor/JSX-import scaffolding from that artifact while preserving design-tool workflows separately.

**Risk:** do not just delete the second fetch or hand-prune generated output. Raw table/template encoding around line 372 protects against browser DOM normalization; the already-parsed DOM is not an equivalent input. This is a conditional optimization, lower priority than feed size.

### A19 — Remove only verified obsolete material; update stale instructions

| Candidate | Original audit evidence | Proposed action / caveat |
| --- | --- | --- |
| [events_eventbrite.json](../events_eventbrite.json) | Generated scratch output, 45 rows dated Jul 17–Sep 6; no runtime reader found | Remove/archive after checking current and external use; route CLI scratch output to an ignored location. It is not the canonical catalog. |
| [filter-popup-preview.html](../filter-popup-preview.html) | Standalone design prototype with no app references found | Remove if design review no longer uses it, otherwise move to an explicit prototype/archive directory. Manual use was unknown. |
| [scripts/_layer_merge.py](../scripts/_layer_merge.py) | No repository call sites found; module-level catalog writes and a follow-up `run_digest --no-fetch` required | Not proven dead. It remains useful for manual layering; consider a supported incoming-JSON ingestion path before removing it, and check external routines. |
| [ROADMAP.md](../ROADMAP.md) | Old pending-merge/~700-event/Babel descriptions conflict with newer entries | Update current guidance; preserve historical decisions as history. |
| [README.md](../README.md) and [dashboard/README.md](../dashboard/README.md) | Direct-to-main routine description and streaming-as-future claim are stale | Describe actual routine landing and implemented streaming. |
| [docs/PIPELINE.md](PIPELINE.md) | Single-feed trigger descriptions conflict with fleet rebuilds; about 13-minute receipt promise conflicts with 8+10-minute model bounds before queue/setup/deploy | Correct operational claims; distinguish timeouts from typical latency. |
| [routines/profile-digest-prompt.md](../routines/profile-digest-prompt.md) | Assigns digest work after declaring the workflow owns it; promises nightly backlog handling although unchanged friends are gated out | Remove contradictory ownership/backlog promises after confirming the desired current behavior. |

**Retain:** `rebuilt.*.json` files are actively polled completion receipts, not stale builds. React/ReactDOM and `calendar-core.js` are active dependencies. Legacy JSON chat responses share the current pipeline and support older clients. The vendored Babel bundle was already removed. `fetch_ics.py`, `fetch_squarespace.py`, and `fetch_jsonld.py` are explicitly used by the operating skill for manual source layering. `eval_verdict_shadow.py` is documented audit tooling. Legacy enrichment records still use compatibility defaults. Missing CI references do not prove obsolescence.

### A20 — Automatically run the existing regression suites

**Evidence:** none of the six baseline workflows ran the existing Python/backend tests; they built, deployed, or landed state.

**Proposal:** add relevant PR/push validation using existing suites and canonical digest-staging checks. Baseline commands were `python -m pytest scripts/tests -q` from the root and `npm test` from `backend` after dependency installation. These commands were verified in the original audit, not rerun when saving this record.

**Acceptance / risk:** confirm actual tests execute, preserve failing exit codes, and add behavioral regressions for the changed paths. Do not substitute trivial passing checks or disable assertions to achieve a green run.

## Suggested implementation sequence

1. Small reliability/cleanup change: canonical staging (A03), zoned date helper (A16), anchored Spotify dispatch (A05), conflict recovery (A04), and existing test automation (A20). These may be separate focused commits.
2. Shared-state safety: delta merging (A01), preserving queued requests (A02), and truthful handling of failed syncs (A08). Keep coordination intact while changing locks.
3. Measured computation: score reuse/prepared inputs (A09), targeted profile builds (A08), and shared loaded inputs. Compare actual candidate/editor/blurb outputs and owner routing.
4. Payload: normalize series (A06), then boot/full-feed loading (A07) with offline fallback (A14). Measure downloaded bytes, useful-content timing, parse time, and memory in a browser.
5. Follow-up after measurements: dedupe indexing (A10), bounded source/group concurrency (A11/A12), Explore paging (A13), price caching (A15), shared calendar primitives (A17), reproducible frontend generation (A18), and artifact/doc cleanup (A19).

This sequence recommends scope, not authorization. The owner can select a smaller or different item. A new database or wholesale frontend rewrite is not required to capture the measured wins.

## Decision and validation log

| Revision / date | Author | Items | Decision / evidence / follow-up |
| --- | --- | --- | --- |
| Original audit, 2026-10-07, `6c61c4d` | Codex | All | Read-only review and historical checks summarized above; proposals only. |
| Record added on checkout `34c38dc` | Codex, at owner's request | All | Restored findings into this shared repository document; added discovery pointers for both agents. No findings revalidated against this later revision and no application changes implemented. |
