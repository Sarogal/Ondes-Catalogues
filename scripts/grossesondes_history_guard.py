"""Garde-fou strict pour une extension approuvée de l'historique Grosses Ondes.

La photographie Infomaniak et son empreinte restent immuables. Aucun nouveau
festival du calendrier ne peut être déduit de cet historique.
"""
from datetime import date
import json
from pathlib import Path
from urllib.parse import urlparse

REGISTRY_PATH = Path("reviews/grossesondes-historical-candidates-2026-10-30.json")


def require(ok, reason):
    if not ok:
        raise ValueError("Extension historique bloquée : " + reason)


def load_registry(path=REGISTRY_PATH):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    require(data.get("schema") == "grossesondes.history.candidates.v1",
            "registre inconnu")
    require(data.get("status") == "approved_for_history_release",
            "liste non validée pour publication")
    require(data.get("baseArchives") == 170, "compteur initial différent")
    require(data.get("releaseDate") == "2026-10-30", "date de lot inattendue")
    slugs = data.get("approvedSlugs")
    require(isinstance(slugs, list) and len(slugs) == 3
            and len(set(slugs)) == len(slugs),
            "liste d'approbation inattendue")
    require(slugs == ["rock-in-bourlon", "heavy-metal-breizh", "bully-on-rocks"],
            "liste des trois archives approuvées modifiée")
    records = data.get("additions")
    require(isinstance(records, list) and len(records) == 4, "lot candidat incomplet")
    require(len({x.get("slug") for x in records if isinstance(x, dict)}) == 4,
            "candidats ambigus")
    require(data.get("deferredSlugs") == ["festival-de-la-mer-landunvez"],
            "événement de genre voisin non différé")
    return data


def validate_history_extension(baseline, published, registry=None):
    """Autorise uniquement les archives explicitement approuvées, dans le bon ordre.

    Un historique inchangé est valide aussi, ce qui préserve les tests existants
    et permet au synchroniseur de fonctionner avant le déploiement du nouveau lot.
    """
    require(isinstance(baseline, dict) and isinstance(published, dict)
            and baseline.get("schema") == published.get("schema") == 2,
            "schéma différent")
    base_rows, new_rows = baseline.get("knownFestivals"), published.get("knownFestivals")
    require(isinstance(base_rows, list) and isinstance(new_rows, list),
            "collections absentes")
    require(len(new_rows) >= len(base_rows), "archives supprimées")
    require(new_rows[:len(base_rows)] == base_rows,
            "archive initiale modifiée, supprimée ou déplacée")
    old_slugs = [r.get("slug") for r in base_rows if isinstance(r, dict)]
    all_slugs = [r.get("slug") for r in new_rows if isinstance(r, dict)]
    require(len(old_slugs) == len(base_rows)
            and len(all_slugs) == len(new_rows)
            and all(isinstance(s, str) and s for s in all_slugs)
            and len(set(all_slugs)) == len(all_slugs), "slugs absents ou répétés")
    if len(new_rows) == len(base_rows):
        require(published == baseline, "métadonnées modifiées sans nouvelle archive")
        return 0

    registry = registry if registry is not None else load_registry()
    require(registry.get("schema") == "grossesondes.history.candidates.v1"
            and registry.get("status") == "approved_for_history_release",
            "registre non approuvé")
    require(len(base_rows) == registry.get("baseArchives") == 170,
            "volume initial incompatible avec la photographie officielle")
    approved = registry.get("approvedSlugs")
    require(approved == ["rock-in-bourlon", "heavy-metal-breizh", "bully-on-rocks"],
            "liste de publication modifiée")
    require(registry.get("deferredSlugs") == ["festival-de-la-mer-landunvez"],
            "événement différé non protégé")
    choices = registry.get("additions")
    require(isinstance(choices, list) and len(choices) == 4, "candidats incomplets")
    by_slug = {r.get("slug"): r for r in choices if isinstance(r, dict)}
    require(len(by_slug) == 4 and all(slug in by_slug for slug in approved),
            "identité de candidature incertaine")
    added = new_rows[len(base_rows):]
    require(added == [by_slug[slug] for slug in approved],
            "fiches ajoutées différentes du lot approuvé")
    expected = dict(baseline)
    expected["updatedAt"] = registry.get("releaseDate")
    expected["knownFestivals"] = base_rows + added
    require(published == expected, "métadonnées inattendues")

    for r in added:
        start, end = r.get("startDate"), r.get("endDate")
        require(isinstance(start, str) and isinstance(end, str), "dates historiques manquantes")
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        require(first <= last <= date.fromisoformat(registry["releaseDate"]),
                "dates inversées ou futures")
        require(r.get("lastKnownYear") == last.year, "année historique discordante")
        require(r.get("lastVerified") == registry["releaseDate"],
                "vérification non datée")
        source = r.get("source")
        require(isinstance(source, str) and urlparse(source).scheme == "https"
                and bool(urlparse(source).hostname),
                "preuve officielle absente")
    return len(added)
