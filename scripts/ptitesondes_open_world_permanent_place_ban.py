"""Independent official municipal place + BAN proof, without Overpass.

Offline evidence primitive. Inputs must be freshly fetched by the caller.
Never grants publication permission or derives a coordinate from a street or
commune centroid. Numberless places remain eligible for the existing route.
"""
import math
import re
from urllib.parse import urlsplit

from ptitesondes_family_national_source_preflight import norm_text
from ptitesondes_dila_municipal_domains import approved_municipal_page_host
from ptitesondes_generic_venue_ign_corroboration import HOUSE, MIN_SCORE, MAX_FEATURES
from ptitesondes_open_world_permanent_place_draft import (
    MainBlocks, ACTIVITIES, ACCESS, RESTRICTED, DEDICATED, administrative_identity,
)
from ptitesondes_open_world_permanent_place_evidence import CLOSED, MAX_HTML


class PlaceMain(MainBlocks):
    """Bind the exact visible H1 to the same main/article as the facts."""
    def __init__(self):
        super().__init__()
        self.headings = []
        self.heading = None

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if (tag == "h1" and not self._hidden()
                and any(t in ("main", "article") and not h for t, h in self.elements)):
            self.heading = []

    def handle_data(self, data):
        super().handle_data(data)
        if self.heading is not None and not self._hidden():
            self.heading.append(data)

    def handle_endtag(self, tag):
        if tag == "h1" and self.heading is not None:
            self.headings.append(norm_text(" ".join(self.heading)))
            self.heading = None
        super().handle_endtag(tag)


def official_facts(city, venue, url, html, directory):
    """Exact first-party identity and visible permanent family service."""
    try:
        town, name = norm_text(city), norm_text(venue)
        p = urlsplit(url)
        if (not town or not name or town == name or not p.path.strip("/")
                or p.query or p.fragment
                or not approved_municipal_page_host(url, city, directory)
                or not isinstance(html, str) or not 50 <= len(html) <= MAX_HTML):
            return None
        codes = {str(r.get("code_insee_commune")) for r in directory["results"]
                 if isinstance(r, dict)
                 and norm_text(r.get("nom")) == norm_text("Mairie - " + city)}
        if len(codes) != 1:
            return None
        insee = next(iter(codes))
        if not re.fullmatch(r"(?:[0-9]{5}|2[AB][0-9]{3})", insee):
            return None
        parser = PlaceMain()
        parser.feed(html)
        parser.close()
        blocks = parser.blocks
        if (parser.headings != [name] or not parser.seen_main
                or any(RESTRICTED.search(b) or CLOSED.search(b) for b in blocks)):
            return None
        # Exactly one explicit numbered address in the main content.
        # Other postcode-bearing addresses are not silently ignored.
        addresses = []
        for b in blocks:
            m = re.fullmatch(r"([0-9]{1,4}(?: (?:bis|ter|quater|[a-z]))?) (.{3,120}) ([0-9]{5}) (.{2,120})", b)
            if m and HOUSE.fullmatch(m.group(1)):
                addresses.append(m.groups())
        if len(set(addresses)) != 1:
            return None
        number, street, postcode, address_city = addresses[0]
        if address_city != town:
            return None
        activities = [label for pattern, label in ACTIVITIES
                      if any(re.search(pattern, b) for b in blocks)]
        admission = next((label for pattern, label in ACCESS
                          if any(re.search(pattern, b) for b in blocks)), None)
        if not activities or admission is None:
            return None
        kinds = set()
        if re.search(r"\bludotheque\b", name):
            kinds.add(("ludotheque", "Ludothèque"))
        if re.search(r"\b(?:bibliotheque|mediatheque)\b", name):
            kinds.add(("mediatheque-jeunesse", "Bibliothèque / médiathèque jeunesse"))
        for pattern, category, label in DEDICATED.values():
            if any(re.search(pattern, b) for b in blocks):
                kinds.add((category, label))
        if len(kinds) != 1:
            return None
        category, label = kinds.pop()
        return {"city": city, "venue": venue, "official_url": url,
                "insee": insee, "postcode": postcode, "housenumber": number,
                "street": street, "address_query": f"{number} {street} {postcode} {city}",
                "category": category, "category_label": label,
                "activities": activities, "admission": admission,
                "public_eligible": False}
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, UnicodeError):
        return None


def exact_ban_point(facts, response):
    """Require one exact numbered BAN address in the authenticated commune."""
    try:
        if (not isinstance(response, dict) or response.get("type") != "FeatureCollection"
                or not isinstance(response.get("features"), list)
                or len(response["features"]) > MAX_FEATURES):
            return None
        matches = []
        for feature in response["features"]:
            if not isinstance(feature, dict) or feature.get("type") != "Feature":
                continue
            p, g = feature.get("properties"), feature.get("geometry")
            if not isinstance(p, dict) or not isinstance(g, dict):
                continue
            score = p.get("score")
            if (p.get("type") != "housenumber" or p.get("citycode") != facts["insee"]
                    or p.get("postcode") != facts["postcode"]
                    or norm_text(p.get("city")) != norm_text(facts["city"])
                    or norm_text(p.get("housenumber")) != norm_text(facts["housenumber"])
                    or norm_text(p.get("street")) != norm_text(facts["street"])
                    or norm_text(p.get("label")) != norm_text(facts["address_query"])
                    or type(score) not in (int, float) or not math.isfinite(score)
                    or not MIN_SCORE <= score <= 1):
                continue
            coords = g.get("coordinates")
            if (g.get("type") != "Point" or not isinstance(coords, list) or len(coords) != 2
                    or not all(type(x) in (int, float) and math.isfinite(x) for x in coords)
                    or not -180 <= coords[0] <= 180 or not -90 <= coords[1] <= 90):
                continue
            matches.append((coords[1], coords[0]))
        return matches[0] if len(matches) == 1 else None
    except (ValueError, TypeError, KeyError, OverflowError):
        return None


def corroborate_official_ban(city, venue, url, html, directory, ban_fetch, admin_fetch):
    """No OSM dependency; return only a private, independently located hint."""
    facts = official_facts(city, venue, url, html, directory)
    if facts is None:
        return None
    try:
        point = exact_ban_point(facts, ban_fetch(facts))
        if point is None:
            return None
        admin = admin_fetch(*point)
        ident = administrative_identity(admin, city, facts["postcode"])
        if ident is None or admin[0].get("code") != facts["insee"]:
            return None
        return {**facts, "lat": point[0], "lng": point[1],
                "department": ident[0], "region": ident[1],
                "method": "dila_official_place_address_plus_ban",
                "publication_ready": False, "public_writes": 0}
    except (OSError, ValueError, TypeError, KeyError, OverflowError, UnicodeError):
        return None


def discover_official_ban(row, *, directory_fetch=None, page_read=None,
                          ban_fetch=None, admin_fetch=None):
    """Use an untrusted venue URL or exact municipal homepage link as a hint.

    Every page is authenticated by a fresh DILA result before network access.
    No external crawling, manual venue registry, or reuse of old coordinates.
    """
    from ptitesondes_dila_municipal_domains import fetch_dila, municipal_site_hosts
    from ptitesondes_municipal_venue_link_discovery import exact_named_venue_page
    from ptitesondes_unlisted_source_safe_recheck import read_unknown_https
    from ptitesondes_generic_venue_ign_corroboration import fetch_ign
    from ptitesondes_open_world_permanent_place_draft import fetch_admin
    directory_fetch = directory_fetch or fetch_dila
    page_read = page_read or read_unknown_https
    ban_fetch = ban_fetch or fetch_ign
    admin_fetch = admin_fetch or fetch_admin
    try:
        city, venue = row["city"], row["venue"]
        directory = directory_fetch(city)
        hosts = municipal_site_hosts(city, directory)
        if not hosts:
            return None
        hint = row.get("possible_website_unverified")
        pages = []
        if approved_municipal_page_host(hint, city, directory):
            p = urlsplit(hint)
            if p.path.strip("/") and not p.query and not p.fragment:
                pages.append(hint)
        # At most one authenticated homepage, and one exact visible venue link.
        home = "https://" + sorted(hosts)[0] + "/"
        for url in pages:
            try:
                proof = corroborate_official_ban(city, venue, url, page_read(url),
                                                 directory, ban_fetch, admin_fetch)
                if proof is not None:
                    historical = row.get("historical_address_unverified")
                    if isinstance(historical, dict) and historical.get("postal_code") not in (None, proof["postcode"]):
                        return None
                    return proof
            except (OSError, ValueError, TypeError, UnicodeError):
                pass
        url = exact_named_venue_page(venue, home, page_read(home), city, directory)
        if not url or url in pages:
            return None
        proof = corroborate_official_ban(city, venue, url, page_read(url),
                                         directory, ban_fetch, admin_fetch)
        historical = row.get("historical_address_unverified")
        if proof is not None and isinstance(historical, dict) and historical.get("postal_code") not in (None, proof["postcode"]):
            return None
        return proof
    except (OSError, ValueError, TypeError, KeyError, OverflowError, UnicodeError):
        return None
