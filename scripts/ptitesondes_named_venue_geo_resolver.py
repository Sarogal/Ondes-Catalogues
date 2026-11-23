"""Source-first venue coordinates for generic city-only OpenAgenda locations.

A city centroid must never be silently represented as the event's venue.
Existing named OA venues keep the ordinary first-party route; when OA names
only a commune, this optional open-ended evidence cache can point to an
independently published venue page. Its live HTML (NOT the cached metadata)
must identify the same physical venue/city and contain an unambiguous map pin.

The cache is a growing source-discovery aid, NOT an organizer, municipality,
venue or event allowlist. Missing proof means hold, never a guessed location.
No second source is required for the event's date, status or audience.
"""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import json
import re

from proof import norm, meters
from ptitesondes_openagenda_national_event_research import _french_text
from ptitesondes_shared_venue_location_evidence import _coordinates
from ptitesondes_unlisted_source_safe_recheck import read_unknown_https

SCHEMA = "ptitesondes.named_venue_geoevidence_sources.v1"
SOURCES = Path(__file__).resolve().parents[1] / "config" / "ptitesondes-named-venue-geo-sources.json"
MAX_CACHE_BYTES = 100_000
MAX_SOURCES = 800
MAX_HTML = 400_000
MAX_CITY_DISTANCE_METERS = 6_000
MAX_GEO_DISAGREEMENT_METERS = 65


class _VisibleMaps(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.words = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.depth += 1
        if tag == "a":
            href = dict(attrs).get("href")
            if isinstance(href, str) and len(href) <= 1400:
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if not self.depth and data.strip():
            self.words.append(data.strip())


def _valid_source(row):
    if type(row) is not dict or set(row) != {
            "city", "region", "venue_name", "official_url"}:
        return False
    city, region, venue = (row.get(k) for k in ("city", "region", "venue_name"))
    if any(type(value) is not str or not 2 <= len(value) <= 180 or not norm(value)
           for value in (city, region, venue)):
        return False
    try:
        parsed = urlsplit(row["official_url"])
        return (parsed.scheme == "https" and parsed.hostname is not None
                and parsed.hostname != "openagenda.com"
                and not parsed.hostname.endswith(".openagenda.com")
                and parsed.port in (None, 443) and not parsed.username
                and not parsed.password and not parsed.fragment
                and bool(parsed.path.strip("/"))
                and len(row["official_url"]) <= 1000)
    except (ValueError, TypeError):
        return False


def read_source_cache(path=SOURCES):
    """Never trust a cache document enough to bypass a live evidence read."""
    try:
        raw = Path(path).read_bytes()
        if not raw or len(raw) > MAX_CACHE_BYTES:
            return []
        doc = json.loads(raw)
        rows = doc.get("sources") if type(doc) is dict and doc.get("schema") == SCHEMA else None
        if (type(rows) is not list or len(rows) > MAX_SOURCES
                or any(not _valid_source(x) for x in rows)):
            return []
        return rows
    except (OSError, UnicodeError, ValueError, TypeError):
        return []


def _described_venue(event, venue):
    """Require a *distinctive prefix* of the named venue in live OA text.

    At least four significant words, 20 letters and a city different from
    the venue guard prevent matches on generic words such as 'centre culturel'.
    The suffix may be missing in OA ('dit Zwazo' on the place's full name).
    """
    name = norm(venue)
    parts = name.split()
    if len(parts) < 4:
        return False
    prefix = " ".join(parts[:4])
    if len(prefix.replace(" ", "")) < 20:
        return False
    description = " ".join(_french_text(event, field)
                           for field in ("description", "longDescription", "conditions"))
    return prefix in norm(description)


def _pin_from_link(url):
    """Only explicit geographic destinations; never town-search map URLs."""
    try:
        u = urlsplit(url)
        if (u.scheme != "https" or u.hostname not in ("google.com", "www.google.com")
                or not u.path.startswith("/maps/dir/")):
            return None
        values = parse_qs(u.query).get("destination")
        if not isinstance(values, list) or len(values) != 1:
            return None
        pair = values[0].split(",")
        if len(pair) != 2:
            return None
        a, b = (float(x.strip()) for x in pair)
        return _coordinates((a, b))
    except (TypeError, ValueError, OverflowError):
        return None


def _page_pin(html, record):
    if type(html) is not str or not 100 <= len(html) <= MAX_HTML:
        return None
    reader = _VisibleMaps()
    try:
        reader.feed(html)
        reader.close()
    except (ValueError, TypeError):
        return None
    visible = norm(" ".join(reader.words))
    # Page independently names BOTH the venue and the municipality.
    if norm(record["venue_name"]) not in visible or norm(record["city"]) not in visible:
        return None
    points = [point for link in reader.links
              if (point := _pin_from_link(link)) is not None]
    if not points or any(meters(points[0], x) > MAX_GEO_DISAGREEMENT_METERS
                         for x in points[1:]):
        return None
    return points[0]


def resolve_named_city_only_venue(event, *, source_reader=read_unknown_https,
                                  sources=None):
    """Return verified physical venue+pin or None; no publication authority.

    The caller must pass a FRESH exact-UID-bound OpenAgenda event. It is the
    caller's job to verify UID, state, schedule, license and deduplication in
    the normal first-party Publisher. No information is taken from a dossier.
    """
    if type(event) is not dict or not callable(source_reader):
        return None
    location = event.get("location")
    if type(location) is not dict:
        return None
    city, region, city_name = (location.get("adminLevel4"),
                               location.get("adminLevel1"),
                               location.get("name"))
    origin = _coordinates((location.get("latitude"), location.get("longitude")))
    if (type(city) is not str or type(region) is not str
            or type(city_name) is not str or not norm(city)
            or norm(city_name) != norm(city) or origin is None):
        return None
    rows = read_source_cache() if sources is None else sources
    if type(rows) is not list or len(rows) > MAX_SOURCES:
        return None
    eligible = [r for r in rows if (_valid_source(r)
                and norm(r["city"]) == norm(city)
                and norm(r["region"]) == norm(region)
                and norm(r["venue_name"]) != norm(city)
                and _described_venue(event, r["venue_name"]))]
    # Two matching independent venues are ambiguous; never choose by order.
    if len(eligible) != 1:
        return None
    record = eligible[0]
    try:
        html = source_reader(record["official_url"])
        point = _page_pin(html, record)
    except (OSError, ValueError, TypeError, TimeoutError, UnicodeError):
        return None
    if point is None or meters(origin, point) > MAX_CITY_DISTANCE_METERS:
        return None
    return {"name": record["venue_name"], "latitude": point[0],
            "longitude": point[1], "official_url": record["official_url"]}
