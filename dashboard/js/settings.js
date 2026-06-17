/* Settings view: read the config snapshot (from data.json), stage edits in a working
 * copy, preview a human-readable change-set, and hand it to the agent to apply+commit
 * the real YAML. The page never writes YAML itself (no backend) — it composes a precise
 * instruction; the agent edits taste.yaml / profile.yaml / sources.yaml and commits, so
 * the source of truth stays in the files and comments/ordering are preserved.
 *
 * Also hosts the Pipeline actions that tie into the daily run: refresh events, discover
 * sources — each a hand-off so the page works hand-in-hand with the scheduled routine. */

import { App, $, el } from "./data.js";
import { handoffToAgent, repoContext } from "./handoff.js";

let working;   // structuredClone of feed.config, mutated in place by the widgets

export function mountSettings(root) {
  root.innerHTML = "";
  const cfg = App.feed.config;
  if (!cfg) { root.append(el("div", { className: "empty" }, el("h2", { textContent: "No config in this feed" }), el("p", { textContent: "Rebuild data.json with the updated scripts/build_dashboard.py." }))); return; }
  working = structuredClone(cfg);

  root.append(
    el("p", { className: "settings-intro" },
      document.createTextNode("Tune what the engine surfaces. Changes are staged here, then applied by your Claude Code session — they take effect on the "),
      el("strong", { textContent: "next daily run" }),
      document.createTextNode(" (or hit “Refresh events” below to re-score now).")),

    section("Taste — what you like", "taste.yaml",
      sub("Tracked artists (+2 & a badge when in a lineup)"), chips(working.taste.artists_tracked),
      sub("Loved venues (+1)"), chips(working.taste.venues_loved),
      sub("Loved comedians (the comedy exception)"), chips(working.taste.comedians_loved),
      sub("Pinned series (always surface when on)"), chips(working.taste.pinned_series),
      sub("High-interest categories (+3)"), rows(working.taste.categories.high),
      sub("Medium (+2)"), rows(working.taste.categories.medium),
      sub("Low — include only if exceptional (+1)"), rows(working.taste.categories.low),
      sub("Boosts (+1 each)"), rows(working.taste.boosts),
      sub("Penalties (−2 each)"), rows(working.taste.penalties)),

    section("Scoring mechanics", "profile.yaml",
      sub("Category weights"), numberMap(working.scoring.category_weights),
      sub("Rating thresholds  [min score → ★]"), thresholds(working.scoring.rating_thresholds),
      sub("Near-home neighborhoods (+1)"), chips(working.scoring.near_home_neighborhoods),
      sub("Groove terms (+1)"), chips(working.scoring.groove_terms),
      sub("European-vibe terms (+1)"), chips(working.scoring.eu_terms),
      sub("Penalty terms (−2 each)"), chips(working.scoring.penalty_terms),
      sub("Far-flung terms (−2)"), chips(working.scoring.far_terms),
      sub("Spotify tier points"), numberMap(working.scoring.spotify.tier_points || {}),
      sub("Spotify caps & genre"), numberMap(working.scoring.spotify, ["artist_cap", "genre_points", "genre_threshold", "genre_cap", "min_name_len"]),
      sub("Feedback weights"), numberMap(working.scoring.feedback.weights || {})),

    section("Home base", "profile.yaml",
      homeFields(working.home)),

    section("Sources", "sources.yaml",
      sourceTable(working.sources)),

    pipelineSection(),

    reviewBar());

  // wire the spotify caps subset back onto the object (numberMap mutates the subset clone)
}

/* ── Layout helpers ──────────────────────────────────────────────────────── */
function section(title, file, ...kids) {
  return el("section", { className: "settings-section" },
    el("div", { className: "settings-head" },
      el("h2", { textContent: title }),
      el("span", { className: "file-tag", textContent: file })),
    ...kids);
}
const sub = (t) => el("h4", { className: "settings-sub", textContent: t });

/* ── Widgets (mutate the passed array/object in place) ───────────────────── */
function chips(arr) {
  const wrap = el("div", { className: "chips" });
  const repaint = () => {
    wrap.innerHTML = "";
    arr.forEach((v, i) => {
      wrap.append(el("span", { className: "chip" }, document.createTextNode(String(v)),
        el("button", { className: "chip-x", textContent: "×", title: "remove", onclick: () => { arr.splice(i, 1); repaint(); markDirty(); } })));
    });
    const inp = el("input", { className: "chip-add", type: "text", placeholder: "add…" });
    inp.onkeydown = (e) => { if (e.key === "Enter" && inp.value.trim()) { arr.push(inp.value.trim()); repaint(); markDirty(); wrap.querySelector(".chip-add").focus(); } };
    wrap.append(inp);
  };
  repaint();
  return wrap;
}

function rows(arr) {
  const wrap = el("div", { className: "rows" });
  const repaint = () => {
    wrap.innerHTML = "";
    arr.forEach((v, i) => {
      const ta = el("textarea", { className: "row-text", rows: 1, value: String(v) });
      ta.oninput = () => { arr[i] = ta.value; markDirty(); autoGrow(ta); };
      requestAnimationFrame(() => autoGrow(ta));
      wrap.append(el("div", { className: "row" }, ta,
        el("button", { className: "chip-x", textContent: "×", onclick: () => { arr.splice(i, 1); repaint(); markDirty(); } })));
    });
    const add = el("button", { className: "btn sm", textContent: "+ add line", onclick: () => { arr.push(""); repaint(); markDirty(); } });
    wrap.append(add);
  };
  repaint();
  return wrap;
}
function autoGrow(ta) { ta.style.height = "auto"; ta.style.height = ta.scrollHeight + "px"; }

function numberMap(obj, keys) {
  const wrap = el("div", { className: "num-grid" });
  for (const k of (keys || Object.keys(obj))) {
    if (!(k in obj)) continue;
    const inp = el("input", { className: "num", type: "number", step: "any", value: obj[k] });
    inp.onchange = () => { obj[k] = numlike(inp.value); markDirty(); };
    wrap.append(el("label", { className: "num-field" }, el("span", { textContent: k }), inp));
  }
  return wrap;
}

function thresholds(arr) {
  const wrap = el("div", { className: "thresholds" });
  const repaint = () => {
    wrap.innerHTML = "";
    arr.forEach((pair, i) => {
      const a = el("input", { className: "num", type: "number", step: "any", value: pair[0] });
      const b = el("input", { className: "num", type: "number", step: "any", value: pair[1] });
      a.onchange = () => { pair[0] = numlike(a.value); markDirty(); };
      b.onchange = () => { pair[1] = numlike(b.value); markDirty(); };
      wrap.append(el("div", { className: "threshold-row" }, el("span", { textContent: "≥" }), a, el("span", { textContent: "→" }), b, el("span", { textContent: "★" }),
        el("button", { className: "chip-x", textContent: "×", onclick: () => { arr.splice(i, 1); repaint(); markDirty(); } })));
    });
    wrap.append(el("button", { className: "btn sm", textContent: "+ threshold", onclick: () => { arr.push([0, 1]); repaint(); markDirty(); } }));
  };
  repaint();
  return wrap;
}

function homeFields(home) {
  const wrap = el("div", { className: "num-grid" });
  const text = (key, label) => {
    const inp = el("input", { className: "num wide", type: "text", value: home[key] ?? "" });
    inp.onchange = () => { home[key] = inp.value; markDirty(); };
    return el("label", { className: "num-field" }, el("span", { textContent: label }), inp);
  };
  wrap.append(text("neighborhood", "neighborhood"), text("cross_streets", "cross streets"));
  const coords = home.coords || [null, null];
  const lat = el("input", { className: "num", type: "number", step: "any", value: coords[0] ?? "" });
  const lon = el("input", { className: "num", type: "number", step: "any", value: coords[1] ?? "" });
  lat.onchange = () => { home.coords = [numlike(lat.value), numlike(lon.value)]; markDirty(); };
  lon.onchange = () => { home.coords = [numlike(lat.value), numlike(lon.value)]; markDirty(); };
  wrap.append(el("label", { className: "num-field" }, el("span", { textContent: "lat" }), lat),
    el("label", { className: "num-field" }, el("span", { textContent: "lon" }), lon));
  return wrap;
}

const STATUSES = ["active", "flaky", "candidate", "manual", "dead"];
function sourceTable(sources) {
  const wrap = el("div", { className: "src-table" });
  for (const s of sources) {
    const sel = el("select", { className: "src-status" });
    for (const st of STATUSES) sel.append(el("option", { value: st, textContent: st, selected: st === s.status }));
    sel.onchange = () => { s.status = sel.value; markDirty(); };
    wrap.append(el("div", { className: "src-row" },
      el("div", { className: "src-name", textContent: s.name || "(unnamed)" }),
      el("div", { className: "src-meta", textContent: [s.category, s.method, s.priority != null ? "p" + s.priority : ""].filter(Boolean).join(" · ") }),
      sel));
  }
  wrap.append(el("p", { className: "dim", textContent: "Adding a source is a discovery task — use “Discover sources” below; the scout returns a vetted proposal." }));
  return wrap;
}

function pipelineSection() {
  const refresh = el("button", { className: "btn", textContent: "Refresh events now ↻" });
  refresh.onclick = () => handoffToAgent({
    title: "Refresh the catalog",
    prompt: ["Run the la-events daily weekend-digest routine on this repo (see routines/daily-digest-prompt.md):",
      "run_digest core → layer in webfetch/Gmail/editorial → enrich top candidates → cache images →",
      "render the upcoming weekends → rebuild the dashboard (python scripts/build_dashboard.py) → commit.",
      "Degrade gracefully on dead sources; note them in the footer.", "", repoContext()].join("\n"),
  });
  const discover = el("button", { className: "btn", textContent: "Discover sources ⌕" });
  discover.onclick = () => handoffToAgent({
    title: "Discover new sources",
    prompt: ["Run la-events Discover mode via the source-scout agent: gap-mine the catalog, probe any",
      "venue/promoter links, sweep directories. Return a vetted PROPOSAL table — do NOT modify",
      "sources.yaml without my approval (marking existing sources flaky/dead is fine).", "", repoContext()].join("\n"),
  });
  return el("section", { className: "settings-section" },
    el("div", { className: "settings-head" }, el("h2", { textContent: "Pipeline" }), el("span", { className: "file-tag", textContent: "daily run" })),
    el("p", { className: "dim", textContent: "The catalog refreshes on a daily routine. Kick one off or look for new sources on demand." }),
    el("div", { className: "pipeline-actions" }, refresh, discover));
}

/* ── Review + apply ──────────────────────────────────────────────────────── */
let dirty = false;
let reviewBtn;
function markDirty() { dirty = true; if (reviewBtn) { reviewBtn.disabled = false; reviewBtn.textContent = "Review changes"; } }

function reviewBar() {
  reviewBtn = el("button", { className: "btn primary", textContent: "No changes yet", disabled: true });
  reviewBtn.onclick = openReview;
  return el("div", { className: "review-bar" }, reviewBtn);
}

function openReview() {
  const changes = diffConfig(App.feed.config, working);
  if (!changes.length) return;
  const byFile = {};
  for (const c of changes) (byFile[c.file] ||= []).push(c.detail);

  const body = el("div", { className: "review-body" });
  for (const file of Object.keys(byFile)) {
    body.append(el("h4", { textContent: file }));
    const ul = el("ul");
    for (const d of byFile[file]) ul.append(el("li", { textContent: d }));
    body.append(ul);
  }

  const prompt = composeSettingsPrompt(byFile);
  const apply = el("button", { className: "btn primary", textContent: "Apply via Claude Code →" });
  apply.onclick = () => handoffToAgent({ title: "Apply settings changes", prompt });

  const overlay = el("div", { className: "modal-overlay", id: "review-modal" },
    el("div", { className: "modal" },
      el("div", { className: "modal-head" }, el("h3", { textContent: "Review changes" }),
        el("button", { className: "modal-x", textContent: "✕", onclick: () => overlay.remove() })),
      el("p", { className: "modal-sub", textContent: "These will be applied to the YAML and committed by your Claude Code session, then take effect on the next run." }),
      body,
      el("div", { className: "modal-actions" }, apply)));
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
  document.body.append(overlay);
}

function composeSettingsPrompt(byFile) {
  const lines = ["Apply these settings changes to the la-events repo, then commit. Edit the YAML by hand,",
    "preserving comments, ordering, and style. Make ONLY these changes:", ""];
  for (const file of Object.keys(byFile)) {
    lines.push(`## ${file}`);
    for (const d of byFile[file]) lines.push(`- ${d}`);
    lines.push("");
  }
  lines.push("Then run `python scripts/build_dashboard.py` and commit so the dashboard reflects them.");
  lines.push("They otherwise take effect on the next daily run (re-scoring the catalog).", "", repoContext());
  return lines.join("\n");
}

/* ── Diff ────────────────────────────────────────────────────────────────── */
function diffConfig(orig, cur) {
  const out = [];
  const T = "taste.yaml", P = "profile.yaml", S = "sources.yaml";

  // taste lists
  listDiff(out, T, "Tracked artists", orig.taste.artists_tracked, cur.taste.artists_tracked);
  listDiff(out, T, "Loved venues", orig.taste.venues_loved, cur.taste.venues_loved);
  listDiff(out, T, "Loved comedians", orig.taste.comedians_loved, cur.taste.comedians_loved);
  listDiff(out, T, "Pinned series", orig.taste.pinned_series, cur.taste.pinned_series);
  listDiff(out, T, "High categories", orig.taste.categories.high, cur.taste.categories.high);
  listDiff(out, T, "Medium categories", orig.taste.categories.medium, cur.taste.categories.medium);
  listDiff(out, T, "Low categories", orig.taste.categories.low, cur.taste.categories.low);
  listDiff(out, T, "Boosts", orig.taste.boosts, cur.taste.boosts);
  listDiff(out, T, "Penalties", orig.taste.penalties, cur.taste.penalties);

  // scoring
  mapDiff(out, P, "scoring.category_weights", orig.scoring.category_weights, cur.scoring.category_weights);
  if (JSON.stringify(orig.scoring.rating_thresholds) !== JSON.stringify(cur.scoring.rating_thresholds))
    out.push({ file: P, detail: `scoring.rating_thresholds → ${JSON.stringify(cur.scoring.rating_thresholds)}` });
  listDiff(out, P, "scoring.near_home_neighborhoods", orig.scoring.near_home_neighborhoods, cur.scoring.near_home_neighborhoods);
  listDiff(out, P, "scoring.groove_terms", orig.scoring.groove_terms, cur.scoring.groove_terms);
  listDiff(out, P, "scoring.eu_terms", orig.scoring.eu_terms, cur.scoring.eu_terms);
  listDiff(out, P, "scoring.penalty_terms", orig.scoring.penalty_terms, cur.scoring.penalty_terms);
  listDiff(out, P, "scoring.far_terms", orig.scoring.far_terms, cur.scoring.far_terms);
  mapDiff(out, P, "scoring.spotify.tier_points", orig.scoring.spotify.tier_points || {}, cur.scoring.spotify.tier_points || {});
  for (const k of ["artist_cap", "genre_points", "genre_threshold", "genre_cap", "min_name_len"])
    if ((orig.scoring.spotify || {})[k] !== (cur.scoring.spotify || {})[k])
      out.push({ file: P, detail: `scoring.spotify.${k}: ${fmt(orig.scoring.spotify?.[k])} → ${fmt(cur.scoring.spotify?.[k])}` });
  mapDiff(out, P, "scoring.feedback.weights", orig.scoring.feedback.weights || {}, cur.scoring.feedback.weights || {});

  // home
  for (const k of ["neighborhood", "cross_streets"])
    if ((orig.home || {})[k] !== (cur.home || {})[k]) out.push({ file: P, detail: `home.${k}: ${fmt(orig.home?.[k])} → ${fmt(cur.home?.[k])}` });
  if (JSON.stringify(orig.home?.coords) !== JSON.stringify(cur.home?.coords))
    out.push({ file: P, detail: `home.coords → ${JSON.stringify(cur.home?.coords)}` });

  // sources (status by name)
  const om = Object.fromEntries((orig.sources || []).map((s) => [s.name, s.status]));
  for (const s of cur.sources || []) if (om[s.name] !== s.status) out.push({ file: S, detail: `"${s.name}": status ${om[s.name]} → ${s.status}` });

  return out;
}

function listDiff(out, file, label, a, b) {
  const A = new Set((a || []).map(String)), B = new Set((b || []).map(String));
  const added = [...B].filter((x) => !A.has(x)), removed = [...A].filter((x) => !B.has(x));
  if (added.length) out.push({ file, detail: `${label}: add ${added.map(q).join(", ")}` });
  if (removed.length) out.push({ file, detail: `${label}: remove ${removed.map(q).join(", ")}` });
}
function mapDiff(out, file, label, a, b) {
  const keys = new Set([...Object.keys(a || {}), ...Object.keys(b || {})]);
  for (const k of keys) if (fmt(a?.[k]) !== fmt(b?.[k])) out.push({ file, detail: `${label}.${k}: ${fmt(a?.[k])} → ${fmt(b?.[k])}` });
}

const q = (s) => `"${s}"`;
const fmt = (v) => (v === undefined ? "—" : JSON.stringify(v));
function numlike(v) { if (v === "" || v == null) return v; const n = Number(v); return Number.isNaN(n) ? v : n; }
