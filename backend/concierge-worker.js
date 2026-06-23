/**
 * la-events concierge backend — a Cloudflare Worker (the BACKEND_URL the dashboard POSTs to).
 *
 * Why this exists: the dashboard is a static GitHub Pages site, so it can't hold an API key
 * or call an LLM directly. This Worker is the one place that does: it holds ANTHROPIC_API_KEY,
 * grounds the model on the live catalog + dining feed, and answers in the LA-insider concierge
 * voice. The page's "Concierge" mode POSTs here; "Fast filter" mode never touches it.
 *
 * Three things it does, by what the body carries:
 *   1. CHAT (always): answer / recommend / plan, grounded on the feed. If `profile` (a feed
 *      hash) is sent, it grounds on THAT profile's feed (data.<hash>.json) — the friend's taste.
 *   2. TASTE SELF-EDIT (only when a profile is attached AND GITHUB_TOKEN is configured): when the
 *      logged-in person expresses a lasting preference change ("more techno, less comedy", "track
 *      Peggy Gou"), the model calls the `propose_taste_change` tool; the Worker applies a structured
 *      patch to that profile's taste file (a friend's profiles/<name>/taste.yaml, or the root
 *      taste.yaml for the `owner: true` profile) and COMMITS it. CI then
 *      rebuilds the feed (scripts/build_profiles.py — the same deterministic scorer the digest
 *      uses, so the ranking can't drift) and redeploys. The reply tells them to refresh shortly.
 *   3. PROFILE / MECHANISM SELF-EDIT (same gate): taste.yaml is CONTENT (what they like); profile.yaml
 *      is MECHANISM (where home is + how the scoring math weights things). When the person changes
 *      their LOCATION ("I moved to Glendale") or a ranking knob ("weight live music higher", "stop
 *      down-ranking hip-hop", "count Frogtown as near me"), the model calls `propose_profile_change`;
 *      the Worker patches that profile's profile.yaml (the friend's profiles/<name>/profile.yaml —
 *      created on first edit — or the root profile.yaml for the owner) and COMMITS. Same CI rebuild.
 *      Because lib/scoring.py resolves each scoring key all-or-nothing (profile → taste → default),
 *      a first-time edit MATERIALIZES the full effective list/map first (seeded from the root
 *      profile.yaml, which is the defaults verbatim) so it never silently drops the rest.
 *
 * Contract:
 *   POST  { messages: [{role:'user'|'assistant', content:string}, ...], profile?: "<feed-hash>" }
 *   ->    { reply: string, taste_changed?: boolean, profile_changed?: boolean }
 *   Auth: optional `Authorization: Bearer <CONCIERGE_TOKEN>` (set CONCIERGE_TOKEN to require it;
 *         leave it unset and the proxy is OPEN to anyone who finds the URL — see README).
 *   BYOK: optional `x-anthropic-key: sk-ant-...` — the caller's OWN Anthropic key. It pays for that
 *         request (used in place of ANTHROPIC_API_KEY) and is its own entry ticket: a valid personal
 *         key satisfies the gate even without CONCIERGE_TOKEN. (Taste self-edit still commits with the
 *         owner's GITHUB_TOKEN; by config that's open to own-key callers too — see canEditTaste.)
 *
 * Env (wrangler secrets / vars):
 *   ANTHROPIC_API_KEY  (secret, required unless every caller brings their own key via x-anthropic-key)
 *   CONCIERGE_TOKEN    (secret, optional — shared token gating the proxy)
 *   GITHUB_TOKEN       (secret, optional — repo-scoped contents:write PAT; enables taste + profile self-edit)
 *   ANTHROPIC_MODEL    (var, optional — executor model that does the bulk of generation; default Sonnet)
 *   ADVISOR_MODEL      (var, optional — stronger model the executor consults for planning; "" disables)
 *   EFFORT             (var, optional — executor effort: low | medium | high | max; default max)
 *   MAX_TOKENS         (var, optional — output cap; must leave room for adaptive thinking)
 *   DATA_URL           (var, optional — the published data.json to ground on)
 *   ALLOWED_ORIGIN     (var, optional — CORS origin; defaults to the Pages site)
 *   GITHUB_REPO        (var, optional — "owner/repo"; defaults to arinazari/la-events)
 *   GITHUB_BRANCH      (var, optional — defaults to main)
 *   PROFILE_SALT       (var, optional — must match the page + build_profiles.py; defaults below)
 */
import { parse as yamlParse, parseDocument } from "yaml";

const DEFAULTS = {
  ANTHROPIC_MODEL: "claude-sonnet-4-6",   // executor — does the bulk of generation
  ADVISOR_MODEL: "claude-opus-4-8",        // advisor — consulted for multi-step planning (must be >= executor)
  EFFORT: "max",                            // executor effort: low | medium | high | max
  DATA_URL: "https://arinazari.github.io/la-events/data.json",
  ALLOWED_ORIGIN: "https://arinazari.github.io",
  GITHUB_REPO: "arinazari/la-events",
  GITHUB_BRANCH: "main",
  PROFILE_SALT: "la-events/v1:",
  MAX_EVENTS: 220,     // cap grounding context (events are ~700; dining is small, sent whole)
  MAX_TOKENS: 8000,    // room for adaptive thinking + the reply (raise if complex plans get cut off)
  SPOTIFY_AUTH: "https://accounts.spotify.com",
  SPOTIFY_API: "https://api.spotify.com/v1",
  SPOTIFY_SCOPES: "user-top-read user-follow-read user-read-recently-played",
  STATE_TTL_MS: 15 * 60 * 1000,   // how long a /spotify/login state token stays valid
};

export default {
  async fetch(request, env) {
    const origin = env.ALLOWED_ORIGIN || DEFAULTS.ALLOWED_ORIGIN;
    const cors = {
      "Access-Control-Allow-Origin": origin,
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "content-type, authorization, x-anthropic-key",
      "Access-Control-Max-Age": "86400",
    };
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });

    // Per-profile Spotify (browser OAuth + KV token store + an authed sync the routine/CI calls)
    // is path-routed here; every other request is the chat proxy below. One Worker, one deploy.
    const url = new URL(request.url);
    if (url.pathname.startsWith("/spotify/")) return handleSpotify(url, request, env, cors);
    if (url.pathname === "/refresh-events" || url.pathname === "/rebuild-profile")
      return handlePipeline(url, request, env, cors);

    if (request.method !== "POST") return json({ error: "POST only" }, 405, cors);

    // Auth + bring-your-own-key. The shared CONCIERGE_TOKEN normally gates the proxy (it guards the
    // owner's Anthropic spend). But a caller may instead bring their OWN Anthropic key via the
    // x-anthropic-key header — that key pays for the request, so it's its own entry ticket: a valid
    // personal key satisfies the gate even without the shared token. (Self-edit commits still use the
    // owner's GitHub token; by Ari's call those are open to own-key callers too — see canEdit below.)
    const userKey = parseUserKey(request.headers.get("x-anthropic-key"));
    const tokenOk = !env.CONCIERGE_TOKEN || (request.headers.get("authorization") || "") === "Bearer " + env.CONCIERGE_TOKEN;
    if (!tokenOk && !userKey) return json({ error: "unauthorized" }, 401, cors);
    const apiKey = userKey || env.ANTHROPIC_API_KEY;
    if (!apiKey) return json({ error: "server missing ANTHROPIC_API_KEY" }, 500, cors);

    let body;
    try { body = await request.json(); } catch { return json({ error: "bad json" }, 400, cors); }
    // Health ping (the page's connection indicator): validates reachability + the token, no LLM call.
    if (body && body.ping) return json({ ok: true, taste: !!env.GITHUB_TOKEN, byok: !!userKey }, 200, cors);
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

    // Self-edit (taste CONTENT + profile MECHANISM) is available to any logged-in profile, as long as
    // commits are configured. It commits to the owner's repo using the owner's GITHUB_TOKEN — by Ari's
    // call a bring-your-own-key caller can self-edit too (the GitHub write is the owner's setup, not
    // something the caller needs a shared token for). Accepted tradeoff: any valid key reaching the
    // Worker can trigger a (revertible) commit to a profile's file; keep GITHUB_TOKEN a single-repo,
    // Contents-only PAT.
    const canEdit = !!(profileHash && env.GITHUB_TOKEN);
    const system = buildSystem(feed, { canEdit, profileName: feed && feed.profile && feed.profile.name });
    // Advisor mode: a stronger model (Opus) the executor (Sonnet) consults for multi-step planning —
    // set ADVISOR_MODEL to "" to disable. Plus the two self-edit tools when this profile can edit.
    const advisorModel = env.ADVISOR_MODEL === undefined ? DEFAULTS.ADVISOR_MODEL : env.ADVISOR_MODEL;
    const tools = [
      ...(advisorModel ? [{ type: "advisor_20260301", name: "advisor", model: advisorModel }] : []),
      ...(canEdit ? [TASTE_TOOL, PROFILE_TOOL] : []),
    ];
    // BYOK callers may upgrade the executor on their OWN spend (Q3: "Opus if they bring a key"):
    // `model: "opus"` in the body is honored only when a personal key is present — shared-token spend
    // (the owner's key) always stays on the default, so a friend can't run up Ari's bill on Opus.
    const execModel = (userKey && body && body.model) ? resolveModel(env, body.model) : null;

    // The advisor is a SERVER-side tool; its sampling loop can return stop_reason "pause_turn" — when
    // it does, re-send the conversation to let it continue (don't inject a user turn). Cap re-sends.
    let convo = messages;
    let data;
    try {
      for (let i = 0; i < 4; i++) {
        data = await callAnthropic(env, { system, messages: convo, tools, apiKey, model: execModel });
        if (data.stop_reason !== "pause_turn") break;
        convo = [...convo, { role: "assistant", content: data.content }];
      }
    } catch (e) {
      return json({ error: "anthropic", detail: String(e && e.message || e).slice(0, 400) }, 502, cors);
    }

    // Tool-use round: the model wants to change this profile's taste (CONTENT) and/or profile
    // (MECHANISM) — both are client-handled custom tools that commit a YAML file.
    if (data.stop_reason === "tool_use" && canEdit) {
      const uses = (data.content || []).filter(
        (b) => b.type === "tool_use" && (b.name === TASTE_TOOL.name || b.name === PROFILE_TOOL.name)
      );
      if (uses.length) {
        let tasteChanged = false, profileChanged = false;
        const results = [];
        for (const use of uses) {
          const isProfile = use.name === PROFILE_TOOL.name;
          const apply = isProfile ? applyProfileEdit : applyTasteEdit;
          const result = await apply(env, profileHash, use.input).catch((e) => ({ ok: false, error: String(e && e.message || e) }));
          if (result.ok) { if (isProfile) profileChanged = true; else tasteChanged = true; }
          results.push({ type: "tool_result", tool_use_id: use.id, content: JSON.stringify(result) });
        }
        const follow = [
          ...convo,
          { role: "assistant", content: data.content },
          { role: "user", content: results },
        ];
        let data2;
        try { data2 = await callAnthropic(env, { system, messages: follow, tools, apiKey, model: execModel }); }
        catch (e) { return json({ error: "anthropic", detail: String(e && e.message || e).slice(0, 400) }, 502, cors); }
        const changed = tasteChanged || profileChanged;
        return json({
          reply: textOf(data2) || (changed ? "Updated — re-ranking, refresh in ~a minute." : "Couldn't apply that change."),
          taste_changed: tasteChanged, profile_changed: profileChanged,
        }, 200, cors);
      }
    }

    return json({ reply: textOf(data) || "(no answer)" }, 200, cors);
  },
};

/* ----- Anthropic ----- */
/* Map a friendly model choice to a configured id — reuses the existing executor/advisor constants
 * (no new hardcoded ids), and passes through an explicit, well-formed `claude-*` id. Used only for a
 * BYOK caller's optional upgrade (Q3: "Opus if they bring a key"); shared-token spend stays default. */
function resolveModel(env, m) {
  const k = String(m || "").trim().toLowerCase();
  if (k === "opus") return env.ADVISOR_MODEL || DEFAULTS.ADVISOR_MODEL;
  if (k === "sonnet") return env.ANTHROPIC_MODEL || DEFAULTS.ANTHROPIC_MODEL;
  if (/^claude-[a-z0-9.\-]+$/.test(k)) return k;
  return env.ANTHROPIC_MODEL || DEFAULTS.ANTHROPIC_MODEL;
}

async function callAnthropic(env, { system, messages, tools, apiKey, model }) {
  const resp = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": apiKey || env.ANTHROPIC_API_KEY,
      "anthropic-version": "2023-06-01",
      "anthropic-beta": "advisor-tool-2026-03-01",   // enables the advisor tool
    },
    body: JSON.stringify({
      model: model || env.ANTHROPIC_MODEL || DEFAULTS.ANTHROPIC_MODEL,
      max_tokens: Number(env.MAX_TOKENS) || DEFAULTS.MAX_TOKENS,
      // Cache the (large, stable) persona + grounded feed: turns 2+ of a conversation read it at ~0.1x.
      system: [{ type: "text", text: system, cache_control: { type: "ephemeral" } }],
      thinking: { type: "adaptive" },                          // adaptive thinking for quality planning
      output_config: { effort: env.EFFORT || DEFAULTS.EFFORT },
      messages,
      ...(tools && tools.length ? { tools } : {}),
    }),
  });
  if (!resp.ok) throw new Error(resp.status + " " + (await resp.text().catch(() => "")).slice(0, 300));
  return resp.json();
}
function textOf(data) {
  return (data.content || []).filter((b) => b.type === "text").map((b) => b.text).join("\n").trim();
}

/* A caller-supplied Anthropic key (BYOK), validated to the documented shape so we never forward
 * junk — or a mis-pasted concierge token — to Anthropic as a key. Empty / malformed -> null. */
function parseUserKey(h) {
  const k = (h || "").trim();
  return /^sk-ant-[A-Za-z0-9_-]{20,}$/.test(k) ? k : null;
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

/* The second self-edit tool — a constrained patch to the MECHANISM profile (profile.yaml):
 * location + how the ranking math weights things. Distinct from taste (artists/genres/venues).
 * Like the taste tool it touches only the safe high-value knobs — home, category weights, and the
 * near-home / penalty / boost / far term lists — never source ids, rating thresholds, or the
 * numeric Spotify/feedback/travel tuning (hand-edit those). Every term-list / weight edit writes
 * the COMPLETE effective value (see applyProfilePatchDoc) so a first edit can't drop the defaults. */
const PROFILE_TOOL = {
  name: "propose_profile_change",
  description:
    "Update the logged-in person's MECHANISM profile (profile.yaml) — their LOCATION or how the " +
    "ranking math weights things. This is DISTINCT from propose_taste_change (artists/genres/venues " +
    "they like). Call this for: 'I moved to Glendale' / 'I'm near Sunset & Vermont' (home — always " +
    "include approx coords so travel times stay right); 'weight live music higher', 'I care less " +
    "about film' (category importance); 'count Highland Park as near me' (near-home neighborhoods); " +
    "'stop down-ranking hip-hop', 'down-rank bottle-service nights' (penalty words); a setting/vibe " +
    "boost word like 'rooftop' or 'vinyl' (boost words). Do NOT call this for one-off questions, or " +
    "for taste/artist changes (use propose_taste_change). Only include the fields that change.",
  input_schema: {
    type: "object",
    properties: {
      home: {
        type: "object",
        description: "Where they live — drives the near-home boost + night-planner travel times. When you set this, ALWAYS include `coords` (your best approx [lat, lng] for the neighborhood/cross-streets) so travel times stay correct.",
        properties: {
          neighborhood: { type: "string", description: "Neighborhood name, e.g. 'Glendale'." },
          cross_streets: { type: "string", description: "Nearest cross-streets, e.g. 'Brand & Broadway'." },
          coords: { type: "array", items: { type: "number" }, description: "[latitude, longitude] in decimal degrees, your best approximation for the place above." },
        },
      },
      set_category_weights: {
        type: "array",
        description: "Set how many points an event category is worth (higher ranks higher; typical 1–3). Known categories: electronic, party, film, music, live_music, theater, beer_food, comedy, art, pop, general.",
        items: {
          type: "object",
          properties: {
            category: { type: "string", description: "One of the known category tokens above." },
            weight: { type: "number", description: "Points (0–5)." },
          },
          required: ["category", "weight"],
        },
      },
      add_near_home: { type: "array", items: { type: "string" }, description: "Neighborhoods to start counting as near home (+boost)." },
      remove_near_home: { type: "array", items: { type: "string" }, description: "Neighborhoods to stop counting as near home." },
      add_penalty_terms: { type: "array", items: { type: "string" }, description: "Words/phrases that should DOWN-rank an event (e.g. 'bottle service', 'top 40')." },
      remove_penalty_terms: { type: "array", items: { type: "string" }, description: "Penalty words to stop down-ranking (e.g. 'hip hop')." },
      add_boost_terms: { type: "array", items: { type: "string" }, description: "Setting/vibe words that should BOOST an event (e.g. 'rooftop', 'vinyl', 'sunset', 'open-air')." },
      remove_boost_terms: { type: "array", items: { type: "string" }, description: "Boost words to remove." },
      add_far_terms: { type: "array", items: { type: "string" }, description: "Far-away places to down-rank as not-worth-the-trip (e.g. 'Anaheim')." },
      remove_far_terms: { type: "array", items: { type: "string" }, description: "Far-place words to remove (e.g. they now want Long Beach)." },
      summary: { type: "string", description: "One short human sentence describing the change." },
    },
    required: ["summary"],
  },
};

/* Build the system prompt: the concierge persona + a compact, grounded snapshot of the feed. */
export function buildSystem(feed, opts = {}) {
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
  if (opts.canEdit) {
    persona.push(
      "",
      "TASTE EDITING: this person can tune their own taste. Their full saved taste profile is shown",
      "below (TASTE PROFILE) — read it to answer 'what's in my taste?' and quote its exact wording",
      "when removing an entry. When they express a lasting preference change (not a one-off query),",
      "call propose_taste_change with just the fields that change. After it succeeds, confirm in one",
      "line and tell them their feed re-ranks in about a minute — they should refresh (the ↻ button)",
      "to see it. If it fails, say so plainly; don't pretend.",
      "",
      "MECHANISM EDITING: they can also tune HOW their feed ranks — via propose_profile_change, which",
      "is SEPARATE from taste. Their current mechanism is shown below (MECHANISM). Use this tool when",
      "they change their LOCATION ('I moved to Glendale' → set home, and include your best approx",
      "coords so travel times stay right) or a scoring dial: how categories are weighted ('weight live",
      "music higher', 'I care less about film'), the near-home neighborhoods, the down-rank/penalty",
      "words, or the setting/boost words. Decide by what the request is ABOUT: an artist/genre/venue →",
      "propose_taste_change; a place they live or a ranking knob → propose_profile_change. Same",
      "after-success line (re-ranks in ~a minute, refresh)."
    );
  }
  const personaText = persona.filter((l) => l !== null && l !== undefined).join("\n");

  if (!feed) return personaText + "\n\n(DATA unavailable this request — answer from the conversation, and say your catalog access is temporarily down.)";

  // Ground on the FULL taste profile, preferring the complete structured snapshot (config.taste)
  // over the thin feed.taste (which is only venues + artists). Without the whole profile the
  // concierge can neither answer "what's in my taste?" nor edit existing entries precisely
  // (remove_lines needs the exact wording, which it can only know by seeing it here).
  const taste = (feed.config && feed.config.taste) || feed.taste || {};
  const cats = taste.categories || {};
  const clean = (xs, n = 50) =>
    (Array.isArray(xs) ? xs : []).slice(0, n).map((s) => String(s).replace(/\s+/g, " ").trim()).filter(Boolean);
  const tasteBlock = [
    cats.high && cats.high.length ? "Loves (rank high): " + clean(cats.high).join("; ") : null,
    cats.medium && cats.medium.length ? "Likes: " + clean(cats.medium).join("; ") : null,
    cats.low && cats.low.length ? "Only if exceptional: " + clean(cats.low).join("; ") : null,
    taste.boosts && taste.boosts.length ? "Boosts: " + clean(taste.boosts).join("; ") : null,
    taste.penalties && taste.penalties.length ? "Down-ranks: " + clean(taste.penalties).join("; ") : null,
    taste.artists_tracked && taste.artists_tracked.length ? "Tracked artists: " + clean(taste.artists_tracked, 80).join(", ") : null,
    taste.comedians_loved && taste.comedians_loved.length ? "Comedians to surface: " + clean(taste.comedians_loved).join(", ") : null,
    taste.venues_loved && taste.venues_loved.length ? "Loved venues: " + clean(taste.venues_loved).join(", ") : null,
  ].filter(Boolean).join("\n");

  // MECHANISM snapshot (profile.yaml) — home + the scoring dials. Lets the concierge answer
  // "where's home / what are my weights?" and, when editing, target propose_profile_change
  // precisely. Knobs the page didn't set fall back to the repo defaults (say so if asked).
  const cfg = feed.config || {};
  const home = cfg.home || {};
  const sc = cfg.scoring || {};
  const cw = sc.category_weights && Object.keys(sc.category_weights).length ? sc.category_weights : null;
  const mechBlock = [
    home.neighborhood || (Array.isArray(home.coords) && home.coords.length === 2)
      ? "Home: " + (home.neighborhood || "(coords only)") +
        (home.cross_streets ? " (" + home.cross_streets + ")" : "") +
        (Array.isArray(home.coords) && home.coords.length === 2 ? " [" + home.coords.join(", ") + "]" : "")
      : null,
    cw ? "Category weights: " + Object.entries(cw).map(([k, v]) => `${k}=${v}`).join(", ") : null,
    Array.isArray(sc.near_home_neighborhoods) && sc.near_home_neighborhoods.length ? "Near-home: " + clean(sc.near_home_neighborhoods, 60).join(", ") : null,
    Array.isArray(sc.penalty_terms) && sc.penalty_terms.length ? "Down-rank words: " + clean(sc.penalty_terms, 60).join(", ") : null,
    Array.isArray(sc.groove_terms) && sc.groove_terms.length ? "Boost words: " + clean(sc.groove_terms, 60).join(", ") : null,
    Array.isArray(sc.far_terms) && sc.far_terms.length ? "Far (down-ranked) places: " + clean(sc.far_terms, 60).join(", ") : null,
  ].filter(Boolean).join("\n");

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
    tasteBlock
      ? "TASTE PROFILE (the saved profile — rank everything against this" +
        (opts.canEdit ? "; it's also what propose_taste_change edits, so quote its exact wording when removing an entry" : "") +
        "):\n" + tasteBlock
      : "",
    "",
    mechBlock
      ? "MECHANISM (profile.yaml — location + scoring dials" +
        (opts.canEdit ? "; propose_profile_change edits these" : "") +
        "; unlisted knobs use the defaults):\n" + mechBlock
      : "",
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

/* Resolve a feed hash to its profile (name + taste/profile file paths) via profiles.yaml.
 * profilePath mirrors build_profiles.py: the owner edits the root profile.yaml; a friend edits
 * their own profiles/<name>/profile.yaml (explicit `profile:` in the manifest, else the path that
 * sits beside their taste file, else the conventional one — created on first edit if absent). */
async function resolveProfile(env, hash) {
  const f = await ghGetFile(env, "profiles.yaml");
  if (!f) return null;
  const manifest = yamlParse(f.text) || {};
  const salt = manifest.salt || DEFAULTS.PROFILE_SALT;
  for (const p of manifest.profiles || []) {
    if (!p || !p.username) continue;
    if ((await profileHash(p.username, salt)) === hash) {
      const tastePath = p.taste || "taste.yaml";
      const owner = !!p.owner;
      let profilePath;
      if (owner) profilePath = "profile.yaml";
      else if (p.profile) profilePath = p.profile;
      else if (/^profiles\/.+\/taste\.ya?ml$/.test(tastePath)) profilePath = tastePath.replace(/taste\.ya?ml$/, "profile.yaml");
      else profilePath = `profiles/${String(p.username).trim().toLowerCase()}/profile.yaml`;
      return { name: p.name || p.username, tastePath, profilePath, owner };
    }
  }
  return null;
}

/* Fold a structured patch into a parsed YAML *Document* (not a plain object) so existing comments
 * + key order survive the round-trip — important for the curated root taste.yaml. Exported for tests. */
function seqVals(seq) { return (seq && seq.items ? seq.items : []).map((it) => String(it && it.value !== undefined ? it.value : it)); }
function ensureSeq(doc, path) {
  let n = doc.getIn(path);
  if (!n || !n.items) { doc.setIn(path, doc.createNode([])); n = doc.getIn(path); }
  return n;
}
function addUniqDoc(doc, path, items) {
  if (!items || !items.length) return;
  const seq = ensureSeq(doc, path);
  const have = new Set(seqVals(seq).map((s) => s.trim().toLowerCase()));
  for (const v of items) {
    const s = String(v).trim();
    if (s && !have.has(s.toLowerCase())) { seq.add(s); have.add(s.toLowerCase()); }
  }
}
function removeDoc(doc, path, items) {
  const seq = doc.getIn(path);
  if (!seq || !seq.items || !items) return;
  const kill = new Set(items.map((x) => String(x).trim().toLowerCase()));
  for (let i = seq.items.length - 1; i >= 0; i--) {
    const it = seq.items[i];
    const v = String(it && it.value !== undefined ? it.value : it).trim().toLowerCase();
    if (kill.has(v)) seq.delete(i);
  }
}
export function applyPatchDoc(doc, patch, today) {
  addUniqDoc(doc, ["artists_tracked"], patch.add_artists);
  if (patch.remove_artists) removeDoc(doc, ["artists_tracked"], patch.remove_artists);
  addUniqDoc(doc, ["venues_loved"], patch.add_venues);
  addUniqDoc(doc, ["comedians_loved"], patch.add_comedians);
  addUniqDoc(doc, ["categories", "high"], patch.add_high_category);
  addUniqDoc(doc, ["boosts"], patch.add_boost);
  addUniqDoc(doc, ["penalties"], patch.add_penalty);
  if (patch.remove_lines && patch.remove_lines.length) {
    for (const path of [["categories", "high"], ["categories", "medium"], ["categories", "low"], ["boosts"], ["penalties"], ["artists_tracked"], ["venues_loved"], ["comedians_loved"]]) {
      removeDoc(doc, path, patch.remove_lines);
    }
  }
  addUniqDoc(doc, ["feedback"], [`${today}: ${(patch.summary || "taste updated").trim()} (self-edit via concierge)`]);
  return doc;
}

async function applyTasteEdit(env, hash, patch) {
  const prof = await resolveProfile(env, hash);
  if (!prof) return { ok: false, error: "profile not found for that session" };
  // A friend edits only their own profiles/<name>/taste.yaml. The shared root taste.yaml is
  // editable only by an `owner: true` profile (Ari's own login).
  const isRoot = /(^|\/)taste\.ya?ml$/.test(prof.tastePath) && !prof.tastePath.startsWith("profiles/");
  if (isRoot && !prof.owner) return { ok: false, error: "this profile has no editable taste file" };
  if (!isRoot && !/^profiles\/.+\/taste\.ya?ml$/.test(prof.tastePath)) return { ok: false, error: "this profile has no editable taste file" };

  const file = await ghGetFile(env, prof.tastePath);
  if (!file) return { ok: false, error: "could not read taste file" };

  let out;
  try {
    const doc = parseDocument(file.text);
    if (doc.errors && doc.errors.length) throw new Error("parse");
    applyPatchDoc(doc, patch || {}, new Date().toISOString().slice(0, 10));
    out = String(doc);
    const check = yamlParse(out);                       // never commit something that won't parse
    if (!check || typeof check !== "object" || !check.categories) throw new Error("invalid result");
  } catch { return { ok: false, error: "edit produced invalid YAML; nothing changed" }; }

  const msg = `taste(${prof.name}): ${(patch.summary || "self-edit").slice(0, 72)}\n\nSelf-edit via the dashboard concierge.`;
  const ok = await ghPutFile(env, prof.tastePath, out, file.sha, msg);
  return ok ? { ok: true, summary: patch.summary || "updated", note: "committed; the feed rebuilds via CI in ~1–2 min" } : { ok: false, error: "commit failed" };
}

/* ----- profile self-edit (commit profiles/<name>/profile.yaml; CI rebuilds the feed) -----
 *
 * profile.yaml = MECHANISM (home + the scoring dials) — the sibling of the taste (CONTENT) edit
 * above. The subtlety that makes this NOT a copy-paste of the taste edit: lib/scoring.py resolves
 * each scoring key ALL-OR-NOTHING (profile.yaml's value, else taste.yaml's, else the in-code
 * DEFAULT_*), so a present-but-partial list/map shadows the rest. A first-time edit therefore must
 * write the COMPLETE effective value. We get that base by reading the repo's own files (the friend's
 * taste.yaml, then the root profile.yaml — which IS DEFAULT_* verbatim), mirroring the scorer's
 * fallback chain without duplicating the default constants in JS. */
function safeYaml(text) { try { const o = yamlParse(text); return o && typeof o === "object" ? o : null; } catch { return null; } }
function nodeJSON(node) { return node && typeof node.toJSON === "function" ? node.toJSON() : undefined; }

/* The scorer's per-key fallback for a key absent from the file being edited: the friend's
 * taste.yaml `scoring`, then the root profile.yaml `scoring` (the defaults). undefined => neither
 * has it, so the caller refuses that key rather than risk writing a partial. */
function effectiveScoringVal(key, tasteObj, rootObj) {
  const t = tasteObj && tasteObj.scoring && tasteObj.scoring[key];
  if (t !== undefined && t !== null) return t;
  const r = rootObj && rootObj.scoring && rootObj.scoring[key];
  return (r === undefined || r === null) ? undefined : r;
}

/* Materialize a fallback-defaulted LIST to its full effective value (unless the file already has a
 * non-empty one) before add/remove, so a first edit never shadows the default list with a 1-item one. */
function ensureFullSeq(doc, path, effectiveList) {
  const n = doc.getIn(path);
  if (n && n.items && n.items.length) return true;                          // already complete in the file
  if (!Array.isArray(effectiveList) || !effectiveList.length) return false; // no base → caller skips this list
  doc.setIn(path, doc.createNode(effectiveList.slice()));
  return true;
}

/* Apply the structured MECHANISM patch to a parsed YAML Document (comments/key-order preserved).
 * `effective` carries the full fallback values for the defaulted keys. Returns the list of knobs
 * actually touched (empty => nothing actionable). Exported for tests. */
export function applyProfilePatchDoc(doc, patch, effective) {
  const touched = [];
  effective = effective || {};

  // Home (location) — each subfield set independently; safe (no all-or-nothing fallback).
  if (patch.home && typeof patch.home === "object") {
    const h = patch.home;
    if (h.neighborhood) { doc.setIn(["home", "neighborhood"], String(h.neighborhood).trim()); touched.push("home"); }
    if (h.cross_streets) { doc.setIn(["home", "cross_streets"], String(h.cross_streets).trim()); touched.push("home"); }
    if (Array.isArray(h.coords) && h.coords.length === 2 &&
        h.coords.every((x) => typeof x === "number" && isFinite(x)) &&
        h.coords[0] >= -90 && h.coords[0] <= 90 && h.coords[1] >= -180 && h.coords[1] <= 180) {
      const c = doc.createNode([h.coords[0], h.coords[1]]); c.flow = true;   // match the repo's `coords: [lat, lng]` style
      doc.setIn(["home", "coords"], c);
      if (!touched.includes("home")) touched.push("home");
    }
  }

  // Category weights — write a COMPLETE map: effective base ∪ what's already in the file ∪ overrides.
  // Refuse if there's no complete base to build on (would otherwise drop unlisted categories to 1).
  if (Array.isArray(patch.set_category_weights) && patch.set_category_weights.length) {
    const fileMap = nodeJSON(doc.getIn(["scoring", "category_weights"]));
    const haveBase = (effective.category_weights && Object.keys(effective.category_weights).length) ||
                     (fileMap && Object.keys(fileMap).length);
    if (haveBase) {
      const base = { ...(effective.category_weights || {}), ...(fileMap || {}) };
      let any = false;
      for (const it of patch.set_category_weights) {
        if (!it || !it.category || typeof it.weight !== "number" || !isFinite(it.weight)) continue;
        const cat = String(it.category).trim().toLowerCase().replace(/\s+/g, "_");
        if (!cat) continue;
        base[cat] = Math.max(0, Math.min(5, Math.round(it.weight)));
        any = true;
      }
      if (any) { doc.setIn(["scoring", "category_weights"], doc.createNode(base)); touched.push("category_weights"); }
    }
  }

  // Term lists — materialize to the full effective list, then add/remove. A list with no base is skipped.
  const lists = [
    ["near_home_neighborhoods", effective.near_home, patch.add_near_home, patch.remove_near_home],
    ["penalty_terms", effective.penalty, patch.add_penalty_terms, patch.remove_penalty_terms],
    ["groove_terms", effective.groove, patch.add_boost_terms, patch.remove_boost_terms],
    ["far_terms", effective.far, patch.add_far_terms, patch.remove_far_terms],
  ];
  for (const [key, effList, add, rem] of lists) {
    const hasAdd = Array.isArray(add) && add.length;
    const hasRem = Array.isArray(rem) && rem.length;
    if (!hasAdd && !hasRem) continue;
    const path = ["scoring", key];
    if (!ensureFullSeq(doc, path, effList)) continue;   // no base to materialize from → leave it on the default
    if (hasAdd) addUniqDoc(doc, path, add);
    if (hasRem) removeDoc(doc, path, rem);
    touched.push(key);
  }
  return touched;
}

/* A fresh profile.yaml for a friend who didn't have one (block style + a short header comment). */
export function newProfileDoc(name) {
  const doc = parseDocument("{}");
  if (doc.contents) doc.contents.flow = false;   // block YAML, not inline {}
  doc.commentBefore =
    ` profile.yaml — MECHANISM overrides for ${name}'s feed, created by the dashboard concierge.\n` +
    ` taste.yaml = CONTENT (what they like); this = MECHANISM (home + scoring dials). Only the knobs\n` +
    ` that differ need to live here — anything absent falls back to the repo defaults.`;
  return doc;
}

async function applyProfileEdit(env, hash, patch) {
  const prof = await resolveProfile(env, hash);
  if (!prof) return { ok: false, error: "profile not found for that session" };
  const path = prof.profilePath;
  // The owner edits the shared root profile.yaml; a friend edits only their own profiles/<name>/profile.yaml.
  const isRoot = /(^|\/)profile\.ya?ml$/.test(path) && !path.startsWith("profiles/");
  if (isRoot && !prof.owner) return { ok: false, error: "this profile can't edit the shared mechanism file" };
  if (!isRoot && !/^profiles\/.+\/profile\.ya?ml$/.test(path)) return { ok: false, error: "this profile has no editable mechanism file" };

  // Effective fallback base for materializing a first-time partial edit (see the block comment):
  // the friend's taste.yaml `scoring`, then the root profile.yaml (= DEFAULT_* verbatim). For the
  // owner, the file IS the root, so its own complete values cover everything and this goes unused.
  let tasteObj = null, rootObj = null;
  if (!isRoot) {
    const rootFile = await ghGetFile(env, "profile.yaml");
    rootObj = rootFile ? safeYaml(rootFile.text) : null;
    if (prof.tastePath) { const tf = await ghGetFile(env, prof.tastePath); tasteObj = tf ? safeYaml(tf.text) : null; }
  }
  const effective = {
    category_weights: effectiveScoringVal("category_weights", tasteObj, rootObj),
    near_home: effectiveScoringVal("near_home_neighborhoods", tasteObj, rootObj),
    penalty: effectiveScoringVal("penalty_terms", tasteObj, rootObj),
    groove: effectiveScoringVal("groove_terms", tasteObj, rootObj),
    far: effectiveScoringVal("far_terms", tasteObj, rootObj),
  };

  const existing = await ghGetFile(env, path);   // null => create a fresh friend profile.yaml
  let out;
  try {
    const doc = existing ? parseDocument(existing.text) : newProfileDoc(prof.name);
    if (existing && doc.errors && doc.errors.length) throw new Error("parse");
    const touched = applyProfilePatchDoc(doc, patch || {}, effective);
    if (!touched.length) return { ok: false, error: "nothing actionable in that change (or no default base to seed from yet — try again in a minute)" };
    out = String(doc);
    const check = yamlParse(out);                 // never commit something that won't parse
    if (!check || typeof check !== "object") throw new Error("invalid");
    const cw = check.scoring && check.scoring.category_weights;
    if (cw && (typeof cw !== "object" || Object.values(cw).some((v) => typeof v !== "number" || !isFinite(v)))) throw new Error("bad weights");
    const co = check.home && check.home.coords;
    if (co && (!Array.isArray(co) || co.length !== 2 || co.some((v) => typeof v !== "number" || !isFinite(v)))) throw new Error("bad coords");
  } catch { return { ok: false, error: "edit produced invalid YAML; nothing changed" }; }

  const msg = `profile(${prof.name}): ${(patch.summary || "self-edit").slice(0, 72)}\n\nMechanism self-edit via the dashboard concierge.`;
  const ok = await ghPutFile(env, path, out, existing ? existing.sha : undefined, msg);
  return ok ? { ok: true, summary: patch.summary || "updated", note: "committed; the feed rebuilds via CI in ~1–2 min" } : { ok: false, error: "commit failed" };
}

/* ===== Per-profile Spotify — browser OAuth → KV refresh-token store → authed raw-payload sync =====
 *
 * The refresh token NEVER leaves Cloudflare. The browser does the OAuth dance; the Worker keeps the
 * token in KV keyed by the profile's feed hash; an authed sync (the daily routine / a CI job that
 * holds SPOTIFY_SYNC_TOKEN) pulls only the RAW top/followed/recently-played payloads — Python's
 * lib/affinity.build_affinity (the one tested builder) turns those into data/spotify/<hash>.json.
 * Nothing here computes taste, and nothing here is committed. See backend/README.md.
 *
 * Routes:
 *   GET  /spotify/login?profile=<hash>[&t=<token>]  -> 302 to Spotify consent
 *   GET  /spotify/callback?code=&state=             -> store token in KV, show a "connected" page
 *   GET  /spotify/status?profile=<hash>             -> { connected, name? }
 *   POST /spotify/disconnect { profile }            -> forget that token
 *   GET  /spotify/connected   (Bearer SPOTIFY_SYNC_TOKEN) -> { connected: [hash,...] }
 *   GET  /spotify/fetch?profile=<hash> (Bearer SPOTIFY_SYNC_TOKEN) -> { top, followed, recent } raw
 *
 * Extra env: KV binding SPOTIFY_KV; secrets SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET,
 * SPOTIFY_SYNC_TOKEN, STATE_SECRET; vars SPOTIFY_REDIRECT_URI, PAGE_URL.
 */
async function handleSpotify(url, request, env, cors) {
  const path = url.pathname;
  if (!env.SPOTIFY_KV) return json({ error: "spotify not configured (no SPOTIFY_KV binding)" }, 501, cors);
  const hashOf = (s) => { const h = String(s || "").toLowerCase(); return /^[0-9a-f]{8,32}$/.test(h) ? h : null; };

  // --- browser: start the OAuth dance ---
  if (path === "/spotify/login" && request.method === "GET") {
    if (!env.SPOTIFY_CLIENT_ID) return htmlPage("Spotify isn't configured on this backend yet.");
    const hash = hashOf(url.searchParams.get("profile"));
    if (!hash) return htmlPage("Log into your profile first, then Connect Spotify.");
    // Optional shared-token gate (the same CONCIERGE_TOKEN the page already holds) so a random
    // visitor can't attach a Spotify to someone's hash. Passed as ?t= since a top-level browser
    // redirect can't carry an Authorization header. Within Ari's circle everyone has this token.
    if (env.CONCIERGE_TOKEN && url.searchParams.get("t") !== env.CONCIERGE_TOKEN)
      return htmlPage("This link needs your concierge access token. Open Connect Spotify from the page.");
    const params = new URLSearchParams({
      client_id: env.SPOTIFY_CLIENT_ID, response_type: "code",
      redirect_uri: spotifyRedirect(env, url), scope: DEFAULTS.SPOTIFY_SCOPES,
      state: await signState(env, hash),
      // Force Spotify's account/consent screen every time so a returning visitor isn't silently
      // re-connected to whatever Spotify session is cached in this browser (e.g. the owner's from
      // testing). Lets the user log in as / switch to their own account.
      show_dialog: "true",
    });
    return Response.redirect(`${DEFAULTS.SPOTIFY_AUTH}/authorize?${params}`, 302);
  }

  // --- browser: Spotify redirects back here with code + state ---
  if (path === "/spotify/callback" && request.method === "GET") {
    const back = env.PAGE_URL || env.ALLOWED_ORIGIN || DEFAULTS.ALLOWED_ORIGIN;
    if (url.searchParams.get("error")) return htmlPage("Spotify connection was cancelled.", back);
    const hash = await verifyState(env, url.searchParams.get("state"));
    const code = url.searchParams.get("code");
    if (!hash || !code) return htmlPage("That link expired or was invalid — try Connect Spotify again.", back);
    let tok;
    try { tok = await spotifyToken(env, { grant_type: "authorization_code", code, redirect_uri: spotifyRedirect(env, url) }); }
    catch { return htmlPage("Couldn't complete the Spotify handshake. Try again in a minute.", back); }
    if (!tok.refresh_token) return htmlPage("Spotify didn't return a refresh token. Try Connect again.", back);
    let name = null;
    try { name = (await spotifyApiGet(`${DEFAULTS.SPOTIFY_API}/me`, tok.access_token)).display_name || null; } catch { /* optional */ }
    await env.SPOTIFY_KV.put("rt:" + hash, JSON.stringify({ rt: tok.refresh_token, name, ts: Date.now() }));
    dispatchSync(env, hash);   // best-effort: kick the rebuild so the feed re-ranks in ~1–2 min
    return htmlPage(`Spotify connected${name ? " — hey " + name : ""}! Your picks re-rank to your listening in a minute or two.`, back);
  }

  // --- browser: is this profile connected? (no token leaked) ---
  if (path === "/spotify/status" && request.method === "GET") {
    const hash = hashOf(url.searchParams.get("profile"));
    if (!hash) return json({ connected: false }, 200, cors);
    const rec = await kvJson(env, "rt:" + hash);
    return json({ connected: !!(rec && rec.rt), name: (rec && rec.name) || null }, 200, cors);
  }

  // --- browser: forget my token ---
  if (path === "/spotify/disconnect" && request.method === "POST") {
    let body = {}; try { body = await request.json(); } catch { /* tolerate */ }
    const hash = hashOf(body.profile);
    if (!hash) return json({ ok: false }, 400, cors);
    await env.SPOTIFY_KV.delete("rt:" + hash);
    return json({ ok: true }, 200, cors);
  }

  // --- sync (authed): who's connected ---
  if (path === "/spotify/connected" && request.method === "GET") {
    if (!syncAuthed(env, request)) return json({ error: "unauthorized" }, 401, cors);
    const out = [];
    let cursor;
    do {
      const list = await env.SPOTIFY_KV.list({ prefix: "rt:", cursor });
      for (const k of list.keys) out.push(k.name.slice(3));
      cursor = list.list_complete ? null : list.cursor;
    } while (cursor);
    return json({ connected: out }, 200, cors);
  }

  // --- sync (authed): raw payloads for one profile (token stays in KV) ---
  if (path === "/spotify/fetch" && request.method === "GET") {
    if (!syncAuthed(env, request)) return json({ error: "unauthorized" }, 401, cors);
    const hash = hashOf(url.searchParams.get("profile"));
    const rec = hash && await kvJson(env, "rt:" + hash);
    if (!rec || !rec.rt) return json({ error: "not connected" }, 404, cors);
    let access;
    try { access = (await spotifyToken(env, { grant_type: "refresh_token", refresh_token: rec.rt })).access_token; }
    catch (e) { return json({ error: "refresh failed", detail: String((e && e.message) || e).slice(0, 200) }, 502, cors); }
    if (!access) return json({ error: "no access token" }, 502, cors);
    try { return json(await spotifyPull(access), 200, cors); }
    catch (e) { return json({ error: "spotify fetch failed", detail: String((e && e.message) || e).slice(0, 200) }, 502, cors); }
  }

  return json({ error: "not found" }, 404, cors);
}

function spotifyRedirect(env, url) {
  return env.SPOTIFY_REDIRECT_URI || `${url.origin}/spotify/callback`;
}
function syncAuthed(env, request) {
  if (!env.SPOTIFY_SYNC_TOKEN) return false;   // closed by default — no token set, no sync access
  return (request.headers.get("authorization") || "") === "Bearer " + env.SPOTIFY_SYNC_TOKEN;
}
async function kvJson(env, key) {
  try { const v = await env.SPOTIFY_KV.get(key); return v ? JSON.parse(v) : null; } catch { return null; }
}
async function spotifyToken(env, form) {
  const basic = btoa(`${env.SPOTIFY_CLIENT_ID}:${env.SPOTIFY_CLIENT_SECRET}`);
  const r = await fetch(`${DEFAULTS.SPOTIFY_AUTH}/api/token`, {
    method: "POST",
    headers: { authorization: "Basic " + basic, "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(form),
  });
  if (!r.ok) throw new Error(r.status + " " + (await r.text().catch(() => "")).slice(0, 200));
  return r.json();
}
async function spotifyApiGet(urlStr, access) {
  const r = await fetch(urlStr, { headers: { authorization: "Bearer " + access, "user-agent": "la-events-concierge" } });
  if (!r.ok) throw new Error(r.status + " " + urlStr);
  return r.json();
}
/* Pull the three open-to-new-apps signals (top / followed / recently-played) — the same set
 * fetch_spotify.py pulls. Raw artist objects only; build_affinity does the weighting in Python. */
async function spotifyPull(access) {
  const A = DEFAULTS.SPOTIFY_API;
  const top = {};
  for (const tr of ["long_term", "medium_term", "short_term"]) {
    top[tr] = (await spotifyApiGet(`${A}/me/top/artists?time_range=${tr}&limit=50`, access)).items || [];
  }
  let followed = [], after = null;
  for (let i = 0; i < 10; i++) {
    const q = new URLSearchParams({ type: "artist", limit: "50" });
    if (after) q.set("after", after);
    const d = (await spotifyApiGet(`${A}/me/following?${q}`, access)).artists || {};
    followed = followed.concat(d.items || []);
    after = (d.cursors || {}).after;
    if (!after || !(d.items || []).length) break;
  }
  const recent = (await spotifyApiGet(`${A}/me/player/recently-played?limit=50`, access)).items || [];
  return { top, followed, recent };
}

/* Signed, short-lived OAuth `state` — binds the login to the callback (CSRF) and carries the hash. */
async function hmacHex(env, msg) {
  const secret = env.STATE_SECRET || env.CONCIERGE_TOKEN || env.SPOTIFY_CLIENT_SECRET || "la-events/state";
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(msg));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
async function signState(env, hash) {
  const body = `${hash}.${Date.now().toString(36)}`;
  return `${body}.${(await hmacHex(env, body)).slice(0, 32)}`;
}
async function verifyState(env, state) {
  const parts = String(state || "").split(".");
  if (parts.length !== 3) return null;
  const [hash, ts, sig] = parts;
  if (!/^[0-9a-f]{8,32}$/.test(hash)) return null;
  if ((await hmacHex(env, `${hash}.${ts}`)).slice(0, 32) !== sig) return null;
  if (Date.now() - parseInt(ts, 36) > DEFAULTS.STATE_TTL_MS) return null;
  return hash;
}

/* Pipeline actions from the dashboard's settings panel — they fire a repository_dispatch that a
 * GitHub Action picks up (same mechanism as spotify-sync), then rebuilds + redeploys:
 *   POST /refresh-events            -> event_type "refresh-events"  (admin: re-fetch all sources,
 *                                      rebuild the catalog + default feed, republish catalog_meta)
 *   POST /rebuild-profile {profile} -> event_type "rebuild-profile" (full LLM pass for ONE profile:
 *                                      editor verdicts + scene enrichment + narrative digest)
 * Gated by the same shared CONCIERGE_TOKEN the chat uses. Owner-only enforcement for refresh is on
 * the page (it only shows the button to owner:true) — consistent with this app's obfuscation model.
 */
async function handlePipeline(url, request, env, cors) {
  if (request.method !== "POST") return json({ error: "POST only" }, 405, cors);
  if (env.CONCIERGE_TOKEN) {
    const auth = request.headers.get("authorization") || "";
    if (auth !== "Bearer " + env.CONCIERGE_TOKEN) return json({ error: "unauthorized" }, 401, cors);
  }
  if (!env.GITHUB_TOKEN) return json({ error: "server missing GITHUB_TOKEN" }, 501, cors);

  let body = {};
  try { body = await request.json(); } catch { /* empty body is fine for /refresh-events */ }
  const repo = env.GITHUB_REPO || DEFAULTS.GITHUB_REPO;

  let event_type, client_payload = {};
  if (url.pathname === "/refresh-events") {
    event_type = "refresh-events";
  } else {
    const hash = typeof body.profile === "string" && /^[0-9a-f]{8,32}$/.test(body.profile) ? body.profile : null;
    if (!hash) return json({ error: "missing or invalid profile hash" }, 400, cors);
    event_type = "rebuild-profile";
    client_payload = { profile: hash };
  }

  try {
    const r = await fetch(`https://api.github.com/repos/${repo}/dispatches`, {
      method: "POST", headers: ghHeaders(env),
      body: JSON.stringify({ event_type, client_payload }),
    });
    if (!r.ok) {
      const detail = await r.text().catch(() => "");
      return json({ error: "dispatch failed", status: r.status, detail: detail.slice(0, 200) }, 502, cors);
    }
  } catch (e) {
    return json({ error: "dispatch error" }, 502, cors);
  }
  return json({ ok: true, dispatched: event_type }, 202, cors);
}

/* Best-effort: nudge a rebuild of this one profile's feed (the spotify-sync workflow). */
async function dispatchSync(env, hash) {
  if (!env.GITHUB_TOKEN) return;
  const repo = env.GITHUB_REPO || DEFAULTS.GITHUB_REPO;
  try {
    await fetch(`https://api.github.com/repos/${repo}/dispatches`, {
      method: "POST", headers: ghHeaders(env),
      body: JSON.stringify({ event_type: "spotify-sync", client_payload: { profile: hash } }),
    });
  } catch { /* best-effort; the daily routine will catch it otherwise */ }
}

function esc(s) { return String(s).replace(/[<>&"]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;" }[c])); }
function htmlPage(message, back) {
  const home = back ? `<p style="margin-top:1.4rem"><a href="${esc(back)}" style="color:#1db954;font-weight:600">← back to la-events</a></p>` : "";
  const body = `<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">` +
    `<title>la-events × Spotify</title>` +
    `<body style="font:16px/1.55 -apple-system,system-ui,sans-serif;max-width:32rem;margin:16vh auto;padding:0 1.2rem;color:#1b1a17;background:#f7f6f2">` +
    `<div style="font:600 12px/1 ui-monospace,Menlo,monospace;letter-spacing:.07em;color:#1db954">SPOTIFY × LA-EVENTS</div>` +
    `<p style="font-size:18px;margin:.7rem 0 0">${esc(message)}</p>${home}` +
    `<p style="color:#76746b;font-size:13px;margin-top:1.6rem">You can close this tab.</p></body>`;
  return new Response(body, { status: 200, headers: { "content-type": "text/html; charset=utf-8" } });
}
