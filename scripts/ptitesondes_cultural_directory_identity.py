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


def address_format(value, street, postcode, city):
    """Only exact permutations of known components; never discard extra tokens."""
    text = _text(value, 300)
    if text is None:
        return None
    n = norm_text(text)
    street, city = norm_text(street), norm_text(city)
    variants = {
        f"{street} {postcode} {city}": "full",
        f"{street} {city} {postcode}": "city_before_postcode",
        f"{street} {postcode} {city} france": "country_suffix",
        f"{street} {city} {postcode} france": "country_suffix",
        street: "street_only",
        f"{street} {postcode}": "street_postcode",
        f"{street} {city}": "street_city",
    }
    return variants.get(n)


def directory_identity(city, venue, row, diagnostics=None, *, equivalent_formats=True):
    """Exact name/alias, commune, INSEE, postcode and numbered street.

    Do not infer missing postal digits, municipality codes, age, or GPS.
    Both structured street and complete address must agree when present.
    Numberless venues remain in the existing independent OSM pathway.
    """
    def reject(reason):
        if diagnostics is not None:
            diagnostics[reason] += 1
        return None
    try:
        if not isinstance(row, dict):
            return reject('directory_record_missing')
        city, venue = _text(city, 180), _text(venue, 180)
        town = _text(row.get("commune"), 180)
        aliases = [_text(row.get(field), 180)
                   for field in ("nom_du_lieu", "nom_usuel_du_lieu")]
        if (not city or not venue or not town or norm_text(city) != norm_text(town)
                or not any(a and norm_text(a) == norm_text(venue) for a in aliases)):
            return reject('name_or_commune_mismatch')
        insee = row.get("code_commune")
        postcode = row.get("code_postal")
        if (not isinstance(insee, str)
                or not re.fullmatch(r"(?:[0-9]{5}|2[AB][0-9]{3})", insee)
                or not isinstance(postcode, str) or not re.fullmatch(r"[0-9]{5}", postcode)):
            return reject("administrative_code_format")
        street_raw = _text(row.get("numero_et_libelle_voie"), 180)
        full_raw = _text(row.get("adresse_complete"), 300)
        if not street_raw or not full_raw:
            return reject("address_field_missing_or_invalid")
        street = norm_text(street_raw)
        m = re.fullmatch(r"([0-9]{1,4}(?: (?:bis|ter|quater|[a-z]))?) (.{3,120})", street)
        if not m or not HOUSE.fullmatch(m.group(1)):
            return reject("numbered_street_missing")
        number, road = m.groups()
        expected = f"{number} {road} {postcode} {norm_text(city)}"
        style = address_format(full_raw, street, postcode, city)
        if style is None or (not equivalent_formats and style != "full"):
            return reject("complete_address_mismatch")
        # Structured postcode and commune are mandatory above. The official
        # site and independent BAN still have to match the complete address.
        # When an entrance address is explicitly present, a differing
        # entrance must not be silently replaced by the postal address.
        entrance = row.get("adresse_entree_public")
        if entrance not in (None, ""):
            text = _text(entrance, 300)
            entrance_style = address_format(text, street, postcode, city)
            if entrance_style is None or (not equivalent_formats and entrance_style != "full"):
                return reject("entrance_address_mismatch")
        return {"city": city, "venue": venue, "insee": insee,
                "postcode": postcode, "housenumber": number, "street": road,
                "address_query": f"{number} {road} {postcode} {city}",
                "public_eligible": False}
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, UnicodeError):
        return reject("invalid_record")


def same_official_address(identity, facts):
    """Compare the directory against freshly extracted first-party page facts."""
    if not isinstance(identity, dict) or not isinstance(facts, dict):
        return False
    required = ("city", "venue", "insee", "postcode", "housenumber", "street", "address_query")
    return all(isinstance(identity.get(k), str) and identity[k]
               and isinstance(facts.get(k), str) and facts[k]
               and norm_text(identity[k]) == norm_text(facts[k])
               for k in required)


def live_address_probe():
    """Inspect up to 240 public rows; emit counts, never venue data."""
    from collections import Counter
    from urllib.parse import urlencode
    from ptitesondes_national_cultural_directory_probe import URL, _fetch, directory_website_hints
    from ptitesondes_cultural_directory_discovery import PAGE_SIZE, parse_page, identity, is_family_lead
    counts = Counter()
    family_counts = Counter()
    baseline_counts = Counter()
    baseline_family = Counter()
    examined = 0
    for page in range(1, 13):
        doc = _fetch(URL.split("?")[0] + "?" + urlencode({"page": page, "page_size": PAGE_SIZE}))
        _, total = parse_page(doc, page)
        for row in doc["data"]:
            examined += 1
            pair = identity(row)
            local = Counter()
            if pair is None:
                local["discovery_identity_missing"] += 1
            elif directory_identity(*pair, row, local) is not None:
                local["address_verified"] += 1
            counts.update(local)
            baseline = Counter()
            if pair is None:
                baseline["discovery_identity_missing"] += 1
            elif directory_identity(*pair, row, baseline, equivalent_formats=False) is not None:
                baseline["address_verified"] += 1
            baseline_counts.update(baseline)
            if is_family_lead(row):
                baseline_family.update(baseline)
                family_counts.update(local)
                family_counts["family_rows"] += 1
                urls = directory_website_hints(row)
                family_counts["website_unique" if len(urls) == 1 else
                              "website_missing" if not urls else "website_multiple"] += 1
        if page * PAGE_SIZE >= total:
            break
    return {"rows_examined": examined, "address_counts": dict(counts),
            "family_counts": dict(family_counts), "baseline_address_counts": dict(baseline_counts),
            "baseline_family_counts": dict(baseline_family),
            "publication_ready": False, "public_writes": 0}


if __name__ == "__main__":
    import json
    try:
        print(json.dumps(live_address_probe(), sort_keys=True))
    except (OSError, ValueError, TypeError, KeyError, OverflowError, UnicodeError):
        print("::error::National address probe unavailable")
        raise SystemExit(1) from None
