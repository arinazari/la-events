# .claude/agents — the worker agents

Subagents the la-events / la-dining **skills** (the orchestrators) and the **routines** spawn to
do the parallelizable, context-heavy work. The principle (see ROADMAP "Execution architecture"):
mechanical work in Python, taste/curation/prose in Claude, and **fan the parallel Claude work out
to these workers** so the main run stays fast and its context doesn't bloat.

| Agent | Tier / when | Spawned by | Returns |
|---|---|---|---|
| `scene-researcher` | Tier 1 — every digest run, **in parallel** over the top ~30–40 (one per batch) | la-events skill / daily routine | structured enrichment JSON (tags, artist notes, curator note, description, image) → written to the enrichment cache |
| `source-scout` | On demand only | la-events Discover mode / Ari | a vetted **proposal** table (+ ready-to-paste `sources.yaml` snippets); never commits |
| `night-planner` | On demand | concierge / Ari | a timed dinner → show → afters itinerary with booking links |

## How a digest run uses them (the flow)

```
run_digest.py (Tier 0, no LLM)         ← fetch → normalize → dedupe → expire → score
        │  ranked, deduped candidate set
        ▼
scene-researcher ×N  (Tier 1, parallel) ← enrich top ~30–40; read+update the enrichment cache
        │  enriched records (cache)
        ▼
main agent (Tier 2, one creative step) ← write the digest in the single "LA insider" voice,
                                          render .md (canonical) + HTML (top-10 images) → email
```

`source-scout` and `night-planner` sit **outside** that loop — invoked when Ari asks, not on a
schedule.

## Notes
- **Least privilege:** `scene-researcher` can write (the cache); `source-scout` and
  `night-planner` are read-only (scout proposes, it never edits the registry).
- **The enrichment cache is the moat-lite:** keyed by event-id + normalized artist name, it turns
  the nightly fan-out into an accumulating LA scene knowledge base — recurring artists are
  researched once.
- **Model:** unset → inherits the parent run's model. `scene-researcher` is the one candidate for
  a cheaper model if the nightly fan-out ever needs cost control; quality of its annotations is
  the brand, so keep it sharp until proven otherwise.
- These are drafts of the execution shape (ROADMAP Phase B/D). Wiring them into `run_digest.py`
  and the routines is the build step.
