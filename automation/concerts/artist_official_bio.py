"""First-party linked artist biographies: reusable, PRIVATE genre research evidence.

A committed official artist tour source may link to ONE same-host biography.
The link is independently fetched and robots checked. Only a specific artist
self-description in a first-party biography near an explicit music subgenre
can support the INDIVIDUAL ARTIST genre. Neither a biography nor a performer
genre can prove a concert/date/venue/lineup, or sign a publication approval.
"""
from __future__ import annotations

import datetime as dt
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import artist_genre_knowledge as knowledge
from triage import words

# Explicit genre names, shared across artists (not a list of known bands).
# Avoid unqualified "rock", "hardcore" (techno homonym) and generic "metal".
BIO_GENRES = (
    "heavy rock", "hard rock", "heavy metal", "black metal", "death metal",
    "thrash metal", "doom metal", "stoner rock", "punk rock", "post punk",
    "post rock", "post metal", "noise rock", "garage rock", "psychedelic rock",
    "grunge", "metalcore", "deathcore", "grindcore", "powerviolence",
    "blackgaze", "sludge metal", "progressive metal", "symphonic metal",
)
BIO_CONTEXT = re.compile(
    r"\b(?:leur|leurs|notre|nos|our|their|son|style|genre|musique|sound|"
    r"groupe|band|duo|trio|we are|nous sommes|nous jouons|they play|plays|"
    r"playing|pratiquent|joue|des)\b"
)
NEGATION = re.compile(r"\b(?:not|no|never|pas|sans|ne|ni|isnt|isn't)\b")
BIO_LABELS = frozenset({"bio", "biography", "biographie", "about", "about us"})


def _same_first_party(url, expected):
    if not isinstance(url, str) or not isinstance(expected, str):
        return False
    try:
        actual, source = urlsplit(url), urlsplit(expected)
        return bool(
            source.scheme == actual.scheme == "https"
            and source.hostname and source.netloc.casefold() == actual.netloc.casefold()
            and not actual.username and not actual.password and not source.username
            and not source.password and not actual.fragment and not actual.query
            and actual.path != source.path
        )
    except ValueError:
        return False


class _BioLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self._href = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a":
            label = words(" ".join(self._text))
            if label in BIO_LABELS and isinstance(self._href, str):
                self.links.append(self._href)
            self._href = None
            self._text = []


def linked_official_biography(tour_html, source_url, actual_tour_url):
    """Return exactly one same-host HTTPS biography link, never a search guess."""
    if (not isinstance(tour_html, str) or len(tour_html) > 900_000
            or not isinstance(actual_tour_url, str)
            or actual_tour_url.rstrip("/") != str(source_url).rstrip("/")
            or urlsplit(source_url).scheme != "https"):
        return None
    parser = _BioLinks()
    parser.feed(tour_html)
    permitted = set()
    for link in parser.links:
        resolved = urljoin(source_url, link)
        if _same_first_party(resolved, source_url):
            permitted.add(resolved)
    if len(permitted) != 1:
        return None
    return next(iter(permitted))


class _OfficialBio(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.paragraphs = []
        self._title = False
        self._p = False
        self._parts = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "nav", "aside", "footer", "noscript"}:
            self._skip += 1
        if tag == "title":
            self._title = True
        elif tag == "p" and not self._skip:
            self._p = True
            self._parts = []

    def handle_data(self, data):
        if self._title:
            self.title += data[:250]
        if self._p and not self._skip:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag == "title":
            self._title = False
        elif tag == "p" and self._p:
            self.paragraphs.append(" ".join(" ".join(self._parts).split())[:1400])
            self._parts = []
            self._p = False
        if tag in {"script", "style", "nav", "aside", "footer", "noscript"}:
            self._skip = max(self._skip - 1, 0)


def verify_official_biography(source, catalogue, bio_html, actual_bio_url,
                              biography_link, checked_at):
    """Conservative *artist-only* genre evidence from a linked first-party bio."""
    if (not isinstance(checked_at, dt.date)
            or not isinstance(source, dict)
            or source.get("sourceRole") != "artist_official"
            or source.get("enabled") is not True
            or not isinstance(bio_html, str) or not 0 < len(bio_html) <= 600_000
            or biography_link != actual_bio_url
            or not _same_first_party(actual_bio_url, source.get("url"))):
        raise ValueError("Biographie non officielle ou redirection ambiguë")
    artist_id = source.get("artistId")
    if not isinstance(catalogue, dict) or not isinstance(catalogue.get("artists"), list):
        raise ValueError("Catalogue artiste invalide")
    matches = [a for a in catalogue["artists"]
               if isinstance(a, dict) and a.get("id") == artist_id]
    if len(matches) != 1:
        raise ValueError("Artiste absent ou ambigu")
    aliases, collision = knowledge._aliases(catalogue)
    artist = matches[0]
    known_names = {words(x) for x in
                   [artist.get("name"), *(artist.get("aliases") or [])]
                   if isinstance(x, str) and words(x)}
    if (not known_names or any(x in collision or aliases.get(x) != artist_id
                               for x in known_names)):
        raise ValueError("Alias artiste ambigu")
    parser = _OfficialBio()
    parser.feed(bio_html)
    title = words(parser.title)
    if not any(re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", title)
               for n in known_names):
        raise ValueError("La biographie ne nomme pas cet artiste")
    evidence = []
    # Only the opening artist self-description, NEVER pages of influences,
    # recommendations, labels or historical concerts.
    for paragraph in parser.paragraphs[:4]:
        normalized = words(paragraph[:650])
        if not any(re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", normalized)
                   for n in known_names):
            continue
        for genre in BIO_GENRES:
            for match in re.finditer(r"(?<!\w)" + re.escape(genre) + r"(?!\w)",
                                     normalized):
                before = normalized[max(0, match.start() - 65):match.start()]
                if not BIO_CONTEXT.search(before) or NEGATION.search(before[-28:]):
                    continue
                if genre not in evidence:
                    evidence.append(genre)
    if not evidence:
        raise ValueError("Genre individuel explicite non corroboré")
    return {
        "schema": knowledge.SCHEMA,
        "artistId": artist_id,
        "artistName": artist["name"],
        "genres": [g.title() for g in evidence],
        "sourceUrl": actual_bio_url,
        "sourceTourUrl": source["url"],
        "verifiedAt": checked_at.isoformat(),
        "evidenceKind": "first-party-artist-visible-linked-bio",
        "scope": "individual_artist_not_event",
        "publicationAllowed": False,
        "approvalsProposed": 0,
        "eventDateLocationAndLineupProved": False,
    }
