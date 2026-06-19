# Concierge backend — the `BACKEND_URL` for the dashboard's LLM mode

The dashboard is a static page, so it can't hold an API key or call an LLM. This tiny
Cloudflare Worker is the seam that does. It holds `ANTHROPIC_API_KEY`, grounds the model on
the live `data.json` (events + dining + taste), and answers in the concierge voice. The page's
**Concierge** mode POSTs here; **Fast filter** mode never touches it (and the page falls back to
Fast filter automatically if this backend is unset or down).

It does **two** things, depending on what the POST body carries:

```
1. CHAT (always)
   dashboard ──POST {messages, profile?}──► worker ──► Anthropic    grounded on data.json
             ◄──────── { reply } ──────────                          (or the profile's feed)

2. TASTE SELF-EDIT (only when a profile is attached AND GITHUB_TOKEN is set)
   "more techno, less comedy" ─► worker ─► Claude calls propose_taste_change
       ─► worker commits profiles/<name>/taste.yaml ─► CI rebuilds the feed ─► Pages redeploys
             ◄──── { reply, taste_changed:true } ────   "re-ranking, refresh in ~a minute"
```

The self-edit keeps the **single deterministic scorer**: the Worker only edits the taste file;
`scripts/build_profiles.py` (the same `lib/scoring.py` the digest uses) does the actual
re-scoring in CI — see `.github/workflows/build-profiles.yml` — so a profile's ranking can't
drift from the digest. The Worker applies a **structured patch** (add/remove tracked artists,
venues, comedians; add a high-category / boost / penalty line; append a feedback note), never a
freeform rewrite, and refuses to commit anything that doesn't re-parse as valid YAML.

## Contract

```
POST  { messages: [{role:'user'|'assistant', content:string}, ...], profile?: "<feed-hash>" }
->    { reply: string, taste_changed?: boolean }
Auth: optional  Authorization: Bearer <CONCIERGE_TOKEN>
```

`profile` is the feed hash the page already computes from the username (it's what `data.<hash>.json`
is named after). The Worker resolves it back to the profile via `profiles.yaml` and edits only that
person's `profiles/<name>/taste.yaml` — never the shared root `taste.yaml`.

## Deploy (Cloudflare Workers — free tier)

```bash
cd backend
npm i                                      # installs the `yaml` dep the Worker bundles
npx wrangler login
npx wrangler secret put ANTHROPIC_API_KEY  # paste your Anthropic key
npx wrangler secret put CONCIERGE_TOKEN    # optional but recommended (see Auth)
npx wrangler secret put GITHUB_TOKEN       # optional — enables friend taste self-edit (see below)
npx wrangler deploy                        # prints https://la-events-concierge.<you>.workers.dev
```

Then point the dashboard at it: open the page, tap **connect** in the chat header, paste the
Worker URL + (if set) the token. Stored in your browser's localStorage — no redeploy needed.

## Config

| Env | Where | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | `wrangler secret put` | **required** — your Anthropic key |
| `CONCIERGE_TOKEN`   | `wrangler secret put` | optional shared token gating the proxy (see Auth) |
| `GITHUB_TOKEN`      | `wrangler secret put` | optional — a **fine-grained PAT scoped to this repo, Contents: read & write**. Set it to enable taste self-edit; leave it unset and the Worker is chat-only. |
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

The `GITHUB_TOKEN` should be a **fine-grained PAT limited to this one repo with only Contents
write** — nothing else. Worst case a friend rewrites their own taste file; you `git revert` it.

## Porting to another host

The logic is host-agnostic — only the wrapper differs. For Vercel/Netlify functions or a Node
server, reuse `buildSystem()` + `sanitizeMessages()` + `callAnthropic()` + the taste helpers
(`applyPatch`, `applyTasteEdit`, the `gh*` functions) and swap `export default { fetch }` for that
platform's handler signature.
