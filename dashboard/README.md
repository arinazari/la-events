# Dashboard

A self-contained, static dashboard for exploring the event catalog with filters for
**date, type, location, and recommended rating** — the visual companion to the markdown
digest. No framework, no build step.

## How it fits together

```
data/catalog.json ──┐
                    ├─► scripts/build_dashboard.py ─► dashboard/data.json ─► index.html
taste.yaml ─────────┘     (scores each event,                (static viewer,
                           writes a 1–5 rating)                filters client-side)
```

- **`scripts/build_dashboard.py`** reads the catalog + `taste.yaml`, scores every event
  the same way the digest cares about (category interest, Fri/Sat, proximity to Silver
  Lake, RA picks, afterhours, editorial mentions, loved venues, tracked artists, minus
  bottle-service / mega-rave penalties), maps the score to a **1–5 star "recommended for
  you" rating**, and writes `dashboard/data.json`.
- **`index.html` / `app.js` / `styles.css`** are a pure viewer. The dashboard never
  scores — re-run the build script to refresh ratings/data.

`data.json` is committed so the dashboard works on GitHub Pages without a backend.

## Use it

```bash
# Build the feed from the real catalog (default input: data/catalog.json)
python scripts/build_dashboard.py

# ...or from the bundled demo data while the catalog is still filling up:
python scripts/build_dashboard.py -i data/sample-catalog.json

# View locally (any static server; the SW + fetch need http, not file://)
cd dashboard && python -m http.server 8000
# open http://localhost:8000
```

`data.json` carries an `is_sample` flag; when it's built from `data/sample-catalog.json`
the header shows a **SAMPLE DATA** badge so demo data is never mistaken for the real feed.

## Filters

- **Search** — title, venue, artist/lineup, neighborhood, genre.
- **Type** — toggle category pills (electronic, live music, comedy, film, theater,
  beer & food…); multiple = OR.
- **Location** — neighborhood dropdown.
- **From / To date** — inclusive range.
- **Recommended rating** — click a star for "N+ stars".
- Plus: hide-past toggle, sort by date or rating, and a Reset.

Each card's **"why?"** link expands the per-event scoring breakdown, so a rating is never
a black box. **"＋ Calendar"** downloads a standard `.ics` for that event (start/end,
venue, lineup, ticket link) — generated entirely client-side, opens in Apple/Google/
Outlook calendars. Times are written as floating local time (correct for LA).

## Keeping it fresh

The digest routine should regenerate this after writing the catalog. Add to the daily
routine (or run manually):

```bash
python scripts/build_dashboard.py && git add dashboard/data.json
```

## Hosting on GitHub Pages

`.github/workflows/deploy-dashboard.yml` publishes the `dashboard/` folder to Pages on
every push to `main` that touches it (and via manual "Run workflow"). One-time setup:

> **Settings → Pages → Build and deployment → Source: GitHub Actions**

After that, the site is served with `dashboard/` as its root, so it loads `./data.json`
relative to itself — no path changes needed. A web manifest + service worker make it
installable and openable offline on a phone, so it doubles as the lightweight PWA that is
the Phase 3 frontend in `ROADMAP.md`.

Locally you don't need any of this — just `python -m http.server` as above.
