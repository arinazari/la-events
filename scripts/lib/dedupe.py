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
from collections import defaultdict
from datetime import date
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


# ── Festival cross-source dedupe ───────────────────────────────────────────────
# Festivals list under varying names ("HARD Summer 2026" vs "HARD Summer Music Festival")
# AND varying venue strings ("Hollywood Park Grounds" vs "TBA - Hollywood Park adjacent to
# SoFi Stadium") across sources, so the standard venue+title path misses them. A same-date pair
# whose festival "core name" agrees and whose venues are at least loosely related is one festival.
_FEST_SIGNAL = re.compile(r"\b(festival|fest|weekender|block party)\b")
# Edition / format / ticket-tier / year filler, stripped to get the festival's core name.
_FEST_FILLER = re.compile(
    r"\b(festival|fest|music|edition|presents|day|days|one|two|three|[123]|"
    r"pass|passes|weekend|weekender|ga|vip|19\d\d|20\d\d)\b")


def _is_festivalish(ev: dict) -> bool:
    """Looks like a festival: festival words in the title/detail, or a deep (≥4) bill."""
    hay = normalize(ev.get("title", "")) + " " + normalize(str(ev.get("detail") or ""))
    if _FEST_SIGNAL.search(hay):
        return True
    lineup = ev.get("lineup") or []
    return isinstance(lineup, list) and len(lineup) >= 4


def _fest_core(title: str) -> str:
    """The festival's distinctive name: drop an organizer 'X presents:' prefix, then edition/
    format/year filler. 'Hypnotique Presents: Sway Festival - 2 DAY PASS' -> 'sway'."""
    s = normalize(title)
    s = re.sub(r"^.*?\bpresents\b[:\s]*", "", s)   # organizer prefix
    return _WS.sub(" ", _FEST_FILLER.sub(" ", s)).strip()


def _venue_related(a: dict, b: dict) -> bool:
    """Looser than _venue_match: same venue, a shared meaningful token, or one side TBA/unknown
    (festivals get vague/placeholder venue strings that vary across sources)."""
    va, vb = _venue_key(a.get("venue", "")), _venue_key(b.get("venue", ""))
    if not va or not vb or "tba" in va or "tba" in vb:
        return True
    if _venue_match(a, b):
        return True
    return bool({t for t in (set(va.split()) & set(vb.split())) if len(t) >= 4})


def _festival_match(a: dict, b: dict) -> bool:
    """Same festival from two sources: at least one side reads as a festival, the core names
    agree, and the venues are related. Festival-ness is a property of the *pair* — one source
    labels it 'HARD Summer Music Festival', the other 'HARD Summer 2026' with a short bill.
    Deliberately does NOT require lineup agreement (sources bill different headliners)."""
    fa, fb = _is_festivalish(a), _is_festivalish(b)
    if not (fa or fb):
        return False
    ca, cb = _fest_core(a.get("title", "")), _fest_core(b.get("title", ""))
    if len(ca) < 4 or len(cb) < 4:
        return False  # too generic to trust without a stronger signal
    if not _venue_related(a, b):
        return False
    if fa and fb:                                   # both look like festivals: allow fuzzy core
        return ca == cb or _contains(ca, cb) or _ratio(ca, cb) >= 0.9
    return ca == cb                                 # one-sided: demand an identical core name


# ── Ticket-link identity ───────────────────────────────────────────────────────
# A shared *per-event* ticket id is the highest-precision duplicate signal there is: two records
# pointing at the same Ticketmaster event / RA event / Posh page / DICE / Eventbrite listing are
# the same event, even when their venue+title strings diverge past the fuzzy threshold (a
# secret-warehouse party billed "Secret DTLA Warehouse" by one source, "TBA (DTLA)" by another) or
# when a source mis-dates it by a day (a post-midnight set filed on the next calendar day). 19hz in
# particular re-lists RA/Posh/TM events and links straight back to them, so most of these collide.
#
# Two rules make this safe:
#   • Only canonicalize URLs that identify ONE event. Promoter/tracking links (on.fgtix.com/trk/...)
#     and venue homepages are shared by many distinct events, so they are NOT identity — a two-day
#     festival shares one fgtix link across both nights and must stay two rows.
#   • TM ids are CASE-SENSITIVE and use a base64url alphabet ('Z7r9jZ1A7x71F' and '...71f' are two
#     different shows): preserve case and keep '_' and '-', or distinct events collapse together.
_LINK_ID_PATTERNS = [
    ("tm", re.compile(r"ticketmaster\.com/(?:[^?#]*/)?event/([0-9A-Za-z_-]+)")),
    ("ra", re.compile(r"ra\.co/events/(\d+)")),
    ("posh", re.compile(r"posh\.vip/e/([A-Za-z0-9-]+)")),
    ("dice", re.compile(r"dice\.fm/(?:event|e)/([A-Za-z0-9-]+)")),
    ("eventbrite", re.compile(r"eventbrite\.[a-z.]+/e/(?:[A-Za-z0-9-]*-)?(\d{6,})")),
]


def _link_ids(ev: dict) -> set:
    """Canonical per-event ticket ids carried by a record's links (e.g. {'tm:09006437C99A49D6'}).
    Case preserved on purpose (TM ids are case-sensitive). Generic/tracking links yield nothing."""
    ids = set()
    for link in (ev.get("links") or []):
        url = link.get("url") if isinstance(link, dict) else link
        if not url:
            continue
        for tag, pat in _LINK_ID_PATTERNS:
            m = pat.search(str(url))
            if m:
                ids.add(f"{tag}:{m.group(1)}")
    return ids


def _link_premerge(events: list) -> tuple:
    """Collapse records that share a per-event ticket id — regardless of date, venue, or title.

    Runs before the date-bucketed fuzzy pass and catches exactly what that pass can't: the same
    event from two sources whose venue strings diverge too far to fuzzy-match, and the same event
    a source filed a day off (post-midnight roll). Each cluster merges into its EARLIEST-dated
    member — a roll only ever pushes a show later, so the earliest date is the night-of one.
    Returns (events, report) with report entries shaped like dedupe's (kept_title, absorbed_title).
    """
    buckets = defaultdict(list)            # link id -> [event index, ...]
    for idx, ev in enumerate(events):
        for lid in _link_ids(ev):
            buckets[lid].append(idx)

    parent = list(range(len(events)))      # union-find so an event bridging two ids joins one cluster
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    for idxs in buckets.values():
        for other in idxs[1:]:
            union(idxs[0], other)

    comps = defaultdict(list)
    for idx in range(len(events)):
        comps[find(idx)].append(idx)

    out, report = [], []
    for idxs in comps.values():
        members = [events[i] for i in idxs]
        if len(members) == 1:
            out.append(members[0])
            continue
        members.sort(key=lambda e: (parse_event_date(e) or date.max))   # earliest = night-of
        base = members[0]
        for m in members[1:]:
            report.append((base.get("title"), m.get("title")))
            base = merge(base, m)
        out.append(base)
    return out, report


# ── Placeholder-venue dedupe ───────────────────────────────────────────────────
# Secret / TBA warehouse + afterhours parties name no real place, and the placeholder string varies
# by source ("Secret DTLA Warehouse" / "TBA (DTLA)" / "TBA - Location Link in Bio on Instagram …"),
# so _venue_match can't pair them and — when they also share no ticket link (a third source the link
# pass can't reach) — they slip through as duplicates. Two escapes, both behind the same-date guard:
#   • At least ONE side is a placeholder + a STRONG title match (stricter than the normal
#     venue+title bar, since the venue signal is weak or absent). One-sided covers the TBA party's
#     lifecycle: a source names the room (venue reveal) or the promoter re-lists it under the bare
#     series name ("RECOLLECT UNDERGROUND" ⊂ "Recollect Underground: <lineup>") — the Recollect
#     shape, where the TBA row and the venue'd row are the same night's party.
#   • BOTH sides are placeholders + a shared headliner. Sources retitle the same secret party
#     around different names ("SPECIAL GUEST CURRY FURY (B-DAY SET)" vs "Curry Fury Bday Bash,
#     Blerry, …") — past any title-ratio bar — but two secret-venue rows billing the same headliner
#     on one night are the same party. Both-sides-only on purpose: an artist can play a real venue
#     AND be billed at someone's TBA afters the same night, so a one-sided headliner tie is not
#     identity. And because a shared name is the WEAKEST tie, it defers to platform evidence:
#     records carrying DIFFERENT per-event ids on the same platform (two distinct RA pages — the
#     headliner's 7pm doc screening vs his 10pm rave) are two events, no merge. The strong-title
#     arm deliberately skips that veto: promoters delete-and-recreate ticket pages for one party
#     (two posh slugs, same night, near-same title), and a near-identical title outranks id drift.
# Guard on the whole path: a title pair that DISAGREES about being a companion event never merges —
# "X" and "X Afterparty" (or "X Documentary Screening") share a name stem, ≥15-char substring and
# all, but are two gatherings.
_PLACEHOLDER_VENUE = re.compile(
    r"\b(tba|tbd|secret|undisclosed|location|address|rsvp|dm|day of|drops?)\b")
_COMPANION_MARKER = re.compile(
    r"\b(afterparty|after party|afters|afterhours|after hours|pre party|preparty|"
    r"screening|documentary|premiere|listening party)\b")


def _is_placeholder_venue(v: str) -> bool:
    if not _venue_key(v):
        return True                                   # blank / filler-only venue string
    return bool(_PLACEHOLDER_VENUE.search(normalize(v)))


def _strong_title_match(a: dict, b: dict) -> bool:
    """A high-confidence title match: near-identical, or one title is a substantial substring of the
    other (a source appends the lineup — "… Party" vs "… Party ft Rhino, Iguess, …")."""
    ta, tb = normalize(a.get("title", "")), normalize(b.get("title", ""))
    if not ta or not tb:
        return False
    if _ratio(ta, tb) >= 0.85:
        return True
    short, long = sorted((ta, tb), key=len)
    return len(short) >= 15 and short in long


def _companion_disagree(a: dict, b: dict) -> bool:
    """Exactly one title reads as a companion event (afterparty/screening/…) — a shared name
    stem around the same artist or brand, not the same gathering."""
    ta, tb = normalize(a.get("title", "")), normalize(b.get("title", ""))
    return bool(_COMPANION_MARKER.search(ta)) != bool(_COMPANION_MARKER.search(tb))


def _conflicting_link_ids(a: dict, b: dict) -> bool:
    """Both records carry per-event ids on a common platform, and none agree — the platform
    itself files them as two different events (they'd have hit the shared-id path otherwise)."""
    ia, ib = _link_ids(a), _link_ids(b)
    if ia & ib:
        return False
    plat = lambda ids: {i.split(":", 1)[0] for i in ids}
    return bool(plat(ia) & plat(ib))


# ── Shared venue-page identity ─────────────────────────────────────────────────
# The Yaamava / Dane Cook shape: Ticketmaster registers one room under TWO venue records
# ("Yaamava Theater" and "Yaamava Resort & Casino at San Manuel") and lists the same show once
# under each — two resale records with two DIFFERENT Z ids, so no shared per-event id, and venue
# strings too far apart for the fuzzy path. But both records carry TM's own venueBoxOffice URL,
# and it's the SAME page — the platform's statement that both listings sell through one room. A
# shared venue-page URL therefore counts as the VENUE leg of the predicate; title/headliner and
# same-date still required, so a two-night casino run (same box-office URL, both nights) stays two
# rows, and two different shows at that room the same night don't merge. Deliberately NOT vetoed by
# conflicting per-event ids: the TMR double-listing IS two tm ids for one show — that's the bug.
# Three guards keep "shared URL" meaning "same room", because plenty of URLs are shared by rows
# that are genuinely different events:
#   • Only `source: "venue"` links qualify (the tag _resale_links and the venue fetchers use for a
#     box-office/venue page). Editorial roundup URLs name a LIST of events across venues (six 7/18
#     rows at six venues share one discoverlosangeles.com page), promoter tracking links
#     (on.fgtix.com/trk/…) and 19hz's Instagram-profile links are shared by every event the
#     promoter runs — none of them identify a room.
#   • A bare domain doesn't either: scfta.org / ocfair.com-style campus box offices sell for every
#     hall on the grounds, so the URL must carry a real path (yaamava.com/yaamava-theater does).
#     In the current catalog the ONLY pathed venue URL spanning two venue strings is the Yaamava
#     page — this signal is precisely as narrow as intended.
#   • A companion-title pair ("X" / "X Afterparty") never merges on it — same room, two gatherings
#     (the same guard the placeholder path uses).
def _venue_page_urls(ev: dict) -> set:
    out = set()
    for link in (ev.get("links") or []):
        if not isinstance(link, dict) or link.get("source") != "venue":
            continue
        u = str(link.get("url") or "").strip().rstrip("/")
        path = u.split("://", 1)[-1].partition("/")[2]   # everything after the host
        if path:
            out.add(u)
    return out


def _shared_venue_page(a: dict, b: dict) -> bool:
    return bool(_venue_page_urls(a) & _venue_page_urls(b))


def _headliner_tie(a: dict, b: dict) -> bool:
    """Same headliner: lineup[0] agreement, or one side's headliner billed in the other's title.
    Min-length guard so a short name can't land in an unrelated title by accident."""
    ha, hb = _headliner(a), _headliner(b)
    if ha and hb and (ha == hb or _ratio(ha, hb) >= 0.9):
        return True
    ta, tb = normalize(a.get("title", "")), normalize(b.get("title", ""))
    if ha and len(ha) >= 5 and ha in tb:
        return True
    return bool(hb and len(hb) >= 5 and hb in ta)


def is_duplicate(a: dict, b: dict) -> bool:
    """Two records describe the same real-world event."""
    if _link_ids(a) & _link_ids(b):
        return True  # same per-event ticket id — same event, even if venue/title/date drifted

    da, db = parse_event_date(a), parse_event_date(b)
    if da is None or db is None or da != db:
        return False  # conservative: no date match, no merge
    if ((_venue_match(a, b) or (_shared_venue_page(a, b) and not _companion_disagree(a, b)))
            and _title_or_headliner_match(a, b)):
        return True
    pa, pb = _is_placeholder_venue(a.get("venue", "")), _is_placeholder_venue(b.get("venue", ""))
    if (pa or pb) and not _companion_disagree(a, b):
        if _strong_title_match(a, b):
            return True  # TBA/secret placeholder on (at least) one side + strong title = same underground event
        if pa and pb and not _conflicting_link_ids(a, b) and _headliner_tie(a, b):
            return True  # two secret-venue rows billing the same headliner that night = same party
    return _festival_match(a, b)  # cross-source festival (venue + title vary by source)


# TM resale-marketplace URLs (TMR feed, id prefix 'Z') routinely dead-end — the primary sale was
# never on Ticketmaster. They stay in the list (the Z id above is an identity signal) but must
# never be links[0]: the digest and dashboard both surface the first link as THE ticket link.
_TM_RESALE_URL = re.compile(r"ticketmaster\.com/(?:[^?#]*/)?event/Z")


def _is_resale_link(link) -> bool:
    url = link.get("url") if isinstance(link, dict) else link
    return bool(url and _TM_RESALE_URL.search(str(url)))


def _merge_links(a, b):
    seen, out = set(), []
    for link in (a.get("links") or []) + (b.get("links") or []):
        url = link.get("url") if isinstance(link, dict) else link
        if url and url not in seen:
            seen.add(url)
            out.append(link)
    # Stable demote: any working link outranks a TM resale-marketplace URL.
    return [l for l in out if not _is_resale_link(l)] + [l for l in out if _is_resale_link(l)]


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
    """Combine two duplicate records.

    Descriptive fields keep the RICHEST value (longest title/detail, any non-null neighborhood/
    genre/organizer) — completeness across sources. But the VOLATILE fields (price, start time,
    status) track the FRESHER side instead: merge_new feeds the existing catalog record as `a` and
    today's fetch as `b`, so `b` is normally the newer reading — this is what un-freezes a price
    that moved, a door time that shifted, or a sold-out/cancelled flag (the "lineups firm up, prices
    change" staleness gap). But when two long-lived CATALOG rows collapse (a predicate improvement
    healing an old dupe), either side may be the stale one — last_seen decides, tie → `b`, which
    keeps merge_new's behavior exactly (incoming is always stamped today). Status is the one field
    with no non-null fallback: NO status on the fresher-seen side means "still listed as of
    last_seen", so a stale row's `unlisted` flag must not ghost a live event. Lineup prefers the
    longer bill, tie → the fresher side (captures a firm-up or a same-size swap without letting a
    sparse re-fetch clobber a richer known bill)."""
    fresh, stale = (a, b) if (a.get("last_seen") or "") > (b.get("last_seen") or "") else (b, a)
    out = dict(a)
    out["links"] = _merge_links(a, b)
    out["sources"] = _union(a.get("sources"), b.get("sources"))
    out["lineup"] = (fresh.get("lineup")
                     if len(fresh.get("lineup") or []) >= len(stale.get("lineup") or [])
                     else stale.get("lineup"))
    out["detail"] = _richest(a.get("detail"), b.get("detail"))
    out["title"] = _richest(a.get("title"), b.get("title")) or a.get("title")
    out["organizers"] = _richest(a.get("organizers"), b.get("organizers"))
    out["neighborhood"] = a.get("neighborhood") or b.get("neighborhood")
    out["genre"] = a.get("genre") or b.get("genre")  # sparse (only some sources classify); don't lose it if the base lacks one
    out["ra_pick"] = bool(a.get("ra_pick") or b.get("ra_pick"))
    out["afterhours"] = bool(a.get("afterhours") or b.get("afterhours"))
    # Volatile fields: the fresher side's non-null reading wins, so a re-fetch updates them in place.
    out["price"] = fresh.get("price") if fresh.get("price") not in (None, "") else stale.get("price")
    out["start"] = fresh.get("start") if fresh.get("start") not in (None, "") else stale.get("start")
    # Status follows the fresher side WITHOUT fallback: its absence means "listed as of last_seen".
    if fresh.get("status"):
        out["status"] = fresh["status"]
    else:
        out.pop("status", None)
    fs = [x for x in (a.get("first_seen"), b.get("first_seen")) if x]
    ls = [x for x in (a.get("last_seen"), b.get("last_seen")) if x]
    if fs:
        out["first_seen"] = min(fs)
    if ls:
        out["last_seen"] = max(ls)
    return out


def dedupe(events: list) -> tuple:
    """Collapse duplicate records. Returns (merged_events, merge_report).

    First collapses shared-ticket-link duplicates (cross-date, cross-venue), then buckets by date so
    the fuzzy comparison is ~O(n) in practice and greedily clusters within each day. merge_report is
    a list of (kept_title, absorbed_title).
    """
    events, report = _link_premerge(events)
    merged = []
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
