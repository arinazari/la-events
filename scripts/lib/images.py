"""Image caching — pull enrichment hero images into the repo so digests don't rot.

scene-researcher returns an `image: {url, source, credit}` for the top picks. Those URLs
hotlink third-party CDNs that expire. This downloads them into data/images/<event_key>.<ext>
once, defensively (content-type + size guards, never blocks), and records image["cached"]
(a repo-relative path) on the enrichment record. The renderer prefers the cached copy.

  cache_image(url, key, dest_dir)        -> repo-relative path | None  (skip-if-exists)
  cache_enriched_images(cache, dest_dir) -> count   (updates image["cached"] in place)
"""

import re
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
MAX_BYTES = 6_000_000
EXT_BY_TYPE = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
               "image/webp": ".webp", "image/gif": ".gif", "image/avif": ".avif"}


def _rel(p: Path) -> str:
    return str(p.relative_to(REPO)) if p.is_relative_to(REPO) else str(p)


def _ext(content_type: str, url: str) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in EXT_BY_TYPE:
        return EXT_BY_TYPE[ct]
    m = re.search(r"\.(jpe?g|png|webp|gif|avif)\b", url, re.I)
    return "." + m.group(1).lower().replace("jpeg", "jpg") if m else ".jpg"


def cache_image(url: str, key: str, dest_dir, timeout: int = 15):
    """Download url -> dest_dir/<key>.<ext>; return a repo-relative path, or None on any failure.
    Idempotent: if a file for this key already exists, return it without re-fetching."""
    dest = Path(dest_dir)
    if dest.exists():
        existing = next((p for p in dest.glob(f"{key}.*")), None)
        if existing:
            return _rel(existing)
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ct = r.headers.get("Content-Type", "")
            if not ct.lower().startswith("image/"):
                return None
            data = r.read(MAX_BYTES + 1)
        if not data or len(data) > MAX_BYTES:
            return None
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / f"{key}{_ext(ct, url)}"
        path.write_bytes(data)
        return _rel(path)
    except Exception:
        return None


def cache_enriched_images(cache: dict, dest_dir, timeout: int = 15) -> int:
    """Download images for every cached event that has image.url but no image.cached.
    Mutates the cache (sets image['cached']); caller saves it. Returns how many were cached."""
    n = 0
    for key, ev in (cache.get("events") or {}).items():
        img = ev.get("image") or {}
        if not img.get("url") or img.get("cached"):
            continue
        rel = cache_image(img["url"], key, dest_dir, timeout)
        if rel:
            img["cached"] = rel
            n += 1
    return n
