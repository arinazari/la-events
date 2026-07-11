/**
 * Node tests for the Worker's pure edit helpers — the YAML self-edit functions that commit a
 * profile's files. Run: `cd backend && npm i && node test-edits.mjs` (needs the `yaml` dep).
 * No network, no Anthropic, no GitHub — just the structured-patch -> YAML round-trips.
 */
import assert from "node:assert";
import { readFileSync } from "node:fs";
import { parse as yamlParse, parseDocument } from "yaml";
import {
  applyDigestPatchDoc, newDigestDoc, applyProfilePatchDoc, applyPatchDoc, buildSystem, profileHash,
} from "./concierge-worker.js";

let passed = 0;
const ok = (name) => { console.log("ok  " + name); passed++; };

/* ---- digest FORMAT edits (the new tool) ---- */
{
  const doc = newDigestDoc("Lori");
  const touched = applyDigestPatchDoc(doc, {
    length: "brief", group_by: "neighborhood", max_picks_per_day: 5,
    set_sections: ["dont_miss", "day_by_day"], add_emphasis: ["lead with live music"],
    add_tone: ["drier, less hype"], summary: "tighten it up",
  });
  const out = yamlParse(String(doc));
  assert.equal(out.length, "brief");
  assert.equal(out.group_by, "neighborhood");
  assert.equal(out.max_picks_per_day, 5);
  assert.deepEqual(out.sections, ["dont_miss", "day_by_day"]);
  assert.deepEqual(out.emphasis, ["lead with live music"]);
  assert.deepEqual(out.tone, ["drier, less hype"]);
  assert.ok(touched.length >= 6);
  ok("digest: fresh doc applies every field");
}
{
  const doc = newDigestDoc("X");
  applyDigestPatchDoc(doc, { max_picks_per_day: 8 });
  assert.equal(yamlParse(String(doc)).max_picks_per_day, 8);
  applyDigestPatchDoc(doc, { max_picks_per_day: 0 });          // 0 clears the cap -> null
  assert.equal(yamlParse(String(doc)).max_picks_per_day, null);
  ok("digest: max_picks_per_day 0 clears the cap to null");
}
{
  const doc = newDigestDoc("X");
  applyDigestPatchDoc(doc, { add_emphasis: ["a", "b"] });
  applyDigestPatchDoc(doc, { add_emphasis: ["a", "c"] });       // dedupe
  assert.deepEqual(yamlParse(String(doc)).emphasis, ["a", "b", "c"]);
  applyDigestPatchDoc(doc, { remove_lines: ["b"] });
  assert.deepEqual(yamlParse(String(doc)).emphasis, ["a", "c"]);
  ok("digest: add dedupes, remove_lines drops an entry");
}
{
  const doc = newDigestDoc("X");
  assert.deepEqual(applyDigestPatchDoc(doc, { summary: "no-op" }), []);   // nothing actionable
  assert.deepEqual(applyDigestPatchDoc(doc, { length: "loud" }), []);     // invalid enum ignored
  ok("digest: no-op / invalid values touch nothing");
}
{
  // Editing an EXISTING digest.yaml (the repo's root) preserves its comments + untouched keys.
  const text = readFileSync(new URL("../digest.yaml", import.meta.url), "utf8");
  const doc = parseDocument(text);
  applyDigestPatchDoc(doc, { length: "detailed" });
  const s = String(doc);
  assert.ok(s.includes("#"), "comments survive the round-trip");
  assert.equal(yamlParse(s).length, "detailed");
  assert.deepEqual(yamlParse(s).sections, ["dont_miss", "day_by_day", "around_town", "radar"]);
  ok("digest: editing the real root file preserves comments + untouched keys");
}

/* ---- existing tools still behave (regression guard for the dispatch refactor) ---- */
{
  const doc = parseDocument("categories:\n  high: [a]\nartists_tracked: [Foo]\n");
  applyPatchDoc(doc, { add_artists: ["Bar"], summary: "track Bar" }, "2026-06-24");
  const out = yamlParse(String(doc));
  assert.ok(out.artists_tracked.includes("Bar"));
  assert.ok((out.feedback || []).some((l) => /track Bar/.test(l)));
  ok("taste: add_artists + feedback trail still works");
}
{
  const doc = parseDocument("home:\n  neighborhood: Silver Lake\n");
  const touched = applyProfilePatchDoc(doc, { home: { neighborhood: "Glendale", coords: [34.14, -118.25] } }, {});
  const out = yamlParse(String(doc));
  assert.equal(out.home.neighborhood, "Glendale");
  assert.deepEqual(out.home.coords, [34.14, -118.25]);
  assert.ok(touched.includes("home"));
  ok("profile: home edit still works");
}

/* ---- system prompt advertises the new capabilities ---- */
{
  const s0 = buildSystem(null);
  assert.ok(/plan_with_friends/.test(s0), "persona mentions plan_with_friends");
  const sEdit = buildSystem({ events: [], dining: [], profile: { name: "Lori" } }, { canEdit: true, profileName: "Lori" });
  assert.ok(/propose_digest_change/.test(sEdit), "edit persona mentions propose_digest_change");
  assert.ok(/TOKEN-COST/.test(sEdit), "edit persona carries the token-cost guardrail");
  ok("system prompt advertises group planning + digest editing + the guardrail");
}

/* ---- hash parity with Python/build_profiles (salt + token, Track A1) ---- */
{
  // Same fixture as scripts/lib/profiles.py: sha256("la-events/v2:" + token)[:16].
  assert.equal(await profileHash("aaaa000011112222", "la-events/v2:"), "a8de6e4309060de7");
  assert.equal(await profileHash(" AAAA000011112222 ", "la-events/v2:"),
               await profileHash("aaaa000011112222", "la-events/v2:"));
  ok("profileHash matches the Python/page hashing (token, v2 salt)");
}

console.log(`\nall ${passed} worker edit tests passed`);
