"""Independent official MusicEvent + named OSM point attestation for new event sites.

A discovery record NEVER grants trust. Only an enabled, code-reviewed artist or
promoter source, a freshly re-read individual first-party MusicEvent and a
separately fetched named OpenStreetMap feature can yield a paired private
proposal. The real publisher/preflight remains the final authority.

Initial geometry support: named OSM nodes. Ways/relations fail closed until
their independent geometry can be computed safely; NO city-centre fallback.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import concert_event_site_contract as contract

import discover
import independent_named_site_geo
import official_rss_jsonld_bridge as bridge
import triage

SOURCE_FILE = Path(__file__).with_name("artist-tour-sources.json")
OSM_NODE = re.compile(r"https://www[.]openstreetmap[.]org/node/([1-9][0-9]{0,18})/?")
HTTPS = re.compile(r"^https://")
SOURCES = frozenset({
    "artist_official_tour", "promoter_official_tour",
    "promoter_official_tour_detail",
})


def require(ok, reason):
    if not ok:
        raise ValueError("Event site verification: " + reason)


def source_for(lead, catalogue, source_file=SOURCE_FILE):
    """Resolve exact official authority independently of private lead claims."""
    require(isinstance(lead, dict)
            and lead.get("source") in SOURCES
            and lead.get("newVenueToReview") is True
            and lead.get("reviewBucket") in {"genre_tag_review", "genre_unknown"}
            and lead.get("publicationAllowed") is False
            and lead.get("reviewRequired") is True
            and lead.get("possibleExistingConcert") is not True,
            "untrusted candidate")
    sources = json.loads(Path(source_file).read_text(encoding="utf-8"))
    require(sources.get("schema") ==
            "grossesondes.concert.artist_tour_sources.v1", "unknown source registry")
    # On a promoter's individual detail page, sourceUrl points at the
    # *event*, while sourcePage points at the already-reviewed tour listing.
    # Do not confuse that normal discovery shape with a newly trusted host.
    individual_promoter_detail = (
        lead["source"] == "promoter_official_tour_detail")
    authority = (lead.get("sourcePage") if individual_promoter_detail
                 else lead.get("sourceUrl"))
    detail = lead.get("eventDetailUrl")
    artist_id = lead.get("artistId")
    matches = [s for s in sources.get("sources", [])
               if isinstance(s, dict) and s.get("enabled") is True
               and s.get("url") == authority
               and s.get("artistId") == artist_id
               and s.get("sourceRole") in {"artist_official", "promoter_official"}]
    require(len(matches) == 1, "unknown or ambiguous official authority")
    expected_role = ("artist_official" if lead["source"] == "artist_official_tour"
                     else "promoter_official")
    require(matches[0]["sourceRole"] == expected_role
            and lead.get("sourceRole") == expected_role,
            "source role mismatch")
    require(any(x.get("id") == artist_id for x in catalogue.get("artists", [])
                if isinstance(x, dict)), "unverified source artist")
    try:
        base, target = urlsplit(authority), urlsplit(detail)
        trusted_url = (
            base.scheme == target.scheme == "https"
            and base.hostname == target.hostname
            and base.username is None and target.username is None
            and base.password is None and target.password is None
            and base.port is None and target.port is None
            and not target.query and not target.fragment
            and bool(target.path.strip("/"))
        )
        if individual_promoter_detail:
            prefix = matches[0].get("detailPathPrefix")
            trusted_url = (trusted_url
                           and isinstance(prefix, str)
                           and prefix.startswith("/")
                           and len(prefix) >= 8
                           and target.path.startswith(prefix)
                           and lead.get("sourceUrl") == detail)
    except (TypeError, ValueError):
        trusted_url = False
    require(trusted_url, "event detail outside reviewed source scope")
    return matches[0]


def _name(value):
    return triage.words(value)


def _department(postal, address):
    # Standard mainland departments and overseas codes follow postal prefix.
    # Corsican postcodes are not a sufficient independent 2A/2B proof.
    if postal.startswith("20"):
        dept = str(address.get("department") or "").upper()
        require(dept in ("2A", "2B"), "Corsican department not verified")
        return dept
    if postal.startswith(("97", "98")):
        return postal[:3]
    return postal[:2]


def _read_osm_node(node_url, expected, fetch):
    hit = OSM_NODE.fullmatch(node_url or "")
    require(hit is not None, "named OSM node URL absent")
    number = int(hit[1])
    api_url = f"https://api.openstreetmap.org/api/0.6/node/{number}.json"
    data, final = fetch(api_url, 120_000)
    require(final == api_url and isinstance(data, str)
            and len(data) <= 120_000, "OSM object not independently fetched")
    object_ = json.loads(data)
    elements = object_.get("elements")
    require(isinstance(elements, list) and len(elements) == 1,
            "ambiguous OSM object")
    el = elements[0]
    tags = el.get("tags")
    require(el.get("type") == "node" and el.get("id") == number
            and el.get("visible") is not False and isinstance(tags, dict),
            "OSM object identity missing")
    # OSM is geography evidence only. It NEVER supplies the show or genre.
    require(_name(tags.get("name")) == _name(expected["name"])
            and _name(tags.get("addr:city")) == _name(expected["city"])
            and tags.get("addr:postcode") == expected["postalCode"]
            and tags.get("addr:country", "FR").upper() == "FR",
            "OSM site identity, city or postcode not confirmed")
    lat, lon = el.get("lat"), el.get("lon")
    require(type(lat) in (int, float) and type(lon) in (int, float),
            "OSM coordinates missing")
    return float(lat), float(lon)


def _official_event(lead, html, url, today):
    require(isinstance(html, str) and len(html) <= 1_000_000,
            "official page too large")
    # A legitimate concert can be described as schema.org/Event rather than
    # MusicEvent. Accept either only when the SAME individual first-party
    # event carries an explicit named bill, genre, date and precise location.
    # Reject ANY second Event/MusicEvent node: never borrow metadata from
    # another event, a tour listing or a recommendation carousel.
    nodes = [n for n in discover.read_ld(html) if isinstance(n, dict)
             and bridge._event_types(n.get("@type")) & {"MusicEvent", "Event"}]
    require(len(nodes) == 1,
            "one unambiguous individual official Event/MusicEvent required")
    raw = nodes[0]
    canonical = raw.get("url")
    require(canonical is None or canonical == url,
            "official event canonical URL mismatch")
    status = str(raw.get("eventStatus") or "").lower()
    require(not any(s in status for s in ("cancel", "postpon", "resched", "report")),
            "concert cancelled or postponed")
    day = discover.iso_day(raw.get("startDate"))
    require(day == lead.get("date") and dt.date.fromisoformat(day) >= today,
            "official event date mismatch or expired")
    require(_name(raw.get("name")) == _name(lead.get("name")),
            "official concert title changed")
    bill = bridge.official_named_bill(raw.get("performer"))
    require(bill is not None, "complete official named bill missing")
    names, unnamed = bill
    require(_name(lead.get("leadArtist")) in {_name(n) for n in names},
            "lead artist not on fresh official bill")
    genres = raw.get("genre")
    if isinstance(genres, str):
        genres = [genres]
    require(contract.relevant_genres(genres),
            "explicit relevant non-electronic event genre absent")
    location = raw.get("location")
    require(isinstance(location, dict)
            and isinstance(location.get("name"), str),
            "official named place missing")
    addr = location.get("address")
    require(isinstance(addr, dict), "official postal address missing")
    country = addr.get("addressCountry")
    if isinstance(country, dict):
        country = country.get("name") or country.get("@id")
    require(_name(country) in {"fr", "france", "republique francaise"},
            "official location outside France")
    postal = str(addr.get("postalCode") or "")
    require(re.fullmatch(r"[0-9]{5}", postal) is not None,
            "official postcode missing")
    venue = str(location["name"]).strip()
    city = str(addr.get("addressLocality") or "").strip()
    require(_name(venue) == _name(lead.get("venue"))
            and _name(city) == _name(lead.get("city")),
            "official place and municipality mismatch")
    street = str(addr.get("streetAddress") or "").strip()
    region = str(addr.get("addressRegion") or "").strip()
    require(len(street) >= 3 and len(region) >= 3,
            "official street address or region missing")
    # The producer may know the exact named site without linking OSM.
    # The IGN BAN + named OSM fallback is independent of that producer.
    links = location.get("sameAs") or location.get("url") or []
    if isinstance(links, str):
        links = [links]
    require(isinstance(links, list) and len(links) <= 8
            and all(isinstance(link, str) for link in links),
            "invalid official site links")
    require(not any("openstreetmap.org" in link
                    and OSM_NODE.fullmatch(link) is None
                    for link in links),
            "invalid official OSM site identity")
    osm_links = [link for link in links if OSM_NODE.fullmatch(link)]
    require(len(osm_links) <= 1, "ambiguous official OSM site identity")
    return raw, names, unnamed, genres, {
        "name": venue, "city": city, "address": street,
        "postalCode": postal, "department": _department(postal, addr),
        "region": region, "geoSource": osm_links[0] if osm_links else None,
    }


def _artists(names, catalogue):
    known = {}
    aliases = set()
    taken = set()
    for a in catalogue.get("artists", []):
        require(isinstance(a, dict) and a.get("id"), "invalid artist catalogue")
        taken.add(a["id"])
        known.setdefault(_name(a.get("name")), []).append(a["id"])
        aliases.update(_name(n) for n in a.get("aliases", [])
                       if isinstance(n, str))
    result, fresh = [], []
    for n in names:
        key = _name(n)
        matches = known.get(key, [])
        require(len(matches) <= 1 and (matches or key not in aliases),
                "ambiguous artist identity")
        ident = matches[0] if matches else key.replace(" ", "-")[:72].strip("-")
        require(len(ident) >= 3
                and (matches or ident not in taken)
                and ident not in result,
                "duplicate or ambiguous new artist")
        result.append(ident)
        if not matches:
            taken.add(ident)
            fresh.append({"id": ident, "name": n})
    return result, fresh


def verify(lead, catalogue, today, *, fetch, source_file=SOURCE_FILE):
    """Pair proposals are produced ONLY after two real independent fetches.

    fetch(url, max_bytes) must return (body, final_url). Production uses
    trusted robots-aware fetch below; tests inject only synthetic responses.
    """
    require(isinstance(today, dt.date) and not isinstance(today, dt.datetime),
            "review date invalid")
    authority = source_for(lead, catalogue, source_file)
    url = lead["eventDetailUrl"]
    html, final = fetch(url, 1_000_000)
    require(final == url, "official event URL redirected")
    raw, names, unnamed, genres, location = _official_event(
        lead, html, url, today)
    ids, fresh = _artists(names, catalogue)
    require(lead["artistId"] in ids, "authority artist missing from official bill")
    if location["geoSource"] is not None:
        lat, lon = _read_osm_node(location["geoSource"], location, fetch)
        precision = "named-site-point"
    else:
        # The official address locates the search only: never publish a BAN
        # coordinate or a street midpoint as the actual concert site.
        osm_url, lat, lon, precision = independent_named_site_geo.verify(
            location, fetch)
        location["geoSource"] = osm_url
    location.update({
        "latitude": lat, "longitude": lon,
        "geoPrecision": precision,
        "id": contract.site_id(location["name"], location["city"],
                               location["geoSource"]),
    })
    date = lead["date"]
    event_id = ("go-c-" + date.replace("-", "") + "-"
                + _name(location["city"]).replace(" ", "-") + "-"
                + _name(names[0]).replace(" ", "-")[:72])
    require(re.fullmatch(r"go-c-[a-z0-9-]{7,150}", event_id) is not None,
            "event ID invalid")
    require(all(not (e.get("officialUrl") == url
                     or e.get("id") == event_id
                     or (e.get("date") == date
                         and e.get("venueId") == location["id"]
                         and set(e.get("artistIds") or []).intersection(ids)))
                for e in catalogue.get("events", [])
                if isinstance(e, dict)), "event already published")
    today_str = today.isoformat()
    proof = {"url": url, "proofType": "official-organizer-or-venue",
             "checkedAt": today_str,
             "checkedFields": ["artists", "date", "venue", "genre"]}
    event = {"reviewDecision": "approved",
             "reviewedBy": "independent-official-verifier",
             "reviewedAt": today_str,
             "officialEvidence": [proof],
             "event": {
                 "id": event_id, "title": " + ".join(names),
                 "date": date, "time": None, "artistIds": ids,
                 "venueId": location["id"], "genres": genres,
                 "status": "confirmed", "officialUrl": url,
                 "sourceType": "organisateur"},
             "newArtists": fresh}
    p = {"url": url, "proofType": "official-event-location",
         "checkedAt": today_str,
         "checkedFields": ["eventId", "date", "venueName", "city", "country"],
         "eventId": event_id, "venueName": location["name"],
         "city": location["city"], "country": "FR"}
    g = {"url": location["geoSource"], "proofType": "independent-osm-site",
         "checkedAt": today_str,
         "checkedFields": ["venueName", "city", "coordinates", "country"],
         "venueName": location["name"], "city": location["city"],
         "country": "FR", "latitude": lat, "longitude": lon,
         "geoPrecision": precision}
    kind = "named-physical-site"
    site = {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": today_str,
        "venueKind": "independent-event-site-v1",
        "locationKind": kind,
        "venue": location,
        "eventBinding": {
            "eventId": event_id, "eventDate": date,
            "eventOfficialUrl": url,
            "authoritySourceUrl": authority["url"],
            "authorityArtistId": authority["artistId"],
        },
        "officialEvidence": [p, g],
    }
    # Run the actual publisher site contract before returning any proposal.
    contract.validate(site, today, [event])
    return event, site


def fetch_verified(url, max_bytes, cache):
    """Network access is checked for robots, HTTPS and exact final URL."""
    require(HTTPS.match(url) is not None
            and (url.startswith("https://api.openstreetmap.org/api/0.6/node/")
                 or bool(urlsplit(url).hostname)),
            "invalid fetch URL")
    require(discover.robots_allow(url, cache), "robots policy unavailable or denied")
    body, final = discover.download(url, timeout=12, cap=max_bytes)
    require(final == url, "remote redirect refused")
    return body, final
