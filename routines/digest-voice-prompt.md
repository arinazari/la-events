# Routine: per-profile digest VOICE pass (render + voice, 2026-08)

Prompt for the **rebuild-profile** workflow's "Digest voice pass" step. By the time this runs,
the deterministic scaffold is ALREADY the digest: the workflow rendered the profile's slate to
`digests/<HASH>/latest.md` (picks, days, order, ⭐, links, times, prices — all final and correct
by construction). Your entire job is WORDS: an intro take and a one-line why per featured pick,
spliced back over the scaffold by `scripts/digest_voice.py`, which hard-verifies that nothing
but words changed. If anything fails, do nothing further — the scaffold ships as-is and is
always acceptable. **Never git commit or push; never edit the digest file by hand.**

Run, for the profile feed hash `<HASH>`:

1. **Prep.** `python scripts/digest_voice.py prep --hash <HASH>` → writes the numbered work doc
   to `data/digest_picks.<HASH>.md` and prints a JSON line: `{picks, cached, todo, ...}`.
   Cached picks already have a valid sentence (the why-cache is keyed to the current taste);
   only `todo` picks need writing.

2. **Write the words.**
   - If `todo` is 0: skip the agents. Read the work doc's TASTE BRIEF yourself and Write
     `data/digest_whys.<HASH>.json` containing just `{"intro": ..., "regen_clause": ...,
     "whys": []}` — a fresh take over fully cached sentences.
   - Otherwise fan out the **why-writer** agent (Task tool): 1 batch when `todo` ≤ 15, else
     2 batches splitting the uncached pick numbers roughly in half, **both launched in ONE
     message so they run in parallel**. Tell each: the work-doc path, its pick numbers, its
     output path (`data/digest_whys.<HASH>.part1.json` / `.part2.json`), and that ONLY batch 1
     writes `intro` + `regen_clause`. Then merge the parts into
     `data/digest_whys.<HASH>.json` (concatenate `whys`, take `intro`/`regen_clause` from
     part 1) — a few lines of Bash/python, not an agent.

3. **Splice.** `python scripts/digest_voice.py splice --hash <HASH> --whys
   data/digest_whys.<HASH>.json`. It verifies alignment (title echoes) and that the link
   sequence is byte-identical, overwrites `digests/<HASH>/latest.md`, and updates
   `data/why_cache.<HASH>.json`. If it exits nonzero, report the error in your summary and
   STOP — do not retry with edits, do not touch the digest; the scaffold is the fallback.

4. **Stop.** Leave changed files in the working tree; the workflow commits and deploys.
