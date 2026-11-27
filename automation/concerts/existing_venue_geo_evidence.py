"""Read-only generic evidence for correcting existing municipal-centroid pins.

A published concert supplies an identity anchor, not new publishing authority.
Read its individual official MusicEvent/ Event address, verify the exact French
postal address and independently named OSM object, and bind the event origin
to the known official source or an independently attributed OSM website.
This never edits the catalogue or produces a signed approval.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
import re
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import discover
import independent_named_site_geo as geo
import official_rss_jsonld_bridge as bridge
import official_venue_single_source as official
import official_html_evidence as visible
import source_admission_intake as intake
import source_evidence_probe as probe
import triage
import venue_address_osm_source as address_source

SCHEMA = "grossesondes.concert.existing-venue-geo-evidence.v1"


def require(ok, message):
    if not ok:
        raise ValueError("Existing venue geo evidence: " + message)


class EvidenceHeld(ValueError):
    """Fixed diagnostic, never expose URLs or raw transport errors."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class MissingVenueAddress(ValueError):
    """Dated event recognized, but no explicit address in its own body."""


def eligible(venue):
    # A building centroid with an explicit independently named location is
    # not the same as a municipality centroid. Do not redo accurate pins.
    precision = triage.words(venue.get("geoPrecision"))
    return ("centre de commune" in precision or
            precision == "salle a recontroler")



# A street number is optional: BAN independently checks the exact street,
# municipality and named OSM site. Do not guess an address from arbitrary text.
STREET = re.compile(
    r"(?:(?:[0-9]{1,4}(?:\s*(?:bis|ter|quater|[a-z]))?)\s+)?"
    r"(?:rue|avenue|av\.|boulevard|bd\.|place|route|chemin|impasse|allée|allee|"
    r"quai|cours|passage|square|parvis|promenade|voie|esplanade|sentier|"
    r"montée|montee|lieu-dit)\s+[\wÀ-ÿ'’ .\-]{2,120}", re.I)
ADDRESS = re.compile(r"(?P<street>.+?)\s*[,;–—]?\s+(?P<postcode>\d{5})\s+(?P<city>.+)", re.I)
NONVENUE = re.compile(r"\b(?:billetterie|ticket(?:s|ing)?|administration|siege social|"
                       r"bureau(?:x)?|correspondance|facturation|reservation|"
                       r"parking|restaurant|hebergement)\b")
PLACE_LABELS = {"lieu", "salle", "adresse", "lieu du concert",
                "salle du concert", "adresse de la salle", "adresse du concert"}
STOP = visible.END_SECTION | {"billetterie", "reservations", "autres dates",
                              "autres lieux", "autres evenements"}


class AddressBlocks(visible.VisibleBlocks):
    """Keep explicit address blocks and inline break-delimited address lines."""
    def __init__(self):
        super().__init__(leaf_divs=True)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if not self.ignored and (tag == "template" or "hidden" in attributes
                or attributes.get("aria-hidden", "").lower() == "true"
                or re.search(r"display\s*:\s*none|visibility\s*:\s*hidden",
                             attributes.get("style") or "", re.I)):
            if tag not in visible.VOID:
                self.ignored = 1
            return
        if tag == "br" and not self.ignored:
            self.handle_data(" \u241e ")
        super().handle_starttag(tag, attrs)
        if tag == "address" and not self.ignored:
            self.frames.append([tag, []])

    def handle_endtag(self, tag):
        if tag == "address" and not self.ignored:
            for i in range(len(self.frames) - 1, -1, -1):
                if self.frames[i][0] == tag:
                    frame = self.frames.pop(i)
                    value = " ".join(" ".join(frame[1]).split())
                    if value:
                        self.blocks.append((tag, value[:1000]))
                    return
        super().handle_endtag(tag)


def _postal_line(line, city):
    # Recognize a complete postal address, never silently select the first
    # number or the first municipality mentioned in a free-form paragraph.
    line = " ".join(line.replace("\u241e", " ").split()).strip(" ,;")
    match = ADDRESS.fullmatch(line)
    if not match:
        return None
    street = match["street"].strip(" ,;–—")
    actual_city = match["city"].strip(" ,;")
    # France is redundant with the independently established French venue,
    # but another explicit country must not be discarded.
    actual_city = re.sub(r"\s*[,–—]?\s+France$", "", actual_city, flags=re.I)
    if (triage.words(actual_city) != triage.words(city)
            or not STREET.fullmatch(street)
            or NONVENUE.search(triage.words(street))):
        return None
    return street, match["postcode"]


def _named_location(text, venue):
    """Exact named venue heading or explicit venue label, not a substring."""
    name = triage.words(venue["name"])
    value = triage.words(text)
    return bool(name and (value == name or any(
        value == label + " " + name for label in PLACE_LABELS)))


def _event_day(text):
    day = visible._date_in(text)
    if day is not None:
        return day
    match = re.fullmatch(r"(?:(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+)?"
                         r"(\d{1,2})\s+(\d{1,2})\s+(20\d{2})(?:\s+\d{1,2}:\d{2})?",
                         text.strip(), re.I)
    if match:
        try:
            return dt.date(int(match[3]), int(match[2]), int(match[1])).isoformat()
        except ValueError:
            return "_invalid_date"
    return None


def visible_address(html, event, venue):
    """Only a dated exact event heading and an explicitly named address.

    Footer/menu addresses and recommendations are ignored. A street is
    accepted only in the same named venue block or immediately following
    its exact heading, and still needs independent BAN and named OSM proof.
    """
    parser = AddressBlocks()
    parser.feed(html)
    parser.close()
    headings = [(i, text) for i, (tag, text) in enumerate(parser.blocks)
                if tag == "h1"]
    require(len(headings) == 1 and triage.words(event.get("title"))
            and triage.words(headings[0][1]) == triage.words(event["title"]),
            "visible event heading differs from published concert")
    detail = parser.blocks[headings[0][0] + 1:][:160]
    cut = next((i for i, (tag, text) in enumerate(detail)
                if triage.words(text) in STOP | {"vous devriez aimer", "nous vous recommandons egalement", "we also recommend"}),
               len(detail))
    detail = detail[:cut]
    # Date fields may precede the sole event heading. Require a nearby
    # unambiguous date, and never replace a contradictory date after it.
    preceding = parser.blocks[max(0, headings[0][0] - 6):headings[0][0]]
    before_days = {_event_day(text) for _, text in preceding
                   if _event_day(text)}
    after_day = next((_event_day(text) for _, text in detail[:12]
                      if _event_day(text)), None)
    require((after_day == event["date"] and
             (not before_days or before_days == {event["date"]}))
            or (after_day is None and before_days == {event["date"]}),
            "visible event date differs")
    addresses = set()
    for i, (tag, text) in enumerate(detail):
        if NONVENUE.search(triage.words(text)):
            continue
        # An explicit venue block with line breaks, punctuation or address
        # label may contain the entire address without any special CSS.
        lines = [part.strip() for part in text.split("\u241e") if part.strip()]
        if len(lines) >= 2 and _named_location(lines[0], venue):
            address = _postal_line(" ".join(lines[1:]), venue["city"])
            if address:
                addresses.add(address)
        if _named_location(text, venue):
            for n in (1, 2):
                following = detail[i+1:i+1+n]
                if len(following) != n or any(
                        kind.startswith("h") or NONVENUE.search(triage.words(value))
                        for kind, value in following):
                    continue
                address = _postal_line(" ".join(value for _, value in following),
                                       venue["city"])
                if address:
                    addresses.add(address)
    if not addresses:
        # Do not reinterpret a conflicting explicit postal address as absent.
        # A postal-looking line in the immediate named venue block must be
        # resolved on that event page before any practical-page fallback.
        for i, (_, value) in enumerate(detail):
            lines = value.split("\u241e")
            if _named_location(lines[0], venue):
                nearby = " ".join(lines[1:] + [v for _, v in detail[i+1:i+3]])
                require(not re.search(r"\b\d{5}\b", nearby),
                        "explicit event postal address not verified")
        raise MissingVenueAddress("no explicit visible named-venue address")
    require(len(addresses) == 1, "one explicit visible named-venue address required")
    street, postcode = next(iter(addresses))
    site = dict(venue, address=street, postalCode=postcode)
    require(address_source.eligible_address(site), "non-geocodable visible address")
    return site


PRACTICAL_LABELS = {"infos pratiques", "informations pratiques",
                    "acces", "venir", "venir a la salle", "adresse", "getting here"}
ROOM_SUFFIXES = {"grande salle", "petite salle", "salle principale"}


def _room_label(text, venue):
    # An explicit subroom label may omit the venue's leading article.
    # Never strip arbitrary words, a municipality or another venue name.
    name = triage.words(venue["name"])
    names = {name, re.sub(r"^(?:le|la|les) ", "", name)}
    parts = [triage.words(p) for p in text.split(",")]
    return bool(name and parts[0] in names and
                (len(parts) == 1 or
                 (len(parts) == 2 and parts[1] in ROOM_SUFFIXES)))


class PracticalLinks(HTMLParser):
    """Read visible navigation links, never a guessed path or third-party URL."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.href = None
        self.parts = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag not in visible.VOID:
                self.skip += 1
            return
        attrs = dict(attrs)
        if (tag in {"script", "style", "template", "noscript", "svg"}
                or "hidden" in attrs or attrs.get("aria-hidden") == "true"
                or re.search(r"display\s*:\s*none|visibility\s*:\s*hidden",
                             attrs.get("style") or "", re.I)):
            if tag not in visible.VOID:
                self.skip = 1
            return
        if tag == "a":
            self.href = attrs.get("href")
            self.parts = []

    def handle_data(self, data):
        if not self.skip and self.href is not None:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if self.skip:
            if tag not in visible.VOID:
                self.skip -= 1
            return
        if tag == "a" and self.href is not None:
            if triage.words(" ".join(self.parts)) in PRACTICAL_LABELS:
                self.links.append(self.href)
            self.href = None


def linked_practical_address(html, event, venue, fetch, cache):
    """A known official event may link to one official named venue address.

    This fallback is unavailable for an unbound or third-party origin.
    The event title/date were checked before MissingVenueAddress was raised;
    independently require an explicit event location label and the physical
    venue's name on the practical page. BAN/OSM still validate the result.
    """
    url = event["officialUrl"]
    require(official.official_origin(venue, url) is not None,
            "linked address requires independently bound event domain")
    parser = AddressBlocks()
    parser.feed(html)
    headings = [i for i, (tag, _) in enumerate(parser.blocks) if tag == "h1"]
    require(len(headings) == 1, "linked address needs one event heading")
    details = parser.blocks[headings[0]+1:headings[0]+17]
    labels = []
    for i, (_, value) in enumerate(details):
        if triage.words(value) in {"lieu", "salle", "lieu du concert"} and i+1 < len(details):
            labels.append(details[i+1][1])
        elif re.match(r"^(?:lieu|salle)\s*:", value, re.I):
            labels.append(value.split(":", 1)[1].strip())
    require(bool(labels) and all(_room_label(x, venue) for x in labels),
            "event does not explicitly identify this venue")
    links = PracticalLinks()
    links.feed(html)
    source = urlsplit(url)
    candidates = set()
    for link in links.links:
        resolved = urljoin(url, link)
        target = urlsplit(resolved)
        if (target.scheme == "https" and target.netloc.casefold() == source.netloc.casefold()
                and not target.username and not target.password and not target.query
                and not target.fragment and target.path.rstrip("/") != source.path.rstrip("/")
                and intake.valid_https(resolved)):
            candidates.add(resolved)
    require(len(candidates) == 1, "one visible official practical link required")
    page = fetch(next(iter(candidates)), cache)
    require(isinstance(page, str) and 0 < len(page) <= probe.MAX_BYTES,
            "official practical page unavailable")
    blocks = AddressBlocks()
    blocks.feed(page)
    addresses = set()
    for i, (tag, value) in enumerate(blocks.blocks):
        if tag not in {"h1", "h2", "h3", "h4"} or not _named_location(value, venue):
            continue
        for kind, text in blocks.blocks[i+1:i+6]:
            if kind.startswith("h") or NONVENUE.search(triage.words(text)):
                break
            for line in text.split("\u241e"):
                address = _postal_line(line, venue["city"])
                if address:
                    addresses.add(address)
    require(len(addresses) == 1, "one named official practical address required")
    street, postcode = next(iter(addresses))
    site = dict(venue, address=street, postalCode=postcode)
    require(address_source.eligible_address(site), "non-geocodable practical address")
    return site


class NamedFooterBlocks(AddressBlocks):
    """Read address blocks only from a real, visible footer."""
    def __init__(self):
        super().__init__()
        self.in_footer = False
        self.outer_hidden = 0

    def handle_starttag(self, tag, attrs):
        flags = dict(attrs)
        if self.outer_hidden:
            if tag not in visible.VOID:
                self.outer_hidden += 1
            return
        if not self.in_footer:
            if tag in {"script", "style", "template", "noscript", "svg", "form"} or (
                    "hidden" in flags or (flags.get("aria-hidden") or "").lower() == "true"
                    or re.search(r"display\s*:\s*none|visibility\s*:\s*hidden",
                                 flags.get("style") or "", re.I)):
                if tag not in visible.VOID:
                    self.outer_hidden = 1
                return
            if tag == "footer":
                self.in_footer = True
            return
        super().handle_starttag(tag, attrs)

    def handle_data(self, data):
        if self.in_footer and not self.outer_hidden:
            super().handle_data(data)

    def handle_endtag(self, tag):
        if self.outer_hidden:
            if tag not in visible.VOID:
                self.outer_hidden -= 1
            return
        if self.in_footer:
            if tag == "footer" and not self.ignored:
                self.in_footer = False
                self.frames.clear()
            else:
                super().handle_endtag(tag)


def _named_footer_address(html, venue):
    """A complete named footer address is a location hint, not an event proof."""
    parser = NamedFooterBlocks()
    parser.feed(html)
    parser.close()
    addresses = set()
    for _, text in parser.blocks:
        # Keep the name, street, postcode and municipality within ONE block.
        # Optional phone metadata is not part of the address.
        if NONVENUE.search(triage.words(text)):
            continue
        match = re.fullmatch(r"(.{2,140}?)[,:\u241e]\s*(.+)", text)
        if not match or not _named_location(match[1], venue):
            continue
        rest = re.sub(r"\s*/\s*t[ée]l\.?\s*:\s*[+0-9 .()\-]+$", "",
                      match[2], flags=re.I)
        # Postal separators are not part of the street name.
        rest = re.sub(r"\s+[–—-]\s+(?=\d{5}\s)", " ", rest)
        address = _postal_line(rest, venue["city"])
        require(address is not None, "named footer postal address unconfirmed")
        addresses.add(address)
    if not addresses:
        raise MissingVenueAddress("no named visible footer address")
    require(len(addresses) == 1, "one named visible footer address required")
    street, postcode = next(iter(addresses))
    site = dict(venue, address=street, postalCode=postcode)
    require(address_source.eligible_address(site), "non-geocodable footer address")
    return site


def _footer_after_exact_event(html, event, venue):
    """Require the published event's own visible title, date and named place.

    Only used on a known official venue origin after missing body address.
    A generic site footer, even on a venue domain, cannot identify the room
    of a show which does not itself explicitly identify that room.
    """
    require(official.official_origin(venue, event["officialUrl"]) is not None,
            "footer address requires independently bound event domain")
    parsed = AddressBlocks()
    parsed.feed(html)
    parsed.close()
    headings = [(i, t) for i, (tag, t) in enumerate(parsed.blocks) if tag == "h1"]
    require(len(headings) == 1 and triage.words(headings[0][1]) == triage.words(event.get("title")),
            "footer event title unconfirmed")
    i = headings[0][0]
    detail = []
    for tag, text in parsed.blocks[i+1:]:
        if triage.words(text) in STOP | {"vous devriez aimer", "nous vous recommandons egalement",
                                         "we also recommend"}:
            break
        detail.append((tag, text))
    dates = {_event_day(text) for _, text in detail if _event_day(text)}
    require(dates == {event["date"]}, "footer event date unconfirmed")
    require(any(_named_location(t, venue) for _, t in detail),
            "footer event venue unconfirmed")
    return _named_footer_address(html, venue)


def extract_address(html, event, venue):
    """Only an unambiguous, exact, dated event and its own physical Place."""
    url = event.get("officialUrl")
    require(isinstance(url, str) and bool(intake.valid_https(url)),
            "invalid published event URL")
    require(event.get("venueId") == venue.get("id")
            and event.get("sourceType") == "salle", "event/venue mismatch")
    require(isinstance(html, str) and 0 < len(html) <= probe.MAX_BYTES,
            "invalid event response")
    nodes = [n for n in discover.read_ld(html) if isinstance(n, dict)
             and bridge._event_types(n.get("@type")) & {"MusicEvent", "Event"}]
    if not nodes:
        return visible_address(html, event, venue)
    # Recommendation cards may include other events. Select one exact
    # canonical detail only if every other node is demonstrably distinct.
    matches = [n for n in nodes if isinstance(n.get("url"), str)
               and n["url"].rstrip("/") == url.rstrip("/")]
    require(len(matches) == 1, "single structured event required")
    node = matches[0]
    primary = urlsplit(url)
    for other in nodes:
        if other is node:
            continue
        other_url = other.get("url")
        require(isinstance(other_url, str) and intake.valid_https(other_url)
                and isinstance(other.get("name"), str)
                and bool(triage.words(other["name"]))
                and triage.words(other["name"]) != triage.words(node.get("name")),
                "ambiguous structured recommendation")
        parts = urlsplit(other_url)
        require(parts.netloc == primary.netloc and parts.scheme == "https"
                and bool(parts.path) and not parts.query and not parts.fragment
                and parts.path.rstrip("/") != primary.path.rstrip("/"),
                "ambiguous structured recommendation")
    raw_url = node.get("url")
    require(isinstance(raw_url, str) and raw_url.rstrip("/") == url.rstrip("/"),
            "structured event URL differs from published source")
    raw_day = node.get("startDate")
    require(isinstance(raw_day, str) and re.fullmatch(
        r"20\d{2}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)?", raw_day)
        and dt.date.fromisoformat(raw_day[:10]).isoformat() == event.get("date"),
        "structured event day differs from published date")
    place = node.get("location")
    require(isinstance(place, dict)
            and bridge._event_types(place.get("@type")) & {"Place", "MusicVenue"}
            and triage.words(place.get("name")) == triage.words(venue.get("name"))
            and bool(triage.words(venue.get("name"))), "named place mismatch")
    address = place.get("address")
    # Fall back only for absent address, never contradict an explicit one.
    if address is None:
        return visible_address(html, event, venue)
    require(isinstance(address, dict)
            and "PostalAddress" in bridge._event_types(address.get("@type")),
            "structured postal address missing")
    street, postcode = address.get("streetAddress"), address.get("postalCode")
    if isinstance(postcode, str):
        postcode = re.sub(r"^(\d{2})\s+(\d{3})$", r"\1\2", postcode.strip())
    require(isinstance(street, str) and 6 <= len(street.strip()) <= 160
            and isinstance(postcode, str) and re.fullmatch(r"\d{5}", postcode)
            and triage.words(address.get("addressLocality")) == triage.words(venue.get("city"))
            and bool(triage.words(venue.get("city"))), "exact postal identity missing")
    country = address.get("addressCountry")
    if isinstance(country, dict):
        require(bridge._event_types(country.get("@type")) == {"Country"},
                "French postal country not established")
        country = country.get("name")
    require(isinstance(country, str) and country.strip().casefold() in {"fr", "fra", "france"},
            "French postal country not established")
    # Existing published regional identity is retained, never inferred from
    # a search result or changed by the event page.
    site = dict(venue, address=street.strip(), postalCode=postcode)
    require(address_source.eligible_address(site), "non-geocodable postal address")
    return site


def verify(event, venue, *, fetch=probe.safe_fetch, cache=None):
    """Return evidence only, with no signature or catalogue write permission."""
    require(isinstance(event, dict) and isinstance(venue, dict)
            and eligible(venue), "only municipal-centroid/recheck pins eligible")
    url = event.get("officialUrl")
    require(isinstance(url, str) and bool(intake.valid_https(url)),
            "unsafe event URL")
    cache = {} if cache is None else cache
    try:
        html = fetch(url, cache)
    except (ValueError, TypeError, KeyError, OSError, TimeoutError) as exc:
        raise EvidenceHeld("event_fetch_unavailable") from exc
    try:
        site = extract_address(html, event, venue)
    except MissingVenueAddress:
        # Keep the existing practical-page route first. If it actually
        # fetched a page, a conflicting or unverifiable address must not be
        # bypassed by a footer. Only an absent/unusable link permits fallback.
        practical_fetched = False
        def practical_fetch(url, shared):
            nonlocal practical_fetched
            practical_fetched = True
            return fetch(url, shared)
        try:
            site = linked_practical_address(html, event, venue, practical_fetch, cache)
        except (ValueError, TypeError, KeyError, OSError, TimeoutError) as exc:
            if practical_fetched:
                raise EvidenceHeld("linked_practical_address_unconfirmed") from exc
            try:
                site = _footer_after_exact_event(html, event, venue)
            except (ValueError, TypeError, KeyError, OSError, TimeoutError):
                raise EvidenceHeld("linked_practical_address_unconfirmed") from exc
    except (ValueError, TypeError, KeyError, OSError, TimeoutError) as exc:
        raise EvidenceHeld("event_identity_or_address_unconfirmed") from exc

    def bounded(endpoint, limit):
        body = fetch(endpoint, cache)
        require(isinstance(body, str) and 0 < len(body) <= min(limit, probe.MAX_BYTES),
                "independent geographical evidence unavailable")
        return body, endpoint

    # Only an independently bound official venue origin may invoke the
    # extra public-establishment corroboration for a conflicting OSM street.
    homepage = official.official_origin(venue, url)
    try:
        options = {"official_website": homepage} if homepage else {}
        feature, lat, lon, precision = geo.verify(site, bounded, **options)
    except (ValueError, TypeError, KeyError, OSError, TimeoutError) as exc:
        # Compare only known fixed messages; never persist remote response text.
        msg = str(exc)
        if msg == "Independent BAN/OSM site: one exact government street address required":
            code = "ban_exact_address_unconfirmed"
        elif isinstance(exc, geo.NamedFeatureHeld):
            code = exc.code
        elif msg == "Independent BAN/OSM site: one independent named OSM feature at exact address required":
            code = "osm_named_feature_unconfirmed"
        else:
            code = "independent_geo_unavailable_or_invalid"
        raise EvidenceHeld(code) from exc
    require(precision in {"named-site-point", "named-site-area"},
            "no independent named physical site")
    # The existing source manifest is only one provenance route. Unlisted
    # venues may use the independently matched OSM website, without a PR.
    if homepage is None:
        homepage, independently_named = address_source.website_from_address(
            site, fetch=fetch, cache=cache)
        require(independently_named == feature, "independent site changed")
    a, b = intake.valid_https(url), intake.valid_https(homepage)
    require(bool(a and b) and a.removeprefix("www.") == b.removeprefix("www."),
            "event domain not independently attributable to venue")
    patch = {"address": site["address"], "postalCode": site["postalCode"],
             "latitude": lat, "longitude": lon, "geoSource": feature,
             "geoPrecision": precision}
    return {"schema": SCHEMA, "venueId": venue["id"], "eventId": event["id"],
            "eventDate": event["date"], "officialUrl": url,
            "officialVenueSourceUrl": homepage, "originalVenue": dict(venue),
            "venuePatch": patch, "publicationAllowed": False,
            "publisherAuthorityGranted": False}


def registered_venue_source(venue):
    """Select one existing identity-bound official source, never a fuzzy match."""
    try:
        rows = json.loads(official.SOURCES.read_text(encoding="utf-8"))["venues"]
        matches = {
            row["url"] for row in rows
            if isinstance(row, dict) and isinstance(row.get("url"), str)
            and official.official_origin(venue, row["url"]) == row["url"]
        }
    except (OSError, ValueError, TypeError, KeyError):
        return None
    return next(iter(matches)) if len(matches) == 1 else None


class _PracticalTitle(HTMLParser):
    """Retain only the document title, not arbitrary text or metadata."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.titles = []
    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True
            self.titles.append("")
    def handle_data(self, data):
        if self.in_title:
            self.titles[-1] += data
    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False


def _access_section_address(page, blocks, venue):
    """One venue-named document with a bounded explicit arrival section.

    Do not take addresses from the restaurant, ticket office or transport
    sections of a practical page. A generic heading alone is not identity.
    The caller still independently verifies the named physical BAN/OSM site.
    """
    title = _PracticalTitle()
    title.feed(page)
    title.close()
    if len(title.titles) != 1:
        return set()
    name = triage.words(venue.get("name"))
    parts = [triage.words(part) for part in re.split(
        r"\s+[–—|\-]\s+|\s*[:|]\s*", title.titles[0])]
    if not name or name not in parts:
        return set()
    labels = {"comment venir", "venir", "acces", "comment acceder",
              "venir a la salle", "getting here", "how to get here"}
    headings = [i for i, (tag, value) in enumerate(blocks)
                if tag in {"h1", "h2", "h3", "h4"}
                and triage.words(value) in labels]
    if not headings:
        return set()
    require(len(headings) == 1, "ambiguous practical arrival sections")
    nearby = []
    for tag, value in blocks[headings[0]+1:headings[0]+9]:
        if tag.startswith("h") or NONVENUE.search(triage.words(value)):
            break
        nearby.append(value)
    addresses = set()
    for i, value in enumerate(nearby):
        if not re.search(r"\b\d{5}\b", value):
            continue
        matches = {_postal_line(value, venue["city"])}
        if i:
            matches.add(_postal_line(nearby[i-1] + " " + value, venue["city"]))
        matches.discard(None)
        require(len(matches) == 1, "conflicting practical arrival address")
        addresses.update(matches)
    require(len(addresses) == 1, "one exact arrival address required")
    return addresses


def _standalone_practical_address(html, source, venue, fetch, cache):
    """Follow one actual visible same-origin practical link, never guess URLs."""
    links = PracticalLinks()
    links.feed(html)
    links.close()
    origin = urlsplit(source)
    candidates = set()
    for link in links.links:
        resolved = urljoin(source, link)
        target = urlsplit(resolved)
        if (target.scheme == "https" and target.netloc.casefold() == origin.netloc.casefold()
                and not target.username and not target.password
                and not target.query and not target.fragment
                and target.path.rstrip("/") != origin.path.rstrip("/")
                and intake.valid_https(resolved)):
            candidates.add(resolved)
    require(len(candidates) == 1, "one visible official practical link required")
    page = fetch(next(iter(candidates)), cache)
    require(isinstance(page, str) and 0 < len(page) <= probe.MAX_BYTES,
            "invalid practical page")
    addresses = set()
    try:
        footer = _named_footer_address(page, venue)
        addresses.add((footer["address"], footer["postalCode"]))
    except MissingVenueAddress:
        pass
    parser = AddressBlocks()
    parser.feed(page)
    parser.close()
    for i, (tag, text) in enumerate(parser.blocks):
        if tag not in {"h1", "h2", "h3", "h4"} or not _named_location(text, venue):
            continue
        nearby = []
        for kind, value in parser.blocks[i+1:i+6]:
            if kind.startswith("h") or NONVENUE.search(triage.words(value)):
                break
            nearby.append(value)
        for j, value in enumerate(nearby):
            # A split street/postcode may occupy two adjacent visible blocks.
            variants = [value]
            if j+1 < len(nearby):
                variants.append(value + " " + nearby[j+1])
            matches = {_postal_line(v, venue["city"]) for v in variants}
            matches.discard(None)
            if re.search(r"\b\d{5}\b", value) and not matches:
                # A preceding street line may be part of the exact address.
                prior = _postal_line(nearby[j-1] + " " + value, venue["city"]) if j else None
                require(prior is not None, "conflicting named practical postal address")
                matches.add(prior)
            addresses.update(matches)
    addresses.update(_access_section_address(page, parser.blocks, venue))
    require(len(addresses) == 1, "one exact named practical address required")
    street, postcode = next(iter(addresses))
    site = dict(venue, address=street, postalCode=postcode)
    require(address_source.eligible_address(site), "non-geocodable practical address")
    return site


def discovered_venue_sources(registry, venues, today):
    """Untrusted, exact name/city navigation hints; never source authority."""
    if (not isinstance(registry, dict) or registry.get("schema") != intake.REGISTRY_SCHEMA
            or not isinstance(registry.get("items"), dict)):
        return {}
    from open_world_site_research import safe_page
    from collections import defaultdict
    identities = defaultdict(list)
    for vid, venue in venues.items():
        identities[(intake.normalized(venue.get("name")),
                    intake.normalized(venue.get("city")))].append(vid)
    candidates = defaultdict(dict)
    for record in registry["items"].values():
        if not isinstance(record, dict) or record.get("status") != "pending_review":
            continue
        lead = record.get("candidate")
        if (not isinstance(lead, dict) or lead.get("publicationAllowed") is not False
                or lead.get("reviewRequired") is not True
                or not intake.official_claim(lead.get("source"))
                or lead.get("cancellationNotice") is True):
            continue
        try:
            day = dt.date.fromisoformat(lead.get("date"))
        except (ValueError, TypeError):
            continue
        if day < today:
            continue
        ids = identities.get((intake.normalized(lead.get("venue")),
                              intake.normalized(lead.get("city"))), [])
        if len(ids) != 1:
            continue
        url = safe_page(lead.get("eventDetailUrl") or lead.get("sourceUrl"))
        if not url or urlsplit(url).query:
            continue
        host = intake.valid_https(url).removeprefix("www.")
        previous = candidates[ids[0]].get(host)
        rank = (day.isoformat(), url)
        if previous is None or rank < previous:
            candidates[ids[0]][host] = rank
    # Competing domains are not silently chosen. New evidence can resolve
    # that ambiguity during a later cycle.
    return {vid: next(iter(hosts.values()))[1]
            for vid, hosts in candidates.items() if len(hosts) == 1}


def verify_venue_source(source, venue, *, fetch=probe.safe_fetch, cache=None):
    """Correct an existing coarse pin without needing a published concert.

    Require a registered origin or independent named OSM website attribution,
    one explicitly named physical address and a fresh BAN/OSM match.
    A generic contact address, a discovery hint alone or a city pin cannot qualify.
    """
    from open_world_site_research import safe_page
    require(isinstance(venue, dict) and eligible(venue)
            and isinstance(source, str) and safe_page(source) == source
            and not urlsplit(source).query,
            "unsafe venue source")
    registered = registered_venue_source(venue) == source
    cache = {} if cache is None else cache
    try:
        html = fetch(source, cache)
        require(isinstance(html, str) and 0 < len(html) <= probe.MAX_BYTES,
                "invalid venue page")
        try:
            site = _named_footer_address(html, venue)
        except MissingVenueAddress:
            site = _standalone_practical_address(html, source, venue, fetch, cache)
    except (ValueError, TypeError, KeyError, OSError, TimeoutError) as exc:
        raise EvidenceHeld("standalone_named_address_unconfirmed") from exc
    def bounded(endpoint, limit):
        body = fetch(endpoint, cache)
        require(isinstance(body, str) and 0 < len(body) <= min(limit, probe.MAX_BYTES),
                "independent geographical evidence unavailable")
        return body, endpoint
    try:
        if registered:
            feature, lat, lon, precision = geo.verify(
                site, bounded, official_website=source)
        else:
            # The private URL is only a hint. Independently match the exact
            # postal address and named OSM feature, then its HTTPS website.
            website, named_feature = address_source.website_from_address(
                site, fetch=fetch, cache=cache)
            actual, expected = intake.valid_https(source), intake.valid_https(website)
            require(bool(actual and expected)
                    and actual.removeprefix("www.") == expected.removeprefix("www."),
                    "discovered source not independently attributed")
            feature, lat, lon, precision = geo.verify(site, bounded)
            require(feature == named_feature, "named site identity changed")
    except (ValueError, TypeError, KeyError, OSError, TimeoutError) as exc:
        raise EvidenceHeld("standalone_independent_geo_unconfirmed") from exc
    require(precision in {"named-site-point", "named-site-area"},
            "no independent named physical site")
    return {"schema": SCHEMA, "venueId": venue["id"], "eventId": None,
            "eventDate": None, "officialUrl": source,
            "officialVenueSourceUrl": source, "originalVenue": dict(venue),
            "venuePatch": {"address": site["address"], "postalCode": site["postalCode"],
                           "latitude": lat, "longitude": lon, "geoSource": feature,
                           "geoPrecision": precision},
            "publicationAllowed": False, "publisherAuthorityGranted": False}


def _recent_keys(raw, active):
    """Keep only unique active IDs, oldest to newest; advisory scheduling."""
    if not isinstance(raw, list):
        return []
    seen = set()
    result = []
    for key in reversed(raw):
        if isinstance(key, str) and key in active and key not in seen:
            seen.add(key)
            result.append(key)
    return list(reversed(result))


def _review_history(prior, groups, today, standalone=()):
    if (not isinstance(prior, dict)
            or prior.get("schema") != SCHEMA + ".scan"
            or prior.get("publicationAllowed") is not False
            or prior.get("publisherAuthorityGranted") is not False):
        return [], {}
    try:
        if dt.date.fromisoformat(prior["asOf"]) > today:
            return [], {}
    except (KeyError, TypeError, ValueError):
        return [], {}
    active = {vid for vid, rows in groups.items() if rows} | set(standalone)
    venues = _recent_keys(prior.get("recentVenueIds"), active)
    saved = prior.get("recentEventIdsByVenue")
    events = {}
    if isinstance(saved, dict):
        for vid in active:
            keys = {row["id"] for row in groups[vid]}
            recent = _recent_keys(saved.get(vid), keys)
            if recent:
                events[vid] = recent
    return venues, events


def _least_recent(rotated, recent):
    rank = {key: i for i, key in enumerate(recent)}
    return sorted(rotated, key=lambda key: rank.get(key, -1))


def _touch(recent, key):
    if key in recent:
        recent.remove(key)
    recent.append(key)


def scan(catalogue, today, *, slot=0, limit=4, per_venue=2, verify_one=verify,
         prior=None, verify_standalone=verify_venue_source, registry=None):
    """Bounded private research. Rotate over all eligible venues and their events.

    A permanent hold at the first room cannot starve the remaining rooms.
    Never write approvals or the public catalogue; no network on accurate pins.
    """
    require(isinstance(today, dt.date) and not isinstance(today, dt.datetime)
            and type(slot) is int and 0 <= slot <= 2
            and type(limit) is int and 1 <= limit <= 4
            and type(per_venue) is int and 1 <= per_venue <= 2,
            "invalid bounded research budget")
    require(isinstance(catalogue, dict)
            and isinstance(catalogue.get("venues"), list)
            and isinstance(catalogue.get("events"), list),
            "invalid published catalogue")
    venues = {v["id"]: v for v in catalogue["venues"]
              if isinstance(v, dict) and isinstance(v.get("id"), str)}
    require(len(venues) == len(catalogue["venues"]), "duplicate or invalid venue ID")
    groups = {vid: [] for vid, v in venues.items() if eligible(v)}
    for event in catalogue["events"]:
        if (not isinstance(event, dict) or event.get("venueId") not in groups
                or event.get("status") != "confirmed"
                or event.get("sourceType") != "salle"
                or not intake.valid_https(event.get("officialUrl"))):
            continue
        try:
            day = dt.date.fromisoformat(event.get("date"))
        except (ValueError, TypeError):
            continue
        if day >= today:
            groups[event["venueId"]].append(event)
    hints = discovered_venue_sources(
        registry, {vid: venues[vid] for vid in groups if not groups[vid]}, today)
    standalone = {vid: source for vid, rows in groups.items() if not rows
                  if (source := registered_venue_source(venues[vid]) or hints.get(vid)) is not None}
    ordered = sorted((vid for vid in groups if groups[vid] or vid in standalone),
                     key=lambda vid: (-len(groups[vid]), vid))
    cycle = today.toordinal() * 3 + slot
    start = (cycle * limit) % len(ordered) if ordered else 0
    recent_venues, recent_events = _review_history(prior, groups, today, standalone)
    chosen = _least_recent(ordered[start:] + ordered[:start], recent_venues)[:limit]
    report = {"schema": SCHEMA + ".scan", "asOf": today.isoformat(),
              "eligibleVenues": len(groups),
              "venuesWithFutureOfficialEvents": sum(bool(rows) for rows in groups.values()),
              "venuesWithStandaloneSource": len(standalone), "standaloneSourcesExamined": 0,
              "venuesWithDiscoveredSourceHints": len(hints),
              "examinedVenues": len(chosen), "eventPagesExamined": 0,
              "proposals": [], "held": [], "reasonCounts": {},
              "publicationAllowed": False, "publisherAuthorityGranted": False}
    cache = {}
    reasons = Counter()
    for vid in chosen:
        _touch(recent_venues, vid)
        if vid in standalone:
            report["standaloneSourcesExamined"] += 1
            try:
                report["proposals"].append(verify_standalone(
                    standalone[vid], venues[vid], cache=cache))
            except (ValueError, TypeError, KeyError, OSError, TimeoutError) as exc:
                code = exc.code if isinstance(exc, EvidenceHeld) else "other_evidence_unconfirmed"
                reasons[code] += 1
                report["held"].append({"venueId": vid, "reason": "no_verified_address",
                                       "reasonCounts": {code: 1}})
            continue
        rows = sorted(groups[vid], key=lambda e: (e["date"], e["id"]))
        # Avoid retrying only the same event page for a room indefinitely.
        offset = cycle % len(rows)
        by_id = {row["id"]: row for row in rows}
        history = recent_events.setdefault(vid, [])
        rotated = [row["id"] for row in rows[offset:] + rows[:offset]]
        selected = [by_id[key] for key in _least_recent(rotated, history)[:per_venue]]
        venue_reasons = Counter()
        for event in selected:
            _touch(history, event["id"])
            report["eventPagesExamined"] += 1
            try:
                proof = verify_one(event, venues[vid], cache=cache)
            except (ValueError, TypeError, KeyError, OSError, TimeoutError) as exc:
                code = exc.code if isinstance(exc, EvidenceHeld) else "other_evidence_unconfirmed"
                reasons[code] += 1
                venue_reasons[code] += 1
                continue
            report["proposals"].append(proof)
            break
        else:
            report["held"].append({"venueId": vid, "reason": "no_verified_address",
                                   "reasonCounts": dict(sorted(venue_reasons.items()))})
    report["reasonCounts"] = dict(sorted(reasons.items()))
    report["recentVenueIds"] = recent_venues
    report["recentEventIdsByVenue"] = dict(sorted(recent_events.items()))
    return report
