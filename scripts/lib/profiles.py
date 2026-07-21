"""profiles.yaml helpers — hash <-> display-name resolution.

The feed hash is name-derived: sha256(salt + username.lower())[:16], the SAME computation as
scripts/build_profiles.py:profile_hash, the Worker's profileHash, and the browser's Web-Crypto —
so a hash resolves back to a person's display name identically everywhere.

`hash_names(manifest)` is the {hash: name} map the stars fold (lib/reactions.stars_for) needs to
turn a reaction's profile hash into "★ Lori". Kept as its own module so build_dashboard.py and
render_digest.py share one resolver.

Note: when Track A (capability tokens replacing name-derived hashes) lands, this module's hashing
becomes token-derived — a clean, expected replacement. Everything downstream is hash-agnostic.
"""

import hashlib

DEFAULT_SALT = "la-events/v1:"


def profile_hash(username: str, salt: str = DEFAULT_SALT) -> str:
    return hashlib.sha256((salt + str(username).strip().lower()).encode("utf-8")).hexdigest()[:16]


def hash_names(manifest: dict) -> dict:
    """{feed-hash: display-name} for every profile in profiles.yaml."""
    salt = (manifest or {}).get("salt") or DEFAULT_SALT
    out = {}
    for p in (manifest or {}).get("profiles") or []:
        if not isinstance(p, dict) or not p.get("username"):
            continue
        h = profile_hash(p["username"], salt)
        out[h] = p.get("name") or p.get("username") or h
    return out
