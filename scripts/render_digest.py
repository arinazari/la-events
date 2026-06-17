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
from datetime import date, datetime
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.enrich import load_cache, merge_enrichment  # noqa: E402
from lib.dedupe import normalize  # noqa: E402

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
    img = (e.get("image") or {}).get("url") if pick else None
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default="data/candidates.json")
    ap.add_argument("--enrichment", default="data/enrichment.json")
    ap.add_argument("--md", default="/tmp/digest.md")
    ap.add_argument("--html", default="/tmp/digest.html")
    args = ap.parse_args()

    cpath = REPO / args.candidates if not Path(args.candidates).is_absolute() else Path(args.candidates)
    doc = json.loads(cpath.read_text())
    cands = doc.get("candidates", doc) if isinstance(doc, dict) else doc
    enriched = merge_enrichment(cands, load_cache(args.enrichment))

    Path(args.md).write_text(render_markdown(doc, enriched))
    Path(args.html).write_text(render_html(doc, enriched))
    n_enr = sum(1 for e in enriched if e.get("enrichment"))
    print(f"rendered {len(enriched)} candidates ({n_enr} enriched) -> {args.md} + {args.html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
