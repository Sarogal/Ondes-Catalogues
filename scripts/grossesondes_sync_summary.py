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
        f"- Propositions différées ou refusées : **{len(held)}**",
        f"- Âge du patch privé : {safe(report.get('patch_age_days', '?'))} jour(s)",
        f"- Archives historiques inchangées : {'oui' if report.get('unchanged_history') is True else 'non attesté'}",
        f"- Mode de travail : {safe(report.get('mode', '?'))}",
    ]
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
