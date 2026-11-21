#!/usr/bin/env python3
"""Discover NEW concert leads from official venue websites found via named OSM.

No venue/organizer/artist/domain manifest is used to decide which origins exist.
The published map's NAMED OSM point is an untrusted hint: fetch that point
through DNS-pinned HTTPS, check exact name/place/geography and read its website.
Only same-domain first-party pages are browsed (strict robots, no redirects);
an individually structured future MusicEvent generates a QUARANTINED candidate.
This scanner cannot admit authority, sign an approval or publish a concert.

Network budget rotates through ALL eligible map venues and through detail links.
Unverified new locations, tickets, aliases and festivals stay held/referred.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "automation/concerts"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))
import discover
import official_rss_jsonld_bridge as bridge
import source_admission_intake as intake
import source_evidence_probe as probe
import triage
from independent_named_site_geo import _distance_meters

SCHEMA = "grossesondes.concert.discovery.v1"
# OSM node identities already appear in several canonical provenance formats.
# None is a trust grant: the independent OSM API must confirm site+location.
OSM_NODE = re.compile(r"https://www[.]openstreetmap[.]org/node/([1-9][0-9]*)\Z")
OSM_API_NODE = re.compile(r"https://www[.]openstreetmap[.]org/api/0[.]6/node/([1-9][0-9]*)\Z")
MAPCARTA_NODE = re.compile(r"https://mapcarta[.]com/(?:fr/)?N([1-9][0-9]*)\Z")
TEXT_OSM_NODE = re.compile(r"\b(?:OpenStreetMap\s+)?node\s+([1-9][0-9]*)\b",re.I)


def osm_node_id(venue):
    values=set()
    for value in (venue.get("geoSource"),venue.get("geoPrecision")):
        if not isinstance(value,str):
            continue
        for pattern in (OSM_NODE, OSM_API_NODE, MAPCARTA_NODE):
            m=pattern.fullmatch(value.strip())
            if m:
                values.add(m.group(1))
        for m in TEXT_OSM_NODE.finditer(value):
            values.add(m.group(1))
    return next(iter(values)) if len(values)==1 else None
TERRITORY_DISTANCE_METERS = 125
MAX_VENUES = 5
MAX_DETAILS = 3


def require(ok, reason):
    if not ok:
        raise ValueError("Unlisted OSM venue discovery: " + reason)


def eligible(catalogue):
    require(isinstance(catalogue, dict)
            and catalogue.get("schemaVersion") == 1
            and isinstance(catalogue.get("events"), list)
            and isinstance(catalogue.get("venues"), list),
            "invalid published reference")
    return sorted([
        v for v in catalogue["venues"]
        if isinstance(v, dict) and isinstance(v.get("id"), str)
        and isinstance(v.get("geoSource"), str)
        and osm_node_id(v) is not None
        and isinstance(v.get("name"), str)
        and isinstance(v.get("city"), str)
        and isinstance(v.get("postalCode"), str)
        and re.fullmatch(r"\d{5}", v["postalCode"])
        and type(v.get("latitude")) in (int,float)
        and type(v.get("longitude")) in (int,float)
    ], key=lambda v: v["id"])


def select(venues, day, slot, limit):
    require(isinstance(day, dt.date) and not isinstance(day, dt.datetime)
            and type(slot) is int and slot in (0,1,2)
            and type(limit) is int and 1 <= limit <= 10,
            "invalid source network budget")
    if not venues:
        return []
    # Rotate by slot and day; never permanently process only first N sites.
    offset = ((day.toordinal() * 3 + slot) * limit) % len(venues)
    return [venues[(offset+n) % len(venues)]
            for n in range(min(limit, len(venues)))]


def official_source(venue, fetch, cache):
    """OSM website is not authority alone; output is only an exploration seed."""
    node_id=osm_node_id(venue)
    require(bool(node_id),"not an unambiguous named OSM node")
    url="https://api.openstreetmap.org/api/0.6/node/"+node_id
    body = fetch(url, cache)
    require(isinstance(body, str) and 0 < len(body) <= probe.MAX_BYTES
            and "<!DOCTYPE" not in body.upper()
            and "<!ENTITY" not in body.upper(),
            "invalid independent OSM XML")
    root = ElementTree.fromstring(body)
    require(root.tag == "osm", "wrong OSM XML")
    nodes = root.findall("node")
    require(len(nodes) == 1 and nodes[0].get("id") == node_id,
            "OSM node identity changed")
    node = nodes[0]
    tags = {t.get("k"):t.get("v") for t in node.findall("tag")
            if t.get("k") and t.get("v")}
    require(triage.words(tags.get("name")) == triage.words(venue["name"]),
            "OSM does not independently name this room")
    if tags.get("addr:city"):
        require(triage.words(tags["addr:city"]) == triage.words(venue["city"]),
                "OSM city differs")
    if tags.get("addr:postcode"):
        require(tags["addr:postcode"] == venue["postalCode"],
                "OSM postcode differs")
    require(tags.get("addr:country", "FR").upper() == "FR",
            "foreign OSM venue")
    try:
        lat,lon=float(node.get("lat")),float(node.get("lon"))
        require(_distance_meters(lat,lon,venue["latitude"],venue["longitude"])
                <= TERRITORY_DISTANCE_METERS,"OSM site moved")
    except (TypeError,ValueError,OverflowError):
        raise ValueError("Unlisted OSM venue discovery: bad coordinates")
    websites = [tags[k] for k in ("website","contact:website")
                if isinstance(tags.get(k),str) and tags[k].strip()]
    require(bool(websites), "no website explicitly attributed to this OSM site")
    origins = {intake.valid_https(url) for url in websites}
    require(len(origins)==1 and None not in origins,
            "multiple or unsafe websites; identity requires review")
    source_url = websites[0]
    require(urlsplit(source_url).scheme == "https",
            "website must be HTTPS")
    return source_url


def detail_links(home, source_url, day, slot, limit):
    require(isinstance(home,str) and len(home)<=probe.MAX_BYTES,
            "unreadable official page")
    links = []
    for extractor in (discover.linked_first_party_event_urls,
                      discover.linked_first_party_dated_card_urls):
        links.extend(extractor(home, source_url, day))
    # Fallback to ordinary anchors as exploratory navigation, NOT event proof.
    # A real event may use any path convention, including /band-name/.
    parser = discover.EventHtml()
    parser.feed(home)
    for href in parser.links[:250]:
        if not isinstance(href,str):
            continue
        link = urljoin(source_url, href)
        if intake.valid_https(link) == intake.valid_https(source_url):
            links.append(link)
    unique = list(dict.fromkeys(
        link.split("#")[0] for link in links
        if isinstance(link,str)
        and intake.valid_https(link.split("#")[0]) ==
            intake.valid_https(source_url)
        and urlsplit(link).path not in ("","/")
        and link.split("#")[0] != source_url
    ))
    # Relevant-looking paths get probe priority, never a mandatory allowlist.
    indexed = list(enumerate(unique))
    indexed.sort(key=lambda x: (
        not bool(re.search(r"(concert|event|evenement|agenda|programm|spectacle|tour|live|\b20\d{2}\b)",
                           urlsplit(x[1]).path,re.I)),
        x[0]))
    ordered = [url for _,url in indexed]
    if not ordered:
        return []
    offset = ((day.toordinal()*3+slot)*limit)%len(ordered)
    return [ordered[(offset+i)%len(ordered)]
            for i in range(min(limit,len(ordered)))]


def event_leads(html, url, source, catalogue, today):
    """Only individual first-party MusicEvent nodes; no extracted-page join."""
    rows=[]
    for raw in discover.read_ld(html):
        if not isinstance(raw,dict) or "MusicEvent" not in bridge._event_types(
                raw.get("@type")):
            continue
        event_url=raw.get("url")
        if event_url is not None and event_url!=url:
            continue
        bill=bridge.official_named_bill(raw.get("performer"))
        if not bill:
            continue
        day=discover.iso_day(raw.get("startDate"))
        if not day or day<today.isoformat() or discover.reject_listing(raw.get("name")):
            continue
        source["url"]=source["url"].split("#")[0]
        cand=discover.venue_candidate(raw,source,url,
                discover.make_known_keys(catalogue),today.isoformat())
        if not cand:
            continue
        genres,scope=bridge.event_genres_from_own_bill(raw)
        if genres:
            cand["classification"]=genres
            cand["genreEvidenceScope"]=scope
        cand.update({
            "source":"agenda_officiel_structuré",
            "sourcePage":url,
            "eventDetailUrl":url,
            "officialDetailFound":True,
            # A source venue may announce an event at a new physical place.
            # NEVER bind that event to the announcing venue's public ID.
            "venueCatalogueId":(
                None if cand.get("venueOutsideSource") else source["id"]),
            "newlyDiscoveredFirstPartySource":True,
            "sourceAuthorityVerified":False,
            "publicationAllowed":False,
            "reviewRequired":True,
        })
        rows.append(cand)
    return rows


def scan(catalogue,today,*,slot=0,max_venues=MAX_VENUES,
         max_details=MAX_DETAILS,fetch=probe.safe_fetch):
    require(1<=max_details<=4,"invalid detail budget")
    candidates={}
    diagnostics=Counter()
    venues=eligible(catalogue)
    for venue in select(venues,today,slot,max_venues):
        cache={}
        diagnostics["roomsConsidered"]+=1
        try:
            homepage=official_source(venue,fetch,cache)
            diagnostics["namedOsmWebsitesVerified"]+=1
            text=fetch(homepage,cache)
            require(isinstance(text,str),"official homepage missing")
            pending=detail_links(text,homepage,today,slot,max_details)
            diagnostics["individualDetailsQueued"]+=len(pending)
            source={
                "id":venue["id"],"name":venue["name"],
                "city":venue["city"],"department":venue["department"],
                "url":homepage,
            }
            visited={homepage}
            read=0
            # A homepage often links to an agenda which THEN links to
            # individual event detail pages. Explore these two steps on the
            # same independently attributed HTTPS origin, never more than
            # max_details fetched pages in total per venue per cycle.
            while pending and read < max_details:
                link=pending.pop(0)
                if link in visited:
                    continue
                visited.add(link)
                read+=1
                try:
                    detail=fetch(link,cache)
                    leads=event_leads(detail,link,dict(source),catalogue,today)
                    for row in leads:
                        # Do not use a finite artist or room directory. A
                        # stable ID is a candidate identity, never authority.
                        candidates[row["candidateId"]]=row
                    diagnostics["detailPagesRead"]+=1
                    if not leads:
                        extra=detail_links(detail,link,today,slot,max_details)
                        unseen=[next_url for next_url in extra
                                if next_url not in visited
                                and next_url not in pending
                                and intake.valid_https(next_url) ==
                                    intake.valid_https(homepage)]
                        # Prefer event cards discovered on a currently opened
                        # agenda over another menu from the homepage.
                        pending=unseen+pending
                        diagnostics["individualDetailsQueued"]+=len(unseen)
                except (ValueError,TypeError,KeyError,OSError,TimeoutError):
                    diagnostics["detailPagesHeld"]+=1
        except (ValueError,TypeError,KeyError,OSError,TimeoutError,
                ElementTree.ParseError):
            diagnostics["sourcesHeld"]+=1
    classified,shortlist,counts=triage.classify(candidates.values(),catalogue)
    return {
        "schema":SCHEMA,
        "generatedAt":dt.datetime.now(dt.timezone.utc).isoformat(),
        "publicationAllowed":False,
        "automaticPublication":False,
        "scanSlot":slot,
        "eligiblePhysicalVenues":len(venues),
        "sourceChecks":dict(diagnostics),
        "triageCounts":counts,
        "shortlistReviewCount":len(shortlist),
        "candidates":classified,
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--catalogue",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--scan-slot",type=int,choices=(0,1,2),default=0)
    p.add_argument("--max-venues",type=int,default=MAX_VENUES)
    args=p.parse_args()
    report=scan(json.loads(args.catalogue.read_text(encoding="utf-8")),
                dt.datetime.now(ZoneInfo("Europe/Paris")).date(),
                slot=args.scan_slot,max_venues=args.max_venues)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",
                           encoding="utf-8")
    print("Named-OSM unknown-source reconnaissance complete. "
          "Candidate proposals quarantined; publication forbidden.")


if __name__=="__main__":
    main()
