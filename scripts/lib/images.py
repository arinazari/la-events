"""Event image-URL extraction for the fetch layer — the CHEAP path to event photos.

Event photos on the dashboard's top-events row come straight from the structured source
responses the fetchers ALREADY download and parse. That's the whole point: no scene-researcher,
no WebFetch, no WebSearch — extracting an image URL from a response we've already got in hand is
pure deterministic parsing, so it costs ZERO extra network and ZERO LLM tokens. Every source that
carries art hands it over for free:

  Ticketmaster  ev["images"]         -> from_tm     (an array of {url,width,ratio,fallback})
  Resident Adv. event.flyerFront     -> clean       (one extra field on the same GraphQL POST)
  schema.org    ev["image"]          -> from_jsonld (JSON-LD Event `image`: str | ImageObject | list)
  DICE          MusicEvent `image`   -> from_jsonld (DICE's JSON-LD is schema.org too)
  Eventbrite    (via fetch_jsonld)   -> from_jsonld (reuses the JSON-LD parser)
  Squarespace   item["assetUrl"]     -> clean       (Squarespace's primary-image field)
  Posh          ev["flyer"]          -> clean       (already parsed; just the canonical field name)
  Goldenvoice   ev["media"]          -> from_axs_media (AXS {key:{width,height,file_name}})

Each helper returns ONE clean URL string (the best available) or None. The fetcher stores it on the
event as `image`; pipeline.normalize_record forwards it (re-cleaning as the single final gate) and
dedupe.merge keeps it across duplicate sources. A source with no art just yields None — never an error.

`clean()` is deliberately strict: HTTPS only (the deployed dashboard is HTTPS, so an http:// image is
blocked as mixed content and would only ever render broken — better to drop it and show no photo), and
no characters that could break out of the `url('…')` CSS context the dashboard renders it in.
"""

import re

# A URL longer than this is almost certainly a data: blob or junk, not a CDN image link.
_MAX_LEN = 2048
# Characters that could break the HTML-attribute / CSS `url('…')` context the dashboard uses, or
# smuggle markup: quotes, angle brackets, backtick, backslash, and anything <= space (incl. spaces
# and control chars). Parens/commas are allowed — they're valid in URLs and safe inside the quoted
# CSS string. Extraction is deterministic, but URLs come from third-party feeds, so we sanitize.
_UNSAFE = re.compile(r"""['"<>`\\\x00-\x20]""")


def clean(url):
    """Return a safe, absolute HTTPS image URL, or None.

    Rules: strip surrounding whitespace; upgrade a protocol-relative `//host/x` to `https://`;
    require an `https://` scheme (see module note on mixed content); reject over-long URLs and any
    that carry a context-breaking character. Idempotent — re-cleaning an already-clean URL is a no-op.
    """
    if not url or not isinstance(url, str):
        return None
    u = url.strip()
    if u.startswith("//"):                      # protocol-relative -> the dashboard is HTTPS
        u = "https:" + u
    if not u.lower().startswith("https://"):     # http:// would be blocked as mixed content anyway
        return None
    if len(u) > _MAX_LEN:
        return None
    if _UNSAFE.search(u):
        return None
    return u


def from_jsonld(value):
    """Best image URL from a schema.org `image` value.

    schema.org lets `image` be a bare URL string, an ImageObject ({url|contentUrl|@id}), or a list of
    either — take the first that cleans. Used for JSON-LD venues, DICE, and Eventbrite (all schema.org).
    """
    if not value:
        return None
    if isinstance(value, str):
        return clean(value)
    if isinstance(value, dict):
        return clean(value.get("url") or value.get("contentUrl") or value.get("@id"))
    if isinstance(value, list):
        for item in value:
            u = from_jsonld(item)
            if u:
                return u
    return None


def from_tm(images):
    """Best image URL from Ticketmaster's `images` array ({url,width,height,ratio,fallback}).

    Prefer a real (non-fallback) image, in 16:9 (a clean banner crop), at the widest resolution
    available; the browser scales it down. TM `fallback:true` images are generic category placeholders
    — deprioritized so a genuine event image always wins, but still used as a last resort so a
    placeholder is better than a blank card only when there's literally nothing else.
    """
    if not isinstance(images, list):
        return None
    cands = [im for im in images if isinstance(im, dict) and im.get("url")]
    if not cands:
        return None

    def rank(im):
        return (
            0 if im.get("fallback") else 1,          # real image before a generic placeholder
            1 if im.get("ratio") == "16_9" else 0,   # a landscape banner crop
            im.get("width") or 0,                    # widest = crispest
        )

    return clean(max(cands, key=rank).get("url"))


def from_axs_media(media):
    """Best image URL from a Goldenvoice/AXS `media` value.

    AXS ships media as a dict keyed by numeric strings, each {media_id, width, height, file_name(url)}
    (a list of the same shape is also accepted). Pick the largest by pixel area — the biggest is the
    event hero; the smaller ones are thumbnails.
    """
    if isinstance(media, dict):
        items = list(media.values())
    elif isinstance(media, list):
        items = media
    else:
        return None
    best, best_area = None, -1
    for it in items:
        if not isinstance(it, dict):
            continue
        url = it.get("file_name") or it.get("url")
        if not url:
            continue
        area = (it.get("width") or 0) * (it.get("height") or 0)
        if area >= best_area:
            best, best_area = url, area
    return clean(best)
