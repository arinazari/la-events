/**
 * la-events concierge backend — a Cloudflare Worker (the BACKEND_URL the dashboard POSTs to).
 *
 * Why this exists: the dashboard is a static GitHub Pages site, so it can't hold an API key
 * or call an LLM directly. This Worker is the one place that does: it holds ANTHROPIC_API_KEY,
 * grounds the model on the live catalog + dining feed, and answers in the LA-insider concierge
 * voice. The page's "Concierge" mode POSTs here; "Fast filter" mode never touches it.
 *
 * Contract:
 *   POST  { messages: [{role:'user'|'assistant', content:string}, ...] }
 *   ->    { reply: string }
 *   Auth: optional `Authorization: Bearer <CONCIERGE_TOKEN>` (set CONCIERGE_TOKEN to require it;
 *         leave it unset and the proxy is OPEN to anyone who finds the URL — see README).
 *
 * Env (wrangler secrets / vars):
 *   ANTHROPIC_API_KEY  (secret, required)
 *   CONCIERGE_TOKEN    (secret, optional — shared token gating the proxy)
 *   ANTHROPIC_MODEL    (var, optional — defaults to a current Claude model)
 *   DATA_URL           (var, optional — the published data.json to ground on)
 *   ALLOWED_ORIGIN     (var, optional — CORS origin; defaults to the Pages site)
 */

const DEFAULTS = {
  ANTHROPIC_MODEL: "claude-sonnet-4-6",
  DATA_URL: "https://arinazari.github.io/la-events/data.json",
  ALLOWED_ORIGIN: "https://arinazari.github.io",
  MAX_EVENTS: 220,     // cap grounding context (events are ~700; dining is small, sent whole)
  MAX_TOKENS: 1024,
};

export default {
  async fetch(request, env) {
    const origin = env.ALLOWED_ORIGIN || DEFAULTS.ALLOWED_ORIGIN;
    const cors = {
      "Access-Control-Allow-Origin": origin,
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "content-type, authorization",
      "Access-Control-Max-Age": "86400",
    };
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    if (request.method !== "POST") return json({ error: "POST only" }, 405, cors);

    // Optional shared-token gate.
    if (env.CONCIERGE_TOKEN) {
      const auth = request.headers.get("authorization") || "";
      if (auth !== "Bearer " + env.CONCIERGE_TOKEN) return json({ error: "unauthorized" }, 401, cors);
    }
    if (!env.ANTHROPIC_API_KEY) return json({ error: "server missing ANTHROPIC_API_KEY" }, 500, cors);

    let body;
    try { body = await request.json(); } catch { return json({ error: "bad json" }, 400, cors); }
    const messages = sanitizeMessages(body && body.messages);
    if (!messages.length) return json({ error: "no messages" }, 400, cors);

    // Ground on the live feed (best-effort; a fetch failure just means a thinner context).
    let feed = null;
    try {
      const r = await fetch(env.DATA_URL || DEFAULTS.DATA_URL, { cf: { cacheTtl: 300 } });
      if (r.ok) feed = await r.json();
    } catch { /* degrade gracefully */ }

    const system = buildSystem(feed);

    const resp = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-api-key": env.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify({
        model: env.ANTHROPIC_MODEL || DEFAULTS.ANTHROPIC_MODEL,
        max_tokens: DEFAULTS.MAX_TOKENS,
        system,
        messages,
      }),
    });

    if (!resp.ok) {
      const detail = await resp.text().catch(() => "");
      return json({ error: "anthropic " + resp.status, detail: detail.slice(0, 400) }, 502, cors);
    }
    const data = await resp.json();
    const reply = (data.content || []).filter((b) => b.type === "text").map((b) => b.text).join("\n").trim();
    return json({ reply: reply || "(no answer)" }, 200, cors);
  },
};

function json(obj, status, cors) {
  return new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json", ...cors } });
}

/* Keep only well-formed user/assistant turns; cap history so context stays cheap. */
function sanitizeMessages(msgs) {
  if (!Array.isArray(msgs)) return [];
  const out = [];
  for (const m of msgs.slice(-8)) {
    if (!m || typeof m.content !== "string" || !m.content.trim()) continue;
    const role = m.role === "assistant" ? "assistant" : "user";
    out.push({ role, content: m.content.slice(0, 2000) });
  }
  // Anthropic requires the conversation to start with a user turn.
  while (out.length && out[0].role !== "user") out.shift();
  return out;
}

/* Build the system prompt: the concierge persona + a compact, grounded snapshot of the feed. */
function buildSystem(feed) {
  const today = new Date().toISOString().slice(0, 10);
  const persona = [
    "You are Ari's personal LA going-out concierge — a knowledgeable insider with strong taste,",
    "not a generic chatbot. Voice: conversational, opinionated, concise; no sycophancy, no padding.",
    `Today is ${today} (America/Los_Angeles).`,
    "",
    "You can do three things with the data below: (1) ANSWER questions about events, venues,",
    "restaurants, artists, neighborhoods; (2) RECOMMEND with a one-line 'why' per pick; (3) PLAN a",
    "night — sequence dinner → show → afters, pairing the dining list with on-taste events, and",
    "noting rough proximity (you don't have exact travel times — approximate and say so).",
    "",
    "Rules: ground every claim in the DATA — if something isn't in it, say so plainly rather than",
    "inventing it (e.g. don't fabricate a venue or a showtime). Prefer higher-rated, on-taste picks.",
    "Lead with the answer/pick, keep it tight, surface ticket/booking links when relevant.",
  ].join("\n");

  if (!feed) return persona + "\n\n(DATA unavailable this request — answer from the conversation, and say your catalog access is temporarily down.)";

  const taste = feed.taste || (feed.config && feed.config.taste) || {};
  const tasteLine = [
    taste.venues_loved && taste.venues_loved.length ? "Loved venues: " + taste.venues_loved.join(", ") : null,
    taste.artists_tracked && taste.artists_tracked.length ? "Tracked artists: " + taste.artists_tracked.slice(0, 30).join(", ") : null,
  ].filter(Boolean).join(" | ");

  const dining = (feed.dining || []).map((r) =>
    `- ${r.name} — ${r.neighborhood || "LA"}${r.price ? " · " + r.price : ""}` +
    `${r.cuisine && r.cuisine.length ? " · " + r.cuisine.join("/") : ""}` +
    `${r.notes ? " — " + r.notes : ""}${r.reservation_url ? " [" + r.reservation_url + "]" : ""}`
  ).join("\n");

  const today2 = today;
  const events = (feed.events || [])
    .filter((e) => !e.is_past && (e.iso_date || "") >= today2)
    .sort((a, b) => (a.iso_date || "").localeCompare(b.iso_date || "") || (b.rating || 0) - (a.rating || 0))
    .slice(0, DEFAULTS.MAX_EVENTS)
    .map((e) => {
      const link = (e.links && e.links[0] && e.links[0].url) || "";
      const why = Array.isArray(e.reasons) ? e.reasons.slice(0, 3).join("; ") : "";
      return `- ${e.title} — ${e.venue || "TBA"}${e.neighborhood ? ", " + e.neighborhood : ""}` +
        ` · ${e.iso_date}${e.start ? " " + e.start : ""} · ${e.category || ""} · ★${e.rating || "?"}` +
        `${why ? " · " + why : ""}${link ? " [" + link + "]" : ""}`;
    }).join("\n");

  return [
    persona,
    "",
    tasteLine ? "TASTE: " + tasteLine : "",
    "",
    `RESTAURANTS (la-dining, ${(feed.dining || []).length}):`,
    dining || "(none)",
    "",
    `UPCOMING EVENTS (top ${Math.min(DEFAULTS.MAX_EVENTS, (feed.events || []).length)} by date, ★ = taste rating):`,
    events || "(none)",
  ].join("\n");
}
