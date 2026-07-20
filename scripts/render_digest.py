#!/usr/bin/env python3
"""Render an enriched candidate set into the digest — a canonical Markdown agenda.

One enriched dataset (data/candidates.json + the scene-researcher enrichment cache),
one renderer. Built for "what are my options each day" — a pure day-by-day agenda,
grouped by category within each day, time-first, with high-ranked events flagged as
picks inline (no separate top section).

Usage:
  python scripts/render_digest.py                       # data/candidates.json -> /tmp out
  python scripts/render_digest.py --md digest.md
"""

import argparse
import json
import math
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.enrich import load_cache, merge_enrichment, event_key  # noqa: E402
from lib.series import series_key, is_film, showtimes_url  # noqa: E402
from lib.config import load_taste, load_profile, load_digest_prefs  # noqa: E402
from lib.feedback import merged_affinity  # noqa: E402
from lib.affinity import ambiguous_set  # noqa: E402  (gates title-token artist-bio folds)
from lib.pipeline import score_pool, today_la  # noqa: E402
from lib.assemble import assemble, event_lane, top_picks, TOP_PICKS_N  # noqa: E402
from lib import editor as ED  # noqa: E402
from lib import catalog_meta as CM  # noqa: E402
from posh_token_status import evaluate as posh_evaluate  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
FULLDOW = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]

# Within-day display groups, in priority order — keyed by the slate LANE (lib/assemble.event_lane:
# the editor's lane override wins, else the multi-axis tags), NOT the raw source category. The raw
# category misfiled the core lane: an RA warehouse bill arrives category "Event"/"general" and used
# to land under "Other" while "Electronic & dance" sat near-empty. Groups match on the lane family
# (the part before ":"); the last group is the catch-all.
GROUPS = [
    ("Electronic & dance", ("club",)),           # club:* — underground / afters / day / big room
    ("Live music", ("live-music",)),
    ("Film", ("film",)),
    ("Comedy & stage", ("comedy", "stage")),
    ("Elsewhere", ()),                           # art / market / workshop / community / other …
]

# Sub-lane chips, shown inline so the one dance heading keeps the afters/day/big-room distinction
# (and the one live heading keeps small rooms apart from arena/hall shows).
LANE_CHIP = {"club:afters": "afters", "club:day": "day party", "club:mainstream": "big room",
             "live-music:big": "big venue"}

PICK_MIN_RATING = 5   # rating at/above this gets an "editor's pick" flag inline

# Tier-scaled display: the editor's verdict decides how much page an event gets (build_slate_cands
# maps must-see/great/solid onto rating 5/4/3, so unjudged high-scorers keep the full treatment
# their deterministic stars earn). rating >= FULL gets the two-line entry with a note; rating ==
# COMPACT gets one line with the verdict's why inline; anything below collapses into the day's
# closing "Also:" row — listed, linked, but not given a paragraph it didn't earn.
FULL_MIN_RATING = 4
COMPACT_RATING = 3


def stars(rating) -> str:
    r = int(rating or 0)
    return "★" * r + "☆" * (5 - r)


def _is_pick(ev) -> bool:
    return int(ev.get("rating") or 0) >= PICK_MIN_RATING


def day_label(iso: str) -> str:
    y, m, d = (int(x) for x in iso.split("-"))
    return f"{DOW[date(y, m, d).weekday()]} {m}/{d}"


def day_header(iso: str) -> str:
    y, m, d = (int(x) for x in iso.split("-"))
    return f"{FULLDOW[date(y, m, d).weekday()]} · {MONTHS[m - 1]} {d}"


def fmt_time(t) -> str:
    """Robust to the formats in the wild: 'HH:MM', a full ISO datetime, or an already-
    display string like '5pm' / '5pm-10pm'. Returns '' if there's nothing usable."""
    s = str(t or "").strip()
    if not s:
        return ""
    if "T" in s:                                   # ISO datetime -> HH:MM
        try:
            s = datetime.fromisoformat(s.replace("Z", "+00:00")).strftime("%H:%M")
        except ValueError:
            pass
    if re.search(r"[ap]\.?m", s, re.I):            # already '5pm' / '5pm-10pm'
        return s.replace(" ", "")
    m = re.match(r"^(\d{1,2}):(\d{2})", s)         # 'HH:MM' -> '5pm' / '9:30pm'
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        ap = "am" if h < 12 else "pm"
        h12 = h % 12 or 12
        return f"{h12}:{mn:02d}{ap}" if mn else f"{h12}{ap}"
    return ""


def _lane_of(ev: dict) -> str:
    """Slate lane at render time — delegate to THE resolver (lib/assemble.event_lane) with the
    event's folded verdict, so the digest applies the same off-vocab whitelist and bare-family
    refinement as the slate and the dashboard (a cached bare 'live-music' override on a Greek
    Theatre show must still render the 'big venue' chip)."""
    v = ev.get("verdict") or {}
    return event_lane(ev, {event_key(ev): v} if v.get("lane") else None)


def _group_of(ev: dict) -> str:
    fam = _lane_of(ev).split(":")[0]
    for label, fams in GROUPS:
        if fams and fam in fams:
            return label
    return GROUPS[-1][0]


def _style_of(ev: dict) -> str:
    """full | compact | also — how much page this event gets (see the constants above)."""
    r = int(ev.get("rating") or 0)
    return "full" if r >= FULL_MIN_RATING else ("compact" if r == COMPACT_RATING else "also")


def _link(ev: dict):
    links = ev.get("links") or []
    if links and isinstance(links[0], dict):
        return links[0].get("url")
    return ev.get("url")


FETCH_REF = ""      # the latest catalog fetch date (YYYY-MM-DD); events first_seen/updated on or
                    # after it are flagged 🆕 new / ↻ updated in the digest (set by main from meta)


def freshness_line(meta: dict, today_iso: str) -> str:
    """One human line stating WHEN the catalog was last pulled and WHAT moved — shown in every
    digest so it's always clear what changed or didn't (Q2). Sources the run delta from catalog_meta."""
    ref = (meta.get("fetched_at") or "")[:10] or today_iso[:10]
    when = day_label(ref) if ref else "recently"
    added, updated = int(meta.get("added") or 0), int(meta.get("updated") or 0)
    if added or updated:
        bits = []
        if added:
            bits.append(f"{added} new")
        if updated:
            bits.append(f"{updated} updated")
        return f"Updated {when} · {' · '.join(bits)} since the last pull · 🆕 new · ↻ updated"
    return f"Checked {when} · no new or changed events since the last pull"


def _is_new(ev: dict) -> bool:
    fs = str(ev.get("first_seen") or "")[:10]
    return bool(FETCH_REF and fs and fs >= FETCH_REF)


def _updated_fields(ev: dict) -> list:
    """The volatile fields that moved on the latest pull, for an event that isn't brand-new."""
    ua = str(ev.get("updated_at") or "")[:10]
    if _is_new(ev) or not FETCH_REF or not ua or ua < FETCH_REF:
        return []
    return ev.get("changed_fields") or ["details"]


def _gloss(ev: dict) -> str:
    e = ev.get("enrichment") or {}
    notes = e.get("artist_notes") or []
    if notes:
        n = notes[0]
        return f"{n.get('name')} — {n.get('note')}" if n.get("note") else n.get("name", "")
    sl = e.get("sounds_like") or []
    return f"sounds like {', '.join(sl[:2])}" if sl else ""


def _loc(ev: dict) -> str:
    v = ev.get("venue")
    if not v:
        return ""
    return v + (f", {ev['neighborhood']}" if ev.get("neighborhood") else "")


def fmt_dates(isos: list) -> str:
    labels = [day_label(i) for i in isos if i]
    if not labels:
        return ""
    if len(labels) <= 2:
        return " + ".join(labels)
    return f"{labels[0]} +{len(labels) - 1} more"


def collapse_runs(cands: list) -> list:
    """Collapse the same PROGRAM across dates into one entry carrying all its dates — multi-night
    runs and recurring weeklies show once, not per day. Grouping is lib/series.series_key: films
    group by core title ACROSS theaters (the movie is the program; '(70mm)' at the Vista and the
    same film at the Egyptian are one card, venues teased apart via `_venues`/`_links_by_venue`),
    everything else by title+venue as always. Ungroupable rows (no title) pass through solo."""
    groups, order = {}, []
    for i, ev in enumerate(cands):
        k = series_key(ev) or f"solo:{i}"
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(ev)
    rows = []
    for k in order:
        evs = sorted(groups[k], key=lambda e: -(e.get("score") or 0))
        rep = dict(evs[0])
        rep["_dates"] = sorted({e.get("iso_date") for e in evs if e.get("iso_date")})
        rep["_earliest"] = rep["_dates"][0] if rep["_dates"] else (rep.get("iso_date") or "")
        venues, by_venue = [], {}
        for e in sorted(evs, key=lambda e: e.get("iso_date") or ""):
            v = e.get("venue")
            if v and v not in venues:
                venues.append(v)
                by_venue[v] = _link(e)
        rep["_venues"] = venues
        rep["_links_by_venue"] = by_venue
        rows.append(rep)
    return rows


def _by_day(cands: list) -> dict:
    days = {}
    for ev in collapse_runs(cands):
        iso = ev.get("_earliest")
        if iso:
            days.setdefault(iso, []).append(ev)
    return days


def _day_groups(day_evs: list):
    """Yield (group_label, [events]) in priority order, events best-first within the group."""
    for label, _cats in GROUPS:
        g = [e for e in day_evs if _group_of(e) == label]
        if g:
            g.sort(key=lambda e: (-(e.get("rating") or 0), -(e.get("score") or 0)))
            yield label, g


# ── Markdown ────────────────────────────────────────────────────────────────
def _note_of(ev: dict) -> str:
    """The event's one-line why, richest-first: the curator's take, else the artist gloss,
    else the (blurb-tier) factual description — every full entry gets SOME context."""
    e = ev.get("enrichment") or {}
    return e.get("curator_note") or _gloss(ev) or e.get("description") or ""


def event_md(ev: dict, style: str = "full", note_seen: frozenset = frozenset(),
             lead: str = "time") -> str:
    """One slate entry. `style` is the tier-scaled treatment (_style_of): "full" = headline line
    + an indented note; "compact" = one line with the verdict's why inline. `note_seen` = event
    keys whose full note already ran (the Don't-miss shelf) — suppressed here so the day body
    cross-references instead of repeating the blurb verbatim. `lead` = "time" (within a day
    section) or "date" (cross-day lists like the weekends block)."""
    time = fmt_time(ev.get("start")) or "time TBA"
    dates = ev.get("_dates") or []
    if lead == "date" and (ev.get("iso_date") or dates):
        head_chip = day_label(ev.get("_earliest") or ev["iso_date"])
        n_more = len(dates) - 1
        span = f" (+{n_more} more date{'s' if n_more != 1 else ''})" if n_more > 0 else ""
    else:
        head_chip = time
        span = f" ({fmt_dates(dates)})" if len(dates) > 1 else ""
    pick = "⭐ " if _is_pick(ev) else ""
    fresh = "🆕 " if _is_new(ev) else ""
    upd = _updated_fields(ev)
    upd_note = f"↻ updated ({', '.join(upd)})" if upd else ""
    title, url = ev.get("title") or "Untitled", _link(ev)
    head = f"[{title}]({url})" if url else title
    # A cross-theater film run teases the other venues apart (each linked to ITS tickets), and
    # any film gets the external showtimes search — the LA theaters that aren't fetch sources.
    also_at = ""
    others = [v for v in (ev.get("_venues") or []) if v != ev.get("venue")]
    if others:
        by_venue = ev.get("_links_by_venue") or {}
        also_at = "also at " + ", ".join(
            f"[{v}]({by_venue[v]})" if by_venue.get(v) else v for v in others[:3])
    more = f"[more LA showtimes]({showtimes_url(title)})" if is_film(ev) else ""
    chip = LANE_CHIP.get(_lane_of(ev))
    tail = " · ".join(x for x in (_loc(ev), also_at, chip, ev.get("price"), upd_note, more) if x)
    line = f"- `{head_chip}`{span} {pick}{fresh}**{head}**" + (f" — {tail}" if tail else "")
    if style == "compact":
        why = (ev.get("verdict") or {}).get("why") or ""
        if why and event_key(ev) not in note_seen:
            line += f" — *{why}*"
        return line
    note = _note_of(ev)
    if note and event_key(ev) not in note_seen:
        line += f"  \n  {note}"
    return line


def _also_md(evs: list) -> str:
    """The day's collapsed tail — every below-the-line slate pick, linked but not blurbed."""
    bits = []
    for ev in evs:
        title, url = ev.get("title") or "Untitled", _link(ev)
        head = f"[{title}]({url})" if url else title
        fresh = "🆕 " if _is_new(ev) else ""
        bits.append(f"{fresh}{head}" + (f" ({ev['venue']})" if ev.get("venue") else ""))
    return "- *Also:* " + " · ".join(bits)


def _day_body(day_evs: list, note_seen: frozenset = frozenset()) -> list:
    """One day's entries: lane groups in priority order, tier-scaled within — full entries and
    compact one-liners in place, the rest collapsed into a single closing "Also:" row. A day of
    nothing but tail picks still promotes its best to a real line (no header over an empty day)."""
    styled = {event_key(e): _style_of(e) for e in day_evs}
    if day_evs and all(s == "also" for s in styled.values()):
        top = max(day_evs, key=lambda e: ((e.get("rating") or 0), (e.get("score") or 0)))
        styled[event_key(top)] = "compact"
    out, also = [], []
    for label, evs in _day_groups(day_evs):
        keep = [e for e in evs if styled[event_key(e)] != "also"]
        also += [e for e in evs if styled[event_key(e)] == "also"]
        if keep:
            out.append(f"\n**{label}**")
            out.extend(event_md(e, styled[event_key(e)], note_seen) for e in keep)
    if also:
        out.append("")
        out.append(_also_md(sorted(also, key=lambda e: -(e.get("score") or 0))))
    return out


def _footer_notes(doc: dict) -> list:
    """Degraded-but-not-fatal conditions to disclose in the digest footer. Two kinds, kept
    distinct: event-source COVERAGE gaps (a fetcher failed → missing events) and a RANKING note
    when the Spotify music layer couldn't refresh (picks ranked on the taste profile only).
    Neither blocks the digest — they're surfaced, per the 'degrade gracefully' contract."""
    sources = doc.get("sources") or {}
    notes = []
    failed = sources.get("failed") or []
    if failed:
        notes.append("*Coverage gaps: " + ", ".join(f"{s} ({why})" for s, why in failed) + "*")
    # A source gone dark (frozen last_seen — broken fetcher / lapsed key) is worse than a one-run
    # failure: its events keep showing as if live while silently aging. Disclose it so week-old data
    # never passes for current (the gap that let a Thu show read as Fri all week).
    stale = (doc.get("meta") or {}).get("stale_sources") or []
    if stale:
        notes.append("*⚠️ Stale sources (not refreshed — these events may be out of date): "
                     + ", ".join(f"{s['source']} {s['days']}d ({s['count']} events)" for s in stale) + "*")
    sp = sources.get("spotify")
    if isinstance(sp, dict) and not sp.get("ok"):
        why = (sp.get("note") or "refresh failed").strip()
        notes.append("*Ranking note: Spotify music layer unavailable this run — picks ranked on "
                     "your taste profile only. (" + why + ")*")
    return notes


def render_markdown(doc: dict, cands: list) -> str:
    days = _by_day(cands)
    n = sum(len(v) for v in days.values())
    out = [f"# LA Events — {doc.get('today','')[:10]}",
           f"*{n} picks across {len(days)} days · ⭐ = top pick · ranked for your taste*",
           f"*{freshness_line(doc.get('meta') or {}, doc.get('today',''))}*", ""]
    for iso in sorted(days):
        out.append(f"## {day_header(iso)}")
        out.extend(_day_body(days[iso]))
        out.append("")
    notes = _footer_notes(doc)
    if notes:
        out.append("---")
        out.extend(notes)
    return "\n".join(out) + "\n"


# Editor tier -> the 1-5 rating the renderer already keys picks/order off, so a verdict shows
# through the existing rating-based render without touching the renderers.
TIER_RATING = {"must-see": 5, "great": 4, "solid": 3, "skip": 1}
DEFAULT_PER_DAY = {"weekday": 5, "weekend": 8}


def build_slate_cands(catalog, taste, profile, today, verdicts, *, window=None,
                      per_day=None, mute=None, from_=None, to=None, affinity=None, pool=None) -> list:
    """The digest's event list = the assemble() slate (verdict-ranked, lane-diverse, capped),
    flattened best-first per day. Each pick gets the editor's tier mapped onto `rating` and its
    `adjust` folded into `score`, so the existing rating-based renderer reflects the verdict.

    Pass a pre-scored `pool` (already filtered to score >= 0) to skip the score_pool call — the
    consolidated digest scores the wide window once and date-slices it for the near section, since
    a window-N pool is exactly the window-M pool (M>N) filtered by date (score_pool is a pure date
    filter over identically-scored events)."""
    if pool is None:
        pool = [e for e in score_pool(catalog, taste, profile, today, window_days=window, affinity=affinity)
                if (e.get("score") or 0) >= 0]                   # hard-negatives never make the digest
    slate = assemble(pool, verdicts, per_day=per_day or DEFAULT_PER_DAY, mute=mute)
    cands = []
    for day in slate:
        if (from_ and day["date"] < from_) or (to and day["date"] > to):
            continue
        for ev in day["picks"]:
            v = verdicts.get(event_key(ev))
            if v:
                ev = dict(ev)
                ev["rating"] = TIER_RATING.get(v.get("tier"), ev.get("rating"))
                ev["score"] = (ev.get("score") or 0) + (v.get("adjust") or 0)
                ev["verdict"] = v
            cands.append(ev)
    return cands


# ── Consolidated digest (one doc: don't-miss · next 2 weeks · weekends ahead · around town ·
#    on the radar) ────────────────────────────────────────────────────────────────────────
# Display sizes for the two Track-B4 sections. These cap what's PRINTED, never the ranking —
# the full verdict store ranks everything; Don't-miss is just its top slice pulled forward.
# The Don't-miss size is the shared top-picks policy's (one shelf definition with the
# dashboard front page's hero row — lib/assemble.top_picks).
DONT_MISS_LIMIT = TOP_PICKS_N
AROUND_LIMIT = 12
TONIGHT_TOP = 3      # picks listed per day in Tonight & tomorrow
CHANGES_TOP = 8      # rows per list in What changed
DEFAULT_SECTIONS = ["tonight", "dont_miss", "changes", "day_by_day", "around_town", "radar"]


def _tonight_md(cands: list, today_iso: str) -> list:
    """Tonight & tomorrow — the next-48h actionable slice of the same slate, best-first and
    compact (the day-by-day body carries the full entries; this is the index you act on).
    The tier3:call slot is the voice pass's one-line verdict on what the move actually is —
    including an honest "stay in, Friday's the night"."""
    tod = today_iso[:10]
    tom = (date.fromisoformat(tod) + timedelta(days=1)).isoformat()
    by = {tod: [], tom: []}
    seen = set()
    for ev in cands:
        d0 = ev.get("iso_date")
        rk = series_key(ev) or event_key(ev)    # lib/series: one PROGRAM, films cross-theater
        if d0 in by and rk not in seen:         # a run spanning both nights lists once, today
            by[d0].append(ev)
            seen.add(rk)
    if not (by[tod] or by[tom]):
        return []
    out = ["## Tonight & tomorrow\n", "<!-- tier3:call -->", ""]
    for label, iso in (("Today", tod), ("Tomorrow", tom)):
        evs = sorted(by[iso], key=lambda e: (-(e.get("rating") or 0), -(e.get("score") or 0)))
        for ev in evs[:TONIGHT_TOP]:
            line = event_md(ev, "compact")
            t = fmt_time(ev.get("start")) or "time TBA"
            out.append(line.replace(f"- `{t}`", f"- `{label} {t}`", 1))
    return out + [""]


def _changes_md(cands: list) -> list:
    """What changed on the latest pull, pulled out of the inline 🆕/↻ scatter into one place:
    events new to the slate, and updated ones with the fields that moved. Omitted entirely on
    a no-change day — the freshness line already says so. Runs collapse (collapse_runs — one
    PROGRAM per row, films cross-theater) so a newly announced 4-night residency is one row
    with (+3 more dates), not four."""
    new = collapse_runs([e for e in cands if _is_new(e)])
    upd_pool = [e for e in cands if not _is_new(e) and _updated_fields(e)]
    new_keys = {event_key(e) for e in new}
    upd = [e for e in collapse_runs(upd_pool) if event_key(e) not in new_keys]
    if not (new or upd):
        return []
    out = ["## What changed\n"]
    for intro, rows in (("New to the slate", new), ("Updated", upd)):
        if not rows:
            continue
        out.append(f"\n**{intro}**")
        rows.sort(key=lambda e: (e.get("iso_date") or "9999", -(e.get("score") or 0)))
        for ev in rows[:CHANGES_TOP]:
            out.append(event_md(ev, "compact", lead="date"))
        if len(rows) > CHANGES_TOP:
            out.append(f"- *…plus {len(rows) - CHANGES_TOP} more*")
    return out + [""]


# Deterministic ticket-urgency read on a Don't-miss pick — decision info, not clairvoyance:
# presale tiers in the price string mean the cost of waiting is real; free means RSVP; a TBA
# venue means watch for the address drop. Sell-out *risk* is the editor/voice-pass's call.
_PRESALE_RE = re.compile(r"\b(b4|bb4|before|presale|pre|tier|early\s?bird|adv)\b", re.I)


def _urgency(ev: dict) -> str:
    price = str(ev.get("price") or "")
    if _PRESALE_RE.search(price):
        return "🎟 tiered pricing — buy early"
    if "tba" in str(ev.get("venue") or "").lower():
        return "📍 location TBA — watch for the drop"
    if "free" in price.lower():
        return "free — just RSVP"
    return ""


def _dont_miss_events(cands: list, limit: int = DONT_MISS_LIMIT) -> list:
    """The Don't-miss pick set — ONE policy with the dashboard front page's hero row
    (lib/assemble.top_picks): rank_key order (tier-primary, the editor's call), one night per
    program (lib/series: films group cross-theater, the rest by title+venue — matching the
    day-by-day body's collapse_runs convention), and the shared lane/family diversity caps so
    five club nights can't fill the shelf. Slate cands arrive with the verdict's `adjust`
    already folded into `score` (build_slate_cands), so the map handed to the ranker carries
    tier/lane only — re-adding adjust would double-count it."""
    vmap = {event_key(e): {"tier": e["verdict"].get("tier"), "lane": e["verdict"].get("lane")}
            for e in cands if e.get("verdict")}
    return top_picks(cands, vmap, n=limit, series_of=series_key)


def _dont_miss_md(cands: list, limit: int = DONT_MISS_LIMIT, picked: list = None) -> list:
    """The editorial shelf (Track B4) rendered: each pick dated, priced, urgency-chipped, with
    its why prefilled from the curator note / verdict why; the Tier-3 voice pass may rewrite the
    why text at its slot marker but never the picks themselves (the slate stays deterministic).
    Pass `picked` (a _dont_miss_events result) to reuse an already-computed pick set."""
    if picked is None:
        picked = _dont_miss_events(cands, limit)
    if not picked:
        return []
    out = ["## Don't miss\n"]
    for ev in sorted(picked, key=lambda e: e["iso_date"]):
        d = date.fromisoformat(ev["iso_date"])
        title, url = ev.get("title") or "Untitled", _link(ev)
        head = f"[{title}]({url})" if url else title
        e = ev.get("enrichment") or {}
        why = e.get("curator_note") or (ev.get("verdict") or {}).get("why") or ""
        line = f"- `{DOW[d.weekday()]} {d.month}/{d.day}` **{head}**"
        tail = " · ".join(x for x in (_loc(ev), ev.get("price")) if x)
        if tail:
            line += f" — {tail}"
        urg = _urgency(ev)
        if urg:
            line += f" · *{urg}*"
        out.append(line + f"  \n  {why} <!-- tier3:why {event_key(ev)} -->")
    return out + [""]


def _around_md(rows: list, slate_keys: set, limit: int = AROUND_LIMIT) -> list:
    """Around town (Track B4, the city-pulse): notable around LA this stretch — civic/seasonal
    one-offs, arena bookings, festivals — deliberately NOT taste-ranked ('stay apprised'), and
    de-duped against the slate: this section is what the taste lanes DIDN'T surface."""
    rows = [r for r in rows if r.get("key") not in slate_keys]
    if not rows:
        return []
    out = ["## Around town\n",
           "*Notable around the city — not ranked to taste; here so you stay apprised.*"]
    for r in sorted(rows[:limit], key=lambda r: r["iso_date"]):
        d = date.fromisoformat(r["iso_date"])
        sig = ", ".join(s.replace("tracked:", "") for s in (r.get("signals") or []))
        head = f"[{r['title']}]({r['link']})" if r.get("link") else (r.get("title") or "Untitled")
        loc = " · ".join(x for x in (r.get("venue"), r.get("neighborhood")) if x)
        out.append(f"- `{DOW[d.weekday()]} {d.month}/{d.day}` **{head}**"
                   + (f" — {loc}" if loc else "") + (f"  ·  *{sig}*" if sig else "")
                   + f" <!-- tier3:gloss {r.get('key', '')} -->")
    return out + [""]


WEEKEND_TOP = 4      # picks printed per future weekend; the rest is a count + file pointer


def _weekend_anchor(iso: str) -> str:
    """The Friday anchoring the weekend this date belongs to (Thu–Sun cluster — matches the
    per-weekend files' Friday keying in digests/weekends/)."""
    d = date.fromisoformat(iso)
    return (d + timedelta(days=4 - d.weekday())).isoformat()


def _weekends_md(cands: list) -> list:
    """Weekends ahead, compressed: the slate still ranks everything, but the consolidated doc
    prints each future weekend as its top picks + a count — the full day-by-day for a far
    weekend lives in its own digests/weekends/<Fri>.md (refreshed daily), so duplicating the
    whole list here just made the doc a wall."""
    out = []
    wk = {}
    for ev in collapse_runs(cands):
        iso = ev.get("_earliest")
        if iso:
            wk.setdefault(_weekend_anchor(iso), []).append(ev)
    for anchor in sorted(wk):
        evs = sorted(wk[anchor], key=lambda e: (-(e.get("rating") or 0), -(e.get("score") or 0)))
        d = date.fromisoformat(anchor)
        out.append(f"### Weekend of Fri {d.month}/{d.day}")
        for ev in evs[:WEEKEND_TOP]:
            out.append(event_md(ev, "compact", lead="date"))
        more = len(evs) - WEEKEND_TOP
        if more > 0:
            out.append(f"- *…plus {more} more that weekend — full list: "
                       f"[weekend digest](weekends/{anchor}.md)*")
        out.append("")
    return out


def _radar_md(rows: list, limit: int = 18) -> list:
    if not rows:
        return ["*Nothing flagged on the radar yet.*"]
    out, cur = [], None
    # Select the top N by rank (relevance), then present chronologically so each month heads once.
    for r in sorted(rows[:limit], key=lambda r: r["iso_date"]):
        d = date.fromisoformat(r["iso_date"])
        ym = f"{MONTHS[d.month - 1]} {d.year}"
        if ym != cur:
            cur = ym
            out.append(f"\n**{ym}**")
        sig = ", ".join(s.replace("tracked:", "") for s in (r.get("signals") or []))
        head = f"[{r['title']}]({r['link']})" if r.get("link") else (r.get("title") or "Untitled")
        loc = " · ".join(x for x in (r.get("venue"), r.get("neighborhood")) if x)
        out.append(f"- `{DOW[d.weekday()]} {d.month}/{d.day}` **{head}**"
                   + (f" — {loc}" if loc else "") + (f"  ·  *{sig}*" if sig else "")
                   + f" <!-- tier3:gloss {r.get('key', '')} -->")
    return out


# ── Posh-token expiry banner (proactive half of assisted re-auth) ───────────────────────
# Posh has no token refresh, so POSH_TOKEN lapses ~monthly. When it's within the warn window
# (or already dead) the consolidated digest carries a banner so Ari re-auths before coverage
# silently drops — the routine is deliberately no-email, so this in-digest notice IS the nudge.
# Reuses posh_token_status.evaluate (expiry logic lives in one place). Fires only when the token
# is PRESENT — an unconfigured token shows nothing, so ad-hoc/local renders don't false-alarm.
def posh_notice():
    token = os.environ.get("POSH_TOKEN")
    if not token:
        return None
    status, days, _exp, _msg = posh_evaluate(token, datetime.now(timezone.utc), 5)
    return {"status": status, "days": days} if status in ("warn", "expired") else None


def _warn_days(days) -> int:
    return max(1, math.ceil(days)) if days is not None else 0


def _posh_banner_md(notice: dict) -> str:
    if notice["status"] == "warn":
        d = _warn_days(notice["days"])
        return (f"> ⚠️ **Posh token expires in {d} day{'s' if d != 1 else ''} — re-auth soon.** "
                "Re-capture the `x-jwt-token` from a logged-in posh.vip request, update `POSH_TOKEN`.")
    return ("> ⚠️ **Posh token expired — re-capture it.** Posh events are missing from this digest "
            "until you refresh `POSH_TOKEN` (the `x-jwt-token` on a logged-in posh.vip request).")


def render_consolidated_md(today_iso: str, sections: list, radar: list, doc: dict, notice=None,
                           dont_miss: list = None, around: list = None, order: list = None,
                           weekends: list = None, dm_keys: frozenset = frozenset(),
                           tonight: list = None, changes: list = None) -> str:
    """The consolidated scaffold. Section inclusion + order follow digest.yaml `sections`
    (Track B4 — the renderer finally honors it); day_by_day is the body and is never droppable.
    The `<!-- tier3:… -->` markers are the Tier-3 voice pass's slots: it fills the intro and may
    rewrite a why/gloss, but never adds, removes, or reorders events. The intro slot is wrapped
    in `<!-- take:start/end -->` markers the voice pass must leave in place — build_dashboard
    lifts the filled intro from between them into the feed as `front_page.take` ("The Take"),
    so the page reads the lede structurally instead of parsing markdown conventions.

    `dm_keys` = the Don't-miss picks' event keys: their blurbs run once (in the shelf), and the
    day body shows them starred but note-free instead of repeating the same paragraph verbatim.
    Ops warnings (the Posh-token banner) live in the FOOTER with the other operational notes —
    the top of the doc is editorial, the bottom is ops."""
    out = [f"# LA Events — {today_iso[:10]}",
           "*Your week ahead, the weekends after, and what's on the radar — "
           "ranked for your taste · ⭐ = top pick*",
           f"*{freshness_line(doc.get('meta') or {}, today_iso)}*", "",
           "<!-- take:start -->",
           "<!-- tier3:intro -->",
           "<!-- take:end -->", ""]
    order = [s for s in (order or DEFAULT_SECTIONS) if s in DEFAULT_SECTIONS]
    if "day_by_day" not in order:
        order.append("day_by_day")
    for sec in order:
        if sec == "tonight" and tonight:
            out.extend(tonight)
        elif sec == "dont_miss" and dont_miss:
            out.extend(dont_miss)
        elif sec == "changes" and changes:
            out.extend(changes)
        elif sec == "day_by_day":
            for si, (title, cands) in enumerate(sections):
                days = _by_day(cands)
                if not days:
                    continue
                out.append(f"## {title}\n")
                for iso in sorted(days):
                    out.append(f"### {day_header(iso)}")
                    # Fri/Sat in the near section carry a blueprint slot: the voice pass may
                    # sketch the night (dinner → show → afters, via the night-planner sense)
                    # in one line, or delete the marker. Never a new event — a sequence.
                    if si == 0 and date.fromisoformat(iso).weekday() in (4, 5):
                        out.append(f"<!-- tier3:blueprint {iso} -->")
                    out.extend(_day_body(days[iso], dm_keys))
                    out.append("")
            if weekends:
                out.append("## Weekends ahead\n")
                out.extend(weekends)
        elif sec == "around_town" and around:
            out.extend(around)
        elif sec == "radar":
            out.append("## On the radar\n")
            out.extend(_radar_md(radar))
            out.append("")
    notes = _footer_notes(doc)
    if notice:
        notes = [_posh_banner_md(notice)] + notes
    if notes:
        out.append("---")
        out.extend(notes)
    return "\n".join(out) + "\n"


def main() -> int:
    global FETCH_REF
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="data/catalog.json")
    ap.add_argument("--candidates", default="data/candidates.json",
                    help="read only for the run report / sources footer (optional)")
    ap.add_argument("--enrichment", default="data/enrichment.json")
    ap.add_argument("--verdicts", default=None, help="verdict store (default: data/verdicts/<hash>.json)")
    ap.add_argument("--profile-hash", default=None, help="render a profile's slate (its taste/spotify/verdicts)")
    ap.add_argument("--taste", default="taste.yaml")
    ap.add_argument("--profile", default="profile.yaml")
    ap.add_argument("--digest-prefs", default="digest.yaml",
                    help="format prefs (max_picks_per_day caps per-day density; null = default)")
    ap.add_argument("--consolidated", action="store_true",
                    help="one digest: next 2 weeks (day-by-day) + weekends ahead + on the radar")
    ap.add_argument("--radar", default="data/radar.json", help="radar set for the consolidated digest")
    ap.add_argument("--around", default="data/around_town.json",
                    help="around-town (city-pulse) set for the consolidated digest (build_radar emits it)")
    ap.add_argument("--window", type=int, default=None, help="windowed mode: days from today (default: all upcoming)")
    ap.add_argument("--per-day", type=int, default=None, help="cap per day (default: weekend-aware 8/5)")
    ap.add_argument("--md", default="/tmp/digest.md")
    ap.add_argument("--from", dest="from_", default=None, help="windowed mode: ISO lower bound (inclusive)")
    ap.add_argument("--to", dest="to", default=None, help="windowed mode: ISO upper bound (inclusive)")
    args = ap.parse_args()

    def resolve(p):
        return REPO / p if not Path(p).is_absolute() else Path(p)

    catalog = json.loads(resolve(args.catalog).read_text())
    meta = CM.read_meta(resolve(args.catalog).parent / "catalog_meta.json")
    taste, profile = load_taste(args.taste), load_profile(args.profile)
    # Format prefs: the one structural knob the deterministic renderer honors is the per-day cap
    # (the rest — sections/tone/length/emphasis — shape the LLM digest layer, not this scaffold).
    prefs = load_digest_prefs(args.digest_prefs)
    cap = prefs.get("max_picks_per_day")
    cap = cap if isinstance(cap, int) and cap > 0 else None
    today = today_la()
    # Events first_seen / updated on or after the latest fetch are flagged 🆕 / ↻ in the digest.
    FETCH_REF = (meta.get("fetched_at") or "")[:10] or today.isoformat()
    affinity = merged_affinity(REPO, profile, profile_hash=args.profile_hash)
    vpath = resolve(args.verdicts) if args.verdicts else ED.verdict_path(args.profile_hash)
    verdicts = ED.verdict_map(ED.load_verdicts(vpath))
    cache = load_cache(resolve(args.enrichment))

    # Coverage footer: pull `sources` from candidates.json if present.
    doc = {"today": today.isoformat(), "meta": meta}
    cpath = resolve(args.candidates)
    if cpath.exists():
        try:
            cj = json.loads(cpath.read_text())
            if isinstance(cj, dict) and cj.get("sources"):
                doc["sources"] = cj["sources"]
        except (json.JSONDecodeError, OSError):
            pass

    if args.consolidated:
        # Tier 1: next 14 days, day-by-day. Tier 2: the weekends in days 15–35 (Thu–Sun), lighter.
        # Tier 3: the radar set (festivals/big shows beyond), from build_radar.
        # Score the wide (36-day) window ONCE; the 14-day pool is the same set date-sliced (score_pool
        # is a pure date filter over identically-scored events), so assemble sees identical inputs.
        wide_pool = [e for e in score_pool(catalog, taste, profile, today, window_days=36, affinity=affinity)
                     if (e.get("score") or 0) >= 0]
        end14 = (today + timedelta(days=14)).isoformat()
        near_pool = [e for e in wide_pool if e["iso_date"] <= end14]
        sec1 = build_slate_cands(catalog, taste, profile, today, verdicts, window=14, per_day=cap,
                                 to=(today + timedelta(days=13)).isoformat(), affinity=affinity, pool=near_pool)
        sec2 = build_slate_cands(catalog, taste, profile, today, verdicts, window=36, per_day=6,
                                 from_=(today + timedelta(days=14)).isoformat(),
                                 to=(today + timedelta(days=35)).isoformat(), affinity=affinity, pool=wide_pool)
        sec2 = [c for c in sec2 if date.fromisoformat(c["iso_date"]).weekday() in (3, 4, 5, 6)]
        radar = []
        rpath = resolve(args.radar)
        if rpath.exists():
            try:
                radar = json.loads(rpath.read_text()).get("events", [])
            except (json.JSONDecodeError, OSError):
                pass
        around_rows = []
        apath = resolve(args.around)
        if apath.exists():
            try:
                around_rows = json.loads(apath.read_text()).get("events", [])
            except (json.JSONDecodeError, OSError):
                pass
        amb = ambiguous_set(profile, taste)
        enr1, enr2 = merge_enrichment(sec1, cache, amb), merge_enrichment(sec2, cache, amb)
        sections = [("Next two weeks", enr1)]
        weekends = _weekends_md(enr2)
        slate_keys = {event_key(e) for e in enr1 + enr2}
        dm_events = _dont_miss_events(enr1 + enr2)
        dont_miss = _dont_miss_md(enr1 + enr2, picked=dm_events)
        dm_keys = frozenset(event_key(e) for e in dm_events)
        around = _around_md(around_rows, slate_keys)
        notice = posh_notice()  # proactive Posh-token banner (no-email nudge), if warn/expired
        tonight = _tonight_md(enr1, doc["today"])
        changes = _changes_md(enr1 + enr2)
        Path(args.md).write_text(render_consolidated_md(
            doc["today"], sections, radar, doc, notice,
            dont_miss=dont_miss, around=around, order=prefs.get("sections"),
            weekends=weekends, dm_keys=dm_keys, tonight=tonight, changes=changes))
        print(f"rendered consolidated digest: {max(len(tonight) - 4, 0)} tonight/tomorrow + "
              f"{max(len(dont_miss) - 2, 0)} don't-miss + "
              f"{max(len(changes) - 2, 0)} changed + "
              f"{len(sec1)} + {len(sec2)} picks + {max(len(around) - 3, 0)} around town + "
              f"{min(len(radar), 18)} on the radar -> {args.md}")
        return 0

    # Windowed mode — kept for the per-weekend look-ahead (e.g. next weekend, plugged into the
    # dashboard username click). A single date-bounded slate digest.
    cands = build_slate_cands(catalog, taste, profile, today, verdicts,
                              window=args.window, per_day=args.per_day or cap,
                              from_=args.from_, to=args.to, affinity=affinity)
    enriched = merge_enrichment(cands, cache, ambiguous_set(profile, taste))
    Path(args.md).write_text(render_markdown(doc, enriched))
    n_enr = sum(1 for e in enriched if e.get("enrichment"))
    n_v = sum(1 for e in enriched if e.get("verdict"))
    print(f"rendered {len(enriched)} slate picks ({n_enr} enriched, {n_v} judged) -> {args.md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
