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

  // actions: ticket links + add-to-calendar
  const links = ev.tickets && ev.tickets.length ? ev.tickets
    : (ev.url ? [{ source: "Tickets", url: ev.url }] : []);
  const actions = el("div", { className: "tickets" });
  for (const l of links) {
    actions.append(el("a", { className: "ticket-link", href: l.url, target: "_blank", rel: "noopener", textContent: l.source || "Tickets" }));
  }
  const cal = el("button", { className: "cal-link", title: "Download .ics", textContent: "＋ Calendar" });
  cal.onclick = () => downloadICS(ev);
  actions.append(cal);
  c.append(actions);

  return c;
}

/* ── Add-to-calendar (.ics) ─────────────────────────────── */
const pad = (n) => String(n).padStart(2, "0");

function icsEscape(s) {
  return String(s || "")
    .replace(/\\/g, "\\\\").replace(/;/g, "\\;")
    .replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");
}

function foldLine(line) {
  // RFC 5545: fold lines longer than 75 octets with CRLF + a leading space.
  if (line.length <= 75) return line;
  let out = line.slice(0, 75), rest = line.slice(75);
  while (rest.length > 74) { out += "\r\n " + rest.slice(0, 74); rest = rest.slice(74); }
  return out + "\r\n " + rest;
}

function localStamp(isoDate, time) {
  // floating local time: YYYYMMDDTHHMMSS (no Z) — calendar apps read it as local
  const [y, m, d] = isoDate.split("-").map(Number);
  let hh = 19, mm = 0;
  if (time && /^\d{1,2}:\d{2}/.test(time)) { const [h, mn] = time.split(":").map(Number); hh = h; mm = mn; }
  return `${y}${pad(m)}${pad(d)}T${pad(hh)}${pad(mm)}00`;
}

function addHoursLocal(isoDate, time, hours) {
  const [y, m, d] = isoDate.split("-").map(Number);
  let hh = 19, mm = 0;
  if (time && /^\d{1,2}:\d{2}/.test(time)) { const [h, mn] = time.split(":").map(Number); hh = h; mm = mn; }
  const dt = new Date(y, m - 1, d, hh + hours, mm);
  return `${dt.getFullYear()}${pad(dt.getMonth() + 1)}${pad(dt.getDate())}T${pad(dt.getHours())}${pad(dt.getMinutes())}00`;
}

function nextDay(isoDate) {
  const [y, m, d] = isoDate.split("-").map(Number);
  const dt = new Date(y, m - 1, d + 1);
  return `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}`;
}

function buildICS(ev) {
  const now = new Date();
  const stamp = `${now.getUTCFullYear()}${pad(now.getUTCMonth() + 1)}${pad(now.getUTCDate())}`
    + `T${pad(now.getUTCHours())}${pad(now.getUTCMinutes())}${pad(now.getUTCSeconds())}Z`;
  const uid = `${ev.id || Math.random().toString(36).slice(2)}@la-events`;
  const loc = [ev.venue, ev.neighborhood].filter(Boolean).join(", ");
  const url = (ev.tickets && ev.tickets[0] && ev.tickets[0].url) || ev.url || "";

  const desc = [];
  if (ev.genre) desc.push(ev.genre);
  if (ev.lineup && ev.lineup.length) desc.push("Lineup: " + ev.lineup.join(", "));
  if (ev.description) desc.push(ev.description);
  if (ev.rating) desc.push(`Recommended for you: ${ev.rating}/5`);
  if (url) desc.push(url);

  const lines = [
    "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//la-events//dashboard//EN",
    "CALSCALE:GREGORIAN", "BEGIN:VEVENT", `UID:${uid}`, `DTSTAMP:${stamp}`,
  ];

  if (ev.iso_date && ev.start_time) {
    lines.push(`DTSTART:${localStamp(ev.iso_date, ev.start_time)}`);
    let end;
    if (ev.end_time) {
      end = localStamp(ev.iso_date, ev.end_time);
      if (end <= localStamp(ev.iso_date, ev.start_time)) end = localStamp(nextDay(ev.iso_date), ev.end_time);
    } else {
      end = addHoursLocal(ev.iso_date, ev.start_time, 3);
    }
    lines.push(`DTEND:${end}`);
  } else if (ev.iso_date) {
    lines.push(`DTSTART;VALUE=DATE:${ev.iso_date.replace(/-/g, "")}`);
    lines.push(`DTEND;VALUE=DATE:${nextDay(ev.iso_date).replace(/-/g, "")}`);
  }

  lines.push(`SUMMARY:${icsEscape(ev.title || "Event")}`);
  if (loc) lines.push(`LOCATION:${icsEscape(loc)}`);
  if (desc.length) lines.push(`DESCRIPTION:${icsEscape(desc.join("\n"))}`);
  if (url) lines.push(`URL:${icsEscape(url)}`);
  lines.push("END:VEVENT", "END:VCALENDAR");
  return lines.map(foldLine).join("\r\n");
}

function downloadICS(ev) {
  const blob = new Blob([buildICS(ev)], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const name = (ev.title || "event").replace(/[^\w\- ]+/g, "").trim().slice(0, 60) || "event";
  const a = el("a", { href: url, download: `${name}.ics` });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
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
