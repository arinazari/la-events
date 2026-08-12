#!/usr/bin/env python3
"""Voice pass plumbing for the per-profile digest (2026-08 "render + voice" redesign).

The digest is built in two stages so a digest ALWAYS ships:
  1. render_digest.py --profile-hash <H> writes the deterministic scaffold DIRECTLY to
     digests/<H>/latest.md — correct picks/days/links/⭐ by construction, dry prose.
  2. This module turns LLM-authored words (intro + one why per featured pick) into the
     finished digest — `prep` emits the numbered work doc the why-writer agents consume,
     `splice` folds their JSON back over the scaffold with hard verification (link
     sequence + title-echo alignment). Any failure exits nonzero and leaves the scaffold
     untouched: the fallback is always shippable.

Why-cache (pay once per sentence): data/why_cache.<hash>.json stores each pick's why
keyed by event_key, stamped with a taste-hash. `prep` marks picks whose cached why is
still valid so the agents skip them; `splice` fills from cache + fresh whys and re-stamps.
A taste edit changes the taste-hash and honestly invalidates every cached sentence.

Usage:
  python scripts/digest_voice.py prep   --hash <H> [--scaffold F] [--out F] [--today D]
  python scripts/digest_voice.py splice --hash <H> --whys F [--scaffold F] [--out F] [--today D]
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import yaml  # noqa: E402

BULLET = re.compile(r"^- (?:`[^`]*` )?(?:\([^)]*\) )?(?:[⭐🆕↻★\s]*)?\*\*\[([^\]]+)\]")
ALSO = re.compile(r"^\s*-?\s*\*Also")
HDR = re.compile(r"^(#{2,3}) (.+)$")
DOW = {"Monday": "Mon", "Tuesday": "Tue", "Wednesday": "Wed", "Thursday": "Thu",
       "Friday": "Fri", "Saturday": "Sat", "Sunday": "Sun"}
MON = {"January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6, "July": 7,
       "August": 8, "September": 9, "October": 10, "November": 11, "December": 12}


def resolve_profile(profile_hash: str) -> dict:
    """profiles.yaml entry (+ resolved taste/profile/prefs paths) for a feed hash."""
    man = yaml.safe_load((ROOT / "profiles.yaml").read_text()) or {}
    salt = man.get("salt") or "la-events/v1:"
    for p in man.get("profiles") or []:
        u = (p.get("username") or "").strip().lower()
        if u and hashlib.sha256((salt + u).encode()).hexdigest()[:16] == profile_hash:
            return {
                "username": u, "name": p.get("name") or u, "owner": bool(p.get("owner")),
                "taste": ROOT / (p.get("taste") or "taste.yaml"),
                "profile": ROOT / p["profile"] if p.get("profile") else None,
                "prefs": ROOT / (p.get("digest_prefs") or f"profiles/{u}/digest.yaml"),
            }
    sys.exit(f"no profiles.yaml entry for hash {profile_hash}")


def taste_hash(prof: dict) -> str:
    """Content hash of everything that shapes a why: taste + digest prefs."""
    h = hashlib.sha256()
    for p in (prof["taste"], prof["prefs"]):
        if p and Path(p).exists():
            h.update(Path(p).read_bytes())
    return h.hexdigest()[:16]


def taste_brief(prof: dict) -> str:
    """A few grounding lines for the why-writers, from the profile's own taste.yaml."""
    t = yaml.safe_load(Path(prof["taste"]).read_text()) or {}
    lines = [f"Reader: {prof['name']}."]
    if t.get("narrative"):
        lines.append(str(t["narrative"]).strip()[:600])
    for k, label in (("artists_tracked", "Tracked artists"), ("venues_loved", "Loved venues")):
        v = t.get(k) or []
        if v:
            lines.append(f"{label}: {', '.join(str(x) for x in v[:25])}")
    return "\n".join(lines)


def day_hdr(text: str):
    m = re.match(r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*·\s*(\w+)\s+(\d{1,2})", text)
    if m and m.group(2) in MON:
        return f"## {DOW[m.group(1)]} {MON[m.group(2)]}/{int(m.group(3))}"
    return None


def scan(lines):
    """(idx, lineno, title, desc_lineno) for each featured (non-Also) pick bullet."""
    out, i = [], 0
    for n, line in enumerate(lines):
        m = BULLET.match(line)
        if m and not ALSO.match(line):
            i += 1
            desc = None
            if n + 1 < len(lines):
                nxt = lines[n + 1]
                if nxt.strip() and not BULLET.match(nxt) and not ALSO.match(nxt) \
                   and not HDR.match(nxt) and not nxt.startswith("**") and not nxt.startswith("*"):
                    desc = n + 1
            out.append((i, n, m.group(1), desc))
    return out


def norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())[:24]


def pick_keys(scaffold_text: str, picks):
    """event-link -> stable id per pick (first URL on the bullet line), for the why-cache."""
    lines = scaffold_text.splitlines()
    keys = []
    for _, n, title, _ in picks:
        m = re.search(r"\]\((https?://[^)\s]+)\)", lines[n])
        keys.append(hashlib.sha256(((m.group(1) if m else "") + "|" + norm(title)).encode())
                    .hexdigest()[:12])
    return keys


def load_why_cache(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return {"taste_hash": None, "whys": {}}


def prep(args):
    prof = resolve_profile(args.hash)
    th = taste_hash(prof)
    scaffold = Path(args.scaffold)
    text = scaffold.read_text()
    lines = text.splitlines()
    picks = scan(lines)
    keys = pick_keys(text, picks)
    cache = load_why_cache(args.cache)
    cached_ok = cache.get("taste_hash") == th
    day = ""
    rows, k = [], 0
    n_cached = 0
    for n, line in enumerate(lines):
        h = HDR.match(line)
        if h:
            d = day_hdr(h.group(2))
            if d:
                day = d[3:]
        if k < len(picks) and picks[k][1] == n:
            i, _, title, desc = picks[k]
            body = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line[2:])
            extra = ("  ctx: " + lines[desc].strip()) if desc else ""
            hit = cache["whys"].get(keys[k]) if cached_ok else None
            k += 1
            if hit:
                n_cached += 1
                rows.append(f"{i}. [{day}] [CACHED — skip] {body}")
            else:
                rows.append(f"{i}. [{day}] {body}{extra}")
    doc = (f"# Why-writer work doc — profile {args.hash}\n\n"
           f"TASTE BRIEF:\n{taste_brief(prof)}\n\n"
           f"PICKS ({len(picks)} total, {n_cached} cached — write a why for every pick "
           f"NOT marked [CACHED — skip]):\n\n" + "\n".join(rows) + "\n")
    Path(args.out).write_text(doc)
    todo = len(picks) - n_cached
    print(f"prep: {len(picks)} picks, {n_cached} cached, {todo} to write -> {args.out}")
    # machine-readable handoff for the workflow/routine (batch split + budget decisions)
    print(json.dumps({"picks": len(picks), "cached": n_cached, "todo": todo,
                      "taste_hash": th, "owner": prof["owner"]}))


def splice(args):
    prof = resolve_profile(args.hash)
    th = taste_hash(prof)
    scaffold = Path(args.scaffold)
    text = scaffold.read_text()
    lines = text.splitlines()
    picks = scan(lines)
    keys = pick_keys(text, picks)
    cache = load_why_cache(args.cache)
    cached_ok = cache.get("taste_hash") == th

    j = json.loads(Path(args.whys).read_text())
    fresh = {int(w["i"]): w for w in j.get("whys") or []}
    # Assemble the full why list: fresh wins, else valid cache; every pick must resolve.
    resolved, missing = {}, []
    for pos, (i, n, title, _) in enumerate(picks):
        w = fresh.get(i)
        if w is not None:
            t_echo = norm(w.get("t") or "")
            if t_echo and t_echo not in norm(title) and norm(title) not in t_echo:
                sys.exit(f"FAIL: misalignment at pick {i}: agent said {w.get('t')!r}, "
                         f"pick is {title!r}")
            resolved[i] = str(w.get("why") or "").strip()
        elif cached_ok and cache["whys"].get(keys[pos]):
            resolved[i] = cache["whys"][keys[pos]]["why"]
        if not resolved.get(i):
            missing.append(i)
    if missing:
        sys.exit(f"FAIL: no why for picks {missing[:8]}{'…' if len(missing) > 8 else ''} "
                 f"({len(missing)} of {len(picks)})")

    skip_desc = {desc for (_, _, _, desc) in picks if desc is not None}
    out, k = [], 0
    for n, line in enumerate(lines[3:], start=3):    # drop the scaffold's 3 top-matter lines
        if n in skip_desc:
            continue
        h = HDR.match(line)
        if h:
            d = day_hdr(h.group(2))
            out.append(d if d else line)
            continue
        if line.startswith("**") and line.endswith("**"):    # lane subheader
            continue
        if k < len(picks) and picks[k][1] == n:
            w = resolved[picks[k][0]].rstrip(".") + "."
            out.append(line.rstrip() + f" — *{w}*")
            k += 1
            continue
        out.append(line)
    stats = re.search(r"\*(\d+ picks across \d+ days[^*]*)\*", "\n".join(lines[:3]))
    today = args.today or date.today().strftime("%a %-m/%-d")
    head = [f"# {prof['name']}'s LA Digest", "", str(j.get("intro") or "").strip(), "",
            f"*Digest regenerated {today} — "
            f"{str(j.get('regen_clause') or 'picks re-ranked to your taste').strip().rstrip('.')}."
            f" {stats.group(1) if stats else ''}*".rstrip(), ""]
    final = "\n".join(head + out) + "\n"

    seq = lambda t: re.findall(r"\]\((https?://[^)\s]+)\)", t)
    if seq(text) != seq(final):
        sys.exit("FAIL: link sequence changed — refusing to overwrite the scaffold")

    Path(args.out).write_text(final)
    # Persist every resolved why under the current taste hash (fresh overwrite cached).
    cache = {"taste_hash": th,
             "whys": {keys[pos]: {"why": resolved[i], "title": title[:60]}
                      for pos, (i, _, title, _) in enumerate(picks)}}
    Path(args.cache).write_text(json.dumps(cache, indent=1, ensure_ascii=False) + "\n")
    print(f"splice: {args.out} · {len(picks)} whys ({len(fresh)} fresh) · "
          f"links {len(seq(final))} verified · why-cache updated")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("resolve", help="print the profile's resolved paths as JSON")
    r.add_argument("--hash", required=True)
    for name in ("prep", "splice"):
        s = sub.add_parser(name)
        s.add_argument("--hash", required=True)
        s.add_argument("--scaffold", default=None,
                       help="default: digests/<hash>/latest.md (the rendered scaffold)")
        s.add_argument("--out", default=None)
        s.add_argument("--today", default=None, help="Day M/D stamp override (tests)")
        s.add_argument("--cache", default=None,
                       help="why-cache path (default: data/why_cache.<hash>.json)")
        if name == "splice":
            s.add_argument("--whys", required=True, help="merged why-writer JSON")
    args = ap.parse_args()
    if args.cmd == "resolve":
        prof = resolve_profile(args.hash)
        print(json.dumps({"username": prof["username"], "owner": prof["owner"],
                          "taste": str(prof["taste"]),
                          "profile": str(prof["profile"]) if prof["profile"] else None,
                          "prefs": str(prof["prefs"]) if Path(prof["prefs"]).exists() else None}))
        return
    args.scaffold = args.scaffold or str(ROOT / "digests" / args.hash / "latest.md")
    args.cache = args.cache or str(ROOT / "data" / f"why_cache.{args.hash}.json")
    if args.cmd == "prep":
        args.out = args.out or str(ROOT / "data" / f"digest_picks.{args.hash}.md")
        prep(args)
    else:
        args.out = args.out or str(ROOT / "digests" / args.hash / "latest.md")
        splice(args)


if __name__ == "__main__":
    main()
