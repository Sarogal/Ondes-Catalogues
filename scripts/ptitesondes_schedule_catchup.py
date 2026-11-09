"""Bounded catch-up of missed *verification batches*, not missed collections.

A delayed GitHub schedule event has no reliable scheduled execution timestamp.
Use only the UTC clock and the Paris calendar day, not any inferred missed date.
Never claim that several independent upstream collections were performed.
Reports are stored exclusively on the private intake branch.
"""
import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path

OUTINGS_CRONS = (
    ("17 07 * * *", 7, 17),
    ("17 10 * * *", 10, 17),
    ("17 14 * * *", 14, 17),
    ("17 18 * * *", 18, 17),
)
MAX_SLOTS = 4
REPORT_SCHEMA = "ptitesondes.private_qualification_summary.v1"


def already_reviewed(reports_dir, day, slot):
    """Accept an already completed slot only when its private report is valid."""
    path = reports_dir / f"qualification-{day.isoformat()}-slot{slot}.json"
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Compte rendu privé de créneau illisible") from exc
    checked = data.get("checked") if isinstance(data, dict) else None
    accepted = data.get("accepted_preflight") if isinstance(data, dict) else None
    rejected = data.get("rejected") if isinstance(data, dict) else None
    if (not isinstance(data, dict)
            or data.get("schema") != REPORT_SCHEMA
            or data.get("day") != day.isoformat()
            or type(data.get("slot")) is not int or data["slot"] != slot
            or data.get("mode") != "private_diagnostic_only"
            or data.get("publications") != 0
            or type(checked) is not int or not 0 <= checked <= 15
            or type(accepted) is not int or not 0 <= accepted <= checked
            or type(rejected) is not int or rejected != checked - accepted):
        raise ValueError("Compte rendu privé de créneau incohérent")
    return True


def pending_slots(day, now_utc, event, cron, reports_dir):
    """Return due, unprocessed slots (always <= 4).

    Only scheduled outings can catch up; manual/push preview preserves its
    original single-slot behavior. When Paris has rolled over to tomorrow
    but UTC has not, refuse to mislabel prior-day cron slots.
    """
    if now_utc.tzinfo is None or now_utc.utcoffset() != timezone.utc.utcoffset(now_utc):
        raise ValueError("Horodatage UTC explicite requis")
    if event != "schedule":
        if event not in {"push", "workflow_dispatch"} or cron:
            raise ValueError("Événement de rattrapage non autorisé")
        return [0]
    nominal = {key: (slot, hour, minute)
               for slot, (key, hour, minute) in enumerate(OUTINGS_CRONS)}
    if cron not in nominal:
        raise ValueError("Créneau programmé inconnu")
    if day != now_utc.date():
        # Scheduled outings are at 07-18 UTC and always occur on the same
        # Paris and UTC day; at or after local midnight, a delayed trigger
        # cannot safely be assigned to a day from cron alone.
        return []
    slot, hour, minute = nominal[cron]
    instant = now_utc.astimezone(timezone.utc)
    planned = datetime(day.year, day.month, day.day, hour, minute,
                       tzinfo=timezone.utc)
    if instant < planned:
        raise ValueError("Déclenchement antérieur à son créneau nominal")
    due = [index for index, (_, h, m) in enumerate(OUTINGS_CRONS)
           if instant >= datetime(day.year, day.month, day.day, h, m,
                                  tzinfo=timezone.utc)]
    return [index for index in due
            if not already_reviewed(reports_dir, day, index)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", type=date.fromisoformat, required=True)
    ap.add_argument("--event", choices=("schedule", "push", "workflow_dispatch"),
                    required=True)
    ap.add_argument("--cron", default="")
    ap.add_argument("--reports-dir", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    slots = pending_slots(args.date, now, args.event, args.cron, args.reports_dir)
    if len(slots) > MAX_SLOTS or len(slots) != len(set(slots)):
        raise ValueError("Liste des créneaux non bornée ou dupliquée")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(f"{slot}\n" for slot in slots),
                           encoding="utf-8")
    # Deliberately public-safe summary; no private candidate data.
    print(f"Vérifications en attente : {len(slots)} (maximum {MAX_SLOTS}); "
          "une seule collecte réalisée par exécution.")


if __name__ == "__main__":
    main()
