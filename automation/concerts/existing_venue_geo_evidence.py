"""Read-only generic evidence for correcting existing municipal-centroid pins.

A published concert supplies an identity anchor, not new publishing authority.
Read its individual official MusicEvent/ Event address, verify the exact French
postal address and independently named OSM object, and bind the event origin
to the known official source or an independently attributed OSM website.
This never edits the catalogue or produces a signed approval.
"""
from __future__ import annotations

import datetime as dt
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
                if tag in {"h2", "h3", "h4"} and triage.words(text) in STOP),
               len(detail))
    detail = detail[:cut]
    day = next((visible._date_in(text) for _, text in detail[:20]
                if visible._date_in(text)), None)
    require(day == event["date"], "visible event date differs")
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
    require(len(addresses) == 1, "one explicit visible named-venue address required")
    street, postcode = next(iter(addresses))
    site = dict(venue, address=street, postalCode=postcode)
    require(address_source.eligible_address(site), "non-geocodable visible address")
    return site


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
    require(len(nodes) == 1, "single structured event required")
    node = nodes[0]
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
    require(isinstance(street, str) and 6 <= len(street.strip()) <= 160
            and isinstance(postcode, str) and re.fullmatch(r"\d{5}", postcode)
            and triage.words(address.get("addressLocality")) == triage.words(venue.get("city"))
            and bool(triage.words(venue.get("city"))), "exact postal identity missing")
    country = address.get("addressCountry")
    require(isinstance(country, str) and country.casefold() in {"fr", "fra", "france"},
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
    site = extract_address(fetch(url, cache), event, venue)

    def bounded(endpoint, limit):
        body = fetch(endpoint, cache)
        require(isinstance(body, str) and 0 < len(body) <= min(limit, probe.MAX_BYTES),
                "independent geographical evidence unavailable")
        return body, endpoint

    feature, lat, lon, precision = geo.verify(site, bounded)
    require(precision in {"named-site-point", "named-site-area"},
            "no independent named physical site")
    # The existing source manifest is only one provenance route. Unlisted
    # venues may use the independently matched OSM website, without a PR.
    homepage = official.official_origin(venue, url)
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


def scan(catalogue, today, *, slot=0, limit=4, per_venue=2, verify_one=verify):
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
    ordered = sorted((vid for vid in groups if groups[vid]),
                     key=lambda vid: (-len(groups[vid]), vid))
    cycle = today.toordinal() * 3 + slot
    start = (cycle * limit) % len(ordered) if ordered else 0
    chosen = (ordered[start:] + ordered[:start])[:limit]
    report = {"schema": SCHEMA + ".scan", "asOf": today.isoformat(),
              "eligibleVenues": len(groups), "venuesWithFutureOfficialEvents": len(ordered),
              "examinedVenues": len(chosen), "eventPagesExamined": 0,
              "proposals": [], "held": [],
              "publicationAllowed": False, "publisherAuthorityGranted": False}
    cache = {}
    for vid in chosen:
        rows = sorted(groups[vid], key=lambda e: (e["date"], e["id"]))
        # Avoid retrying only the same event page for a room indefinitely.
        offset = cycle % len(rows)
        selected = (rows[offset:] + rows[:offset])[:per_venue]
        for event in selected:
            report["eventPagesExamined"] += 1
            try:
                proof = verify_one(event, venues[vid], cache=cache)
            except (ValueError, TypeError, KeyError, OSError, TimeoutError):
                continue
            report["proposals"].append(proof)
            break
        else:
            report["held"].append({"venueId": vid, "reason": "no_verified_address"})
    return report
