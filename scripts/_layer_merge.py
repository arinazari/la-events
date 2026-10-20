"""Merge Step-2 layered rows (webfetch venues / editorial / one-off JSON-LD) into catalog.json.
Run once per digest, then `run_digest.py --no-fetch` redoes expire/tag/score/candidates.

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
from lib import pipeline as P
from lib import catalog_meta as CM
from lib import dedupe as D

# Raw-fetcher spellings normalize_record folds into canonical fields — don't re-add them.
_RAW_ONLY = {"source", "url", "time", "name", "event_name", "venue_name", "artists", "artist"}

cat_path = REPO / "data" / "catalog.json"
catalog = json.loads(cat_path.read_text())
today = P.today_la()

incoming = []
for fname in sys.argv[1:]:
    p = Path(fname)
    if not p.exists():
        continue
    rows = json.loads(p.read_text())
    if isinstance(rows, dict):
        rows = rows.get("events", [])
    for r in rows:
        src = (r.get("sources") or [r.get("source") or "webfetch"])[0]
        n = P.normalize_record(r, src)   # url -> links, time -> start; keeps an explicit `sources`
        # ...but its fixed schema drops fields the pipeline still reads (editorial_mentions = the
        # scorer's +1 and the radar's editorial signal; status; end) — carry those through.
        n.update({k: v for k, v in r.items() if k not in n and k not in _RAW_ONLY})
        incoming.append(n)

incoming = [r for r in incoming if r.get("title") and r.get("date")]
print(f"layering {len(incoming)} incoming records from {len(sys.argv[1:])} files")

# Editorial roundups are ranking signals, not catalog rows (CLAUDE.md): a mention of an event the
# catalog already has goes onto that row as `editorial_mentions` only. Merging the row in would
# also add an "editorial" source, which the core never re-fetches — switching off ghost detection
# (cancelled/pulled shows → unlisted) for exactly the events the roundups push up the ranking.
mentioned, rest = 0, []
for r in incoming:
    if r.get("editorial_mentions") and set(r.get("sources") or []) <= {"editorial"}:
        hit = next((e for e in catalog if D.is_duplicate(e, r)), None)
        if hit is not None:
            hit["editorial_mentions"] = D.merge_mentions(hit.get("editorial_mentions"), r["editorial_mentions"])
            mentioned += 1
            continue
    rest.append(r)
incoming = rest
if mentioned:
    print(f"  {mentioned} editorial mention(s) folded onto existing rows")

catalog, stats = P.merge_new(catalog, incoming, today)
cat_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")
print("merge stats:", stats)

# Count the layered additions in today's change summary. The `run_digest --no-fetch` that follows
# diffs against this already-layered catalog, so otherwise they'd never read as "new" (and the
# next day's fetch sees them as pre-existing too).
meta_path = cat_path.parent / "catalog_meta.json"
meta = CM.read_meta(meta_path)
try:
    same_day = datetime.fromisoformat(meta["fetched_at"]).astimezone(P._LA).date() == today
except (KeyError, TypeError, ValueError):
    same_day = False
if stats.get("added") and same_day:
    meta["added"] = int(meta.get("added") or 0) + stats["added"]
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
