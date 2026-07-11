"""profiles.yaml helpers — the capability-token → feed-hash mapping (Track A1).

A profile's access key is a random `token` (secrets.token_hex(8), stored only in
profiles.yaml — the private token map). Its public feed key is
profile_hash(token, salt): the first 16 hex of sha256(salt + token). The dashboard
(Web Crypto), the concierge Worker, and every script here derive it the same way —
this module is the Python home for that derivation so the copies can't drift.

Usernames are NOT hashed anymore (v1 hashed lowercased usernames, which anyone could
derive — the privacy hole A1 closed). A profile without a token has no feed hash.
"""

import hashlib

DEFAULT_SALT = "la-events/v2:"


def profile_hash(token: str, salt: str = DEFAULT_SALT) -> str:
    """First 16 hex of sha256(salt + token). Mirrors the dashboard page (Web Crypto)
    and backend/concierge-worker.js profileHash() — keep all three in sync."""
    return hashlib.sha256((salt + token.strip().lower()).encode("utf-8")).hexdigest()[:16]


def entry_hash(entry: dict, salt: str = DEFAULT_SALT):
    """A manifest entry's feed hash, or None when it has no token (no token = no feed)."""
    tok = (entry or {}).get("token")
    return profile_hash(str(tok), salt) if tok else None


def hash_names(manifest: dict) -> dict:
    """{feed_hash: display name} for every tokened profile in a parsed profiles.yaml.
    Used to turn a reaction's profile hash back into a name ("★ Lori") for display."""
    salt = (manifest or {}).get("salt") or DEFAULT_SALT
    out = {}
    for p in (manifest or {}).get("profiles") or []:
        if not isinstance(p, dict):
            continue
        h = entry_hash(p, salt)
        if h:
            out[h] = p.get("name") or p.get("username") or h
    return out
