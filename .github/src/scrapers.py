import re
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

TIMEOUT = 20


def get_html(url):
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT
        )
        response.raise_for_status()
        return response.text
    except Exception as e:
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

def scrape_glory():
    url = "https://glorykickboxing.com/events"
    html = get_html(url)

    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    events = []

    for link in soup.find_all("a", href=True):

        href = link.get("href", "")

        if "/events/" not in href:
            continue

        if not href.startswith("http"):
            href = "https://glorykickboxing.com" + href

        text = clean_text(link.get_text(" ", strip=True))

        if not text:
            continue

        # Récupère le bloc parent pour obtenir date/localisation
        parent = link

        for _ in range(4):
            if parent.parent:
                parent = parent.parent

        parent_text = clean_text(
            parent.get_text(" ", strip=True)
        )

        date_match = re.search(
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
            r"\s+\d{1,2}",
            parent_text,
            re.I
        )

        if not date_match:
            continue

        date = parse_date(date_match.group(0))

        if not date:
            continue

        events.append(
            make_event(
                organization="GLORY",
                name=text,
                date=date,
                url=href
            )
        )

    return deduplicate_events(events)


# ============================================================
# ONE CHAMPIONSHIP
# ============================================================

def scrape_one():
    url = "https://www.onefc.com/events/"
    html = get_html(url)

    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    events = []

    for link in soup.find_all("a", href=True):

        href = link.get("href", "")

        if "/events/" not in href:
            continue

        if not href.startswith("http"):
            href = "https://www.onefc.com" + href

        parent = link

        for _ in range(5):
            if parent.parent:
                parent = parent.parent

        text = clean_text(
            parent.get_text(" ", strip=True)
        )

        if len(text) < 5:
            continue

        # Recherche une date complète
        date_match = re.search(
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
            r"\s+\d{1,2}(?:,\s*|\s+)\d{4}",
            text,
            re.I
        )

        if not date_match:
            continue

        date = parse_date(date_match.group(0))

        if not date:
            continue

        title = clean_text(
            link.get_text(" ", strip=True)
        )

        if not title:
            title = text[:150]

        events.append(
            make_event(
                organization="ONE",
                name=title,
                date=date,
                url=href
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