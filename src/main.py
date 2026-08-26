import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from scrapers import get_all_events


DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK")
DAYS_AHEAD = int(os.environ.get("DAYS_AHEAD", "30"))

DATA_FILE = Path("data/sent.json")


# ============================================================
# DATABASE
# ============================================================

def load_sent():
    default = {"events": [], "reminded": [], "last_daily_reminder": None}

    if not DATA_FILE.exists():
        return default

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        for key, value in default.items():
            data.setdefault(key, value)

        return data
    except Exception:
        return default


def save_sent(data):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


def event_id(event):
    return "|".join([
        event.get("organization", ""),
        event.get("name", ""),
        event.get("date", "")
    ])


def event_date(event):
    try:
        dt = datetime.fromisoformat(event["date"])

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt
    except Exception:
        return None


def is_today(event, now):
    dt = event_date(event)
    return dt is not None and dt.date() == now.date()


# ============================================================
# FORMAT / EMBEDS
# ============================================================

ORG_EMOJI = {
    "UFC": "🥊",
    "PFL": "🥋",
    "GLORY": "🥇",
    "ONE": "🔥",
}

# Couleurs proches de l'identité visuelle de chaque organisation
ORG_COLOR = {
    "UFC": 0xD20A0A,
    "PFL": 0x1479CE,
    "GLORY": 0xF5C518,
    "ONE": 0xFF4500,
}

DEFAULT_COLOR = 0x2F3136


def discord_ts(dt, style="D"):
    """Timestamp dynamique Discord (s'affiche selon la langue/fuseau de
    chaque utilisateur). style: D = date longue, R = relatif ("dans 3
    jours")."""

    if not dt:
        return ""

    return f"<t:{int(dt.timestamp())}:{style}>"


def build_event_embed(event):

    org = event.get("organization", "")
    emoji = ORG_EMOJI.get(org, "🥊")
    color = ORG_COLOR.get(org, DEFAULT_COLOR)
    dt = event_date(event)

    main_event = next(
        (f for f in event.get("fights", []) if f.get("main_event")),
        None
    )

    description = None

    if main_event:
        f1 = main_event.get("fighter1", "").strip()
        f2 = main_event.get("fighter2", "").strip()

        if f1 and f2:
            description = f"🥊 **{f1}**  🆚  **{f2}**"

    fields = []

    if dt:
        fields.append({
            "name": "📅 Date",
            "value": f"{discord_ts(dt, 'D')}\n{discord_ts(dt, 'R')}",
            "inline": True
        })

    if event.get("location"):
        fields.append({
            "name": "📍 Lieu",
            "value": event["location"],
            "inline": True
        })

    embed = {
        "author": {"name": f"{emoji}  {org}"},
        "title": event.get("name", "Événement"),
        "url": event.get("url") or None,
        "description": description,
        "color": color,
        "fields": fields,
        "footer": {"text": "Fight Calendar"}
    }

    return {k: v for k, v in embed.items() if v not in (None, [], "")}


def chunk(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


# ============================================================
# DISCORD
# ============================================================

def send_discord(content=None, embeds=None, mention_everyone=True):

    if not DISCORD_WEBHOOK:
        raise RuntimeError(
            "DISCORD_WEBHOOK n'est pas configuré."
        )

    text = content or ""

    if mention_everyone:
        text = "@everyone" + (f"\n{text}" if text else "")
        allowed_mentions = {"parse": ["everyone"]}
    else:
        allowed_mentions = {"parse": []}

    payload = {
        "username": "Fight Calendar",
        "allowed_mentions": allowed_mentions
    }

    if text:
        payload["content"] = text

    if embeds:
        payload["embeds"] = embeds[:10]

    response = requests.post(
        DISCORD_WEBHOOK,
        json=payload,
        timeout=20
    )

    if response.status_code not in (200, 204):
        raise RuntimeError(
            f"Discord error {response.status_code}: "
            f"{response.text}"
        )


def send_event_batch(content, events, mention_everyone=True):
    """Envoie une liste d'événements sous forme d'embeds, en respectant
    la limite Discord de 10 embeds par message (un seul message si
    <= 10 événements, sinon plusieurs messages à la suite)."""

    embed_batches = list(
        chunk([build_event_embed(e) for e in events], 10)
    )

    for i, batch in enumerate(embed_batches):
        send_discord(
            content=content if i == 0 else None,
            embeds=batch,
            mention_everyone=mention_everyone if i == 0 else False
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print("================================")
    print("FIGHT CALENDAR V2")
    print("================================")

    now = datetime.now(timezone.utc)
    today_str = now.date().isoformat()

    limit = now + timedelta(days=DAYS_AHEAD)

    events = get_all_events()

    print(f"[INFO] {len(events)} événements récupérés.")

    upcoming = []

    for event in events:

        dt = event_date(event)

        if dt is None:
            continue

        if now <= dt <= limit:
            upcoming.append(event)

    upcoming.sort(key=lambda x: x["date"])

    print(f"[INFO] {len(upcoming)} événements à venir.")

    if not upcoming:
        print("[INFO] Aucun événement.")
        return

    database = load_sent()

    sent = set(database.get("events", []))
    reminded = set(database.get("reminded", []))
    last_daily_reminder = database.get("last_daily_reminder")

    did_something = False

    # 1) Annonce des nouveaux événements découverts
    new_events = [
        event for event in upcoming
        if event_id(event) not in sent
    ]

    print(f"[INFO] {len(new_events)} nouveaux événements.")

    if new_events:
        n = len(new_events)
        label = "événement" if n == 1 else "événements"

        send_event_batch(
            content=f"🆕 **{n} nouveau{'x' if n > 1 else ''} {label} annoncé{'s' if n > 1 else ''} !**",
            events=new_events,
            mention_everyone=True
        )

        for event in new_events:
            sent.add(event_id(event))

        did_something = True

    # 2) Rappel quotidien : le combat le plus proche (une fois par jour)
    nearest = upcoming[0]
    nearest_already_announced = event_id(nearest) in {
        event_id(e) for e in new_events
    }

    if last_daily_reminder != today_str and not nearest_already_announced:

        send_event_batch(
            content="📌 **Prochain combat à venir**",
            events=[nearest],
            mention_everyone=True
        )

        did_something = True

    if last_daily_reminder != today_str:
        last_daily_reminder = today_str

    # 3) Rappel "c'est aujourd'hui" pour les événements du jour
    today_events = [
        event for event in upcoming
        if is_today(event, now) and event_id(event) not in reminded
    ]

    print(f"[INFO] {len(today_events)} événement(s) aujourd'hui à rappeler.")

    if today_events:

        send_event_batch(
            content="⏰ **Ça se passe aujourd'hui !**",
            events=today_events,
            mention_everyone=True
        )

        for event in today_events:
            reminded.add(event_id(event))

        did_something = True

    if not did_something:
        print("[INFO] Rien de nouveau, rien à rappeler aujourd'hui.")
        return

    database["events"] = list(sent)[-500:]
    database["reminded"] = list(reminded)[-500:]
    database["last_daily_reminder"] = last_daily_reminder

    save_sent(database)

    print("[OK] Discord envoyé.")


if __name__ == "__main__":
    main()
