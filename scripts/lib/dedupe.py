"""Fuzzy event dedupe — extracted so it's testable instead of done by hand.

The same real-world event shows up on RA + DICE + Ticketmaster + a venue site.
Merge rule (from SKILL.md): **same date + fuzzy-same venue + similar title/headliner**.
On merge, keep ALL ticket links and the richest description. Crucially, same
venue + same date is NOT enough (three different World Cup parties run at one bar
the same night) — title or headliner similarity is required.

dedupe(events) -> (merged_events, merge_report)
is_duplicate(a, b) -> bool          # the pairwise predicate (unit-tested)
merge(a, b) -> dict                 # combine two duplicate records
"""

import re
from difflib import SequenceMatcher

from .scoring import parse_event_date

_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")
# Filler dropped when comparing venues/titles.
_VENUE_NOISE = re.compile(r"\b(the|los angeles|la|dtla|presents|at)\b")


def normalize(s: str) -> str:
    """Lowercase, drop punctuation/filler, collapse whitespace."""
    s = (s or "").lower().replace("&", "and")
    s = _PUNCT.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    return s


def _venue_key(v: str) -> str:
    return _WS.sub(" ", _VENUE_NOISE.sub(" ", normalize(v))).strip()


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _contains(a: str, b: str) -> bool:
    """One string contains the other (guarded against trivial short matches)."""
    if not a or not b:
        return False
    short, long = sorted((a, b), key=len)
    return len(short) >= 4 and short in long


def _headliner(ev: dict) -> str:
    lineup = ev.get("lineup") or []
    if isinstance(lineup, list) and lineup:
        return normalize(str(lineup[0]))
    return ""


def _venue_match(a: dict, b: dict) -> bool:
    va, vb = _venue_key(a.get("venue", "")), _venue_key(b.get("venue", ""))
    if not va or not vb:
        return False
    return va == vb or _ratio(va, vb) >= 0.85 or _contains(va, vb)


def _title_or_headliner_match(a: dict, b: dict) -> bool:
    ta, tb = normalize(a.get("title", "")), normalize(b.get("title", ""))
    if _ratio(ta, tb) >= 0.80 or _contains(ta, tb):
        return True
    ha, hb = _headliner(a), _headliner(b)
    if ha and hb and (ha == hb or _ratio(ha, hb) >= 0.9):
        return True
    # A shared headliner that shows up in the other's title (lineup vs title-billed).
    if ha and ha in tb:
        return True
    if hb and hb in ta:
        return True
    return False


def is_duplicate(a: dict, b: dict) -> bool:
    """Two records describe the same real-world event."""
    da, db = parse_event_date(a), parse_event_date(b)
    if da is None or db is None or da != db:
        return False  # conservative: no date match, no merge
    return _venue_match(a, b) and _title_or_headliner_match(a, b)


def _merge_links(a, b):
    seen, out = set(), []
    for link in (a.get("links") or []) + (b.get("links") or []):
        url = link.get("url") if isinstance(link, dict) else link
        if url and url not in seen:
            seen.add(url)
            out.append(link)
    return out


def _union(a, b):
    out = list(a or [])
    for x in (b or []):
        if x not in out:
            out.append(x)
    return out


def _richest(*vals):
    """Longest non-empty string among vals (None if all empty)."""
    best = None
    for v in vals:
        if v and (best is None or len(str(v)) > len(str(best))):
            best = v
    return best


def merge(a: dict, b: dict) -> dict:
    """Combine two duplicate records — keep all links + the richest fields."""
    out = dict(a)
    out["links"] = _merge_links(a, b)
    out["sources"] = _union(a.get("sources"), b.get("sources"))
    out["lineup"] = a.get("lineup") if len(a.get("lineup") or []) >= len(b.get("lineup") or []) else b.get("lineup")
    out["detail"] = _richest(a.get("detail"), b.get("detail"))
    out["title"] = _richest(a.get("title"), b.get("title")) or a.get("title")
    out["organizers"] = _richest(a.get("organizers"), b.get("organizers"))
    out["price"] = a.get("price") or b.get("price")
    out["neighborhood"] = a.get("neighborhood") or b.get("neighborhood")
    out["genre"] = a.get("genre") or b.get("genre")  # sparse (only some sources classify); don't lose it if the base lacks one
    out["ra_pick"] = bool(a.get("ra_pick") or b.get("ra_pick"))
    out["afterhours"] = bool(a.get("afterhours") or b.get("afterhours"))
    fs = [x for x in (a.get("first_seen"), b.get("first_seen")) if x]
    ls = [x for x in (a.get("last_seen"), b.get("last_seen")) if x]
    if fs:
        out["first_seen"] = min(fs)
    if ls:
        out["last_seen"] = max(ls)
    return out


def dedupe(events: list) -> tuple:
    """Collapse duplicate records. Returns (merged_events, merge_report).

    Buckets by date so comparison is ~O(n) in practice, then greedily clusters
    within each day. merge_report is a list of (kept_title, absorbed_title).
    """
    merged, report = [], []
    by_date = {}
    for ev in events:
        d = parse_event_date(ev)
        by_date.setdefault(d.isoformat() if d else None, []).append(ev)

    for _, bucket in by_date.items():
        kept = []
        for ev in bucket:
            for i, k in enumerate(kept):
                if is_duplicate(k, ev):
                    report.append((k.get("title"), ev.get("title")))
                    kept[i] = merge(k, ev)
                    break
            else:
                kept.append(ev)
        merged.extend(kept)

    return merged, report
