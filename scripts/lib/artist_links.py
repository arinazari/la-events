"""Spotify artist-link resolution — the dashboard's "▶ listen goes straight to the artist" layer.

data/artist_links.json is a committed cache mapping a normalized artist name to a Spotify
artist page:

  { "<norm name>": { "name": "Billed Name",
                     "spotify": "https://open.spotify.com/artist/<id>" | null,
                     "checked": "2026-07-20T06:00:00" } }

refresh() runs inside run_digest (best-effort, creds-gated, capped): new lineup names from
upcoming music-category events plus every scene-graph artist get ONE conservative Spotify
search each (client-credentials — app auth only, no user scope). A result is accepted only
when its name matches ours after normalization (lowercase, trailing parenthetical qualifier
stripped, whitespace collapsed; diacritics ignored for the comparison) — a WRONG direct
link is worse than a search link, so anything fuzzier stays a miss. Misses cache as
spotify:null and re-check after RECHECK_DAYS. build_dashboard folds the hits into the feed
as `artist_links` (norm -> url) for exactly the names its events carry; the dashboard falls
back to a search URL for anything unresolved. SoundCloud has no keyless lookup API, so
SoundCloud stays a search link by design.

norm_name() must stay in lockstep with the dashboard's _artistNorm() (index.html) — the
feed's map keys are looked up client-side with the JS twin of this function.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import unicodedata
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TOKEN_URL = "https://accounts.spotify.com/api/token"
SEARCH_URL = "https://api.spotify.com/v1/search"
RECHECK_DAYS = 45          # a cached miss gets one more look after this long
MAX_NEW_DEFAULT = 250      # per-run lookup cap — the cache converges over a few runs
REQUEST_GAP_S = 0.25       # ~4 req/s, well inside Spotify's tolerance

# Raw catalog categories whose lineup entries are trustworthy as ARTIST names. TM's
# 'arts & theatre' rows put the show title in lineup — never resolve those.
MUSIC_RAW_CATS = {"music", "electronic", "live_music", "live music", "party",
                  "jazz", "club", "dj", "concert"}

_PAREN_TAIL = re.compile(r"\s*\([^)]*\)\s*$")


def norm_name(s) -> str:
    """Cache/feed key — the JS twin is _artistNorm() in dashboard/index.html."""
    s = str(s or "").lower()
    s = _PAREN_TAIL.sub("", s, count=1)
    return re.sub(r"\s+", " ", s).strip()


def _fold(s: str) -> str:
    """Diacritic-insensitive comparison form (comparison only — never a key)."""
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c))


def load(path: Path) -> dict:
    try:
        with Path(path).open() as f:
            c = json.load(f)
        return c if isinstance(c, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save(path: Path, cache: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
                    encoding="utf-8")


def wanted_names(catalog: list, enrichment: dict, today_iso: str) -> dict:
    """{norm: display} for every name worth resolving: upcoming music-category lineup
    entries + every scene-graph artist (those are verified artists whatever the event)."""
    out = {}
    for ev in catalog or []:
        if (ev.get("date") or "") < today_iso:
            continue
        if str(ev.get("category") or "").lower() not in MUSIC_RAW_CATS:
            continue
        lineup = ev.get("lineup")
        for a in (lineup if isinstance(lineup, list) else []):
            k = norm_name(a)
            if k and k not in out:
                out[k] = str(a).strip()
    for ev in (enrichment or {}).get("events", {}).values():
        for an in (ev or {}).get("artist_notes") or []:
            k = norm_name((an or {}).get("name"))
            if k and k not in out:
                out[k] = str(an["name"]).strip()
    for k in (enrichment or {}).get("artists", {}):
        kk = norm_name(k)
        if kk and kk not in out:
            out[kk] = str(k).strip()
    return out


def _get_token(cid: str, secret: str) -> str:
    basic = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    req = Request(TOKEN_URL,
                  data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(),
                  headers={"Authorization": f"Basic {basic}",
                           "Content-Type": "application/x-www-form-urlencoded"})
    with urlopen(req, timeout=20) as r:
        return json.load(r)["access_token"]


def _search_artist(token: str, name: str) -> str | None:
    """The artist-page URL, or None. Accept only a normalized (diacritic-folded) exact
    name match among the top results — never popularity-based guessing."""
    q = urllib.parse.urlencode({"q": name, "type": "artist", "limit": 5})
    req = Request(f"{SEARCH_URL}?{q}", headers={"Authorization": f"Bearer {token}"})
    with urlopen(req, timeout=20) as r:
        items = (json.load(r).get("artists") or {}).get("items") or []
    want = _fold(norm_name(name))
    for it in items:
        got = _fold(norm_name(it.get("name")))
        if got and got == want:
            url = ((it.get("external_urls") or {}).get("spotify")
                   or (f"https://open.spotify.com/artist/{it['id']}" if it.get("id") else None))
            if url:
                return url
    return None


def refresh(repo: Path, max_new: int = MAX_NEW_DEFAULT, now: datetime = None) -> str:
    """Resolve due names into data/artist_links.json. Returns a one-line summary
    (starts with SKIP:/WARN: when degraded) — never raises for network/API trouble."""
    cid = os.environ.get("SPOTIFY_CLIENT_ID")
    secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not cid or not secret:
        return "SKIP: no SPOTIFY_CLIENT_ID/SECRET — direct links unchanged"
    repo = Path(repo)
    now = now or datetime.now()
    cache_path = repo / "data" / "artist_links.json"
    cache = load(cache_path)
    try:
        with (repo / "data" / "catalog.json").open() as f:
            catalog = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        catalog = []
    if not isinstance(catalog, list):
        catalog = []
    enrichment = load(repo / "data" / "enrichment.json")
    wanted = wanted_names(catalog, enrichment, now.date().isoformat())

    recheck_before = (now - timedelta(days=RECHECK_DAYS)).isoformat(timespec="seconds")
    due = []
    for k, display in wanted.items():
        hit = cache.get(k)
        if hit is None:
            due.append((k, display))
        elif not hit.get("spotify") and (hit.get("checked") or "") < recheck_before:
            due.append((k, display))
    if not due:
        hits = sum(1 for v in cache.values() if v.get("spotify"))
        return f"cache current ({hits}/{len(cache)} resolved, nothing due)"

    try:
        token = _get_token(cid, secret)
    except (HTTPError, URLError, OSError, KeyError, json.JSONDecodeError) as ex:
        return f"WARN: token exchange failed ({str(ex)[:80]}) — direct links unchanged"

    resolved = missed = errors = 0
    for k, display in due[:max_new]:
        try:
            url = _search_artist(token, display)
        except (HTTPError, URLError, OSError, json.JSONDecodeError) as ex:
            errors += 1
            if errors >= 5:      # persistent API trouble — stop burning the run's time
                break
            time.sleep(1.0 if not isinstance(ex, HTTPError) or ex.code != 429 else 5.0)
            continue
        cache[k] = {"name": display, "spotify": url,
                    "checked": now.isoformat(timespec="seconds")}
        resolved += 1 if url else 0
        missed += 0 if url else 1
        time.sleep(REQUEST_GAP_S)

    save(cache_path, cache)
    left = max(0, len(due) - max_new)
    return (f"+{resolved} resolved, {missed} misses cached"
            + (f", {errors} errors" if errors else "")
            + (f", {left} still due" if left else "")
            + f" ({sum(1 for v in cache.values() if v.get('spotify'))}/{len(cache)} total)")


def feed_map(cache: dict, events: list) -> dict:
    """{norm: url} for exactly the artists this feed's UPCOMING events carry (lineups +
    enrichment artist notes) — what build_dashboard embeds as `artist_links`."""
    out = {}
    for e in events or []:
        if e.get("is_past"):
            continue
        names = list(e.get("lineup") or [])
        for an in ((e.get("enrichment") or {}).get("artist_notes") or []):
            if isinstance(an, dict) and an.get("name"):
                names.append(an["name"])
        for nm in names:
            k = norm_name(nm)
            if k and k not in out:
                hit = cache.get(k)
                if hit and hit.get("spotify"):
                    out[k] = hit["spotify"]
    return out
