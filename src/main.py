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
    if not DATA_FILE.exists():
        return {"events": []}

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"events": []}


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


# ============================================================
# FORMAT
# ============================================================

ORG_EMOJI = {
    "UFC": "🥊",
    "PFL": "🥋",
    "GLORY": "🥊",
    "ONE": "🔥",
}


def format_date(date_string):
    try:
        dt = datetime.fromisoformat(date_string)
        return dt.strftime("%A %d %B %Y").capitalize()
    except Exception:
        return date_string


def fight_line(fight):
    fighter1 = fight.get("fighter1", "").strip()
    fighter2 = fight.get("fighter2", "").strip()

    if not fighter1 or not fighter2:
        return None

    label = fight.get("label", "")

    if label:
        return f"• **{label}** — {fighter1} 🆚 {fighter2}"

    return f"• {fighter1} 🆚 {fighter2}"


# ============================================================
# DISCORD MESSAGE
# ============================================================

def build_message(events):

    lines = []

    lines.append("🔥 **PROCHAINS COMBATS — MMA & KICKBOXING**")
    lines.append("━━━━━━━━━━━━━━━━━━━━")

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
            f"{ORG_EMOJI.get(org, '🥊')} **{org}**"
        )
        lines.append("━━━━━━━━━━━━━━━━━━━━")

        events_for_org = sorted(
            grouped[org],
            key=lambda x: x.get("date") or ""
        )

        for event in events_for_org:

            date = format_date(event["date"])

            lines.append("")
            lines.append(
                f"📅 **{date}**"
            )

            lines.append(
                f"🏟️ **{event['name']}**"
            )

            fights = event.get("fights", [])

            if fights:

                main_event = None
                other_fights = []

                for fight in fights:
                    if fight.get("main_event"):
                        main_event = fight
                    else:
                        other_fights.append(fight)

                if main_event:
                    line = fight_line(main_event)

                    if line:
                        lines.append("")
                        lines.append("🔥 **MAIN EVENT**")
                        lines.append(line)

                if other_fights:

                    lines.append("")
                    lines.append("⚔️ **CARTE**")

                    for fight in other_fights[:12]:

                        line = fight_line(fight)

                        if line:
                            lines.append(line)

                if len(fights) > 13:
                    lines.append(
                        f"… + {len(fights) - 13} autres combats"
                    )

            if event.get("url"):
                lines.append(
                    f"🔗 {event['url']}"
                )

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("🤖 Calendrier automatique")

    return "\n".join(lines)


# ============================================================
# DISCORD
# ============================================================

def send_discord(message):

    if not DISCORD_WEBHOOK:
        raise RuntimeError(
            "DISCORD_WEBHOOK n'est pas configuré."
        )

    payload = {
        "content": "@everyone\n" + message,
        "username": "Fight Calendar",
        "allowed_mentions": {
            "parse": ["everyone"]
        }
    }

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


# ============================================================
# MAIN
# ============================================================

def main():

    print("================================")
    print("FIGHT CALENDAR V2")
    print("================================")

    now = datetime.now(timezone.utc)

    limit = now + timedelta(
        days=DAYS_AHEAD
    )

    events = get_all_events()

    print(
        f"[INFO] {len(events)} événements récupérés."
    )

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
        f"[INFO] {len(upcoming)} événements à venir."
    )

    if not upcoming:
        print("[INFO] Aucun événement.")
        return

    database = load_sent()

    sent = set(
        database.get("events", [])
    )

    new_events = []

    for event in upcoming:

        eid = event_id(event)

        if eid not in sent:
            new_events.append(event)

    print(
        f"[INFO] {len(new_events)} nouveaux événements."
    )

    if not new_events:
        print(
            "[INFO] Rien de nouveau. "
            "Aucun ping."
        )
        return

    message = build_message(
        new_events
    )

    print(message)

    send_discord(message)

    for event in new_events:
        sent.add(
            event_id(event)
        )

    database["events"] = list(sent)[-500:]

    save_sent(database)

    print("[OK] Discord envoyé avec @everyone.")


if __name__ == "__main__":
    main()