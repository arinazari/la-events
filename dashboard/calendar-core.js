/* calendar-core.js — the ONE filter + iCalendar builder behind the calendar-subscription
 * feature. Loaded two ways so the page's live preview, its snapshot download, and the
 * Worker's subscribed feed can never disagree:
 *   - browser: plain <script> → window.CalendarCore (dashboard/index.html modal)
 *   - CJS: require/import by backend/concierge-worker.js (GET /calendar.ics) and
 *     backend/test-calendar.mjs. No package.json governs dashboard/, so Node and
 *     wrangler's esbuild both treat this .js as CommonJS — keep it exports-free.
 *
 * Input is ALWAYS raw feed rows (data[.<hash>].json `events`) — never the page's
 * parseEvent() view rows — so both consumers filter the identical shape.
 *
 * Times: explicit TZID=America/Los_Angeles + a VTIMEZONE block. This deliberately
 * diverges from the repo's floating-local convention (lib/ics.py, the per-event export):
 * those are download-and-import-in-LA one-shots, while a SUBSCRIBED feed is re-read by
 * arbitrary clients/servers (Google fetches server-side) where floating times are
 * interpreted per-client — explicit TZ is the only way every subscriber sees 8pm as 8pm LA.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.CalendarCore = factory();
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  // Defaults tuned for "top events": in a real feed rating>=4 is ~1 event every other day.
  // Loosening to 3 is one chip tap; the per-day cap keeps even that calendar readable.
  var DEFAULTS = { min: 4, perday: 3, horizon: 60 };
  var LIMITS = { min: [1, 5], perday: [1, 10], horizon: [7, 120] };
  var WEEKDAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
  var MAX_EVENTS = 500;      // hard feed cap — keeps the worst-case .ics bounded
  var MAX_KEYS = 300;        // saved-mode cap — bounds the URL length (~13 chars/key → ~4KB)
  var TZID = "America/Los_Angeles";

  // Same canonical form as the page's parseEvent(): lowercase, whitespace/underscore → hyphen,
  // so a chip toggled in the modal matches the identically-labeled variants in the data.
  function canonTag(x) { return String(x == null ? "" : x).trim().toLowerCase().replace(/[\s_]+/g, "-"); }

  function uniqTags(arr) {
    var seen = {}, out = [];
    for (var i = 0; i < arr.length; i++) {
      var k = canonTag(arr[i]);
      if (k && !seen[k]) { seen[k] = 1; out.push(k); }
    }
    return out;
  }

  // Genre axis = deterministic tags UNION the scene-researcher's subgenres (the same fold
  // parseEvent does), so filters see what the card shows.
  function eventGenres(row) {
    var tags = (row && row.tags) || {};
    var enr = (row && row.enrichment) || {};
    var g = Array.isArray(tags.genre) ? tags.genre : [];
    var s = Array.isArray(enr.subgenres) ? enr.subgenres : [];
    return uniqTags(s.concat(g));
  }

  function eventType(row) {
    var tags = (row && row.tags) || {};
    return canonTag(tags.type || "");
  }

  function clampInt(v, lo, hi, dflt) {
    var n = parseInt(v, 10);
    if (isNaN(n)) return dflt;
    return Math.max(lo, Math.min(hi, n));
  }

  function tokenList(v, vocab) {
    var arr = Array.isArray(v) ? v : String(v == null ? "" : v).split(",");
    var out = uniqTags(arr);
    if (vocab) out = out.filter(function (t) { return vocab.indexOf(t) !== -1; });
    return out;
  }

  // Saved-event keys are the server event_key (sha1(title|date|venue)[:12], hex). Sanitize hard —
  // these come straight off a URL — and cap so the subscription URL stays a sane length.
  function keyList(v) {
    var arr = Array.isArray(v) ? v : String(v == null ? "" : v).split(",");
    var seen = {}, out = [];
    for (var i = 0; i < arr.length && out.length < MAX_KEYS; i++) {
      var k = String(arr[i] == null ? "" : arr[i]).trim().toLowerCase();
      if (/^[0-9a-f]{6,40}$/.test(k) && !seen[k]) { seen[k] = 1; out.push(k); }
    }
    return out;
  }

  // Normalize any partial/untrusted settings object (modal state, URL params) into the
  // full clamped shape every other function takes.
  function normSettings(raw) {
    raw = raw || {};
    return {
      min: clampInt(raw.min, LIMITS.min[0], LIMITS.min[1], DEFAULTS.min),
      perday: clampInt(raw.perday, LIMITS.perday[0], LIMITS.perday[1], DEFAULTS.perday),
      horizon: clampInt(raw.horizon, LIMITS.horizon[0], LIMITS.horizon[1], DEFAULTS.horizon),
      days: tokenList(raw.days, WEEKDAYS),
      types: tokenList(raw.types),
      xtypes: tokenList(raw.xtypes),
      genres: tokenList(raw.genres),
      xgenres: tokenList(raw.xgenres),
      // Saved-events mode. Two ways to say "the events I starred", both bypassing the picks knobs:
      //  - saved + savedHash: server-side stars — the calendar is every event whose `stars` list
      //    contains this profile's hash. A STABLE url (?saved=1), so new stars appear on the next
      //    poll with no re-subscribe. This is the current path.
      //  - keys: an explicit event-key list baked into the url. Legacy (the pre-server localStorage
      //    saves) + what the client snapshot uses; still honored so old subscriptions keep working.
      saved: !!raw.saved && raw.saved !== "0" && raw.saved !== "false",
      savedHash: /^[0-9a-f]{8,32}$/.test(String(raw.savedHash || "")) ? String(raw.savedHash) : "",
      keys: keyList(raw.keys),
    };
  }

  // URLSearchParams OR a plain object → settings. The worker hands the former, tests the latter.
  function settingsFromParams(params) {
    var get = typeof params.get === "function"
      ? function (k) { return params.get(k); }
      : function (k) { return params[k]; };
    return normSettings({
      min: get("min"), perday: get("perday"), horizon: get("horizon"),
      days: get("days"), types: get("types"), xtypes: get("xtypes"),
      genres: get("genres"), xgenres: get("xgenres"), keys: get("keys"),
      saved: get("saved"),   // savedHash is injected by the Worker from `p`, never off the URL itself
    });
  }

  // settings → canonical query string (fixed key order, defaults omitted) so the same choices
  // always mint the same URL — calendar apps treat a changed URL as a brand-new calendar.
  function paramsFromSettings(settings) {
    var s = normSettings(settings);
    // Saved mode. Server stars -> a stable ?saved=1 (the profile is already `p=` in the url, so the
    // hash isn't repeated here). Legacy key list -> keys=. Either way the picks knobs don't apply.
    if (s.saved || s.savedHash) return "saved=1";
    if (s.keys.length) return "keys=" + s.keys.join(",");
    var parts = [];
    if (s.min !== DEFAULTS.min) parts.push("min=" + s.min);
    if (s.perday !== DEFAULTS.perday) parts.push("perday=" + s.perday);
    if (s.horizon !== DEFAULTS.horizon) parts.push("horizon=" + s.horizon);
    if (s.days.length) parts.push("days=" + s.days.join(","));
    if (s.types.length) parts.push("types=" + s.types.join(","));
    if (s.xtypes.length) parts.push("xtypes=" + s.xtypes.join(","));
    if (s.genres.length) parts.push("genres=" + s.genres.join(","));
    if (s.xgenres.length) parts.push("xgenres=" + s.xgenres.join(","));
    return parts.join("&");
  }

  // ---------- dates ----------

  function isISODate(s) { return /^\d{4}-\d{2}-\d{2}$/.test(String(s || "")); }

  // Day-of-week of a calendar date is TZ-independent when computed from the literal Y/M/D.
  function weekdayOf(iso) {
    var p = String(iso).split("-");
    var d = new Date(Date.UTC(+p[0], +p[1] - 1, +p[2]));
    return WEEKDAYS[d.getUTCDay()];
  }

  function addDaysISO(iso, n) {
    var p = String(iso).split("-");
    var d = new Date(Date.UTC(+p[0], +p[1] - 1, +p[2] + n));
    var pad = function (x) { return String(x).padStart(2, "0"); };
    return d.getUTCFullYear() + "-" + pad(d.getUTCMonth() + 1) + "-" + pad(d.getUTCDate());
  }

  // Lenient start-time parser over the feed's real variety: "19:30" (the 95% case, 24h),
  // "8pm", "8:00 PM", "10pm-2am" / "11pm-6am" (club ranges — start AND end, end may cross
  // midnight). Anything else (null, "TBA", bare digits) → null → the event goes all-day
  // rather than getting a fabricated hour.
  function parseStartTime(sRaw) {
    var s = String(sRaw == null ? "" : sRaw).trim().toLowerCase();
    if (!s) return null;
    var one = function (part) {
      var m = /^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$/.exec(part.trim());
      if (!m) return null;
      var h = +m[1], min = m[2] == null ? 0 : +m[2], ap = m[3];
      if (ap) {                                  // 12h: needs am/pm
        if (h < 1 || h > 12) return null;
        if (ap === "pm" && h !== 12) h += 12;
        if (ap === "am" && h === 12) h = 0;
      } else {
        if (m[2] == null) return null;           // bare "8" is ambiguous — refuse, go all-day
        if (h > 23) return null;                 // 24h needs a plausible hour
      }
      if (min > 59) return null;
      return { h: h, m: min };
    };
    var range = s.split(/\s*[-–—]\s*/);
    var start = one(range[0]);
    if (!start) return null;
    var end = range.length > 1 ? one(range[1]) : null;
    return { sh: start.h, sm: start.m, eh: end ? end.h : null, em: end ? end.m : null };
  }

  // ---------- selection ----------

  // The subscription slate: date-window → rating threshold → weekday → type/genre
  // include/exclude (exclusion wins) → best-N per day. Returns raw rows, (date, time, title)
  // ordered, so the page preview and the served feed literally share this list.
  function selectEvents(feed, settings, todayISO) {
    var s = normSettings(settings);
    var rows = (feed && Array.isArray(feed.events)) ? feed.events : [];
    if (s.savedHash) return selectStarred(rows, s.savedHash, todayISO);
    if (s.keys.length) return selectSaved(rows, s, todayISO);
    var lastISO = addDaysISO(todayISO, s.horizon);
    var picked = [];
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      if (!r || !r.title || !isISODate(r.iso_date)) continue;
      if (r.iso_date < todayISO || r.iso_date > lastISO) continue;    // recompute vs today — is_past is build-time
      var rating = typeof r.rating === "number" ? r.rating : 0;
      if (rating < s.min) continue;
      if (s.days.length && s.days.indexOf(weekdayOf(r.iso_date)) === -1) continue;
      var t = eventType(r);
      if (s.xtypes.length && s.xtypes.indexOf(t) !== -1) continue;
      if (s.types.length && s.types.indexOf(t) === -1) continue;
      var g = eventGenres(r);
      var hit = function (list) {
        for (var j = 0; j < g.length; j++) if (list.indexOf(g[j]) !== -1) return true;
        return false;
      };
      if (s.xgenres.length && hit(s.xgenres)) continue;
      if (s.genres.length && !hit(s.genres)) continue;
      picked.push(r);
    }
    // Per-day cap keeps the BEST of each day: rank by rating, then raw score, then title
    // (a stable tiebreak so the same feed always yields the same calendar).
    picked.sort(function (a, b) {
      return (b.rating || 0) - (a.rating || 0) || (b.score || 0) - (a.score || 0) ||
        String(a.title).localeCompare(String(b.title));
    });
    var perDay = {}, kept = [];
    for (var k = 0; k < picked.length && kept.length < MAX_EVENTS; k++) {
      var day = picked[k].iso_date;
      perDay[day] = (perDay[day] || 0) + 1;
      if (perDay[day] <= s.perday) kept.push(picked[k]);
    }
    kept.sort(function (a, b) {
      return String(a.iso_date).localeCompare(String(b.iso_date)) ||
        String(a.start || "").localeCompare(String(b.start || "")) ||
        String(a.title).localeCompare(String(b.title));
    });
    return kept;
  }

  // Server-stars selection: every upcoming event whose feed `stars` list contains this profile's
  // hash. This is the live saved calendar — no key list to bake into the url, so newly-starred
  // events just appear on the next poll (after the feed rebuilds the `stars` fold).
  function selectStarred(rows, hash, todayISO) {
    var kept = [];
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      if (!r || !r.title || !isISODate(r.iso_date) || r.iso_date < todayISO) continue;
      var stars = Array.isArray(r.stars) ? r.stars : [];
      for (var j = 0; j < stars.length; j++) {
        if (stars[j] && stars[j].hash === hash) { kept.push(r); break; }
      }
    }
    kept.sort(function (a, b) {
      return String(a.iso_date).localeCompare(String(b.iso_date)) ||
        String(a.start || "").localeCompare(String(b.start || "")) ||
        String(a.title).localeCompare(String(b.title));
    });
    return kept.slice(0, MAX_EVENTS);
  }

  // Saved-events selection: EXACTLY the starred events (by server event_key), still upcoming so
  // yesterday's starred show drops off on its own. No rating/weekday/type/genre/per-day filtering
  // — the user hand-picked these. Date-ordered, capped like the picks feed.
  function selectSaved(rows, s, todayISO) {
    var want = {};
    for (var i = 0; i < s.keys.length; i++) want[s.keys[i]] = 1;
    var kept = [];
    for (var j = 0; j < rows.length; j++) {
      var r = rows[j];
      if (!r || !r.title || !isISODate(r.iso_date)) continue;
      if (r.iso_date < todayISO) continue;
      if (r.key && want[r.key]) kept.push(r);
    }
    kept.sort(function (a, b) {
      return String(a.iso_date).localeCompare(String(b.iso_date)) ||
        String(a.start || "").localeCompare(String(b.start || "")) ||
        String(a.title).localeCompare(String(b.title));
    });
    return kept.slice(0, MAX_EVENTS);
  }

  // ---------- iCalendar ----------

  // RFC 5545 TEXT escaping + 75-OCTET line folding, ported byte-for-byte from the tested
  // lib/ics.py (the page's older per-event export folds by chars — chars overflow the octet
  // limit on non-ASCII titles, which a one-shot import forgives but a polled feed shouldn't).
  function icsEscape(s) {
    s = String(s == null ? "" : s);
    s = s.replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,");
    return s.replace(/\r\n/g, "\\n").replace(/\n/g, "\\n").replace(/\r/g, "\\n");
  }

  function icsFold(line) {
    var enc = new TextEncoder();
    if (enc.encode(line).length <= 75) return line;
    var out = [], cur = "", curLen = 0, first = true;
    var chars = Array.from(line);                 // fold on code points, never mid-UTF-8
    for (var i = 0; i < chars.length; i++) {
      var b = enc.encode(chars[i]).length;
      var cap = first ? 75 : 74;                  // continuations burn one octet on the lead space
      if (curLen + b > cap) { out.push(cur); cur = chars[i]; curLen = b; first = false; }
      else { cur += chars[i]; curLen += b; }
    }
    out.push(cur);
    return out.join("\r\n ");
  }

  function pad2(n) { return String(n).padStart(2, "0"); }

  function icsLocal(iso, h, m) { return String(iso).replace(/-/g, "") + "T" + pad2(h) + pad2(m) + "00"; }

  // UTC DTSTAMP derived from the feed's own generated_at: the file only changes when the feed
  // does, so pollers see a stable document between builds.
  function utcStamp(isoTs) {
    var d = new Date(isoTs || 0);
    if (isNaN(d.getTime())) d = new Date(0);
    return d.getUTCFullYear() + pad2(d.getUTCMonth() + 1) + pad2(d.getUTCDate()) + "T" +
      pad2(d.getUTCHours()) + pad2(d.getUTCMinutes()) + pad2(d.getUTCSeconds()) + "Z";
  }

  // Stable UID: the server event_key (sha1(title|date|venue)[:12], stamped on every row by
  // build_dashboard.py) — updates in place across polls instead of duplicating. The hash
  // fallback mirrors that key's inputs for the rare keyless row.
  function eventUid(row) {
    if (row.key) return row.key + "@la-events";
    var base = (String(row.title || "") + "|" + String(row.iso_date || "") + "|" + String(row.venue || "")).toLowerCase();
    var h = 0;
    for (var i = 0; i < base.length; i++) h = (h * 31 + base.charCodeAt(i)) | 0;
    return "x" + (h >>> 0).toString(36) + "@la-events";
  }

  var VTIMEZONE = [
    "BEGIN:VTIMEZONE", "TZID:" + TZID,
    "BEGIN:DAYLIGHT", "TZOFFSETFROM:-0800", "TZOFFSETTO:-0700", "TZNAME:PDT",
    "DTSTART:19700308T020000", "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU", "END:DAYLIGHT",
    "BEGIN:STANDARD", "TZOFFSETFROM:-0700", "TZOFFSETTO:-0800", "TZNAME:PST",
    "DTSTART:19701101T020000", "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU", "END:STANDARD",
    "END:VTIMEZONE",
  ];

  function eventLines(row, stamp) {
    var lines = ["BEGIN:VEVENT", "UID:" + eventUid(row), "DTSTAMP:" + stamp];
    var tm = parseStartTime(row.start);
    if (tm) {
      lines.push("DTSTART;TZID=" + TZID + ":" + icsLocal(row.iso_date, tm.sh, tm.sm));
      var endIso = row.iso_date, eh = tm.eh, em = tm.em;
      if (eh == null) { eh = tm.sh + 3; em = tm.sm; }        // no end in the data → the export convention's 3-hour block
      if (eh >= 24) { eh -= 24; endIso = addDaysISO(row.iso_date, 1); }
      else if (eh < tm.sh || (eh === tm.sh && em <= tm.sm)) endIso = addDaysISO(row.iso_date, 1);   // "10pm-2am"
      lines.push("DTEND;TZID=" + TZID + ":" + icsLocal(endIso, eh, em));
    } else {
      lines.push("DTSTART;VALUE=DATE:" + String(row.iso_date).replace(/-/g, ""));
      lines.push("DTEND;VALUE=DATE:" + addDaysISO(row.iso_date, 1).replace(/-/g, ""));
    }
    lines.push("SUMMARY:" + icsEscape(row.title));
    var loc = [row.venue, row.neighborhood].filter(Boolean).join(", ");
    if (loc) lines.push("LOCATION:" + icsEscape(loc));

    var links = Array.isArray(row.links) ? row.links.filter(function (l) { return l && l.url; }) : [];
    var url = (links[0] && links[0].url) || row.url || "";
    var enr = row.enrichment || {};
    var desc = [];
    if (typeof row.rating === "number") desc.push("Recommended for you: " + row.rating + "/5");
    if (Array.isArray(row.lineup) && row.lineup.length) desc.push("Lineup: " + row.lineup.join(", "));
    var about = enr.description || row.detail || "";
    if (about) desc.push(String(about).slice(0, 500));
    var why = enr.curator_note || (row.verdict && row.verdict.why) || "";
    if (why) desc.push("Why: " + String(why).slice(0, 500));
    if (row.price) desc.push(String(row.price));
    if (url) desc.push(url);
    if (desc.length) lines.push("DESCRIPTION:" + icsEscape(desc.join("\n")));
    if (url) lines.push("URL:" + url);           // URI value — not TEXT-escaped (lib/ics.py convention)
    lines.push("END:VEVENT");
    return lines;
  }

  // The whole feed document. opts: { todayISO (required — the caller knows LA-today),
  // calname?, stamp? } — stamp defaults from feed.generated_at so output is deterministic.
  function buildIcs(feed, settings, opts) {
    opts = opts || {};
    var events = selectEvents(feed, settings, opts.todayISO);
    var stamp = opts.stamp || utcStamp(feed && feed.generated_at);
    var who = feed && feed.profile && feed.profile.name ? feed.profile.name : "";
    var ns = normSettings(settings);
    var saved = ns.savedHash || ns.saved || ns.keys.length > 0;
    var name = opts.calname ||
      (saved ? (who ? "LA Events — " + who + "’s starred" : "LA Events — starred")
             : (who ? "LA Events — " + who : "LA Events — top picks"));
    var lines = [
      "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//la-events//calendar-feed//EN",
      "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
      "X-WR-CALNAME:" + icsEscape(name),
      "X-WR-TIMEZONE:" + TZID,
      // both spellings of "re-poll twice a day" — clients honor one or the other
      "REFRESH-INTERVAL;VALUE=DURATION:PT12H", "X-PUBLISHED-TTL:PT12H",
    ].concat(VTIMEZONE);
    for (var i = 0; i < events.length; i++) lines = lines.concat(eventLines(events[i], stamp));
    lines.push("END:VCALENDAR");
    return lines.map(icsFold).join("\r\n") + "\r\n";
  }

  return {
    DEFAULTS: DEFAULTS,
    LIMITS: LIMITS,
    WEEKDAYS: WEEKDAYS,
    TZID: TZID,
    canonTag: canonTag,
    eventGenres: eventGenres,
    eventType: eventType,
    weekdayOf: weekdayOf,
    addDaysISO: addDaysISO,
    parseStartTime: parseStartTime,
    normSettings: normSettings,
    settingsFromParams: settingsFromParams,
    paramsFromSettings: paramsFromSettings,
    selectEvents: selectEvents,
    keyList: keyList,
    buildIcs: buildIcs,
  };
});
