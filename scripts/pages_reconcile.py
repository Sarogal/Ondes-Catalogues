"""Read-only verification that GitHub Pages serves the three approved main catalogues.

Never writes catalogue JSON. A record missing from main but present on Pages is
an error requiring human reconciliation; do not publish a destructive snapshot.
"""
import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen

CATALOGUES = (
    ("festivals", "docs/grossesondes/festivals.json", "https://sarogal.github.io/Ondes-Catalogues/grossesondes/festivals.json", "festivals", "slug", "schema", 1, 90),
    ("concerts", "docs/grossesondes/concerts.json", "https://sarogal.github.io/Ondes-Catalogues/grossesondes/concerts.json", "events", "id", "schemaVersion", 1, 10),
    ("sorties", "docs/ptitesondes/sorties.json", "https://sarogal.github.io/Ondes-Catalogues/ptitesondes/sorties.json", "events", "id", "version", 3, 100),
)
MAX_BYTES = 5_000_000


def event_ids(doc, spec):
    name, _path, _url, key, id_key, schema_key, expected_version, minimum = spec
    if not isinstance(doc, dict) or doc.get(schema_key) != expected_version:
        raise ValueError(f"{name}: schéma inattendu; pas de déploiement")
    rows = doc.get(key)
    if not isinstance(rows, list) or len(rows) < minimum:
        raise ValueError(f"{name}: volume insuffisant; pas de déploiement")
    ids = [row.get(id_key) if isinstance(row, dict) else None for row in rows]
    if any(not isinstance(x, str) or not x for x in ids) or len(ids) != len(set(ids)):
        raise ValueError(f"{name}: identifiants manquants ou dupliqués")
    return set(ids)


def needs_reconcile(approved, published, spec):
    approved_ids = event_ids(approved, spec)
    published_ids = event_ids(published, spec)
    missing = published_ids - approved_ids
    if missing:
        raise ValueError(f"{spec[0]}: {len(missing)} fiche(s) publiques absentes de main, réconciliation manuelle requise")
    return approved != published


def read_public(url):
    request = Request(url, headers={"User-Agent": "OndesPagesReconcile/1.0", "Accept": "application/json"})
    with urlopen(request, timeout=20) as response:
        if response.geturl() != url:
            raise ValueError("Redirection Pages inattendue")
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError("Catalogue Pages trop volumineux")
    return json.loads(body.decode("utf-8-sig"))


def evaluate(root=Path("."), fetch=read_public):
    differences = []
    for spec in CATALOGUES:
        name, path, url, *_ = spec
        approved = json.loads((root / path).read_text(encoding="utf-8-sig"))
        published = fetch(url)
        if needs_reconcile(approved, published, spec):
            differences.append(name)
    return differences


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    changed = evaluate()
    decision = "true" if changed else "false"
    print(f"GitHub Pages: {'réconciliation de ' + ', '.join(changed) if changed else 'déjà conforme à main'}")
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as file:
            file.write(f"deploy={decision}\n")
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as file:
            file.write("## Réconciliation Pages (catalogues approuvés)\n")
            file.write(f"Déploiement nécessaire : **{decision}**. Écarts : {', '.join(changed) or 'aucun'}.\n")
            file.write("Aucun JSON de main n'a été modifié ; aucun ajout non approuvé n'est produit ici.\n")


if __name__ == "__main__":
    main()
