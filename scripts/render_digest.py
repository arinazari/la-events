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
from lib.dedupe import normalize  # noqa: E402
from lib.config import load_taste, load_profile  # noqa: E402
from lib.feedback import merged_affinity  # noqa: E402
from lib.pipeline import score_pool, today_la  # noqa: E402
from lib.assemble import assemble  # noqa: E402
from lib import editor as ED  # noqa: E402
from lib import catalog_meta as CM  # noqa: E402
from posh_token_status import evaluate as posh_evaluate  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
FULLDOW = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]

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
    fresh = "🆕 " if _is_new(ev) else ""
    upd = _updated_fields(ev)
    upd_note = f"↻ updated ({', '.join(upd)})" if upd else ""
    title, url = ev.get("title") or "Untitled", _link(ev)
    head = f"[{title}]({url})" if url else title
    tail = " · ".join(x for x in (_loc(ev), ev.get("price"), upd_note) if x)
    line = f"- `{time}`{span} {pick}{fresh}**{head}**" + (f" — {tail}" if tail else "")
    note = e.get("curator_note") or _gloss(ev)
    if note:
        line += f"  \n  {note}"
    return line


def render_markdown(doc: dict, cands: list) -> str:
    days = _by_day(cands)
    n = sum(len(v) for v in days.values())
    out = [f"# LA Events — {doc.get('today','')[:10]}",
           f"*{n} picks across {len(days)} days · ⭐ = top pick · ranked for your taste*",
           f"*{freshness_line(doc.get('meta') or {}, doc.get('today',''))}*", ""]
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
                   + (f" — {loc}" if loc else "") + (f"  ·  *{sig}*" if sig else ""))
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


def render_consolidated_md(today_iso: str, sections: list, radar: list, doc: dict, notice=None) -> str:
    out = [f"# LA Events — {today_iso[:10]}",
           "*Your week ahead, the weekends after, and what's on the radar — "
           "ranked for your taste · ⭐ = top pick*",
           f"*{freshness_line(doc.get('meta') or {}, today_iso)}*", ""]
    if notice:
        out += [_posh_banner_md(notice), ""]
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
    ap.add_argument("--consolidated", action="store_true",
                    help="one digest: next 2 weeks (day-by-day) + weekends ahead + on the radar")
    ap.add_argument("--radar", default="data/radar.json", help="radar set for the consolidated digest")
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
        notice = posh_notice()  # proactive Posh-token banner (no-email nudge), if warn/expired
        Path(args.md).write_text(render_consolidated_md(doc["today"], sections, radar, doc, notice))
        print(f"rendered consolidated digest: {len(sec1)} + {len(sec2)} picks + "
              f"{min(len(radar), 18)} on the radar -> {args.md}")
        return 0

    # Windowed mode — kept for the per-weekend look-ahead (e.g. next weekend, plugged into the
    # dashboard username click). A single date-bounded slate digest.
    cands = build_slate_cands(catalog, taste, profile, today, verdicts,
                              window=args.window, per_day=args.per_day,
                              from_=args.from_, to=args.to, affinity=affinity)
    enriched = merge_enrichment(cands, cache)
    Path(args.md).write_text(render_markdown(doc, enriched))
    n_enr = sum(1 for e in enriched if e.get("enrichment"))
    n_v = sum(1 for e in enriched if e.get("verdict"))
    print(f"rendered {len(enriched)} slate picks ({n_enr} enriched, {n_v} judged) -> {args.md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
