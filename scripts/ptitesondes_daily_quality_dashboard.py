"""Private-only P'tites Ondes daily quality dashboard from existing redacted reports.

Runs on public GitHub runners, but MUST write exclusively to the PRIVATE
automation/ptitesondes-intake branch. Does not contact APIs, publish, approve,
or include candidate names, URLs, source material or personal information.
"""
import argparse
from collections import Counter
from datetime import date, timedelta
import json
from pathlib import Path
REASON_CODES = frozenset((
    "already_published", "schema", "official_page_dynamic",
    "official_page_unavailable", "organizer_proof", "venue_or_gps",
    "date_or_time", "age_or_audience", "title_or_identity",
    "uid_or_source", "transport_or_data", "other",
))


def nonnegative(value):
    if type(value) is not int or value < 0:
        raise ValueError("Compteur de diagnostic absent ou non fiable")
    return value


def read_document(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Document de diagnostic invalide")
    return data


def daily_dashboard(reports_dir, catalogue, today, window=7):
    """Display decisions, not unique events, and never claim GitHub Pages delivery."""
    if type(window) is not int or not 1 <= window <= 31:
        raise ValueError("Fenêtre du tableau de bord hors limites")
    if not isinstance(today, date):
        raise ValueError("Date invalide")
    if catalogue.get("version") != 3 or not isinstance(catalogue.get("events"), list):
        raise ValueError("Catalogue public illisible")
    events = catalogue["events"]
    ids = [e.get("id") if isinstance(e, dict) else None for e in events]
    if any(not isinstance(k, str) or not k for k in ids) or len(set(ids)) != len(ids):
        raise ValueError("Identifiants publics absents ou dupliqués")
    updated = catalogue.get("updated_at")
    if not isinstance(updated, str) or not updated.strip():
        raise ValueError("Date réelle du catalogue absente")

    rows = []
    for offset in range(window - 1, -1, -1):
        day = today - timedelta(days=offset)
        root = Path(reports_dir)
        path = root / (day.isoformat() + ".json")
        if not path.exists():
            continue  # No collection is never shown as a successful collection.
        collected = read_document(path)
        if collected.get("day") != day.isoformat():
            raise ValueError("Rapport de collecte avec mauvaise date")
        row = {
            "day": day.isoformat(),
            "sources": nonnegative(collected.get("sources_interrogees")),
            "events_examined": nonnegative(collected.get("evenements_examines")),
            "relevant_sessions": nonnegative(collected.get("seances_pertinentes")),
            "new_leads": nonnegative(collected.get("decouvertes_nouvelles_en_attente")),
            "backlog": nonnegative(collected.get("en_attente_total")),
            "qualification_slots": 0,
            "eligible": None,
            "checks": 0,
            "accepted_preflight": 0,
            "rejected_decisions": 0,
            "reason_groups": {},
            "private_approvals": None,
            "public_writes_reported_by_private_intake": None,
        }
        reasons = Counter()
        for slot in range(4):
            p = root / ("qualification-" + day.isoformat() + "-slot" + str(slot) + ".json")
            if not p.exists():
                continue
            q = read_document(p)
            if q.get("day") != day.isoformat() or q.get("slot") != slot or (
                q.get("mode") != "private_diagnostic_only"
            ):
                raise ValueError("Qualification datée ou statut incohérent")
            total = nonnegative(q.get("backlog_total"))
            eligible = nonnegative(q.get("eligible"))
            checked = nonnegative(q.get("checked"))
            accepted = nonnegative(q.get("accepted_preflight"))
            rejected = nonnegative(q.get("rejected"))
            if eligible > total or accepted + rejected != checked:
                raise ValueError("Rapports de qualification non réconciliés")
            # A backlog can legitimately grow between scheduled slots.
            # Never treat a previous slot snapshot as an immutable daily total.
            row["eligible"] = eligible
            row["qualification_slots"] += 1
            row["checks"] += checked
            row["accepted_preflight"] += accepted
            row["rejected_decisions"] += rejected
            buckets = q.get("reason_groups")
            if not isinstance(buckets, dict) or not set(buckets).issubset(REASON_CODES):
                raise ValueError("Groupes de rejet incorrects")
            if sum(nonnegative(n) for n in buckets.values()) != rejected:
                raise ValueError("Somme de rejets non réconciliée")
            reasons.update(buckets)
        row["reason_groups"] = dict(sorted(reasons.items()))
        verification = root / ("verification-" + day.isoformat() + ".json")
        if verification.exists():
            v = read_document(verification)
            if v.get("day") != day.isoformat() or v.get("mode") != "private_patch_only":
                raise ValueError("Rapport des approbations non concordant")
            row["private_approvals"] = nonnegative(v.get("new_approved_privately"))
            row["public_writes_reported_by_private_intake"] = nonnegative(
                v.get("public_writes"))
        rows.append(row)
    return {
        "schema": "ptitesondes.private_quality_dashboard.v1",
        "generated_day": today.isoformat(),
        "report_window_days": window,
        "public_catalogue": {
            "events": len(events), "updated_at": updated,
        },
        "days": rows,
        "notes": {
            "checks": "décisions de vérification; un candidat peut être revu plusieurs fois",
            "public_writes_reported_by_private_intake": (
                "ne prouve ni un déploiement GitHub Pages ni un affichage sur le site"),
            "absent_values": "null signifie absence de rapport, pas zéro succès",
            "private_storage_only": True,
        },
    }


def markdown_status(status):
    cat = status["public_catalogue"]
    lines = [
        "# P'tites Ondes — veille sorties (privé)",
        "",
        "Généré pour le " + status["generated_day"] + ".",
        "",
        "Catalogue Git consulté : **" + str(cat["events"]) +
        " fiches** ; mise à jour déclarée : `" + cat["updated_at"] + "`.",
        "",
        "| Jour | Sources | Événements | Nouvelles pistes | Backlog | Lots | "
        "Décisions | Prévalidés | Approuvés privés | Écritures privées signalant publication |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    def value(v):
        return "—" if v is None else str(v)
    for row in status["days"]:
        lines.append("| " + " | ".join(value(x) for x in (
            row["day"], row["sources"], row["events_examined"],
            row["new_leads"], row["backlog"], row["qualification_slots"],
            row["checks"], row["accepted_preflight"], row["private_approvals"],
            row["public_writes_reported_by_private_intake"],
        )) + " |")
    lines.extend([
        "",
        "**Attention :** les décisions ne sont pas des candidats uniques. "
        "La dernière mise à jour Git représente le catalogue de référence "
        "au moment de la collecte, **pas** une preuve d'affichage Pages.",
        "Un rapport absent reste une donnée inconnue, jamais un succès.",
        "",
    ])
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reports-dir", type=Path, required=True)
    ap.add_argument("--catalogue", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--markdown", type=Path, required=True)
    ap.add_argument("--date", type=date.fromisoformat, required=True)
    args = ap.parse_args()
    doc = read_document(args.catalogue)
    status = daily_dashboard(args.reports_dir, doc, args.date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    args.markdown.write_text(markdown_status(status), encoding="utf-8")


if __name__ == "__main__":
    main()
