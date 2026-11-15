"""Organizer-linked Google Maps points: a location clue, never a 2027 venue certificate.

Only parse an exact, pre-reviewed Maps POI linked *from official organizer HTML*.
Never geocode an arbitrary address, fetch Maps or infer a future edition's venue.
"""
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit
import re
import unicodedata

MOZHELL_MAP_PLACE_ID = "0x479445b5f1e51199:0x61c10102323eb346"
MOZHELL_MAP_COORDS = (48.9580091, 6.8717186)
MOZHELL_MAP_URL = (
    "https://www.google.com/maps/place/Mozhell+Open+Air/"
    "@48.9581784,6.8711046,18.07z/data=!4m6!3m5"
    "!1s0x479445b5f1e51199:0x61c10102323eb346"
    "!8m2!3d48.9580091!4d6.8717186!16s%2Fg%2F11w2k3xr87"
)
MOZHELL_ACCESS_FR = "https://www.mozhell.fr/fr/acces"
MOZHELL_ACCESS_EN = "https://www.mozhell.fr/en/access-parkings"


def _norm(value):
    value = unicodedata.normalize("NFKD", str(value).casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


class VisibleLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors = []
        self.text_parts = []
        self._active = None
        self._hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self._hidden += 1
            return
        if tag == "a" and not self._hidden:
            self._active = {"href": dict(attrs).get("href"), "text": []}

    def handle_data(self, data):
        if not self._hidden:
            self.text_parts.append(data)
            if self._active is not None:
                self._active["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._active is not None:
            self.anchors.append((
                self._active["href"], " ".join(self._active["text"])))
            self._active = None
        if tag in ("script", "style", "noscript", "svg"):
            self._hidden = max(0, self._hidden - 1)


def _parse(html):
    if not isinstance(html, str) or not 100 <= len(html) <= 1_400_000:
        return None
    parser = VisibleLinks()
    parser.feed(html)
    return parser


def _maps_poi(href, expected_place_id, expected_coords):
    if not isinstance(href, str) or len(href) > 1500:
        return False
    try:
        url = urlsplit(href)
        path = unquote(url.path)
        if (url.scheme != "https" or url.hostname != "www.google.com"
                or url.port is not None or url.username or url.password
                or not path.startswith("/maps/place/")
                or "mozhell open air" not in _norm(path.split("/")[3].replace("+", " "))
                or ("!1s" + expected_place_id) not in path):
            return False
        points = re.findall(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", path)
        if len(points) != 1:
            return False
        lat, lon = map(float, points[0])
        return (abs(lat - expected_coords[0]) < 0.0000001
                and abs(lon - expected_coords[1]) < 0.0000001)
    except (ValueError, IndexError):
        return False


def _organizer_itinerary_links(parser, label):
    return [
        href for href, text in parser.anchors
        if _norm(label) in _norm(text)
    ]


def assess_mozhell_organizer_maps(fr_html, en_html):
    """Return private-only, provenance-labeled evidence, or None if unsafe.

    The 2027 French access text is checked because the English access page
    still carries 2026 timetables. Either address may be stale or incorrect.
    """
    fr, en = _parse(fr_html), _parse(en_html)
    if fr is None or en is None:
        return None
    fr_text, en_text = _norm(" ".join(fr.text_parts)), _norm(" ".join(en.text_parts))
    fr_itinerary = _organizer_itinerary_links(fr, "Itinéraire")
    en_itinerary = _organizer_itinerary_links(en, "Itinerary")
    if (len(fr_itinerary) != 1 or len(en_itinerary) != 1
            or not _maps_poi(fr_itinerary[0], MOZHELL_MAP_PLACE_ID, MOZHELL_MAP_COORDS)
            or not _maps_poi(en_itinerary[0], MOZHELL_MAP_PLACE_ID, MOZHELL_MAP_COORDS)
            or "insming" not in fr_text or "insming" not in en_text
            or not all(text in fr_text for text in (
                "vendredi 23 juillet", "samedi 24 juillet",
                "dimanche 25 juillet", "2027"))):
        return None
    fr_address = re.search(
        r"le festival a lieu dans le village d insming en moselle 57670 "
        r"(\d{1,3}) rue de l albe", fr_text)
    en_address = re.search(
        r"the festival takes place in the village of insming in moselle 57670 "
        r"(\d{1,3}) rue de l albe", en_text)
    if not fr_address or not en_address:
        return None
    fr_house, en_house = fr_address.group(1), en_address.group(1)
    return {
        "status": "ORGANIZER_LINKED_MAPS_POI_REVIEW_ONLY",
        "provider": "Google Maps",
        "official_organizer_access_pages": [MOZHELL_ACCESS_FR, MOZHELL_ACCESS_EN],
        "map_place_id": MOZHELL_MAP_PLACE_ID,
        "maps_url": MOZHELL_MAP_URL,
        "coordinates": {"lat": MOZHELL_MAP_COORDS[0],
                        "lon": MOZHELL_MAP_COORDS[1]},
        "geo_precision": "organizer_linked_poi",
        "municipality": "Insming",
        "official_addresses_disagree": fr_house != en_house,
        "addresses_private": {
            "fr": fr_house + " rue de l'Albe",
            "en": en_house + " rue de l'Albe",
        },
        "english_access_page_has_2026_timetable": (
            "friday july 24" in en_text and "sunday july 26" in en_text),
        "future_edition_exact_venue_confirmed": False,
        "independent_edition_confirmation": False,
        "publication_authorized": False,
    }
