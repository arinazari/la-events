"""Catalog version stamp — the spine of the dashboard's "your customization is stale" check.

A single, deterministic *version* string identifies the current state of the events database
(`data/catalog.json`). `run_digest.py` writes `data/catalog_meta.json` after every fetch, and
`build_dashboard.py` stamps each feed with the version it was BUILT AGAINST. The dashboard then
compares its feed's `catalog_version` to the live `dashboard/catalog_meta.json`: if they differ,
the catalog has been refreshed since that feed was scored, so the user's ranking/digest is stale
and the "Update my ranking & digest" button lights up. When they match, it's disabled.

The version hashes only each event's STABLE identity (venue|date|title), not the volatile
first/last-seen stamps — so a refresh that pulls no genuinely new/changed events leaves the
version (and everyone's "in sync" state) untouched. Adds, drops, reschedules and retitles all
move it. Kept tiny + stdlib-only so the CI deploy jobs need no extra deps.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def _identity(event: dict) -> str:
    return f"{event.get('venue') or ''}|{event.get('date') or ''}|{event.get('title') or ''}"


def version(catalog) -> str:
    """A stable 12-hex digest of the catalog's event set (order-independent)."""
    ids = sorted(_identity(e) for e in (catalog or []))
    return hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()[:12]


def build_meta(catalog) -> dict:
    return {
        "version": version(catalog),
        "count": len(catalog or []),
        # Timezone-AWARE (UTC) so the browser parses the right instant and renders it in the
        # viewer's local zone. A naive datetime.now() has no offset → JS reads it as local → the
        # CI runner's UTC clock shows ~hours in the "future" for a PT viewer.
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def write_meta(path, catalog) -> dict:
    """Write {version, count, fetched_at} for `catalog` to `path`; return it."""
    meta = build_meta(catalog)
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
