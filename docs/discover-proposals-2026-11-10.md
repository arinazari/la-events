# Discover proposals — 2026-11-10 (nothing applied to sources.yaml; awaiting approval)

Auto-applied (allowed): Eventbrite `--scan-catalog` added 2 organizers (Jungle Hollywood, Subphonic Events).
Rotation this week: comedy, rep cinema, jazz/listening rooms, LA newsletters, 2026 openings.

## Carried from 11-03, now verified with `fetch_dice.py`
| Source | Method | Result | Rec |
|---|---|---|---|
| Kiss Kiss Bang Bang (Mid-Wilshire) | DICE `kiss-kiss-bang-bang-la-w79p` | 3 events (Paradisco 11/21, 12/12; Club Joon 11/28) | Add. Mostly already in via RA/19hz; adds DICE ticket links + Club Joon |
| Los Globos (Silver Lake) | DICE `los-globos-a6w7` | 4 events (MAURICE 11/21, Wasted 11/27–28, Koastle 12/5) | Add. Partly covered by 19hz; adds MAURICE/Wasted |
| Club Tee Gee (Atwater) | no DICE venue page found | — | Drop the DICE idea; RA already catches its club nights |

## New candidates
| # | Source | Category | Method | Sample | Rec |
|---|---|---|---|---|---|
| 1 | Camber "Things to Do in LA" | newsletter (signal) | rss `https://camberplaces.substack.com/feed` (verified, full-text) | Nov 10–16 issue, by day | Add as editorial signal |
| 2 | The Upstairs Comedy Club (DTLA, opened 5/2026) | comedy | webfetch `https://theupstairsla.com/` (Tixr 403s) | Mark Hayes & Friends 11/11–13 | Add (webfetch); not in catalog at all |
| 3 | Laugh Factory Hollywood | comedy | webfetch `https://www.laughfactory.com/clubs/hollywood` | Neon Moon 11/11, Throwdown Thursdays 11/12 | Add (webfetch); 0 catalog rows today |
| 4 | BLK Events LA "The RoundUp" | newsletter (signal) | rss `https://blackeventsla.substack.com/feed` | Nov calendar: Leimert First Saturdays, Dance Theatre of Harlem @ Soraya | Optional signal; partial taste fit |
| 5 | Hollywood Improv | comedy | webfetch `https://improv.com/hollywood/calendar/` | Comedy Spotlight 11/11 | Hold. TM brings in only Brea, not Hollywood, so this is a real gap if you want the comedy lane |
| 6 | Gardena Cinema | rep cinema | Eventbrite organizer 31976506589 | Child's Play 3 35th, 12/13 | Hold (2 events, low fit) |

Dropped after catalog check: Comedy Chateau (20 rows already via TM), Blue Note LA (via TM),
LA Insider (art-skewed), Secret Movie Club (no dates after Aug).

Housekeeping: World Stage row URL may be stale (moved venues per DownBeat 1/2026).
After approval: set `last_discovery: 2026-11-10` (still 2026-10-06; 11-03 batch also never applied).
