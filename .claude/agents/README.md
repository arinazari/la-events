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

`source-scout` and `night-planner` sit **outside** that loop — invoked when Ari asks (typically
via the **concierge**, the natural-language front door — see `.claude/skills/concierge/SKILL.md`),
not on a schedule.

## Notes
- **Least privilege:** `scene-researcher` can write (the enrichment cache); `source-scout` is
  read-only and proposes (never edits the registry). `night-planner` has `Bash` so it can run
  `scripts/travel.py` (travel times) and `scripts/run_digest.py --no-fetch` (rescore) — both
  compute-only; it never writes the durable state (`catalog.json`, `dining.json`, `sources.yaml`,
  the taste files), only the gitignored `data/candidates.json` the rescore emits.
- **The enrichment cache is the moat-lite:** keyed by event-id + normalized artist name, it turns
  the nightly fan-out into an accumulating LA scene knowledge base — recurring artists are
  researched once.
- **Model:** unset → inherits the parent run's model. `scene-researcher` is the one candidate for
  a cheaper model if the nightly fan-out ever needs cost control; quality of its annotations is
  the brand, so keep it sharp until proven otherwise.
- **Status:** `night-planner` is wired and operational (Phase D) — it runs the travel engine +
  offline rescore and reads both catalogs. `scene-researcher` is still a draft of the Phase-B
  enrichment shape (wiring it into `run_digest.py` + the daily routine is Phase B). `source-scout`
  is invoked on demand by Discover mode.
