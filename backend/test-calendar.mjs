/**
 * Node tests for the calendar-subscription core (dashboard/calendar-core.js) — the shared
 * filter + iCalendar builder behind GET /calendar.ics and the dashboard's calendar modal.
 * Run: `cd backend && node test-calendar.mjs` (no deps, no network — pure functions only).
 */
import assert from "node:assert";
import Cal from "../dashboard/calendar-core.js";

let passed = 0;
const ok = (name) => { console.log("ok  " + name); passed++; };

const row = (over) => Object.assign({
  title: "Test Show", iso_date: "2026-07-24", start: "20:00", venue: "The Echo",
  neighborhood: "Echo Park", rating: 4, score: 8, key: "abc123def456",
  tags: { type: "live-music", genre: ["rock"] }, lineup: [], links: [{ source: "x", url: "https://t.example/1" }],
}, over || {});
const feed = (events, extra) => Object.assign({ generated_at: "2026-07-20T12:30:50+00:00", events }, extra || {});
const TODAY = "2026-07-20";

/* ---- settings: normalize / params round-trip ---- */
{
  const s = Cal.normSettings({});
  assert.deepEqual(s, { min: 4, perday: 3, horizon: 60, days: [], types: [], xtypes: [], genres: [], xgenres: [], saved: false, savedHash: "", keys: [] });
  ok("settings: empty input yields the documented defaults");
}
{
  const s = Cal.normSettings({ min: "99", perday: -2, horizon: "3", days: "FRI, sat,nope", genres: "Deep House, techno" });
  assert.equal(s.min, 5); assert.equal(s.perday, 1); assert.equal(s.horizon, 7);
  assert.deepEqual(s.days, ["fri", "sat"]);                       // vocab-filtered, canonicalized
  assert.deepEqual(s.genres, ["deep-house", "techno"]);           // whitespace -> hyphen like the page
  ok("settings: clamps, canonicalizes, drops off-vocab weekdays");
}
{
  const qs = Cal.paramsFromSettings({ min: 3, days: ["sat", "fri"], xgenres: ["country"] });
  assert.equal(qs, "min=3&days=sat,fri&xgenres=country");         // defaults omitted, fixed key order
  assert.equal(Cal.paramsFromSettings({}), "");                   // all-default -> bare URL
  const back = Cal.settingsFromParams(new URLSearchParams(qs));
  assert.equal(back.min, 3); assert.equal(back.perday, 3);
  assert.deepEqual(back.days, ["sat", "fri"]); assert.deepEqual(back.xgenres, ["country"]);
  ok("settings: params round-trip through URLSearchParams");
}

/* ---- start-time parsing (the feed's real variety) ---- */
{
  assert.deepEqual(Cal.parseStartTime("19:30"), { sh: 19, sm: 30, eh: null, em: null });
  assert.deepEqual(Cal.parseStartTime("8pm"), { sh: 20, sm: 0, eh: null, em: null });
  assert.deepEqual(Cal.parseStartTime("8:00 PM"), { sh: 20, sm: 0, eh: null, em: null });
  assert.deepEqual(Cal.parseStartTime("12am"), { sh: 0, sm: 0, eh: null, em: null });
  assert.deepEqual(Cal.parseStartTime("10pm-2am"), { sh: 22, sm: 0, eh: 2, em: 0 });
  assert.equal(Cal.parseStartTime("8"), null);                    // bare digit: ambiguous, refuse
  assert.equal(Cal.parseStartTime("TBA"), null);
  assert.equal(Cal.parseStartTime(null), null);
  ok("time: 24h / 12h / ranges parse; garbage goes all-day");
}

/* ---- selection: window, threshold, weekday, include/exclude, per-day cap ---- */
{
  const f = feed([
    row({ title: "past", iso_date: "2026-07-19" }),
    row({ title: "in", iso_date: "2026-07-24" }),
    row({ title: "beyond", iso_date: "2026-11-30" }),
  ]);
  assert.deepEqual(Cal.selectEvents(f, {}, TODAY).map(e => e.title), ["in"]);
  ok("select: date window recomputed against today (is_past ignored)");
}
{
  const f = feed([row({ title: "meh", rating: 2 }), row({ title: "top", rating: 5 })]);
  assert.deepEqual(Cal.selectEvents(f, { min: 4 }, TODAY).map(e => e.title), ["top"]);
  assert.equal(Cal.selectEvents(f, { min: 1 }, TODAY).length, 2);
  ok("select: rating threshold");
}
{
  // 2026-07-24 is a Friday, 2026-07-26 a Sunday
  const f = feed([row({ iso_date: "2026-07-24", title: "fri" }), row({ iso_date: "2026-07-26", title: "sun" })]);
  assert.deepEqual(Cal.selectEvents(f, { days: ["fri"] }, TODAY).map(e => e.title), ["fri"]);
  assert.equal(Cal.weekdayOf("2026-07-24"), "fri");
  ok("select: weekday filter");
}
{
  const f = feed([
    row({ title: "rock", tags: { type: "live-music", genre: ["rock"] } }),
    row({ title: "club", tags: { type: "club", genre: ["techno"] } }),
    row({ title: "deep", tags: { type: "club", genre: ["house"] }, enrichment: { subgenres: ["Deep House"] } }),
  ]);
  assert.deepEqual(Cal.selectEvents(f, { types: ["club"] }, TODAY).map(e => e.title), ["club", "deep"]);
  assert.deepEqual(Cal.selectEvents(f, { xtypes: ["club"] }, TODAY).map(e => e.title), ["rock"]);
  assert.deepEqual(Cal.selectEvents(f, { genres: ["deep-house"] }, TODAY).map(e => e.title), ["deep"]);
  assert.deepEqual(Cal.selectEvents(f, { xgenres: ["techno"] }, TODAY).map(e => e.title), ["deep", "rock"]);  // (date, start, title) order
  // exclusion beats inclusion when both would match
  assert.deepEqual(Cal.selectEvents(f, { genres: ["techno", "house"], xgenres: ["techno"] }, TODAY).map(e => e.title), ["deep"]);
  ok("select: type/genre include + exclude (enrichment subgenres folded in; exclusion wins)");
}
{
  const f = feed([
    row({ title: "a", rating: 5, key: "k1" }), row({ title: "b", rating: 4, key: "k2" }),
    row({ title: "c", rating: 4, key: "k3" }), row({ title: "d", rating: 5, key: "k4", iso_date: "2026-07-25" }),
  ]);
  const got = Cal.selectEvents(f, { perday: 2 }, TODAY);
  assert.deepEqual(got.map(e => e.title), ["a", "b", "d"]);       // best 2 of 7/24 by rating, then 7/25
  ok("select: per-day cap keeps the highest-rated, output stays date-ordered");
}

/* ---- ICS document ---- */
{
  const ics = Cal.buildIcs(feed([row()]), {}, { todayISO: TODAY });
  assert.ok(ics.startsWith("BEGIN:VCALENDAR\r\n"));
  assert.ok(ics.endsWith("END:VCALENDAR\r\n"));
  assert.ok(ics.includes("X-WR-CALNAME:LA Events — top picks"));
  assert.ok(ics.includes("BEGIN:VTIMEZONE"));
  assert.ok(ics.includes("TZID:America/Los_Angeles"));
  assert.ok(ics.includes("REFRESH-INTERVAL;VALUE=DURATION:PT12H"));
  assert.ok(ics.includes("UID:abc123def456@la-events"));
  assert.ok(ics.includes("DTSTART;TZID=America/Los_Angeles:20260724T200000"));
  assert.ok(ics.includes("DTEND;TZID=America/Los_Angeles:20260724T230000"));   // 3h default block
  assert.ok(ics.includes("DTSTAMP:20260720T123050Z"));            // derived from generated_at -> stable between builds
  assert.ok(ics.includes("LOCATION:The Echo\\, Echo Park"));
  assert.ok(ics.includes("URL:https://t.example/1"));
  ok("ics: document structure, TZID times, stable UID/DTSTAMP");
}
{
  const ics = Cal.buildIcs(feed([row({ start: "10pm-2am" })]), {}, { todayISO: TODAY });
  assert.ok(ics.includes("DTSTART;TZID=America/Los_Angeles:20260724T220000"));
  assert.ok(ics.includes("DTEND;TZID=America/Los_Angeles:20260725T020000"));   // crosses midnight
  ok("ics: club range ends next day");
}
{
  const ics = Cal.buildIcs(feed([row({ start: null })]), {}, { todayISO: TODAY });
  assert.ok(ics.includes("DTSTART;VALUE=DATE:20260724"));
  assert.ok(ics.includes("DTEND;VALUE=DATE:20260725"));
  ok("ics: timeless event goes all-day");
}
{
  const late = Cal.buildIcs(feed([row({ start: "23:00" })]), {}, { todayISO: TODAY });
  assert.ok(late.includes("DTEND;TZID=America/Los_Angeles:20260725T020000")); // 11pm + 3h rolls over
  ok("ics: default 3h block rolls past midnight");
}
{
  const ics = Cal.buildIcs(feed([row({ title: "A; B, C\nD" })]), {}, { todayISO: TODAY });
  assert.ok(ics.includes("SUMMARY:A\\; B\\, C\\nD"));
  ok("ics: TEXT escaping");
}
{
  const long = "Ünïcode véry long títle ".repeat(8);
  const ics = Cal.buildIcs(feed([row({ title: long })]), {}, { todayISO: TODAY });
  const enc = new TextEncoder();
  for (const line of ics.split("\r\n")) assert.ok(enc.encode(line).length <= 75, "folded line fits 75 octets");
  ok("ics: 75-octet folding survives multi-byte titles");
}
{
  const f = feed([row()], { profile: { name: "Lori", hash: "feedbeeffeedbeef" } });
  assert.ok(Cal.buildIcs(f, {}, { todayISO: TODAY }).includes("X-WR-CALNAME:LA Events — Lori"));
  ok("ics: profile feed names the calendar after its person");
}
{
  const a = Cal.buildIcs(feed([row()]), {}, { todayISO: TODAY });
  const b = Cal.buildIcs(feed([row()]), {}, { todayISO: TODAY });
  assert.equal(a, b);
  ok("ics: same feed + settings -> byte-identical document");
}

/* ---- saved-events mode (keys=) ---- */
{
  const s = Cal.normSettings({ keys: "ABC123def456, zz, 0011223344, ABC123def456" });
  assert.deepEqual(s.keys, ["abc123def456", "0011223344"]);   // lowercased, hex-only, deduped, 'zz' dropped
  ok("saved: keyList sanitizes to hex, lowercases, dedupes");
}
{
  const qs = Cal.paramsFromSettings({ keys: ["a1aaaa", "b2bbbb"], min: 3, days: ["fri"] });
  assert.equal(qs, "keys=a1aaaa,b2bbbb");                      // saved mode: picks knobs suppressed
  assert.deepEqual(Cal.settingsFromParams(new URLSearchParams(qs)).keys, ["a1aaaa", "b2bbbb"]);
  ok("saved: params emit keys only, round-trip");
}
{
  const f = feed([
    row({ title: "kept", key: "aaaaaaaaaaaa" }),
    row({ title: "unstarred", key: "bbbbbbbbbbbb" }),
    row({ title: "starred-but-past", key: "cccccccccccc", iso_date: "2026-07-19" }),
    row({ title: "low-rated-but-starred", key: "dddddddddddd", rating: 1, iso_date: "2026-07-25" }),
  ]);
  const got = Cal.selectEvents(f, { keys: ["aaaaaaaaaaaa", "cccccccccccc", "dddddddddddd"] }, TODAY);
  assert.deepEqual(got.map(e => e.title), ["kept", "low-rated-but-starred"]);  // past drops; rating ignored
  ok("saved: selects exactly the starred upcoming events, ignoring rating");
}
{
  const f = feed([row({ key: "aaaaaaaaaaaa" })], { profile: { name: "Lori", hash: "feedbeeffeedbeef" } });
  const ics = Cal.buildIcs(f, { keys: ["aaaaaaaaaaaa"] }, { todayISO: TODAY });
  assert.ok(ics.includes("X-WR-CALNAME:LA Events — Lori’s starred"));
  assert.ok(ics.includes("UID:aaaaaaaaaaaa@la-events"));
  ok("saved: calendar named after the person + built from the starred set");
}

/* ---- server-stars mode (saved=1 / savedHash) ---- */
{
  const s = Cal.settingsFromParams(new URLSearchParams("saved=1"));
  assert.equal(s.saved, true);
  assert.equal(Cal.paramsFromSettings({ saved: true }), "saved=1");
  assert.equal(Cal.paramsFromSettings({ savedHash: "feedbeeffeedbeef" }), "saved=1");   // hash rides p=, not repeated
  ok("stars: saved=1 param round-trips, savedHash mints a stable saved url");
}
{
  const mine = "feedbeeffeedbeef", other = "0011223344556677";
  const f = feed([
    row({ title: "i-starred", key: "aaaaaaaaaaaa", stars: [{ name: "Me", hash: mine }] }),
    row({ title: "friend-only", key: "bbbbbbbbbbbb", stars: [{ name: "Lori", hash: other }] }),
    row({ title: "both", key: "cccccccccccc", stars: [{ name: "Lori", hash: other }, { name: "Me", hash: mine }] }),
    row({ title: "none", key: "dddddddddddd" }),
    row({ title: "mine-but-past", key: "eeeeeeeeeeee", iso_date: "2026-07-19", stars: [{ name: "Me", hash: mine }] }),
  ]);
  const got = Cal.selectEvents(f, { savedHash: mine }, TODAY);
  assert.deepEqual(got.map(e => e.title), ["both", "i-starred"]);   // only my stars, upcoming, date-ordered
  ok("stars: selectEvents(savedHash) picks exactly my upcoming starred events");
}
{
  const mine = "feedbeeffeedbeef";
  const f = feed([row({ key: "aaaaaaaaaaaa", stars: [{ name: "Ari", hash: mine }] })],
    { profile: { name: "Ari", hash: mine } });
  const ics = Cal.buildIcs(f, { savedHash: mine }, { todayISO: TODAY });
  assert.ok(ics.includes("X-WR-CALNAME:LA Events — Ari’s starred"));
  assert.ok(ics.includes("UID:aaaaaaaaaaaa@la-events"));
  ok("stars: savedHash builds the starred calendar, named for the person");
}
{
  const many = Array.from({ length: 400 }, (_, i) => "f" + String(i).padStart(11, "0"));  // hex keys
  assert.equal(Cal.keyList(many).length, 300);                // MAX_KEYS bound
  ok("saved: keyList caps at MAX_KEYS");
}

console.log(`\nall ${passed} calendar tests passed`);
