import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from scrapers import get_all_events


DISCORD_WEBHOOK = os.environ.get(
    "DISCORD_WEBHOOK"
)

DATA_FILE = Path("data/sent.json")

DAYS_AHEAD = int(
    os.environ.get("DAYS_AHEAD", "30")
)


def load_sent():
    if not DATA_FILE.exists():
        return {
            "events": []
        }

    try:
        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            return json.load(f)

    except Exception:
        return {
            "events": []
        }


def save_sent(data):
    DATA_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        DATA_FILE,
        "w",
        encoding="utf-8"
    ) as f:
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


def format_date(date_string):
    dt = datetime.fromisoformat(
        date_string
    )

    # UTC -> heure française approximative.
    # Pour les dates sans heure précise, cela ne change pas le jour.
    dt = dt.astimezone()

    return dt.strftime("%d/%m/%Y")


def emoji(org):
    return {
        "UFC": "🥊",
        "PFL": "🥋",
        "GLORY": "🥊",
        "ONE": "🔥"
    }.get(org, "🥊")


def build_message(events):
    lines = []

    lines.append(
        "🔥 **PROCHAINS COMBATS — MMA & KICKBOXING**"
    )

    lines.append(
        "━━━━━━━━━━━━━━━━━━━━"
    )

    grouped = {}

    for event in events:
        org = event["organization"]

        if org not in grouped:
            grouped[org] = []

        grouped[org].append(event)

    order = [
        "UFC",
        "PFL",
        "ONE",
        "GLORY"
    ]

    for org in order:

        if org not in grouped:
            continue

        lines.append("")
        lines.append(
            f"{emoji(org)} **{org}**"
        )

        sorted_events = sorted(
            grouped[org],
            key=lambda x: x["date"] or ""
        )

        for event in sorted_events:

            date = format_date(
                event["date"]
            )

            name = event["name"]

            lines.append(
                f"📅 **{date}** — {name}"
            )

            if event.get("location"):
                lines.append(
                    f"📍 {event['location']}"
                )

            if event.get("url"):
                lines.append(
                    f"🔗 {event['url']}"
                )

    lines.append("")
    lines.append(
        "━━━━━━━━━━━━━━━━━━━━"
    )

    lines.append(
        "🤖 Calendrier automatique"
    )

    return "\n".join(lines)


def send_discord(message):
    if not DISCORD_WEBHOOK:
        raise RuntimeError(
            "DISCORD_WEBHOOK n'est pas configuré."
        )

    payload = {
        "content": message,
        "username": "Fight Calendar Bot",
        "allowed_mentions": {
            "parse": []
        }
    }

    response = requests.post(
        DISCORD_WEBHOOK,
        json=payload,
        timeout=20
    )

    if response.status_code not in (
        200,
        204
    ):
        raise RuntimeError(
            f"Discord error "
            f"{response.status_code}: "
            f"{response.text}"
        )


def main():

    print("================================")
    print("FIGHT CALENDAR BOT")
    print("================================")

    now = datetime.now(
        timezone.utc
    )

    limit = now + timedelta(
        days=DAYS_AHEAD
    )

    print(
        f"[INFO] Recherche jusqu'au "
        f"{limit.date()}"
    )

    events = get_all_events()

    upcoming = []

    for event in events:

        if not event.get("date"):
            continue

        try:
            dt = datetime.fromisoformat(
                event["date"]
            )

            if dt.tzinfo is None:
                dt = dt.replace(
                    tzinfo=timezone.utc
                )

        except Exception:
            continue

        if now <= dt <= limit:
            upcoming.append(event)

    upcoming.sort(
        key=lambda x: x["date"]
    )

    print(
        f"[INFO] {len(upcoming)} événements "
        f"à venir."
    )

    if not upcoming:
        print(
            "[INFO] Aucun événement trouvé."
        )
        return

    data = load_sent()

    sent_ids = set(
        data.get("events", [])
    )

    new_events = []

    for event in upcoming:

        eid = event_id(event)

        if eid not in sent_ids:
            new_events.append(event)

    print(
        f"[INFO] {len(new_events)} nouveaux "
        f"événements."
    )

    # IMPORTANT :
    # Pour la première exécution, on envoie tout.
    if new_events:

        message = build_message(
            new_events
        )

        print(message)

        send_discord(message)

        for event in new_events:
            sent_ids.add(
                event_id(event)
            )

        # On garde seulement les 500 derniers
        data["events"] = list(
            sent_ids
        )[-500:]

        save_sent(data)

        print(
            "[OK] Message envoyé sur Discord."
        )

    else:

        print(
            "[INFO] Rien de nouveau. "
            "Aucun message envoyé."
        )


if __name__ == "__main__":
    main()