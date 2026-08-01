# Concierge backend — the `BACKEND_URL` for the dashboard's LLM mode

The dashboard is a static page, so it can't hold an API key or call an LLM. This tiny
Cloudflare Worker is the seam that does. It holds `ANTHROPIC_API_KEY`, grounds the model on
the live `data.json` (events + dining + taste), and answers in the concierge voice. The page's
**Concierge** mode POSTs here; **Fast filter** mode never touches it (and the page falls back to
Fast filter automatically if this backend is unset or down).

It does **a few** things, depending on what the POST body carries:

```
1. CHAT (always)
   dashboard ──POST {messages, profile?}──► worker ──► Anthropic    grounded on data.json
             ◄──────── { reply } ──────────                          (or the profile's feed)

2. TASTE SELF-EDIT (only when a profile is attached AND GITHUB_TOKEN is set)
   "more techno, less comedy" ─► worker ─► Claude calls propose_taste_change
       ─► worker commits profiles/<name>/taste.yaml ─► CI rebuilds the feed ─► Pages redeploys
             ◄──── { reply, taste_changed:true } ────   "re-ranking, refresh in ~a minute"

3. PROFILE / MECHANISM SELF-EDIT (same gate) — taste.yaml is CONTENT; profile.yaml is MECHANISM
   "I moved to Glendale" / "weight live music higher" ─► worker ─► Claude calls propose_profile_change
       ─► worker commits profiles/<name>/profile.yaml ─► CI rebuilds the feed ─► Pages redeploys
             ◄──── { reply, profile_changed:true } ───   "re-ranking, refresh in ~a minute"

4. DIGEST FORMAT SELF-EDIT (same gate) — digest.yaml is FORMAT (how the digest READS, not what ranks)
   "make my digest shorter" / "drop the radar" ─► worker ─► Claude calls propose_digest_change
       ─► worker commits digest.yaml (root for owner; profiles/<name>/digest.yaml for a friend)
             ◄──── { reply, digest_changed:true } ───   "your digest reflects it on the next build"

5. PLAN WITH FRIENDS (read-only — any authed caller, no commit, no key)
   "what would me + Lori be into" ─► worker ─► Claude calls plan_with_friends(["lori"])
       ─► worker fetches each named PUBLIC feed + the caller's, returns a per-person rating matrix
             ◄──────────── { reply } ────────────   profiles aren't private; a username is permission

5b. STARS (POST /react — the one social save, no LLM, no CONCIERGE_TOKEN)
   ☆ Star on a card ─► worker POST /react {profile, event_key, kind, title?, artists?}
       ─► commits data/reactions.jsonl (last-wins per person+event) ─► everyone's dashboard
          overlays it in seconds via GET /stars (below); the nightly routine bakes `stars`
          into feeds + digests durably; the starrer's saved calendar picks it up
       ─► star/hide with artists also appends loved/hide to feedback.<hash>.jsonl (teaches ranking)
             ◄──────── { ok, changed, learned } ────────   gate = valid profile hash + GITHUB_TOKEN

5c. LIVE STAR MAP (GET /stars — display freshness, no auth, no LLM)
   page boot / tab refocus ─► worker GET /stars ─► reads data/reactions.jsonl + profiles.yaml,
       folds the ACTIVE star map (same rules as the build-time fold; ~30s cache)
             ◄──── { ok, ts, stars: {event_key: [{name, hash}]} } ────   page overlays it on the
          baked feed, so a friend's star (or unstar) shows without waiting for any rebuild

6. CALENDAR FEED (GET, no auth, no LLM — Google/Apple Calendar poll this)
   GET /calendar.ics?p=<hash>&min=&perday=&horizon=&days=&types=&xtypes=&genres=&xgenres=
       ─► worker fetches the PUBLIC feed (data[.<hash>].json), filters + builds iCalendar
             ◄──────── text/calendar ────────   dashboard/calendar-core.js does the work
```

Both self-edits keep the **single deterministic scorer**: the Worker only edits the YAML;
`scripts/build_profiles.py` (the same `lib/scoring.py` the digest uses) does the actual
re-scoring in CI — see `.github/workflows/build-profiles.yml` — so a profile's ranking can't
drift from the digest. Each is a **structured patch**, never a freeform rewrite, and the Worker
refuses to commit anything that doesn't re-parse as valid YAML:

- **`propose_taste_change`** (CONTENT) — add/remove tracked artists, venues, comedians; add a
  high-category / boost / penalty line; append a feedback note.
- **`propose_profile_change`** (MECHANISM) — set `home` (location + coords), `category_weights`,
  and the `near_home` / `penalty` / boost / `far` term lists. Because `lib/scoring.py` resolves
  each scoring key **all-or-nothing** (profile → taste → default), a first-time edit **materializes
  the full effective value first** — seeded from the root `profile.yaml`, which is the defaults
  verbatim — so it can never silently drop the rest of a list/map. A friend who has no
  `profiles/<name>/profile.yaml` yet gets one created on first edit. Source ids, rating thresholds,
  and the numeric Spotify/feedback/travel knobs are intentionally **not** exposed (hand-edit those).
- **`propose_digest_change`** (FORMAT) — how the digest *reads*, separate from what ranks: `length`,
  `group_by`, `sections`, `max_picks_per_day`, and the `emphasis`/`tone`/`notes` free-text lists in
  `digest.yaml` (owner → root; friend → `profiles/<name>/digest.yaml`, created on first edit). The
  model runs a **token-cost self-check** first: a change that materially raises generation cost
  (`length: detailed`, every-event, lifting a per-day cap) gets flagged with a bounded alternative
  before it's proposed; small/structural changes (reorder/toggle a section, `group_by`, tone) just
  apply. `build_profiles.py` injects the prefs into the feed and the digest gate signs over them, so
  a format change regenerates the narrative digest exactly once.

And one **read-only** tool (no commit, no GitHub token, available to any authed caller):

- **`plan_with_friends`** (GROUP) — "find events for me + Lori + Dr. Ganesan." Given the friends'
  usernames, the Worker fetches each one's **public** feed (`data.<hash>.json`) plus the caller's,
  joins upcoming events, and returns a per-person rating matrix the model reasons over with judgment
  (no fixed group rules — Ari's call). **Profiles aren't private**: knowing a username is permission
  enough, there's no opt-out flag. A username with no feed comes back under `unknown`.

## Stars (`POST /react`) — the one social save

```
POST /react { profile: "<feed-hash>", event_key: "<12-hex>", kind: "star"|"unstar"|"hide",
              title?: string, artists?: [string] }
->   200 { ok, changed, learned }
```

A star is double-duty by design. The Worker commits it to `data/reactions.jsonl` (the shared
log — star state is **last-wins per person+event**, idempotent taps), and the star is **visible
to everyone** two ways: within seconds via the live **`GET /stars`** overlay (the dashboard
fetches the folded map at boot/refocus and lays it over the baked feed), and durably at the next
feed/digest bake as `stars: [{name, hash}]` — "★ Lori" on the card and beside the event in every
digest. It also drives that person's **Starred calendar** (`GET /calendar.ics?saved=1`). AND — for `star`/`hide` with `artists` attached — it appends a
`loved`/`hide` line to that profile's `data/feedback.<hash>.jsonl`, which the existing tested
feedback→scoring fold picks up with **zero new ranking code** (append-once per event+kind, so
flapping can't stack weight; `unstar` never teaches — a past star still meant interest).

Gate = a **valid profile hash** (`resolveProfile` maps it via `profiles.yaml` — a name-derived
feed hash today; a capability token once Track A lands) **+ `GITHUB_TOKEN`**. There is **no
`CONCIERGE_TOKEN` check**: that token guards LLM spend and `/react` spends none, so a friend who
never set up the concierge can still star. Blast radius is a revertible commit to the shared
reactions log — same "obfuscation, not security" model as the feeds. Committing to the repo is
what makes stars mutual and durable (no per-viewer state); display freshness is `GET /stars`
(a reactions push deliberately does NOT trigger `build-profiles.yml` — a tap shouldn't cost a
fleet re-score + Pages deploy; the nightly routine bakes stars durably, and the feedback line
still triggers the starrer's re-rank). `GET /stars` folds the log with the SAME rules as the
build-time fold (`scripts/lib/reactions.py`): last-wins, unstar/hide clear, names resolved
through the CURRENT profiles.yaml (stale identities never leak), ~30s cache. Ported from Track A
"A4: stars" with the reactions.jsonl schema kept identical, so that branch's eventual merge is a
clean overlap.

## Contract

```
POST  { messages: [{role:'user'|'assistant', content:string}, ...], profile?: "<feed-hash>",
        stream?: true }
->    without stream: { reply, taste_changed?, profile_changed?, digest_changed? }   (application/json)
->    with stream:    application/x-ndjson progress lines, one JSON object each:
        {t:"hello",v}  {t:"delta",text}  {t:"reset"}  {t:"status",msg}  {t:"tick"}
        {t:"done", reply, taste_changed, profile_changed, digest_changed}   <- authoritative final
        {t:"error", code, error, detail}                                    <- in-band failure
Auth: optional  Authorization: Bearer <CONCIERGE_TOKEN>
GET / (no auth) -> { ok, service, v }   deploy fingerprint — `curl https://<worker>/` answers
                                        "which build is live?" (wrangler deploys are manual)
GET /calendar.ics (no auth) -> text/calendar   the calendar-subscription feed. Settings ride the
    query string (parsed by dashboard/calendar-core.js — the SAME file the page's calendar modal
    uses for its preview/snapshot, imported at bundle time, so they can't drift):
      p=<feed-hash>        whose feed (omit = the default data.json)
      min=1..5             minimum rating (default 4)         perday=1..10  max events/day (default 3)
      horizon=7..120       days ahead (default 60)            days=fri,sat  weekdays (empty = all)
      types= / xtypes=     include/exclude tags.type          genres= / xgenres=  include/exclude genres
      saved=1              STARRED mode: the calendar is every event this profile (p=) STARRED,
                           resolved server-side from the feed's `stars` field. A STABLE url — new
                           stars appear on the next poll, no re-subscribe. This is what the dashboard's
                           "Starred" calendar tab subscribes to.
      keys=k1,k2,…         legacy per-event key list baked into the url (the pre-server saves + the
                           client snapshot). Still honored so old subscriptions keep working.
POST /react (no CONCIERGE_TOKEN — see Stars) -> { ok, changed, learned }   star / unstar / hide.
GET /stars (no auth) -> { ok, ts, stars: {event_key: [{name, hash}]} }   the LIVE star map,
    folded from data/reactions.jsonl on demand (~30s cache). The dashboard overlays it on the
    baked feed at boot/refocus so stars appear in seconds. Public: stars already ship in every
    public feed; this re-serves the same data fresher.
    UNAUTHENTICATED BY DESIGN: calendar clients poll server-side and can't send Bearer headers,
    and the route spends nothing — no LLM call, no commit; it only re-serves the already-public
    Pages feed reshaped. Same obfuscation-not-security model as the feed hashes themselves.
```

The page opts into `stream` and falls back by response content-type, so old page ↔ new Worker and
new page ↔ old Worker both keep working (an old Worker ignores the flag and answers JSON). With
streaming, reply text appears in the chat as it generates; `reset` marks streamed text as tool-round
preamble (not the reply), `status` narrates the tool round ("updating your taste profile…"), and
`done.reply` replaces whatever accumulated (pause_turn chains can make them differ).

`profile` is the feed hash the page already computes from the username (it's what `data.<hash>.json`
is named after). The Worker resolves it back to the profile via `profiles.yaml` and edits that
person's files: a friend's own `profiles/<name>/{taste,profile}.yaml`, or — for the `owner: true`
profile (Ari's login) — the shared root `taste.yaml` / `profile.yaml`. A friend can never edit the
root files.

### Pipeline actions (the dashboard's refresh / update buttons)

Two extra POST routes let the dashboard trigger a GitHub Action (via `repository_dispatch`, the
same mechanism as `spotify-sync`) — they need `GITHUB_TOKEN` set, and are gated by the same
`CONCIERGE_TOKEN`:

```
POST /refresh-events            -> 202 { ok, dispatched:"refresh-events" }
     (admin "Refresh events database": re-fetch all sources, rebuild the catalog + default feed,
      republish the catalog version stamp — applies to everyone. event_type "refresh-events")
POST /rebuild-profile { profile: "<feed-hash>" } -> 202 { ok, dispatched:"rebuild-profile" }
     (per-user "Update my ranking & digest": full LLM pass for that ONE profile against the latest
      catalog — editor verdicts + scene enrichment + narrative digest. client_payload.profile = hash)
```

The page shows the **Refresh** button to the `owner:true` profile only; owner-enforcement is on the
page (consistent with this app's obfuscation model — the token gates spend/dispatch-spam). The
per-user **Update** button auto-disables when the loaded feed's `catalog_version` matches the live
`dashboard/catalog_meta.json` (i.e. the customization is already on the latest DB), and lights up
after an admin refresh. The workflows commit the rebuilt artifacts and redeploy Pages:

- `refresh-events.yml` is **deterministic** (fetch → catalog → default feed → version stamp); it
  needs the source secrets (`TM_API_KEY`, …) but no Anthropic key.
- `rebuild-profile.yml` runs **Claude Code** (`anthropics/claude-code-action`) over
  `routines/profile-digest-prompt.md`, so it needs **`ANTHROPIC_API_KEY` as a repo Actions secret**
  (the agent). The `GITHUB_TOKEN` PAT needs only **Contents: write** to fire `repository_dispatch`
  (the same scope taste self-edit / spotify-sync already use — no extra permission). A
  per-click LLM run costs tokens and takes a few minutes; the nightly routine still covers everyone.

## Deploy (Cloudflare Workers — free tier)

```bash
cd backend
npm i                                      # installs the `yaml` dep the Worker bundles
npx wrangler login
npx wrangler secret put ANTHROPIC_API_KEY  # paste your Anthropic key
npx wrangler secret put CONCIERGE_TOKEN    # optional but recommended (see Auth)
npx wrangler secret put GITHUB_TOKEN       # optional — enables taste self-edit + refresh/update buttons
npx wrangler deploy                        # prints https://la-events-concierge.<you>.workers.dev
```

Then point the dashboard at it: set the `BACKEND_URL` constant in `dashboard/index.html` to the
printed Worker URL and redeploy Pages. Visitors connect from the page itself — **connect** in the
chat header stores the token / personal key (per profile, in that browser's localStorage).

> Re-run `npx wrangler deploy` after Worker-code changes in this repo. Current pending changes
> (2026-07-21): the `opener` field is retired — the chat's take is display-only and the page no
> longer sends it, so a stale deployed Worker is harmless — the **calendar feed**
> (`GET /calendar.ics`) ships, and **stars** (`POST /react` + `GET /calendar.ics?saved=1`) at build
> `2026-07-21-star1`. The calendar modal probes the live route when opened and shows a "redeploy"
> note (subscribe links hidden, snapshot download still works) until the deploy lands; the Starred
> tab additionally checks the live build via the ping and warns if it's older than
> `2026-07-21-star1` (an older calendar build would serve picks for a `saved=1` URL, and `/react`
> wouldn't exist at all). Stars need `GITHUB_TOKEN` set (else `/react` returns 501). A stale Worker
> degrades gracefully — but stars + the starred calendar don't exist until you redeploy.

### "I redeployed but it still fails" — verify the deploy actually landed

`curl https://<worker>/` — every build since 2026-07-20 answers `GET /` with its deploy
fingerprint `{ok, service, v}` (`VERSION` in concierge-worker.js). Two outcomes matter:

- **`{"error":"POST only"}`** → the live build predates the fingerprint (2026-07-20, PR #96) —
  it might be the one-PR-older #95 build (which already streams but can't say so), or anything
  older. Either way, a deploy of the latest `main` did **not** land on the URL the page calls.
  Usual causes: `wrangler deploy` run from a stale checkout (`git pull` first — fixes land on
  `main` via PRs, so a laptop clone lags), or wrangler logged into a different Cloudflare
  account / worker name, so it deployed *somewhere else* — compare the URL wrangler prints
  against the page's `BACKEND_URL`.
- **`v` with an older DATE than the page's `MIN_BACKEND_VERSION`** (dashboard/index.html;
  compared at day granularity — same-day suffixes are free-form) → same story, newer flavor.
  The page checks this on every ping and shows **old build** (amber) in the chat's connect
  pill and modal, and names the stale build in chat error messages.

Signature worth knowing: a chat error of `502 — 524 error code: 524` is the Worker relaying
Cloudflare's timeout page from api.anthropic.com — the **non-streaming** call blowing the ~100s
first-byte window on a long generation (a profile self-edit is the worst case: two max-effort
generations plus a tool round). The streaming build can't produce that status (bytes flow
immediately), so seeing it after a "redeploy" means the old build is still live — check the
fingerprint before debugging anything else.

## Config

| Env | Where | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | `wrangler secret put` | **required** — your Anthropic key |
| `CONCIERGE_TOKEN`   | `wrangler secret put` | optional shared token gating the proxy (see Auth) |
| `GITHUB_TOKEN`      | `wrangler secret put` | optional — a **fine-grained PAT scoped to this repo, Contents: read & write**. That one scope covers taste **and** profile self-edit AND the refresh/update buttons (the `repository_dispatch` endpoint requires Contents: write — *not* Actions). Set it to enable those; leave it unset and the Worker is chat-only. |
| `POSH_TOKEN`        | `wrangler secret put` | optional — enables the `/posh` relay: `scripts/fetch_posh.py` retries through it when posh.vip's Cloudflare challenges the digest runner's datacenter IP (cloud sessions, GH Actions). Same session JWT as everywhere else; the route requires the caller to present a matching one, so **update this copy too at each ~monthly re-capture** or the fetcher will flag "sync the Worker copy". Unset → the route answers 501 and the fetcher degrades with an honest footer line. |
| `ANTHROPIC_MODEL`   | `wrangler.toml [vars]` | **executor** model — does the bulk of generation (default `claude-sonnet-4-6`) |
| `ADVISOR_MODEL`     | `wrangler.toml [vars]` | **advisor** the executor consults for multi-step planning (default `claude-opus-4-8`; `""` disables; must be ≥ the executor) |
| `EFFORT`            | `wrangler.toml [vars]` | executor effort `low`/`medium`/`high`/`max` (default `max`) |
| `MAX_TOKENS`        | `wrangler.toml [vars]` | output cap (default `8000`; raise if complex plans truncate — `stop_reason: max_tokens`) |
| `DATA_URL`          | `wrangler.toml [vars]` | the published `data.json` to ground on (profile feeds are derived from it) |
| `ALLOWED_ORIGIN`    | `wrangler.toml [vars]` | CORS origin (your Pages site) |
| `GITHUB_REPO` / `GITHUB_BRANCH` | `wrangler.toml [vars]` | where to commit taste edits (defaults: `arinazari/la-events` / `main`) |
| `PROFILE_SALT`      | `wrangler.toml [vars]` | **must match** the page + `build_profiles.py` (`la-events/v1:`) so hashes line up |

## Quality & cost

Tuned for **multi-step, high-quality planning**:

- **Advisor mode** — the cheap **executor** (Sonnet 4.6) does the generation and consults a stronger
  **advisor** (Opus 4.8) for planning (the `advisor_20260301` server tool). Opus-level plans at
  Sonnet-level bulk cost. The advisor must be ≥ the executor — if you set `ANTHROPIC_MODEL` to Opus,
  set `ADVISOR_MODEL` to the same Opus (or `""`), or the request 400s.
- **Max effort + adaptive thinking** — `EFFORT=max` + `thinking: adaptive` for the deepest reasoning.
- **Prompt caching** — the persona + grounded feed (the big, stable prefix) is sent as a cache block,
  so turns 2+ of a conversation read it at ~0.1× input cost.
- **Streaming upstream** — the Worker calls Anthropic with `stream: true` and folds the SSE back
  into one JSON reply for the page. This is load-bearing, not cosmetic: a non-streaming Messages
  call sends **zero bytes until the whole generation finishes**, and at max effort with the Opus
  advisor (or an Opus executor) that can exceed the Worker's outbound first-byte window — the
  chat then dies with `concierge backend error 502` even though nothing is misconfigured. With
  streaming, bytes flow immediately and the connection stays alive for the full generation.
- **Streaming downstream** (2026-07-20-stream3) — with `stream: true` in the body, the same text
  deltas are forwarded to the page as NDJSON (see Contract), so words appear in the chat as they
  generate instead of behind one long THINKING spinner. Perceived latency drops massively; total
  latency is unchanged.
- **Cheap confirmation round** — the follow-up generation after a **bare** taste/profile/digest
  edit ("track Peggy Gou", short message, no question) runs at `effort: low` — it's a one-line
  confirmation, not planning — roughly halving taste-edit latency. A mixed ask ("more techno —
  what's good this weekend?") keeps full effort, because its real answer is generated in that
  follow-up; so do `plan_with_friends` rounds (the group-matrix reasoning happens there). The
  ask-detection heuristic is deliberately greedy: misreading a bare edit only costs speed,
  never answer quality.

**Executor upgrade:** the page's **Use Opus** toggle sends `model: "opus"` in the body, and the
Worker honors it for **any authed caller** — shared-token users included (Ari's call: the token
already gates who can spend at all). BYOK callers pay on their own key as before.

**Tradeoff:** max effort + adaptive thinking + an Opus advisor is **slower and pricier per message**
(a complex "plan my Saturday" can take tens of seconds — the page shows a spinner and a stop button).
Dial it back anytime without code: set `EFFORT=high` (or `medium`), or `ADVISOR_MODEL=""` to drop the
Opus consult. If long plans get cut off, raise `MAX_TOKENS`.

## Auth — read this

Your Pages site is public, so `BACKEND_URL` is discoverable. **If `CONCIERGE_TOKEN` is unset, the
proxy is open** — anyone who finds the URL can spend your Anthropic budget (and, if `GITHUB_TOKEN`
is set, trigger commits). Set `CONCIERGE_TOKEN`; it's entered once in the page and sent as a Bearer
header. The *taste data* is low-stakes (every edit is a normal commit, revertible from git history),
but the **token still protects your API spend + the repo from spam** — so set it.

**Bring your own key (BYOK).** A caller can send their own Anthropic key in an `x-anthropic-key:
sk-ant-…` header (the dashboard's *Settings → Claude API key* stores it in that browser, behind an
on/off switch, and attaches it per request). When the switch is on, that key pays for the request —
the Worker uses it in place of `ANTHROPIC_API_KEY` — and it doubles as the entry ticket: **a valid
personal key satisfies the gate even when `CONCIERGE_TOKEN` is set**, so you can hand someone the
concierge without sharing your token. There's **no silent failover**: if a live key errors or hits a
limit the Worker surfaces that error (it does *not* fall back to your key); the user flips the switch
off and the shared token takes over. Self-edit (taste **and** profile) is **also** open to own-key
callers (Ari's call): the commit still uses *your* `GITHUB_TOKEN`, so a friend on their own key can
tune their taste/profile without the shared token. **Accepted tradeoff:** anyone who reaches the Worker
with any valid Anthropic key can trigger a (revertible) commit to a profile's file — keep `GITHUB_TOKEN` a fine-grained,
single-repo, Contents-only PAT so that's the worst they can do. (With `CONCIERGE_TOKEN` unset the proxy
is fully open either way.)

The `GITHUB_TOKEN` should be a **fine-grained PAT limited to this one repo with only Contents
write** — nothing else. Worst case a friend rewrites their own taste/profile file; you `git revert`
it. A friend can only ever touch files under their own `profiles/<name>/` — never the root.

## Per-profile Spotify (the music layer)

The same Worker also lets each **friend connect their own Spotify** so their feed re-ranks to
*their* listening — not Ari's. The refresh token never leaves Cloudflare; only the *derived* feed
is ever committed (the affinity artifact is gitignored — it's a friend's listening).

```
1. CONNECT (browser)
   page "Connect Spotify" ─► worker /spotify/login ─► Spotify consent ─► /spotify/callback
       ─► stores the refresh token in KV (keyed by feed hash) ─► repository_dispatch "spotify-sync"

2. SYNC (the routine / the spotify-sync CI job — holds SPOTIFY_SYNC_TOKEN)
   sync_profiles_spotify.py ─► worker /spotify/connected + /spotify/fetch  (raw payloads only)
       ─► lib/affinity.build_affinity ─► data/spotify/<hash>.json (gitignored)
       ─► build_profiles.py re-scores ─► dashboard/data.<hash>.json ─► Pages
```

Routes (all under `/spotify/`): `login`, `callback`, `status`, `disconnect` (browser-facing) and
`connected`, `fetch` (sync-facing, `Bearer SPOTIFY_SYNC_TOKEN`). The affinity is built by the one
tested **Python** builder (`lib/affinity.py`) — the Worker never computes taste, so a friend's
music layer can't drift from Ari's.

### Enable it

1. **Spotify app** at developer.spotify.com → add redirect URI
   `https://<your-worker>.workers.dev/spotify/callback` (must match `SPOTIFY_REDIRECT_URI` in
   `wrangler.toml`). Copy the Client ID + Secret.
2. **KV namespace**: `npx wrangler kv namespace create SPOTIFY_KV` → paste the `id` into
   `wrangler.toml`'s `[[kv_namespaces]]` block.
3. **Worker secrets**: `npx wrangler secret put` each of `SPOTIFY_CLIENT_ID`,
   `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_SYNC_TOKEN` (a strong random string), `STATE_SECRET` (any
   long random string — signs the OAuth state). Keep `GITHUB_TOKEN` set so the on-connect rebuild
   fires. Then `npx wrangler deploy`.
4. **Repo secrets** (GitHub → Settings → Secrets → Actions), so the daily routine + the
   `spotify-sync` workflow can sync: `SPOTIFY_SYNC_URL` = the Worker base URL, `SPOTIFY_SYNC_TOKEN`
   = the same value you set on the Worker.

| Env (Worker) | Where | Purpose |
|---|---|---|
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | `wrangler secret put` | Spotify app creds (token exchange) |
| `SPOTIFY_SYNC_TOKEN` | `wrangler secret put` | Bearer that gates `/spotify/connected` + `/spotify/fetch` (listening data) |
| `STATE_SECRET` | `wrangler secret put` | signs the short-lived OAuth `state` (CSRF) |
| `SPOTIFY_KV` | `wrangler.toml [[kv_namespaces]]` | per-profile refresh-token store |
| `SPOTIFY_REDIRECT_URI` | `wrangler.toml [vars]` | must equal the URI registered in the Spotify app |
| `PAGE_URL` | `wrangler.toml [vars]` | where the callback page's "back" link points |

**Privacy / threat model** — same "obfuscation, not security" as profiles: feed hashes are public
(they're the feed filenames), so a friend who has the shared `CONCIERGE_TOKEN` could attach a
Spotify to another known hash. Blast radius is small (they'd shape that feed's *music* nudge;
they can't read anyone's listening — `/spotify/fetch` needs `SPOTIFY_SYNC_TOKEN`), and it's
revertible (disconnect/reconnect). The derived feed does surface Spotify-matched artist names in
its "why" lines; if that's too much for a given friend, that's a future per-feed toggle.

## Porting to another host

The logic is host-agnostic — only the wrapper differs. For Vercel/Netlify functions or a Node
server, reuse `buildSystem()` + `sanitizeMessages()` + `callAnthropic()` + the self-edit helpers
(`applyPatchDoc` / `applyTasteEdit` for taste, `applyProfilePatchDoc` / `applyProfileEdit` /
`newProfileDoc` for profile, the `gh*` functions) and swap `export default { fetch }` for that
platform's handler signature.
