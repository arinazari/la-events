"""Deterministic pipeline transforms for run_digest.py — pure and testable.

The "map" half (per-source normalize) is intentionally thin; the "reduce" half
(merge → dedupe → expire → stamp → score → select) is the schema-locking core that
the enrichment (scene-researcher) and synthesis steps build on. Keep it side-effect
free: run_digest.py does the I/O, this module does the transforms.
"""

import re
from datetime import date, datetime, timedelta, timezone

from .scoring import score_event, score_to_rating, parse_event_date
from .dedupe import dedupe
from .enrich import event_key
from .catalog_meta import VOLATILE_FIELDS, _lineup_sig
from .affinity import ambiguous_set, tracked_hits
from .tagging import VENUE_SCALE
from . import geo
from . import images

try:
    from zoneinfo import ZoneInfo
    _LA = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover - tzdata missing
    _LA = None

# Default category per source when a record doesn't carry one.
SOURCE_CATEGORY = {
    "ra": "electronic", "19hz": "electronic", "posh": "party",
    "ticketmaster": "music", "goldenvoice": "music", "dice": "live_music",
    "filmbot": "film", "vidiots": "film", "veezi": "film", "vista": "film", "newbev": "film",
    "eventbrite": "general",
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


# Marketing boilerplate that adds no information to a card blurb — dropped line-by-line.
_DETAIL_JUNK = re.compile(
    r"^\s*(buy\s+tickets?|get\s+tickets?|tickets?\s+(on\s+sale|available)|"
    r"doors?\s+open|21\s*\+|18\s*\+|all\s+ages|presented\s+by|"
    r"follow\s+us|click\s+here|rsvp|sold\s+out|free\s+entry|no\s+refunds?).*$",
    re.I)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([.,;:!?])")


def clean_detail(text, max_len: int = 400):
    """Sanitize a raw source description into a card-safe blurb: strip HTML tags/entities, drop
    pure-boilerplate lines (ticket CTAs, age limits, 'presented by …'), collapse whitespace, and
    cap length on a word boundary. Returns None when nothing meaningful survives — the single
    chokepoint so every source's `detail` is uniformly clean (run on normalize, not per-fetcher)."""
    if not text:
        return None
    s = _TAG.sub(" ", str(text))
    s = (s.replace("&amp;", "&").replace("&nbsp;", " ").replace("&#39;", "'")
          .replace("&quot;", '"').replace("&rsquo;", "'").replace("&ldquo;", '"').replace("&rdquo;", '"'))
    # Drop lines that are nothing but boilerplate; keep informative ones.
    kept = [ln.strip() for ln in s.splitlines() if ln.strip() and not _DETAIL_JUNK.match(ln.strip())]
    s = _SPACE_BEFORE_PUNCT.sub(r"\1", _WS.sub(" ", " ".join(kept)).strip())
    if len(s) < 3:
        return None
    if len(s) > max_len:
        s = s[:max_len].rsplit(" ", 1)[0].rstrip(",;:-") + "…"
    return s or None


# ── Junk / scam-listing gate ──────────────────────────────────────────────────────────
# SEO-spam listings dressed as events — call-center "customer service number" pages that
# sources (RA open submissions, TM resellers) let through. Tuned against the July 2026
# waves: the airline/hotline batch (~100 judged "skip" by event-editor, 2026-07-14) and
# the RA-sourced insurance wave ("State Farm … Customer Service Number", 2026-07-22..24).
# Judged on the TITLE only, on purpose: phones and service-speak occur legitimately in
# `detail` (TM box-office lines, venue info numbers) — a detail match would false-positive.
# Brand hits alone never drop (venue "The Airliner", band "Delta By The Beach" stay safe);
# a brand must co-occur with a service-action word.

# A formatted 3-3-4 phone (optionally +1 / parens) or a contiguous toll-free number.
_JUNK_PHONE_IN_TITLE = re.compile(
    r"(?:\+?1[\s.\-()]{0,3})?\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}"
    r"|\b\+?1?8(?:00|33|44|55|66|77|88)\d{7}\b")

# Call-center phrasing no real event title uses.
_JUNK_SERVICE_KW = re.compile(
    r"(?i)\b(customer\s+(?:service|care|support)|help\s?-?line|toll[\s\-]?free|"
    r"reservations?\s+(?:number|line|phone|desk)|booking\s+number|support\s+number|"
    r"contact\s+number|phone\s+number|call\s+now|24[/x]7\s+(?:support|help|assist))\b")

# Airline / travel brand + a service-action word (both required: keeps venue 'The
# Airliner', band 'Delta By The Beach', 'The United Theater' etc. safe).
_JUNK_TRAVEL_BRAND = re.compile(
    r"(?i)\b(airlines?|airways|ryanair|lufthansa|qantas(?:link)?|expedia|jetblue|"
    r"easyjet|air\s+canada|air\s+france|british\s+airways|volotea|eurowings|"
    r"air\s+astana|oman\s+air|garuda|aegean|china\s+southern|norse\s+atlantic|"
    r"arik\s+air|gulf\s+air|virgin\s+australia|breeze\s+airways)\b")
_JUNK_TRAVEL_ACTION = re.compile(
    r"(?i)\b(book(?:ing)?|reservations?|cancel(?:lation)?s?|refunds?|customer|"
    r"support|service|helpdesk|phone|number|call|baggage|check[\s\-]?in|"
    r"flight\s+change|name\s+change|ticket\s+change)\b")

# Insurance / fintech brand + an account-service action word.
_JUNK_FIN_BRAND = re.compile(
    r"(?i)\b(insurance|state\s+farm|allstate|geico|progressive\s+insurance|"
    r"coinbase|robinhood|quickbooks|paypal|venmo|norton|mcafee|antivirus)\b")
_JUNK_FIN_ACTION = re.compile(
    r"(?i)\b(customer\s+service|log\s?-?in|sign\s?-?in|bill\s+pay|billing|"
    r"cancel(?:lation)?s?|policy|grace\s+period|claims?|refunds?|credentials?|"
    r"account\s+access|phone|number|support)\b")


def is_junk_event(ev: dict):
    """Deterministic scam/SEO-spam gate. Returns a reason string for a junk
    listing, or None for a real event. Judged on the TITLE only — phones and
    service-speak in detail/venue fields occur legitimately (box-office lines)."""
    title = str(ev.get("title") or "")
    if _JUNK_PHONE_IN_TITLE.search(title):
        return "phone number in title (call-center spam)"
    if _JUNK_SERVICE_KW.search(title):
        return "call-center service phrasing in title"
    if _JUNK_TRAVEL_BRAND.search(title) and _JUNK_TRAVEL_ACTION.search(title):
        return "airline-hotline spam title"
    if _JUNK_FIN_BRAND.search(title) and _JUNK_FIN_ACTION.search(title):
        return "insurance/account-service spam title"
    return None


def drop_junk(records: list) -> tuple:
    """Split records into (kept, dropped) by is_junk_event. Runs over catalog + incoming
    at merge time, so junk that slipped into a committed catalog self-heals next pass."""
    kept, dropped = [], []
    for ev in records:
        (dropped if is_junk_event(ev) else kept).append(ev)
    return kept, dropped


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
            link = {"source": source or "?", "url": v}
            # Optional display label for the primary url (fetch_veezi's per-showtime "7:30pm"):
            # when dedupe folds a run's showtimes into one record, the accumulated links stay
            # distinguishable instead of rendering as N identical venue buttons.
            if key == "url" and isinstance(raw.get("url_label"), str) and raw["url_label"]:
                link["label"] = raw["url_label"]
            out.append(link)
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
    # Event photo (dashboard's top-events row): the fetchers pull this straight from the source
    # response they already fetched — zero extra network, zero LLM tokens (see lib/images.py). The
    # single final gate lives here: re-clean whatever a fetcher put on `image` so one bad/mixed-content
    # URL can't reach the feed. Kept SPARSE (only when present) so the ~3k image-less rows don't each
    # grow a null field — same treatment as lineup_genre.
    image = images.clean(raw.get("image"))
    return {
        "title": raw.get("title") or raw.get("name") or raw.get("event_name"),
        "date": date_str,
        "start": start,
        "venue": raw.get("venue") or raw.get("venue_name"),
        "neighborhood": raw.get("neighborhood"),
        "category": raw.get("category") or SOURCE_CATEGORY.get(source, "general"),
        "genre": raw.get("genre"),  # finer classification (TM segment->category, genre->genre); dashboard's CATEGORY / GENRE line
        # attraction-level TM genre — only present when the fetcher found one (kept sparse so
        # 3,600 records don't each grow a null field); tagging._resolve_type reads it.
        **({"lineup_genre": raw["lineup_genre"]} if raw.get("lineup_genre") else {}),
        "lineup": lineup,
        "links": _links(raw, source),
        "sources": _as_list(raw.get("sources") or source),
        "organizers": raw.get("organizers") or raw.get("organizer") or raw.get("promoter"),
        "detail": clean_detail(raw.get("detail") or raw.get("description") or raw.get("desc")),
        **({"image": image} if image else {}),
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
    """Stamp incoming as seen-today, drop junk, append, dedupe. Returns (catalog, stats).

    Catalog records come first so they're the merge base (preserve identity; absorb
    new ticket links). first_seen survives, last_seen advances (via dedupe.merge).
    The junk gate runs over catalog AND incoming before dedupe, so a scam listing
    already committed to the catalog is swept on the next pass (self-healing).
    """
    t = (today or today_la()).isoformat()
    for r in incoming:
        r["first_seen"] = r.get("first_seen") or t
        r["last_seen"] = t
    pool, junk = drop_junk(list(catalog) + list(incoming))
    deduped, report = dedupe(pool)
    stats = {"incoming": len(incoming), "merged": len(report),
             "added": max(0, len(deduped) - len(catalog)),
             "junk": len(junk)}
    if junk:
        stats["junk_titles"] = [str(e.get("title") or "")[:80] for e in junk[:5]]
    return deduped, stats


# Ticketmaster bakes the night-of date into its marketing URL slug: .../<name>-<city>-MM-DD-YYYY/event/<id>.
# Verified against the live Discovery API, this slug date equals `localDate` for every correctly-dated
# event — the *only* rows where it disagrees are ones an older fetcher mis-dated off TM's UTC `dateTime`
# (an evening LA show rolls past midnight into the next calendar day). So the slug is the authority.
_TM_SLUG_DATE = re.compile(r"-(\d{2})-(\d{2})-(\d{4})/event/", re.I)


def _tm_slug_date(ev: dict):
    """The night-of date from a record's Ticketmaster URL slug ('YYYY-MM-DD'), or None."""
    for link in (ev.get("links") or []):
        url = link.get("url") if isinstance(link, dict) else link
        m = _TM_SLUG_DATE.search(str(url or ""))
        if m:
            mm, dd, yyyy = m.groups()
            return f"{yyyy}-{mm}-{dd}"
    return None


def reconcile_tm_dates(catalog: list) -> int:
    """Repair Ticketmaster rows whose stored date drifted a day off the night-of date. Returns the count fixed.

    The root cause was fixed in fetch_ticketmaster.py (it now reads venue-LOCAL `localDate`/`localTime`,
    not UTC `dateTime`), but two failure modes outlive that fix: ~hundreds of pre-fix rows already sit in
    the catalog mis-dated, and a stale source (e.g. TM dark on a missing key) can keep re-seeding them. A
    mis-dated row is invisible until the night of the show — it just sits a day late — so this runs on
    EVERY pipeline pass (including --no-fetch rebuilds), idempotently, making the slug authoritative so a
    drifted row can never silently outlive one pass. (This is the general-day-roll sibling of the fetcher's
    narrow post-midnight `_nightof_date`; together they keep TM dates pinned to night-of.)

    Self-classifying per row — only the exactly-one-day roll signature is ever touched, so a genuinely
    different date is never clobbered:
      • full-UTC row  — (date, start) interpreted as UTC lands on the slug day once converted to LA, so
        the whole stamp is UTC: take the LA-local date AND time (a `01:30` 'next day' becomes the real
        `18:30` night-of).
      • date-only roll — the time is already venue-local; just move the date back to the slug.
    """
    fixed = 0
    for ev in catalog:
        slug = _tm_slug_date(ev)
        stored = str(ev.get("date") or "")[:10]
        if not slug or not stored or slug == stored:
            continue
        try:
            d0 = datetime.strptime(stored, "%Y-%m-%d").date()
            sd = datetime.strptime(slug, "%Y-%m-%d").date()
        except ValueError:
            continue
        if abs((d0 - sd).days) != 1:
            continue  # only the day-roll signature — never touch a genuinely different date
        start = ev.get("start")
        if start and _LA:
            try:
                la = (datetime.fromisoformat(f"{stored}T{start}")
                      .replace(tzinfo=timezone.utc).astimezone(_LA))
                if la.date().isoformat() == slug:        # whole stamp was UTC → recover local date+time
                    ev["date"] = slug
                    ev["start"] = la.strftime("%H:%M:%S")
                    fixed += 1
                    continue
            except ValueError:
                pass
        ev["date"] = slug                                # date-only roll — venue-local time already right
        fixed += 1
    return fixed


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


# ── Out-of-market drop (catalog policy, Ari 2026-07-17) ───────────────────────────────
# The TM DMA query reaches Palm Springs / Paso Robles / San Diego-adjacent venues; those rows
# used to travel the whole pipeline (catalog, diffs, editor pool) and then rank at the bottom
# forever under the far penalty. Now they're dropped at merge time UNLESS radar-worthy —
# festival bills, tracked artists, and arena headliners keep the "genuinely worth the trip"
# door open (same signals build_radar keys on). The list is profile config
# (`pipeline.out_of_market`), so the day-trip boundary is a YAML edit, not code.

_FEST_TITLE_KW = re.compile(r"\bfestival\b|\bfest\b", re.I)
_ARENA_KEYS = tuple(k for k, v in VENUE_SCALE.items() if v == "arena")


def radar_worthy(ev: dict, tracked: list, ambiguous=frozenset()) -> bool:
    """Would the plan-ahead radar want this event regardless of distance? Festival bills,
    arena/amphitheater-tier venues, and tracked artists (lineup-first, whole-token —
    lib/affinity.tracked_hits, same matcher the radar uses)."""
    title = str(ev.get("title") or "")
    if _FEST_TITLE_KW.search(title):
        return True
    venue = str(ev.get("venue") or "").lower()
    if any(k in venue for k in _ARENA_KEYS):
        return True
    return bool(tracked and tracked_hits(tracked, title, ev.get("lineup"), ambiguous))


def drop_out_of_market(catalog: list, taste: dict = None, profile: dict = None) -> tuple:
    """Drop rows whose neighborhood is on the profile's `pipeline.out_of_market` list and
    that carry no radar signal. Runs over the merged catalog (cleans pre-existing rows too;
    re-fetched rows re-drop idempotently). Returns (kept, n_dropped). No list => no-op."""
    hoods = {str(h).lower().strip()
             for h in (((profile or {}).get("pipeline") or {}).get("out_of_market") or [])}
    if not hoods:
        return catalog, 0
    tracked = [a for a in ((taste or {}).get("artists_tracked") or []) if a]
    amb = ambiguous_set(profile, taste)
    kept, dropped = [], 0
    for ev in catalog:
        nb = str(ev.get("neighborhood") or "").lower().strip()
        if nb in hoods and not radar_worthy(ev, tracked, amb):
            dropped += 1
        else:
            kept.append(ev)
    return kept, dropped


# ── Recurring markets/fleas → dated catalog rows (recurring.yaml materializer) ─────────
# The known weeklies/monthlies (Silver Lake Farmers Market, Melrose Trading Post, Rose Bowl
# Flea…) used to exist only as digest-render prose, so the market lane, dashboard shelves,
# and editor pool never saw them. This expands the cadence rules into normal dated records
# (source `recurring`); merge_new dedupes them, so re-running is idempotent.

_DOW = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _cadence_dates(token: str, today: date, days: int) -> list:
    """Dates in [today, today+days) for one cadence token: weekly:<DOW> or monthly:<N>:<DOW>
    (monthly:2:Sun = 2nd Sunday). Unknown tokens yield [] (never block a run)."""
    parts = str(token or "").strip().lower().split(":")
    out, end = [], today + timedelta(days=days)
    if len(parts) == 2 and parts[0] == "weekly" and parts[1][:3] in _DOW:
        d = today + timedelta(days=(_DOW[parts[1][:3]] - today.weekday()) % 7)
        while d < end:
            out.append(d)
            d += timedelta(days=7)
    elif len(parts) == 3 and parts[0] == "monthly" and parts[2][:3] in _DOW:
        try:
            nth = int(parts[1])
        except ValueError:
            return []
        y, m = today.year, today.month
        while date(y, m, 1) < end:
            first = date(y, m, 1)
            d = first + timedelta(days=(_DOW[parts[2][:3]] - first.weekday()) % 7
                                        + 7 * (nth - 1))
            if d.month == m and today <= d < end:
                out.append(d)
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def materialize_recurring(doc: dict, today: date = None, days: int = 35) -> list:
    """Expand recurring.yaml's `markets` into normalized records for the next `days` days.
    Each occurrence is a normal catalog row (title/venue/date/category/start), so dedupe,
    expiry, tagging, and scoring treat it like any fetched event."""
    today = today or today_la()
    out = []
    for entry in (doc or {}).get("markets") or []:
        skip_months = {int(m) for m in entry.get("except_months") or []}
        for token in entry.get("cadence") or []:
            for d in _cadence_dates(token, today, days):
                if d.month in skip_months:
                    continue                  # e.g. Topanga Vintage skips December
                out.append(normalize_record({
                    "title": entry.get("name"),
                    "date": d.isoformat(),
                    "start": entry.get("start"),
                    "venue": entry.get("where"),
                    "neighborhood": entry.get("neighborhood"),
                    "category": entry.get("category") or "market",
                    "detail": " · ".join(x for x in (entry.get("when"), entry.get("note")) if x),
                    "url": entry.get("url"),
                }, source="recurring"))
    return out


def _volatile_snapshot(ev: dict) -> dict:
    """A compact view of the fields whose change means 'this event was updated' (not just re-seen).
    Shares `_lineup_sig` with catalog_meta so the per-field diff can't drift from content_version."""
    snap = {f: ("" if ev.get(f) is None else str(ev.get(f))) for f in VOLATILE_FIELDS if f != "lineup"}
    snap["lineup"] = _lineup_sig(ev)
    return snap


def content_index(catalog: list) -> dict:
    """Map event_key -> its volatile snapshot. Taken BEFORE a fetch/merge so the next diff_catalog
    can tell genuinely-new and genuinely-changed events apart from merely re-seen ones."""
    return {event_key(e): _volatile_snapshot(e) for e in (catalog or [])}


def diff_catalog(old_index: dict, new_catalog: list, today: date = None) -> dict:
    """Compare the merged catalog against the pre-fetch `content_index`. Stamps `updated_at` +
    `changed_fields` on each record whose volatile fields moved, and returns the run's change
    summary {added, updated, changes:[{title,date,venue,fields}]} — the data behind the digest's
    "N new, M updated since <when>" line and the dashboard's "what changed" readout."""
    t = (today or today_la()).isoformat()
    added = updated = 0
    changes = []
    for ev in new_catalog:
        prev = old_index.get(event_key(ev))
        if prev is None:
            added += 1
            continue
        snap = _volatile_snapshot(ev)
        moved = [f for f in snap if snap[f] != prev.get(f, "")]
        if moved:
            updated += 1
            ev["updated_at"] = t
            ev["changed_fields"] = moved
            changes.append({"title": ev.get("title"), "date": ev.get("date"),
                            "venue": ev.get("venue"), "fields": moved})
    return {"added": added, "updated": updated, "changes": changes}


def flag_stale(catalog: list, fetched_sources, today: date = None, *,
               horizon_days: int, grace_days: int = 2) -> int:
    """Ghost detection: an event still future-dated but no longer listed by ANY of its sources is
    probably cancelled / postponed / sold-through / pulled — stamp `status: "unlisted"` so it stops
    being recommended (score_pool drops it) while staying in the catalog (it un-flags if it returns).

    Conservative on purpose — only judges an event when we can: every one of its sources was fetched
    OK this run (a source that failed/wasn't fetched tells us nothing), the event is inside the fetch
    horizon (beyond it, absence is expected), and it's been unseen for `grace_days` (last_seen lag),
    so a single source hiccup doesn't ghost the catalog. Returns the number newly flagged."""
    today = today or today_la()
    fetched = set(fetched_sources or [])
    if not fetched:
        return 0                              # no successful structured fetch → can't judge anything
    horizon = today + timedelta(days=horizon_days)
    flagged = 0
    for ev in catalog:
        d = parse_event_date(ev)
        if d is None or d < today or d > horizon:
            continue
        srcs = set(ev.get("sources") or [])
        if not srcs or not srcs.issubset(fetched):     # some source wasn't refreshed → don't judge
            continue
        ls = str(ev.get("last_seen") or "")[:10]
        try:
            seen = date.fromisoformat(ls) if ls else None
        except ValueError:
            seen = None
        if seen is None:
            continue
        if (today - seen).days >= grace_days:
            if ev.get("status") != "unlisted":
                ev["status"] = "unlisted"
                flagged += 1
        elif ev.get("status") == "unlisted":           # re-listed since → clear the flag
            ev.pop("status", None)
    return flagged


def source_freshness(catalog: list, today: date = None) -> dict:
    """Per-source recency from the catalog's `last_seen` stamps:
    {source: {"last_seen": newest, "median_last_seen": bulk, "days": <bulk staleness>,
              "newest_days": <newest staleness>, "count": n}}.

    The signal behind 'a source went dark'. last_seen is fetch-time: a healthy fetcher re-confirms
    nearly all of its events every run, so their last_seen tracks today; when the fetcher breaks or a
    key/token lapses, those timestamps freeze while today marches on — even though the run still
    'succeeds' (degrade-gracefully buries the gap in one log line). Staleness keys off the MEDIAN
    last_seen, not the newest: a dark source can still show a few fresh rows because another source
    cross-lists them (19hz/DICE re-list a TM event and refresh it), and the max would let those
    outliers mask the outage. The bulk (median) is immune. Computed straight off the committed catalog
    so it's honest whether or not this run fetched."""
    today = today or today_la()
    from collections import defaultdict
    seen: dict = defaultdict(list)
    for ev in catalog:
        ls = str(ev.get("last_seen") or "")[:10]
        if not ls:
            continue
        for s in (ev.get("sources") or []):
            seen[s].append(ls)

    def _days(d):
        try:
            return (today - date.fromisoformat(d)).days
        except ValueError:
            return None

    out: dict = {}
    for s, dates in seen.items():
        dates.sort()
        newest = dates[-1]
        median = dates[(len(dates) - 1) // 2]      # lower median — robust to cross-listed fresh outliers
        out[s] = {"last_seen": newest, "median_last_seen": median,
                  "days": _days(median), "newest_days": _days(newest), "count": len(dates)}
    return out


def stale_sources(catalog: list, today: date = None, *, min_days: int = 3, min_count: int = 20) -> list:
    """Sources gone quiet: the BULK (median) of their events hasn't been re-seen in >= min_days, and
    they carry >= min_count rows (so a tiny/occasional source isn't flagged). Returns
    [(source, days_stale, count)], stalest first — the 'Ticketmaster has been dark for a week' alarm
    that a silently-skipped fetch (missing key, broken fetcher) never raised."""
    out = []
    for s, v in source_freshness(catalog, today).items():
        if v.get("count", 0) >= min_count and v.get("days") is not None and v["days"] >= min_days:
            out.append((s, v["days"], v["count"]))
    return sorted(out, key=lambda x: -x[1])


def normalize_locations(catalog: list, profile: dict = None) -> list:
    """Canonicalize each record's `neighborhood` in place (idempotent).

    Fetchers leave the location messy — TM/JSON-LD/Goldenvoice emit city-level
    "Los Angeles", Posh and others emit nothing — so the catalog's "location" reads as a
    "LA" + "Los Angeles" + blank pile. geo.canonical_location() resolves a venue to its real
    neighborhood where the gazetteer knows it (Fonda -> Hollywood), collapses the unplaceable
    city-level rows to one label, and fixes casing/aliases. Runs over the WHOLE catalog each
    pass so existing rows get cleaned too, not just incoming. True unknowns stay blank — the
    digest/dashboard own that fallback."""
    for ev in catalog:
        ev["neighborhood"] = geo.canonical_location(ev.get("venue"), ev.get("neighborhood"), profile)
    return catalog


def score_view(ev: dict, taste: dict, profile: dict, affinity: dict = None) -> dict:
    """A scored copy of an event (catalog stays score-free; scores live in the candidate set)."""
    s = score_event(ev, taste, profile, affinity)
    d = parse_event_date(ev)
    out = dict(ev)
    out["score"] = s["score"]
    out["rating"] = score_to_rating(s["score"], profile, taste)
    out["reasons"] = s["reasons"]
    out["iso_date"] = d.isoformat() if d else None
    return out


def score_pool(catalog, taste, profile, today=None, window_days=None, affinity=None) -> list:
    """All upcoming events in the window, scored and sorted best-first (no top-N cut).

    The shared scored set: select_candidates slices the enrichment top-N off it, and the editor
    pass (lib/editor.editor_pool) draws its per-lane judging set from the same list — one scoring
    path, no drift. `window_days=None` = all upcoming."""
    today = today or today_la()
    start = today.isoformat()
    end = (today + timedelta(days=window_days)).isoformat() if window_days is not None else None

    scored = []
    for ev in catalog:
        if ev.get("status") == "unlisted":          # ghost (dropped from all its sources) — don't surface
            continue
        v = score_view(ev, taste, profile, affinity)
        if not v["iso_date"] or v["iso_date"] < start:
            continue
        if end and v["iso_date"] > end:
            continue
        scored.append(v)

    scored.sort(key=lambda e: (-e["score"], e["iso_date"]))
    return scored


def select_candidates(catalog, taste, profile, today=None, window_days=None,
                      top_n=40, affinity=None, verdicts=None) -> list:
    """The enrichment candidate set: upcoming events, best-first, top N.

    `affinity` (optional) layers the Spotify + feedback music profile into the scoring.
    `verdicts` (optional, Track B2 — the on-disk event-editor cache as a key->verdict map):
    orders the head by assemble.rank_score (score + adjust + bounded tier bonus), so the
    editor's judgment, not the raw keyword score, decides what gets the full enrichment
    treatment. Unjudged (brand-new) events compete on raw score — they're judged the same
    run and slot correctly the next.
    """
    pool = score_pool(catalog, taste, profile, today, window_days, affinity)
    if verdicts:
        from .assemble import rank_score
        pool = sorted(pool, key=lambda e: (-rank_score(e, verdicts), event_key(e)))
    return pool[:top_n]
