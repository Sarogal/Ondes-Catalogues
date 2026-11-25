"""One published OpenAgenda event page is enough to prove a concert.

The official OpenAgenda public page itself supplies the named event, concert
date, listed performers (including + delimited co-headliners), event-scoped
genre and location. No second website, artist allowlist, municipality or OSM
lookup is required for a site ALREADY on the Grosses Ondes public map.

Discovery/OpendataSoft metadata is never admission authority. An actual fresh
OpenAgenda page is fetched by independent publisher and is compared against
the exact signed event at each initial admission. No description or image is
republished; the public event URL attributes the originating record.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import sys
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit

# The existing discovery modules have legacy top-level sibling imports.
# One explicit local path supports both standalone CLI and package tests.
_SOURCE_DIR = Path(__file__).resolve().parent
_ROOT = Path(__file__).resolve().parents[2]
for _path in (str(_ROOT), str(_SOURCE_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from automation.concerts import discover
from automation.concerts import official_rss_jsonld_bridge as bridge
from scripts import concert_event_site_contract as contract
from automation.concerts.source_admission_intake import normalized

AGENDA_PATH = re.compile(
    r"/(?:fr/|en/)?[a-z0-9][a-z0-9-]{1,119}/events/"
    r"[a-z0-9][a-z0-9_-]{2,180}/?\Z", re.I)
CANCELLED = ("cancel", "postpon", "resched", "report", "annul")
PLACEHOLDERS = frozenset(("concert", "soiree", "festival", "concert punk",
                          "concert metal", "live", "show", "spectacle"))


class _VisibleOfficialGenreText(HTMLParser):
    """Genre signals may come from visible original OpenAgenda descriptions.

    HTML attributes, scripts and hidden templates are not evidence. This
    extracts only a bounded human-readable description; it never adds artists,
    dates or locations and is not an additional event source.
    """
    _HIDDEN = frozenset({"script", "style", "noscript", "template"})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self._HIDDEN:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in self._HIDDEN and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden and len(self.parts) < 600:
            self.parts.append(data)


def _described_official_genres(record):
    """Classify ONLY explicit genre words on the UID-authenticated OA record.

    Never infer a support act's individual style or promote discovery hints.
    Hardtek/hardcore techno is not evidence of the metal/punk universe.
    """
    descriptions = record.get("description")
    if not isinstance(descriptions, dict):
        return []
    content = descriptions.get("fr") or descriptions.get("en")
    if not isinstance(content, str) or not 4 <= len(content) <= 12000:
        return []
    parsed = _VisibleOfficialGenreText()
    try:
        parsed.feed(content)
        parsed.close()
    except (ValueError, TypeError):
        return []
    visible = normalized(" ".join(parsed.parts))
    if not visible or len(visible) > 12000:
        return []
    labels = []
    for match in contract.MUSIC.finditer(visible):
        genre = match.group(0)
        if genre == "hardcore" and re.match(
                r"\s+(?:techno|electro|electronic)\b",
                visible[match.end():]):
            continue
        if (genre not in labels and contract.relevant_genres([genre])):
            labels.append(genre)
    return labels[:8]


class _LongDescriptionText(HTMLParser):
    """Keep sentence/block boundaries; ignore scripts and explicitly hidden HTML."""
    _VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img",
                       "input", "link", "meta", "param", "source", "track", "wbr"})
    _SKIP = frozenset({"script", "style", "noscript", "template", "nav", "aside",
                       "footer", "form", "svg"})
    _BREAK = frozenset({"p", "div", "section", "article", "li", "h1", "h2",
                        "h3", "h4", "h5", "br", "hr"})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        hidden = ((self.stack and self.stack[-1][1]) or tag in self._SKIP
                  or "hidden" in attrs
                  or str(attrs.get("aria-hidden", "")).lower() == "true"
                  or re.search(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)\b",
                               str(attrs.get("style", "")), re.I))
        if not hidden and tag in self._BREAK:
            self.parts.append("\n")
        if tag not in self._VOID:
            self.stack.append((tag, bool(hidden)))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                hidden = self.stack[i][1]
                del self.stack[i:]
                if not hidden and tag in self._BREAK:
                    self.parts.append("\n")
                return

    def handle_data(self, data):
        if not self.stack or not self.stack[-1][1]:
            self.parts.append(data)


def _long_description_genres(record, names):
    """Recover an explicit named performer's genre, not influences or mentions.

    The original OpenAgenda export is already bound to the event UID, date
    and physical venue. A long biography can mention other musicians,
    comparisons, or recommendations, so only complete positive assertions
    about an artist on THIS verified bill are eligible. No new artist names
    are inferred and no individual genre is assigned to the other acts.
    """
    from automation.concerts.artist_official_bio import BIO_GENRES
    content = record.get("longDescription")
    if not isinstance(content, dict):
        return []
    content = content.get("fr") or content.get("en")
    if not isinstance(content, str) or not 4 <= len(content) <= 20000:
        return []
    reader = _LongDescriptionText()
    try:
        reader.feed(content)
        reader.close()
    except (ValueError, TypeError, RecursionError):
        return []
    labels = sorted(set(BIO_GENRES) | {"punk", "metal", "hardcore punk",
                                      "industrial metal", "metal indus"},
                    key=lambda label: (-len(label), label))
    identities = {normalized(name) for name in names if normalized(name)}
    genres = []
    for part in re.split(r"[\n.!?;]+", "".join(reader.parts)):
        sentence = normalized(part)
        if not sentence or len(sentence) > 350:
            continue
        if re.search(r"\b(?:not|never|pas|sans|influence|influences|influenced|"
                     r"inspire|inspiree|tribute|hommage|techno|gabber|hardstyle)\b",
                     sentence):
            continue
        for name in identities:
            subject = re.escape(name)
            for genre in labels:
                label = re.escape(normalized(genre))
                patterns = (
                    subject + r" (?:est|sont) (?:un|une) (?:groupe|duo|trio|formation|artiste) (?:de|du|d) " + label,
                    subject + r" (?:joue|jouent|pratique|pratiquent) (?:du |de la |de l )?" + label,
                    subject + r" (?:is|are) (?:an? )?" + label + r" (?:band|group|duo|trio|artist)",
                    subject + r" (?:plays|play) " + label,
                )
                if any(re.fullmatch(pattern, sentence) for pattern in patterns):
                    if genre not in genres and contract.relevant_genres([genre]):
                        genres.append(genre)
    return sorted(genres)[:8]


def _electronic_hardcore_only(record, raw_keywords, genres):
    """Disambiguate electronic hardcore from metal/punk hardcore.

    'Hardcore' is shared by punk and electronic music. One authenticated
    OpenAgenda source is enough, but its own explicit hardstyle/gabber/techno
    context cannot be ignored when it otherwise gives ONLY 'hardcore'.
    Explicit punk/metal/rock evidence still qualifies a mixed event.
    """
    if len(genres) != 1 or normalized(genres[0]) != "hardcore":
        return False
    labels = " ".join(x for x in raw_keywords if isinstance(x, str))
    description = record.get("description")
    original = (description.get("fr") or description.get("en")
                if isinstance(description, dict) else "")
    if isinstance(original, str) and 4 <= len(original) <= 12000:
        reader = _VisibleOfficialGenreText()
        try:
            reader.feed(original)
            reader.close()
            labels += " " + " ".join(reader.parts)
        except (ValueError, TypeError):
            return True  # fail closed when original evidence is malformed
    evidence = normalized(labels[:16000])
    electronic = re.search(
        r"\b(?:hardstyle|gabber|uptempo|frenchcore|hardtek|"
        r"techno|electronic|electronique|electro)\b", evidence)
    guitar = re.search(
        r"\b(?:punk|metal|rock|metalcore|deathcore|thrash|"
        r"grindcore|screamo|skramz)\b", evidence)
    return bool(electronic and not guitar)


def is_openagenda_event_url(url):
    if not isinstance(url, str) or not 20 <= len(url) <= 1000:
        return False
    try:
        u = urlsplit(url)
        return (u.scheme == "https" and u.hostname == "openagenda.com"
                and not u.username and not u.password and u.port is None
                and not u.query and not u.fragment
                and AGENDA_PATH.fullmatch(u.path) is not None)
    except ValueError:
        return False


def _performer_names(value):
    rows = value if isinstance(value, list) else [value]
    out = []
    for item in rows:
        if isinstance(item, str):
            n = item
        elif isinstance(item, dict) and bridge._event_types(
                item.get("@type")) & {"MusicGroup", "Person",
                                      "PerformingGroup", "Organization"}:
            n = item.get("name")
        else:
            continue
        if isinstance(n, str) and 2 <= len(n.strip()) <= 120:
            out.append(" ".join(n.split()))
    return out


# Recognize only explicit trailing promotional markers, not arbitrary
# parenthesized artist names or ordinary words that happen to contain "live".
_PROMOTIONAL_SUFFIX = re.compile(
    r"\s+(?:release\s+party|en\s+concert)\s*\Z", re.I)
_FORMER_MEMBER_SUFFIX = re.compile(r"\s+\(ex[\s-]+[^()]{1,80}\)\s*\Z", re.I)


def promotional_artist_candidate(title):
    """Extract a possible artist name, NEVER a source proof by itself."""
    if not isinstance(title, str):
        return None
    match = _PROMOTIONAL_SUFFIX.search(title)
    if not match:
        return None
    name = title[:match.start()].strip()
    if normalized(match.group(0)) == "en concert":
        name = _FORMER_MEMBER_SUFFIX.sub("", name).strip()
    if not 2 <= len(name) <= 120 or normalized(name) in PLACEHOLDERS:
        return None
    return name


def _confirmed_promotional_artist(title, record):
    """Use the original UID-bound announcement's own independent name usage.

    Require a separate, visible occurrence of the proposed name after
    eliminating repetitions of the full promotional title. No external
    site, known-band list, or genre inference from a former membership.
    """
    candidate = promotional_artist_candidate(title)
    if candidate is None:
        return None
    full = normalized(title)
    name = normalized(candidate)
    if not name or name == full:
        return None
    for field in ("description", "longDescription"):
        value = record.get(field)
        content = (value.get("fr") or value.get("en")) if isinstance(value, dict) else None
        if not isinstance(content, str) or not 4 <= len(content) <= 20000:
            continue
        reader = _VisibleOfficialGenreText()
        try:
            reader.feed(content)
            reader.close()
        except (TypeError, ValueError):
            continue
        visible = normalized(" ".join(reader.parts))
        # The full headline echoed in the body does not corroborate a name.
        visible = re.sub(r"(?<!\w)" + re.escape(full) + r"(?!\w)", " ", visible)
        # A named subject or an explicit group/artist introduction, rather
        # than an incidental mention (e.g. a tour venue or a former band).
        subject = r"(?<!\w)" + re.escape(name) + r"(?!\w)"
        role = r"(?:le groupe|la formation|l artiste|the band|the artist)"
        verb = r"(?:est|sont|fait|font|joue|jouent|a|ont|propose|proposent|poursuit|poursuivent|façonne|faconne|is|are|has|have|plays|play)"
        if (re.search(role + r"\s+" + subject, visible)
                or re.search(subject + r"\s+" + verb + r"(?!\w)", visible)):
            return candidate
    return None


def _bill(event):
    title = event.get("name")
    if not isinstance(title, str) or not 3 <= len(title) <= 900:
        raise ValueError("OpenAgenda: missing named event title")
    named = _performer_names(event.get("performer"))
    # A first-party title explicitly listing GROUP + GROUP is itself a named
    # complete bill, even when schema.org performer lists only the headliner.
    # Never generalize one headliner's genre to the support act; event.genre
    # is stored as an EVENT-level label.
    parts = re.split(r"\s+\+\s+", title)
    if len(parts) > 1:
        if any(not 2 <= len(part.strip()) <= 120 for part in parts):
            raise ValueError("OpenAgenda: malformed named lineup")
        title_names = [" ".join(part.split()) for part in parts]
        known = {normalized(n) for n in title_names}
        if any(normalized(n) not in known for n in named):
            raise ValueError("OpenAgenda: structured performer contradicts title")
        names = title_names
    elif named:
        names = named
    elif normalized(title) not in PLACEHOLDERS and "concert " not in normalized(title):
        # A single explicitly named act is sufficient only if the page is a
        # MusicEvent, not a generic exhibition or conference.
        if "MusicEvent" not in bridge._event_types(event.get("@type")):
            raise ValueError("OpenAgenda: untyped single-act concert")
        names = [title]
    else:
        raise ValueError("OpenAgenda: no explicitly named performers")
    if (len({normalized(s) for s in names}) != len(names)
            or any(not normalized(s) for s in names)):
        raise ValueError("OpenAgenda: duplicate or malformed performers")
    return names



def _numeric_uid(value):
    """Only decimal OpenAgenda IDs can enter a pinned first-party export URL."""
    if type(value) not in (int, str):
        raise ValueError("OpenAgenda: malformed numeric identifier")
    raw = str(value)
    if (not raw.isascii() or not raw.isdecimal()
            or not 1 <= len(raw) <= 12 or int(raw) == 0):
        raise ValueError("OpenAgenda: malformed numeric identifier")
    return int(raw)


def official_export_url(agenda_uid, event_uid):
    """OpenAgenda's own public read-only export, never a candidate URL."""
    agenda_uid = _numeric_uid(agenda_uid)
    event_uid = _numeric_uid(event_uid)
    return (f"https://openagenda.com/agendas/{agenda_uid}/events.json"
            f"?oaq%5Buids%5D%5B%5D={event_uid}&limit=1")



def original_event_url_from_export(raw_json, discovered_url, *,
                                   agenda_uid, event_uid):
    """Bind a syndicated OpenAgenda hint to its ACTUAL originating event.

    A city's public agenda can legitimately republish a concert whose origin
    is the venue's own OpenAgenda agenda. The public index must not authorize
    that origin: only a freshly fetched OpenAgenda export may establish its
    original UID, event UID, full slug and canonical permalink. On a genuine
    syndication we publish the *origin* URL, never the unbound index alias.
    No other host, guessed organizer website or secondary source is trusted.
    The regular verifier and Publisher still independently replay the export.
    """
    if not is_openagenda_event_url(discovered_url):
        raise ValueError("OpenAgenda: invalid syndicated event URL")
    origin_id = _numeric_uid(agenda_uid)
    record_id = _numeric_uid(event_uid)
    if not isinstance(raw_json, str) or not 20 <= len(raw_json) <= 400_000:
        raise ValueError("OpenAgenda: invalid syndication export")
    try:
        doc = json.loads(raw_json)
    except (TypeError, ValueError) as exc:
        raise ValueError("OpenAgenda: invalid syndication JSON") from exc
    if (not isinstance(doc, dict) or doc.get("total") != 1
            or not isinstance(doc.get("events"), list)
            or len(doc["events"]) != 1
            or not isinstance(doc["events"][0], dict)):
        raise ValueError("OpenAgenda: ambiguous syndicated event")
    record = doc["events"][0]
    origin = record.get("origin")
    if ("originAgenda" in record and record["originAgenda"] != origin):
        raise ValueError("OpenAgenda: contradictory syndicated origins")
    parts = [part for part in urlsplit(discovered_url).path.split("/") if part]
    if parts and parts[0] in ("fr", "en"):
        parts = parts[1:]
    if len(parts) != 3 or parts[1] != "events":
        raise ValueError("OpenAgenda: invalid syndicated event path")
    event_slug = record.get("slug")
    originating_slug = origin.get("slug") if isinstance(origin, dict) else None
    discovered_slug = re.sub(r"^[0-9]{1,12}[_-]", "", parts[2])
    if (type(record.get("uid")) is not int or record["uid"] != record_id
            or not isinstance(origin, dict)
            or type(origin.get("uid")) is not int
            or origin["uid"] != origin_id
            or not isinstance(event_slug, str)
            or re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,160}", event_slug) is None
            or discovered_slug != event_slug
            or not isinstance(originating_slug, str)
            or re.fullmatch(r"[a-z0-9][a-z0-9-]{1,119}",
                            originating_slug) is None):
        raise ValueError("OpenAgenda: syndicated original identity not authenticated")
    if normalized(originating_slug) == normalized(parts[0]):
        return discovered_url
    # Mismatched agenda slugs are syndication ONLY when the same exact
    # original UID pair is confirmed by OpenAgenda's own canonical permalink.
    expected = (f"https://openagenda.com/agendas/{origin_id}/events/"
                f"{record_id}")
    if record.get("permalink") != expected:
        raise ValueError("OpenAgenda: syndicated origin permalink not authenticated")
    original_url = (f"https://openagenda.com/{originating_slug}/events/"
                    f"{record_id}_{event_slug}")
    if not is_openagenda_event_url(original_url):
        raise ValueError("OpenAgenda: invalid originating event URL")
    return original_url


def _known_catalogue_postcode(venue):
    """Only a concrete 5-digit postal code can contradict official OA data."""
    value = venue.get("postalCode") if isinstance(venue, dict) else None
    return value.strip() if isinstance(value, str) and re.fullmatch(
        r"[0-9]{5}", value.strip()) else None


def _known_catalogue_address(venue):
    """A provisional historical map placeholder is NOT a street address.

    Never turn 'Adresse exacte à vérifier' into a real location constraint.
    Concrete stored streets remain protected by the existing exact check.
    """
    value = venue.get("address") if isinstance(venue, dict) else None
    if not isinstance(value, str):
        return None
    text = normalized(value)
    if (not text or len(text) < 6 or any(phrase in text for phrase in (
            "a verifier", "a preciser", "adresse inconnue",
            "non renseigne", "geolocalisation indicative"))):
        return None
    return value


def _verified_street(street, venue, place):
    """Match an official numbered street to an unnumbered map entry safely.

    A historic map may say "Quai des Antilles" while the OpenAgenda
    event gives "21 quai des Antilles". Never ignore a conflicting
    stored house number. The extra case requires an independently
    positioned named venue, consistent postcode and nearby event GPS.
    """
    source, reference = normalized(street), normalized(venue.get("address"))
    if not source or not reference:
        return False
    if source == reference or source.startswith(reference + " "):
        return True
    # Only an official leading house number may be removed, never a
    # recorded house number or a mismatching street.
    if re.match(r"^[0-9]", reference):
        return False
    without_number = re.sub(r"^[0-9]+(?:[a-z]|\s+(?:bis|ter|quater))?\s+", "", source)
    if (without_number == source or
            not (without_number == reference or
                 without_number.startswith(reference + " "))):
        return False
    precision = normalized(venue.get("geoPrecision"))
    if not (precision.startswith("point du lieu") or
            precision.startswith("point nominatif") or
            precision.startswith("noeud openstreetmap")):
        return False
    try:
        lat1, lon1 = float(place["latitude"]), float(place["longitude"])
        lat2, lon2 = float(venue["latitude"]), float(venue["longitude"])
    except (KeyError, TypeError, ValueError):
        return False
    if not all(math.isfinite(n) for n in (lat1, lon1, lat2, lon2)):
        return False
    if not all(-90 <= x <= 90 for x in (lat1, lat2)):
        return False
    if not all(-180 <= x <= 180 for x in (lon1, lon2)):
        return False
    radius = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    arc = (math.sin(dp / 2) ** 2 +
           math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * radius * math.asin(min(1, math.sqrt(arc))) <= 125


def verified_export(raw_json, url, when, venue, *, agenda_uid, event_uid):
    """Fresh OpenAgenda-owned single-event export; no external corroboration.

    The public national index may suggest IDs, but cannot sign a concert.
    The actual OpenAgenda export must bind both IDs to the exact source slug,
    date, published location and music classification.
    """
    if not is_openagenda_event_url(url):
        raise ValueError("OpenAgenda: noncanonical event URL")
    origin_id = _numeric_uid(agenda_uid)
    record_id = _numeric_uid(event_uid)
    if not isinstance(raw_json, str) or not 20 <= len(raw_json) <= 400_000:
        raise ValueError("OpenAgenda: official JSON export missing")
    try:
        doc = json.loads(raw_json)
    except (TypeError, ValueError) as exc:
        raise ValueError("OpenAgenda: invalid official JSON export") from exc
    if (not isinstance(doc, dict) or doc.get("total") != 1
            or not isinstance(doc.get("events"), list)
            or len(doc["events"]) != 1
            or not isinstance(doc["events"][0], dict)):
        raise ValueError("OpenAgenda: no unique original event")
    record = doc["events"][0]
    # The still-live legacy OpenAgenda events.json export calls this "origin",
    # whereas the v2 API calls it "originAgenda". We deliberately read the
    # legacy contract used by official_export_url rather than silently accepting
    # an unbound discovery/index field as the source identity.
    agenda = record.get("origin")
    if ("originAgenda" in record and record["originAgenda"] != agenda):
        raise ValueError("OpenAgenda: contradictory origin identities")
    path_parts = [x for x in urlsplit(url).path.split("/") if x]
    if path_parts and path_parts[0] in ("fr", "en"):
        path_parts = path_parts[1:]
    if len(path_parts) != 3 or path_parts[1] != "events":
        raise ValueError("OpenAgenda: invalid original event slug")
    event_slug = str(record.get("slug") or "")
    source_slug = re.sub(r"^[0-9]{1,12}[_-]", "", path_parts[2])
    if (type(record.get("uid")) is not int or record["uid"] != record_id
            or not isinstance(agenda, dict)
            or type(agenda.get("uid")) is not int
            or agenda["uid"] != origin_id
            or normalized(agenda.get("slug")) != normalized(path_parts[0])
            or not event_slug or event_slug != source_slug):
        raise ValueError("OpenAgenda: original event identity not authenticated")
    # OpenAgenda status 1 means published/scheduled; cancelled, postponed
    # and deprogrammed records never enter the public confirmed catalogue.
    if record.get("status") != 1:
        raise ValueError("OpenAgenda: event is not currently scheduled")
    event_status = str(record.get("eventStatus") or "").casefold()
    if any(token in event_status for token in CANCELLED):
        raise ValueError("OpenAgenda: event is cancelled or postponed")
    try:
        exact = dt.date.fromisoformat(when)
        if (record.get("firstDate") != exact.isoformat()
                or dt.date.fromisoformat(record.get("lastDate")) < exact):
            raise ValueError("OpenAgenda: contradictory event date")
    except (ValueError, TypeError) as exc:
        raise ValueError("OpenAgenda: invalid event date") from exc
    place = record.get("location")
    if (not isinstance(place, dict)
            or normalized(place.get("name")) != normalized(venue.get("name"))
            or normalized(place.get("city")) != normalized(venue.get("city"))):
        raise ValueError("OpenAgenda: official physical venue mismatch")
    published_postcode = _known_catalogue_postcode(venue)
    if (place.get("postalCode") and published_postcode
            and str(place["postalCode"]).strip() != published_postcode):
        raise ValueError("OpenAgenda: postal code mismatch")
    street = place.get("address")
    if (street and _known_catalogue_address(venue)
            and not _verified_street(street, venue, place)):
        raise ValueError("OpenAgenda: official street location mismatch")
    if str(place.get("countryCode") or "").lower() not in ("fr", "gp",
            "mq", "gf", "re", "yt", "nc", "pf", "wf", "pm", "bl", "mf"):
        raise ValueError("OpenAgenda: non-French event location")
    title = record.get("title")
    title = (title.get("fr") or title.get("en")) if isinstance(
        title, dict) else None
    if (not isinstance(title, str) or not 3 <= len(title) <= 900
            or any(x in normalized(title)
                   for x in ("festival", "annule", "annulled"))):
        raise ValueError("OpenAgenda: missing concert bill or festival")
    # An OpenAgenda title may append the EXACT physical venue name as a
    # presentation suffix (e.g. "LocoMuerte + DoorShan - La Maroquinerie").
    # Do not manufacture an artist named "DoorShan - La Maroquinerie".
    # This is safe only after the independent location block above has
    # authenticated the very same venue.
    suffix_with_city = re.search(
        r"\s+[-–—]\s+([^–—]+?)\s+[-–—]\s+([^–—]+?)\s*\Z", title)
    if (suffix_with_city
            and normalized(suffix_with_city.group(1)) ==
                normalized(venue.get("name"))
            and normalized(suffix_with_city.group(2)) ==
                normalized(venue.get("city"))):
        title = title[:suffix_with_city.start()]
    else:
        suffix = re.search(r"\s+[-–—]\s+([^–—]+?)\s*\Z", title)
        if suffix and normalized(suffix.group(1)) == normalized(venue.get("name")):
            title = title[:suffix.start()]
    keys = record.get("keywords")
    raw_genres = ((keys.get("fr") or keys.get("en"))
                  if isinstance(keys, dict) else None)
    # Keywords are useful but optional on a published OpenAgenda record.
    # Explicit music genres in the original, UID-authenticated DESCRIPTION
    # are equivalent first-party evidence. No second event domain is required.
    # A collector/index hint is never enough and the publisher re-fetches.
    genres = ([x for x in raw_genres
               if isinstance(x, str) and contract.relevant_genres([x])]
              if isinstance(raw_genres, list) else [])
    genres = list(dict.fromkeys(genres))
    if not genres:
        genres = _described_official_genres(record)
    if not genres:
        # Use exactly the same named bill as the final identity verification.
        candidates = _bill({"@type": "MusicEvent", "name": title})
        names_for_genre = [promotional_artist_candidate(n) or n for n in candidates]
        genres = _long_description_genres(record, names_for_genre)
    if _electronic_hardcore_only(
            record, raw_genres if isinstance(raw_genres, list) else [], genres):
        genres = []
    if not genres or len(genres) > 20:
        raise ValueError("OpenAgenda: original metal/punk genre evidence missing")
    # The raw export has no typed performers in many official records.
    # An explicit promotional suffix is not part of the group's identity.
    # If the original announcement cannot corroborate the cleaned name,
    # do not create a false artist from the commercial headline.
    names = _bill({"@type": "MusicEvent", "name": title})
    cleaned = []
    for name in names:
        if promotional_artist_candidate(name) is not None:
            confirmed = _confirmed_promotional_artist(name, record)
            if confirmed is None:
                raise ValueError("OpenAgenda: promotional artist name not confirmed")
            cleaned.append(confirmed)
        else:
            cleaned.append(name)
    if len({normalized(n) for n in cleaned}) != len(cleaned):
        raise ValueError("OpenAgenda: duplicate normalized performers")
    return cleaned, genres


def verified_bill(html, url, when, venue):
    """Return (names, event_genres) from one fresh, source-bound OA page."""
    if not is_openagenda_event_url(url):
        raise ValueError("Not an individual public OpenAgenda event URL")
    if not isinstance(html, str) or not 100 <= len(html) <= 400_000:
        raise ValueError("OpenAgenda: event page unavailable or oversized")
    rows = [e for e in discover.read_ld(html) if isinstance(e, dict) and
            bridge._event_types(e.get("@type")) & {"Event", "MusicEvent"}]
    eligible = []
    for row in rows:
        if discover.reject_listing(row.get("name")):
            continue
        if discover.iso_day(row.get("startDate")) != when:
            continue
        try:
            dt.date.fromisoformat(when)
        except (ValueError, TypeError):
            continue
        state = str(row.get("eventStatus") or "").casefold()
        if any(s in state for s in CANCELLED):
            continue
        location = row.get("location")
        if not isinstance(location, dict):
            continue
        if normalized(location.get("name")) != normalized(venue.get("name")):
            continue
        addr = location.get("address")
        if isinstance(addr, dict):
            if (addr.get("addressLocality") and normalized(
                    addr["addressLocality"]) != normalized(venue.get("city"))):
                continue
            published_postcode = _known_catalogue_postcode(venue)
            if (addr.get("postalCode") and published_postcode and
                    str(addr["postalCode"]).strip() != published_postcode):
                continue
            street = addr.get("streetAddress")
        elif isinstance(addr, str):
            street = addr
        else:
            street = None
        # The Opendata event is venue-scoped: an explicitly contradictory
        # postal/street address fails. If absent, the already published venue
        # supplies the map point, never a fabricated city-centre coordinate.
        if (street and _known_catalogue_address(venue) and
                normalized(street) != normalized(venue["address"])):
            continue
        genre = row.get("genre")
        genre = ([genre] if isinstance(genre, str) else genre)
        if (not isinstance(genre, list)
                or any(not isinstance(g, str) for g in genre)
                or not contract.relevant_genres(genre)):
            # The same event's structured performers may contain individual
            # genre labels even when Event.genre is omitted.
            genre, _ = bridge.event_genres_from_own_bill(row)
            if not contract.relevant_genres(genre):
                continue
        try:
            names = _bill(row)
        except ValueError:
            continue
        eligible.append((names, list(dict.fromkeys(genre))))
    if len(eligible) != 1:
        raise ValueError("OpenAgenda: no unique exact dated musical event")
    return eligible[0]
