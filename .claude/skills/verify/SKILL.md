---
name: verify
description: Build/launch/drive recipe for verifying dashboard changes end-to-end in headless Chromium (cloud sessions).
---

# Verifying dashboard changes

The dashboard is a static page (`dashboard/index.html`, in-browser Babel — no build step).
Drive it in a real browser; don't import functions out of it.

## Launch

```bash
cd dashboard && python3 -m http.server 8931 --bind 127.0.0.1 &   # serves index.html + data feeds
```

Playwright is preinstalled system-wide in cloud sessions but not as a project dep:
`npm i playwright` in a scratch dir, then launch with
`chromium.launch({ executablePath: '/opt/pw-browsers/chromium' })` — never `playwright install`.

## Drive

- Page boot takes ~4s headless (in-browser Babel compile + React mount) before asserting.
- Boot order (componentDidMount): `migrateLegacyConn()` → feed load → `pingBackend()` POST to
  `BACKEND_URL`. Intercept with `page.route('**://la-events-concierge.arinazari.workers.dev/**', ...)`
  and fulfill `{"ok":true}` to keep runs hermetic; `{ping:true}` needs no LLM.
- Sign in a profile by seeding localStorage via `context.addInitScript`:
  `la-profile = {"hash":"<h>","name":"..."}` where
  `<h> = sha256('la-events/v1:' + username).hex.slice(0,16)` (feeds: `dashboard/data.<h>.json`).
- A fresh profile auto-opens the welcome overlay and its backdrop swallows clicks — seed
  `la-onboarded:<hash> = '1'` (returning user) or press Escape first.
- The connect pill (chat header) renders only when a profile is signed in (`showConnect`).

## Expected local noise

`/digests/latest.md` and `/digests/index.json` 404 locally — CI stages `dashboard/digests/`
into the Pages artifact; they are not in the repo. Any other 404 or pageerror is a finding.
