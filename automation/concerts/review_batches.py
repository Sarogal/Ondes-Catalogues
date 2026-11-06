#!/usr/bin/env python3
"""Prepare non-publishing editorial review batches from the national gap report.

Review batches are NOT approvals: every source, artist and date must still be
rechecked individually by an official-source verifier before any publication.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

SCHEMA = "grossesondes.concert.coverage-gaps.v1"
OUT_SCHEMA = "grossesondes.concert.review-batches.v1"
# A complete metropolitan department map; overseas regions are also supported.
# The priority order is derived daily from published upcoming concerts, never
# from a hard-coded list of preferred areas.
REGIONS = {
    "Auvergne-Rhône-Alpes": {"01","03","07","15","26","38","42","43","63","69","73","74"},
    "Bourgogne-Franche-Comté": {"21","25","39","58","70","71","89","90"},
    "Bretagne": {"22","29","35","56"},
    "Centre-Val de Loire": {"18","28","36","37","41","45"},
    "Corse": {"2A","2B"},
    "Grand Est": {"08","10","51","52","54","55","57","67","68","88"},
    "Hauts-de-France": {"02","59","60","62","80"},
    "Île-de-France": {"75","77","78","91","92","93","94","95"},
    "Normandie": {"14","27","50","61","76"},
    "Nouvelle-Aquitaine": {"16","17","19","23","24","33","40","47","64","79","86","87"},
    "Occitanie": {"09","11","12","30","31","32","34","46","48","65","66","81","82"},
    "Pays de la Loire": {"44","49","53","72","85"},
    "Provence-Alpes-Côte d’Azur": {"04","05","06","13","83","84"},
    "Guadeloupe": {"971"},
    "Martinique": {"972"},
    "Guyane": {"973"},
    "La Réunion": {"974"},
    "Mayotte": {"976"},
}
LEGACY_PRIORITY = ("Bretagne", "Nouvelle-Aquitaine", "Hauts-de-France")


def region_order(report):
    """Underserved published regions first, with zero-event regions included.

    The input is a *snapshot*, not a publication instruction; unknown
    department codes remain in the trailing 'Autres régions' bucket.
    """
    catalogue = report.get("catalogue") or {}
    counts = catalogue.get("regions") if isinstance(catalogue, dict) else None
    if isinstance(counts, dict) and all(
        isinstance(n, int) and not isinstance(n, bool) and n >= 0
        for n in counts.values()
    ):
        return sorted(REGIONS, key=lambda r: (counts.get(r, 0), r)) + ["Autres régions"]
    return list(LEGACY_PRIORITY) + [
        r for r in REGIONS if r not in LEGACY_PRIORITY
    ] + ["Autres régions"]


def region_of(dept):
    code = str(dept or "").strip()
    code = code.zfill(2) if code.isdigit() else code.upper()
    return next((r for r, departments in REGIONS.items() if code in departments), "Autres régions")


def single_line(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:180]


def validate_report(report):
    if not isinstance(report, dict) or report.get("schema") != SCHEMA:
        raise ValueError("Rapport national absent ou inconnu")
    if report.get("publicationAllowed") is not False or not re.fullmatch(
        r"20\d{2}-\d\d-\d\d", str(report.get("asOf", ""))
    ):
        raise ValueError("Rapport non quarantainé ou date absente")
    if not isinstance(report.get("priorityLeads"), list) or not isinstance(
        report.get("discovery"), dict
    ):
        raise ValueError("Pistes nationales non conformes")
    if len(report["priorityLeads"]) > 100:
        raise ValueError("Trop de pistes pour un lot de revue")
    for item in report["priorityLeads"]:
        if not isinstance(item, dict) or item.get("publicationAllowed") is not False or (
            item.get("reviewRequired") is not True
        ):
            raise ValueError("Piste non explicitement tenue hors publication")


def build_batches(report, *, batch_size=24, per_venue=3):
    validate_report(report)
    if not 1 <= batch_size <= 40 or not 1 <= per_venue <= 5:
        raise ValueError("Limites de lot invalides")
    # Keep only documentary leads. Unknown genres remain in the gap report
    # but cannot fill review batches prematurely.
    candidates = [x for x in report["priorityLeads"]
                  if x.get("tier") == "genre_documented"
                  and isinstance(x.get("sourceUrl"), str)
                  and x["sourceUrl"].startswith("https://")
                  and x.get("name") and x.get("date") and x.get("city")]
    order = region_order(report)
    groups = {key: [] for key in order}
    for item in candidates:
        groups[region_of(item.get("department"))].append(item)
    # Review all regions fairly, starting with those containing the fewest
    # already published concerts; a prolific venue cannot monopolize a batch.
    chosen, selected_ids = [], set()
    venue_counts, region_counts = Counter(), Counter()

    def add(item, region):
        venue_key = (single_line(item.get("venue")).casefold(),
                     single_line(item.get("city")).casefold())
        identity = (item.get("date"), venue_key, single_line(item.get("name")).casefold())
        if identity in selected_ids or venue_counts[venue_key] >= per_venue:
            return False
        selected_ids.add(identity)
        venue_counts[venue_key] += 1
        region_counts[region] += 1
        chosen.append({
            "date": item["date"],
            "artistOrBill": single_line(item["name"]),
            "venue": single_line(item["venue"]),
            "city": single_line(item["city"]),
            "department": single_line(item.get("department")),
            "region": region,
            "sourceUrl": item["sourceUrl"],
            "sourceKind": single_line(item.get("sourceKind")),
            "firstPartyDetailCandidate": bool(item.get("individualOfficialLead")),
            "status": "awaiting_independent_event_recheck",
            "reviewChecklist": [
                "fiche événement officielle nominative",
                "date future et lieu exact",
                "programmation et identité de chaque artiste",
                "genre explicitement prouvé",
                "absence d'annulation ou de report",
                "doublon catalogue et festival exclu",
            ],
            "publicationAllowed": False,
            "approvalDecision": "not_reviewed",
        })
        return True

    # Reserve one slot per represented region, without exceeding batch_size.
    for region in order:
        if len(chosen) >= batch_size:
            break
        for item in groups[region]:
            if add(item, region):
                break

    # Continue a fair rotation across all four geographic buckets.
    while len(chosen) < batch_size:
        progress = False
        for region in order:
            if len(chosen) >= batch_size:
                break
            for item in groups[region]:
                if add(item, region):
                    progress = True
                    break
        if not progress:
            break

    return {
        "schema": OUT_SCHEMA,
        "asOf": report["asOf"],
        "publicationAllowed": False,
        "reviewedOrApproved": 0,
        "eligibleLeadsBeforeCap": len(candidates),
        "selected": len(chosen),
        "perVenueLimit": per_venue,
        "regionPriorityOrder": order,
        "regionCounts": dict(sorted(region_counts.items())),
        "items": chosen,
        "warning": "Dossier éditorial non signé : aucune écriture d'approbation ni publication",
    }


def markdown(data):
    lines = [
        "# Grosses Ondes — lot de vérification des dates absentes",
        "",
        f"État au {data['asOf']} : **{data['selected']} pistes à vérifier**, "
        f"sur {data['eligibleLeadsBeforeCap']} éligibles à une revue.",
        "**Aucune date approuvée ni publiée par ce rapport.**",
        "",
        "## Répartition géographique",
    ]
    for region, count in data["regionCounts"].items():
        lines.append(f"- {region} : {count}")
    lines.extend(["", "## Fiches à contrôler auprès des organisateurs", ""])
    for item in data["items"]:
        link = item["sourceUrl"]
        lines.append(f"- {item['date']} — {item['artistOrBill']} — "
                     f"{item['venue']} ({item['city']}) — {link}")
    lines.extend(["", "Après recoupement : établir une preuve indépendante et "
                  "utiliser séparément la procédure d'approbation existante."])
    return "\n".join(lines) + "\n"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    result = build_batches(data)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "lots-revue.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "LOTS_REVUE.md").write_text(markdown(result), encoding="utf-8")
    print(f"Lots Concerts : {result['selected']} pistes en revue, zéro approbation.")


if __name__ == "__main__":
    main()
