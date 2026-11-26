"""Open-world permanent-place evidence, offline and read-only.

Inputs are fresh independently fetched official HTML and OSM data, not private
assertions. This is an evidence primitive, not a publication permission.
No network access, venue registry, city registry or fabricated access facts.
"""
import math
import re
from ptitesondes_family_national_source_preflight import _Visibility, norm_text
from ptitesondes_delegated_source_authority import _url_host, _same_host
from ptitesondes_independent_venue_site_proof import _osm_website_host

MAX_HTML = 450000
PUBLIC_ACCESS = re.compile(r"\b(?:ouvert(?:e)? a tous|ouvert(?:e)? au public|"
                           r"acces libre|entree libre|consultation sur place libre)\b")
CHILDREN = re.compile(r"\b(?:enfants|jeune public|jeunesse|tout petits|ludotheque)\b")
CLOSED = re.compile(r"\b(?:fermeture definitive|definitivement ferme|"
                    r"ferme au public|fermee au public|reserve aux professionnels)\b")


def contains(text, value):
    return bool(value and re.search(r"\b" + re.escape(value) + r"\b", text))


class VenuePage(_Visibility):
    """Use a single visible H1 and visible page content, never hidden anchors."""
    def __init__(self):
        super().__init__()
        self.words = []
        self.headings = []
        self.heading = None

    def handle_starttag(self, tag, attrs):
        hidden = super().handle_starttag(tag, attrs)
        if not hidden and tag == "h1":
            self.heading = []

    def handle_data(self, data):
        if not self._hidden():
            self.words.append(data)
            if self.heading is not None:
                self.heading.append(data)

    def handle_endtag(self, tag):
        if tag == "h1" and not self._hidden() and self.heading is not None:
            self.headings.append(norm_text(" ".join(self.heading)))
            self.heading = None
        super().handle_endtag(tag)


def corroborate_place(city, venue, postcode, official_url, html, osm):
    """Return a conservative private evidence record or None.

    Start with exact OSM nodes for libraries and toy libraries. Other
    categories, ways, relations and unresolved identities remain pending.
    A numberless address may be corroborated by the exact named node and
    independently visible street, postcode and city; no street centroid.
    """
    try:
        city_n, name = norm_text(city), norm_text(venue)
        host = _url_host(official_url)
        if (not city_n or not name or name == city_n or not host
                or not isinstance(postcode, str) or not re.fullmatch(r"\d{5}", postcode)
                or not isinstance(html, str) or not 50 <= len(html) <= MAX_HTML
                or not isinstance(osm, dict) or osm.get("remark")
                or not isinstance(osm.get("elements"), list)
                or not 1 <= len(osm["elements"]) < 120):
            return None
        matches = []
        for obj in osm["elements"]:
            if not isinstance(obj, dict) or not isinstance(obj.get("tags"), dict):
                continue
            tags = obj["tags"]
            if norm_text(tags.get("name")) != name:
                continue
            # A different explicit municipality is unrelated, but an
            # unlocated homonym is ambiguous and must not select a GPS.
            tagged_city = norm_text(tags.get("addr:city"))
            if tagged_city and tagged_city != city_n:
                continue
            matches.append(obj)
        if len(matches) != 1:
            return None
        obj = matches[0]
        tags = obj["tags"]
        oid = obj.get("id")
        street = norm_text(tags.get("addr:street"))
        number = tags.get("addr:housenumber")
        if (obj.get("type") != "node" or type(oid) is not int or oid <= 0
                or tags.get("amenity") not in ("library", "toy_library")
                or norm_text(tags.get("addr:city")) != city_n
                or tags.get("addr:postcode") != postcode or not street
                or tags.get("access") in ("private", "no", "customers")
                or tags.get("disused") == "yes" or tags.get("abandoned") == "yes"
                or (tags.get("addr:country") and
                    norm_text(tags["addr:country"]) not in ("fr", "france"))
                or (number is not None and not norm_text(number))):
            return None
        sites = [tags[k] for k in ("website", "contact:website") if k in tags]
        hosts = [_osm_website_host(v) for v in sites]
        if not hosts or any(h is None or not _same_host(h, host) for h in hosts):
            return None
        lat, lng = obj.get("lat"), obj.get("lon")
        if (type(lat) not in (int, float) or type(lng) not in (int, float)
                or not math.isfinite(lat) or not math.isfinite(lng)
                or not -90 <= lat <= 90 or not -180 <= lng <= 180):
            return None
        parser = VenuePage()
        parser.feed(html)
        parser.close()
        body = norm_text(" ".join(parser.words))
        street_address = (norm_text(number) + " " + street).strip() if number else street
        if (parser.headings != [name] or not contains(body, street_address)
                or not contains(body, postcode + " " + city_n)
                or not CHILDREN.search(body) or not PUBLIC_ACCESS.search(body)
                or CLOSED.search(body)):
            return None
        return {
            "status": "independent_place_evidence_requires_publication_review",
            "city": city, "venue": venue, "postal_code": postcode,
            "official_url": official_url, "osm_object": f"node/{oid}",
            "geo_source_url": f"https://www.openstreetmap.org/node/{oid}",
            "lat": lat, "lng": lng,
            "address_number_present": number is not None,
            "public_eligible": False,
        }
    except (ValueError, TypeError, KeyError, OverflowError, UnicodeError):
        return None
