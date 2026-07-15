"""Series / run consolidation — one CARD per program, at the ranking/presentation layer.

dedupe.py's contract is one record per (real-world event, night): a 15-night run of The
Odyssey at the Vista is *correctly* 15 catalog rows (each night is separately buyable and
separately sell-out-able). But every surface that ranks globally — the dashboard's final
rank, the chat picks, the digest's "Don't miss" — then shows the same program N times,
crowding out everything else. This module derives a stable `series_key` so those surfaces
collapse a run into ONE representative card that carries all its dates, without touching
the catalog or the dedupe contract.

Two grouping shapes:
  • film — the movie IS the program, the theater is a detail: group by CORE TITLE alone
    (cross-venue, cross-date), so "The Odyssey (70mm)" at the Vista and "The Odyssey 70MM"
    at the Egyptian are one card whose entries tease the venues/formats apart. Format and
    edition noise (70mm/35mm, 4K restoration, Q&A, anniversary, a year tag) is stripped to
    get the core title — but a double feature is its own program (both titles stay in the
    key), and two different films at one theater never group.
  • everything else — group by title+venue only (multi-night runs, weekly residencies):
    exactly the convention render_digest.collapse_runs has always used. An artist playing
    two venues is two bookings, never merged.

series_key(ev)          -> stable grouping key (None if the record has no usable title)
group_series(events)    -> {key: [events]} for keys with 2+ members, insertion-ordered
series_summary(members) -> the compact run descriptor carried by every member's card
showtimes_url(title)    -> external "all LA showtimes" search link (theaters we don't fetch)
"""

import re
from collections import OrderedDict
from urllib.parse import quote_plus

from .dedupe import normalize

# Format / edition / presentation noise that varies per screening of the SAME film.
# Applied AFTER dedupe.normalize, so patterns target normalized text ("Q&A" -> "qanda",
# "Q + A" -> "q a", apostrophes gone). Deliberately conservative: strip projection formats,
# restoration/anniversary tags, and Q&A markers — never words that distinguish programs (a
# double feature keeps both titles; a year stays UNLESS parenthesized, i.e. "(1975)" is a
# release-year tag but "Blade Runner 2049" must not collapse into "Blade Runner").
_FILM_NOISE = re.compile(
    r"\b(\d{2,3}\s?mm|4k|8k|imax|dcp|digital|dolby(\s+(vision|atmos|cinema))?|"
    r"restoration|restored|remaster(ed)?|extended (cut|edition)|directors cut|"
    r"final cut|theatrical cut|uncut|"
    r"\d{1,3}(st|nd|rd|th) anniversary|anniversary|"
    r"qanda|q and a|q a)\b")
_PAREN_YEAR = re.compile(r"\(\s*(19|20)\d\d\s*\)")
_WS = re.compile(r"\s+")

_SOLD_OUT = re.compile(r"\bsold[\s-]?out\b", re.I)


def is_film(ev: dict) -> bool:
    """Film-typed event: the deterministic tag (lib/tagging) or the source category."""
    if ((ev.get("tags") or {}).get("type")) == "film":
        return True
    return (ev.get("category") or "").strip().lower() == "film"


def film_core_title(title: str) -> str:
    """The film's identity with per-screening noise stripped, normalized for grouping.
    'The Odyssey (70mm)' -> 'the odyssey'; 'Jaws 50th Anniversary 4K' -> 'jaws'.
    Falls back to the full normalized title if stripping would leave nothing."""
    s = _PAREN_YEAR.sub(" ", str(title or ""))
    s = normalize(s)
    core = _WS.sub(" ", _FILM_NOISE.sub(" ", s)).strip()
    return core if len(core) >= 3 else s


def series_key(ev: dict):
    """Stable grouping key for the program this record is one night of. None = ungroupable."""
    title = (ev.get("title") or "").strip()
    if not title:
        return None
    if is_film(ev):
        return "film:" + film_core_title(title)
    return "run:" + normalize(title) + "|" + normalize(ev.get("venue") or "")


def group_series(events: list) -> "OrderedDict[str, list]":
    """Group events by series_key, keeping only real series (2+ members). Insertion-ordered
    and side-effect-free; members keep their input order (callers sort as they need)."""
    groups = OrderedDict()
    for ev in events:
        k = series_key(ev)
        if k:
            groups.setdefault(k, []).append(ev)
    return OrderedDict((k, v) for k, v in groups.items() if len(v) >= 2)


def _iso(ev: dict) -> str:
    return str(ev.get("iso_date") or ev.get("date") or "")[:10]


def _first_url(ev: dict):
    for link in (ev.get("links") or []):
        url = link.get("url") if isinstance(link, dict) else link
        if url:
            return url
    return ev.get("url")


def _sold_out(ev: dict) -> bool:
    hay = " ".join(str(ev.get(f) or "") for f in ("detail", "status", "price"))
    return bool(_SOLD_OUT.search(hay))


def series_summary(members: list) -> dict:
    """The compact run descriptor every member's card carries: how many nights, the span,
    the venues involved, and one entry per night (date/time/venue/link/sold-out) so a card
    can tease the individual showings apart. Entries are date-ordered."""
    entries = []
    for ev in sorted(members, key=_iso):
        entry = {"date": _iso(ev), "venue": ev.get("venue")}
        if ev.get("start"):
            entry["start"] = ev["start"]
        url = _first_url(ev)
        if url:
            entry["url"] = url
        if _sold_out(ev):
            entry["sold_out"] = True
        entries.append(entry)
    dates = [e["date"] for e in entries if e["date"]]
    venues = []
    for e in entries:
        if e.get("venue") and e["venue"] not in venues:
            venues.append(e["venue"])
    return {
        "count": len(entries),
        "first": dates[0] if dates else None,
        "last": dates[-1] if dates else None,
        "venues": venues,
        "entries": entries,
    }


def showtimes_url(title: str) -> str:
    """External showtimes search for a film — Google's showtimes panel covers the LA theaters
    that aren't (and won't be) fetch sources, satisfying 'where else can I see this'."""
    core = film_core_title(title) or normalize(title)
    return "https://www.google.com/search?q=" + quote_plus(f'"{core}" showtimes Los Angeles')
