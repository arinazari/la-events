"""Stars + hides — the shared reaction log and how it folds onto events.

`data/reactions.jsonl` is an append-only social log the concierge Worker commits to
(POST /react). One JSON object per line:

  {"ts": "2026-07-21", "profile": "<feed-hash>", "name": "Lori",
   "event_key": "<12-hex lib/enrich.event_key>", "kind": "star", "title": "..."}

kinds: star / unstar / hide / unhide. State is LAST-WINS per (profile, event), and star and
hide are MUTUALLY EXCLUSIVE — an event is starred, hidden, or neither, whichever action came
last for that person:
  star   -> starred (and clears any hide)     unstar -> clears the star
  hide   -> hidden ("show less like this")    unhide -> clears the hide
Stars are the SOCIAL signal (everyone sees "★ Lori"); hides are PER-PROFILE (your hide only
affects your own feed). This module is display-side only: the learning side of a star/hide is
the `loved`/`hide`/`unhide` line the Worker also appends to that profile's data/feedback.<hash>.jsonl,
which lib/feedback.py folds into scoring (a hide down-ranks similar events; an unhide reverses it).

Display names come from profiles.yaml via lib/profiles.hash_names — a reaction whose
hash no longer maps still counts but shows namelessly, so old log lines can never leak a
stale identity mapping into the feeds.

(Ported from Track A "A4: stars" — the schema is kept byte-identical so the eventual
Track A merge is a clean overlap, not a conflict.)
"""

import json
from pathlib import Path

DEFAULT_PATH = "data/reactions.jsonl"
# Star + hide share one log and one last-wins fold; star ⟂ hide (see _fold_states).
STAR_KINDS = {"star", "unstar", "hide"}     # kept for back-compat imports
REACTION_KINDS = {"star", "unstar", "hide", "unhide"}


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


def _fold_states(reactions: list) -> dict:
    """{event_key: {profile_hash: {"starred": bool, "hidden": bool}}} — the last-wins fold of the
    log. star and hide are mutually exclusive (each clears the other) so a person is at most one of
    starred/hidden per event. Order matters: reactions are read in append (chronological) order."""
    st = {}
    for r in reactions:
        if not isinstance(r, dict):
            continue
        key, prof = r.get("event_key"), r.get("profile")
        kind = (r.get("kind") or "").lower()
        if not key or not prof or kind not in REACTION_KINDS:
            continue
        cell = st.setdefault(key, {}).setdefault(prof, {"starred": False, "hidden": False})
        if kind == "star":
            cell["starred"], cell["hidden"] = True, False
        elif kind == "unstar":
            cell["starred"] = False
        elif kind == "hide":
            cell["hidden"], cell["starred"] = True, False
        elif kind == "unhide":
            cell["hidden"] = False
    return st


def star_map(reactions: list) -> dict:
    """{event_key: {profile_hash, ...}} of ACTIVE stars — last state wins per (profile, event);
    `unstar` and `hide` both clear a star."""
    st = _fold_states(reactions)
    return {k: {p for p, c in d.items() if c["starred"]}
            for k, d in st.items() if any(c["starred"] for c in d.values())}


def hidden_map(reactions: list) -> dict:
    """{event_key: {profile_hash, ...}} of ACTIVE hides — last state wins per (profile, event);
    `unhide` and `star` both clear a hide. Per-profile by nature (unlike stars, a hide is NOT
    social): a feed applies only ITS OWN profile's hidden set (see build_dashboard --hidden-hash)."""
    st = _fold_states(reactions)
    return {k: {p for p, c in d.items() if c["hidden"]}
            for k, d in st.items() if any(c["hidden"] for c in d.values())}


def is_hidden(hmap: dict, event_key: str, profile_hash: str) -> bool:
    """Has `profile_hash` actively hidden this event? (False when no profile / no log.)"""
    return bool(profile_hash and profile_hash in (hmap.get(event_key) or ()))


def stars_for(smap: dict, names: dict, event_key: str) -> list:
    """The display list a feed carries per event: [{name, hash}], name-sorted.
    `names` = lib/profiles.hash_names(manifest); an unmapped hash shows as a short stub."""
    out = [{"name": names.get(h) or ("friend·" + h[:4]), "hash": h}
           for h in (smap.get(event_key) or ())]
    out.sort(key=lambda s: (s["name"].lower(), s["hash"]))
    return out
