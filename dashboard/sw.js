/* Minimal service worker: cache the app shell so the dashboard opens offline.
 * The HTML and data.json are fetched network-first (fall back to cache) so the
 * app updates as soon as a new version ships; the heavy static assets
 * (support.js, vendored React/Babel) stay cache-first for fast offline loads.
 *
 * Bump CACHE whenever a cache-first asset below changes — that byte change is
 * what makes the browser re-install this worker and re-fetch the shell. */

const CACHE = "la-events-v7";
const SHELL = [
  "./",
  "./index.html",
  "./manifest.webmanifest",
  "./icon.svg",
  "./support.js",
  "./calendar-core.js",
  "./vendor/react.production.min.js",
  "./vendor/react-dom.production.min.js",
  "./vendor/babel.min.js",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== self.location.origin) return;

  // Network-first for the HTML and the data feed so the app updates the moment a
  // new version ships (fall back to cache offline); cache-first for everything else.
  const netFirst = e.request.mode === "navigate" ||
    url.pathname.endsWith("/index.html") || url.pathname.endsWith("/") ||
    url.pathname.endsWith("/data.json");
  if (netFirst) {
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
