#!/usr/bin/env python3
"""One-off catalog repair: fix dead Ticketmaster resale-marketplace links.

The Discovery API carries events whose primary sale is NOT on Ticketmaster (Hollywood Bowl /
LA Phil, Segerstrom, Greek, …) as resale-feed (TMR) records whose constructed
ticketmaster.com/event/Z… URL routinely dead-ends. fetch_ticketmaster now prefers the record's
venueBoxOffice outlet at fetch time; this script repairs the rows already in the catalog:

  • every event's links are re-ordered so a working link outranks any resale URL
    (same rule as lib.dedupe._merge_links — digest + dashboard surface links[0]);
  • events whose ONLY links are resale URLs get the real point of sale looked up from the
    Discovery detail endpoint (outlets type "venueBoxOffice") and prepended as source "venue".

Usage:
    export TM_API_KEY=...
    python scripts/repair_resale_links.py [--catalog data/catalog.json] [--dry-run]

Safe to re-run (idempotent); lookups stay under the 5 req/s limit. Without TM_API_KEY it still
does the re-ordering pass and just skips the lookups.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.dedupe import _is_resale_link  # noqa: E402

_TM_EVENT_ID = re.compile(r"ticketmaster\.com/(?:[^?#]*/)?event/(Z[0-9A-Za-z_-]+)")
DETAIL = "https://app.ticketmaster.com/discovery/v2/events/{id}.json?apikey={key}"


def box_office_url(event_id: str, key: str):
    """The venueBoxOffice outlet URL for a Discovery event, or None."""
    try:
        with urlopen(DETAIL.format(id=event_id, key=key), timeout=20) as resp:
            data = json.load(resp)
    except Exception:  # noqa: BLE001 — a vanished/expired event just stays unrepaired
        return None
    return next((o.get("url") for o in (data.get("outlets") or [])
                 if o.get("type") == "venueBoxOffice" and o.get("url")), None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="data/catalog.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    key = os.environ.get("TM_API_KEY")
    if not key:
        print("WARN: TM_API_KEY not set — re-ordering links only, skipping box-office lookups",
              file=sys.stderr)

    path = Path(args.catalog)
    events = json.loads(path.read_text())

    reordered = looked_up = repaired = unrepaired = 0
    for ev in events:
        links = ev.get("links") or []
        resale = [l for l in links if _is_resale_link(l)]
        if not resale:
            continue
        alive = [l for l in links if not _is_resale_link(l)]
        if not alive and key:
            m = _TM_EVENT_ID.search(str(resale[0].get("url") or ""))
            if m:
                looked_up += 1
                box = box_office_url(m.group(1), key)
                time.sleep(0.25)  # 5 req/s cap
                if box:
                    alive = [{"source": "venue", "url": box}]
                    repaired += 1
                else:
                    unrepaired += 1
        new_links = alive + resale
        if new_links != links:
            ev["links"] = new_links
            reordered += 1

    print(f"{reordered} events re-linked ({looked_up} looked up: "
          f"{repaired} box-office URLs found, {unrepaired} left as-is)")
    if args.dry_run:
        print("dry run — catalog not written")
        return 0
    path.write_text(json.dumps(events, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
