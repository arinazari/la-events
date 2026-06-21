#!/usr/bin/env python3
"""
One-shot script to inject webfetch venue events + editorial signals into catalog.json.
Run AFTER run_digest.py, BEFORE --no-fetch re-score.
"""
import json, re
from datetime import date, timedelta
from pathlib import Path

CATALOG_PATH = Path("data/catalog.json")
TODAY = date(2026, 6, 21)
WINDOW_END = TODAY + timedelta(days=120)

def load_catalog():
    return json.loads(CATALOG_PATH.read_text())

def save_catalog(events):
    CATALOG_PATH.write_text(json.dumps(events, indent=2, default=str))

def make_id(source, title, date_str):
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")[:40]
    return f"{source}:{date_str}:{slug}"

def normalize(title, artist, date_str, time_str, price, url, source, venue, venue_city="Los Angeles"):
    return {
        "id": make_id(source, title, date_str),
        "title": title,
        "headliner": artist or title,
        "date": date_str,
        "start_time": time_str or "",
        "price": price or "",
        "ticket_url": url or "",
        "venue": venue,
        "city": venue_city,
        "source": source,
        "method": "webfetch",
        "tags": [],
    }

def in_window(date_str):
    try:
        d = date.fromisoformat(date_str)
        return TODAY <= d <= WINDOW_END
    except Exception:
        return False

def existing_ids(catalog):
    return {e.get("id") for e in catalog}

def fuzzy_match(catalog, title, date_str):
    """Return existing record if title+date roughly match."""
    t = (title or "").lower()
    for e in catalog:
        if e.get("date") == date_str:
            et = (e.get("title") or "").lower()
            if t and et and (t in et or et in t or t[:20] == et[:20]):
                return e
    return None

# ─────────────────────────────────────────────────────────────────────────────
# WEBFETCH DATA
# ─────────────────────────────────────────────────────────────────────────────

MCCABES = [
    {"title": "Joel Rafael / Citrus Sisters", "date": "2026-06-21", "time": "8pm", "url": "https://www.mccabes.com/product/joel-rafael-citrus-sisters/"},
    {"title": "Peter Stampfel", "date": "2026-06-27", "time": "8pm", "url": "https://www.mccabes.com/product/peter-stampfel/"},
    {"title": "Pi Jacobs and Babilonia (Celia Chavez) & Friends", "date": "2026-06-28", "time": "8pm", "url": "https://www.mccabes.com/product/pi-jacobs-and-babilonia/"},
    {"title": "Dave Alvin & Jimmie Dale Gilmore (Friday Show)", "date": "2026-07-10", "time": "8pm", "url": "https://www.mccabes.com/product/dave-alvin-jimmie-dale-gilmore-friday-show/"},
    {"title": "Dave Alvin & Jimmie Dale Gilmore (Saturday Show)", "date": "2026-07-11", "time": "8pm", "url": "https://www.mccabes.com/product/dave-alvin-jimmie-dale-gilmore-saturday-show/"},
    {"title": "In the Big Round", "date": "2026-07-19", "time": "8pm", "url": "https://www.mccabes.com/product/in-the-big-round/"},
    {"title": "El Rayo-X", "date": "2026-07-24", "time": "8pm", "url": "https://www.mccabes.com/product/el-rayo-x/"},
    {"title": "Tom Rush", "date": "2026-07-25", "time": "8pm", "url": "https://www.mccabes.com/product/tom-rush/"},
    {"title": "Teddy Thompson", "date": "2026-07-26", "time": "8pm", "url": "https://www.mccabes.com/product/teddy-thompson/"},
    {"title": "Andy McKee", "date": "2026-07-31", "time": "8pm", "url": "https://www.mccabes.com/product/andy-mckee/"},
    {"title": "Abby Posner & The Big Fall", "date": "2026-08-15", "time": "8pm", "url": "https://www.mccabes.com/product/abby-posner/"},
    {"title": "The John Stewart Band", "date": "2026-08-16", "time": "8pm", "url": "https://www.mccabes.com/product/the-john-stewart-band/"},
    {"title": "Amy LaVere featuring Will Sexton", "date": "2026-08-29", "time": "8pm", "url": "https://www.mccabes.com/product/amy-lavere-featuring-will-sexton/"},
    {"title": "Jim Keller w/ David Hidalgo, Mitchell Froom, Bob Glaub, Pete Thomas", "date": "2026-08-30", "time": "8pm", "url": "https://www.mccabes.com/product/jim-keller/"},
    {"title": "I See Hawks in L.A. w/ Rick Shea and Tony Gilkyson", "date": "2026-09-19", "time": "8pm", "url": "https://www.mccabes.com/product/i-see-hawks-in-l-a/"},
    {"title": "Deke Dickerson & Friends", "date": "2026-09-27", "time": "8pm", "url": "https://www.mccabes.com/product/deke-dickerson/"},
    {"title": "Val McCallum", "date": "2026-09-29", "time": "8pm", "url": "https://www.mccabes.com/product/val-mccallum-2/"},
    {"title": "Kim Richey", "date": "2026-10-16", "time": "8pm", "url": "https://www.mccabes.com/product/kim-richey/"},
    {"title": "Laurence Juber", "date": "2026-10-17", "time": "8pm", "url": "https://www.mccabes.com/product/laurence-juber/"},
    {"title": "Andrew Duhon", "date": "2026-11-07", "time": "8pm", "url": "https://www.mccabes.com/product/andrew-duhon/"},
]

HARVELLES = [
    {"title": "ALL-STAR JAM SESSION BENEFIT", "date": "2026-07-01", "time": "9:30 PM", "url": "https://santamonica.harvelles.com/events/135797"},
    {"title": "THE NO CHASERS", "date": "2026-07-02", "time": "9:30 PM", "url": "https://santamonica.harvelles.com/events/135802"},
    {"title": "VERONICA DUB", "date": "2026-07-04", "time": "9:30 PM", "url": "https://santamonica.harvelles.com/events/136355"},
    {"title": "Alligator Beach New Orleans Funk Party", "date": "2026-07-06", "time": "9:30 PM", "url": "https://santamonica.harvelles.com/events/136858"},
    {"title": "THE TOLEDO SHOW", "date": "2026-07-07", "time": "9:30 PM", "url": "https://santamonica.harvelles.com/events/135793"},
    {"title": "ALL-STAR JAM SESSION BENEFIT", "date": "2026-07-08", "time": "9:30 PM", "url": "https://santamonica.harvelles.com/events/135798"},
    {"title": "THE NO CHASERS", "date": "2026-07-09", "time": "9:30 PM", "url": "https://santamonica.harvelles.com/events/135803"},
    {"title": "WESTERN REVENGE", "date": "2026-07-12", "time": "9:30 PM", "url": "https://santamonica.harvelles.com/events/137387"},
    {"title": "The Scorch Sisters & Friends All Female Blues & Soul Revue", "date": "2026-07-13", "time": "9:30 PM", "url": "https://santamonica.harvelles.com/events/137764"},
    {"title": "THE TOLEDO SHOW", "date": "2026-07-14", "time": "9:30 PM", "url": "https://santamonica.harvelles.com/events/135794"},
    {"title": "SUMMER ROCK JAM", "date": "2026-07-18", "time": "9:00 PM", "url": "https://santamonica.harvelles.com/events/136121"},
    {"title": "SMOKESTACK LIGHTNING", "date": "2026-07-20", "time": "9:30 PM", "url": "https://santamonica.harvelles.com/events/137390"},
    {"title": "KELLY MONEYMAKER & LAST HOUSE", "date": "2026-07-25", "time": "9:00 PM", "url": "https://santamonica.harvelles.com/shows/367815"},
    {"title": "WESTERN REVENGE", "date": "2026-07-26", "time": "9:30 PM", "url": "https://santamonica.harvelles.com/shows/372838"},
    {"title": "The Boneshakers", "date": "2026-07-27", "time": "9:30 PM", "url": "https://santamonica.harvelles.com/shows/362607"},
]

# Dresden recurring — compute next 6 weeks of instances
DRESDEN_RECURRING = []
def add_dresden_recurrings():
    # Wed: Luke Strand & Friends 8:30pm
    # Thu: Billy T and the Fam 8:30pm
    # Fri 1st&3rd: Funky Fridays 9:15pm, 2nd&4th: A Swingin Jazz Affair 9:15pm
    # Sat: David Moscoe & Company 9:15pm
    # Sun 1st&3rd: Lisa Crawley Trio 7:30pm, 2nd: Wes Hutchinson Duo 7:30pm
    d = TODAY
    end = TODAY + timedelta(days=42)
    fri_count_by_month = {}
    sun_count_by_month = {}
    while d <= end:
        ym = (d.year, d.month)
        ds = d.isoformat()
        if d.weekday() == 2:  # Wed
            DRESDEN_RECURRING.append({"title": "Luke Strand & Friends", "date": ds, "time": "8:30 PM", "url": "https://www.thedresden.com/events/"})
        elif d.weekday() == 3:  # Thu
            DRESDEN_RECURRING.append({"title": "Billy T and the Fam", "date": ds, "time": "8:30 PM", "url": "https://www.thedresden.com/events/"})
        elif d.weekday() == 4:  # Fri
            fri_count_by_month[ym] = fri_count_by_month.get(ym, 0) + 1
            n = fri_count_by_month[ym]
            if n in (1, 3):
                DRESDEN_RECURRING.append({"title": "Funky Fridays @ The Dresden", "date": ds, "time": "9:15 PM", "url": "https://www.thedresden.com/events/"})
            else:
                DRESDEN_RECURRING.append({"title": "A Swingin Jazz Affair @ The Dresden", "date": ds, "time": "9:15 PM", "url": "https://www.thedresden.com/events/"})
        elif d.weekday() == 5:  # Sat
            DRESDEN_RECURRING.append({"title": "David Moscoe & Company @ The Dresden", "date": ds, "time": "9:15 PM", "url": "https://www.thedresden.com/events/"})
        elif d.weekday() == 6:  # Sun
            sun_count_by_month[ym] = sun_count_by_month.get(ym, 0) + 1
            n = sun_count_by_month[ym]
            if n in (1, 3):
                DRESDEN_RECURRING.append({"title": "Lisa Crawley Trio @ The Dresden", "date": ds, "time": "7:30 PM", "url": "https://www.thedresden.com/events/"})
            elif n == 2:
                DRESDEN_RECURRING.append({"title": "Wes Hutchinson Duo @ The Dresden", "date": ds, "time": "7:30 PM", "url": "https://www.thedresden.com/events/"})
        d += timedelta(days=1)

add_dresden_recurrings()

# Sam First jazz — fix year to 2026
SAM_FIRST = [
    {"title": "Taylor Eigsti: Solo Piano", "date": "2026-06-21", "time": "7:30 PM", "url": "https://www.samfirstbar.com/events/taylor-eigsti-solo-piano"},
    {"title": "Tuesday Happenings: Hosted by Devin Daniels", "date": "2026-06-23", "time": "7:30 PM", "url": "https://www.samfirstbar.com/events/tuesday-happenings-hosted-by-devin-daniels-13"},
    {"title": "Mauricio Morales Quartet", "date": "2026-06-24", "time": "7:30 PM", "url": "https://www.samfirstbar.com/events/mauricio-morales-quartet-with-devin-daniels-edmar-colon-adam-hersh-nate-friedman"},
    {"title": "Jaz Sawyer Quartet: Music of Coltrane", "date": "2026-06-25", "time": "7:30 PM", "url": "https://www.samfirstbar.com/events/jaz-sawyer-quartet-music-of-coltrane-with-teodross-avery-javier-santiago-luca-alemanno"},
    {"title": "Yotam Silberstein Trio", "date": "2026-06-26", "time": "7:30 PM", "url": "https://www.samfirstbar.com/events/yotam-silberstein-trio-with-john-clayton-roy-mccurdy"},
    {"title": "Yotam Silberstein Trio", "date": "2026-06-27", "time": "7:30 PM", "url": "https://www.samfirstbar.com/events/yotam-silberstein-trio-with-john-clayton-roy-mccurdy-1"},
    {"title": "Tuesday Happenings: Host TBA", "date": "2026-06-30", "time": "7:30 PM", "url": "https://www.samfirstbar.com/events/tuesday-happenings-host-tba-27"},
    {"title": "Mark Valdes and Joey Curreri's Tabula Rasa", "date": "2026-07-01", "time": "7:30 PM", "url": "https://www.samfirstbar.com/events/mark-valdes-and-joey-curreris-tabula-rasa-with-devin-daniels-jonathan-paik-dario-bizio"},
    {"title": "Logan Kane Kickflip Quartet", "date": "2026-07-02", "time": "7:30 PM", "url": "https://www.samfirstbar.com/events/logan-kane-kickflip-quartet-with-roni-kaspi-jon-hatamiya-luca-mendoza"},
    {"title": "Kathleen Grace & Larry Koonse: The Art of the Duo", "date": "2026-07-03", "time": "7:30 PM", "url": "https://www.samfirstbar.com/events/kathleen-grace-larry-koonse-the-art-of-the-duo"},
    {"title": "Daniel Rotem Quintet", "date": "2026-07-04", "time": "7:30 PM", "url": "https://www.samfirstbar.com/events/daniel-rotem-quintet-with-jeff-parker-joshua-white-darek-oles-mark-ferber"},
    {"title": "Ethan Chilton's Dream Machine", "date": "2026-07-08", "time": "7:30 PM", "url": "https://www.samfirstbar.com/events/ethan-chiltons-dream-machine-with-isaiah-harwood-dario-bizio-gavin-harris"},
    {"title": "Emma Dayhuff Sextet", "date": "2026-07-09", "time": "7:30 PM", "url": "https://www.samfirstbar.com/events/emma-dayhuff-sextet-with-lolokamill-devin-daniels-andrew-renfroe-luca-mendoza-jonathan-pinson"},
    {"title": "Euman/Renfroe/Carroll Trio Feat. Devin Daniels", "date": "2026-07-11", "time": "7:30 PM", "url": "https://www.samfirstbar.com/events/euman-renfroe-carroll-trio-feat-devin-daniels"},
    {"title": "Tuesday Happenings: Hosted by Devin Daniels", "date": "2026-07-14", "time": "7:30 PM", "url": "https://www.samfirstbar.com/events/tuesday-happenings-hosted-by-devin-daniels-15"},
    {"title": "Adi Meyerson & Dark Matter", "date": "2026-07-29", "time": "7:30 PM", "url": "https://www.samfirstbar.com/events/adi-meyerson-dark-matter-with-nicole-mccabe-julien-knowles-anthony-fung"},
]

VENICE_WEST = [
    {"title": "Burritos - Tribute to Sublime", "date": "2026-06-24", "time": "8:00 PM", "url": "https://www.tixr.com/groups/thevenicewest/events/burritos-tribute-to-sublime-192780"},
    {"title": "Nikka Costa w/ Tyron Taylor", "date": "2026-06-27", "time": "8:00 PM", "url": "https://www.tixr.com/groups/thevenicewest/events/nikka-costa-w-tyron-taylor-181300"},
    {"title": "Salsa & Vinyls Brunch", "date": "2026-06-28", "time": "11:00 AM", "url": "https://www.tixr.com/groups/thevenicewest/events/salsa-vinyls-brunch-191457"},
    {"title": "Nikka Costa w/ Tyron Taylor", "date": "2026-06-28", "time": "8:00 PM", "url": "https://www.tixr.com/groups/thevenicewest/events/nikka-costa-w-tyron-taylor-189391"},
    {"title": "The Laurel Canyon Band", "date": "2026-06-30", "time": "8:00 PM", "url": "https://www.tixr.com/groups/thevenicewest/events/the-laurel-canyon-band-192625"},
    {"title": "The Music of The Doors with Peace Frog", "date": "2026-07-03", "time": "8:00 PM", "url": "https://www.tixr.com/groups/thevenicewest/events/the-music-of-the-doors-with-peace-frog-179319"},
    {"title": "Swamp Dogg w/ Ben Vaughn Ensemble & Special Guest DJ Eli Paperboy Reed", "date": "2026-07-11", "time": "8:00 PM", "url": "https://www.tixr.com/groups/thevenicewest/events/swamp-dogg-w-ben-vaughn-ensemble-special-guest-dj-eli-paperboy-reed-176543"},
    {"title": "DISCO NIGHT w/ Bad News PB&Yam", "date": "2026-07-11", "time": "10:30 PM", "url": "https://www.tixr.com/groups/thevenicewest/events/disco-night-w-bad-news-pb-yam-185276"},
    {"title": "Tito Puente Jr. w/ Maria Sanchez & The Midnight Groove", "date": "2026-07-19", "time": "8:00 PM", "url": "https://www.tixr.com/groups/thevenicewest/events/tito-puente-jr-w-maria-sanchez-the-midnight-groove-175159"},
    {"title": "Monophonics - Performing IT'S ONLY US in its Entirety w/ KENDRA MORRIS", "date": "2026-07-24", "time": "8:00 PM", "url": "https://www.tixr.com/groups/thevenicewest/events/monophonics-performing-their-2020-album-it-s-only-us-in-its-entirety-w-kendra-morris-178910"},
    {"title": "Tommy Newport", "date": "2026-08-06", "time": "8:00 PM", "url": "https://www.tixr.com/groups/thevenicewest/events/tommy-newport-187959"},
    {"title": "Start Making Sense - A Tribute to The Talking Heads", "date": "2026-08-07", "time": "8:00 PM", "url": "https://www.tixr.com/groups/thevenicewest/events/start-making-sense-a-tribute-to-the-talking-heads-168454"},
    {"title": "Black Joe Lewis", "date": "2026-08-18", "time": "8:00 PM", "url": "https://www.tixr.com/groups/thevenicewest/events/black-joe-lewis-184075"},
    {"title": "La Luz", "date": "2026-08-29", "time": "8:00 PM", "url": "https://www.tixr.com/groups/thevenicewest/events/la-luz-186907"},
    {"title": "Black Uhuru", "date": "2026-09-06", "time": "8:00 PM", "url": "https://www.tixr.com/groups/thevenicewest/events/black-uhuru-184204"},
    {"title": "Dengue Fever", "date": "2026-12-12", "time": "8:00 PM", "url": "https://www.tixr.com/groups/thevenicewest/events/dengue-fever-183333"},
]

# Editorial boosts from DiscoverLA — these events very likely already in catalog
# We add editorial_mentions to matched records
EDITORIAL_SIGNALS = [
    {"title": "Beautiful Swimmers", "date": "2026-06-20", "mention": "DiscoverLA weekend pick"},
    {"title": "Midnight Lovers", "date": "2026-06-20", "mention": "DiscoverLA weekend pick"},
    {"title": "KCRW Summer Nights", "date": "2026-06-20", "mention": "DiscoverLA/KCRW pick"},
    {"title": "Nicole Moudaber", "date": "2026-06-20", "mention": "DiscoverLA weekend pick"},
    {"title": "Hot Since 82", "date": "2026-06-21", "mention": "DiscoverLA weekend pick"},
    {"title": "Chris Lake", "date": "2026-06-20", "mention": "DiscoverLA weekend pick"},
    {"title": "Homage 10 Year Anniversary", "date": "2026-06-20", "mention": "DiscoverLA weekend pick"},
]

VENUE_MAP = {
    "mccabes": ("McCabe's Guitar Shop", "Santa Monica"),
    "harvelles": ("Harvelle's", "Santa Monica"),
    "dresden": ("The Dresden", "Los Feliz"),
    "sam_first": ("Sam First", "Westchester"),
    "venice_west": ("The Venice West", "Venice"),
}

def main():
    catalog = load_catalog()
    ids = existing_ids(catalog)
    added = 0
    skipped = 0

    batches = [
        ("mccabes", MCCABES),
        ("harvelles", HARVELLES),
        ("dresden", DRESDEN_RECURRING),
        ("sam_first", SAM_FIRST),
        ("venice_west", VENICE_WEST),
    ]

    for source_key, events in batches:
        venue, city = VENUE_MAP[source_key]
        for e in events:
            date_str = e["date"]
            if not in_window(date_str):
                continue
            rec = normalize(
                title=e["title"],
                artist=e.get("artist", e["title"]),
                date_str=date_str,
                time_str=e.get("time"),
                price=e.get("price"),
                url=e.get("url"),
                source=source_key,
                venue=venue,
                venue_city=city,
            )
            eid = rec["id"]
            # Skip if exact id exists
            if eid in ids:
                skipped += 1
                continue
            # Skip if fuzzy match exists
            if fuzzy_match(catalog, e["title"], date_str):
                skipped += 1
                continue
            catalog.append(rec)
            ids.add(eid)
            added += 1

    # Apply editorial signals to existing records
    boosted = 0
    for sig in EDITORIAL_SIGNALS:
        for e in catalog:
            if e.get("date") == sig["date"]:
                t = (e.get("title") or "").lower()
                st = sig["title"].lower()
                if st in t or t.startswith(st[:12]):
                    mentions = e.get("editorial_mentions", [])
                    if sig["mention"] not in mentions:
                        mentions.append(sig["mention"])
                        e["editorial_mentions"] = mentions
                        boosted += 1
                    break

    save_catalog(catalog)
    print(f"inject_webfetch: +{added} events added, {skipped} skipped (fuzzy dup), {boosted} editorial boosts applied")
    print(f"catalog total: {len(catalog)} events")

if __name__ == "__main__":
    main()
