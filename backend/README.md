# Concierge backend — the `BACKEND_URL` for the dashboard's LLM mode

The dashboard is a static page, so it can't hold an API key or call an LLM. This tiny
Cloudflare Worker is the seam that does: it holds `ANTHROPIC_API_KEY`, grounds the model on
the live `data.json` (events + the dining list + your taste), and answers in the concierge
voice. The page's **Concierge** mode POSTs here; **Fast filter** mode never touches it (and the
page falls back to Fast filter automatically if this backend is unset or down).

```
dashboard (Concierge mode)  ──POST {messages}──►  concierge-worker.js  ──►  Anthropic API
                            ◄──── { reply } ─────                       grounded on data.json
```

## Deploy (Cloudflare Workers — free tier)

```bash
cd backend
npm i -g wrangler          # or: npx wrangler ...
wrangler login
wrangler secret put ANTHROPIC_API_KEY      # paste your Anthropic key
wrangler secret put CONCIERGE_TOKEN        # optional but recommended (see Auth)
wrangler deploy                            # prints your https://la-events-concierge.<you>.workers.dev URL
```

Then point the dashboard at it: open the page, in the chat header tap **connect**, paste the
Worker URL and (if set) the token. They're stored in your browser's localStorage — no redeploy
needed. (You can also pre-bake them by editing `BACKEND_URL` near the top of the dashboard's
component script.)

## Config

| Env | Where | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | `wrangler secret put` | **required** — your Anthropic key |
| `CONCIERGE_TOKEN`   | `wrangler secret put` | optional shared token gating the proxy (see Auth) |
| `ANTHROPIC_MODEL`   | `wrangler.toml [vars]` | which Claude model to use (defaults to Sonnet; bump to a more capable model for richer planning) |
| `DATA_URL`          | `wrangler.toml [vars]` | the published `data.json` to ground on |
| `ALLOWED_ORIGIN`    | `wrangler.toml [vars]` | CORS origin (your Pages site) |

## Auth — read this

Your Pages site is public, so the `BACKEND_URL` is discoverable. **If `CONCIERGE_TOKEN` is
unset, the proxy is open** — anyone who finds the URL can spend your Anthropic budget. Options,
cheapest first:

1. **Shared token (default here).** Set `CONCIERGE_TOKEN`; share it with yourself + friends; it's
   entered once in the page (localStorage) and sent as `Authorization: Bearer …`. Good enough for
   a private tool; the token is visible to anyone you give it to (and lives in their browser).
2. **Cloudflare Access** in front of the Worker — Google/email login gate, no token in the
   client. The clean "private to Ari + friends" answer; a bit more setup.
3. **Add rate limiting** (Cloudflare rules / a KV counter) as a backstop on spend regardless.

## Porting to another host

The logic is host-agnostic — only the wrapper differs. For Vercel/Netlify functions or a Node
server, reuse `buildSystem()` + `sanitizeMessages()` + the Anthropic `fetch`, and swap
`export default { fetch }` for that platform's handler signature. Ping me and I'll port it.
