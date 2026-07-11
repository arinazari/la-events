"""Stars (Track A4) — the shared reaction log and how it folds onto events.

`data/reactions.jsonl` is an append-only social log the concierge Worker commits to
(POST /react). One JSON object per line:

  {"ts": "2026-07-11", "profile": "<feed-hash>", "name": "Lori",
   "event_key": "<12-hex lib/enrich.event_key>", "kind": "star", "title": "..."}

kinds: star / unstar / hide. Star state is LAST-WINS per (profile, event) — an unstar
(or a hide) clears that person's star. This module is display-side only: the learning
side of a star is the `loved`/`hide` line the Worker also appends to that profile's
data/feedback.<hash>.jsonl, which lib/feedback.py already folds into scoring.

Display names come from profiles.yaml via lib/profiles.hash_names — a reaction whose
hash no longer maps (rotated token) still counts but shows namelessly, so old log lines
can never leak a stale identity mapping into the feeds.
"""

import json
from pathlib import Path

DEFAULT_PATH = "data/reactions.jsonl"
STAR_KINDS = {"star", "unstar", "hide"}


def load_reactions(path) -> list:
    """Read reactions.jsonl -> [reaction dicts]. Blank/`#`/malformed lines are skipped."""
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def star_map(reactions: list) -> dict:
    """{event_key: {profile_hash, ...}} of ACTIVE stars — last state wins per (profile, event);
    `unstar` and `hide` both clear a star."""
    state = {}
    for r in reactions:
        if not isinstance(r, dict):
            continue
        key, prof = r.get("event_key"), r.get("profile")
        kind = (r.get("kind") or "").lower()
        if not key or not prof or kind not in STAR_KINDS:
            continue
        state.setdefault(key, {})[prof] = (kind == "star")
    return {k: {p for p, on in d.items() if on} for k, d in state.items() if any(d.values())}


def stars_for(smap: dict, names: dict, event_key: str) -> list:
    """The display list a feed carries per event: [{name, hash}], name-sorted.
    `names` = lib/profiles.hash_names(manifest); an unmapped hash shows as a short stub."""
    out = [{"name": names.get(h) or ("friend·" + h[:4]), "hash": h}
           for h in (smap.get(event_key) or ())]
    out.sort(key=lambda s: (s["name"].lower(), s["hash"]))
    return out
