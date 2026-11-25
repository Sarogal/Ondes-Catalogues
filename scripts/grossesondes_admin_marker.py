"""Shape validation for independently published indicative commune markers."""
import re
from urllib.parse import urlencode

COG_URL = "https://www.insee.fr/fr/statistiques/fichier/8740222/v_mvt_commune_2026.csv"
PROOF_KEYS = {"proofMode", "firstObserved", "verifiedAt", "officialSite", "markerMeaning"}
HISTORICAL_KEYS = {"historicalInsee", "historicalSource"}


def historical_proof(resolved):
    return {k: resolved[k] for k in HISTORICAL_KEYS if k in resolved}


def valid_commune_marker_identity(row):
    proof = row.get("geoVerification")
    if not isinstance(proof, dict):
        return False
    source = row.get("geoSource")
    city, parent = row.get("city"), row.get("geoCity")
    if not isinstance(source, str) or not isinstance(city, str) or not isinstance(parent, str):
        return False
    if set(proof) == PROOF_KEYS:
        return city == parent and source.startswith((
            "https://geo.api.gouv.fr/communes?",
            "https://geo.api.gouv.fr/communes_associees_deleguees?"))
    if (set(proof) != PROOF_KEYS | HISTORICAL_KEYS
            or proof.get("historicalSource") != COG_URL
            or not isinstance(proof.get("historicalInsee"), str)
            or re.fullmatch(r"[0-9AB]{5}", proof["historicalInsee"]) is None
            or city == parent or not 2 <= len(parent) <= 80
            or not re.fullmatch(r"[\wÀ-ÿ .'()\-]+", parent, re.U)):
        return False
    expected = "https://geo.api.gouv.fr/communes?" + urlencode({
        "nom": parent, "fields": "nom,code,codeDepartement,departement,centre",
        "format": "geojson", "geometry": "centre", "zone": "metro,drom,com",
    })
    return source == expected
