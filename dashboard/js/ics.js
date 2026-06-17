/* Client-side .ics (RFC 5545) export for a single event. Times are written as
 * floating local time (no Z) so calendar apps read them as LA-local. Reads the real
 * feed schema: start (HH:MM:SS), links[{source,url}], lineup[], enrichment.description. */

import { el, dedupeLinks, fmtTime } from "./data.js";

const pad = (n) => String(n).padStart(2, "0");

function icsEscape(s) {
  return String(s || "").replace(/\\/g, "\\\\").replace(/;/g, "\\;")
    .replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");
}
function foldLine(line) {
  if (line.length <= 75) return line;
  let out = line.slice(0, 75), rest = line.slice(75);
  while (rest.length > 74) { out += "\r\n " + rest.slice(0, 74); rest = rest.slice(74); }
  return out + "\r\n " + rest;
}
function localStamp(isoDate, time) {
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

export function buildICS(ev) {
  const now = new Date();
  const stamp = `${now.getUTCFullYear()}${pad(now.getUTCMonth() + 1)}${pad(now.getUTCDate())}`
    + `T${pad(now.getUTCHours())}${pad(now.getUTCMinutes())}${pad(now.getUTCSeconds())}Z`;
  const uid = `${(ev.title || "event").replace(/\W+/g, "-").slice(0, 40)}-${(ev.iso_date || "")}@la-events`;
  const loc = [ev.venue, ev.neighborhood].filter(Boolean).join(", ");
  const links = dedupeLinks(ev.links);
  const url = links[0]?.url || "";
  const start = ev.start;

  const desc = [];
  if (ev.lineup?.length) desc.push("Lineup: " + ev.lineup.join(", "));
  const blurb = ev.enrichment?.curator_note || ev.enrichment?.description || ev.detail;
  if (blurb) desc.push(blurb);
  if (ev.price) desc.push(ev.price);
  if (ev.rating) desc.push(`Recommended for you: ${ev.rating}/5`);
  if (url) desc.push(url);

  const lines = [
    "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//la-events//dashboard//EN",
    "CALSCALE:GREGORIAN", "BEGIN:VEVENT", `UID:${uid}`, `DTSTAMP:${stamp}`,
  ];
  if (ev.iso_date && start) {
    lines.push(`DTSTART:${localStamp(ev.iso_date, start)}`);
    lines.push(`DTEND:${addHoursLocal(ev.iso_date, start, 3)}`);
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

export function downloadICS(ev) {
  const blob = new Blob([buildICS(ev)], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const name = (ev.title || "event").replace(/[^\w\- ]+/g, "").trim().slice(0, 60) || "event";
  const a = el("a", { href: url, download: `${name}.ics` });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export { fmtTime };
