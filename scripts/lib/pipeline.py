"""Deterministic pipeline transforms for run_digest.py — pure and testable.

The "map" half (per-source normalize) is intentionally thin; the "reduce" half
(merge → dedupe → expire → stamp → score → select) is the schema-locking core that
the enrichment (scene-researcher) and synthesis steps build on. Keep it side-effect
free: run_digest.py does the I/O, this module does the transforms.
"""

from datetime import date, datetime, timedelta

from .scoring import score_event, score_to_rating, parse_event_date
from .dedupe import dedupe

try:
    from zoneinfo import ZoneInfo
    _LA = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover - tzdata missing
    _LA = None

# Default category per source when a record doesn't carry one.
SOURCE_CATEGORY = {
    "ra": "electronic", "19hz": "electronic", "posh": "party",
    "ticketmaster": "music", "goldenvoice": "music", "dice": "live_music",
    "filmbot": "film", "vidiots": "film", "eventbrite": "general",
    "squarespace": "live_music", "ics": "general", "jsonld": "general",
}

# Per-source dict->dict pre-processors, populated as live fetcher shapes are confirmed
# (each can rename/reshape fields before the generic normalizer runs). Empty = generic only.
NORMALIZERS: dict = {}


def today_la() -> date:
    """Today's date in America/Los_Angeles (window math must be LA-local, not UTC)."""
    return datetime.now(_LA).date() if _LA else date.today()


def _as_list(x) -> list:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _split_datetime(raw: dict):
    """(date 'YYYY-MM-DD', start 'HH:MM') from a record's date/datetime/start fields."""
    d = parse_event_date(raw)
    date_str = d.isoformat() if d else (str(raw["date"])[:10] if raw.get("date") else None)
    start = raw.get("start") or raw.get("time")
    src = start if (start and "T" in str(start)) else raw.get("datetime")
    if (not start or "T" in str(start)) and src and "T" in str(src):
        try:
            start = datetime.fromisoformat(str(src).replace("Z", "+00:00")).strftime("%H:%M")
        except ValueError:
            pass
    return date_str, (start or None)


def _links(raw: dict, source) -> list:
    links = raw.get("links")
    if isinstance(links, list) and links and isinstance(links[0], dict):
        return links
    out = []
    for key in ("url", "ticket_url", "link", "event_url", "tickets"):
        v = raw.get(key)
        if isinstance(v, str) and v:
            out.append({"source": source or "?", "url": v})
    return out


def _price(raw: dict):
    """A price string. Prefer an explicit `price`; else synthesize from price_min/price_max
    (Ticketmaster emits the range, not a string). `$lo-hi`, `$lo`, "free", or None."""
    p = raw.get("price")
    if p not in (None, ""):
        return p
    lo, hi = raw.get("price_min"), raw.get("price_max")
    if lo in (None, "") and hi in (None, ""):
        return None
    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    nlo, nhi = num(lo), num(hi)
    if (nlo in (0.0, None)) and (nhi in (0.0, None)):
        return "free" if (nlo == 0.0 or nhi == 0.0) else None
    fmt = lambda v: f"{v:g}"
    if nlo and nhi and nlo != nhi:
        return f"${fmt(nlo)}-{fmt(nhi)}"
    v = nlo or nhi
    return f"${fmt(v)}"


def normalize_record(raw: dict, source=None) -> dict:
    """Best-effort map an arbitrary fetcher record onto the canonical catalog schema.

    Key order mirrors data/catalog.json to minimize churn when run_digest rewrites it.
    """
    if source in NORMALIZERS:
        raw = NORMALIZERS[source](dict(raw)) or raw
    date_str, start = _split_datetime(raw)
    lineup = [str(a) for a in _as_list(raw.get("lineup") or raw.get("artists") or raw.get("artist")) if a]
    return {
        "title": raw.get("title") or raw.get("name") or raw.get("event_name"),
        "date": date_str,
        "start": start,
        "venue": raw.get("venue") or raw.get("venue_name"),
        "neighborhood": raw.get("neighborhood"),
        "category": raw.get("category") or SOURCE_CATEGORY.get(source, "general"),
        "lineup": lineup,
        "links": _links(raw, source),
        "sources": _as_list(raw.get("sources") or source),
        "organizers": raw.get("organizers") or raw.get("organizer") or raw.get("promoter"),
        "detail": raw.get("detail") or raw.get("description") or raw.get("desc"),
        "price": _price(raw),
        "ra_pick": bool(raw.get("ra_pick")),
        "afterhours": bool(raw.get("afterhours") or raw.get("afterhours_flag")),
    }


def stamp_seen(records: list, today: date = None) -> list:
    """Ensure each record has first_seen (set once) and a refreshed last_seen."""
    t = (today or today_la()).isoformat()
    for r in records:
        r.setdefault("first_seen", t)
        r.setdefault("last_seen", t)
    return records


def merge_new(catalog: list, incoming: list, today: date = None) -> tuple:
    """Stamp incoming as seen-today, append, dedupe. Returns (catalog, stats).

    Catalog records come first so they're the merge base (preserve identity; absorb
    new ticket links). first_seen survives, last_seen advances (via dedupe.merge).
    """
    t = (today or today_la()).isoformat()
    for r in incoming:
        r["first_seen"] = r.get("first_seen") or t
        r["last_seen"] = t
    deduped, report = dedupe(list(catalog) + list(incoming))
    stats = {"incoming": len(incoming), "merged": len(report),
             "added": max(0, len(deduped) - len(catalog))}
    return deduped, stats


def expire_past(catalog: list, today: date = None) -> tuple:
    """Drop events dated before today (LA). Keep future + undated (TBA). Returns (kept, n)."""
    today = today or today_la()
    kept, expired = [], 0
    for ev in catalog:
        d = parse_event_date(ev)
        if d is not None and d < today:
            expired += 1
        else:
            kept.append(ev)
    return kept, expired


def score_view(ev: dict, taste: dict, profile: dict, affinity: dict = None) -> dict:
    """A scored copy of an event (catalog stays score-free; scores live in the candidate set)."""
    s = score_event(ev, taste, profile, affinity)
    d = parse_event_date(ev)
    out = dict(ev)
    out["score"] = s["score"]
    out["rating"] = score_to_rating(s["score"], profile)
    out["reasons"] = s["reasons"]
    out["iso_date"] = d.isoformat() if d else None
    return out


def select_candidates(catalog, taste, profile, today=None, window_days=None,
                      top_n=40, image_n=10, affinity=None) -> list:
    """The enrichment candidate set: upcoming events, best-first, top N.

    Flags the first `image_n` with image_wanted=True (the scene-researcher images contract).
    `affinity` (optional) layers the Spotify + feedback music profile into the scoring.
    """
    today = today or today_la()
    start = today.isoformat()
    end = (today + timedelta(days=window_days)).isoformat() if window_days is not None else None

    scored = []
    for ev in catalog:
        v = score_view(ev, taste, profile, affinity)
        if not v["iso_date"] or v["iso_date"] < start:
            continue
        if end and v["iso_date"] > end:
            continue
        scored.append(v)

    scored.sort(key=lambda e: (-e["score"], e["iso_date"]))
    top = scored[:top_n]
    for i, e in enumerate(top):
        e["image_wanted"] = i < image_n
    return top
