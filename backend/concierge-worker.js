/**
 * la-events concierge backend — a Cloudflare Worker (the BACKEND_URL the dashboard POSTs to).
 *
 * Why this exists: the dashboard is a static GitHub Pages site, so it can't hold an API key
 * or call an LLM directly. This Worker is the one place that does: it holds ANTHROPIC_API_KEY,
 * grounds the model on the live catalog + dining feed, and answers in the LA-insider concierge
 * voice. The page's "Concierge" mode POSTs here; "Fast filter" mode never touches it.
 *
 * Two things it does, by what the body carries:
 *   1. CHAT (always): answer / recommend / plan, grounded on the feed. If `profile` (a feed
 *      hash) is sent, it grounds on THAT profile's feed (data.<hash>.json) — the friend's taste.
 *   2. TASTE SELF-EDIT (only when a profile is attached AND GITHUB_TOKEN is configured): when the
 *      logged-in friend expresses a lasting preference change ("more techno, less comedy", "track
 *      Peggy Gou"), the model calls the `propose_taste_change` tool; the Worker applies a
 *      structured patch to that profile's profiles/<name>/taste.yaml and COMMITS it. CI then
 *      rebuilds the feed (scripts/build_profiles.py — the same deterministic scorer the digest
 *      uses, so the ranking can't drift) and redeploys. The reply tells them to refresh shortly.
 *
 * Contract:
 *   POST  { messages: [{role:'user'|'assistant', content:string}, ...], profile?: "<feed-hash>" }
 *   ->    { reply: string, taste_changed?: boolean }
 *   Auth: optional `Authorization: Bearer <CONCIERGE_TOKEN>` (set CONCIERGE_TOKEN to require it;
 *         leave it unset and the proxy is OPEN to anyone who finds the URL — see README).
 *
 * Env (wrangler secrets / vars):
 *   ANTHROPIC_API_KEY  (secret, required)
 *   CONCIERGE_TOKEN    (secret, optional — shared token gating the proxy)
 *   GITHUB_TOKEN       (secret, optional — repo-scoped contents:write PAT; enables taste self-edit)
 *   ANTHROPIC_MODEL    (var, optional — defaults to a current Claude model)
 *   DATA_URL           (var, optional — the published data.json to ground on)
 *   ALLOWED_ORIGIN     (var, optional — CORS origin; defaults to the Pages site)
 *   GITHUB_REPO        (var, optional — "owner/repo"; defaults to arinazari/la-events)
 *   GITHUB_BRANCH      (var, optional — defaults to main)
 *   PROFILE_SALT       (var, optional — must match the page + build_profiles.py; defaults below)
 */
import { parse as yamlParse, stringify as yamlStringify } from "yaml";

const DEFAULTS = {
  ANTHROPIC_MODEL: "claude-sonnet-4-6",
  DATA_URL: "https://arinazari.github.io/la-events/data.json",
  ALLOWED_ORIGIN: "https://arinazari.github.io",
  GITHUB_REPO: "arinazari/la-events",
  GITHUB_BRANCH: "main",
  PROFILE_SALT: "la-events/v1:",
  MAX_EVENTS: 220,     // cap grounding context (events are ~700; dining is small, sent whole)
  MAX_TOKENS: 1200,
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
    const profileHash = typeof body.profile === "string" && /^[0-9a-f]{8,32}$/.test(body.profile) ? body.profile : null;

    // Ground on the live feed — the profile's feed when one is attached (best-effort).
    const dataUrl = env.DATA_URL || DEFAULTS.DATA_URL;
    const feedUrl = profileHash ? dataUrl.replace(/data\.json(\?.*)?$/, `data.${profileHash}.json$1`) : dataUrl;
    let feed = null;
    try {
      const r = await fetch(feedUrl, { cf: { cacheTtl: 120 } });
      if (r.ok) feed = await r.json();
    } catch { /* degrade gracefully */ }

    // Taste self-edit is available only to a logged-in profile, and only if commits are configured.
    const canEditTaste = !!(profileHash && env.GITHUB_TOKEN);
    const system = buildSystem(feed, { canEditTaste, profileName: feed && feed.profile && feed.profile.name });
    const tools = canEditTaste ? [TASTE_TOOL] : undefined;

    let data;
    try {
      data = await callAnthropic(env, { system, messages, tools });
    } catch (e) {
      return json({ error: "anthropic", detail: String(e && e.message || e).slice(0, 400) }, 502, cors);
    }

    // Tool-use round: the model wants to change this profile's taste.
    if (data.stop_reason === "tool_use" && canEditTaste) {
      const use = (data.content || []).find((b) => b.type === "tool_use" && b.name === TASTE_TOOL.name);
      if (use) {
        const result = await applyTasteEdit(env, profileHash, use.input).catch((e) => ({ ok: false, error: String(e && e.message || e) }));
        const follow = [
          ...messages,
          { role: "assistant", content: data.content },
          { role: "user", content: [{ type: "tool_result", tool_use_id: use.id, content: JSON.stringify(result) }] },
        ];
        let data2;
        try { data2 = await callAnthropic(env, { system, messages: follow, tools }); }
        catch (e) { return json({ error: "anthropic", detail: String(e && e.message || e).slice(0, 400) }, 502, cors); }
        return json({ reply: textOf(data2) || (result.ok ? "Updated — re-ranking, refresh in ~a minute." : "Couldn't apply that change."), taste_changed: !!result.ok }, 200, cors);
      }
    }

    return json({ reply: textOf(data) || "(no answer)" }, 200, cors);
  },
};

/* ----- Anthropic ----- */
async function callAnthropic(env, { system, messages, tools }) {
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
      ...(tools ? { tools } : {}),
    }),
  });
  if (!resp.ok) throw new Error(resp.status + " " + (await resp.text().catch(() => "")).slice(0, 300));
  return resp.json();
}
function textOf(data) {
  return (data.content || []).filter((b) => b.type === "text").map((b) => b.text).join("\n").trim();
}

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

/* The one tool the concierge can call — a constrained, list-shaped patch to a taste profile.
 * Deliberately NOT a freeform YAML rewrite: it only touches the safe list knobs the scorer reads,
 * so a profile can't be structurally broken and every change is auditable in git. */
const TASTE_TOOL = {
  name: "propose_taste_change",
  description:
    "Update the logged-in person's taste profile when they express a LASTING preference change " +
    "(e.g. 'I'm more into techno now', 'stop showing me comedy', 'track Peggy Gou', 'I love the " +
    "Lodge Room'). Do NOT call this for one-off questions like 'what's good Friday' or 'plan my " +
    "night' — those are just answered. Only the fields you want to change need values.",
  input_schema: {
    type: "object",
    properties: {
      add_artists: { type: "array", items: { type: "string" }, description: "Artist/DJ names to start tracking (+ranking boost)." },
      remove_artists: { type: "array", items: { type: "string" }, description: "Tracked artists to stop tracking." },
      add_venues: { type: "array", items: { type: "string" }, description: "Venue names they love (boost)." },
      add_comedians: { type: "array", items: { type: "string" }, description: "Comedians they want surfaced." },
      add_high_category: { type: "array", items: { type: "string" }, description: "A genre/scene phrase to rank highly (e.g. 'warehouse techno parties')." },
      add_boost: { type: "array", items: { type: "string" }, description: "A soft-preference phrase to boost (e.g. 'rooftop / open-air sets')." },
      add_penalty: { type: "array", items: { type: "string" }, description: "A phrase to down-rank (e.g. 'bottle-service clubs')." },
      remove_lines: { type: "array", items: { type: "string" }, description: "Best-effort: remove an existing entry (exact-ish text) from any list above." },
      summary: { type: "string", description: "One short human sentence describing the change, logged to the feedback trail." },
    },
    required: ["summary"],
  },
};

/* Build the system prompt: the concierge persona + a compact, grounded snapshot of the feed. */
function buildSystem(feed, opts = {}) {
  const today = new Date().toISOString().slice(0, 10);
  const persona = [
    "You are Ari's personal LA going-out concierge — a knowledgeable insider with strong taste,",
    "not a generic chatbot. Voice: conversational, opinionated, concise; no sycophancy, no padding.",
    `Today is ${today} (America/Los_Angeles).`,
    opts.profileName ? `You're talking to ${opts.profileName}; the picks below are ranked to THEIR taste.` : "",
    "",
    "You can do three things with the data below: (1) ANSWER questions about events, venues,",
    "restaurants, artists, neighborhoods; (2) RECOMMEND with a one-line 'why' per pick; (3) PLAN a",
    "night — sequence dinner → show → afters, pairing the dining list with on-taste events, and",
    "noting rough proximity (you don't have exact travel times — approximate and say so).",
    "",
    "Rules: ground every claim in the DATA — if something isn't in it, say so plainly rather than",
    "inventing it (e.g. don't fabricate a venue or a showtime). Prefer higher-rated, on-taste picks.",
    "Lead with the answer/pick, keep it tight, surface ticket/booking links when relevant.",
  ];
  if (opts.canEditTaste) {
    persona.push(
      "",
      "TASTE EDITING: this person can tune their own taste. When they express a lasting preference",
      "change (not a one-off query), call propose_taste_change with just the fields that change.",
      "After it succeeds, confirm in one line and tell them their feed re-ranks in about a minute —",
      "they should refresh (the ↻ button) to see it. If it fails, say so plainly; don't pretend."
    );
  }
  const personaText = persona.filter((l) => l !== null && l !== undefined).join("\n");

  if (!feed) return personaText + "\n\n(DATA unavailable this request — answer from the conversation, and say your catalog access is temporarily down.)";

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

  const events = (feed.events || [])
    .filter((e) => !e.is_past && (e.iso_date || "") >= today)
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
    personaText,
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

/* ----- taste self-edit (commit profiles/<name>/taste.yaml; CI rebuilds the feed) ----- */
export async function profileHash(username, salt) {
  const data = new TextEncoder().encode((salt || DEFAULTS.PROFILE_SALT) + String(username).trim().toLowerCase());
  const buf = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 16);
}

function ghHeaders(env) {
  return {
    authorization: "Bearer " + env.GITHUB_TOKEN,
    "user-agent": "la-events-concierge",
    accept: "application/vnd.github+json",
    "content-type": "application/json",
  };
}
function b64encodeUtf8(str) {
  const bytes = new TextEncoder().encode(str);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin);
}
function b64decodeUtf8(b64) {
  const bin = atob(String(b64).replace(/\s/g, ""));
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new TextDecoder().decode(bytes);
}
async function ghGetFile(env, path) {
  const repo = env.GITHUB_REPO || DEFAULTS.GITHUB_REPO;
  const branch = env.GITHUB_BRANCH || DEFAULTS.GITHUB_BRANCH;
  const r = await fetch(`https://api.github.com/repos/${repo}/contents/${path}?ref=${branch}`, { headers: ghHeaders(env) });
  if (!r.ok) return null;
  const j = await r.json();
  return { text: b64decodeUtf8(j.content), sha: j.sha };
}
async function ghPutFile(env, path, text, sha, message) {
  const repo = env.GITHUB_REPO || DEFAULTS.GITHUB_REPO;
  const branch = env.GITHUB_BRANCH || DEFAULTS.GITHUB_BRANCH;
  const r = await fetch(`https://api.github.com/repos/${repo}/contents/${path}`, {
    method: "PUT",
    headers: ghHeaders(env),
    body: JSON.stringify({ message, content: b64encodeUtf8(text), sha, branch }),
  });
  return r.ok;
}

/* Resolve a feed hash to its profile (name + taste-file path) via profiles.yaml. */
async function resolveProfile(env, hash) {
  const f = await ghGetFile(env, "profiles.yaml");
  if (!f) return null;
  const manifest = yamlParse(f.text) || {};
  const salt = manifest.salt || DEFAULTS.PROFILE_SALT;
  for (const p of manifest.profiles || []) {
    if (!p || !p.username) continue;
    if ((await profileHash(p.username, salt)) === hash) {
      return { name: p.name || p.username, tastePath: p.taste || "taste.yaml" };
    }
  }
  return null;
}

/* Pure: fold a structured patch into a parsed taste object. Exported for tests. */
export function applyPatch(t, patch, today) {
  t = t || {};
  t.categories = t.categories || {};
  const arr = (k, o) => { o[k] = Array.isArray(o[k]) ? o[k] : []; return o[k]; };
  const norm = (s) => String(s).trim().toLowerCase();
  const addUniq = (list, items) => {
    for (const it of items || []) {
      const v = String(it).trim();
      if (v && !list.some((x) => norm(x) === norm(v))) list.push(v);
    }
  };
  const removeFrom = (list, items) => {
    const kill = new Set((items || []).map(norm));
    for (let i = list.length - 1; i >= 0; i--) if (kill.has(norm(list[i]))) list.splice(i, 1);
  };

  addUniq(arr("artists_tracked", t), patch.add_artists);
  if (patch.remove_artists) removeFrom(arr("artists_tracked", t), patch.remove_artists);
  addUniq(arr("venues_loved", t), patch.add_venues);
  addUniq(arr("comedians_loved", t), patch.add_comedians);
  addUniq(arr("high", t.categories), patch.add_high_category);
  addUniq(arr("boosts", t), patch.add_boost);
  addUniq(arr("penalties", t), patch.add_penalty);

  if (patch.remove_lines && patch.remove_lines.length) {
    const lists = [t.categories.high, t.categories.medium, t.categories.low, t.boosts, t.penalties, t.artists_tracked, t.venues_loved, t.comedians_loved];
    for (const l of lists) if (Array.isArray(l)) removeFrom(l, patch.remove_lines);
  }

  const note = (patch.summary || "taste updated").trim();
  arr("feedback", t).push(`${today}: ${note} (self-edit via concierge)`);
  return t;
}

async function applyTasteEdit(env, hash, patch) {
  const prof = await resolveProfile(env, hash);
  if (!prof) return { ok: false, error: "profile not found for that session" };
  // Never let a friend edit the shared root taste.yaml — only their own profiles/<name>/ file.
  if (!/^profiles\/.+\/taste\.ya?ml$/.test(prof.tastePath)) return { ok: false, error: "this profile has no editable taste file" };

  const file = await ghGetFile(env, prof.tastePath);
  if (!file) return { ok: false, error: "could not read taste file" };

  let obj;
  try { obj = yamlParse(file.text) || {}; } catch { return { ok: false, error: "taste file did not parse" }; }
  const today = new Date().toISOString().slice(0, 10);
  applyPatch(obj, patch || {}, today);

  let out;
  try {
    out = yamlStringify(obj, { lineWidth: 0 });
    const check = yamlParse(out);                       // never commit something that won't parse
    if (!check || typeof check !== "object" || !check.categories) throw new Error("invalid result");
  } catch { return { ok: false, error: "edit produced invalid YAML; nothing changed" }; }

  const msg = `taste(${prof.name}): ${(patch.summary || "self-edit").slice(0, 72)}\n\nSelf-edit via the dashboard concierge.`;
  const ok = await ghPutFile(env, prof.tastePath, out, file.sha, msg);
  return ok ? { ok: true, summary: patch.summary || "updated", note: "committed; the feed rebuilds via CI in ~1–2 min" } : { ok: false, error: "commit failed" };
}
