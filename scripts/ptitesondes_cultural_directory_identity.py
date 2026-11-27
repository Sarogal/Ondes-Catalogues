"""Strict identity and address corroboration for the national culture directory.

A directory match is not a publication decision. The caller must obtain the
record from the live exact lookup, authenticate its listed HTTPS page, and
independently verify address, family service, access and coordinates.
This module only binds structured facts to the requested place.
"""
import re
from ptitesondes_family_national_source_preflight import norm_text
from ptitesondes_generic_venue_ign_corroboration import HOUSE


def _text(value, limit):
    if (not isinstance(value, str) or not 1 <= len(value.strip()) <= limit
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        return None
    return value.strip()


def directory_identity(city, venue, row):
    """Exact name/alias, commune, INSEE, postcode and numbered street.

    Do not infer missing postal digits, municipality codes, age, or GPS.
    Both structured street and complete address must agree when present.
    Numberless venues remain in the existing independent OSM pathway.
    """
    try:
        if not isinstance(row, dict):
            return None
        city, venue = _text(city, 180), _text(venue, 180)
        town = _text(row.get("commune"), 180)
        aliases = [_text(row.get(field), 180)
                   for field in ("nom_du_lieu", "nom_usuel_du_lieu")]
        if (not city or not venue or not town or norm_text(city) != norm_text(town)
                or not any(a and norm_text(a) == norm_text(venue) for a in aliases)):
            return None
        insee = row.get("code_commune")
        postcode = row.get("code_postal")
        if (not isinstance(insee, str)
                or not re.fullmatch(r"(?:[0-9]{5}|2[AB][0-9]{3})", insee)
                or not isinstance(postcode, str) or not re.fullmatch(r"[0-9]{5}", postcode)):
            return None
        street_raw = _text(row.get("numero_et_libelle_voie"), 180)
        full_raw = _text(row.get("adresse_complete"), 300)
        if not street_raw or not full_raw:
            return None
        street = norm_text(street_raw)
        m = re.fullmatch(r"([0-9]{1,4}(?: (?:bis|ter|quater|[a-z]))?) (.{3,120})", street)
        if not m or not HOUSE.fullmatch(m.group(1)):
            return None
        number, road = m.groups()
        expected = f"{number} {road} {postcode} {norm_text(city)}"
        if norm_text(full_raw) != expected:
            return None
        # When an entrance address is explicitly present, a differing
        # entrance must not be silently replaced by the postal address.
        entrance = row.get("adresse_entree_public")
        if entrance not in (None, ""):
            text = _text(entrance, 300)
            if not text or norm_text(text) != expected:
                return None
        return {"city": city, "venue": venue, "insee": insee,
                "postcode": postcode, "housenumber": number, "street": road,
                "address_query": f"{number} {road} {postcode} {city}",
                "public_eligible": False}
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, UnicodeError):
        return None


def same_official_address(identity, facts):
    """Compare the directory against freshly extracted first-party page facts."""
    if not isinstance(identity, dict) or not isinstance(facts, dict):
        return False
    required = ("city", "venue", "insee", "postcode", "housenumber", "street", "address_query")
    return all(isinstance(identity.get(k), str) and identity[k]
               and isinstance(facts.get(k), str) and facts[k]
               and norm_text(identity[k]) == norm_text(facts[k])
               for k in required)
