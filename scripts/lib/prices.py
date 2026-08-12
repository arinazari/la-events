"""Cheapest-ticket finder — resale price checks across marketplaces (data/ticket_prices.json).

The card's "cheapest tickets" option (Ari, 2026-08-01: "Kim Gordon is $20 on StubHub,
~$45 on Ticketmaster"). Resale floors routinely undercut face price and nothing in the
pipeline knew: Ticketmaster's Discovery API returns 0% priceRanges for LA (verified —
see ROADMAP), so even the primary price is usually unknown. Three layers, cheapest wins:

  1. AUTOMATED — Gametime's open mobile API (mobile.gametime.co/v1/search, no key)
     returns real all-in resale floors (min_price.total, in cents) with venue + metro
     per event, so ONE query per artist prices every LA date they play. Optionally
     SeatGeek's official API when SEATGEEK_CLIENT_ID is set (stats.lowest_price).
  2. RECORDED — StubHub / Vivid Seats / TickPick are bot-walled from datacenters; a
     session (concierge) reads them and records finds via check_prices.py --record.
  3. LINKS — compare_links() builds prefilled marketplace-search URLs that always work
     in the *browser* regardless of bot walls; the dashboard mirrors the same set
     client-side so every card has one-tap comparison even with no check on file.

Store: data/ticket_prices.json, COMMITTED (stateless-run rule), keyed by
lib/enrich.event_key. One entry per event; options dedupe by source, a re-check
replaces that source's row. build_dashboard folds entries onto feed rows as
`price_check` (options cheapest-first + checked_at); the card renders the comparison
with the cheapest flagged and the check's age shown honestly — resale prices move
daily, so a stamp is part of the data, not decoration.
"""

import json
import re
from pathlib import Path
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen

from .dedupe import _venue_key, normalize
from .enrich import event_key

DEFAULT_STORE = "data/ticket_prices.json"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

GAMETIME_SEARCH = "https://mobile.gametime.co/v1/search"
SEATGEEK_EVENTS = "https://api.seatgeek.com/2/events"

# Marketplace search fronts, verified 2026-08-01 (StubHub's old /find/s/ path is a 404 now;
# TickPick redirects /search -> /search/). Label -> prefilled-search URL builder.
MARKETPLACES = (
    ("StubHub", lambda q: f"https://www.stubhub.com/search?q={quote_plus(q)}"),
    ("SeatGeek", lambda q: f"https://seatgeek.com/search?search={quote_plus(q)}"),
    ("Gametime", lambda q: f"https://gametime.co/search?query={quote_plus(q)}"),
    ("TickPick", lambda q: f"https://www.tickpick.com/search/?q={quote_plus(q)}"),
    ("Vivid Seats", lambda q: f"https://www.vividseats.com/search?searchTerm={quote_plus(q)}"),
)

# Title tails that aren't the act: tour names ("Kim Gordon - Play Me Tour"), age gates,
# "with special guests…". Kept deliberately narrow — a dash tail is only dropped when the
# head is substantial, so "Jay - Z" style names don't lose their tail.
_TOUR_TAIL = re.compile(r"\s*[-–—:]\s*[^-–—:]*\b(tour|live|residency)\b[^-–—:]*$", re.I)
_PAREN_TAIL = re.compile(r"\s*\((?:[^)]*)\)\s*$")
_EVENING_WITH = re.compile(r"^an evening with\s+", re.I)
_FREE_RE = re.compile(r"\bfree\b|no cover", re.I)
_MONEY_RE = re.compile(r"\$\s?(\d+(?:\.\d+)?)")


def search_name(ev: dict) -> str:
    """The marketplace query for an event: the headliner when the lineup names one, else the
    title with tour-name / parenthetical / "An evening with" dressing stripped."""
    lineup = ev.get("lineup") or []
    if lineup and str(lineup[0]).strip():
        # Headliners carry dressing too — TM lineups say "The Phantom of the Opera (Touring)".
        head = _PAREN_TAIL.sub("", str(lineup[0])).strip()
        return head or str(lineup[0]).strip()
    t = str(ev.get("title") or "").strip()
    t = _EVENING_WITH.sub("", t)
    t = _PAREN_TAIL.sub("", t).strip()
    cut = _TOUR_TAIL.sub("", t).strip()
    if cut != t and len(cut) >= 3:
        return cut
    # A plain spaced-dash tail ("Justice - Woven City") is dressing too — the head is the
    # act, kept only when substantial so a short/degenerate head keeps the whole title.
    parts = re.split(r"\s+[-–—]\s+", t, maxsplit=1)
    if len(parts) == 2 and len(parts[0].strip()) >= 3:
        return parts[0].strip()
    return t or str(ev.get("title") or "").strip()


def compare_links(name: str) -> list:
    """[{label, url}] prefilled marketplace searches for a query — browser-side deep links."""
    q = str(name or "").strip()
    return [{"label": lbl, "url": mk(q)} for lbl, mk in MARKETPLACES] if q else []


def is_free(ev: dict) -> bool:
    """True when the listed price reads free (a resale check would be noise)."""
    p = str(ev.get("price") or "")
    return bool(_FREE_RE.search(p)) and not _MONEY_RE.search(p)


def listed_price_min(ev: dict):
    """Lowest advertised dollar figure in the catalog's free-text `price`, or None."""
    nums = [float(m) for m in _MONEY_RE.findall(str(ev.get("price") or ""))]
    return min(nums) if nums else None


def listed_option(ev: dict, checked_at: str = None) -> dict | None:
    """The primary "as listed" row from the catalog's own price text (RA/19hz/webfetch/flyer
    sources carry one; TM rows usually don't). Anchors the comparison when present."""
    pmin = listed_price_min(ev)
    if pmin is None and not is_free(ev):
        return None
    links = ev.get("links") or []
    src = (links[0].get("source") if links and isinstance(links[0], dict) else None) \
        or ((ev.get("sources") or [None])[0]) or "listed"
    return _clean_option({
        "source": str(src), "kind": "listed",
        "price": 0.0 if pmin is None else pmin,
        "url": links[0].get("url") if links and isinstance(links[0], dict) else None,
        "note": str(ev.get("price")).strip() or None,
        "checked_at": checked_at,
    })


# ── Gametime ────────────────────────────────────────────────────────────────────


def _http_json(url: str, timeout: int = 15, fetch=None):
    if fetch is not None:
        return json.loads(fetch(url))
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def gametime_search(query: str, fetch=None) -> list:
    """Raw Gametime search items ([{event, venue, performers}, …]) for a query. `fetch`
    (url -> bytes/str) is injectable for tests; network errors propagate to the caller,
    which degrades gracefully (one dead marketplace never blocks a check run)."""
    url = f"{GAMETIME_SEARCH}?{urlencode({'q': query})}"
    data = _http_json(url, fetch=fetch)
    return [it for it in (data.get("events") or []) if isinstance(it, dict)]


def _venue_overlap(a: str, b: str) -> bool:
    ta = {t for t in _venue_key(a).split() if len(t) >= 3}
    tb = {t for t in _venue_key(b).split() if len(t) >= 3}
    return bool(ta & tb)


def _name_matches(ev: dict, gt_name: str) -> bool:
    """Every token of Gametime's event name appears in our title+lineup blob (their name is
    the performer — ours usually carries tour dressing on top of it)."""
    blob = normalize(" ".join([str(ev.get("title") or "")] + [str(x) for x in (ev.get("lineup") or [])]))
    toks = [t for t in normalize(gt_name).split() if t]
    return bool(toks) and all(t in blob.split() for t in toks)


def match_gametime(ev: dict, items: list) -> dict | None:
    """The Gametime search item for OUR event: same LA metro + same local date, and either
    the venue overlaps or their event name is contained in our title/lineup. Venue overlap
    outranks name-only (an artist can play two rooms in one night)."""
    date = str(ev.get("date") or "")[:10]
    best, best_rank = None, -1
    for it in items:
        e, v = it.get("event") or {}, it.get("venue") or {}
        if (v.get("metro") or "").lower() != "losangeles":
            continue
        if str(e.get("datetime_local") or "")[:10] != date:
            continue
        venue_ok = _venue_overlap(ev.get("venue") or "", v.get("name") or "")
        name_ok = _name_matches(ev, e.get("name") or "")
        if not (venue_ok or name_ok):
            continue
        rank = (2 if venue_ok else 0) + (1 if name_ok else 0)
        if rank > best_rank:
            best, best_rank = it, rank
    return best


def gametime_option(item: dict, checked_at: str = None) -> dict | None:
    """A store option from a matched Gametime item — their prices are all-in cents
    (total = what checkout charges; prefee = sticker before fees). No listings -> None."""
    e = (item or {}).get("event") or {}
    mp = e.get("min_price") or {}
    total = mp.get("total") or 0
    if not isinstance(total, (int, float)) or total <= 0:
        return None
    prefee = mp.get("prefee") or 0
    return _clean_option({
        "source": "gametime", "kind": "resale",
        "price": round(total / 100.0, 2),
        "prefee": round(prefee / 100.0, 2) if prefee > 0 else None,
        "url": e.get("seo_url") or None,
        "note": "all-in",
        "checked_at": checked_at,
    })


# ── SeatGeek (optional — needs SEATGEEK_CLIENT_ID) ─────────────────────────────


def seatgeek_option(ev: dict, client_id: str, fetch=None) -> dict | None:
    """SeatGeek's lowest listing for the event's date in LA, via their official API.
    stats.lowest_price is BEFORE fees (their checkout adds them) — noted on the row."""
    if not client_id:
        return None
    date = str(ev.get("date") or "")[:10]
    q = {"client_id": client_id, "q": search_name(ev), "venue.city": "Los Angeles",
         "datetime_local.gte": f"{date}T00:00", "datetime_local.lte": f"{date}T23:59",
         "per_page": 10}
    data = _http_json(f"{SEATGEEK_EVENTS}?{urlencode(q)}", fetch=fetch)
    best = None
    for e in data.get("events") or []:
        low = (e.get("stats") or {}).get("lowest_price")
        if low and (best is None or low < best[0]):
            best = (low, e)
    if not best:
        return None
    low, e = best
    return _clean_option({
        "source": "seatgeek", "kind": "resale", "price": float(low),
        "url": e.get("url") or None, "note": "+fees",
    })


# ── Store (data/ticket_prices.json) ─────────────────────────────────────────────


_OPTION_FIELDS = ("source", "kind", "price", "prefee", "url", "note", "checked_at")


def _clean_option(opt: dict) -> dict:
    out = {k: opt[k] for k in _OPTION_FIELDS if opt.get(k) is not None}
    out["source"] = str(out.get("source") or "?").lower()
    out.setdefault("kind", "resale")
    return out


def load_store(path=DEFAULT_STORE) -> dict:
    p = Path(path)
    if p.exists():
        s = json.loads(p.read_text())
        s.setdefault("events", {})
        return s
    return {"events": {}}


def save_store(store: dict, path=DEFAULT_STORE) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(store, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def record(store: dict, ev: dict, option: dict, checked_at: str = None) -> dict:
    """Upsert one option for one event. Same-source rows replace (a re-check IS the new
    truth); different sources accumulate into the comparison. Returns the entry."""
    key = ev.get("key") or event_key(ev)
    opt = _clean_option(dict(option))
    if checked_at and "checked_at" not in opt:
        opt["checked_at"] = checked_at
    entry = store.setdefault("events", {}).setdefault(key, {
        "title": ev.get("title"), "date": str(ev.get("date") or "")[:10],
        "venue": ev.get("venue"), "options": [],
    })
    entry["title"], entry["venue"] = ev.get("title") or entry.get("title"), ev.get("venue") or entry.get("venue")
    entry["options"] = [o for o in entry.get("options") or [] if o.get("source") != opt["source"]]
    entry["options"].append(opt)
    entry["options"].sort(key=_price_sort)
    stamps = [o.get("checked_at") for o in entry["options"] if o.get("checked_at")]
    if stamps:
        entry["checked_at"] = max(stamps)
    return entry


def _price_sort(o: dict):
    p = o.get("price")
    return (p is None, p if p is not None else 0.0, o.get("source") or "")


def prune(store: dict, today_iso: str) -> int:
    """Drop entries for past events (the card they'd render on is gone). Returns #dropped."""
    evs = store.get("events") or {}
    dead = [k for k, e in evs.items() if str(e.get("date") or "") and str(e.get("date")) < today_iso]
    for k in dead:
        del evs[k]
    return len(dead)


def price_map(store: dict) -> dict:
    """{event_key: {checked_at, options[]}} for the feed fold — options cheapest-first,
    capped; the page renders rows verbatim and flags options[0] as the floor."""
    out = {}
    for k, e in (store.get("events") or {}).items():
        opts = sorted([_clean_option(o) for o in e.get("options") or [] if isinstance(o, dict)],
                      key=_price_sort)[:8]
        if opts:
            out[k] = {"checked_at": e.get("checked_at"), "options": opts}
    return out


# ── --auto selection (which events are worth a nightly check) ───────────────────

# Lane FAMILIES where a resale market actually exists: club nights, live rooms (incl. the
# arena tier), comedy, theater runs. Film/markets/workshops never resell; free events have
# no floor to find. Callers pass events that already carry `score` (the CLI stamps the same
# lib/scoring score the feed uses) so rank_key orders exactly like the front page.
_AUTO_FAMILIES = {"club", "live-music", "comedy", "stage"}


def auto_pool(catalog: list, verdicts: dict, today_iso: str, days: int = 21,
              starred: set = None) -> list:
    """The events worth a nightly automated check: upcoming resale-plausible lanes in the
    near window, not free, not ghost-flagged, not judged-skip — ranked (stars first, then
    the same rank_key the front page features by) so the CLI's --top cap keeps the head.
    Starred events make the pool at ANY horizon: someone is actually going to those."""
    from .assemble import event_lane, rank_key  # local import — avoids an import cycle
    end = None
    if days:
        from datetime import date, timedelta
        end = (date.fromisoformat(today_iso) + timedelta(days=days)).isoformat()
    pool = []
    for ev in catalog:
        d = str(ev.get("date") or "")[:10]
        if not d or d < today_iso or ev.get("status") == "unlisted":
            continue
        key = event_key(ev)
        star = bool(starred and key in starred)
        if not star:
            if end and d > end:
                continue
            if event_lane(ev, verdicts).split(":")[0] not in _AUTO_FAMILIES:
                continue
            if is_free(ev):
                continue
            if (verdicts.get(key) or {}).get("tier") == "skip":
                continue
        pool.append((star, rank_key(ev, verdicts), key, ev))
    pool.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
    return [ev for _, _, _, ev in pool]
