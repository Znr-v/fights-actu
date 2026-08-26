import html
import os
import time

import requests


TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

ORG_EMOJI = {
    "UFC": "🥊",
    "PFL": "🥋",
    "GLORY": "🥇",
    "ONE": "🔥",
}

JOURS_FR = [
    "Lundi", "Mardi", "Mercredi", "Jeudi",
    "Vendredi", "Samedi", "Dimanche"
]

MOIS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre"
]


def is_configured():
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def format_date_fr(dt):
    if not dt:
        return ""

    return f"{JOURS_FR[dt.weekday()]} {dt.day} {MOIS_FR[dt.month - 1]} {dt.year}"


def _send(text):
    """Envoie un message Telegram. Ne lève jamais d'exception : une
    erreur Telegram ne doit jamais empêcher l'envoi Discord (et
    inversement)."""

    if not is_configured():
        print("[INFO] Telegram non configuré (secrets absents), ignoré.")
        return

    url = TELEGRAM_API.format(token=TELEGRAM_BOT_TOKEN)

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }

    try:
        response = requests.post(url, json=payload, timeout=20)

        if response.status_code != 200:
            print(
                f"[WARN] Telegram error {response.status_code}: "
                f"{response.text}"
            )

    except Exception as e:
        print(f"[WARN] Telegram exception: {e}")


def build_event_text(event, event_date_fn):

    org = event.get("organization", "")
    emoji = ORG_EMOJI.get(org, "🥊")
    dt = event_date_fn(event)
    name = html.escape(event.get("name", "Événement"))
    url = event.get("url", "")

    if url:
        title_line = f'{emoji} <b>{html.escape(org)}</b> — <a href="{html.escape(url)}">{name}</a>'
    else:
        title_line = f"{emoji} <b>{html.escape(org)}</b> — {name}"

    lines = [title_line]

    main_event = next(
        (f for f in event.get("fights", []) if f.get("main_event")),
        None
    )

    if main_event:
        f1 = html.escape(main_event.get("fighter1", "").strip())
        f2 = html.escape(main_event.get("fighter2", "").strip())

        if f1 and f2:
            lines.append(f"🥊 <b>{f1}</b> 🆚 <b>{f2}</b>")

    if dt:
        lines.append(f"📅 {format_date_fr(dt)}")

    if event.get("location"):
        lines.append(f"📍 {html.escape(event['location'])}")

    return "\n".join(lines)


def send_event_batch(header, events, event_date_fn, delay=0.4):
    """Envoie un message d'en-tête puis un message par événement (comme
    les embeds Discord). `event_date_fn` convertit event['date'] (str)
    en datetime, réutilisée depuis main.py pour rester cohérent."""

    if not is_configured():
        print("[INFO] Telegram non configuré (secrets absents), ignoré.")
        return

    if header:
        _send(header)
        time.sleep(delay)

    for event in events:
        _send(build_event_text(event, event_date_fn))
        time.sleep(delay)
