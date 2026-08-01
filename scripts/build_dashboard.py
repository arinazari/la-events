#!/usr/bin/env python3
"""Build the dashboard data feed from the catalog + taste profile.

Reads a catalog JSON (deduped event records), taste.yaml, profile.yaml, and
sources.yaml, scores each event against the taste profile, folds in any cached
scene-researcher enrichment, and writes dashboard/data.json — the static feed the
dashboard (dashboard/index.html) loads. Scoring is imported from scripts/lib/scoring.py
— the SAME module the digest/run_digest.py use, so the dashboard's "recommended for
you" rating can't drift from the digest's ranking.

The feed has three parts:
  - events[]   — every catalog event, scored (+ rating/reasons), with enrichment folded
                 in when data/enrichment.json has a hit for it (curator note, type/
                 subgenre tags, artist notes).
  - config     — a structured snapshot of the editable knobs (taste.yaml content,
                 profile.yaml scoring mechanics, sources.yaml registry) so the
                 dashboard's Settings view can render current state and stage edits.
  - metadata   — generated_at, counts, the neighborhood/category facets for filters.

Usage:
    python scripts/build_dashboard.py                      # from data/catalog.json
    python scripts/build_dashboard.py -i data/sample-catalog.json   # demo data
    python scripts/build_dashboard.py -o dashboard/data.json

The dashboard is a pure viewer: it does NOT score. Re-run this after every digest
(or whenever the catalog changes) to refresh what the dashboard shows.
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Make `lib` importable regardless of cwd (scripts/ on sys.path).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.config import load_yaml  # noqa: E402
from lib.scoring import score_event, score_to_rating, parse_event_date  # noqa: E402
from lib.feedback import merged_affinity  # noqa: E402
from lib import affinity as AF  # noqa: E402  (ambiguous_set gates title-token bio folds)
from lib.enrich import load_cache, merge_enrichment, event_key  # noqa: E402
from lib.reactions import load_reactions, star_map, stars_for  # noqa: E402  (stars — the social fold)
from lib.profiles import hash_names  # noqa: E402
from lib import editor as ED  # noqa: E402
from lib.assemble import rank_key, event_lane, top_picks, TOP_PICKS_LANE_CAP  # noqa: E402
from lib.series import group_series, series_summary, is_film, showtimes_url  # noqa: E402
from lib.festivals import load_festivals  # noqa: E402  (festivals.yaml -> front_page.festivals)
from lib.dedupe import _fest_core, _FEST_SIGNAL, normalize as _norm  # noqa: E402  (festival rollup)
from lib.tagging import VOCAB as TAG_VOCAB  # noqa: E402
from lib import catalog_meta as CM  # noqa: E402
from lib.pipeline import today_la  # noqa: E402
from lib import artist_links as ALINK  # noqa: E402  (direct ▶ listen links for the feed)

REPO = Path(__file__).resolve().parent.parent

# Enrichment fields worth surfacing on the dashboard (scene-researcher output). The
# cache also stores id/enriched_at/confidence — internal plumbing the viewer ignores.
ENRICH_FIELDS = (
    "type", "subgenres", "label_orbit", "energy", "setting", "sounds_like",
    "artist_notes", "curator_note", "description",
)


def music_block(affinity: dict) -> dict:
    """A compact self-report of the music layer this feed was actually scored against, so the
    dashboard can tell a connected-but-not-yet-applied Spotify (a stale ranking, or a failed
    per-profile sync) from a live one. `layer` is none / feedback / spotify / spotify+feedback;
    the counts are what fed the scorer. Purely additive — older viewers ignore it."""
    if not affinity:
        return {"layer": "none", "artists": 0, "genres": 0}
    return {"layer": affinity.get("source") or "spotify",
            "artists": len(affinity.get("artists") or {}),
            "genres": len(affinity.get("genres") or {})}


def build_config(taste: dict, profile: dict, sources: dict) -> dict:
    """A structured snapshot of the editable settings for the dashboard Settings view.

    Mirrors the split of concerns the repo already enforces:
      taste.yaml   = CONTENT  (what Ari likes)        -> config.taste
      profile.yaml = MECHANISM (weights/terms/geo)    -> config.scoring + config.home
      sources.yaml = REGISTRY                          -> config.sources
    The view stages edits against this and hands a precise change-set to the agent,
    which writes the real YAML — so the source of truth stays in the files, not here.
    """
    scoring = profile.get("scoring") or {}
    cats = taste.get("categories") or {}
    src_list = []
    for s in (sources.get("sources") or []):
        if not isinstance(s, dict):
            continue
        src_list.append({
            "name": s.get("name"),
            "category": s.get("category"),
            "method": s.get("method"),
            "priority": s.get("priority"),
            "status": s.get("status"),
        })
    dashboard_knobs = profile.get("dashboard") or {}
    return {
        "files": {"taste": "taste.yaml", "profile": "profile.yaml", "sources": "sources.yaml"},
        # profile.yaml `dashboard:` — page-presentation knobs (admin-controlled, per Ari
        # 2026-07-24: event photos are opt-in, top-picks-only; the page defaults them OFF).
        "photos": bool(dashboard_knobs.get("photos", False)),
        "taste": {
            "categories": {
                "high": cats.get("high") or [],
                "medium": cats.get("medium") or [],
                "low": cats.get("low") or [],
            },
            "boosts": taste.get("boosts") or [],
            "penalties": taste.get("penalties") or [],
            "artists_tracked": taste.get("artists_tracked") or [],
            "comedians_loved": taste.get("comedians_loved") or [],
            "venues_loved": taste.get("venues_loved") or [],
            "film": taste.get("film") or {},
        },
        "scoring": {
            "category_weights": scoring.get("category_weights") or {},
            "rating_thresholds": scoring.get("rating_thresholds") or [],
            "near_home_neighborhoods": scoring.get("near_home_neighborhoods") or [],
            "groove_terms": scoring.get("groove_terms") or [],
            "eu_terms": scoring.get("eu_terms") or [],
            "penalty_terms": scoring.get("penalty_terms") or [],
            "far_terms": scoring.get("far_terms") or [],
            "spotify": scoring.get("spotify") or {},
            "feedback": scoring.get("feedback") or {},
        },
        "home": profile.get("home") or {},
        "sources": src_list,
    }


# ── Front page (editorial home view) ────────────────────────────────────────────
# The dashboard's default view is a rendered SLATE, not a filtered table: hero picks per
# time-lens + per-lane shelves, all computed HERE with the same rank_key the final_rank column
# uses — the page does zero ranking of its own (the drift rule). Events are referenced by their
# stable `key` (event_key, also stamped on every feed row); the client date-windows the
# pre-ranked lists and slices — selection, never re-sorting.
#
# The front-page shape (Ari, 2026-08-01): two MARQUEE sections (rich card shelves) carry what
# gets *featured* — "Sets and shows" (the music: club lanes + live rooms + any big concert the
# editor calls must-see/great) and "Events" (comedy + one-off happenings). Everything seasonal,
# repeating, or program-shaped is *listed*, not featured, in five TABLES each formatted to its
# category: "Seasonal and repeating" (standing markets/fleas/showcase series), "Movies" (film
# programs — the dedicated marquee view holds the full boards), "Theater" (stage runs +
# one-offs), "Festivals" (date-sorted: festivals.yaml fixture + festival-tagged catalog rows),
# and "FYI" (big/far shows worth knowing about that aren't taste matches — the non-must-see
# arena tier, judged-skip stadium bookings, and the radar leftovers). Marquee sections are
# lens-windowed; the tables are fixtures (lens-independent). Only marquee-class rows are
# hero-eligible: a movie, a season, or a festival is never the featured card.
FP_MARQUEES = [
    ("sets", "Sets and shows", ("club:underground", "club:afters", "club:day",
                                "club:mainstream", "live-music", "live-music:big")),
    ("events", "Events", None),   # comedy + unclaimed one-offs (art/community/one-off markets…)
]
FP_SHELF_CAP = 40      # keys per marquee list (near + ahead each) — deep enough for a lens to fill
FP_TABLE_CAP = 40      # keys per table emit — the page slices its visible rows
# "Seasonal and repeating" membership = the old Now-running density guards, minus the "opened"
# gate (an unopened standing market is still a standing market — the table shows its next date):
#   nights >= 3          two bookings weeks apart are two dated picks, not a series;
#   ~weekly density      count >= span/7 — an Usher stadium date rebooked twice months later
#                        and a monthly party are TOUR STOPS/dated picks, not a season.
# Music lanes never take this exit: a weekly club residency stays one rep card in "Sets and
# shows" (its card wears the run label); film/stage runs have their own tables.
FP_RUN_MIN_DAYS = 14
FP_RUN_MIN_NIGHTS = 3
# Hero size/diversity knobs live in lib/assemble (TOP_PICKS_*): the hero row IS the shared
# Don't-miss policy (assemble.top_picks — one shelf definition with the digest's "Don't miss").


# "The Take" — the one-sentence teaser the voice pass writes into the consolidated digest's
# invisible `<!-- take: … -->` slot, lifted here with the doc's own date so the feed carries it
# structurally (front_page.take = {text, date}) and the page never parses markdown conventions.
# The date rides along so the chat welcome can honestly show WHICH day's read this is (a stale
# digest shows its real date, never today's). Display chrome only — never sent to the model.
# The body excludes '<' so an unclosed take comment (an LLM fill that dropped its `-->`) fails
# to match rather than lazily swallowing up to the NEXT comment's closer and shipping literal
# markup into the feed. Malformed slot -> None -> the page's lede fallback.
TAKE_RE = re.compile(r"<!--\s*take:(?!start\b|end\b)([^<]*?)-->", re.S)
DOC_DATE_RE = re.compile(r"^# .*?(\d{4}-\d{2}-\d{2})", re.M)


def digest_take(md: str):
    """{text, date} from the digest's take slot, or None when the doc has no slot (a free-form
    per-profile digest, a pre-take flagship) or the slot is unfilled — the page then falls back
    to its clipped digestLede() heuristic over the digest it loads."""
    m = TAKE_RE.search(md or "")
    if not m:
        return None
    text = " ".join(m.group(1).split())
    if not text:
        return None
    d = DOC_DATE_RE.search(md)
    return {"text": text, "date": d.group(1) if d else None}


def _fp_windows(today):
    """The four time-lens windows (inclusive ISO bounds). weekend = the next Fri–Sun cluster
    (today-inclusive when already inside one). "twoweeks" is the NEXT 3 WEEKS lens (the id
    survives the widening — it's a stored key in feeds): through the THIRD Sunday out, i.e.
    this week + two full Mon–Sun weeks, matching the client's marquee week-rows exactly."""
    t = today
    fri = t + timedelta(days=(4 - t.weekday()) % 7)
    start_wknd = t if t.weekday() in (4, 5, 6) else fri
    sun = start_wknd + timedelta(days=6 - start_wknd.weekday())
    this_sun = t + timedelta(days=(6 - t.weekday()) % 7)
    return {
        "today": (t.isoformat(), t.isoformat()),
        "weekend": (start_wknd.isoformat(), sun.isoformat()),
        "twoweeks": (t.isoformat(), (this_sun + timedelta(days=14)).isoformat()),
        "ahead": ((t + timedelta(days=14)).isoformat(), (t + timedelta(days=60)).isoformat()),
    }


def _run_span_days(e: dict) -> int:
    """Days spanned by a series rep's REMAINING nights (series summaries cover upcoming
    members only), 0 for non-series rows or same-day programs."""
    s = e.get("series") or {}
    first, last = s.get("first"), s.get("last")
    if not (e.get("series_rep") and first and last):
        return 0
    try:
        return (date.fromisoformat(last) - date.fromisoformat(first)).days
    except ValueError:
        return 0


def _is_standing(e: dict) -> bool:
    """A standing series: 3+ remaining nights at ~weekly-or-denser cadence over 14+ days.
    (The old Now-running guards without the opened gate — see the FP_RUN_* comment.)"""
    span = _run_span_days(e)
    count = ((e.get("series") or {}).get("count")) or 0
    return span >= FP_RUN_MIN_DAYS and count >= FP_RUN_MIN_NIGHTS and count >= span / 7


def _fp_section(e: dict) -> str:
    """Which front-page section a (rep) row belongs to. Festival-tagged rows are checked first
    — a festival bill's lane is club:mainstream, but it's a Festivals-table row, not a set."""
    if "festival" in ((e.get("tags") or {}).get("vibe") or []):
        return "festivals"
    lane = e.get("lane") or "other"
    if lane == "film":
        return "movies"
    if lane == "stage":
        return "theater"
    if lane == "live-music:big":
        # A big concert the editor rates IS of interest — it belongs with the featured music.
        # The rest of the arena tier is exactly "FYI": know about it, not featured.
        tier = (e.get("verdict") or {}).get("tier")
        return "sets" if tier in ("must-see", "great") else "fyi"
    if lane.startswith("club:") or lane == "live-music":
        return "sets"
    if _is_standing(e):
        return "seasonal"
    return "events"


def _program_order(e: dict, today_iso: str):
    """Movies/Theater table order: open runs first, closing-soonest (urgency), then upcoming
    programs and one-nighters by opening date. A one-nighter's first == last == its date."""
    s = e.get("series") or {}
    first = s.get("first") or e.get("iso_date") or "9999"
    last = s.get("last") or e.get("iso_date") or "9999"
    if first <= today_iso:
        return (0, last, first)
    return (1, first, last)


_WS_RE = re.compile(r"\s+")


def _fest_rollup_key(title: str) -> str:
    """One Festivals-table row per FESTIVAL, not per sub-event. Sub-events title as
    "<Festival name>: <night/program>" — when the pre-colon head reads festival-ish, IT is
    the program's identity; then dedupe's _fest_core strips edition/pass/year filler and a
    leading article, so "The Windgrease Festival: Full Festival Passes" and "Windgrease
    Festival: Billy Higgins' Drumline" share a key. (Series consolidation can't group these:
    the titles differ, deliberately — each night IS a distinct catalog event.)"""
    t = str(title or "")
    head = t.split(":", 1)[0]
    if ":" not in t or not _FEST_SIGNAL.search(_norm(head)):
        head = t
    core = re.sub(r"^the\s+", "", _fest_core(head))
    # Per-day passes differ only by a date/weekday tail ("Ocean Way Festival - 09/26
    # Saturday" / "- 09/27 Sunday") — display grouping strips those tokens too. Safe at this
    # layer: this keys a TABLE ROW, never a dedupe merge.
    core = _WS_RE.sub(" ", re.sub(
        r"\b(?:mon|tues?|wednes|thurs?|fri|satur|sun)day\b|\b\d+\b", " ", core)).strip()
    return core or _norm(t)


def build_front_page(events, verdicts, today, radar_rows=None, around_rows=None,
                     take=None, festivals=None) -> dict:
    """The front_page block: hero keys per lens, the two MARQUEE shelves (Sets and shows /
    Events), the five category TABLES (seasonal/movies/theater/festivals/fyi — see the
    FP_MARQUEES comment for the shape), radar/around joins, "The Take" ({text, date}, carried
    structurally for the concierge chat's welcome), and the festivals.yaml fixture rows. One
    card per PROGRAM: series members (lib/series — multi-night runs, cross-theater film
    programs, stamped by the consolidation pass in main()) enter only via their rep night,
    the same unit final_rank ranks."""
    pool = [e for e in events
            if not e.get("is_past") and e.get("iso_date") and (e.get("score") or 0) >= 0
            and (e.get("verdict") or {}).get("tier") != "skip"
            and (e.get("series_rep") or "series_key" not in e)]
    # THE ordering is rank_key + event_key — the exact expression final_rank is stamped from in
    # main() — so the front page can never disagree with the Explore table's rank column (no
    # second copy of the ranking expression to drift).
    ranked = sorted(pool, key=lambda e: e.get("final_rank") or 10 ** 9)
    t_iso = today.isoformat()

    by_sec = {}
    for e in ranked:
        by_sec.setdefault(_fp_section(e), []).append(e)

    # The hero row is the shared Don't-miss policy (lib/assemble.top_picks — one shelf
    # definition with the flagship digest's shelf), applied per time-lens window over the
    # MARQUEE pool only: a movie, a season, a market, or a festival is listed in its table,
    # never featured. Skips are re-checked harmlessly (top_picks reads the same verdicts
    # map), but program collapse is NOT re-applied here (no series_of) — the reps-only pool
    # filter above is the only thing keeping a multi-night run to one hero card.
    marquee_pool = sorted((by_sec.get("sets") or []) + (by_sec.get("events") or []),
                          key=lambda e: e.get("final_rank") or 10 ** 9)
    hero = {}
    for lens, (lo, hi) in _fp_windows(today).items():
        window = [e for e in marquee_pool if lo <= e["iso_date"] <= hi]
        hero[lens] = [e["key"] for e in top_picks(window, verdicts)]

    # Marquee key-lists split NEAR (days 0–13) vs AHEAD (14–60). The today/weekend lenses live
    # in NEAR, plan-ahead in AHEAD, and the 3-week lens spans the seam (the client concats both
    # zones before windowing). One global-rank cut would starve plan-ahead by construction —
    # rank_key is two-zone (judged/near events sort structurally above the unjudged far tail),
    # so a busy section's top-40 can sit entirely inside the near window. The client windows
    # each list with its LIVE date (a stale feed thins honestly rather than showing yesterday).
    near_end = (today + timedelta(days=13)).isoformat()
    shelves = []
    for sid, label, lanes in FP_MARQUEES:
        rows = by_sec.get(sid) or []
        near = [e["key"] for e in rows if e["iso_date"] <= near_end][:FP_SHELF_CAP]
        ahead = [e["key"] for e in rows if e["iso_date"] > near_end][:FP_SHELF_CAP]
        if near or ahead:
            shelves.append({"id": sid, "label": label, "kind": "marquee",
                            "lanes": list(lanes or ()), "near": near, "ahead": ahead})

    # The five tables. Each is a fixture (lens-independent) in the order its category reads
    # best: programs by urgency (_program_order), standing series by next night, FYI by date.
    seasonal = sorted(by_sec.get("seasonal") or [],
                      key=lambda e: ((e.get("series") or {}).get("first") or e["iso_date"]))
    movies = sorted(by_sec.get("movies") or [], key=lambda e: _program_order(e, t_iso))
    theater = sorted(by_sec.get("theater") or [], key=lambda e: _program_order(e, t_iso))
    fest_evs = sorted(by_sec.get("festivals") or [], key=lambda e: e["iso_date"])
    seen_fest, rolled = set(), []
    for e in fest_evs:            # one row per festival — earliest night represents it
        fk = _fest_rollup_key(e.get("title") or "")
        if fk not in seen_fest:
            seen_fest.add(fk)
            rolled.append(e)
    fest_evs = rolled

    # FYI = the arena tier that isn't a taste match — including judged SKIPS (excluded from
    # every other surface, but "big show I'd skip" is exactly what FYI exists to list) — plus
    # any radar row not already placed in a section. Date-sorted: it reads as a calendar of
    # things to know about, not a ranking.
    reps = {e["key"]: e for e in events
            if not e.get("is_past") and e.get("iso_date")
            and (e.get("series_rep") or "series_key" not in e)}
    fyi = list(by_sec.get("fyi") or [])
    fyi += [e for e in reps.values()
            if (e.get("lane") or "") == "live-music:big"
            and (e.get("verdict") or {}).get("tier") == "skip"]
    placed = {e["key"] for sec in ("sets", "events", "seasonal", "movies", "theater",
                                   "festivals") for e in (by_sec.get(sec) or [])}
    fyi_keys = {e["key"] for e in fyi}
    for r in (radar_rows or []):
        k = r.get("key") or event_key(r)
        e = reps.get(k)
        if e is not None and k not in placed and k not in fyi_keys:
            fyi.append(e)
            fyi_keys.add(k)
    fyi.sort(key=lambda e: e["iso_date"])

    tables = [{"id": sid, "label": label, "keys": [e["key"] for e in rows[:FP_TABLE_CAP]]}
              for sid, label, rows in (
                  ("seasonal", "Seasonal and repeating", seasonal),
                  ("movies", "Movies", movies),
                  ("theater", "Theater", theater),
                  ("festivals", "Festivals", fest_evs),
                  ("fyi", "FYI", fyi))]

    feed_keys = {e["key"] for e in events if not e.get("is_past")}
    def join(rows, cap):
        out = []
        for r in (rows or []):
            k = r.get("key") or event_key(r)
            if k in feed_keys and k not in out:
                out.append(k)
            if len(out) >= cap:
                break
        return out

    return {
        "windows": _fp_windows(today),
        "take": take,
        "hero": hero,
        "shelves": shelves,
        "tables": tables,
        "radar": join(radar_rows, 16),
        "around": join(around_rows, 12),
        "festivals": festivals or [],
    }


def _radar_artifacts_fresh(paths, catalog_mtime, today) -> bool:
    """True when every rail artifact exists, was built for `today`, and is no older than
    the catalog it summarizes. Unreadable or legacy docs (no `today` stamp) count as stale."""
    for p in paths:
        try:
            if p.stat().st_mtime < catalog_mtime:
                return False
            if json.loads(p.read_text()).get("today") != today.isoformat():
                return False
        except (OSError, json.JSONDecodeError):
            return False
    return True


def ensure_radar_artifacts(today) -> None:
    """Self-heal the front-page rails' inputs (data/radar.json + data/around_town.json).

    Both are gitignored runtime artifacts, so a feed rebuild in a tree where the radar step
    never ran — a fresh clone's ad-hoc "rebuild feeds" pass (how the 2026-08-01 post-merge
    rebuild shipped every feed with empty radar/Around-town rails), or a workflow whose
    `build_radar.py || true` failed — silently degrades the flagship surface. When they're
    missing or stale (built for another day, or older than data/catalog.json), rebuild them
    via build_radar.refresh_files(): deterministic, no network, sub-second. Always from the
    ROOT taste/profile — the rails are the shared city-pulse layer, identical across profile
    feeds, so build_profiles' per-profile shell-outs reuse the first rebuild instead of
    recomputing per feed. A rebuild failure warns and leaves the rails empty (degrade
    gracefully) rather than blocking the feed build."""
    paths = (REPO / "data" / "radar.json", REPO / "data" / "around_town.json")
    try:
        catalog_mtime = (REPO / "data" / "catalog.json").stat().st_mtime
    except OSError:
        catalog_mtime = 0.0
    if _radar_artifacts_fresh(paths, catalog_mtime, today):
        return
    try:
        import build_radar
        r = build_radar.refresh_files()
        print(f"  radar rails rebuilt: {r['radar']} radar + {r['around']} around-town")
    except Exception as e:  # noqa: BLE001 — a rail failure never blocks the feed build
        print(f"WARN: radar/around-town rebuild failed ({e}); front-page rails will be empty",
              file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", default="data/catalog.json",
                    help="catalog JSON to read (default: data/catalog.json)")
    ap.add_argument("-o", "--out", default="dashboard/data.json")
    ap.add_argument("--taste", default="taste.yaml")
    ap.add_argument("--profile", default="profile.yaml")
    ap.add_argument("--sources", default="sources.yaml")
    ap.add_argument("--enrichment", default="data/enrichment.json",
                    help="scene-graph cache to fold in (optional; skipped if absent)")
    ap.add_argument("--digest", default="digests/latest.md",
                    help="digest doc to lift 'The Take' (the voice pass's dated one-sentence "
                         "teaser) from into front_page.take — build_profiles points each "
                         "friend's feed at their own digests/<hash>/latest.md (no take slot "
                         "there -> null; the page falls back to its clipped lede heuristic)")
    ap.add_argument("--profile-hash", default=None,
                    help="feed hash of the profile being built — loads its OWN per-person music "
                         "layer (data/spotify/<hash>.json + data/feedback.<hash>.jsonl) instead of "
                         "the default/owner one. Omit for the canonical (Ari's) feed.")
    ap.add_argument("--verdicts", default=None,
                    help="editor verdict store to fold in (default: data/verdicts/<hash>.json for "
                         "this profile). Adds each event's verdict + final_rank to the feed.")
    ap.add_argument("--editor-pool-out", default=None,
                    help="also emit this profile's editor judging pool here (for the event-editor pass)")
    ap.add_argument("--editor-window", type=int, default=28)
    ap.add_argument("--editor-per-lane", type=int, default=0,
                    help="0 (default) = judge every slate-lane event in the window (LLM-first)")
    ap.add_argument("--editor-floor", type=int, default=4)
    args = ap.parse_args()

    def resolve(p):
        return (REPO / p) if not Path(p).is_absolute() else Path(p)

    catalog_path = resolve(args.input)
    out_path = resolve(args.out)
    taste_path = resolve(args.taste)
    profile_path = resolve(args.profile)
    sources_path = resolve(args.sources)
    enrichment_path = resolve(args.enrichment)

    if not catalog_path.exists():
        print(f"ERROR: catalog not found: {catalog_path}", file=sys.stderr)
        return 1

    with catalog_path.open() as f:
        all_rows = json.load(f)
    # Ghost rows (status:"unlisted" — dropped by every source that carried them; lib/pipeline
    # flag_stale) don't ship in the feed: the digest's score_pool already refuses to recommend
    # them, and the dashboard would render a probably-cancelled/pulled event exactly like a live
    # one. They stay in the catalog (flag_stale un-flags them if a source re-lists) and the
    # catalog_meta version fallback below still spans them, so the staleness key can't drift
    # from the run_digest stamp.
    catalog = [e for e in all_rows if e.get("status") != "unlisted"]
    ghosts = len(all_rows) - len(catalog)
    taste = load_yaml(taste_path)
    profile = load_yaml(profile_path)
    sources = load_yaml(sources_path)

    # Dining layer (la-dining) — pass a trimmed restaurant list through to the feed so the
    # dashboard's concierge chat can fuse food + events into plans. Pure passthrough (no
    # scoring); graceful if data/dining.json is absent or malformed.
    dining = []
    dining_path = REPO / "data" / "dining.json"
    if dining_path.exists():
        try:
            with dining_path.open() as f:
                raw_dining = json.load(f)
            for r in (raw_dining if isinstance(raw_dining, list) else []):
                if not isinstance(r, dict) or not r.get("name"):
                    continue
                resv = r.get("reservations") or {}
                dining.append({
                    "name": r.get("name"),
                    "type": r.get("type"),
                    "cuisine": r.get("cuisine") or [],
                    "neighborhood": r.get("neighborhood"),
                    "price": r.get("price"),
                    "occasion": r.get("occasion") or [],
                    "reservation_url": resv.get("url"),
                    "reservation_platform": resv.get("platform"),
                    "notes": r.get("notes"),
                })
        except (json.JSONDecodeError, OSError):
            dining = []

    # Spotify + feedback music layer (Phase C) — the same merged layer the digest scores
    # against (Spotify affinity folded with feedback), so the dashboard stars match. With a
    # --profile-hash this loads THAT profile's own per-person layer (per-profile Spotify), so a
    # friend's feed ranks to their music, not Ari's. Graceful: absent/corrupt -> taste-only.
    affinity = merged_affinity(REPO, profile, profile_hash=args.profile_hash)

    # Scene-researcher enrichment cache (Phase B) — fold the accumulated curator notes / tags /
    # artist notes / images onto matching events, AND cached artist bios onto ANY event that lists
    # those artists (parity with the digest's merge_enrichment). Graceful: no file -> no-op.
    cache = load_cache(enrichment_path)

    # Editor verdicts (per-profile) — the thin-editor's ranking judgment, folded onto each event so
    # the dashboard can show the final (verdict-adjusted) rank beside the deterministic score and
    # sort by either. Same verdict the digest slate uses; absent -> deterministic order only.
    vpath = resolve(args.verdicts) if args.verdicts else ED.verdict_path(args.profile_hash)
    verdicts = ED.verdict_map(ED.load_verdicts(vpath))

    # Stars — the shared reaction log (data/reactions.jsonl, committed by the Worker's POST /react)
    # folded onto events as display names. The one social feature and it's MUTUAL: the same fold in
    # every feed, so everyone sees who starred what. Graceful: no log -> no stars, no profiles.yaml
    # read.
    smap = star_map(load_reactions(REPO / "data" / "reactions.jsonl"))
    star_names = hash_names(load_yaml(REPO / "profiles.yaml") or {}) if smap else {}

    is_sample = "sample" in catalog_path.name
    # LA-local today (NOT the runner's UTC date) — otherwise, in CI (UTC) past midnight UTC, events
    # still happening tonight in LA get marked is_past and lose their final_rank / highlight.
    today = today_la()

    # Fold the enrichment cache onto the whole catalog ONCE (order-preserving) instead of a
    # per-event merge_enrichment([ev]) call inside the loop — same result, O(N) not O(N) calls.
    merged_all = merge_enrichment(catalog, cache, AF.ambiguous_set(profile, taste))

    events = []
    enriched_hits = 0
    for ev, merged in zip(catalog, merged_all):
        scored = score_event(ev, taste, profile, affinity)
        d = parse_event_date(ev)
        out = dict(ev)
        out["score"] = scored["score"]
        out["rating"] = score_to_rating(scored["score"], profile, taste)
        out["reasons"] = scored["reasons"]
        out["iso_date"] = d.isoformat() if d else None
        out["is_past"] = bool(d and d < today)

        enr = merged.get("enrichment")
        if enr:
            out["enrichment"] = {k: enr[k] for k in ENRICH_FIELDS if enr.get(k)}
            enriched_hits += 1

        v = verdicts.get(event_key(ev))
        if v:
            out["verdict"] = v                       # {tier, lane?, adjust, why, confidence}
        out["lane"] = event_lane(out, verdicts)      # verdict lane override else tag-derived
        k = event_key(ev)
        out["key"] = k                               # stable id — front_page joins + feedback + stars

        starred = stars_for(smap, star_names, k)
        if starred:
            out["stars"] = starred                   # [{name, hash}] — who starred it (social)

        events.append(out)

    # Series consolidation (lib/series) — a multi-night run (and, for films, the same movie
    # across theaters) is ONE program, not N competitors: without this the 15-night Odyssey run
    # takes 5 of the top-15 rank slots (each night judged must-see). Every member carries the run
    # summary (dates/venues/per-night links + sold-out flags) so whichever night survives a date
    # filter can render the whole run; film events also get the external "all LA showtimes" link
    # (the theaters that aren't fetch sources). The catalog itself stays one-row-per-night.
    upcoming = [e for e in events if not e["is_past"]]
    series_groups = group_series(upcoming)
    for key, members in series_groups.items():
        summ = series_summary(members)
        rep = max(members, key=lambda e: (rank_key(e, verdicts), event_key(e)))
        for m in members:
            m["series_key"] = key
            m["series"] = summ
            m["series_rep"] = m is rep
    for e in upcoming:
        if is_film(e):
            e["showtimes_url"] = showtimes_url(e.get("title") or "")

    # Final rank — each UPCOMING program's position by the two-zone rank_key (Track B2, LLM-first):
    # judged non-skip events tier-primary (the editor's call IS the ranking; score orders within a
    # tier), then the unjudged tail (far-out / junk lanes) by raw score, judged skips last. The
    # near window is fully judged (B1), so the default view leads with the LLM's ranking and the
    # far tail sorts below it (date filters cover plan-ahead). The dashboard shows final_rank
    # beside the deterministic score and sorts by either. Past events stay unranked. A series
    # ranks ONCE via its rep (the night the ranking itself leads with); the other nights carry
    # `series_rank` (the rep's rank) so a rank-sorted, date-filtered view that clipped the rep
    # still orders the surviving night where the program belongs.
    rank_units = [e for e in upcoming if e.get("series_rep") or "series_key" not in e]
    for rank, e in enumerate(
            sorted(rank_units, key=lambda e: (rank_key(e, verdicts), event_key(e)), reverse=True), 1):
        e["final_rank"] = rank
    for members in series_groups.values():
        rep_rank = next((m.get("final_rank") for m in members if m.get("series_rep")), None)
        for m in members:
            if not m.get("series_rep") and rep_rank is not None:
                m["series_rank"] = rep_rank

    # Sort: upcoming first by date, then by rating desc within a date.
    events.sort(key=lambda e: (e["iso_date"] or "9999-12-31", -e["rating"]))

    neighborhoods = sorted({e["neighborhood"] for e in events if e.get("neighborhood")})
    categories = sorted({e["category"] for e in events if e.get("category")})

    # Multi-axis tag facets (scripts/lib/tagging.py) — only values actually present, each
    # with its count, so a future filter UI can render chips without re-scanning every event.
    def facet(axis, listish=False):
        c = Counter()
        for e in events:
            tags = e.get("tags") or {}
            v = tags.get(axis)
            for item in (v or []) if listish else ([v] if v else []):
                c[item] += 1
        return [{"value": k, "count": n} for k, n in c.most_common()]

    tag_facets = {
        "type": facet("type"),
        "genre": facet("genre", listish=True),
        "setting": facet("setting", listish=True),
        "scale": facet("scale"),
        "vibe": facet("vibe", listish=True),
        "region": facet("region"),
        "vocab": TAG_VOCAB,
    }

    # Front page — hero per time-lens + per-lane shelves + the radar/Around-town rails. The
    # rail inputs are gitignored runtime artifacts: self-heal them (missing/stale -> rebuild)
    # so a feed rebuild from a fresh clone can't ship empty rails. Sample builds don't rebuild
    # (a demo build must not write real-catalog artifacts into data/) but still read what's
    # there. Same rank the final_rank column shows; per-profile for free since this whole
    # build already runs per profile.
    if not is_sample:
        ensure_radar_artifacts(today)
    radar_rows, around_rows = [], []
    for p, target in ((REPO / "data" / "radar.json", "radar"),
                      (REPO / "data" / "around_town.json", "around")):
        if p.exists():
            try:
                rows = json.loads(p.read_text()).get("events", [])
                if target == "radar":
                    radar_rows = rows
                else:
                    around_rows = rows
            except (json.JSONDecodeError, OSError):
                pass
    # Sample builds skip the lift — a demo feed must not carry the real digest's voice-pass
    # intro over sample events (same gate the catalog_meta publish uses).
    take = None
    dpath = resolve(args.digest)
    if not is_sample and dpath.exists():
        try:
            take = digest_take(dpath.read_text(encoding="utf-8"))
        except OSError:
            pass
    if take is None and not is_sample:
        # Keep-last: a deterministic re-render (owner re-rank, no-change day) rewrites the doc
        # with an UNFILLED take slot — the previous feed's take, which carries its own date, is
        # still the operative read. Dropping it is what blanked the front page's digest block
        # (2026-08-01); a dated stale take degrades honestly instead.
        try:
            prev = json.loads(resolve(args.out).read_text(encoding="utf-8"))
            prev_take = (prev.get("front_page") or {}).get("take")
            if isinstance(prev_take, dict) and prev_take.get("text"):
                take = prev_take
        except (json.JSONDecodeError, OSError, AttributeError):
            pass
    # Festivals watch-list — sample builds skip it (a demo feed shouldn't carry the real list).
    festivals = [] if is_sample else load_festivals(REPO / "festivals.yaml")
    front_page = build_front_page(events, verdicts, today, radar_rows, around_rows,
                                  take=take, festivals=festivals)

    # Direct ▶ listen links (data/artist_links.json, resolved during run_digest): normalized
    # name -> Spotify artist URL for exactly the artists this feed's upcoming events carry.
    # The dashboard's _artistNorm() mirrors ALINK.norm_name() and falls back to a search URL
    # on any miss, so an absent/stale cache just means search links — never a broken feed.
    artist_links = ALINK.feed_map(ALINK.load(REPO / "data" / "artist_links.json"), events)

    # The catalog version this feed was scored against — the dashboard compares it to the live
    # dashboard/catalog_meta.json to decide if this profile's ranking/digest is stale. Prefer the
    # stamp written by run_digest; fall back to recomputing from the catalog we just read.
    cat_meta = CM.read_meta(catalog_path.parent / "catalog_meta.json") or CM.build_meta(all_rows)
    # Backfill content_version if the on-disk meta predates it, so a build-only path (build-profiles)
    # still stamps/publishes it — the dashboard staleness check keys off content_version now.
    # Versions compute over ALL rows (ghosts included), matching what run_digest stamps.
    if not cat_meta.get("content_version"):
        cat_meta["content_version"] = CM.content_version(all_rows)

    feed = {
        # Timezone-aware (UTC) — the dashboard's "last data pull" parses this; a naive stamp is
        # read by the browser as local time and shows ~hours in the future for a PT viewer.
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_file": str(catalog_path.relative_to(REPO)) if catalog_path.is_relative_to(REPO) else str(catalog_path),
        "is_sample": is_sample,
        "catalog_version": cat_meta.get("version"),
        "catalog_content_version": cat_meta.get("content_version"),
        "catalog_fetched_at": cat_meta.get("fetched_at"),
        "count": len(events),
        "enriched_count": enriched_hits,
        "music": music_block(affinity),
        "neighborhoods": neighborhoods,
        "categories": categories,
        "tag_facets": tag_facets,
        "front_page": front_page,
        "artist_links": artist_links,
        "dining": dining,
        "taste": {
            "venues_loved": taste.get("venues_loved") or [],
            "artists_tracked": taste.get("artists_tracked") or [],
        },
        "config": build_config(taste, profile, sources),
        "events": events,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(feed, f, indent=2)
    rel_out = out_path.relative_to(REPO) if out_path.is_relative_to(REPO) else out_path
    print(f"Wrote {len(events)} events ({enriched_hits} enriched"
          f"{f', {ghosts} unlisted hidden' if ghosts else ''}) -> {rel_out}"
          f"{' (SAMPLE data)' if is_sample else ''}")

    # Publish the live catalog version next to the feeds (any non-sample build refreshes it; the
    # content is identical regardless of which profile is built). The dashboard fetches this fresh
    # on every load to compare against each feed's `catalog_version`.
    if not is_sample and out_path.parent.is_dir():
        try:
            # Publish content_version (the staleness key) + this run's change delta (added/updated/
            # changes) so the dashboard can both flag "your ranking is stale" AND show what moved.
            meta_pub = {k: v for k, v in cat_meta.items()
                        if k in ("version", "content_version", "count", "fetched_at",
                                 "added", "updated", "changes") and v is not None}
            (out_path.parent / "catalog_meta.json").write_text(
                json.dumps(meta_pub, indent=2) + "\n", encoding="utf-8")
        except OSError as e:
            print(f"  WARN: could not publish catalog_meta.json: {e}", file=sys.stderr)

    # Optionally emit this profile's editor judging pool (the per-lane set worth LLM judgment),
    # so the event-editor pass can judge it and write per-profile verdicts. Reuses the per-profile
    # scoring just done — no second scoring path. The default-profile pool is also emitted by
    # run_digest; here it's per-profile, driven by build_profiles.
    if args.editor_pool_out:
        end_iso = (today + timedelta(days=args.editor_window)).isoformat()
        epool = [e for e in events if not e.get("is_past") and e.get("iso_date")
                 and e["iso_date"] <= end_iso and (e.get("score") or 0) >= 0]
        judge = ED.editor_pool(epool, per_lane=args.editor_per_lane, floor=args.editor_floor)
        ep_doc = ED.pool_doc(judge, today=today, window_days=args.editor_window,
                             per_lane=args.editor_per_lane, floor=args.editor_floor,
                             affinity=affinity, enrichment=cache, taste=taste)
        epath = resolve(args.editor_pool_out)
        epath.parent.mkdir(parents=True, exist_ok=True)
        epath.write_text(json.dumps(ep_doc, indent=2, ensure_ascii=False) + "\n")
        rel_ep = epath.relative_to(REPO) if epath.is_relative_to(REPO) else epath
        print(f"  + editor pool: {len(judge)} to judge -> {rel_ep}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
