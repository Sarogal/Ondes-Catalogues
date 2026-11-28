"""Independent official municipal place + BAN proof, without Overpass.

Offline evidence primitive. Inputs must be freshly fetched by the caller.
Never grants publication permission or derives a coordinate from a street or
commune centroid. Numberless places remain eligible for the existing route.
"""
from collections import Counter
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


# Public diagnostics contain only fixed stage names and numeric counters.
BAN_DIAGNOSTIC_CODES = (
    "directory_unavailable", "directory_no_authenticated_host",
    "directory_code_fallback_attempted", "directory_code_fallback_found",
    "directory_code_fallback_unavailable", "directory_code_fallback_identity_unmatched",
    "hint_missing", "hint_not_authenticated", "hint_not_dedicated",
    "page_unavailable", "homepage_unavailable", "exact_link_missing",
    "official_identity_unmatched", "official_access_restricted",
    "official_address_missing_or_ambiguous", "official_city_conflict",
    "official_family_activities_missing", "official_access_missing",
    "official_category_missing_or_ambiguous", "official_facts_invalid",
    "ban_unavailable", "ban_exact_address_unmatched", "admin_unavailable",
    "admin_identity_unmatched", "historical_postcode_conflict", "proof_found",
    "section_discovery_attempted", "section_page_unavailable",
    "culture_directory_attempted", "culture_directory_unavailable",
    "culture_directory_no_exact_match", "culture_directory_hints_found",
    "culture_independent_attempted", "culture_independent_identity_unmatched",
    "culture_independent_url_ambiguous", "culture_independent_page_unavailable",
    "culture_independent_address_conflict", "culture_independent_proof_found",
    "culture_independent_multi_url_attempted", "culture_independent_multi_url_conflict",
    "culture_independent_multi_url_resolved",
    "culture_independent_named_page_found", "culture_independent_named_page_unavailable",
    "culture_independent_alias_heading", "culture_independent_main_missing",
    "culture_independent_heading_missing", "culture_independent_heading_different",
    "culture_independent_record_missing", "culture_independent_name_or_commune_mismatch",
    "culture_independent_administrative_code_format", "culture_independent_address_field_missing_or_invalid",
    "culture_independent_numbered_street_missing", "culture_independent_complete_address_mismatch",
    "culture_independent_entrance_address_mismatch", "culture_independent_invalid_record",
    "culture_independent_url_missing", "culture_independent_url_unsafe", "culture_independent_url_budget",
)
_BAN_DIAGNOSTICS = Counter()


def _note(code):
    if code in BAN_DIAGNOSTIC_CODES:
        _BAN_DIAGNOSTICS[code] += 1
    return None


def ban_diagnostics():
    return {key: _BAN_DIAGNOSTICS[key] for key in BAN_DIAGNOSTIC_CODES
            if _BAN_DIAGNOSTICS[key]}


class PlaceMain(MainBlocks):
    """Bind the exact visible H1 to the same main/article as the facts."""
    def __init__(self, *, role_main=False):
        super().__init__(role_main=role_main)
        self.headings = []
        self.heading = None

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if (tag == "h1" and not self._hidden()
                and self.in_main()):
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


def _parse_place_main(html, *, allow_role_main=False):
    parser = PlaceMain()
    parser.feed(html)
    parser.close()
    # Fallback only if no visible native main/article exists; require one
    # explicit accessible landmark, not a heuristic CSS class or whole body.
    if allow_role_main and not parser.seen_main:
        parser = PlaceMain(role_main=True)
        parser.feed(html)
        parser.close()
        if parser.role_main_count != 1:
            return PlaceMain()
    return parser


def official_facts(city, venue, url, html, directory):
    """Exact first-party identity and visible permanent family service."""
    try:
        town, name = norm_text(city), norm_text(venue)
        p = urlsplit(url)
        if (not town or not name or town == name or not p.path.strip("/")
                or p.query or p.fragment
                or not approved_municipal_page_host(url, city, directory)
                or not isinstance(html, str) or not 50 <= len(html) <= MAX_HTML):
            return _note("official_facts_invalid")
        codes = {str(r.get("code_insee_commune")) for r in directory["results"]
                 if isinstance(r, dict)
                 and norm_text(r.get("nom")) == norm_text("Mairie - " + city)}
        if len(codes) != 1:
            return _note("official_facts_invalid")
        insee = next(iter(codes))
        return visible_place_facts(city, venue, url, html, insee)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, UnicodeError):
        return None


def visible_place_facts(city, venue, url, html, insee, *, verified_aliases=(),
                        allow_role_main=False):
    """Content only: callers MUST separately authenticate the exact URL."""
    try:
        town, name = norm_text(city), norm_text(venue)
        if (not town or not name or town == name
                or not isinstance(insee, str)
                or not re.fullmatch(r"(?:[0-9]{5}|2[AB][0-9]{3})", insee)
                or not isinstance(html, str) or not 50 <= len(html) <= MAX_HTML):
            return None
        parser = _parse_place_main(html, allow_role_main=allow_role_main)
        blocks = parser.blocks
        names = {name} | {norm_text(alias) for alias in verified_aliases}
        if len(parser.headings) != 1 or parser.headings[0] not in names or not parser.seen_main:
            return _note("official_identity_unmatched")
        if any(RESTRICTED.search(b) or CLOSED.search(b) for b in blocks):
            return _note("official_access_restricted")
        # Exactly one explicit numbered address in the main content.
        # Other postcode-bearing addresses are not silently ignored.
        addresses = []
        for b in blocks:
            m = re.fullmatch(r"([0-9]{1,4}(?: (?:bis|ter|quater|[a-z]))?) (.{3,120}) ([0-9]{5}) (.{2,120})", b)
            if m and HOUSE.fullmatch(m.group(1)):
                addresses.append(m.groups())
        if len(set(addresses)) != 1:
            return _note("official_address_missing_or_ambiguous")
        number, street, postcode, address_city = addresses[0]
        if address_city != town:
            return _note("official_city_conflict")
        activities = [label for pattern, label in ACTIVITIES
                      if any(re.search(pattern, b) for b in blocks)]
        admission = next((label for pattern, label in ACCESS
                          if any(re.search(pattern, b) for b in blocks)), None)
        if not activities:
            return _note("official_family_activities_missing")
        if admission is None:
            return _note("official_access_missing")
        kinds = set()
        if re.search(r"\bludotheque\b", name):
            kinds.add(("ludotheque", "Ludothèque"))
        if re.search(r"\b(?:bibliotheque|mediatheque)\b", name):
            kinds.add(("mediatheque-jeunesse", "Bibliothèque / médiathèque jeunesse"))
        for pattern, category, label in DEDICATED.values():
            if any(re.search(pattern, b) for b in blocks):
                kinds.add((category, label))
        if len(kinds) != 1:
            return _note("official_category_missing_or_ambiguous")
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
    return geocode_place_facts(facts, ban_fetch, admin_fetch,
                               "dila_official_place_address_plus_ban")


BAN_METHODS = ("dila_official_place_address_plus_ban",
               "culture_directory_official_place_address_plus_ban")


def geocode_place_facts(facts, ban_fetch, admin_fetch, method):
    if facts is None or method not in BAN_METHODS:
        return None
    city = facts["city"]
    try:
        data = ban_fetch(facts)
    except (OSError, ValueError, TypeError, KeyError, OverflowError, UnicodeError):
        return _note("ban_unavailable")
    point = exact_ban_point(facts, data)
    if point is None:
        return _note("ban_exact_address_unmatched")
    try:
        admin = admin_fetch(*point)
        ident = administrative_identity(admin, city, facts["postcode"])
        if ident is None or admin[0].get("code") != facts["insee"]:
            return _note("admin_identity_unmatched")
        _note("proof_found")
        return {**facts, "lat": point[0], "lng": point[1],
                "department": ident[0], "region": ident[1],
                "method": method,
                "publication_ready": False, "public_writes": 0}
    except (OSError, ValueError, TypeError, KeyError, OverflowError, UnicodeError):
        return _note("admin_unavailable")


def _section_pages(home, html, city, directory):
    """Bounded second hop through generic municipal culture/library menus."""
    from urllib.parse import urljoin
    from ptitesondes_municipal_venue_link_discovery import VisibleLinks, MAX_ANCHORS
    if not isinstance(html, str) or not 30 <= len(html) <= MAX_HTML:
        return []
    parser = VisibleLinks()
    parser.feed(html)
    parser.close()
    if len(parser.links) >= MAX_ANCHORS:
        return []
    sections = set()
    for href, label in parser.links:
        if not re.fullmatch(r"(?:culture(?: et (?:loisirs|patrimoine))?|bibliotheques?|mediatheques?|ludotheques?|equipements culturels|jeunesse|enfance(?: jeunesse)?|lecture publique)", norm_text(label)):
            continue
        url = urljoin(home, href)
        p = urlsplit(url)
        if (p.path.strip("/") and not p.query and not p.fragment
                and approved_municipal_page_host(url, city, directory)):
            sections.add(url)
    return sorted(sections)[:3]


def discover_official_ban(row, *, directory_fetch=None, page_read=None,
                          ban_fetch=None, admin_fetch=None, cultural_lookup=None,
                          code_directory_fetch=None):
    """Use an untrusted venue URL or exact municipal homepage link as a hint.

    Every page is authenticated by a fresh DILA result before network access.
    No external crawling, manual venue registry, or reuse of old coordinates.
    """
    from ptitesondes_dila_municipal_domains import fetch_dila, municipal_site_hosts
    from ptitesondes_municipal_venue_link_discovery import exact_named_venue_page
    from ptitesondes_unlisted_source_safe_recheck import read_unknown_https, read_municipal_https
    from ptitesondes_generic_venue_ign_corroboration import fetch_ign
    from ptitesondes_open_world_permanent_place_draft import fetch_admin
    use_municipal_reader = page_read is None or page_read is read_unknown_https
    if code_directory_fetch is None and directory_fetch is None and use_municipal_reader:
        code_directory_fetch = lambda city, code: fetch_dila(city, insee=code)
    directory_fetch = directory_fetch or fetch_dila
    if cultural_lookup is None and use_municipal_reader:
        from ptitesondes_national_cultural_directory_probe import exact_directory_record
        cultural_lookup = exact_directory_record
    ban_fetch = ban_fetch or fetch_ign
    admin_fetch = admin_fetch or fetch_admin
    try:
        city, venue = row["city"], row["venue"]
        try:
            directory = directory_fetch(city)
        except (OSError, ValueError, TypeError, KeyError, OverflowError, UnicodeError):
            return _note("directory_unavailable")
        hosts = municipal_site_hosts(city, directory)
        record = None
        lookup_attempted = False
        if not hosts and code_directory_fetch is not None and cultural_lookup is not None:
            from ptitesondes_cultural_directory_discovery import identity
            _note("directory_code_fallback_attempted")
            lookup_attempted = True
            try:
                record = cultural_lookup(city, venue)
                pair = identity(record)
                if pair is not None and tuple(map(norm_text, pair)) == (norm_text(city), norm_text(venue)):
                    code = record["code_commune"]
                    alternative = code_directory_fetch(city, code)
                    bound_hosts = municipal_site_hosts(city, alternative, expected_insee=code)
                    if bound_hosts and bound_hosts == municipal_site_hosts(city, alternative):
                        directory, hosts = alternative, bound_hosts
                        _note("directory_code_fallback_found")
                    else:
                        _note("directory_code_fallback_identity_unmatched")
                else:
                    _note("directory_code_fallback_identity_unmatched")
            except (OSError, ValueError, TypeError, KeyError, OverflowError, UnicodeError):
                _note("directory_code_fallback_unavailable")
        if not hosts:
            return _note("directory_no_authenticated_host")
        def read_page(url):
            if use_municipal_reader:
                return read_municipal_https(url, city, directory)
            return url, page_read(url)
        hint = row.get("possible_website_unverified")
        pages = []
        if approved_municipal_page_host(hint, city, directory):
            p = urlsplit(hint)
            if p.path.strip("/") and not p.query and not p.fragment:
                pages.append(hint)
            else:
                _note("hint_not_dedicated")
        elif hint:
            _note("hint_not_authenticated")
        else:
            _note("hint_missing")
        # Only live production or an explicitly injected lookup may query
        # the national directory. Reuse this cycle's fresh code lookup.
        if not pages and cultural_lookup is not None:
            from ptitesondes_national_cultural_directory_probe import directory_website_hints
            _note("culture_directory_attempted")
            try:
                if not lookup_attempted:
                    record = cultural_lookup(city, venue)
                if record is None:
                    _note("culture_directory_no_exact_match")
                else:
                    for url in directory_website_hints(record):
                        if (approved_municipal_page_host(url, city, directory)
                                and urlsplit(url).path.strip("/")):
                            pages.append(url)
                    if pages:
                        _note("culture_directory_hints_found")
            except (OSError, ValueError, TypeError, KeyError, OverflowError, UnicodeError):
                _note("culture_directory_unavailable")
        # At most one authenticated homepage, and bounded exact page hints.
        home = "https://" + sorted(hosts)[0] + "/"
        for url in pages[:3]:
            try:
                final, html = read_page(url)
                proof = corroborate_official_ban(city, venue, final, html,
                                                 directory, ban_fetch, admin_fetch)
                if proof is not None:
                    historical = row.get("historical_address_unverified")
                    if isinstance(historical, dict) and historical.get("postal_code") not in (None, proof["postcode"]):
                        return _note("historical_postcode_conflict")
                    return proof
            except (OSError, ValueError, TypeError, UnicodeError):
                _note("page_unavailable")
        try:
            home, homepage = read_page(home)
        except (OSError, ValueError, TypeError, UnicodeError):
            return _note("homepage_unavailable")
        url = exact_named_venue_page(venue, home, homepage, city, directory)
        if not url:
            # A facility is rarely linked from the home page. Follow at most
            # three generic same-authority sections, then require an exact
            # visible venue link. Multiple destinations remain ambiguous.
            matches = set()
            for section in _section_pages(home, homepage, city, directory):
                _note("section_discovery_attempted")
                try:
                    section, section_html = read_page(section)
                    hit = exact_named_venue_page(venue, section, section_html,
                                                 city, directory)
                except (OSError, ValueError, TypeError, UnicodeError):
                    _note("section_page_unavailable")
                    continue
                if hit:
                    matches.add(hit)
            if len(matches) == 1:
                url = next(iter(matches))
        if not url or url in pages:
            return _note("exact_link_missing")
        try:
            url, html = read_page(url)
        except (OSError, ValueError, TypeError, UnicodeError):
            return _note("page_unavailable")
        proof = corroborate_official_ban(city, venue, url, html,
                                         directory, ban_fetch, admin_fetch)
        historical = row.get("historical_address_unverified")
        if proof is not None and isinstance(historical, dict) and historical.get("postal_code") not in (None, proof["postcode"]):
            return _note("historical_postcode_conflict")
        return proof
    except (OSError, ValueError, TypeError, KeyError, OverflowError, UnicodeError):
        return _note("official_facts_invalid")


def _cultural_named_page(venue, current_url, html, *, verified_aliases=()):
    """One exact visible venue link on the already authenticated host."""
    from ptitesondes_municipal_venue_link_discovery import VisibleLinks, MAX_ANCHORS
    from ptitesondes_dynamic_municipal_source_links import _safe_url
    from ptitesondes_dila_municipal_domains import _host
    if not isinstance(html, str) or not 30 <= len(html) <= MAX_HTML:
        return None
    host = _host(current_url)
    if not host:
        return None
    parser = VisibleLinks()
    parser.feed(html)
    parser.close()
    if len(parser.links) >= MAX_ANCHORS:
        return None
    matches = set()
    for href, label in parser.links:
        if norm_text(label) not in ({norm_text(venue)} | {norm_text(a) for a in verified_aliases}):
            continue
        candidate = _safe_url(href, base=current_url)
        if not candidate or candidate == current_url or _host(candidate) != host:
            continue
        p = urlsplit(candidate)
        if p.path.strip("/") and not p.query and not p.fragment:
            matches.add(candidate)
    return next(iter(matches)) if len(matches) == 1 else None


def discover_independent_cultural_ban(row, *, cultural_lookup=None, page_read=None,
                                      ban_fetch=None, admin_fetch=None):
    """Fresh national directory link, exact first-party page, independent BAN.

    No DILA dependency. Inspect a bounded set of safe listed URLs; only exact
    dedicated identity and independent address evidence may qualify a page.
    Contradictory identified pages stay private.
    Only bounded same-authority HTTPS canonicalization is allowed; never consume saved
    coordinates, addresses or URLs.
    """
    from ptitesondes_national_cultural_directory_probe import (
        exact_directory_record, directory_website_hints)
    from ptitesondes_cultural_directory_identity import directory_identity, same_official_address
    from ptitesondes_dila_municipal_domains import _host
    from ptitesondes_unlisted_source_safe_recheck import read_cultural_https, same_cultural_authority
    from ptitesondes_generic_venue_ign_corroboration import fetch_ign
    from ptitesondes_open_world_permanent_place_draft import fetch_admin
    cultural_lookup = cultural_lookup or exact_directory_record
    if page_read is None:
        def page_read(url):
            return read_cultural_https(url)
    ban_fetch = ban_fetch or fetch_ign
    admin_fetch = admin_fetch or fetch_admin
    _note("culture_independent_attempted")
    try:
        city, venue = row["city"], row["venue"]
        record = cultural_lookup(city, venue)
        identity_counts = Counter()
        identity = directory_identity(city, venue, record, identity_counts)
        if identity is None:
            for reason in identity_counts:
                code = "culture_independent_" + ("record_missing" if reason == "directory_record_missing" else reason)
                _note(code)
            return _note("culture_independent_identity_unmatched")
        aliases = tuple(value.strip() for key in ("nom_du_lieu", "nom_usuel_du_lieu")
                        if isinstance(value := record.get(key), str)
                        and 2 <= len(value.strip()) <= 180 and norm_text(value)
                        and norm_text(value) != norm_text(city)
                        and not any(ord(c) < 32 or ord(c) == 127 for c in value))
        names = {norm_text(venue)} | {norm_text(a) for a in aliases}
        listed = directory_website_hints(record, try_https_upgrade=True)
        urls = [url for url in listed if _host(url)]
        if not 1 <= len(urls) <= 4:
            _note("culture_independent_url_missing" if not listed else
                  "culture_independent_url_unsafe" if not urls else "culture_independent_url_budget")
            return _note("culture_independent_url_ambiguous")
        if len(urls) > 1:
            _note("culture_independent_multi_url_attempted")
        matched = []
        for url in urls:
            try:
                result = page_read(url)
                final_url, html = result if isinstance(result, tuple) else (url, result)
                if (not same_cultural_authority(url, final_url) or urlsplit(final_url).query
                        or urlsplit(final_url).fragment):
                    raise ValueError('cultural_redirect_outside_authority')
            except (OSError, ValueError, TypeError, UnicodeError):
                _note("culture_independent_page_unavailable")
                continue
            # Distinguish an unrelated page from a contradictory page for
            # this exact venue. The latter cannot be hidden by a good link.
            if not isinstance(html, str) or not 50 <= len(html) <= MAX_HTML:
                continue
            parser = _parse_place_main(html, allow_role_main=True)
            if not parser.seen_main or not names.intersection(parser.headings):
                _note("culture_independent_main_missing" if not parser.seen_main else
                      "culture_independent_heading_missing" if not parser.headings else
                      "culture_independent_heading_different")
                # A directory often lists an institution's homepage rather
                # than its dedicated venue page. Follow only one exact
                # visible link on that same authenticated host.
                target = _cultural_named_page(venue, final_url, html, verified_aliases=aliases)
                if not target:
                    _note("official_identity_unmatched")
                    continue
                _note("culture_independent_named_page_found")
                try:
                    result = page_read(target)
                    final_url, html = result if isinstance(result, tuple) else (target, result)
                    if (not same_cultural_authority(url, final_url) or urlsplit(final_url).query
                            or urlsplit(final_url).fragment):
                        raise ValueError("cultural_redirect_outside_authority")
                except (OSError, ValueError, TypeError, UnicodeError):
                    _note("culture_independent_named_page_unavailable")
                    continue
            facts = visible_place_facts(city, venue, final_url, html, identity["insee"],
                                        verified_aliases=aliases, allow_role_main=True)
            if facts is not None and parser.headings and parser.headings[0] != norm_text(venue) and parser.headings[0] in names:
                _note("culture_independent_alias_heading")
            if facts is None:
                return _note("culture_independent_multi_url_conflict") if len(urls) > 1 else None
            if not same_official_address(identity, facts):
                return _note("culture_independent_address_conflict")
            matched.append(facts)
        if not matched:
            return None
        facts = matched[0]
        # Multiple qualifying pages must agree on all extracted facts.
        if any({k: v for k, v in item.items() if k != "official_url"} !=
               {k: v for k, v in facts.items() if k != "official_url"}
               for item in matched[1:]):
            return _note("culture_independent_multi_url_conflict")
        if len(urls) > 1:
            _note("culture_independent_multi_url_resolved")
        historical = row.get("historical_address_unverified")
        if isinstance(historical, dict) and historical.get("postal_code") not in (None, facts["postcode"]):
            return _note("historical_postcode_conflict")
        proof = geocode_place_facts(facts, ban_fetch, admin_fetch,
                                    "culture_directory_official_place_address_plus_ban")
        if proof is not None:
            _note("culture_independent_proof_found")
        return proof
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError, UnicodeError):
        return _note("culture_directory_unavailable")


def discover_ban_routes(row):
    # Prefer the independent national route to avoid wasting a municipal
    # lookup when a fresh directory and first-party page already agree.
    return discover_independent_cultural_ban(row) or discover_official_ban(row)


def build_ban_draft(proof, today):
    """Build only from a freshly reconstructed proof in the Publisher process."""
    from datetime import date
    from ptitesondes_places import validate, ban_place_id, ban_place_source_url
    try:
        if (type(today) is not date or proof.get("method") not in BAN_METHODS
                or proof.get("public_eligible") is not False):
            return None
        address = f'{proof["housenumber"]} {proof["street"]}, {proof["postcode"]} {proof["city"]}'
        result = {
            "id": ban_place_id(proof["city"], proof["venue"]),
            "name": proof["venue"], "kind": "lieu-permanent",
            "category": proof["category"], "category_label": proof["category_label"],
            "city": proof["city"], "department": proof["department"],
            "region": proof["region"], "postal_code": proof["postcode"],
            "address": address, "lat": proof["lat"], "lng": proof["lng"],
            "geo_precision": "lieu", "age_min": None, "age_max": None,
            "admission": proof["admission"], "activities": proof["activities"],
            "reservation_note": "Vérifier les horaires, tarifs et modalités de réservation sur le site officiel.",
            "official_url": proof["official_url"],
            "geo_source_url": ban_place_source_url(address),
            "reviewed_at": today.isoformat(), "is_publicly_accessible": True,
        }
        validate({"version": 1, "updated_at": today.isoformat(), "places": [result]})
        return result
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return None
