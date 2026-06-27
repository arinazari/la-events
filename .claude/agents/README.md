# .claude/agents — the worker agents

Subagents the la-events / la-dining **skills** (the orchestrators) and the **routines** spawn to
do the parallelizable, context-heavy work. The principle (see ROADMAP "Execution architecture"):
mechanical work in Python, taste/curation/prose in Claude, and **fan the parallel Claude work out
to these workers** so the main run stays fast and its context doesn't bloat.

| Agent | Tier / when | Spawned by | Returns |
|---|---|---|---|
| `scene-researcher` | Tier 1 — every digest run, **in parallel** over the top ~100 full head (one per batch) | la-events skill / daily routine | structured enrichment JSON (tags, artist notes, curator note, description) → enrichment cache (`enriched_tier: full`) |
| `blurb-writer` | Tier 2 (cheap) — every digest run, **in parallel** over the blurb pool below the head (one per batch) | la-events skill / daily routine | one-line `{id, description}` per event, no web/artist research → enrichment cache (`enriched_tier: blurb`; upgrades to full if it climbs into the head) |
| `source-scout` | On demand only | la-events Discover mode / Ari | a vetted **proposal** table (+ ready-to-paste `sources.yaml` snippets); never commits |
| `night-planner` | On demand | concierge / Ari | a timed dinner → show → afters itinerary with booking links |

## How a digest run uses them (the flow)

```
run_digest.py (Tier 0, no LLM)         ← fetch → normalize → dedupe → expire → score
        │  ranked, deduped candidate set
        ▼
scene-researcher ×N  (Tier 1, parallel) ← full-enrich the top ~100 head; read+update the cache
blurb-writer ×N      (Tier 2 cheap, ∥)   ← one-line descriptions for the band below the head
        │  enriched records (cache: full + blurb tiers)
        ▼
main agent (Tier 2, one creative step) ← write the digest in the single "LA insider" voice,
                                          render the canonical Markdown agenda (.md)
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
- **Model (cost tier):** `event-editor` and `scene-researcher` are pinned to **`sonnet`** — bounded,
  structured-output judgment/enrichment that doesn't need the parent's (Opus) tier every night, and
  the per-call work is already delta-gated (only new/changed events are judged or enriched).
  `blurb-writer` is pinned a tier lower to **`haiku`** with no web tools — it only writes one
  factual line from fields it's handed, so it's the cheapest of the three and runs over the widest
  band (the events below the full head). Escalate
  to Opus only **when it matters**, never by default: the orchestrator may spawn the editor with a
  `model: opus` override for a tier-boundary or genuinely ambiguous batch, and the per-user rebuild
  (`rebuild-profile.yml`) takes a `model` input (default Sonnet) so an owner can request an Opus pass.
  A bring-your-own-key concierge caller can run the **live chat** on Opus on their own spend (the
  Worker honors a per-request `model` override for BYOK). Keep annotation quality the bar: if a
  Sonnet gloss ever reads thin, bump `scene-researcher` back up.
- **Status:** `night-planner` is wired and operational (Phase D) — it runs the travel engine +
  offline rescore and reads both catalogs. `scene-researcher` is still a draft of the Phase-B
  enrichment shape (wiring it into `run_digest.py` + the daily routine is Phase B). `source-scout`
  is invoked on demand by Discover mode.
