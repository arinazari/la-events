#!/usr/bin/env python3
"""Append a validated reaction to data/feedback.jsonl (the Phase C feedback loop).

The concierge (or the digest) calls this when Ari reacts to something — "loved Antal",
"more deep house", "never show this bro DJ". Reactions fold into the music-affinity layer
(lib/feedback.py -> lib/affinity.py) automatically on the next run; they do NOT edit
taste.yaml. taste.yaml is the explicit human spine — edit it directly for durable/structural
prefs (track an artist for good, ban a venue, "no comedy"). The feedback loop consumes only
artists + genres, so venue/category rules belong in taste.yaml, not here.

Schema (one JSON object per line), matching lib/feedback.py:
  {"ts": "YYYY-MM-DD", "kind": <kind>, "artists": [...], "genres": [...], "note": "..."}
kinds: loved / went (explicit +), skipped (soft -), hide (hard "never show"),
       clicked_ticket / added_calendar (implicit +, usually from delivery surfaces).

Examples:
  python scripts/log_feedback.py --kind loved --artists "Antal, Peggy Gou" --note "rooftop set was perfect"
  python scripts/log_feedback.py --kind loved --genres "deep house, disco"
  python scripts/log_feedback.py --kind hide  --artists "Some Bro DJ"
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ on path
from lib.pipeline import today_la  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
KINDS = {"loved", "went", "skipped", "hide", "clicked_ticket", "added_calendar"}


def _split(s: str) -> list:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def build_record(kind: str, artists=None, genres=None, note: str = "", ts: str = None) -> dict:
    """Validate + assemble one reaction record. Raises ValueError on a bad kind or empty target."""
    kind = (kind or "").strip().lower()
    if kind not in KINDS:
        raise ValueError(f"unknown kind '{kind}'; expected one of {sorted(KINDS)}")
    artists = [a.strip() for a in (artists or []) if a and a.strip()]
    genres = [g.strip() for g in (genres or []) if g and g.strip()]
    if not artists and not genres:
        raise ValueError("nothing to log: provide at least one artist or genre")
    rec = {"ts": ts or today_la().isoformat(), "kind": kind}
    if artists:
        rec["artists"] = artists
    if genres:
        rec["genres"] = genres
    if note and note.strip():
        rec["note"] = note.strip()
    return rec


def append_reaction(path, rec: dict) -> str:
    """Append a record as one JSONL line (creating the file/dirs, fixing a missing trailing
    newline first so lines never merge). Returns the line written."""
    p = Path(path)
    if not p.is_absolute():
        p = REPO / p
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(rec, ensure_ascii=False)
    prefix = ""
    if p.exists() and p.stat().st_size > 0 and not p.read_text().endswith("\n"):
        prefix = "\n"
    with p.open("a") as f:
        f.write(prefix + line + "\n")
    return line


def main() -> int:
    ap = argparse.ArgumentParser(description="Append a reaction to data/feedback.jsonl.")
    ap.add_argument("--kind", required=True, help="loved|went|skipped|hide|clicked_ticket|added_calendar")
    ap.add_argument("--artists", default="", help="comma-separated artist names")
    ap.add_argument("--genres", default="", help="comma-separated genres")
    ap.add_argument("--note", default="", help="optional free-text note")
    ap.add_argument("--ts", default=None, help="ISO date (default: today, LA)")
    ap.add_argument("--path", default="data/feedback.jsonl")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        rec = build_record(args.kind, _split(args.artists), _split(args.genres), args.note, args.ts)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.dry_run:
        print("(dry-run) would append:", json.dumps(rec, ensure_ascii=False))
        return 0
    line = append_reaction(args.path, rec)
    print("logged:", line)
    print("→ folds into scoring on the next run (run_digest / build_dashboard).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
