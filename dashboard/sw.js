/* Minimal service worker: cache the app shell so the dashboard opens offline.
 * data.json is fetched network-first (fall back to cache) so it stays fresh. */

const CACHE = "la-events-v3";
const SHELL = [
  "./",
  "./index.html",
  "./manifest.webmanifest",
  "./icon.svg",
  "./support.js",
  "./vendor/react.production.min.js",
  "./vendor/react-dom.production.min.js",
  "./vendor/babel.min.js",
];

// Non-disruptive lifecycle: we deliberately do NOT call skipWaiting() or
// clients.claim(). Claiming an already-open page that loaded WITHOUT a controller
// (i.e. the very first visit) makes the worker take over mid-session — which iOS/
// macOS Safari turns into a full page reload. That's the "site reloads on the first
// few interactions after a cold start, then stops" bug: it stops because the next
// load is already controlled. By not claiming, the first load stays stable and the
// worker only takes control on the NEXT navigation. Tradeoff: offline caching kicks
// in from the second visit rather than the first — fine for a catalog viewer.
// Don't re-add skipWaiting()/clients.claim() without accounting for this.
self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
});

self.addEventListener("activate", (e) => {
  // Still purge stale shell caches from older versions — just don't claim clients.
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== self.location.origin) return;

  // Network-first for the data feed; cache-first for everything else.
  if (url.pathname.endsWith("/data.json")) {
    e.respondWith(
      fetch(e.request)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
          return res;
        })
        .catch(() => caches.match(e.request))
    );
    return;
  }

  e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request)));
});
