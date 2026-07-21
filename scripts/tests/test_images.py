#!/usr/bin/env python3
"""Tests for scripts/lib/images.py — deterministic image-URL extraction (the cheap path).

Run: python scripts/tests/test_images.py   (also pytest-compatible)
Anchored on the real source shapes: TM's images[] array, schema.org `image` (str | ImageObject |
list), AXS's keyed `media` dict, and the HTTPS-only / CSS-safe `clean()` gate.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
from lib import images as I  # noqa: E402


def test_clean_https_only():
    assert I.clean("https://cdn/x.jpg") == "https://cdn/x.jpg"
    assert I.clean("  https://cdn/x.jpg  ") == "https://cdn/x.jpg"      # trimmed
    assert I.clean("//cdn/x.jpg") == "https://cdn/x.jpg"                # protocol-relative -> https
    assert I.clean("http://cdn/x.jpg") is None                          # http blocked (mixed content)
    assert I.clean("ftp://cdn/x.jpg") is None
    assert I.clean("") is None and I.clean(None) is None and I.clean(123) is None


def test_clean_rejects_context_breakers():
    # Anything that could break out of the dashboard's url('…') CSS / HTML-attribute context.
    assert I.clean("https://cdn/a'b.jpg") is None
    assert I.clean('https://cdn/a".jpg') is None
    assert I.clean("https://cdn/a b.jpg") is None                       # whitespace
    assert I.clean("https://cdn/a<b.jpg") is None
    assert I.clean("https://cdn/a\\b.jpg") is None
    # …but query params, commas and parens are legal URL characters and safe inside the quotes.
    assert I.clean("https://cdn/x.jpg?w=640&h=360,fit(crop)") == "https://cdn/x.jpg?w=640&h=360,fit(crop)"


def test_clean_length_cap():
    assert I.clean("https://cdn/" + "a" * 5000) is None


def test_from_tm_prefers_real_16x9_widest():
    imgs = [
        {"ratio": "3_2", "url": "https://x/a.jpg", "width": 640, "fallback": False},
        {"ratio": "16_9", "url": "https://x/b.jpg", "width": 2048, "fallback": False},
        {"ratio": "16_9", "url": "https://x/big-but-fallback.jpg", "width": 3000, "fallback": True},
    ]
    assert I.from_tm(imgs) == "https://x/b.jpg"                          # non-fallback 16:9 widest


def test_from_tm_fallback_last_resort_and_empties():
    assert I.from_tm([{"url": "https://x/only.jpg", "width": 100, "fallback": True}]) == "https://x/only.jpg"
    assert I.from_tm([]) is None
    assert I.from_tm(None) is None
    assert I.from_tm([{"width": 100}]) is None                          # no url -> nothing


def test_from_jsonld_shapes():
    assert I.from_jsonld("https://x/a.jpg") == "https://x/a.jpg"        # bare string
    assert I.from_jsonld({"url": "https://x/b.jpg"}) == "https://x/b.jpg"        # ImageObject.url
    assert I.from_jsonld({"contentUrl": "https://x/c.jpg"}) == "https://x/c.jpg" # ImageObject.contentUrl
    assert I.from_jsonld(["https://x/d.jpg", "https://x/e.jpg"]) == "https://x/d.jpg"  # first of a list
    assert I.from_jsonld([{"url": "http://x/skip.jpg"}, "https://x/f.jpg"]) == "https://x/f.jpg"  # skip unclean
    assert I.from_jsonld(None) is None and I.from_jsonld([]) is None and I.from_jsonld({}) is None


def test_from_axs_media_largest_by_area():
    media = {
        "17": {"width": 678, "height": 399, "file_name": "https://a/big.jpg"},
        "1": {"width": 318, "height": 187, "file_name": "https://a/small.jpg"},
        "2": {"width": 238, "height": 140, "file_name": "https://a/tiny.jpg"},
    }
    assert I.from_axs_media(media) == "https://a/big.jpg"
    # list form + a member missing dims still resolves the biggest usable
    assert I.from_axs_media([{"file_name": "https://a/x.jpg", "width": 10, "height": 10}]) == "https://a/x.jpg"
    assert I.from_axs_media(None) is None and I.from_axs_media("nope") is None


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except AssertionError as e:
                fails += 1
                print("FAIL", name, "-", repr(e))
    print(f"\n{'ALL PASS' if not fails else str(fails)+' FAILED'}")
    sys.exit(1 if fails else 0)
