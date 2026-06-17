/* Plan view: a conversational front-end to the catalog.
 *
 * Two tiers, by design (graceful degradation — the ROADMAP value):
 *   1. LOCAL assistant (no LLM): parse the ask ("this weekend, Silver Lake, house,
 *      best") into filters, query the loaded catalog, and answer inline with picks +
 *      actions. Works offline, instantly, for free. This is "help me sort the database".
 *   2. AGENT hand-off (the brain): compose a precise concierge/night-planner prompt
 *      (ask + dashboard context + starred anchors + candidates) and send it via the
 *      hand-off seam. This is "create custom plans".
 */

import {
  App, $, el, on, emit, fmtDateChip, fmtTime, dedupeLinks, linkLabel,
  isSaved, toggleSaved, savedEvents, eventKey, starsNode, catLabel,
} from "./data.js";
import { downloadICS } from "./ics.js";
import { handoffToAgent, repoContext } from "./handoff.js";

let logEl, footEl;

const SUGGESTIONS = [
  "What's on this weekend near me?",
  "Best house / techno shows coming up",
  "Plan my Saturday night — dinner then a show",
  "Free things to do this week",
  "Rooftop or vinyl parties",
  "Rep cinema this weekend",
];

export function mountChat(root) {
  root.innerHTML = "";
  logEl = el("div", { className: "chat-log" });
  const input = el("input", { type: "text", placeholder: "Ask me anything — \"chill walkable Friday, no techno\"…", autocomplete: "off" });
  const send = el("button", { className: "btn primary", type: "submit", textContent: "Ask" });
  const form = el("form", { className: "chat-input" }, input, send);
  form.onsubmit = (e) => { e.preventDefault(); const t = input.value.trim(); if (!t) return; input.value = ""; ask(t); };
  footEl = el("div", { className: "chat-foot" });

  root.append(logEl, form, footEl);
  intro();
  paintFoot();
  input.focus();
}

function intro() {
  const chips = el("div", { className: "suggestions" });
  for (const s of SUGGESTIONS) chips.append(el("button", { className: "pill", textContent: s, onclick: () => ask(s) }));
  pushAssistant(
    el("p", {}, el("strong", { textContent: "I'm your LA concierge. " }),
      document.createTextNode("Tell me a day, a vibe, a neighborhood — I'll pull from the catalog right here. Want a full night out (dinner → show → afters)? Star a few and I'll hand it to the planner.")),
    chips);
}

function paintFoot() {
  footEl.innerHTML = "";
  const n = App.saved.size;
  footEl.append(el("span", { className: "saved-count", textContent: n ? `★ ${n} saved` : "Star events to plan around them" }));
  if (n) {
    const b = el("button", { className: "btn primary sm", textContent: `Build a plan from ${n} saved →` });
    b.onclick = () => buildPlan(`Build a night around my ${n} saved events.`, { from: "", to: "", hood: "", cats: new Set(), q: "" }, []);
    footEl.append(b);
    const clear = el("button", { className: "btn sm", textContent: "Clear", onclick: () => { App.saved.clear(); localStorage.setItem("la-saved", "[]"); emit("saved:change"); } });
    footEl.append(clear);
  }
}

/* ── Conversation rendering ──────────────────────────────────────────────── */
function pushUser(text) {
  logEl.append(el("div", { className: "msg user" }, el("div", { className: "bubble", textContent: text })));
  scroll();
}
function pushAssistant(...nodes) {
  logEl.append(el("div", { className: "msg bot" }, el("div", { className: "bubble" }, ...nodes)));
  scroll();
}
function scroll() { logEl.scrollTop = logEl.scrollHeight; }

function ask(text) {
  pushUser(text);
  const parsed = parseQuery(text);
  const list = localQuery(parsed);

  if (parsed.wantsPlan) {
    respondPlanIntent(text, parsed, list);
  } else {
    respondQuery(text, parsed, list);
  }
}

/* ── The response shapes ─────────────────────────────────────────────────── */
function respondQuery(text, parsed, list) {
  if (!list.length) {
    pushAssistant(
      el("p", { textContent: `Nothing in the catalog matched ${parsed.scopeLabel}. Want me to widen it?` }),
      actionRow(
        ["Show everything upcoming", () => { applyToExplore({}); }],
        ["Turn this into a plan →", () => buildPlan(text, parsed, list)]));
    return;
  }
  const top = list.slice(0, 6);
  pushAssistant(
    el("p", {}, el("strong", { textContent: `${list.length} ${list.length === 1 ? "match" : "matches"} ${parsed.scopeLabel}. ` }),
      document.createTextNode(top.length < list.length ? `Top ${top.length}:` : "")),
    resultList(top),
    actionRow(
      [`Show all ${list.length} in Explore`, () => applyToExplore(parsed)],
      ["Make it a plan →", () => buildPlan(text, parsed, list)]));
}

function respondPlanIntent(text, parsed, list) {
  const top = list.slice(0, 6);
  pushAssistant(
    el("p", {}, document.createTextNode("Good candidates for that"),
      el("strong", { textContent: list.length ? ` (${list.length} found)` : "" }),
      document.createTextNode(". Star the ones you want as anchors, then build the plan — I'll sequence dinner → show → afters with travel times.")),
    list.length ? resultList(top) : el("p", { className: "dim", textContent: "No tight matches in the catalog — the planner can still work from your description and the dining list." }),
    actionRow(
      ["Build my plan →", () => buildPlan(text, parsed, list), "primary"],
      list.length ? [`Show ${list.length} in Explore`, () => applyToExplore(parsed)] : null));
}

function actionRow(...pairs) {
  const row = el("div", { className: "chat-actions" });
  for (const p of pairs) {
    if (!p) continue;
    const [label, fn, cls] = p;
    row.append(el("button", { className: "btn sm " + (cls || ""), textContent: label, onclick: fn }));
  }
  return row;
}

function resultList(list) {
  const wrap = el("div", { className: "result-list" });
  for (const ev of list) wrap.append(miniCard(ev));
  return wrap;
}

function miniCard(ev) {
  const c = el("div", { className: "mini" });
  const when = ev.iso_date ? (() => { const { dow, md } = fmtDateChip(ev.iso_date); const t = fmtTime(ev.start); return `${dow} ${md}${t ? " · " + t : ""}`; })() : "";
  const links = dedupeLinks(ev.links);
  c.append(el("div", { className: "mini-when" }, document.createTextNode(when), starsNode(ev.rating || 0)));
  c.append(links[0]
    ? el("div", { className: "mini-title" }, el("a", { href: links[0].url, target: "_blank", rel: "noopener", textContent: ev.title || "Untitled" }))
    : el("div", { className: "mini-title", textContent: ev.title || "Untitled" }));
  c.append(el("div", { className: "mini-venue", textContent: [ev.venue, ev.neighborhood].filter(Boolean).join(" · ") }));
  const note = ev.enrichment?.curator_note;
  if (note) c.append(el("div", { className: "mini-note", textContent: note }));

  const actions = el("div", { className: "mini-actions" });
  const sb = el("button", { className: "save-btn sm" });
  const paint = () => { const on = isSaved(ev); sb.textContent = on ? "★" : "☆"; sb.title = on ? "Saved" : "Save"; sb.classList.toggle("on", on); };
  sb.onclick = () => { toggleSaved(ev); paint(); };
  paint();
  const cal = el("button", { className: "cal-link sm", textContent: "＋ ics", title: "Download .ics", onclick: () => downloadICS(ev) });
  actions.append(sb, cal);
  c.append(actions);
  return c;
}

/* ── Local query engine (no LLM) ─────────────────────────────────────────── */
const pad = (n) => String(n).padStart(2, "0");
const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const WDAYS = { sunday: 0, sun: 0, monday: 1, mon: 1, tuesday: 2, tue: 2, tues: 2, wednesday: 3, wed: 3, thursday: 4, thu: 4, thurs: 4, friday: 5, fri: 5, saturday: 6, sat: 6 };

function weekendRange(base) {
  const dow = base.getDay();
  let fri;
  if (dow === 0) fri = addDays(base, -2);
  else if (dow >= 5) fri = addDays(base, -(dow - 5));
  else fri = addDays(base, 5 - dow);
  return { fri, sun: addDays(fri, 2) };
}

export function parseQuery(text) {
  const t = " " + text.toLowerCase() + " ";
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const p = { from: "", to: "", hood: "", cats: new Set(), q: "", minRating: 0,
              free: false, afterhours: false, nearHome: false, wantsPlan: false, scopeLabel: "" };
  const scopeBits = [];

  // date scope
  if (/\btonight\b|\btoday\b/.test(t)) { p.from = p.to = iso(today); scopeBits.push("tonight"); }
  else if (/\btomorrow\b/.test(t)) { const d = addDays(today, 1); p.from = p.to = iso(d); scopeBits.push("tomorrow"); }
  else if (/\bnext weekend\b/.test(t)) { const w = weekendRange(addDays(weekendRange(today).fri, 7)); p.from = iso(w.fri); p.to = iso(w.sun); scopeBits.push("next weekend"); }
  else if (/\bthis weekend\b|\bweekend\b/.test(t)) { const w = weekendRange(today); p.from = iso(w.fri); p.to = iso(w.sun); scopeBits.push("this weekend"); }
  else if (/\bnext week\b/.test(t)) { p.from = iso(addDays(today, 7)); p.to = iso(addDays(today, 14)); scopeBits.push("next week"); }
  else if (/\bthis week\b/.test(t)) { p.from = iso(today); p.to = iso(addDays(today, 7)); scopeBits.push("this week"); }
  else {
    for (const [name, dow] of Object.entries(WDAYS)) {
      if (new RegExp(`\\b${name}\\b`).test(t)) {
        let d = new Date(today); const cur = d.getDay();
        let add = (dow - cur + 7) % 7; if (add === 0) add = 0; // today if same day
        d = addDays(d, add);
        p.from = p.to = iso(d); scopeBits.push(name.slice(0, 1).toUpperCase() + name.slice(1));
        break;
      }
    }
  }

  // location
  if (/\bnear me\b|\bnear home\b|\bwalkable\b|\bclose by\b|\bnearby\b|\bmy area\b/.test(t)) { p.nearHome = true; scopeBits.push("near home"); }
  const hoods = App.feed?.neighborhoods || [];
  let best = "";
  for (const h of hoods) if (t.includes(" " + h.toLowerCase())) { if (h.length > best.length) best = h; }
  if (best) { p.hood = best; scopeBits.push("in " + best); }

  // category / vibe — genre words map to a category (don't ALSO use them as a text
  // filter, or you double-constrain: electronic AND title-contains-"house" → near-zero).
  const add = (c) => p.cats.add(c);
  if (/\bfilm\b|\bmovie\b|\bcinema\b|\bscreening\b|\brep cinema\b/.test(t)) add("film");
  if (/\bcomedy\b|\bstand-?up\b/.test(t)) add("comedy");
  if (/\btheat(er|re)\b|\bplay\b|\bmusical\b/.test(t)) add("theater");
  // nightlife bucket — house/techno/party/warehouse all want the electronic + party rows
  if (/\bpart(y|ies)\b|\bclub\b|\brave\b|\bdance\b|\bwarehouse\b|\bdj\b|\belectronic\b|\bhouse\b|\btechno\b|\bdisco\b|\bafro\b|\bminimal\b|\bmelodic\b|\btech-?house\b|\bacid\b/.test(t)) { add("electronic"); add("party"); }
  if (/\blive music\b|\bband\b|\bconcert\b|\bgig\b|\bindie\b|\brock\b|\bjazz\b/.test(t)) { add("live_music"); add("music"); }
  if (/\bbeer\b|\bbrewery\b|\bfood\b|\bmarket\b|\bflea\b/.test(t)) add("beer_food");

  // pure vibe modifiers (NOT categories) — narrow within results via title/enrichment text
  const vibe = ["vinyl", "rooftop", "sunset", "balearic", "groove", "listening bar"].filter((w) => t.includes(" " + w));
  if (vibe.length) p.q = vibe[0];
  if (/\bafterhours\b|\bafter-?hours\b/.test(t)) p.afterhours = true;
  if (/\bfree\b|\bno cover\b/.test(t)) { p.free = true; scopeBits.push("free"); }

  // rating intent
  if (/\bbest\b|\btop\b|\bgreat\b|\bmust\b|\bhighly\b|\brecommend/.test(t)) p.minRating = 4;

  // plan intent
  if (/\bplan\b|\bitinerary\b|\bnight out\b|\bmake a night\b|\bdinner\b|then a |then the |\bafters?\b|\bsort me out\b/.test(t)) p.wantsPlan = true;

  if (p.cats.size) scopeBits.push([...p.cats].map(catLabel).join("/"));
  if (p.minRating) scopeBits.push("top-rated");
  p.scopeLabel = scopeBits.length ? scopeBits.join(", ") : "across the catalog";
  return p;
}

function nearHoodSet() {
  return new Set((App.feed?.config?.scoring?.near_home_neighborhoods || []).map((s) => s.toLowerCase()));
}

export function localQuery(p) {
  const near = p.nearHome ? nearHoodSet() : null;
  const out = App.feed.events.filter((ev) => {
    if (ev.is_past) return false;
    if (p.from && ev.iso_date && ev.iso_date < p.from) return false;
    if (p.to && ev.iso_date && ev.iso_date > p.to) return false;
    if (p.hood && ev.neighborhood !== p.hood) return false;
    if (near && !near.has((ev.neighborhood || "").toLowerCase())) return false;
    if (p.cats.size && !p.cats.has(ev.category)) return false;
    if (p.minRating && (ev.rating || 0) < p.minRating) return false;
    if (p.free && !/\bfree\b|no cover/i.test(ev.price || "")) return false;
    if (p.afterhours && !ev.afterhours) return false;
    if (p.q) {
      const en = ev.enrichment || {};
      const hay = [ev.title, ...(ev.lineup || []), en.type, en.curator_note, ...(en.subgenres || [])].filter(Boolean).join(" ").toLowerCase();
      if (!hay.includes(p.q)) return false;
    }
    return true;
  });
  // Best-first for conversational answers (rating, then soonest).
  return out.sort((a, b) => (b.rating - a.rating) || (a.iso_date || "").localeCompare(b.iso_date || ""));
}

function applyToExplore(p) {
  emit("explore:set", { from: p.from || "", to: p.to || "", hood: p.hood || "",
    cats: p.cats || new Set(), q: p.q || "", minRating: p.minRating || 0, free: !!p.free });
  emit("nav:explore");
}

/* ── Agent hand-off: compose a concierge/night-planner prompt ─────────────── */
function evLine(ev) {
  const when = ev.iso_date ? (() => { const { dow, md } = fmtDateChip(ev.iso_date); return `${dow} ${md}`; })() : "TBD";
  const link = dedupeLinks(ev.links)[0]?.url;
  return `- ${ev.title} — ${ev.venue || "venue TBA"}${ev.neighborhood ? ", " + ev.neighborhood : ""}, ${when}`
    + ` (${ev.rating || "?"}★)${link ? " " + link : ""}`;
}

function buildPlan(text, parsed, list) {
  const saved = savedEvents();
  const savedKeys = new Set(saved.map(eventKey));
  const candidates = (list || []).filter((e) => !savedKeys.has(eventKey(e))).slice(0, 5);

  const where = parsed.nearHome ? "near home (Silver Lake)" : (parsed.hood || "anywhere reasonable");
  const when = parsed.from ? (parsed.from === parsed.to ? parsed.from : `${parsed.from} → ${parsed.to}`) : "(open)";
  const vibe = [[...(parsed.cats || [])].map(catLabel).join("/"), parsed.q, parsed.free && "free", parsed.afterhours && "afterhours", parsed.minRating && "top-rated only"].filter(Boolean).join(", ") || "(open)";

  const prompt = [
    "Act as my LA concierge (la-events / night-planner). Build me a plan from this request:",
    `"${text}"`,
    "",
    "Constraints I set in the dashboard:",
    `- When: ${when}`,
    `- Area: ${where}`,
    `- Vibe/filters: ${vibe}`,
    "",
    "Events I've starred as anchors (use if they fit):",
    saved.length ? saved.map(evLine).join("\n") : "(none yet)",
    "",
    "On-taste candidates the dashboard surfaced:",
    candidates.length ? candidates.map(evLine).join("\n") : "(none — work from the catalog + dining list)",
    "",
    "Please rank against taste.yaml, then sequence dinner → show → afters with real travel",
    "times (scripts/travel.py / the night-planner agent), include booking links, and keep it",
    "tight and opinionated. Commit any itinerary/digest output so it shows up on the page.",
    "",
    repoContext(),
  ].join("\n");

  handoffToAgent({ title: "Build my night — hand off to the planner", prompt });
}

on("saved:change", () => { if (footEl) paintFoot(); });
