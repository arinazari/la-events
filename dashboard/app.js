/* la-events dashboard — loads the generated data.json and renders a filterable
 * grid. Pure client-side; scoring/rating is precomputed by scripts/build_dashboard.py. */

const CAT_LABELS = {
  electronic: "Electronic",
  live_music: "Live Music",
  comedy: "Comedy",
  film: "Film",
  theater: "Theater",
  beer_food: "Beer & Food",
  art: "Art",
  pop: "Pop",
  general: "Other",
};

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const state = {
  feed: null,
  q: "",
  cats: new Set(),        // empty = all
  hood: "",               // "" = all
  from: "",               // ISO date
  to: "",                 // ISO date
  minRating: 0,           // 0 = any
  hidePast: true,
  sortBy: "date",         // "date" | "rating"
};

const $ = (sel) => document.querySelector(sel);
const el = (tag, props = {}, ...kids) => {
  const node = Object.assign(document.createElement(tag), props);
  for (const k of kids) node.append(k);
  return node;
};

async function init() {
  try {
    const res = await fetch("./data.json", { cache: "no-store" });
    if (!res.ok) throw new Error(res.status);
    state.feed = await res.json();
  } catch (e) {
    renderLoadError(e);
    return;
  }
  buildControls();
  render();
}

function fmtDate(iso) {
  // iso = YYYY-MM-DD ; render without leading zeros, "Day M/D" Ari-style.
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  return { dow: DOW[dt.getDay()], md: `${m}/${d}` };
}

function buildControls() {
  const f = state.feed;

  // Meta line
  $("#generated").textContent = `${f.count} events · updated ${f.generated_at.replace("T", " ")}`;
  if (f.is_sample) {
    $("#meta").append(el("span", { className: "sample-badge", textContent: "SAMPLE DATA" }));
  }

  // Category pills
  const pills = $("#cat-pills");
  for (const c of f.categories) {
    const p = el("button", {
      className: "pill",
      textContent: CAT_LABELS[c] || c,
      onclick: () => {
        state.cats.has(c) ? state.cats.delete(c) : state.cats.add(c);
        p.classList.toggle("active");
        render();
      },
    });
    pills.append(p);
  }

  // Neighborhood select
  const sel = $("#hood");
  for (const h of f.neighborhoods) sel.append(el("option", { value: h, textContent: h }));
  sel.onchange = () => { state.hood = sel.value; render(); };

  // Search
  $("#q").oninput = (e) => { state.q = e.target.value.toLowerCase().trim(); render(); };

  // Dates
  $("#from").onchange = (e) => { state.from = e.target.value; render(); };
  $("#to").onchange = (e) => { state.to = e.target.value; render(); };

  // Rating stars filter
  const rf = $("#rating-filter");
  for (let i = 1; i <= 5; i++) {
    rf.append(el("button", {
      className: "star-btn",
      textContent: "★",
      title: `${i}+ stars`,
      onclick: () => { state.minRating = (state.minRating === i ? 0 : i); paintRatingFilter(); render(); },
      dataset: { v: i },
    }));
  }
  rf.append(el("button", { className: "clear", textContent: "clear", onclick: () => { state.minRating = 0; paintRatingFilter(); render(); } }));

  // hide-past toggle
  $("#hide-past").onchange = (e) => { state.hidePast = e.target.checked; render(); };

  // sort + reset
  $("#sort").onclick = () => {
    state.sortBy = state.sortBy === "date" ? "rating" : "date";
    $("#sort").textContent = state.sortBy === "date" ? "Sort: Date ↑" : "Sort: Rating ↓";
    render();
  };
  $("#reset").onclick = resetFilters;

  paintRatingFilter();
}

function paintRatingFilter() {
  document.querySelectorAll("#rating-filter .star-btn").forEach((b) => {
    b.classList.toggle("lit", Number(b.dataset.v) <= state.minRating);
  });
}

function resetFilters() {
  state.q = ""; state.cats.clear(); state.hood = ""; state.from = "";
  state.to = ""; state.minRating = 0; state.hidePast = true; state.sortBy = "date";
  $("#q").value = ""; $("#hood").value = ""; $("#from").value = ""; $("#to").value = "";
  $("#hide-past").checked = true;
  $("#sort").textContent = "Sort: Date ↑";
  document.querySelectorAll("#cat-pills .pill").forEach((p) => p.classList.remove("active"));
  paintRatingFilter();
  render();
}

function matches(ev) {
  if (state.hidePast && ev.is_past) return false;
  if (state.cats.size && !state.cats.has(ev.category)) return false;
  if (state.hood && ev.neighborhood !== state.hood) return false;
  if (state.minRating && (ev.rating || 0) < state.minRating) return false;
  if (state.from && ev.iso_date && ev.iso_date < state.from) return false;
  if (state.to && ev.iso_date && ev.iso_date > state.to) return false;
  if (state.q) {
    const hay = [
      ev.title, ev.venue, ev.neighborhood, ev.genre, ev.description,
      ...(ev.lineup || []),
    ].join(" ").toLowerCase();
    if (!hay.includes(state.q)) return false;
  }
  return true;
}

function render() {
  const grid = $("#grid");
  grid.innerHTML = "";

  let list = state.feed.events.filter(matches);
  if (state.sortBy === "rating") {
    list = [...list].sort((a, b) => (b.rating - a.rating) || (a.iso_date || "").localeCompare(b.iso_date || ""));
  }

  $("#count").innerHTML = `<b>${list.length}</b> ${list.length === 1 ? "event" : "events"}`;

  if (!list.length) {
    grid.append(el("div", { className: "empty" },
      el("h2", { textContent: "Nothing matches those filters" }),
      el("p", { textContent: "Try widening the date range, clearing the rating, or hitting Reset." })));
    return;
  }

  for (const ev of list) grid.append(card(ev));
}

function stars(n) {
  const wrap = el("span", { className: "stars" });
  for (let i = 1; i <= 5; i++) {
    wrap.append(el("span", { textContent: "★", className: i <= n ? "" : "empty" }));
  }
  return wrap;
}

function card(ev) {
  const c = el("div", { className: "card" + (ev.is_past ? " past" : "") });

  // top: date chip + rating
  const top = el("div", { className: "card-top" });
  if (ev.iso_date) {
    const { dow, md } = fmtDate(ev.iso_date);
    const chip = el("div", { className: "date-chip" },
      el("div", { className: "dow", textContent: dow }),
      el("div", { className: "dnum", textContent: md }));
    if (ev.start_time) chip.append(el("div", { className: "time", textContent: ev.start_time }));
    top.append(chip);
  }

  const rating = el("div", { className: "rating" }, stars(ev.rating || 0));
  if (ev.reasons && ev.reasons.length) {
    const why = el("button", { className: "why-btn", textContent: "why?" });
    rating.append(why);
    why.onclick = () => reasonsBox.classList.toggle("open");
  }
  top.append(rating);
  c.append(top);

  // title + venue
  c.append(el("h3", { textContent: ev.title || "Untitled" }));
  const venue = el("div", { className: "venue-line" });
  venue.append(document.createTextNode(ev.venue || "Venue TBA"));
  if (ev.neighborhood) venue.append(el("span", { className: "hood", textContent: ` · ${ev.neighborhood}` }));
  c.append(venue);

  // badges
  const badges = el("div", { className: "badges" });
  badges.append(el("span", { className: "badge cat", textContent: CAT_LABELS[ev.category] || ev.category }));
  if (ev.genre) badges.append(el("span", { className: "badge", textContent: ev.genre }));
  if (ev.afterhours_flag) badges.append(el("span", { className: "badge after", textContent: "afterhours" }));
  if (ev.ra_pick) badges.append(el("span", { className: "badge pick", textContent: "RA pick" }));
  for (const m of ev.editorial_mentions || []) badges.append(el("span", { className: "badge", textContent: `${m} pick` }));
  if ((state.feed.taste.venues_loved || []).map((v) => v.toLowerCase()).includes((ev.venue || "").toLowerCase())) {
    badges.append(el("span", { className: "badge loved", textContent: "♥ venue" }));
  }
  c.append(badges);

  if (ev.description) c.append(el("p", { className: "desc", textContent: ev.description }));

  if (ev.price_min != null || ev.price_max != null) {
    c.append(el("div", { className: "price", textContent: priceLabel(ev) }));
  }

  // reasons (hidden until "why?")
  const reasonsBox = el("div", { className: "reasons" });
  reasonsBox.append(el("strong", { textContent: `Recommended ${ev.rating}/5` }));
  const ul = el("ul");
  for (const r of ev.reasons || []) ul.append(el("li", { textContent: r }));
  reasonsBox.append(ul);
  c.append(reasonsBox);

  // tickets
  const links = ev.tickets && ev.tickets.length ? ev.tickets
    : (ev.url ? [{ source: "Tickets", url: ev.url }] : []);
  if (links.length) {
    const t = el("div", { className: "tickets" });
    for (const l of links) {
      t.append(el("a", { className: "ticket-link", href: l.url, target: "_blank", rel: "noopener", textContent: l.source || "Tickets" }));
    }
    c.append(t);
  }

  return c;
}

function priceLabel(ev) {
  const lo = ev.price_min, hi = ev.price_max;
  if (lo === 0 && (hi === 0 || hi == null)) return "Free";
  if (lo != null && hi != null && lo !== hi) return `$${lo}–$${hi}`;
  if (lo != null) return `$${lo}`;
  return `$${hi}`;
}

function renderLoadError(e) {
  $("#grid").append(el("div", { className: "empty" },
    el("h2", { textContent: "Couldn't load event data" }),
    el("p", {}, "Generate the feed first: ", el("code", { textContent: "python scripts/build_dashboard.py -i data/sample-catalog.json" })),
    el("p", { className: "desc", textContent: `(${e.message})` })));
}

init();
