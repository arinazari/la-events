/* Explore view: the filterable, taste-ranked event grid. Pure viewer over the
 * precomputed feed. Reworked to the real catalog schema + enrichment, with a
 * "save for a plan" star and a hook (emit "explore:set") so the chatbox can drive it. */

import {
  App, $, el, on, emit, defaultExploreState,
  CAT_LABELS, catLabel, fmtDateChip, fmtTime, dedupeLinks, linkLabel,
  priceLabel, isFreeish, isLovedVenue, trackedInLineup, starsNode,
  isSaved, toggleSaved,
} from "./data.js";
import { downloadICS } from "./ics.js";

let refs = {};

export function mountExplore(root) {
  root.innerHTML = "";
  const f = App.feed;

  // ── Controls ──────────────────────────────────────────────────────────
  const search = el("div", { className: "search" });
  search.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"></circle><path d="m21 21-4.3-4.3"></path></svg>`;
  const q = el("input", { type: "search", placeholder: "Search title, venue, artist, neighborhood, vibe…", autocomplete: "off" });
  q.oninput = (e) => { App.explore.q = e.target.value.toLowerCase().trim(); render(); };
  search.append(q);

  const pills = el("div", { className: "pills" });
  for (const c of f.categories) {
    const p = el("button", { className: "pill", textContent: catLabel(c) });
    p.onclick = () => {
      App.explore.cats.has(c) ? App.explore.cats.delete(c) : App.explore.cats.add(c);
      p.classList.toggle("active"); render();
    };
    p.dataset.cat = c;
    pills.append(p);
  }

  const hood = el("select");
  hood.append(el("option", { value: "", textContent: "All neighborhoods" }));
  for (const h of f.neighborhoods) hood.append(el("option", { value: h, textContent: h }));
  hood.onchange = () => { App.explore.hood = hood.value; render(); };

  const from = el("input", { type: "date" });
  const to = el("input", { type: "date" });
  from.onchange = () => { App.explore.from = from.value; render(); };
  to.onchange = () => { App.explore.to = to.value; render(); };

  const ratingFilter = el("div", { className: "rating-filter" });
  for (let i = 1; i <= 5; i++) {
    const b = el("button", { className: "star-btn", textContent: "★", title: `${i}+ stars` });
    b.dataset.v = i;
    b.onclick = () => { App.explore.minRating = App.explore.minRating === i ? 0 : i; paintStars(); render(); };
    ratingFilter.append(b);
  }
  ratingFilter.append(el("button", { className: "clear", textContent: "clear",
    onclick: () => { App.explore.minRating = 0; paintStars(); render(); } }));

  const controls = el("div", { className: "controls" },
    el("div", { className: "search-row" }, search),
    el("div", { className: "field", style: "margin-bottom:16px" },
      el("label", { textContent: "Type" }), pills),
    el("div", { className: "filters" },
      el("div", { className: "field" }, el("label", { textContent: "Location" }), hood),
      el("div", { className: "field" }, el("label", { textContent: "From date" }), from),
      el("div", { className: "field" }, el("label", { textContent: "To date" }), to),
      el("div", { className: "field" }, el("label", { textContent: "Recommended rating" }), ratingFilter)));

  // ── Toolbar ───────────────────────────────────────────────────────────
  const count = el("div", { className: "count" });
  const freeToggle = checkbox("Free only", false, (v) => { App.explore.free = v; render(); });
  const hidePast = checkbox("Hide past", true, (v) => { App.explore.hidePast = v; render(); });
  const sort = el("button", { className: "sort-toggle", textContent: "Sort: Date ↑" });
  sort.onclick = () => {
    App.explore.sortBy = App.explore.sortBy === "date" ? "rating" : "date";
    sort.textContent = App.explore.sortBy === "date" ? "Sort: Date ↑" : "Sort: Rating ↓";
    render();
  };
  const reset = el("button", { className: "reset", textContent: "Reset" });
  reset.onclick = resetFilters;

  const toolbar = el("div", { className: "toolbar" }, count,
    el("div", { className: "toolbar-right" }, freeToggle.label, hidePast.label, sort, reset));

  const grid = el("div", { className: "grid" });

  root.append(controls, toolbar, grid);
  refs = { q, pills, hood, from, to, ratingFilter, count, sort, grid,
           freeCb: freeToggle.input, hidePastCb: hidePast.input, sortBtn: sort };

  paintStars();
  syncControls();
  render();
}

function checkbox(text, checked, onchange) {
  const input = el("input", { type: "checkbox", checked });
  input.onchange = (e) => onchange(e.target.checked);
  const label = el("label", { className: "inline-check" }, input, document.createTextNode(" " + text));
  return { input, label };
}

function paintStars() {
  $$(".rating-filter .star-btn", refs.ratingFilter)
    .forEach((b) => b.classList.toggle("lit", Number(b.dataset.v) <= App.explore.minRating));
}

/* Push control widgets to match App.explore (used after a chat-driven set/reset). */
function syncControls() {
  const s = App.explore;
  refs.q.value = s.q;
  refs.hood.value = s.hood;
  refs.from.value = s.from;
  refs.to.value = s.to;
  refs.freeCb.checked = s.free;
  refs.hidePastCb.checked = s.hidePast;
  refs.sortBtn.textContent = s.sortBy === "date" ? "Sort: Date ↑" : "Sort: Rating ↓";
  $$(".pill", refs.pills).forEach((p) => p.classList.toggle("active", s.cats.has(p.dataset.cat)));
  paintStars();
}

function resetFilters() {
  App.explore = defaultExploreState();
  syncControls();
  render();
}

function haystack(ev) {
  const en = ev.enrichment || {};
  const org = Array.isArray(ev.organizers) ? ev.organizers.join(" ") : (ev.organizers || "");
  return [
    ev.title, ev.venue, ev.neighborhood, ev.detail, org,
    ...(ev.lineup || []), ...(ev.sources || []),
    en.type, en.curator_note, en.description,
    ...(en.subgenres || []), ...(en.label_orbit || []), ...(en.sounds_like || []),
    ...((en.artist_notes || []).flatMap((a) => [a.name, a.note])),
  ].filter(Boolean).join(" ").toLowerCase();
}

export function matches(ev) {
  const s = App.explore;
  if (s.hidePast && ev.is_past) return false;
  if (s.cats.size && !s.cats.has(ev.category)) return false;
  if (s.hood && ev.neighborhood !== s.hood) return false;
  if (s.minRating && (ev.rating || 0) < s.minRating) return false;
  if (s.free && !isFreeish(ev)) return false;
  if (s.from && ev.iso_date && ev.iso_date < s.from) return false;
  if (s.to && ev.iso_date && ev.iso_date > s.to) return false;
  if (s.q && !haystack(ev).includes(s.q)) return false;
  return true;
}

export function filteredEvents() {
  let list = App.feed.events.filter(matches);
  if (App.explore.sortBy === "rating") {
    list = [...list].sort((a, b) => (b.rating - a.rating) || (a.iso_date || "").localeCompare(b.iso_date || ""));
  }
  return list;
}

function render() {
  const grid = refs.grid;
  grid.innerHTML = "";
  const list = filteredEvents();
  refs.count.innerHTML = `<b>${list.length}</b> ${list.length === 1 ? "event" : "events"}`;
  if (!list.length) {
    grid.append(el("div", { className: "empty" },
      el("h2", { textContent: "Nothing matches those filters" }),
      el("p", { textContent: "Try widening the date range, clearing the rating, or hitting Reset." })));
    return;
  }
  for (const ev of list) grid.append(card(ev));
}

/* The event card — full detail. Reused by the chatbox result list. */
export function card(ev) {
  const c = el("div", { className: "card" + (ev.is_past ? " past" : "") });
  const en = ev.enrichment || {};

  // top: date chip + rating + save
  const top = el("div", { className: "card-top" });
  if (ev.iso_date) {
    const { dow, md } = fmtDateChip(ev.iso_date);
    const chip = el("div", { className: "date-chip" },
      el("div", { className: "dow", textContent: dow }),
      el("div", { className: "dnum", textContent: md }));
    const t = fmtTime(ev.start);
    if (t) chip.append(el("div", { className: "time", textContent: t }));
    top.append(chip);
  }
  const right = el("div", { className: "card-top-right" });
  const rating = el("div", { className: "rating" }, starsNode(ev.rating || 0));
  const reasonsBox = el("div", { className: "reasons" });
  if (ev.reasons?.length) {
    const why = el("button", { className: "why-btn", textContent: "why?" });
    why.onclick = () => reasonsBox.classList.toggle("open");
    rating.append(why);
  }
  right.append(rating, saveBtn(ev));
  top.append(right);
  c.append(top);

  // optional hero image (enrichment). Prefer the source URL: the cached copy lives under
  // data/images/, which GitHub Pages doesn't serve (only dashboard/ is published).
  if (en.image?.url || en.image?.cached) {
    const img = el("img", { className: "hero", loading: "lazy", alt: "",
      src: en.image.url || en.image.cached });
    img.onerror = () => img.remove();
    c.append(img);
  }

  // title (linked to first ticket) + venue
  const links = dedupeLinks(ev.links);
  const titleText = ev.title || "Untitled";
  c.append(links[0]
    ? el("h3", {}, el("a", { href: links[0].url, target: "_blank", rel: "noopener", textContent: titleText, className: "title-link" }))
    : el("h3", { textContent: titleText }));

  const venue = el("div", { className: "venue-line" }, document.createTextNode(ev.venue || "Venue TBA"));
  if (ev.neighborhood) venue.append(el("span", { className: "hood", textContent: ` · ${ev.neighborhood}` }));
  c.append(venue);

  // badges
  const badges = el("div", { className: "badges" });
  badges.append(el("span", { className: "badge cat", textContent: en.type || catLabel(ev.category) }));
  for (const sg of (en.subgenres || []).slice(0, 3)) badges.append(el("span", { className: "badge", textContent: sg }));
  if (ev.afterhours) badges.append(el("span", { className: "badge after", textContent: "afterhours" }));
  if (ev.ra_pick) badges.append(el("span", { className: "badge pick", textContent: "RA pick" }));
  if (isLovedVenue(ev)) badges.append(el("span", { className: "badge loved", textContent: "♥ venue" }));
  for (const a of trackedInLineup(ev).slice(0, 3)) badges.append(el("span", { className: "badge tracked", textContent: `★ ${a}` }));
  c.append(badges);

  if (ev.lineup?.length) c.append(el("div", { className: "lineup", textContent: ev.lineup.join(" · ") }));

  const note = en.curator_note || en.description || ev.detail;
  if (note) c.append(el("p", { className: en.curator_note ? "curator" : "desc", textContent: note }));

  const price = priceLabel(ev);
  if (price) c.append(el("div", { className: "price", textContent: price }));

  // reasons (collapsible)
  reasonsBox.append(el("strong", { textContent: `Recommended ${ev.rating}/5` }));
  const ul = el("ul");
  for (const r of ev.reasons || []) ul.append(el("li", { textContent: r }));
  reasonsBox.append(ul);
  c.append(reasonsBox);

  // actions
  const actions = el("div", { className: "tickets" });
  for (const l of links) actions.append(el("a", { className: "ticket-link", href: l.url, target: "_blank", rel: "noopener", textContent: linkLabel(l) }));
  const cal = el("button", { className: "cal-link", title: "Download .ics", textContent: "＋ Calendar" });
  cal.onclick = () => downloadICS(ev);
  actions.append(cal);
  c.append(actions);

  return c;
}

function saveBtn(ev) {
  const b = el("button", { className: "save-btn", title: "Save for a plan" });
  const paint = () => {
    const on = isSaved(ev);
    b.textContent = on ? "★ Saved" : "☆ Save";
    b.classList.toggle("on", on);
  };
  b.onclick = () => { toggleSaved(ev); paint(); };
  paint();
  return b;
}

// Chat drives the explorer: set filters, sync widgets, show the grid.
on("explore:set", (partial) => {
  App.explore = { ...defaultExploreState(), ...partial,
    cats: partial.cats instanceof Set ? partial.cats : new Set(partial.cats || []) };
  if (refs.grid) { syncControls(); render(); }
});

// Re-render save stars across cards when the saved set changes elsewhere.
on("saved:change", () => { if (refs.grid) render(); });
