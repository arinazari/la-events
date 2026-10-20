/**
 * Node tests for the Worker's per-profile Spotify routes — the Development-mode failure path:
 * Spotify hands any account a token, then 403s every API call for accounts not on the app's
 * Users Management allowlist. The callback must keep the token but say so (and flag `blocked`, in
 * its own blk:<hash> key — never by rewriting the token record), /spotify/fetch must carry Spotify's
 * own error text and backfill the flag for accounts connected earlier, and a later success clears it.
 * Run: `cd backend && npm i && node test-spotify.mjs`. No network — global fetch + KV are stubbed.
 */
import assert from "node:assert";
import worker from "./concierge-worker.js";

let passed = 0;
const ok = (name) => { console.log("ok  " + name); passed++; };

const HASH = "07f7c7077c28169c";
const kvStore = new Map();
const env = {
  SPOTIFY_KV: {
    get: async (k) => (kvStore.has(k) ? kvStore.get(k) : null),
    put: async (k, v) => { kvStore.set(k, v); },
    delete: async (k) => { kvStore.delete(k); },
    list: async () => ({ keys: [...kvStore.keys()].map((name) => ({ name })), list_complete: true }),
  },
  SPOTIFY_CLIENT_ID: "cid", SPOTIFY_CLIENT_SECRET: "csecret",
  SPOTIFY_SYNC_TOKEN: "sync-token", STATE_SECRET: "state-secret", GITHUB_TOKEN: "gh",
  SPOTIFY_REDIRECT_URI: "https://worker.test/spotify/callback", PAGE_URL: "https://page.test/",
};
const BASE = "https://worker.test";

// Stub upstreams: token endpoint OK; Spotify API 403s (not registered) until `allowlisted`;
// `meDown` makes /me a transient 503 (an outage, not a block).
let allowlisted = false, meDown = false;
const dispatched = [];
const NOT_REGISTERED = JSON.stringify({ error: { status: 403, message: "The user is not registered for this application" } });
globalThis.fetch = async (url, init = {}) => {
  const u = String(url);
  if (u.startsWith("https://accounts.spotify.com/api/token"))
    return new Response(JSON.stringify({ access_token: "acc", refresh_token: "rt-1" }), { status: 200 });
  if (u.startsWith("https://api.github.com/")) { dispatched.push(JSON.parse(init.body)); return new Response("", { status: 204 }); }
  if (u.startsWith("https://api.spotify.com/v1/")) {
    if (meDown && u.endsWith("/me")) return new Response("Service unavailable", { status: 503 });
    if (!allowlisted) return new Response(NOT_REGISTERED, { status: 403 });
    if (u.includes("/me/following")) return new Response(JSON.stringify({ artists: { items: [], cursors: {} } }), { status: 200 });
    if (u.endsWith("/me")) return new Response(JSON.stringify({ display_name: "Levon" }), { status: 200 });
    return new Response(JSON.stringify({ items: [{ name: "Aphex Twin" }] }), { status: 200 });
  }
  throw new Error("unexpected fetch " + u);
};

const waits = [];
const ctx = { waitUntil: (p) => waits.push(p) };
const call = (path, init) => worker.fetch(new Request(BASE + path, init), env, ctx);

// The login redirect carries a signed state; reuse it on the callback like Spotify would.
const login = await call(`/spotify/login?profile=${HASH}`);
const state = new URL(login.headers.get("location")).searchParams.get("state");
assert.ok(state, "login redirect carries a signed state");

{
  const r = await call(`/spotify/callback?code=c&state=${encodeURIComponent(state)}`);
  const html = await r.text();
  assert.match(html, /isn't sharing your listening with this app yet/);
  assert.doesNotMatch(html, /Spotify connected/);
  const rec = JSON.parse(kvStore.get("rt:" + HASH));
  assert.equal(rec.rt, "rt-1", "token kept so it works once allowlisted");
  assert.equal(rec.blocked, undefined, "the token record itself is never rewritten with the flag");
  assert.match(kvStore.get("blk:" + HASH), /^403 \/v1\/me .*not registered/);
  await Promise.all(waits);
  assert.equal(waits.length, 1, "dispatch handed to ctx.waitUntil");
  assert.equal(dispatched[0].event_type, "spotify-sync");
  ok("callback: a 403'd account keeps its token, is flagged blocked, and is told why");
}
{
  const s = await (await call(`/spotify/status?profile=${HASH}`)).json();
  assert.equal(s.connected, true);
  assert.match(s.blocked, /not registered/);
  assert.ok(!JSON.stringify(s).includes("rt-1"), "status never leaks the token");
  ok("status exposes the blocked reason, never the token");
}
{
  const r = await call(`/spotify/fetch?profile=${HASH}`, { headers: { authorization: "Bearer sync-token" } });
  assert.equal(r.status, 502);
  const j = await r.json();
  assert.equal(j.error, "spotify fetch failed");
  assert.match(j.detail, /^403 \/v1\/me\/top\/artists .*The user is not registered for this application/);
  ok("fetch: the 502 detail carries Spotify's own 403 message");
}
{
  // An account connected BEFORE the callback flagged blocks has no blk key; the nightly sync's
  // 403 backfills it so /spotify/status (and the dashboard) can finally say why.
  kvStore.delete("blk:" + HASH);
  const r = await call(`/spotify/fetch?profile=${HASH}`, { headers: { authorization: "Bearer sync-token" } });
  assert.equal(r.status, 502);
  assert.match(kvStore.get("blk:" + HASH), /not registered/);
  ok("fetch: a 403 pull backfills the blocked flag for an older connection");
}
{
  allowlisted = true;
  const r = await call(`/spotify/fetch?profile=${HASH}`, { headers: { authorization: "Bearer sync-token" } });
  assert.equal(r.status, 200);
  const j = await r.json();
  assert.equal(j.top.long_term[0].name, "Aphex Twin");
  assert.equal(kvStore.has("blk:" + HASH), false, "stale blocked flag cleared");
  assert.equal(JSON.parse(kvStore.get("rt:" + HASH)).rt, "rt-1");
  ok("fetch: once allowlisted, the pull succeeds and the blocked flag clears");
}
{
  kvStore.clear(); waits.length = 0;
  const r = await call(`/spotify/callback?code=c&state=${encodeURIComponent(state)}`);
  assert.match(await r.text(), /Spotify connected — hey Levon!/);
  assert.equal(kvStore.has("blk:" + HASH), false);
  ok("callback: an allowed account still gets the normal connected page");
}
{
  kvStore.clear(); meDown = true;
  const r = await call(`/spotify/callback?code=c&state=${encodeURIComponent(state)}`);
  assert.match(await r.text(), /Spotify connected!/);
  assert.equal(kvStore.has("blk:" + HASH), false, "a transient /me 503 is not a Development-mode block");
  meDown = false;
  ok("callback: a transient /me failure doesn't flag the account blocked");
}
{
  kvStore.set("blk:" + HASH, "403 /v1/me not registered");
  await call("/spotify/disconnect", { method: "POST", body: JSON.stringify({ profile: HASH }) });
  assert.equal(kvStore.has("rt:" + HASH) || kvStore.has("blk:" + HASH), false);
  ok("disconnect forgets the token and the blocked flag");
}

console.log(`\n${passed} spotify tests passed`);
