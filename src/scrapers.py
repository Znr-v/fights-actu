import re
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from dateutil import parser as date_parser


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    )
}

# Wikipedia exige un User-Agent identifiable (avec une URL de contact) et
# bloque en 403 les clients qui enchaînent les requêtes sans pause.
# Voir https://foundation.wikimedia.org/wiki/Policy:User-Agent_policy
WIKIPEDIA_HEADERS = {
    "User-Agent": (
        "fights-actu-bot/1.0 "
        "(https://github.com/Znr-v/fights-actu; "
        "GitHub Actions cron job for a Discord fight-calendar bot)"
    )
}

TIMEOUT = 20


def get_html(url, headers=None, retries=2, backoff=3):
    headers = headers or HEADERS

    for attempt in range(retries + 1):
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=TIMEOUT
            )

            if response.status_code == 403 and attempt < retries:
                print(
                    f"[WARN] {url}: 403, retry dans "
                    f"{backoff}s ({attempt + 1}/{retries})"
                )
                time.sleep(backoff)
                continue

            response.raise_for_status()
            return response.text

        except Exception as e:
            if attempt < retries:
                time.sleep(backoff)
                continue

            print(f"[ERROR] {url}: {e}")
            return None


def clean_text(text):
    if not text:
        return ""

    return re.sub(
        r"\s+",
        " ",
        text.replace("\xa0", " ")
    ).strip()


def parse_date(text):
    if not text:
        return None

    try:
        dt = date_parser.parse(
            text,
            fuzzy=True,
            dayfirst=False
        )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt
    except Exception:
        return None


def make_event(
    organization,
    name,
    date,
    url,
    location="",
    fights=None
):
    return {
        "organization": organization,
        "name": clean_text(name),
        "date": date.isoformat() if date else None,
        "location": clean_text(location),
        "url": url,
        "fights": fights or []
    }


# ============================================================
# UFC
# ============================================================

def scrape_ufc():
    url = "https://www.ufc.com/events"
    html = get_html(url)

    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    events = []

    for block in soup.select(
        "div.c-card-event--result, "
        "article, "
        "div.c-card-event"
    ):
        text = clean_text(block.get_text(" ", strip=True))

        if not text:
            continue

        link = block.find("a", href=True)

        if not link:
            continue

        href = link.get("href", "")

        if not href.startswith("http"):
            href = "https://www.ufc.com" + href

        # Cherche une date dans le bloc
        date_match = re.search(
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
            r"\s+\d{1,2}",
            text,
            re.I
        )

        if not date_match:
            continue

        date = parse_date(date_match.group(0))

        if not date:
            continue

        # On essaye de récupérer le titre
        title = ""

        for selector in [
            "h3",
            "h2",
            ".c-card-event--result__headline",
            ".c-card-event__headline"
        ]:
            node = block.select_one(selector)

            if node:
                title = clean_text(node.get_text(" ", strip=True))
                break

        if not title:
            title = text[:120]

        events.append(
            make_event(
                organization="UFC",
                name=title,
                date=date,
                url=href
            )
        )

    return deduplicate_events(events)


# ============================================================
# GLORY
# ============================================================
#
# glorykickboxing.com/events renders its event list client-side with
# JavaScript: a plain requests.get() only receives the page shell
# (header/footer/newsletter form), never the actual events, so no amount
# of CSS-selector tweaking on that URL can work. Instead we read GLORY's
# own Wikipedia "<year> in Glory" pages, which are static HTML and
# already contain a plain recap table near the top of the page:
#   # | Event Title | Date | Arena | Location
# kept up to date by editors as soon as an event is officially announced.

def _find_table_with_headers(soup, required_keywords):
    """Return the first <table> whose header row contains all the given
    keywords (case-insensitive substring match)."""

    for table in soup.find_all("table"):
        header_row = table.find("tr")

        if not header_row:
            continue

        headers = [
            clean_text(c.get_text(" ", strip=True)).lower()
            for c in header_row.find_all(["th", "td"])
        ]

        if all(
            any(keyword in h for h in headers)
            for keyword in required_keywords
        ):
            return table, headers

    return None, None


def _extract_glory_main_event(soup, event_name):
    """On a GLORY year page, each event has its own '<h2>/<h3>' heading
    (e.g. "Glory 105") followed further down by a "Fight card" table
    (columns: Weight Class | Fighter1 | vs./def. | Fighter2 | Method | ...).
    The first row of that table is the headliner. Returns
    (fighter1, fighter2) or None.
    """

    heading = None

    for h in soup.find_all(["h2", "h3"]):
        if clean_text(h.get_text(" ", strip=True)) == event_name:
            heading = h
            break

    if heading is None:
        return None

    node = heading

    for _ in range(60):
        node = node.find_next(["h2", "h3", "table"])

        if node is None:
            return None

        if node.name in ("h2", "h3"):
            # Reached the next event's heading without finding a card.
            return None

        header_row = node.find("tr")

        if not header_row:
            continue

        headers = [
            clean_text(c.get_text(" ", strip=True)).lower()
            for c in header_row.find_all(["th", "td"])
        ]

        if not any("method" in h for h in headers):
            continue

        data_rows = node.select("tr")[1:]

        if not data_rows:
            return None

        cells = data_rows[0].find_all(["td", "th"])
        texts = [
            clean_text(c.get_text(" ", strip=True))
            for c in cells
        ]

        fighters = [
            t for t in texts[1:4]
            if t and t.lower() not in ("vs.", "vs", "def.", "def")
        ]

        if len(fighters) >= 2:
            return fighters[0], fighters[1]

        return None

    return None


def scrape_glory():
    events = []
    now = datetime.now(timezone.utc)

    # Check the current year's page and next year's, in case upcoming
    # events already have their own page near a year boundary.
    for year in sorted({now.year, now.year + 1}):

        url = f"https://en.wikipedia.org/wiki/{year}_in_Glory"
        html = get_html(url, headers=WIKIPEDIA_HEADERS)

        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")

        table, headers = _find_table_with_headers(
            soup, ["event", "date"]
        )

        if table is None:
            continue

        def col(keyword, default):
            for i, h in enumerate(headers):
                if keyword in h:
                    return i
            return default

        idx_name = col("event", 1)
        idx_date = col("date", 2)
        idx_venue = col("arena", 3)
        idx_location = col("location", 4)

        for row in table.select("tr")[1:]:

            cells = row.find_all(["td", "th"])

            if len(cells) <= max(idx_name, idx_date, idx_venue, idx_location):
                continue

            name = clean_text(cells[idx_name].get_text(" ", strip=True))
            date_text = clean_text(cells[idx_date].get_text(" ", strip=True))
            venue = clean_text(cells[idx_venue].get_text(" ", strip=True))
            location = clean_text(
                cells[idx_location].get_text(" ", strip=True)
            )

            if not name or not date_text:
                continue

            date = parse_date(date_text)

            if not date:
                continue

            fights = []
            main_event = _extract_glory_main_event(soup, name)

            if main_event:
                fights = [{
                    "fighter1": main_event[0],
                    "fighter2": main_event[1],
                    "label": "Main Event",
                    "main_event": True
                }]

            events.append(
                make_event(
                    organization="GLORY",
                    name=name,
                    date=date,
                    url=url,
                    location=location or venue,
                    fights=fights
                )
            )

        time.sleep(1)

    return deduplicate_events(events)


# ============================================================
# ONE CHAMPIONSHIP
# ============================================================
#
# Just like GLORY, onefc.com/events/ is a JavaScript-rendered page with
# no event data in the static HTML. ONE Championship's Wikipedia page
# "List of ONE Championship events" is a plain, regularly-updated
# wikitable with columns # | Event | Date | Venue | Location | ... and
# already includes officially confirmed future events, so we read that
# instead.
#
# That list table has no fighter names though, so for events happening
# soon we make one extra, targeted request to the event's own Wikipedia
# article and pull the main event from its "Background" prose (pattern:
# "... bout between X and Y headlined the event."). We only do this for
# near-term events (not all ~60 events/year) to stay well within
# Wikipedia's rate limits.

ONE_MAIN_EVENT_RE = re.compile(
    r"\bbetween\s+([A-Z][\w.\-' ]+?)\s+and\s+([A-Z][\w.\-' ]+?)\s+"
    r"(?:headlined|served as the main event|"
    r"was (?:scheduled|booked) as the main event)",
    re.I
)

# How many days ahead we bother fetching individual ONE event pages for.
# Should be >= DAYS_AHEAD in main.py so every announced event gets a
# fighter card; kept modest to limit extra Wikipedia requests.
ONE_FETCH_FIGHTERS_WITHIN_DAYS = 35


def _fetch_one_main_event(event_url):
    html = get_html(event_url, headers=WIKIPEDIA_HEADERS)

    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")
    text = clean_text(soup.get_text(" ", strip=True))

    match = ONE_MAIN_EVENT_RE.search(text)

    if not match:
        return None

    return clean_text(match.group(1)), clean_text(match.group(2))


def scrape_one():
    url = "https://en.wikipedia.org/wiki/List_of_ONE_Championship_events"
    html = get_html(url, headers=WIKIPEDIA_HEADERS)

    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    events = []
    now = datetime.now(timezone.utc)

    table = soup.select_one("table.wikitable")

    if not table:
        return []

    header_cells = [
        clean_text(th.get_text(" ", strip=True)).lower()
        for th in table.select_one("tr").find_all(["th", "td"])
    ]

    def col(label, default):
        return header_cells.index(label) if label in header_cells else default

    idx_event = col("event", 1)
    idx_date = col("date", 2)
    idx_venue = col("venue", 3)
    idx_location = col("location", 4)

    rows = table.select("tr")[1:]

    for row in rows:

        cells = row.find_all(["td", "th"])

        if len(cells) <= max(idx_event, idx_date, idx_venue, idx_location):
            continue

        name = clean_text(cells[idx_event].get_text(" ", strip=True))
        date_text = clean_text(cells[idx_date].get_text(" ", strip=True))
        venue = clean_text(cells[idx_venue].get_text(" ", strip=True))
        location = clean_text(cells[idx_location].get_text(" ", strip=True))

        if not name or not date_text or date_text.upper() in ("TBD", "TBA"):
            continue

        date = parse_date(date_text)

        if not date:
            continue

        link = cells[idx_event].find("a", href=True)

        event_url = (
            "https://en.wikipedia.org" + link["href"]
            if link and link["href"].startswith("/wiki/")
            else url
        )

        fights = []
        days_out = (date - now).days

        if event_url != url and 0 <= days_out <= ONE_FETCH_FIGHTERS_WITHIN_DAYS:
            try:
                time.sleep(1)
                main_event = _fetch_one_main_event(event_url)

                if main_event:
                    fights = [{
                        "fighter1": main_event[0],
                        "fighter2": main_event[1],
                        "label": "Main Event",
                        "main_event": True
                    }]

            except Exception as e:
                print(f"[WARN] Main event ONE '{name}': {e}")

        events.append(
            make_event(
                organization="ONE",
                name=name,
                date=date,
                url=event_url,
                location=location or venue,
                fights=fights
            )
        )

    return deduplicate_events(events)


# ============================================================
# PFL
# ============================================================

def scrape_pfl():
    url = "https://pflmma.com/events"
    html = get_html(url)

    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    events = []

    for link in soup.find_all("a", href=True):

        href = link.get("href", "")

        if "/events" not in href:
            continue

        if not href.startswith("http"):
            href = "https://pflmma.com" + href

        parent = link

        for _ in range(5):
            if parent.parent:
                parent = parent.parent

        text = clean_text(
            parent.get_text(" ", strip=True)
        )

        if len(text) < 5:
            continue

        # Formats fréquents :
        # Fri, Oct 2
        # Sat, Oct 10
        date_match = re.search(
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
            r"\s+\d{1,2}",
            text,
            re.I
        )

        if not date_match:
            continue

        date = parse_date(
            f"{date_match.group(0)} {datetime.now().year}"
        )

        if not date:
            continue

        title = clean_text(
            link.get_text(" ", strip=True)
        )

        if not title:
            continue

        events.append(
            make_event(
                organization="PFL",
                name=title,
                date=date,
                url=href
            )
        )

    return deduplicate_events(events)


# ============================================================
# UTILITAIRES
# ============================================================

def deduplicate_events(events):
    seen = set()
    result = []

    for event in events:

        key = (
            event["organization"],
            event["name"],
            event["date"]
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(event)

    return result


def get_all_events():
    all_events = []

    scrapers = [
        ("UFC", scrape_ufc),
        ("GLORY", scrape_glory),
        ("ONE", scrape_one),
        ("PFL", scrape_pfl),
    ]

    for name, scraper in scrapers:

        print(f"[INFO] Scraping {name}...")

        try:
            time.sleep(1)  # évite d'enchaîner les requêtes trop vite
            events = scraper()

            print(
                f"[INFO] {name}: "
                f"{len(events)} événements trouvés"
            )

            all_events.extend(events)

        except Exception as e:
            print(
                f"[ERROR] Scraper {name}: {e}"
            )

    return deduplicate_events(all_events)
