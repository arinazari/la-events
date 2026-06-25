#!/usr/bin/env python3
"""Report how much life is left in POSH_TOKEN — the proactive half of assisted re-auth.

Posh has no token-refresh endpoint (verified against the web client: the session JWT is
minted at OTP login and simply lapses after ~30 days). So instead of discovering a dead
token via a mid-digest 401, the daily routine runs this to nudge Ari a few days *before*
it expires, while a refresh is still a calm 30-second task.

The JWT is self-describing — its payload carries the expiry (`exp`/`expires`, which Posh
stamps in MILLISECONDS), so this reads it with no secret and no network call. It never
prints the token itself, only its expiry.

Status / exit code (so a routine or shell can branch on it):
  ok      / 0  — more than --warn-days of life left
  warn    / 3  — within --warn-days of expiry (re-auth soon)
  expired / 2  — past expiry, or token missing / unparseable (re-auth now)

Usage:
  python scripts/posh_token_status.py            # one-line human status
  python scripts/posh_token_status.py --json     # machine-readable, for the routine
  python scripts/posh_token_status.py --warn-days 7
"""

import argparse
import base64
import json
import os
import sys
from datetime import datetime, timezone

WARN_DAYS = 5


def _epoch_seconds(v):
    """Posh stamps exp/expires in ms; normalize anything that looks like ms to seconds."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    return v / 1000.0 if v > 1e11 else v  # ms epoch (~1.7e12) vs s epoch (~1.7e9)


def decode_exp(token: str):
    """Return the token's expiry as an aware UTC datetime, or None if undecodable."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except Exception:  # noqa: BLE001 — any malformed JWT → treat as undecodable
        return None
    for key in ("exp", "expires"):  # prefer standard `exp`, fall back to Posh's `expires`
        secs = _epoch_seconds(claims.get(key))
        if secs:
            try:
                return datetime.fromtimestamp(secs, tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                continue
    return None


def evaluate(token, now, warn_days):
    """-> (status, days_left|None, exp|None, message). Pure; no I/O."""
    if not token:
        return "expired", None, None, "POSH_TOKEN not set — re-capture it"
    exp = decode_exp(token)
    if exp is None:
        return "expired", None, None, "POSH_TOKEN unparseable — re-capture it"
    days = (exp - now).total_seconds() / 86400
    if days <= 0:
        return "expired", days, exp, f"POSH_TOKEN expired {-days:.1f}d ago — re-capture it"
    if days <= warn_days:
        return "warn", days, exp, f"POSH_TOKEN expires in {days:.1f}d — re-auth soon"
    return "ok", days, exp, f"POSH_TOKEN healthy — {days:.1f}d left"


EXIT = {"ok": 0, "warn": 3, "expired": 2}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--warn-days", type=int, default=WARN_DAYS,
                    help=f"days-before-expiry that flips status to warn (default {WARN_DAYS})")
    ap.add_argument("--json", action="store_true", help="emit a machine-readable status line")
    args = ap.parse_args()

    status, days, exp, msg = evaluate(os.environ.get("POSH_TOKEN"),
                                      datetime.now(timezone.utc), args.warn_days)
    if args.json:
        print(json.dumps({
            "status": status,
            "days_left": round(days, 2) if days is not None else None,
            "expires_utc": exp.isoformat() if exp else None,
            "message": msg,
        }))
    else:
        print(msg, file=sys.stderr if status != "ok" else sys.stdout)
    return EXIT[status]


if __name__ == "__main__":
    raise SystemExit(main())
