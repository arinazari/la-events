/**
 * Node tests for the Worker's live star fold (GET /stars) — foldStarMap must agree with the
 * build-time fold (scripts/lib/reactions.star_map + stars_for): last-wins, unstar/hide clear,
 * stub names for unmapped hashes, (name.lower, hash) tuple sort.
 * Run: `cd backend && npm i && node test-stars.mjs`. No network — pure text in, map out.
 */
import assert from "node:assert";
import { foldStarMap } from "./concierge-worker.js";

let passed = 0;
const ok = (name) => { console.log("ok  " + name); passed++; };

const L = (o) => JSON.stringify(o);
const NAMES = { aaa1: "Ari", bbb2: "Lori", ccc3: "alba" };

{
  const text = [
    L({ ts: "2026-08-01", profile: "aaa1", event_key: "k1", kind: "star" }),
    L({ ts: "2026-08-01", profile: "bbb2", event_key: "k1", kind: "star" }),
    L({ ts: "2026-08-01", profile: "aaa1", event_key: "k2", kind: "star" }),
  ].join("\n");
  const m = foldStarMap(text, NAMES);
  assert.deepEqual(m.k1.map((s) => s.name), ["Ari", "Lori"]);
  assert.deepEqual(m.k2, [{ name: "Ari", hash: "aaa1" }]);
  ok("stars fold per event with resolved names");
}
{
  const text = [
    L({ profile: "aaa1", event_key: "k1", kind: "star" }),
    L({ profile: "aaa1", event_key: "k1", kind: "unstar" }),
    L({ profile: "bbb2", event_key: "k1", kind: "star" }),
    L({ profile: "bbb2", event_key: "k1", kind: "hide" }),
    L({ profile: "ccc3", event_key: "k1", kind: "unstar" }),
    L({ profile: "ccc3", event_key: "k1", kind: "star" }),
  ].join("\n");
  const m = foldStarMap(text, NAMES);
  assert.deepEqual(m.k1, [{ name: "alba", hash: "ccc3" }]);
  ok("last state wins — unstar and hide both clear, re-star revives");
}
{
  const m = foldStarMap(L({ profile: "aaa1", event_key: "k1", kind: "unstar" }), NAMES);
  assert.deepEqual(m, {});
  ok("fully-unstarred events drop out of the map entirely");
}
{
  const text = [
    "# comment", "", "not json", L({ profile: "aaa1", kind: "star" }),
    L({ profile: "", event_key: "k1", kind: "star" }), L({ profile: "aaa1", event_key: "k1", kind: "less" }),
    L({ profile: "aaa1", event_key: "k1", kind: "star" }),
  ].join("\n");
  assert.deepEqual(foldStarMap(text, NAMES), { k1: [{ name: "Ari", hash: "aaa1" }] });
  ok("junk lines, missing fields, and non-star kinds are ignored");
}
{
  const m = foldStarMap(L({ profile: "dead0000cafe", event_key: "k1", kind: "star" }), NAMES);
  assert.deepEqual(m.k1, [{ name: "friend·dead", hash: "dead0000cafe" }]);
  ok("unmapped hash shows as the nameless stub — stale identities never leak");
}
{
  // tuple sort parity with lib/reactions.stars_for: ("a","z") sorts before ("ab","x")
  const text = [
    L({ profile: "zz", event_key: "k1", kind: "star" }),
    L({ profile: "xx", event_key: "k1", kind: "star" }),
  ].join("\n");
  const m = foldStarMap(text, { zz: "a", xx: "ab" });
  assert.deepEqual(m.k1.map((s) => s.name), ["a", "ab"]);
  const m2 = foldStarMap(text, { zz: "Same", xx: "same" });
  assert.deepEqual(m2.k1.map((s) => s.hash), ["xx", "zz"]);
  ok("(name.lower, hash) tuple sort matches the build-time fold");
}

console.log(`\n${passed} star-fold tests passed`);
