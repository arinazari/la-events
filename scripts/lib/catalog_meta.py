"""Catalog version stamps — the spine of the dashboard's "your customization is stale" check
AND the digest's "what changed, and when" line.

Two deterministic *version* strings identify the state of the events database (`data/catalog.json`):

  version          — hashes each event's STABLE IDENTITY (venue|date|title). Moves on adds,
                     drops, reschedules and retitles ONLY. The "is this a different set of
                     events" key (kept for back-compat with feeds stamped before content_version).
  content_version  — hashes identity PLUS the volatile fields (price | start time | lineup |
                     status). Moves on all of the above AND when a known event's lineup firms up,
                     its price changes, its door time shifts, or it sells out / is cancelled.

`run_digest.py` writes `data/catalog_meta.json` after every fetch; `build_dashboard.py` stamps each
feed with the versions it was BUILT AGAINST and republishes the meta. The dashboard compares its
feed's `catalog_content_version` to the live meta: if they differ, the catalog moved since that feed
was scored, so the ranking/digest is stale and the "Update" button lights (Q1: by default any real
change — incl. price/lineup/time — counts; the identity `version` is kept so we can still tell a
brand-new event from a detail change). When they match, it's disabled.

The meta also carries this run's DELTA (`added` / `updated` counts + a bounded `changes` list of what
moved) so the digest can state "N new, M updated since <when>" and the dashboard can show what changed.
Kept tiny + stdlib-only so the CI deploy jobs need no extra deps.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

# The mutable fields whose change should register as "the catalog updated" even when the event's
# identity (venue/date/title) is unchanged — the "lineups firm up / prices move" freshness gap.
VOLATILE_FIELDS = ("price", "start", "status", "lineup")


def _identity(event: dict) -> str:
    return f"{event.get('venue') or ''}|{event.get('date') or ''}|{event.get('title') or ''}"


def _lineup_sig(event: dict) -> str:
    """Order-insensitive lineup signature — a reorder isn't a change; a swap/add/drop is."""
    lineup = event.get("lineup") or []
    if not isinstance(lineup, list):
        lineup = [str(lineup)]
    return ",".join(sorted(str(a).strip().lower() for a in lineup if str(a).strip()))


def _content_identity(event: dict) -> str:
    parts = [_identity(event)]
    for f in VOLATILE_FIELDS:
        parts.append(_lineup_sig(event) if f == "lineup" else str(event.get(f) or ""))
    return "|".join(parts)


def _digest_of(items) -> str:
    return hashlib.sha256("\n".join(sorted(items)).encode("utf-8")).hexdigest()[:12]


def version(catalog) -> str:
    """A stable 12-hex digest of the catalog's event IDENTITIES (order-independent)."""
    return _digest_of(_identity(e) for e in (catalog or []))


def content_version(catalog) -> str:
    """A stable 12-hex digest over identity + the volatile fields (price/time/lineup/status)."""
    return _digest_of(_content_identity(e) for e in (catalog or []))


def build_meta(catalog, delta: dict = None, stale: list = None) -> dict:
    meta = {
        "version": version(catalog),
        "content_version": content_version(catalog),
        "count": len(catalog or []),
        # Timezone-AWARE (UTC) so the browser parses the right instant and renders it in the
        # viewer's local zone. A naive datetime.now() has no offset → JS reads it as local → the
        # CI runner's UTC clock shows ~hours in the "future" for a PT viewer.
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if delta:
        # This run's change summary (since the previous catalog) — drives the digest freshness line
        # and the dashboard "what changed" readout. Counts always; a bounded sample of what moved.
        meta["added"] = int(delta.get("added") or 0)
        meta["updated"] = int(delta.get("updated") or 0)
        if delta.get("changes"):
            meta["changes"] = delta["changes"][:25]
    if stale:
        # Sources that have gone dark (newest last_seen frozen N days back) — so the dashboard/digest
        # can warn that e.g. Ticketmaster events may be stale instead of presenting week-old data as live.
        meta["stale_sources"] = [{"source": s, "days": d, "count": n} for s, d, n in stale]
    return meta


def write_meta(path, catalog, delta: dict = None, stale: list = None) -> dict:
    """Write {version, content_version, count, fetched_at, [added/updated/changes/stale_sources]}; return it."""
    meta = build_meta(catalog, delta, stale)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def read_meta(path) -> dict:
    """Read a catalog_meta.json; {} if absent/malformed (never raises)."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
