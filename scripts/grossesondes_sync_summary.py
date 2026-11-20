"""Accurate GitHub Actions summary for the protected Festivals sync.

A successful validation job is not proof of a new publication. This formatter
only displays the existing independent-proof report, never changes the JSON.
"""
import argparse
import json
from pathlib import Path
import re


def safe(value):
    return re.sub(r"[^\w ./:()=-]", "_", str(value).replace("\n", " "))[:170]


def render(report, deploy_decision=False):
    if not isinstance(report, dict):
        raise ValueError("rapport de synchronisation invalide")
    changed = report.get("changed")
    if type(changed) is not bool:
        raise ValueError("indicateur de changement absent")
    additions = report.get("accepted_additions")
    updates = report.get("accepted_updates")
    held = report.get("held")
    already_published = report.get("already_published", [])
    if not all(isinstance(k, list) for k in (additions, updates, held,
                                              already_published)):
        raise ValueError("rapport de preuve incomplet")
    if (any(not isinstance(slug, str) for slug in already_published)
            or len(set(already_published)) != len(already_published)
            or set(already_published) & set(additions)):
        raise ValueError("identités publiques dupliquées invalides")
    if not all(isinstance(k, list) for k in (additions, updates, held)):
        raise ValueError("rapport de preuve incomplet")
    count = report.get("candidate_total")
    if type(count) is not int or count < 0:
        raise ValueError("nombre d'éditions invalide")
    lines = [
        "### Grosses Ondes — Synchronisation sécurisée Festivals",
        "",
        f"- Éditions du catalogue candidat : **{count}**",
        f"- Propositions revalidées sur sources officielles : {len(additions)} ajout(s), {len(updates)} mise(s) à jour",
        f"- Déjà présentes dans le catalogue signé : **{len(already_published)}** (sans réinsertion)",
        f"- Propositions différées ou refusées : **{len(held)}**",
        f"- Âge du patch privé : {safe(report.get('patch_age_days', '?'))} jour(s)",
        f"- Archives historiques inchangées : {'oui' if report.get('unchanged_history') is True else 'non attesté'}",
        f"- Mode de travail : {safe(report.get('mode', '?'))}",
    ]
    map_report = report.get("future_map_coverage")
    if map_report is not None:
        if not isinstance(map_report, dict):
            raise ValueError("rapport cartographique invalide")
        required = (
            "dated_future_editions", "undated_catalogue_editions",
            "coordinates_present", "coordinates_missing",
            "explicitly_hidden", "explicitly_visible_flag",
            "visibility_flag_absent",
            "coordinates_present_not_explicitly_hidden", "city_missing",
        )
        if (set(map_report) != set(required)
                or any(type(map_report[key]) is not int or map_report[key] < 0
                       for key in required)):
            raise ValueError("compteurs cartographiques invalides")
        future = map_report["dated_future_editions"]
        if (map_report["coordinates_present"] + map_report["coordinates_missing"]
                != future
                or map_report["explicitly_hidden"]
                + map_report["explicitly_visible_flag"]
                + map_report["visibility_flag_absent"] != future
                or map_report["coordinates_present_not_explicitly_hidden"]
                > map_report["coordinates_present"]
                or map_report["city_missing"] > future):
            raise ValueError("réconciliation cartographique invalide")
        lines.extend([
            "",
            "Couverture des éditions futures datées (catalogue candidat) :",
            f"- Éditions futures : **{future}**",
            f"- Avec coordonnées plausibles : **{map_report['coordinates_present']}** ; sans coordonnées : **{map_report['coordinates_missing']}**",
            f"- Marqueur explicitement désactivé : **{map_report['explicitly_hidden']}** ; drapeau absent : **{map_report['visibility_flag_absent']}**",
            f"- Coordonnées présentes, sans désactivation explicite : **{map_report['coordinates_present_not_explicitly_hidden']}**",
            "- Des coordonnées présentes ou un drapeau absent ne garantissent pas l'affichage sur la carte ni le lieu de la nouvelle édition.",
        ])
    geo = report.get("future_geo_publisher")
    if geo is not None:
        required = {
            "private_report", "private_two_day_candidates",
            "independent_rechecks", "accepted_geo_updates", "held_geo",
            "publication_authorized_by_private_report",
        }
        if not isinstance(geo, dict) or set(geo) != required:
            raise ValueError("rapport de seconde vérification géographique invalide")
        values = ("private_two_day_candidates", "independent_rechecks", "held_geo")
        if (any(type(geo[k]) is not int or geo[k] < 0 for k in values)
                or not isinstance(geo["accepted_geo_updates"], list)
                or not all(isinstance(slug, str) for slug in geo["accepted_geo_updates"])
                or len(set(geo["accepted_geo_updates"])) != len(geo["accepted_geo_updates"])
                or geo["publication_authorized_by_private_report"] is not False
                or geo["independent_rechecks"] > geo["private_two_day_candidates"]
                or len(geo["accepted_geo_updates"]) > geo["independent_rechecks"]
                or len(geo["accepted_geo_updates"]) + geo["held_geo"]
                   != geo["private_two_day_candidates"]
                or geo["private_report"] not in (
                    "unavailable", "invalid_or_stale", "valid",
                    "signed_head_not_verified")):
            raise ValueError("compteurs de contre-vérification géographique invalides")
        lines.extend([
            "",
            "Géolocalisation des éditions futures (revérification indépendante) :",
            f"- Rapport privé : **{safe(geo['private_report'])}** (simple piste, jamais autorisation)",
            f"- Indices J+1 : **{geo['private_two_day_candidates']}** ; pages officielles retéléchargées : **{geo['independent_rechecks']}**",
            f"- Enrichissements géographiques du candidat : **{len(geo['accepted_geo_updates'])}** ; différés : **{geo['held_geo']}**",
            "- Un enrichissement n'est publié qu'après commit signé et déploiement Pages réussi.",
        ])
    city = report.get("future_city_publisher")
    if city is not None:
        expected = {
            "private_report", "private_two_day_candidates",
            "independent_rechecks", "accepted_city_updates", "held_city",
            "publication_authorized_by_private_report",
        }
        if not isinstance(city, dict) or set(city) != expected:
            raise ValueError("rapport de vérification de commune invalide")
        numeric = ("private_two_day_candidates", "independent_rechecks", "held_city")
        if (any(type(city[k]) is not int or city[k] < 0 for k in numeric)
                or not isinstance(city["accepted_city_updates"], list)
                or any(not isinstance(s, str) or not s
                       for s in city["accepted_city_updates"])
                or len(set(city["accepted_city_updates"]))
                   != len(city["accepted_city_updates"])
                or city["independent_rechecks"] > city["private_two_day_candidates"]
                or len(city["accepted_city_updates"]) > city["independent_rechecks"]
                or len(city["accepted_city_updates"]) + city["held_city"]
                   != city["private_two_day_candidates"]
                or city["publication_authorized_by_private_report"] is not False
                or city["private_report"] not in (
                    "valid", "unavailable", "invalid_or_stale",
                    "signed_head_not_verified")):
            raise ValueError("compteurs de commune non réconciliés")
        lines.extend([
            "",
            "Communes de futures éditions (centre indicatif, pas lieu exact) :",
            f"- Indices J+1 : **{city['private_two_day_candidates']}** ; pages officielles retéléchargées : **{city['independent_rechecks']}**",
            f"- Centres de commune vérifiés par API officielle : **{len(city['accepted_city_updates'])}** ; différés : **{city['held_city']}**",
            "- Précision des nouveaux marqueurs : **commune** (ni scène, ni entrée, ni camping).",
        ])
    if changed:
        lines.append("- Différence de contenu validée : **oui**")
        lines.append("- Déploiement autorisé par la décision du job : "
                     + ("**oui, en attente de confirmation de GitHub Pages**" if deploy_decision
                        else "**non, catalogue candidat seulement**"))
    else:
        lines.append("- Différence de contenu validée : **non**")
        lines.append("**Aucune nouvelle modification du JSON public.** Les propositions "
                     "revalidées peuvent déjà être intégrées ; les autres demeurent "
                     "en attente de preuve suffisante. Aucune modification artificielle.")
    if held:
        lines.extend(["", "Propositions restées en attente (extrait) :"])
        for row in held[:10]:
            lines.append("- `" + safe(row.get("slug", "?")) + "` : "
                         + safe(row.get("reason", "preuve insuffisante")))
    lines.extend(["", "Une exécution GitHub Actions réussie ne signifie pas "
                  "qu'une nouvelle annonce a été publiée sur GitHub Pages."])
    return "\n".join(lines) + "\n"


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--deploy", choices=("true", "false"), required=True)
    args=parser.parse_args()
    data=json.loads(args.report.read_text(encoding="utf-8"))
    print(render(data, args.deploy == "true"), end="")


if __name__ == "__main__":
    main()
