# Discover proposals — 2026-11-17 (nothing applied to sources.yaml; awaiting approval)

Auto-applied (allowed): Eventbrite `--scan-catalog` added 2 organizers (Nightmare Productions, Yost Theater Nightlife).
Rotation this week: NYE 2026, Latin/global, experimental/new-music, catalog gap-mine.
Caveat: the scout had no shell, so DICE/RA/Shotgun were not probed.

**Headline:** NYE is already well covered (~55 rows on 12/31 via RA/19hz/EB). The real gaps are
new/experimental music (UCLA CAP, Monday Evening Concerts) and the Latin club-night lane (The Mayan).

| # | Source | Category | Method | Sample | Catalog overlap | Rec |
|---|---|---|---|---|---|---|
| 1 | UCLA CAP (Nimoy / Royce / Freud) | live_music (new music) | webfetch `https://cap.ucla.edu/calendar` | Gloria Cheng + Ralph van Raat 11/20, SPELLLING 12/12, Vijay Iyer + Jennifer Koh 1/16, Kronos 1/31, Helado Negro + Sō Percussion 2/10 | 0 (checked: Kronos/Helado Negro absent) | **Add** (p2) |
| 2 | The Mayan (DTLA) | Latin / global club nights | webfetch `https://mayanmusicvenue.com/events/` | Yalla Habibi 11/20, La Santa 11/21, Mayan Fridays 11/27, 12/4, 12/11 | 1 row (TM, venue "Mayan Theatre") | **Add** (p2). No year on the page; tickets via Discotech |
| 3 | Monday Evening Concerts | live_music (new music) | webfetch homepage (Squarespace JSON is empty) | Canto Ostinato 12/7 + 12/14, Perfect Lives 1/25 | 0 | Add (p3): tiny volume, high fit |
| 4 | Masterbeat LA NYE (Leap Events) | electronic / LGBTQ+ | manual, `https://outxout.com/event/masterbeat-la` | Confessions NYE 12/31 @ The Vermont; Salvation afterhours 1/1 @ The Mayan | 0 | Add as manual / one-off rows |
| 5 | Mood (musicofourdesire) + Discotech | directory (Latin/cumbia/club) | seeds only; Mood returns 403 | Mood claims 52 NYE parties; Discotech has Perreo Thursdays @ Los Globos, Trapeton | thin Latin coverage (~6 rows) | Probe from a residential IP; could be a Latin "19hz" |

Hold: REDCAT (mostly dance/theater; optional for Perfume Genius 2/18–27), Coaxial Arts (only stale dates seen).

Dropped after check: Moroccan Lounge, Teragram, Bellwether, Peppermint (all TM); Exchange,
Reframe, Boardner's, Airliner, Lexington (RA/19hz/EB); Redwood Bar (41 rows via RA, own calendar
adds ~2); Ambient Church, dublab (JS-only, unverified); Wild Up (nothing dated).

Flags on existing data:
- Countdown NYE 2026 is a 2-day event at NOS (12/31–1/1). Confirm the catalog row carries both days.
- Time Warp LA 11/27–28 has 3 catalog rows. Possible dedupe miss.
- The one Mayan row ("Fenix Flexin" 11/25) links to the 1720 site. Possible venue mismatch.

Backlog: the 11-03 and 11-10 batches and `source-candidates.md` are still unapplied, and
`last_discovery` is still 2026-10-06. After approval, set it to 2026-11-17.

Paste-ready YAML for #1–4 is below.

```yaml
  - name: UCLA Center for the Art of Performance (CAP)
    category: live_music
    method: webfetch
    url: https://cap.ucla.edu/calendar
    priority: 2
    status: candidate
    notes: >
      Westwood (Nimoy / Royce / Freud). New-music, experimental and cross-genre bookings.
      Verified 2026-11-17: calendar reads cleanly, dated into Feb 2027. No ICS/JSON-LD.
      Tickets via ucla.evenue.net. Filter out school matinees and dance-only.

  - name: The Mayan (DTLA)
    category: live_music
    method: webfetch
    url: https://mayanmusicvenue.com/events/
    priority: 2
    status: candidate
    notes: >
      1038 S Hill St. Latin/reggaeton/global club nights (Mayan Fridays, La Santa, Yalla
      Habibi, Bollywood). No year on the page (infer it). Tickets via Discotech. Normalize
      venue "The Mayan" / "Mayan Theatre" for dedupe.

  - name: Monday Evening Concerts
    category: live_music
    method: webfetch
    url: https://www.mondayeveningconcerts.org/
    priority: 3
    status: candidate
    notes: >
      Long-running new/experimental music series at various venues (Marciano, Zipper Hall).
      Squarespace JSON collection is empty, so use WebFetch. Low volume, high fit.

  - name: Masterbeat Los Angeles NYE (Leap Events)
    category: electronic
    method: manual
    url: https://outxout.com/event/masterbeat-la
    priority: 3
    status: manual
    notes: >
      Annual LGBTQ+ NYE circuit. 2026: Confessions NYE 12/31 @ The Vermont Hollywood;
      Salvation afterhours 1/1 3-10am @ The Mayan. Re-check the lineup in early Dec.
```
