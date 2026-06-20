"""Build a valid iCalendar (.ics) from a list of stops — so a night-planner itinerary
(dinner -> show -> afters) lands on the calendar in one file, not copy-pasted.

Pure + tested; the CLI (scripts/make_ics.py) does the I/O and end-time inference. Times are
**floating local** (no TZ suffix) — interpreted in the user's calendar TZ, which is LA — matching
the dashboard's per-event export. RFC 5545: CRLF lines, TEXT escaping, 75-octet line folding,
UTC DTSTAMP.

  build_ics(events, calname="...") -> str
  event: {summary, start, end?, location?, url?, description?, uid?}
         start/end are "YYYY-MM-DDTHH:MM[:SS]" (a space instead of 'T' is fine).
"""

import hashlib
from datetime import datetime, timezone


def _esc(s: str) -> str:
    """Escape a TEXT value per RFC 5545 (backslash, semicolon, comma, newlines)."""
    s = str(s or "")
    s = s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return s.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def _fold(line: str) -> str:
    """Fold a content line to <=75 octets with CRLF + a leading space (RFC 5545)."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    out, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        # 75-octet limit; continuation lines start with a space, so cap them at 74 + the space.
        if len(cur) + len(b) > (75 if not out else 74):
            out.append(cur)
            cur = b
        else:
            cur += b
    out.append(cur)
    return "\r\n ".join(seg.decode("utf-8") for seg in out)


def _dt(value) -> str:
    """'YYYY-MM-DDTHH:MM[:SS]' (or with a space) -> ICS basic 'YYYYMMDDTHHMMSS' (floating local)."""
    if not value:
        return ""
    raw = str(value).strip().replace(" ", "T")
    if raw.endswith("Z"):
        raw = raw[:-1]
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(raw[:19] if len(raw) >= 19 else raw, fmt).strftime("%Y%m%dT%H%M%S")
        except ValueError:
            continue
    return ""


def build_ics(events, calname: str = "LA night", prodid: str = "-//la-events//night-planner//EN") -> str:
    """Render events to an .ics string. Events missing a parseable `start` are skipped."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{prodid}", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    if calname:
        lines.append(f"X-WR-CALNAME:{_esc(calname)}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for ev in events or []:
        start = _dt(ev.get("start"))
        if not start:
            continue
        end = _dt(ev.get("end"))
        uid = ev.get("uid") or (hashlib.sha1(f"{ev.get('summary','')}|{start}".encode("utf-8")).hexdigest()[:16] + "@la-events")
        lines += ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}", f"DTSTART:{start}"]
        if end:
            lines.append(f"DTEND:{end}")
        lines.append(f"SUMMARY:{_esc(ev.get('summary', ''))}")
        if ev.get("location"):
            lines.append(f"LOCATION:{_esc(ev['location'])}")
        desc = ev.get("description") or ""
        if ev.get("url"):
            desc = (desc + ("\n" if desc else "") + ev["url"]).strip()
        if desc:
            lines.append(f"DESCRIPTION:{_esc(desc)}")
        if ev.get("url"):
            lines.append(f"URL:{ev['url']}")   # URI value — not TEXT-escaped
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(ln) for ln in lines) + "\r\n"
