# sms-ingestion.md — Twilio SMS/MMS → catalog

Spec for ingesting promoter text blasts into la-events. This automates the SMS
"manual-capture" path described in SKILL.md. Read alongside CLAUDE.md (conventions) and
the flyer-capture section of the skill — the parsing logic here reuses it.

## The core constraint (read first)

Inbound texts arrive at random times; the digest runs on a schedule. So the webhook
receiver and the digest are **decoupled** and talk through the repo:

```
[Twilio number] --inbound SMS/MMS webhook--> [always-on receiver] --append--> data/inbox.jsonl (repo)
[scheduled digest routine] --read unprocessed lines--> parse --> merge into data/catalog.json --> mark processed
```

The receiver does almost nothing: validate, normalize, append one line per message. All
parsing and dedup happen in the digest run. Keep the receiver dumb so it never drops a
text — a scheduled routine cannot *be* the webhook (it's not running when the text lands),
so it must process an accumulated inbox instead.

## The receiver — two host options, both fine

- **Twilio Functions (recommended — zero extra infra).** Hosted in the Twilio console, no
  third-party server. Can make outbound HTTPS calls, so it appends to the repo via the
  GitHub Contents API (or fires a `repository_dispatch`). Twilio signature validation is
  available out of the box.
- **Cloudflare Worker / Vercel function.** If you'd rather keep logic out of Twilio. Free
  tiers cover this volume trivially; you validate `X-Twilio-Signature` yourself.

Either way the receiver: (1) confirms the request is really from Twilio, (2) builds the
record below, (3) appends it to `data/inbox.jsonl`, (4) returns an empty 200 / empty TwiML
(no auto-reply to the promoter).

## What Twilio POSTs

`Content-Type: application/x-www-form-urlencoded`. Fields we use:

- `From` — sender number (the promoter)
- `To` — your Twilio number
- `Body` — message text
- `MessageSid` — unique id; the idempotency key
- `NumMedia` — attachment count (MMS)
- `MediaUrl0`, `MediaUrl1`, … — media URLs; `MediaContentType0`, … give the type

**MMS matters:** promoters often send image flyers, not text. Capture the media URL(s) so
the digest can run them through the same flyer-image parse a pasted screenshot uses.

## inbox.jsonl record (one JSON object per line, append-only)

```json
{
  "sid": "<MessageSid>",
  "from": "<From>",
  "received": "<ISO8601>",
  "body": "<Body>",
  "media": ["<MediaUrl0>"],
  "processed": false
}
```

`media` is empty for plain SMS. The digest sets `processed: true` (or moves the line to
`data/inbox-archive.jsonl`) after parsing. Never process the same `sid` twice.

## Digest-side consumption (add to run_digest / SKILL digest mode)

1. Read `data/inbox.jsonl`; take entries with `processed == false`.
2. Parse `body` via the blast-parsing rules (flyer-capture section of SKILL.md). If `media`
   is present, fetch and run the flyer-image parse; media wins when the text is just
   "flyer attached." **Twilio media URLs need your Twilio auth to fetch and expire after a
   retention window — fetch them during the run, don't store the URL for later.**
3. Normalize to a catalog event: preserve "location TBA — drops day-of," capture lineup,
   date, price tiers, RSVP mechanics. Tag `source: "sms"` and keep the from-number so
   Discover mode can build a number → known-promoter map over time.
4. Merge into the catalog with the standard dedupe — a warehouse party texted to you may
   also be on RA, and the same (venue/date/headliner) key applies.
5. Mark processed. Idempotent on `sid`.

## Security

- **Always validate request origin.** Twilio Functions: on by default. External receiver:
  verify `X-Twilio-Signature` against your auth token and reject mismatches — otherwise
  anyone can POST fake events into your catalog.
- Store the Twilio Account SID / auth token as secrets (Twilio Function env or the cloud
  environment), never in the repo.
- The GitHub token the receiver uses to append should be a fine-grained PAT scoped to this
  repo only, `contents: read/write`.

## Twilio setup (one-time)

1. Buy a number: Twilio console → Phone Numbers → Buy a number → US local with SMS (and
   MMS if you want image flyers). ~$1.15/mo.
2. Stand up the receiver (Twilio Function or Worker); note its URL.
3. On the number's config, set **"A message comes in" → Webhook → <receiver URL>, HTTP POST**.
4. Text the number from your phone; confirm a line lands in `inbox.jsonl`.
5. Start giving the number out when you join lists (batched via the Discover-mode queue).

## A2P 10DLC

Receiving needs no registration. Only *sending* (e.g. scripting "JOIN" keyword opt-ins)
requires low-volume A2P 10DLC (~$4 brand + $15 campaign + ~$1.50–10/mo). Recommendation:
don't bother for a handful of opt-ins — send those by hand from the console.

## Cost at this volume

Number ~$1.15/mo; inbound a fraction of a cent each (small T-Mobile inbound fee); receiver
hosting free. Effectively ~$1–2/mo all in.

---

> Slots into ROADMAP Phase 2. Depends on nothing else being built first — the receiver can
> go up today; digest-side parsing reuses the existing flyer logic.
