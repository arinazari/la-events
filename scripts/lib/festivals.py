"""festivals.yaml — the standing festival watch-list, as a real data path.

The yaml was standing memory that NOTHING read (2026-07-25 audit): build_radar derives
radar purely from catalog signals, so out-of-catalog watch-list items (Portola, CRSSD,
Coachella '27) surfaced nowhere — not the dashboard, and not the digest (the voice-pass
"fold it in" instruction contributed zero lines). This module is the one loader both
consumers share:

  - build_dashboard -> front_page.festivals    (the dedicated Festivals view: everything
    non-past, dated first — the view IS the watch-list)
  - build_radar -> radar.json `watchlist`      (TIMELY items only — the yaml header's
    relevance gate: surface in the digest only when there's a live ticket story)
    -> render_digest "On the radar" watch-list block

Entries keep the yaml's own vocabulary: status announced|on_sale|lineup_pending|past|
annual_watch|dormant. `when` can be a bare ISO date (PyYAML parses it as a date object —
str() normalizes), a range ("2026-09-26..27"), or free text ("typically late May").

Every row carries a `scope` — "local" (Greater LA / sleep-at-home) or "travel" (worth the
trip: an overnight or a flight) — so the front page can split the watch-list into its two
real decisions: "block the date" vs "plan the trip". An explicit `scope:` in the yaml wins;
otherwise a location heuristic decides (Greater-LA markers -> local, everything else travel
— unknown-far is the safe default for a watch-list that skews destination).
"""

import re
from pathlib import Path

from .config import load_yaml

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

# Greater-LA location markers — "local" means you sleep at home (LA + OC). San Diego and
# Indio are drives but overnight-shaped, so they classify travel; override with scope: in
# the yaml when the heuristic gets one wrong.
_LOCAL_MARKERS = ("los angeles", "hollywood", "dtla", "downtown la", "echo park",
                  "silver lake", "highland park", "glendale", "burbank", "pasadena",
                  "culver city", "santa monica", "venice", "inglewood", "el segundo",
                  "long beach", "san pedro", "pomona", "malibu", "torrance",
                  "orange county", "anaheim", "irvine", "costa mesa", "santa ana",
                  "(oc", " oc)", "la county")
_LA_WORD_RE = re.compile(r"(?<![A-Za-z])LA(?![A-Za-z])")   # bare 'LA', not 'Atlanta'/'gala'

# Statuses with a live ticket story — what the DIGEST surfaces. annual_watch/dormant stay
# in the file (standing memory) and in the dashboard view, but out of the digest until a
# refresh pass flips them.
TIMELY_STATUSES = ("on_sale", "announced", "lineup_pending")


def festival_scope(location: str, explicit=None) -> str:
    """'local' | 'travel' for a watch-list row: explicit yaml value wins, else the
    Greater-LA marker heuristic (unknown/far -> travel)."""
    if explicit:
        s = str(explicit).strip().lower()
        if s in ("local", "travel"):
            return s
    loc = str(location or "")
    low = loc.lower()
    if any(m in low for m in _LOCAL_MARKERS) or _LA_WORD_RE.search(loc):
        return "local"
    return "travel"


def load_festivals(path) -> list:
    """festivals.yaml -> watch-list rows. [] when the file is absent/empty. Filters
    status:past; sorts dated items first (by first parseable date), undated last."""
    p = Path(path)
    if not p.exists():
        return []
    data = load_yaml(p) or {}
    out = []
    for f in (data.get("festivals") or []):
        if not isinstance(f, dict) or not f.get("name"):
            continue
        status = str(f.get("status") or "").strip().lower() or None
        if status == "past":
            continue
        when = str(f.get("when") or "").strip()
        m = _DATE_RE.search(when)
        location = str(f.get("location") or "").strip()
        out.append({
            "name": str(f.get("name")).strip(),
            "location": location,
            "when": when,
            "when_pretty": pretty_when(when),
            "status": status,
            "scope": festival_scope(location, f.get("scope")),
            "tickets": str(f.get("tickets") or "").strip() or None,
            "why": " ".join(str(f.get("why") or "").split()),
            "first_date": m.group(0) if m else None,
        })
    out.sort(key=lambda x: (x["first_date"] is None, x["first_date"] or "", x["name"]))
    return out


def timely(fests: list) -> list:
    """The digest-facing subset: items with a live ticket story (see TIMELY_STATUSES)."""
    return [f for f in fests if (f.get("status") or "") in TIMELY_STATUSES]


def pretty_when(when) -> str:
    """ISO dates in a `when` string -> the digest's no-leading-zero M/D convention:
    '2026-09-26..27' -> '9/26–27' (a bare '..09' tail drops its zero too); free text
    passes through."""
    s = _DATE_RE.sub(lambda m: f"{int(m.group(0)[5:7])}/{int(m.group(0)[8:10])}",
                     str(when or ""))
    s = re.sub(r"\.\.(\d{1,2})\b", lambda m: "–" + str(int(m.group(1))), s)
    return s.replace("..", "–")
