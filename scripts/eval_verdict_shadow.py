#!/usr/bin/env python3
"""Shadow-eval: how much of the event-editor's per-profile verdict layer is already
implied by the deterministic score — and where it genuinely disagrees.

Ground truth is the cached verdict stores (data/verdicts/*.json): every record carries
score_at_judge (the deterministic score at judging time), tier, adjust, and why. Three
questions, per profile:

  A. ALIGNMENT   — does the deterministic score already order the editor's tiers?
                   (median score per tier + Mann-Whitney-style pairwise concordance)
  B. MOVEMENT    — how far does the editor move the ranking? (adjust distribution +
                   rank displacement between score-only and score+adjust+tier ordering)
  C. SLATE IMPACT — on the profile's CURRENT dashboard feed, how different is the
                   assembled slate + top-picks shelf with verdicts on vs off?

Disagreements (high tier on a low score, skip on a high score, big adjusts) are dumped
to --out for downstream classification of WHICH signal the heuristic lacked.

Usage: python scripts/eval_verdict_shadow.py [--out disagreements.json]
"""
import argparse
import json
import sys
from bisect import bisect_left, bisect_right
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from lib import assemble  # noqa: E402

TIER_ORD = {"skip": 0, "solid": 1, "great": 2, "must-see": 3}


def load_store(path):
    d = json.loads(Path(path).read_text())
    v = d.get("verdicts") if isinstance(d, dict) and "verdicts" in d else d
    return {k: x for k, x in v.items() if isinstance(x, dict) and x.get("tier") in TIER_ORD}


def concordance(store):
    """P(score_at_judge orders a cross-tier pair the same way the editor's tiers do).
    Computed per tier-pair via rank counting (Mann-Whitney U), ties counted half."""
    by_tier = {}
    for x in store.values():
        s = x.get("score_at_judge")
        if s is not None:
            by_tier.setdefault(x["tier"], []).append(s)
    for v in by_tier.values():
        v.sort()
    pairs = wins = 0.0
    tiers = sorted(by_tier, key=TIER_ORD.get)
    for i, lo in enumerate(tiers):
        for hi in tiers[i + 1:]:
            los, his = by_tier[lo], by_tier[hi]
            for s in his:  # count lo-tier scores strictly below / tied with this hi-tier score
                below = bisect_left(los, s)
                tied = bisect_right(los, s) - below
                wins += below + tied / 2.0
                pairs += len(los)
    return (wins / pairs) if pairs else None, {t: len(v) for t, v in by_tier.items()}


def median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


def displacement(store):
    """Percentile displacement between score-only ordering and the editor's effective
    ordering (score + adjust + bounded tier bonus — assemble.rank_score's blend)."""
    rows = [(k, x) for k, x in store.items() if x.get("score_at_judge") is not None]
    if len(rows) < 5:
        return None
    n = len(rows)
    base = sorted(rows, key=lambda kv: (kv[1]["score_at_judge"], kv[0]), reverse=True)
    eff = sorted(rows, key=lambda kv: (kv[1]["score_at_judge"] + (kv[1].get("adjust") or 0)
                                       + assemble.RANK_TIER_BONUS.get(kv[1]["tier"], 0), kv[0]),
                 reverse=True)
    pos_b = {k: i for i, (k, _) in enumerate(base)}
    moves = [abs(pos_b[k] - i) / n * 100 for i, (k, _) in enumerate(eff)]
    moves.sort()
    return {"mean_pct": round(sum(moves) / n, 1), "p90_pct": round(moves[int(n * 0.9)], 1),
            "max_pct": round(moves[-1], 1)}


def slate_impact(feed_path, store):
    """Diff assemble() + top_picks() on the profile's current feed, verdicts on vs off."""
    feed = json.loads(Path(feed_path).read_text())
    pool = [e for e in feed.get("events", []) if not e.get("is_past")]
    if not pool:
        return None
    days_off = assemble.assemble(pool, verdicts={})
    days_on = assemble.assemble(pool, verdicts=store)
    keys = lambda days: {assemble.event_key(p) for d in days for p in d["picks"]}
    k_off, k_on = keys(days_off), keys(days_on)
    leads = lambda days: [assemble.event_key(d["picks"][0]) for d in days if d["picks"]]
    l_off, l_on = leads(days_off), leads(days_on)
    tp_off = [assemble.event_key(e) for e in assemble.top_picks(pool, {})]
    tp_on = [assemble.event_key(e) for e in assemble.top_picks(pool, store)]
    return {
        "slate_size": len(k_on),
        "picks_jaccard": round(len(k_off & k_on) / len(k_off | k_on), 3) if k_off | k_on else None,
        "picks_changed": len(k_off ^ k_on),
        "day_leads_changed": sum(1 for a, b in zip(l_off, l_on) if a != b),
        "day_count": len(l_on),
        "top_picks_changed": len(set(tp_off) ^ set(tp_on)),
        "top_picks_n": len(tp_on),
        "judged_in_pool": sum(1 for e in pool if assemble.event_key(e) in store),
    }


def disagreements(profile, store):
    """Verdicts the deterministic score would NOT have produced — the editor's real deltas."""
    scored = sorted(x["score_at_judge"] for x in store.values()
                    if x.get("score_at_judge") is not None)
    if not scored:
        return []
    pct = lambda s: bisect_left(scored, s) / len(scored) * 100
    out = []
    for k, x in store.items():
        s = x.get("score_at_judge")
        if s is None:
            continue
        p = pct(s)
        kinds = []
        if x["tier"] in ("must-see", "great") and p <= 40:
            kinds.append("promoted_low_score")
        if x["tier"] == "skip" and p >= 75:
            kinds.append("demoted_high_score")
        if abs(x.get("adjust") or 0) >= 3:
            kinds.append("big_adjust")
        if kinds:
            out.append({"profile": profile, "key": k, "kinds": kinds, "tier": x["tier"],
                        "adjust": x.get("adjust") or 0, "score": s, "score_pct": round(p),
                        "confidence": x.get("confidence"), "why": x.get("why") or ""})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="write disagreement records (JSON) here")
    args = ap.parse_args()
    all_dis = []
    for path in sorted((ROOT / "data/verdicts").glob("*.json")):
        profile = path.stem
        store = load_store(path)
        if not store:
            continue
        conc, tier_n = concordance(store)
        adjusts = [x.get("adjust") or 0 for x in store.values()]
        nz = [a for a in adjusts if a]
        med_by_tier = {t: median([x["score_at_judge"] for x in store.values()
                                  if x["tier"] == t and x.get("score_at_judge") is not None])
                       for t in sorted(tier_n, key=TIER_ORD.get)}
        feed = ROOT / f"dashboard/data.{profile}.json"
        if profile == "default":
            feed = ROOT / "dashboard/data.json"
        dis = disagreements(profile, store)
        all_dis.extend(dis)
        print(f"\n== {profile} ({len(store)} verdicts) ==")
        print(f"  tiers: {tier_n}")
        print(f"  A. concordance(score vs tier): {round(conc, 3) if conc else None}"
              f" | median score by tier: {med_by_tier}")
        print(f"  B. adjust: {round(100 * (1 - len(nz) / len(adjusts)))}% zero"
              f" | mean|adj| {round(sum(map(abs, adjusts)) / len(adjusts), 2)}"
              f" | displacement: {displacement(store)}")
        if feed.exists():
            print(f"  C. slate impact: {slate_impact(feed, store)}")
        print(f"  D. disagreements: {len(dis)} "
              f"({round(100 * len(dis) / len(store))}% of verdicts)")
    if args.out:
        Path(args.out).write_text(json.dumps(all_dis, indent=1))
        print(f"\nwrote {len(all_dis)} disagreement records -> {args.out}")


if __name__ == "__main__":
    main()
