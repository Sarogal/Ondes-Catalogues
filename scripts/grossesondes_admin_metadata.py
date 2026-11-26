"""Enrich only missing administrative metadata on already signed commune pins.

The signed INSEE code selects one fixed government endpoint. No private
candidate URL, guessed town or historical venue is authority. Never change
coordinates, dates, map visibility, artist names, prices or existing metadata.
"""
from copy import deepcopy
from datetime import date
import json
import re
import ssl
from urllib.parse import urlencode

from dns_pinned_https import DNSPinnedHTTPSConnection
from official_admin_communes import normalize
from grossesondes_admin_marker import valid_commune_marker_identity

HOST = "geo.api.gouv.fr"
FIELDS = "nom,code,codeDepartement,departement,codeRegion,region"
MAX_BYTES = 32000
MAX_CHECKS = 20
REGIONS = {
    "01": "Guadeloupe", "02": "Martinique", "03": "Guyane",
    "04": "La Réunion", "06": "Mayotte", "11": "Île-de-France",
    "24": "Centre-Val de Loire", "27": "Bourgogne-Franche-Comté",
    "28": "Normandie", "32": "Hauts-de-France", "44": "Grand Est",
    "52": "Pays de la Loire", "53": "Bretagne", "75": "Nouvelle-Aquitaine",
    "76": "Occitanie", "84": "Auvergne-Rhône-Alpes",
    "93": "Provence-Alpes-Côte d'Azur", "94": "Corse",
}
PROOF_MODES = {
    "current-edition-commune-two-day.v1",
    "current-edition-commune-direct-official.v1",
    "signed-city-current-edition-centre.v1",
}


def endpoint(code):
    if not isinstance(code, str) or re.fullmatch(r"[0-9AB]{5}", code) is None:
        raise ValueError("Invalid signed commune code")
    return "/communes/" + code + "?" + urlencode({"fields": FIELDS})


def fetch_metadata(code):
    path = endpoint(code)
    conn = DNSPinnedHTTPSConnection(HOST, port=443, timeout=10,
                                    context=ssl.create_default_context())
    try:
        conn.request("GET", path, headers={"Host": HOST,
            "User-Agent": "GrossesOndesCommuneMetadata/1.0",
            "Accept": "application/json", "Accept-Encoding": "identity"})
        response = conn.getresponse()
        raw = response.read(MAX_BYTES + 1)
        if (response.status != 200 or len(raw) > MAX_BYTES
                or response.getheader("content-type", "").split(";", 1)[0].strip().lower() != "application/json"
                or response.getheader("content-encoding", "identity").lower() != "identity"):
            raise ValueError("Unusable government metadata")
        return json.loads(raw.decode("utf-8"))
    finally:
        conn.close()


def eligible(row, today):
    if not isinstance(row, dict):
        return False
    proof = row.get("geoVerification")
    if (row.get("geoPrecision") != "commune" or row.get("showOnMap") is not True
            or not isinstance(proof, dict) or proof.get("proofMode") not in PROOF_MODES
            or proof.get("markerMeaning") != "centre_indicatif_de_commune"
            or proof.get("officialSite") != row.get("officialSite")
            or not valid_commune_marker_identity(row)
            or not isinstance(row.get("geoInsee"), str)
            or not re.fullmatch(r"[0-9AB]{5}", row["geoInsee"])
            or row.get("status") in ("Annulé", "Reporté")
            or (row.get("department") not in (None, "") and row.get("region") not in (None, ""))):
        return False
    try:
        end = row.get("endDate") or row.get("startDate")
        return (end is None or date.fromisoformat(end) >= date.fromisoformat(today))
    except (ValueError, TypeError):
        return False


def certified_values(row, payload):
    if not isinstance(payload, dict) or payload.get("code") != row.get("geoInsee"):
        return None
    name = payload.get("nom")
    dep, reg = payload.get("codeDepartement"), payload.get("codeRegion")
    d, region = payload.get("departement"), payload.get("region")
    if (not isinstance(name, str) or normalize(name) != normalize(row["geoCity"])
            or not isinstance(dep, str) or not re.fullmatch(r"[0-9AB]{2,3}", dep)
            or not row["geoInsee"].startswith(dep)
            or not isinstance(reg, str) or reg not in REGIONS
            or not isinstance(d, dict) or d.get("code") != dep
            or not isinstance(region, dict) or region.get("code") != reg
            or region.get("nom") != REGIONS[reg]):
        return None
    values = {"department": dep, "region": REGIONS[reg]}
    if any(row.get(k) not in (None, "", v) for k, v in values.items()):
        return None
    return values


def apply(target, signed, today, *, reader=fetch_metadata, limit=MAX_CHECKS):
    if type(limit) is not int or not 0 <= limit <= MAX_CHECKS:
        raise ValueError("Invalid administrative budget")
    out = deepcopy(target)
    by_slug = {row["slug"]: row for row in signed["festivals"] if eligible(row, today)}
    report = {"checked": 0, "accepted": [], "unavailable": 0}
    cache = {}
    for row in out["festivals"]:
        old = by_slug.get(row["slug"])
        # A concurrent update to the marker or its identity requires a later
        # independently signed pass, not authority from the previous point.
        identity = ("city", "geoCity", "geoInsee", "geoSource", "geoPrecision",
                    "geoVerification", "lat", "lon", "showOnMap", "officialSite",
                    "department", "region")
        if old is None or any(row.get(k) != old.get(k) for k in identity):
            continue
        code = old["geoInsee"]
        try:
            if code not in cache:
                if report["checked"] >= limit:
                    continue
                report["checked"] += 1
                cache[code] = None
                cache[code] = reader(code)
            values = certified_values(old, cache[code])
        except (OSError, ValueError, TypeError, UnicodeError, KeyError, RecursionError):
            values = None
        if not values:
            report["unavailable"] += 1
            continue
        fields = {}
        for key, value in values.items():
            if row.get(key) in (None, ""):
                row[key] = value
                fields[key] = value
        if fields:
            report["accepted"].append({"slug": row["slug"], "fields": fields,
                "source": "https://" + HOST + endpoint(code)})
    validate_delta(target, out, report)
    return out, report


def validate_delta(before, after, report):
    """The isolated stage can change ONLY exactly the reported missing fields."""
    accepted = {x["slug"]: x["fields"] for x in report["accepted"]}
    if len(accepted) != len(report["accepted"]):
        raise ValueError("Duplicate administrative proof")
    expected = deepcopy(before)
    for row in expected["festivals"]:
        fields = accepted.pop(row["slug"], {})
        if not set(fields) <= {"department", "region"}:
            raise ValueError("Unexpected administrative field")
        for key, value in fields.items():
            if row.get(key) not in (None, "") or not isinstance(value, str) or not value:
                raise ValueError("Administrative replacement forbidden")
            row[key] = value
    if accepted or expected != after:
        raise ValueError("Administrative stage changed unrelated data")
