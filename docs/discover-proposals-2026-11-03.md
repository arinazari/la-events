# Discover proposals — 2026-11-03 (nothing applied to sources.yaml; awaiting approval)

Caveat: scout had no shell; DICE/RA/Shotgun returned 403/429/503, so slugs/methods are unverified.

| # | Source | Method | Rec |
|---|---|---|---|
| 1 | Kiss Kiss Bang Bang (Mid-Wilshire) — Paradisco, MUZIQUE Fridays | DICE venue slug `kiss-kiss-bang-bang-la-w79p` (from search; verify with fetch_dice.py) | Add |
| 2 | Los Globos (Silver Lake) | DICE, slug unresolved | Add once slug resolved |
| 3 | Club Tee Gee (Atwater) | DICE, slug unresolved | Hold |
| 4 | LP Vinyl Bar (Hollywood) | manual (IG @lpvinylbar); lpvinylbar.com/schedule didn't extract | Add manual |
| 5 | Cara Cara / Proper Sound Sessions (DTLA Proper) | webfetch properhotel.com/downtown-la/ | Candidate; verify still running |
| 6 | Grand Park Sunday Sessions | webfetch grandparkla.org/sundaysessions; seasonal, dormant until ~Jun 2027 | Seasonal candidate |
| 7 | Shotgun (shotgun.live) platform | unverified fetcher | Probe from residential IP first |
| 8 | Stereo Punks (promoter) | manual / join list | Add manual (redundant if #1 lands) |
| 9 | ma.to venue pages | possible JSON-LD | Probe only |

Other notes: American Cinematheque has a 4th location (Directors Village, event_location=181); per-venue list views `/now-showing/?event_location=<id>&view_type=list` — update that row. ORIGIN (ex-Lot 613) already covered by Eventbrite organizer. Promoter signals (no fetch rows): Minty Boi, Loco Disco, EMX, Factory 93, Rhonda Intl, Into The Woods, Pauz, Incognito, Tunnel, etc. — consider a promoters-boosted list in taste.yaml.

After approval: set `last_discovery: 2026-11-03`.
