#!/usr/bin/env python3
"""Render an enriched candidate set into the digest — canonical .md + rich .html.

One enriched dataset (data/candidates.json + the scene-researcher enrichment cache),
two renderers:
  - Markdown: the canonical, diffable, committable digest (Day M/D, leveled-up event lines).
  - HTML: an emailable rich version — type chips, ★ relevance, curator notes, hero images
    for the top picks. Self-contained (inline CSS).

Both read the SAME enriched candidates, so they can't drift.

Usage:
  python scripts/render_digest.py                       # data/candidates.json -> /tmp out
  python scripts/render_digest.py --md digest.md --html digest.html
  python scripts/render_digest.py --candidates data/candidates.json --enrichment data/enrichment.json
"""

import argparse
import json
import sys
from datetime import date
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.enrich import load_cache, merge_enrichment  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Type -> (label, accent color) for the chips.
TYPE_STYLE = {
    "electronic": ("Electronic", "#7c5cff"), "party": ("Party", "#e0529c"),
    "live_music": ("Live", "#2f80ed"), "music": ("Live", "#2f80ed"),
    "film": ("Film", "#e09f3e"), "theater": ("Theater", "#2a9d8f"),
    "comedy": ("Comedy", "#9b5de5"), "beer_food": ("Food & Drink", "#c1660b"),
    "art": ("Art", "#577590"), "general": ("Other", "#6b7280"),
}


def stars(rating: int) -> str:
    rating = int(rating or 0)
    return "★" * rating + "☆" * (5 - rating)


def day_label(iso: str) -> str:
    y, m, d = (int(x) for x in iso.split("-"))
    return f"{DOW[date(y, m, d).weekday()]} {m}/{d}"


def fmt_time(t) -> str:
    s = str(t or "")
    if ":" not in s:
        return ""
    try:
        h, m = (int(x) for x in s.split(":")[:2])
    except ValueError:
        return ""
    ap = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d}{ap}" if m else f"{h12}{ap}"


def _type_of(ev: dict):
    e = ev.get("enrichment") or {}
    return (e.get("type") or ev.get("category") or "general").lower()


def _link(ev: dict):
    links = ev.get("links") or []
    if links and isinstance(links[0], dict):
        return links[0].get("url")
    return ev.get("url")


def _gloss(ev: dict) -> str:
    """A short artist gloss for the inline line — first artist note, else sounds-like."""
    e = ev.get("enrichment") or {}
    notes = e.get("artist_notes") or []
    if notes:
        n = notes[0]
        return f"{n.get('name')} — {n.get('note')}" if n.get("note") else n.get("name", "")
    sl = e.get("sounds_like") or []
    return f"sounds like {', '.join(sl[:2])}" if sl else ""


# ── Markdown ────────────────────────────────────────────────────────────────
def event_md(ev: dict) -> str:
    e = ev.get("enrichment") or {}
    label = TYPE_STYLE.get(_type_of(ev), ("", ""))[0]
    title, url = ev.get("title") or "Untitled", _link(ev)
    head = f"[**{title}**]({url})" if url else f"**{title}**"
    meta = " · ".join(x for x in (
        fmt_time(ev.get("start")),
        ev.get("venue") + (f" ({ev['neighborhood']})" if ev.get("neighborhood") else "") if ev.get("venue") else "",
        ev.get("price"),
    ) if x)
    line = f"- `{label}` {stars(ev.get('rating'))} {head} — {meta}"
    note = e.get("curator_note")
    if note:
        line += f"\n  - {note}"
    gloss = _gloss(ev)
    if gloss:
        line += f" *({gloss})*"
    return line


def render_markdown(doc: dict, cands: list) -> str:
    today = doc.get("today", "")
    out = [f"# LA Events — {len(cands)} on-taste picks",
           f"*Generated {doc.get('generated_at','')[:16]} · scored against your taste profile*", ""]

    # Don't-miss: top 6 by score, cross-date.
    dm = cands[:6]
    if dm:
        out.append("## Don't-miss")
        for ev in dm:
            e = ev.get("enrichment") or {}
            why = e.get("curator_note") or _gloss(ev) or ""
            d = day_label(ev["iso_date"]) if ev.get("iso_date") else ""
            url = _link(ev)
            head = f"[{ev.get('title')}]({url})" if url else ev.get("title")
            out.append(f"- {stars(ev.get('rating'))} **{head}** — {d}" + (f" — {why}" if why else ""))
        out.append("")

    # Day-by-day.
    out.append("## Day by day")
    cur = None
    for ev in sorted(cands, key=lambda e: (e.get("iso_date") or "", -e.get("score", 0))):
        iso = ev.get("iso_date")
        if not iso:
            continue
        if iso != cur:
            cur = iso
            out.append(f"\n### {day_label(iso)}")
        out.append(event_md(ev))

    # Footer.
    src = doc.get("sources") or {}
    failed = src.get("failed") or []
    if failed:
        out.append("\n---")
        out.append("*Coverage gaps: " + ", ".join(f"{s} ({why})" for s, why in failed) + "*")
    return "\n".join(out) + "\n"


# ── HTML ──────────────────────────────────────────────────────────────────
CSS = """
*{box-sizing:border-box} body{margin:0;background:#0f1115;color:#e7e9ee;
font:15px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:680px;margin:0 auto;padding:28px 18px}
h1{font-size:24px;margin:0 0 4px} .sub{color:#9aa0ab;font-size:13px;margin:0 0 22px}
h2{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#9aa0ab;margin:26px 0 12px;
border-bottom:1px solid #232733;padding-bottom:6px}
.card{background:#171a21;border:1px solid #232733;border-radius:12px;padding:14px 16px;margin:10px 0}
.card.hero{display:flex;gap:14px} .hero img{width:104px;height:104px;object-fit:cover;border-radius:9px;flex:none}
.top{display:flex;align-items:center;gap:8px;margin-bottom:4px;flex-wrap:wrap}
.chip{font-size:11px;font-weight:700;color:#fff;padding:2px 8px;border-radius:999px}
.stars{color:#ffd166;letter-spacing:1px;font-size:13px} .title{font-weight:700;font-size:16px}
.title a{color:#fff;text-decoration:none} .meta{color:#9aa0ab;font-size:13px;margin:2px 0}
.note{font-size:14px;margin:6px 0 2px} .gloss{color:#aeb4c0;font-size:13px;font-style:italic}
.tix{margin-top:9px} .tix a{display:inline-block;font-size:12px;font-weight:600;color:#cdd2db;
text-decoration:none;border:1px solid #2c3140;border-radius:7px;padding:4px 10px;margin:0 6px 0 0}
.day{font-size:15px;font-weight:700;color:#e7e9ee;margin:22px 0 2px}
.foot{color:#6b7280;font-size:12px;margin-top:26px;border-top:1px solid #232733;padding-top:12px}
"""


def _chip_html(ev):
    label, color = TYPE_STYLE.get(_type_of(ev), ("Other", "#6b7280"))
    return f'<span class="chip" style="background:{color}">{escape(label)}</span>'


def _tix_html(ev):
    links = ev.get("links") or []
    if not links:
        return ""
    btns = "".join(
        f'<a href="{escape(l.get("url",""))}">{escape((l.get("source") or "tickets").title())}</a>'
        for l in links if isinstance(l, dict) and l.get("url"))
    return f'<div class="tix">{btns}</div>'


def event_html(ev: dict, hero=False) -> str:
    e = ev.get("enrichment") or {}
    title = escape(ev.get("title") or "Untitled")
    url = _link(ev)
    title_html = f'<a href="{escape(url)}">{title}</a>' if url else title
    meta = " · ".join(x for x in (
        fmt_time(ev.get("start")),
        escape(ev["venue"]) + (f' ({escape(ev["neighborhood"])})' if ev.get("neighborhood") else "") if ev.get("venue") else "",
        escape(ev["price"]) if ev.get("price") else "",
    ) if x)
    body = [
        f'<div class="top">{_chip_html(ev)}<span class="stars">{stars(ev.get("rating"))}</span></div>',
        f'<div class="title">{title_html}</div>',
        f'<div class="meta">{meta}</div>',
    ]
    if e.get("curator_note"):
        body.append(f'<div class="note">{escape(e["curator_note"])}</div>')
    gloss = _gloss(ev)
    if gloss:
        body.append(f'<div class="gloss">{escape(gloss)}</div>')
    body.append(_tix_html(ev))
    inner = "".join(body)
    img = (e.get("image") or {}).get("url") if hero else None
    if img:
        return f'<div class="card hero"><img src="{escape(img)}" alt=""><div>{inner}</div></div>'
    return f'<div class="card">{inner}</div>'


def render_html(doc: dict, cands: list) -> str:
    parts = [f'<!doctype html><html><head><meta charset="utf-8">'
             f'<meta name="viewport" content="width=device-width,initial-scale=1">'
             f'<style>{CSS}</style></head><body><div class="wrap">',
             f'<h1>LA Events — {len(cands)} on-taste picks</h1>',
             f'<p class="sub">Generated {escape(doc.get("generated_at","")[:16])} · ranked for you</p>']

    dm = cands[:6]
    if dm:
        parts.append("<h2>Don't miss</h2>")
        for ev in dm:
            parts.append(event_html(ev, hero=bool(ev.get("image_wanted"))))

    parts.append("<h2>Day by day</h2>")
    cur = None
    for ev in sorted(cands, key=lambda e: (e.get("iso_date") or "", -e.get("score", 0))):
        iso = ev.get("iso_date")
        if not iso:
            continue
        if iso != cur:
            cur = iso
            parts.append(f'<div class="day">{day_label(iso)}</div>')
        parts.append(event_html(ev))

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
    cache = load_cache(args.enrichment)
    enriched = merge_enrichment(cands, cache)

    Path(args.md).write_text(render_markdown(doc, enriched))
    Path(args.html).write_text(render_html(doc, enriched))
    n_enr = sum(1 for e in enriched if e.get("enrichment"))
    print(f"rendered {len(enriched)} candidates ({n_enr} enriched) -> {args.md} + {args.html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
