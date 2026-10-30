"""Réconciliation explicite du calendrier initial (123) et des 124 fiches déjà publiées.

Aucune modification antérieure attestée sur GitHub Pages ne doit être effacée
par un patch cumulatif qui repartirait du cliché immuable Infomaniak.
"""
from copy import deepcopy
from hashlib import sha1
import json
from pathlib import Path

APPROVAL_FILE = Path("reviews/grossesondes-approved-calendar-delta-2026-10-30.json")
APPROVAL_BLOB = "e772912a1e7631a4817b630d9baacbcc3b0b8f3d"
BASELINE_SHA256 = "34eefea6689008eec09e1d2bad57e9a8b2ca270f936fd07f6d669947ecd47898"


def require(condition, reason):
    if not condition:
        raise ValueError("Calendrier approuvé bloqué : " + reason)


def load_approval(path=APPROVAL_FILE):
    raw = Path(path).read_bytes()
    git_blob = sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    require(git_blob == APPROVAL_BLOB, "registre approuvé altéré")
    data = json.loads(raw.decode("utf-8-sig"))
    require(data.get("schema") == "grossesondes.calendar.approved-delta.v1"
            and data.get("baselineReference") == {
                "calendarCount": 123,
                "generatedAt": "2026-10-25",
                "sha256": BASELINE_SHA256,
            }, "photographie initiale incorrecte")
    require(data.get("approvedPublic") == {
        "calendarCount": 124,
        "generatedAt": "2026-10-30",
        "gitBlobSha": "0fb7230f7b98ab4213294798f15804ba61ef8807",
    }, "cliché public approuvé inattendu")
    names = [r.get("slug") for r in data.get("changes", [])]
    require(names == ["festival-metal-vouziers-2026", "cernunnos-pagan-fest", "autfest-2027"],
            "modifications approuvées divergentes")
    new = data.get("additions")
    require(isinstance(new, list) and len(new) == 1
            and new[0].get("slug") == "muscadeath-2027",
            "édition ajoutée non approuvée")
    return data


def approved_calendar(original, approval=None):
    approval = approval if approval is not None else load_approval()
    require(original.get("schema") == 1
            and original.get("generatedAt") == approval["baselineReference"]["generatedAt"],
            "date ou schéma source modifié")
    base = original.get("festivals")
    require(isinstance(base, list) and len(base) == 123, "volume original incorrect")
    trusted = deepcopy(original)
    lookup = {r["slug"]: r for r in trusted["festivals"]}
    require(len(lookup) == len(base), "identifiants initiaux dupliqués")
    for item in approval["changes"]:
        slug = item["slug"]
        require(slug in lookup, "festival modifié inconnu")
        target = lookup[slug]
        for field, change in item["changes"].items():
            require(field not in ("slug", "name", "startDate", "endDate", "lat", "lon",
                                   "showOnMap", "status", "officialSite"),
                    "modification d'identité, de géographie ou de date")
            require(field in target and target[field] == change["before"],
                    "ancienne valeur non concordante : " + slug + "." + field)
            target[field] = deepcopy(change["after"])
    addition = deepcopy(approval["additions"][0])
    require(addition["slug"] not in lookup and addition.get("status") == "Dates à venir"
            and addition.get("showOnMap") is False
            and not addition.get("startDate") and not addition.get("endDate")
            and not addition.get("lat") and not addition.get("lon"),
            "nouvelle édition sans date doit rester sans marqueur")
    trusted["festivals"].append(addition)
    trusted["generatedAt"] = approval["approvedPublic"]["generatedAt"]
    require(len(trusted["festivals"]) == 124, "volume approuvé invalide")
    return trusted


def check_known_calendar(original, published):
    """Vérifie l'état actuel par rapport au cliché 123 ou au delta 124 figé."""
    require(published.get("schema") == 1, "schéma public inconnu")
    if published == original:
        return "reference_originale"
    trusted = approved_calendar(original)
    require(published == trusted, "miroir public non conforme à la version vérifiée")
    return "copie_approuvee_124"


def merge_staged_with_approved(original, staged, trusted):
    """Réapplique des changements indépendamment prouvés sans régresser le public."""
    require(original.get("schema") == staged.get("schema") == trusted.get("schema") == 1,
            "schémas divergents")
    old = original.get("festivals")
    new = staged.get("festivals")
    trusted_rows = trusted.get("festivals")
    require(isinstance(old, list) and isinstance(new, list)
            and isinstance(trusted_rows, list), "calendrier sans liste")
    require(len(new) >= len(old) and
            [x.get("slug") for x in new[:len(old)]] == [x.get("slug") for x in old],
            "fiches de production manquantes ou réordonnées")
    original_by_slug = {r["slug"]: r for r in old}
    out = deepcopy(trusted)
    by_slug = {r["slug"]: r for r in out["festivals"]}
    require(len(by_slug) == len(out["festivals"]), "doublon déjà publié")
    for entry in new:
        slug = entry.get("slug")
        if slug in original_by_slug:
            base = original_by_slug[slug]
            current = by_slug[slug]
            require(all(field in entry for field in base),
                    "champ source supprimé : " + slug)
            # Une mise à jour n'a pas le droit de retirer des artistes ou
            # des sources déjà corroborés dans le cliché approuvé.
            for field, value in entry.items():
                if field in base and value == base[field]:
                    continue
                require(field not in ("slug", "name"),
                        "identité réécrite dans le patch")
                if field == "lineup":
                    old_lineup = base.get("lineup")
                    approved_lineup = current.get("lineup")
                    require(isinstance(old_lineup, list) and isinstance(value, list)
                            and isinstance(approved_lineup, list)
                            and value[:len(old_lineup)] == old_lineup
                            and approved_lineup[:len(old_lineup)] == old_lineup,
                            "programmation non additive : " + slug)
                    for artist in value[len(old_lineup):]:
                        require(isinstance(artist, str) and artist.strip(),
                                "nom d'artiste invalide")
                        if artist not in approved_lineup:
                            approved_lineup.append(artist)
                    continue
                if field == "auditSources":
                    require(isinstance(value, list) and isinstance(current.get(field), list),
                            "sources non fusionnables : " + slug)
                    current[field] = list(dict.fromkeys(current[field] + value))
                    continue
                if field == "bands" and isinstance(entry.get("lineup"), list):
                    # La somme des artistes connus prime sur le chiffre extrait
                    # d'une ancienne photographie partielle du site officiel.
                    require(value == len(entry["lineup"]),
                            "comptage officiel discordant : " + slug)
                    current[field] = len(current["lineup"])
                    continue
                if (field in base and current.get(field) != base.get(field)
                        and current.get(field) != value):
                    # Deux valeurs nouvelles contradictoires : l'ancienne preuve
                    # prévaut sauf si la nouvelle vérification est strictement
                    # postérieure. Ne pas faire de régression silencieuse.
                    require(isinstance(entry.get("lastVerified"), str)
                            and isinstance(current.get("lastVerified"), str)
                            and entry["lastVerified"] > current["lastVerified"],
                            "correction plus ancienne ou conflictuelle : " + slug + "." + field)
                current[field] = deepcopy(value)
            if (isinstance(entry.get("lineup"), list)
                    and entry["lineup"] != base.get("lineup")
                    and isinstance(base.get("lineup"), list)
                    and base.get("bands") == len(base["lineup"])
                    and isinstance(current.get("bands"), int)):
                current["bands"] = len(current["lineup"])
        elif slug in by_slug:
            # Une annonce déjà intégrée et certifiée est idempotente. Le patch
            # cumulatif peut porter une ancienne formulation des notes : on ne
            # la réécrit jamais. Son identité, son statut et ses sources restent
            # néanmoins soumis à contrôle strict avant de l'ignorer.
            require(slug == "muscadeath-2027"
                    and by_slug[slug] == load_approval()["additions"][0],
                    "édition ajoutée inconnue ou modifiée : " + str(slug))
            require(entry.get("slug") == by_slug[slug]["slug"]
                    and entry.get("name") == by_slug[slug]["name"]
                    and entry.get("status") == by_slug[slug]["status"]
                    and entry.get("source") == by_slug[slug]["source"]
                    and entry.get("officialSite") == by_slug[slug]["officialSite"]
                    and entry.get("showOnMap") is False
                    and all(entry.get(k) is None for k in
                            ("startDate", "endDate", "city", "department",
                             "region", "venue", "lat", "lon", "price")),
                    "ancienne proposition incompatible avec l'édition certifiée")
            # Préserver intégralement la fiche approuvée, quelle que soit la
            # rédaction moins récente du patch.
        else:
            require(isinstance(slug, str) and slug and slug not in by_slug,
                    "nouvel identifiant absent ou dupliqué")
            out["festivals"].append(deepcopy(entry))
            by_slug[slug] = out["festivals"][-1]
    if out["festivals"] != trusted["festivals"]:
        require(staged.get("generatedAt"), "date de lot validé absente")
        out["generatedAt"] = staged["generatedAt"]
    return out
