#!/usr/bin/env python3
"""Render an enriched candidate set into the digest — canonical .md + rich .html.

One enriched dataset (data/candidates.json + the scene-researcher enrichment cache),
two renderers. Built for "what are my options each day" — a pure day-by-day agenda,
grouped by category within each day, time-first, with high-ranked events flagged as
picks inline (no separate top section). The HTML is a self-contained emailable page.

Usage:
  python scripts/render_digest.py                       # data/candidates.json -> /tmp out
  python scripts/render_digest.py --md digest.md --html digest.html
"""

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.enrich import load_cache, merge_enrichment, event_key  # noqa: E402
from lib.dedupe import normalize  # noqa: E402
from lib.config import load_taste, load_profile  # noqa: E402
from lib.feedback import merged_affinity  # noqa: E402
from lib.pipeline import score_pool, today_la  # noqa: E402
from lib.assemble import assemble  # noqa: E402
from lib import editor as ED  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
FULLDOW = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]

# Type -> (chip label, accent color).
TYPE_STYLE = {
    "electronic": ("Electronic", "#7c5cff"), "party": ("Party", "#e0529c"),
    "live_music": ("Live", "#2f80ed"), "music": ("Live", "#2f80ed"),
    "film": ("Film", "#e09f3e"), "theater": ("Theater", "#2a9d8f"),
    "comedy": ("Comedy", "#9b5de5"), "beer_food": ("Food & Drink", "#c1660b"),
    "art": ("Art", "#577590"), "general": ("Other", "#6b7280"),
}

# Within-day display groups, in priority order. Leads with the dance lane, then live, film…
GROUPS = [
    ("Electronic & dance", {"electronic", "party"}),
    ("Live music", {"music", "live_music"}),
    ("Film", {"film"}),
    ("Theater", {"theater"}),
    ("Comedy", {"comedy"}),
    ("Food & drink", {"beer_food"}),
    ("Other", {"art", "general"}),
]

# Source -> ticket-tag label (uppercased acronyms; brand-cased otherwise).
SOURCE_LABELS = {
    "ra": "RA", "dice": "DICE", "ticketmaster": "TICKETMASTER", "tm": "TM",
    "eventbrite": "EVENTBRITE", "posh": "POSH", "goldenvoice": "GOLDENVOICE",
    "vidiots": "VIDIOTS", "filmbot": "VIDIOTS", "squarespace": "TICKETS", "ics": "TICKETS",
}

PICK_MIN_RATING = 5   # rating at/above this gets an "editor's pick" flag inline


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


def _type_of(ev: dict) -> str:
    e = ev.get("enrichment") or {}
    return (e.get("type") or ev.get("category") or "general").lower()


def _group_of(ev: dict) -> str:
    t = _type_of(ev)
    for label, cats in GROUPS:
        if t in cats:
            return label
    return "Other"


def _link(ev: dict):
    links = ev.get("links") or []
    if links and isinstance(links[0], dict):
        return links[0].get("url")
    return ev.get("url")


ASSET_PREFIX = ""   # prepended to cached image paths (set by main; for hosted serving)


def _image_src(ev: dict):
    """Prefer the repo-cached copy (hotlink-rot proof) over the remote URL."""
    img = (ev.get("enrichment") or {}).get("image") or {}
    if img.get("cached"):
        return ASSET_PREFIX + img["cached"]
    return img.get("url")


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
    """Collapse the same event across dates (same normalized title+venue) into one entry,
    carrying all its dates — multi-night runs and recurring weeklies show once, not per day."""
    groups, order = {}, []
    for ev in cands:
        k = (normalize(ev.get("title", "")), normalize(ev.get("venue", "")))
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
def event_md(ev: dict) -> str:
    e = ev.get("enrichment") or {}
    time = fmt_time(ev.get("start")) or "time TBA"
    dates = ev.get("_dates") or []
    span = f" ({fmt_dates(dates)})" if len(dates) > 1 else ""
    pick = "⭐ " if _is_pick(ev) else ""
    title, url = ev.get("title") or "Untitled", _link(ev)
    head = f"[{title}]({url})" if url else title
    tail = " · ".join(x for x in (_loc(ev), ev.get("price")) if x)
    line = f"- `{time}`{span} {pick}**{head}**" + (f" — {tail}" if tail else "")
    note = e.get("curator_note") or _gloss(ev)
    if note:
        line += f"  \n  {note}"
    return line


def render_markdown(doc: dict, cands: list) -> str:
    days = _by_day(cands)
    n = sum(len(v) for v in days.values())
    out = [f"# LA Events — {doc.get('today','')[:10]}",
           f"*{n} picks across {len(days)} days · ⭐ = top pick · ranked for your taste*", ""]
    for iso in sorted(days):
        out.append(f"## {day_header(iso)}")
        for label, evs in _day_groups(days[iso]):
            out.append(f"\n**{label}**")
            out.extend(event_md(ev) for ev in evs)
        out.append("")
    failed = (doc.get("sources") or {}).get("failed") or []
    if failed:
        out.append("---")
        out.append("*Coverage gaps: " + ", ".join(f"{s} ({why})" for s, why in failed) + "*")
    return "\n".join(out) + "\n"


# ── HTML ──────────────────────────────────────────────────────────────────
CSS = """
*{box-sizing:border-box}body{margin:0;background:#0e1014;color:#e8eaf0;
font:15px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:660px;margin:0 auto;padding:30px 18px 56px}
h1{font-size:22px;margin:0 0 3px;letter-spacing:-.01em}.sub{color:#878d9b;font-size:13px;margin:0 0 8px}
.day{margin:30px 0 4px;padding-bottom:8px;border-bottom:1px solid #20242e}
.day .dh{font-size:18px;font-weight:700}.day .dd{color:#7b8190;font-size:12px;text-transform:uppercase;letter-spacing:.08em}
.grp{font-size:11px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:#878d9b;margin:16px 0 6px}
.ev{display:flex;gap:13px;padding:11px 0;border-bottom:1px solid #181b22}
.ev.pick{margin:6px -12px;padding:11px 12px;background:#15181f;border:1px solid #2a2f3b;
border-left:3px solid #ffd166;border-radius:10px}
.time{flex:none;width:62px;font-weight:700;font-size:13px;color:#cfd3dc;padding-top:2px}
.time .span{display:block;font-weight:500;color:#7b8190;font-size:11px}
.body{flex:1;min-width:0}.thumb{flex:none;width:78px;height:78px;object-fit:cover;border-radius:8px}
.r1{display:flex;align-items:center;gap:7px;margin-bottom:2px;flex-wrap:wrap}
.chip{font-size:10px;font-weight:700;color:#fff;padding:2px 7px;border-radius:999px}
.picktag{font-size:10px;font-weight:700;color:#ffd166;border:1px solid #5a4d22;border-radius:999px;padding:1px 7px}
.ti{font-weight:650;font-size:16px;letter-spacing:-.01em}.ti a{color:#fff;text-decoration:none}
.meta{color:#878d9b;font-size:13px;margin:1px 0}.note{font-size:13.5px;color:#cbd0da;margin:5px 0 2px}
.gloss{color:#8b94e0;font-style:italic}
.tix{margin-top:7px}.tix a{font-size:10px;font-weight:700;letter-spacing:.04em;color:#aeb4c0;
text-decoration:none;border:1px solid #2a2f3b;border-radius:6px;padding:3px 8px;margin-right:6px}
.foot{color:#5f6573;font-size:12px;margin-top:30px;border-top:1px solid #20242e;padding-top:12px}
"""


def _chip(ev):
    label, color = TYPE_STYLE.get(_type_of(ev), ("Other", "#6b7280"))
    return f'<span class="chip" style="background:{color}">{escape(label)}</span>'


def _tix(ev):
    out = []
    for l in ev.get("links") or []:
        if isinstance(l, dict) and l.get("url"):
            src = (l.get("source") or "").lower()
            out.append(f'<a href="{escape(l["url"])}">{escape(SOURCE_LABELS.get(src, src.upper() or "TICKETS"))}</a>')
    return f'<div class="tix">{"".join(out)}</div>' if out else ""


def event_html(ev: dict) -> str:
    e = ev.get("enrichment") or {}
    pick = _is_pick(ev)
    time = fmt_time(ev.get("start")) or "—"
    dates = ev.get("_dates") or []
    span = f'<span class="span">{escape(fmt_dates(dates))}</span>' if len(dates) > 1 else ""
    url = _link(ev)
    title = escape(ev.get("title") or "Untitled")
    title_html = f'<a href="{escape(url)}">{title}</a>' if url else title
    r1 = [_chip(ev)]
    if pick:
        r1.append('<span class="picktag">⭐ PICK</span>')
    body = [f'<div class="r1">{"".join(r1)}</div>', f'<div class="ti">{title_html}</div>']
    loc = _loc(ev)
    if loc or ev.get("price"):
        body.append(f'<div class="meta">{escape(" · ".join(x for x in (loc, ev.get("price")) if x))}</div>')
    note = e.get("curator_note")
    gloss = _gloss(ev)
    if note or gloss:
        nh = escape(note) if note else ""
        if gloss and not note:
            nh = f'<span class="gloss">{escape(gloss)}</span>'
        elif gloss:
            nh += f' <span class="gloss">— {escape(gloss)}</span>'
        body.append(f'<div class="note">{nh}</div>')
    body.append(_tix(ev))
    img = _image_src(ev) if pick else None
    thumb = f'<img class="thumb" src="{escape(img)}" alt="">' if img else ""
    return (f'<div class="ev{" pick" if pick else ""}">'
            f'<div class="time">{escape(time)}{span}</div>'
            f'<div class="body">{"".join(body)}</div>{thumb}</div>')


def render_html(doc: dict, cands: list) -> str:
    days = _by_day(cands)
    n = sum(len(v) for v in days.values())
    parts = [f'<!doctype html><html><head><meta charset="utf-8">'
             f'<meta name="viewport" content="width=device-width,initial-scale=1">'
             f'<style>{CSS}</style></head><body><div class="wrap">',
             f'<h1>LA Events</h1>',
             f'<p class="sub">{escape(doc.get("today","")[:10])} · {n} picks across {len(days)} days · '
             f'<span style="color:#ffd166">⭐</span> top pick · ranked for your taste</p>']
    for iso in sorted(days):
        parts.append(f'<div class="day"><div class="dh">{escape(day_header(iso))}</div></div>')
        for label, evs in _day_groups(days[iso]):
            parts.append(f'<div class="grp">{escape(label)}</div>')
            parts.extend(event_html(ev) for ev in evs)
    failed = (doc.get("sources") or {}).get("failed") or []
    if failed:
        parts.append('<div class="foot">Coverage gaps: '
                     + escape(", ".join(f"{s} ({why})" for s, why in failed)) + "</div>")
    parts.append("</div></body></html>")
    return "".join(parts)


# Editor tier -> the 1-5 rating the renderer already keys picks/order off, so a verdict shows
# through the existing rating-based render without touching the renderers.
TIER_RATING = {"must-see": 5, "great": 4, "solid": 3, "skip": 1}
DEFAULT_PER_DAY = {"weekday": 5, "weekend": 8}


def build_slate_cands(catalog, taste, profile, today, verdicts, *, window=None,
                      per_day=None, mute=None, from_=None, to=None, affinity=None) -> list:
    """The digest's event list = the assemble() slate (verdict-ranked, lane-diverse, capped),
    flattened best-first per day. Each pick gets the editor's tier mapped onto `rating` and its
    `adjust` folded into `score`, so the existing rating-based renderer reflects the verdict."""
    pool = [e for e in score_pool(catalog, taste, profile, today, window_days=window, affinity=affinity)
            if (e.get("score") or 0) >= 0]                       # hard-negatives never make the digest
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


# ── Consolidated digest (one doc: next 2 weeks · weekends ahead · on the radar) ─────────
def _radar_md(rows: list, limit: int = 18) -> list:
    if not rows:
        return ["*Nothing flagged on the radar yet.*"]
    out, cur = [], None
    for r in rows[:limit]:
        d = date.fromisoformat(r["iso_date"])
        ym = f"{MONTHS[d.month - 1]} {d.year}"
        if ym != cur:
            cur = ym
            out.append(f"\n**{ym}**")
        sig = ", ".join(s.replace("tracked:", "") for s in (r.get("signals") or []))
        head = f"[{r['title']}]({r['link']})" if r.get("link") else (r.get("title") or "Untitled")
        loc = " · ".join(x for x in (r.get("venue"), r.get("neighborhood")) if x)
        out.append(f"- `{DOW[d.weekday()]} {d.month}/{d.day}` **{head}**"
                   + (f" — {loc}" if loc else "") + (f"  ·  *{sig}*" if sig else ""))
    return out


def render_consolidated_md(today_iso: str, sections: list, radar: list, doc: dict) -> str:
    out = [f"# LA Events — {today_iso[:10]}",
           "*Your week ahead, the weekends after, and what's on the radar — "
           "ranked for your taste · ⭐ = top pick*", ""]
    for title, cands in sections:
        days = _by_day(cands)
        if not days:
            continue
        out.append(f"## {title}\n")
        for iso in sorted(days):
            out.append(f"### {day_header(iso)}")
            for label, evs in _day_groups(days[iso]):
                out.append(f"\n**{label}**")
                out.extend(event_md(ev) for ev in evs)
            out.append("")
    out.append("## On the radar\n")
    out.extend(_radar_md(radar))
    out.append("")
    failed = (doc.get("sources") or {}).get("failed") or []
    if failed:
        out.append("---")
        out.append("*Coverage gaps: " + ", ".join(f"{s} ({why})" for s, why in failed) + "*")
    return "\n".join(out) + "\n"


_SEC_H = ('<h2 style="font-size:19px;margin:34px 0 2px;padding-bottom:6px;'
          'border-bottom:2px solid #2a2f3b;color:#fff">{}</h2>')


def _radar_html(rows: list, limit: int = 18) -> str:
    if not rows:
        return '<p class="meta">Nothing flagged on the radar yet.</p>'
    items, cur = [], None
    for r in rows[:limit]:
        d = date.fromisoformat(r["iso_date"])
        ym = f"{MONTHS[d.month - 1]} {d.year}"
        if ym != cur:
            cur = ym
            items.append(f'<div class="grp">{escape(ym)}</div>')
        sig = escape(", ".join(s.replace("tracked:", "") for s in (r.get("signals") or [])))
        head = escape(r.get("title") or "Untitled")
        head_html = f'<a href="{escape(r["link"])}">{head}</a>' if r.get("link") else head
        loc = escape(" · ".join(x for x in (r.get("venue"), r.get("neighborhood")) if x))
        items.append(f'<div class="ev"><div class="time">{escape(DOW[d.weekday()])} {d.month}/{d.day}</div>'
                     f'<div class="body"><div class="ti">{head_html}</div>'
                     + (f'<div class="meta">{loc}</div>' if loc else "")
                     + (f'<div class="note gloss">{sig}</div>' if sig else "")
                     + "</div></div>")
    return "".join(items)


def render_consolidated_html(today_iso: str, sections: list, radar: list, doc: dict) -> str:
    parts = [f'<!doctype html><html><head><meta charset="utf-8">'
             f'<meta name="viewport" content="width=device-width,initial-scale=1">'
             f'<style>{CSS}</style></head><body><div class="wrap">',
             '<h1>LA Events</h1>',
             f'<p class="sub">{escape(today_iso[:10])} · your week ahead, the weekends after, and '
             f'what\'s on the radar · <span style="color:#ffd166">⭐</span> top pick</p>']
    for title, cands in sections:
        days = _by_day(cands)
        if not days:
            continue
        parts.append(_SEC_H.format(escape(title)))
        for iso in sorted(days):
            parts.append(f'<div class="day"><div class="dh">{escape(day_header(iso))}</div></div>')
            for label, evs in _day_groups(days[iso]):
                parts.append(f'<div class="grp">{escape(label)}</div>')
                parts.extend(event_html(ev) for ev in evs)
    parts.append(_SEC_H.format("On the radar"))
    parts.append(_radar_html(radar))
    failed = (doc.get("sources") or {}).get("failed") or []
    if failed:
        parts.append('<div class="foot">Coverage gaps: '
                     + escape(", ".join(f"{s} ({why})" for s, why in failed)) + "</div>")
    parts.append("</div></body></html>")
    return "".join(parts)


def main() -> int:
    global ASSET_PREFIX
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="data/catalog.json")
    ap.add_argument("--candidates", default="data/candidates.json",
                    help="read only for the run report / sources footer (optional)")
    ap.add_argument("--enrichment", default="data/enrichment.json")
    ap.add_argument("--verdicts", default=None, help="verdict store (default: data/verdicts/<hash>.json)")
    ap.add_argument("--profile-hash", default=None, help="render a profile's slate (its taste/spotify/verdicts)")
    ap.add_argument("--taste", default="taste.yaml")
    ap.add_argument("--profile", default="profile.yaml")
    ap.add_argument("--consolidated", action="store_true",
                    help="one digest: next 2 weeks (day-by-day) + weekends ahead + on the radar")
    ap.add_argument("--radar", default="data/radar.json", help="radar set for the consolidated digest")
    ap.add_argument("--window", type=int, default=None, help="windowed mode: days from today (default: all upcoming)")
    ap.add_argument("--per-day", type=int, default=None, help="cap per day (default: weekend-aware 8/5)")
    ap.add_argument("--md", default="/tmp/digest.md")
    ap.add_argument("--html", default="/tmp/digest.html")
    ap.add_argument("--from", dest="from_", default=None, help="windowed mode: ISO lower bound (inclusive)")
    ap.add_argument("--to", dest="to", default=None, help="windowed mode: ISO upper bound (inclusive)")
    ap.add_argument("--asset-prefix", default="", help="prepended to cached image paths (hosted serving)")
    args = ap.parse_args()
    ASSET_PREFIX = args.asset_prefix

    def resolve(p):
        return REPO / p if not Path(p).is_absolute() else Path(p)

    catalog = json.loads(resolve(args.catalog).read_text())
    taste, profile = load_taste(args.taste), load_profile(args.profile)
    today = today_la()
    affinity = merged_affinity(REPO, profile, profile_hash=args.profile_hash)
    vpath = resolve(args.verdicts) if args.verdicts else ED.verdict_path(args.profile_hash)
    verdicts = ED.verdict_map(ED.load_verdicts(vpath))
    cache = load_cache(resolve(args.enrichment))

    # Coverage footer: pull `sources` from candidates.json if present.
    doc = {"today": today.isoformat()}
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
        sec1 = build_slate_cands(catalog, taste, profile, today, verdicts, window=14,
                                 to=(today + timedelta(days=13)).isoformat(), affinity=affinity)
        sec2 = build_slate_cands(catalog, taste, profile, today, verdicts, window=36, per_day=6,
                                 from_=(today + timedelta(days=14)).isoformat(),
                                 to=(today + timedelta(days=35)).isoformat(), affinity=affinity)
        sec2 = [c for c in sec2 if date.fromisoformat(c["iso_date"]).weekday() in (3, 4, 5, 6)]
        radar = []
        rpath = resolve(args.radar)
        if rpath.exists():
            try:
                radar = json.loads(rpath.read_text()).get("events", [])
            except (json.JSONDecodeError, OSError):
                pass
        sections = [("Next two weeks", merge_enrichment(sec1, cache)),
                    ("Weekends ahead", merge_enrichment(sec2, cache))]
        Path(args.md).write_text(render_consolidated_md(doc["today"], sections, radar, doc))
        Path(args.html).write_text(render_consolidated_html(doc["today"], sections, radar, doc))
        print(f"rendered consolidated digest: {len(sec1)} + {len(sec2)} picks + "
              f"{min(len(radar), 18)} on the radar -> {args.md} + {args.html}")
        return 0

    # Windowed mode — kept for the per-weekend look-ahead (e.g. next weekend, plugged into the
    # dashboard username click). A single date-bounded slate digest.
    cands = build_slate_cands(catalog, taste, profile, today, verdicts,
                              window=args.window, per_day=args.per_day,
                              from_=args.from_, to=args.to, affinity=affinity)
    enriched = merge_enrichment(cands, cache)
    Path(args.md).write_text(render_markdown(doc, enriched))
    Path(args.html).write_text(render_html(doc, enriched))
    n_enr = sum(1 for e in enriched if e.get("enrichment"))
    n_v = sum(1 for e in enriched if e.get("verdict"))
    print(f"rendered {len(enriched)} slate picks ({n_enr} enriched, {n_v} judged) -> {args.md} + {args.html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
