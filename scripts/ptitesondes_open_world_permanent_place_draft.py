"""Build a complete candidate record from independently fetched place sources.

Preview only: no writes, no admission permission, no guessed prices or ages.
Require an exact official address block, an explicit family service, visible
public access, OSM identity, and the administrative municipality at the point.
"""
from datetime import date
import json
import math
import re
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

from ptitesondes_family_national_source_preflight import _Visibility, norm_text
from ptitesondes_open_world_permanent_place_evidence import corroborate_place, mapped_place_kind
from ptitesondes_places import validate, norm

GEO_API = "https://geo.api.gouv.fr/communes"
MAX_BYTES = 150000
MAX_BLOCKS = 500
ACTIVITIES = (
    (r"\b(?:espace|section|rayon|fonds) (?:pour les )?(?:enfants|jeunesse)\b",
     "espace jeunesse"),
    (r"\b(?:livres|albums|lecture) (?:pour (?:les )?enfants|jeunesse)\b",
     "lecture jeunesse"),
    (r"\b(?:espace de jeux pour enfants|jeux et jouets|jeux pour enfants)\b",
     "jeux pour enfants"),
    (r"\b(?:contes pour enfants|heure du conte)\b", "contes"),
    (r"\beveil musical\b", "éveil musical"),
    (r"\bateliers (?:pour les )?enfants\b", "ateliers pour enfants"),
    (r"\b(?:spectacles?|theatre) (?:pour (?:les )?enfants|jeune public)\b", "spectacles jeune public"),
    (r"\b(?:expositions?|parcours) (?:interactifs?|interactives?) (?:pour les enfants|jeune public)\b", "expositions interactives pour enfants"),
    (r"\beveil artistique\b", "éveil artistique"),
    (r"\b(?:ateliers?|espaces?) sensoriel(?:s|les)? (?:pour les enfants|pour les tout petits)\b", "éveil sensoriel"),
)
ACCESS = (
    (r"\bconsultation sur place libre et gratuite\b", "consultation sur place libre et gratuite"),
    (r"\bacces libre et gratuit\b", "accès libre et gratuit"),
    (r"\bentree libre et gratuite\b", "entrée libre et gratuite"),
    (r"\bacces libre\b", "accès libre"),
    (r"\bentree libre\b", "entrée libre"),
    (r"\bouvert(?:e)? a tous\b", "ouvert à tous — tarif à vérifier"),
    (r"\bouvert(?:e)? au public\b", "ouvert au public — tarif à vérifier"),
)
RESTRICTED = re.compile(r"\b(?:non ouvert(?:e)?|pas ouvert(?:e)?|fermeture temporaire|"
                        r"uniquement sur invitation|reserve aux adherents|"
                        r"reserve aux professionnels|acces interdit|"
                        r"acces reserve|ferme au public|fermee au public|"
                        r"(?:pas de|aucun(?:e)?|sans) (?:jeux|jouets|espace jeunesse|"
                        r"section jeunesse|ateliers? (?:pour les )?enfants|lecture jeunesse)|"
                        r"interdit aux enfants)\b")


# The general cultural facility's category is insufficient: require an
# explicit statement in its own visible main content of a dedicated
# permanent youth vocation, not just a one-off event or family discount.
DEDICATED = {
    "museum": (
        r"\b(?:musee (?:entierement )?(?:dedie|consacre|destine) "
        r"(?:aux enfants|au jeune public)|musee (?:pour les enfants|des enfants))\b",
        "musee-enfants", "Musée pour enfants",
    ),
    "theatre": (
        r"\b(?:theatre (?:entierement )?(?:dedie|consacre|destine) "
        r"(?:aux enfants|au jeune public)|theatre jeune public)\b",
        "theatre-jeune-public", "Théâtre jeune public",
    ),
    "arts_centre": (
        r"\b(?:centre d eveil artistique|centre d art (?:entierement )?"
        r"(?:dedie|consacre|destine) (?:aux enfants|au jeune public))\b",
        "centre-eveil-artistique", "Centre d'éveil artistique",
    ),
}


def place_category(tags, blocks):
    kind = mapped_place_kind(tags)
    if kind == "toy_library":
        return "ludotheque", "Ludothèque"
    if kind == "library":
        return "mediatheque-jeunesse", "Bibliothèque / médiathèque jeunesse"
    if kind not in DEDICATED:
        return None
    pattern, category, label = DEDICATED[kind]
    if any(re.search(pattern, b) for b in blocks):
        return category, label
    return None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_admin(lat, lng):
    if (type(lat) not in (int, float) or type(lng) not in (int, float)
            or not math.isfinite(lat) or not math.isfinite(lng)
            or not -90 <= lat <= 90 or not -180 <= lng <= 180):
        raise ValueError("invalid_place_admin_point")
    url = GEO_API + "?" + urlencode({"lat": lat, "lon": lng,
        "fields": "nom,code,codesPostaux,codeDepartement,departement,codeRegion,region",
        "format": "json"})
    request = Request(url, headers={"Accept": "application/json",
                                    "User-Agent": "PtitesOndesPlaceAdmin/1.0"})
    with build_opener(NoRedirect()).open(request, timeout=15) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("invalid_place_admin_response")
        raw = response.read(MAX_BYTES + 1)
    if not 0 < len(raw) <= MAX_BYTES:
        raise ValueError("invalid_place_admin_size")
    return json.loads(raw)


def administrative_identity(response, city, postcode):
    # Coordinate lookup must return exactly one matching municipality. No
    # inferred department by postal prefix and no fallback to a city centre.
    if not isinstance(response, list) or len(response) != 1:
        return None
    row = response[0]
    if (not isinstance(row, dict) or norm(row.get("nom")) != norm(city)
            or not isinstance(row.get("codesPostaux"), list)
            or postcode not in row["codesPostaux"]
            or not re.fullmatch(r"[0-9A-Z]{5}", str(row.get("code") or ""))):
        return None
    d, g = row.get("departement"), row.get("region")
    if any(not isinstance(x, dict) or not isinstance(x.get("nom"), str)
           or not x["nom"].strip() or not isinstance(x.get("code"), str)
           or not x["code"] for x in (d, g)):
        return None
    if d["code"] != row.get("codeDepartement") or g["code"] != row.get("codeRegion"):
        return None
    return d["nom"], g["nom"]


class MainBlocks(_Visibility):
    """Only explicit main/article content; exclude navigation and sidebars."""
    def __init__(self):
        super().__init__()
        self.active = []
        self.blocks = []
        self.seen_main = False

    def handle_starttag(self, tag, attrs):
        attrs = list(attrs)
        if tag in ("header", "footer", "nav", "aside"):
            attrs.append(("hidden", ""))
        hidden = super().handle_starttag(tag, attrs)
        if not hidden and tag in ("main", "article"):
            self.seen_main = True
        in_main = any(t in ("main", "article") and not h for t, h in self.elements)
        if not hidden and in_main and tag in ("p", "li", "address"):
            self.active.append((tag, []))

    def handle_data(self, data):
        if not self._hidden():
            for _, words in self.active:
                words.append(data)

    def handle_endtag(self, tag):
        if self.active and self.active[-1][0] == tag and not self._hidden():
            _, words = self.active.pop()
            self.blocks.append(norm_text(" ".join(words)))
            if len(self.blocks) > MAX_BLOCKS:
                raise ValueError("too_many_place_blocks")
        super().handle_endtag(tag)


def build_draft(city, venue, postcode, url, html, osm, admin, today):
    """Return a schema-valid candidate, not approval to publish."""
    try:
        if type(today) is not date:
            return None
        proof = corroborate_place(city, venue, postcode, url, html, osm)
        if proof is None:
            return None
        ident = administrative_identity(admin, city, postcode)
        if ident is None:
            return None
        node_id = int(proof["osm_object"].split("/")[1])
        nodes = [v for v in osm["elements"] if v.get("type") == "node"
                 and v.get("id") == node_id]
        if len(nodes) != 1:
            return None
        tags = nodes[0]["tags"]
        street = tags["addr:street"]
        number = tags.get("addr:housenumber")
        if (not isinstance(street, str) or not 3 <= len(street) <= 160
                or (number is not None and (not isinstance(number, str)
                    or not re.fullmatch(r"[0-9]{1,5}(?:[ -]?(?:bis|ter|quater|[a-z]))?", number, re.I)))):
            return None
        address = " ".join(x for x in (number, street) if x)
        address_n = norm_text(address)
        expected = address_n + " " + postcode + " " + norm_text(city)
        parser = MainBlocks()
        parser.feed(html)
        parser.close()
        blocks = parser.blocks
        if (not parser.seen_main or expected not in blocks
                or any(RESTRICTED.search(b) for b in blocks)):
            return None
        acts = [label for pattern, label in ACTIVITIES
                if any(re.search(pattern, b) for b in blocks)]
        admission = next((label for pattern, label in ACCESS
                          if any(re.search(pattern, b) for b in blocks)), None)
        if not acts or admission is None:
            return None
        category = place_category(tags, blocks)
        if category is None:
            return None
        result = {
            "id": "osm-node-" + str(node_id), "name": venue, "kind": "lieu-permanent",
            "category": category[0], "category_label": category[1],
            "city": city, "department": ident[0], "region": ident[1],
            "postal_code": postcode, "address": address + ", " + postcode + " " + city,
            "lat": proof["lat"], "lng": proof["lng"], "geo_precision": "lieu",
            "age_min": None, "age_max": None, "admission": admission, "activities": acts,
            "reservation_note": "Vérifier les horaires, tarifs et modalités de réservation sur le site officiel.",
            "official_url": url, "geo_source_url": proof["geo_source_url"],
            "reviewed_at": today.isoformat(), "is_publicly_accessible": True,
        }
        validate({"version": 1, "updated_at": today.isoformat(), "places": [result]})
        return result
    except (ValueError, TypeError, KeyError, OverflowError, UnicodeError):
        return None
