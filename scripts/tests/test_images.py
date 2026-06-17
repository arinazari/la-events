#!/usr/bin/env python3
"""Tests for scripts/lib/images.py — the non-network logic (skip-existing, ext, update loop).

Run: python scripts/tests/test_images.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import images as IM  # noqa: E402


def test_ext_detection():
    assert IM._ext("image/png", "x") == ".png"
    assert IM._ext("image/jpeg; charset=binary", "x") == ".jpg"
    assert IM._ext("", "https://a/b/photo.WEBP?x=1") == ".webp"
    assert IM._ext("", "https://a/no-extension") == ".jpg"          # default


def test_cache_image_skips_existing_without_network():
    with tempfile.TemporaryDirectory() as d:
        existing = Path(d) / "abc123.png"
        existing.write_bytes(b"\x89PNG fake")
        # URL is bogus on purpose — must NOT be fetched because the file exists.
        out = IM.cache_image("http://0.0.0.0/should-not-fetch.png", "abc123", d)
        assert out and out.endswith("abc123.png")


def test_cache_enriched_images_updates_records():
    cache = {"events": {
        "k1": {"image": {"url": "http://x/1.jpg"}},
        "k2": {"image": {"url": "http://x/2.jpg", "cached": "data/images/k2.jpg"}},  # already cached -> skip
        "k3": {},                                                                    # no image -> skip
    }, "artists": {}}
    calls = []

    def fake(url, key, dest, timeout=15):
        calls.append(key)
        return f"data/images/{key}.jpg"

    orig = IM.cache_image
    IM.cache_image = fake
    try:
        n = IM.cache_enriched_images(cache, "/tmp/whatever")
    finally:
        IM.cache_image = orig
    assert calls == ["k1"]                                  # only the uncached-with-url one
    assert n == 1
    assert cache["events"]["k1"]["image"]["cached"] == "data/images/k1.jpg"


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("PASS", name)
            except AssertionError as e:
                fails += 1; print("FAIL", name, "-", repr(e))
    print(f"\n{'ALL PASS' if not fails else str(fails)+' FAILED'}")
    sys.exit(1 if fails else 0)
