"""Merge Step-2 layered rows (webfetch venues / editorial / one-off JSON-LD) into catalog.json.
Run once per digest, then `run_digest.py --no-fetch` redoes expire/tag/score/candidates.

Usage: python scripts/_layer_merge.py rows.json [more.json ...]

Rows may be in catalog schema (`"sources": [...]`) or raw fetcher output (`"source": "x"`); every
row is normalized (so it carries `sources` — else it never counts toward source freshness — and a
ticket `url` becomes `links`), keeping any extra fields like `editorial_mentions`.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from lib import pipeline as P  # noqa: E402
from lib import catalog_meta as CM  # noqa: E402
from lib import dedupe as D  # noqa: E402

# Raw-fetcher spellings normalize_record folds into canonical fields — don't re-add them.
_RAW_ONLY = {"source", "url", "time", "name", "event_name", "venue_name", "artists", "artist"}


def normalize_rows(rows: list) -> list:
    out = []
    for r in rows:
        src = (r.get("sources") or [r.get("source") or "webfetch"])[0]
        n = P.normalize_record(r, src)   # url -> links, time -> start; keeps an explicit `sources`
        # ...but its fixed schema drops fields the pipeline still reads (editorial_mentions = the
        # scorer's +1 and the radar's editorial signal; status; end) — carry those through.
        n.update({k: v for k, v in r.items() if k not in n and k not in _RAW_ONLY})
        out.append(n)
    return [r for r in out if r.get("title") and r.get("date")]


def fold_mentions(catalog: list, incoming: list) -> tuple:
    """Editorial roundups are ranking signals, not catalog rows (CLAUDE.md): a mention of an event a
    structured source already carries goes onto that row as `editorial_mentions` only. Merging the
    row in would also add an "editorial" source, which the core never re-fetches. An editorial-only
    match (a market an earlier roundup wrote back) goes through merge_new as usual so its details and
    last_seen update. A roundup item with no real venue can't be placed — a title-only match could
    land the +1 on the wrong event. Returns (remaining incoming, folded, unplaced)."""
    folded, unplaced, rest = 0, 0, []
    for r in incoming:
        if r.get("editorial_mentions") and set(r.get("sources") or []) <= {"editorial"}:
            if D._is_placeholder_venue(r.get("venue")):
                unplaced += 1
                continue
            # A TBA/placeholder-venue catalog row matches anything with a similar title — not a
            # place to hang a venue-specific mention.
            hits = [e for e in catalog if D.is_duplicate(e, r) and set(e.get("sources") or []) - {"editorial"}
                    and not D._is_placeholder_venue(e.get("venue"))]
            if hits:   # >1 = unmerged duplicates of the same event at this venue — mention each
                for hit in hits:
                    hit["editorial_mentions"] = D.merge_mentions(hit.get("editorial_mentions"),
                                                                 r["editorial_mentions"])
                folded += 1
                continue
        rest.append(r)
    return rest, folded, unplaced


def count_layered_changes(meta_path: Path, delta: dict, today) -> None:
    """Fold this layering pass's {added, updated, changes} into today's change summary. The
    `run_digest --no-fetch` that follows diffs against this already-layered catalog, so otherwise
    layered rows would never read as new/updated (and the next day's fetch sees them as pre-existing)."""
    meta = CM.read_meta(meta_path)
    try:
        same_day = datetime.fromisoformat(meta["fetched_at"]).astimezone(P._LA).date() == today
    except (KeyError, TypeError, ValueError):
        same_day = False
    if same_day and (delta.get("added") or delta.get("updated")):
        meta["added"] = int(meta.get("added") or 0) + int(delta.get("added") or 0)
        meta["updated"] = int(meta.get("updated") or 0) + int(delta.get("updated") or 0)
        meta["changes"] = (list(delta.get("changes") or []) + list(meta.get("changes") or []))[:25]
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def main(paths: list) -> int:
    cat_path = REPO / "data" / "catalog.json"
    catalog = json.loads(cat_path.read_text())
    today = P.today_la()
    rows = []
    for fname in paths:
        p = Path(fname)
        if not p.is_file():
            continue
        doc = json.loads(p.read_text())
        rows.extend(doc.get("events", []) if isinstance(doc, dict) else doc)
    incoming = normalize_rows(rows)
    print(f"layering {len(incoming)} incoming records from {len(paths)} files")
    old_index = P.content_index(catalog)   # before folding/merging: what this pass adds or moves
    incoming, folded, unplaced = fold_mentions(catalog, incoming)
    if folded or unplaced:
        print(f"  {folded} editorial mention(s) folded onto existing rows; {unplaced} skipped (no venue)")
    catalog, stats = P.merge_new(catalog, incoming, today)
    delta = P.diff_catalog(old_index, catalog, today)   # also stamps updated_at/changed_fields
    cat_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")
    print("merge stats:", stats, f"| +{delta['added']} new, {delta['updated']} updated")
    count_layered_changes(cat_path.parent / "catalog_meta.json", delta, today)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
