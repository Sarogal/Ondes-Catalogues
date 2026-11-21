#!/usr/bin/env python3
"""Produce PRIVATE concert+site approval pairs from independent live evidence.

A cross-domain discovery report is never authority. For a new named physical
site this producer must freshly establish:
  * one first-party individual MusicEvent on a domain attributed by OSM/BAN
    to an already published independent announcing venue;
  * the ENTIRE named artist bill and per-event or per-artist genres;
  * one named physical French site on independently verified OSM geometry;
  * a second named event witness on a DIFFERENT registrable domain;
  * exact event/site binding accepted by the live Publisher contract.

The existing public venues are verified anchors, NOT a domain allowlist.
Each verified pair is passed to the unchanged private Publisher preflight.
This tool never writes approved.json, never changes the public catalogue and
never claims publication. Unproved and unknown sources remain in research.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# The legacy Concerts adapters import their peers as top-level modules.
# Keep the standalone CLI and ordinary tests using the same module paths.
SOURCE_DIR = ROOT / "automation" / "concerts"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))
from automation.concerts import discover
from automation.concerts import event_site_pair_recheck as pairs
from automation.concerts import independent_named_site_geo as named_geo
from automation.concerts import official_rss_jsonld_bridge as bridge
from automation.concerts import source_admission_intake as intake
from automation.concerts import source_cross_domain_corroboration as cross
from automation.concerts import source_cross_domain_live_recheck as witnesses
from automation.concerts import source_evidence_probe as probe
from automation.concerts import venue_osm_self_discovery as origin
from scripts import concert_dynamic_new_site_source as live
from scripts import concert_event_site_contract as contract

SCHEMA = "grossesondes.concert.dynamic-new-site-paired-proposals.v1"
MAX_CHECKS = 4  # network work per run; never an artist/venue/domain total
CHECKED_PROOF = ["artists", "date", "venue", "genre"]


def require(condition, why):
    if not condition:
        raise ValueError("New site approval producer: " + why)


def _event_row(html, url, date, lead, venue, city):
    """Select ONE individual Event by fresh identity before parsing its bill.

    A candidate's title, artist count or claimed genre is never authoritative.
    """
    from automation.concerts import event_site_microdata
    nodes = [n for n in discover.read_ld(html)
             if isinstance(n, dict) and
             bridge._event_types(n.get("@type")) & {"MusicEvent", "Event"}]
    if not nodes:
        nodes = event_site_microdata.read_microdata_events(html)
    eligible = []
    for event in nodes:
        if discover.reject_listing(event.get("name")):
            continue
        if event.get("url") not in (None, url):
            continue
        if discover.iso_day(event.get("startDate")) != date:
            continue
        place = event.get("location")
        if not isinstance(place, dict) or (
                intake.normalized(place.get("name")) != intake.normalized(venue)):
            continue
        address = place.get("address")
        if not isinstance(address, dict) or (
                intake.normalized(address.get("addressLocality"))
                != intake.normalized(city)):
            continue
        bill = bridge.official_named_bill(event.get("performer"))
        if bill is None or intake.normalized(lead) not in {
                intake.normalized(n) for n in bill[0]}:
            continue
        eligible.append(event)
    require(len(eligible) == 1, "ambiguous or absent named first-party MusicEvent")
    return eligible[0]


def _origin_site(url, catalogue, fetch, cache):
    """Attribution comes from independent OSM/BAN, not report host labels."""
    matching = []
    requested = live.domain(url)
    for venue in catalogue["venues"]:
        if not isinstance(venue, dict):
            continue
        # Published named OSM geometry is a growing open collection. An
        # unverified city-centre coordinate never creates source authority.
        geo = venue.get("geoSource", "")
        if not isinstance(geo, str) or "openstreetmap.org/" not in geo:
            continue
        try:
            homepage = origin.official_source(venue, fetch, cache)
            if isinstance(homepage, str) and live.domain(homepage) == requested:
                matching.append((venue, homepage))
        except (ValueError, TypeError, KeyError, IndexError, OSError,
                TimeoutError):
            continue
    require(len(matching) == 1, "first-party origin cannot be independently attributed")
    return matching[0]


def _independent_geo(location, fetch, cache):
    """Apply the same BAN/OSM location proof used by Publisher; no city pin."""
    def secure_get(url, size):
        require(type(size) is int and 0 < size <= 400_000,
                "oversized geographic evidence budget")
        body = fetch(url, cache)
        require(isinstance(body, str) and len(body) <= size,
                "independent named geography missing")
        return body, url
    if not location["region"]:
        point, location["region"] = named_geo.independently_attested_region(
            location, secure_get)
    else:
        point = None
    geo, lat, lon, precision = pairs.corroborate_physical_site(
        location, secure_get)
    if point is not None:
        require(named_geo._distance_meters(point[0], point[1], lat, lon)
                <= named_geo.MAX_DISTANCE_METERS,
                "named OSM site differs from exact government street address")
    location.update({
        "geoSource":geo, "latitude":lat, "longitude":lon,
        "geoPrecision":precision,
        "id":contract.site_id(location["name"],location["city"],geo),
    })


def source_proposal(row, catalogue, today, *, fetch=probe.safe_fetch):
    """Return two jointly verified, immutable proposed private approvals."""
    require(isinstance(row, dict)
            and row.get("crossDomainEventVerified") is True
            and row.get("sourceOwnershipVerified") is False
            and row.get("publisherAuthorityGranted") is False
            and row.get("publicationAllowed") is False
            and row.get("publishedAlreadyKnown") is False
            and row.get("markedPossibleDuplicate") is False,
            "discovery cannot authorize a site")
    try:
        date = dt.date.fromisoformat(row.get("date"))
    except (TypeError, ValueError):
        raise ValueError("New site approval producer: invalid concert date")
    require(date >= today and isinstance(row.get("leadArtist"), str)
            and bool(row["leadArtist"].strip())
            and isinstance(row.get("venue"), str)
            and bool(row["venue"].strip())
            and isinstance(row.get("city"), str)
            and bool(row["city"].strip()), "incomplete dated performer and location")
    verified = row.get("verifiedWitnesses")
    require(isinstance(verified, list) and len(verified) >= 2,
            "two independently fetched event sources required")
    urls = sorted({x["url"] for x in verified
                   if isinstance(x, dict) and
                   isinstance(x.get("url"), str) and
                   intake.valid_https(x["url"]) == x.get("host") and
                   urlsplit(x["url"]).path not in ("", "/")})
    require(len({live.domain(u) for u in urls}) >= 2,
            "independent named event witness domains missing")
    cache = {}
    official = None
    for url in urls:
        try:
            venue, home = _origin_site(url, catalogue, fetch, cache)
            require(intake.normalized(venue.get("name")) !=
                    intake.normalized(row["venue"]),
                    "announcing venue must differ from new event site")
            html = fetch(url, cache)
            require(isinstance(html, str) and 100 <= len(html) <= probe.MAX_BYTES,
                    "first party event body missing")
            item = _event_row(html, url, row["date"],
                              row["leadArtist"], row["venue"], row["city"])
            lead = {
                "date":row["date"], "name":item["name"],
                "leadArtist":row["leadArtist"], "venue":row["venue"],
                "city":row["city"],
            }
            _, names, _unnamed, genres, location = pairs._official_event(
                lead, html, url, today)
            official = (url, venue, home, names, genres, location)
            break
        except (ValueError, TypeError, KeyError, IndexError, OSError,
                TimeoutError):
            continue
    require(official is not None, "fresh independent first-party event missing")
    url, anchor, homepage, names, genres, location = official
    different = [u for u in urls if live.domain(u) != live.domain(url)]
    require(bool(different), "different-domain corroboration absent")
    witness = None
    for candidate in different:
        try:
            other = witnesses.event_page_witness(
                fetch(candidate, cache), url=candidate,
                date=row["date"], lead_artist=names[0],
                venue=location["name"], city=location["city"])
            require(intake.normalized(names[0]) in {
                intake.normalized(n) for n in other["names"]},
                "independent event does not confirm lead performer")
            witness = candidate
            break
        except (ValueError, TypeError, KeyError, IndexError, OSError,
                TimeoutError):
            continue
    require(witness is not None, "independent event corroboration failed")
    _independent_geo(location, fetch, cache)
    require(not any(
        intake.normalized(v.get("name")) ==
        intake.normalized(location["name"]) and
        intake.normalized(v.get("city")) ==
        intake.normalized(location["city"])
        for v in catalogue["venues"] if isinstance(v, dict)),
        "event site already exists; use existing-site route")
    ids, fresh = pairs._artists(names, catalogue)
    slug = pairs._name(location["city"]).replace(" ","-")
    artist_slug = pairs._name(names[0]).replace(" ","-")
    eid = ("go-c-" + row["date"].replace("-","") + "-" + slug[:70] +
           "-" + artist_slug[:68])
    require(contract.SLUG.fullmatch(eid) is not None
            and len(set(ids)) == len(ids),
            "event or artist identifier unstable")
    require(not any(
        e.get("id") == eid or e.get("officialUrl") == url or
        (e.get("date") == row["date"] and
         e.get("venueId") == location["id"] and
         bool(set(e.get("artistIds") or []) & set(ids)))
        for e in catalogue["events"] if isinstance(e, dict)),
        "concert already published or overlapping")
    checked = today.isoformat()
    event = {
        "reviewDecision":"approved",
        "reviewedBy":"independent-official-verifier",
        "reviewedAt":checked,
        "officialEvidence":[
            {"url":url,"proofType":"official-organizer-or-venue",
             "checkedAt":checked,"checkedFields":CHECKED_PROOF},
            {"url":url,"proofType":live.PROFILE,"checkedAt":checked,
             "checkedFields":list(live.CHECKED),
             "originVenueId":anchor["id"],
             "originVenueOsmUrl":anchor["geoSource"],
             "corroboratingEventUrl":witness,
             "officialArtistNames":names,"officialGenreLabels":genres},
        ],
        "event":{
            "id":eid,"title":" + ".join(names),"date":row["date"],"time":None,
            "artistIds":ids,"venueId":location["id"],"genres":genres,
            "status":"confirmed","officialUrl":url,
            "sourceType":"organisateur",
        },
        "newArtists":fresh,
    }
    vproof = {"url":url,"proofType":"official-event-location",
              "checkedAt":checked,
              "checkedFields":["eventId","date","venueName","city","country"],
              "eventId":eid,"venueName":location["name"],
              "city":location["city"],"country":"FR"}
    geo = {"url":location["geoSource"],
           "proofType":"independent-osm-site","checkedAt":checked,
           "checkedFields":["venueName","city","coordinates","country"],
           "venueName":location["name"],"city":location["city"],
           "country":"FR","latitude":location["latitude"],
           "longitude":location["longitude"],
           "geoPrecision":location["geoPrecision"]}
    site = {
        "reviewDecision":"approved",
        "reviewedBy":"independent-official-verifier",
        "reviewedAt":checked,
        "venueKind":contract.PROFILE,
        "locationKind":"named-physical-site",
        "venue":location,
        "eventBinding":{
            "eventId":eid,"eventDate":row["date"],
            "eventOfficialUrl":url,
            "authoritySourceUrl":homepage,
            "authorityArtistId":None},
        "officialEvidence":[vproof,geo],
    }
    # Same proof module as production Publisher. Its own network reads must
    # succeed before the proposed private pair can even reach preflight.
    contract.validate(
        site,today,[event],
        origin_venues={v["id"]:v for v in catalogue["venues"]},
        origin_artists={a["id"]:a for a in catalogue["artists"]},
        fetch=fetch)
    return event, site


def build(report, catalogue, before, today, *, slot=0, limit=MAX_CHECKS,
          fetch=probe.safe_fetch):
    require(isinstance(report, dict)
            and report.get("schema") == witnesses.SCHEMA
            and report.get("sourceOwnershipVerified") is False
            and report.get("publicationAllowed") is False
            and isinstance(report.get("checks"), list),
            "input must be private unsigned cross-domain report")
    require(isinstance(catalogue, dict)
            and catalogue.get("schemaVersion") == 1
            and all(isinstance(catalogue.get(k), list)
                    for k in ("events","artists","venues")),
            "published catalogue missing")
    require(isinstance(before, dict)
            and before.get("schema") == "grossesondes.concert.approvals.v1"
            and isinstance(before.get("approvals"), list)
            and isinstance(before.get("venueApprovals"), list),
            "private preliminary approval pair ledger missing")
    require(type(limit) is int and 1 <= limit <= 8
            and type(slot) is int and slot in (0,1,2)
            and isinstance(today, dt.date) and not isinstance(today, dt.datetime),
            "verification budget or date invalid")
    output=copy.deepcopy(before)
    working=copy.deepcopy(catalogue)
    pending=[r for r in report["checks"] if isinstance(r,dict)
             and r.get("crossDomainEventVerified") is True
             and r.get("publishedAlreadyKnown") is False
             and r.get("markedPossibleDuplicate") is False]
    # Review windows rotate, never a permanent shortlist by performer/place.
    pending.sort(key=lambda x:(str(x.get("date")),str(x.get("leadArtist")),
                               str(x.get("city"))))
    offset=((today-dt.date(2026,11,21)).days*3+slot)*limit
    sample=[pending[(offset+i)%len(pending)]
            for i in range(min(limit,len(pending)))] if pending else []
    used={e["event"]["id"] for e in output["approvals"]
          if isinstance(e,dict) and isinstance(e.get("event"),dict)
          and isinstance(e["event"].get("id"),str)}
    counts=Counter()
    for row in sample:
        try:
            event,site=source_proposal(row,working,today,fetch=fetch)
            eid=event["event"]["id"]
            require(eid not in used and not any(
                x.get("venue",{}).get("id")==site["venue"]["id"]
                for x in output["venueApprovals"]),
                "duplicate pending private pair")
            output["approvals"].append(event)
            output["venueApprovals"].append(site)
            used.add(eid)
            working["events"].append(event["event"])
            working["venues"].append(site["venue"])
            working["artists"].extend(
                {"id":a["id"],"name":a["name"],"aliases":[]}
                for a in event["newArtists"])
            counts["publisher_bound_pairs_proposed"]+=1
        except (ValueError,TypeError,KeyError,IndexError,OSError,TimeoutError):
            counts["held_missing_independent_evidence"]+=1
    return output,{
        "schema":SCHEMA,"asOf":today.isoformat(),"eligibleQueue":len(pending),
        "examined":len(sample),"stateCounts":dict(sorted(counts.items())),
        "privateApprovalApplied":False,"publicationAllowed":False,
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--cross",type=Path,required=True)
    p.add_argument("--catalogue",type=Path,required=True)
    p.add_argument("--candidate",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    p.add_argument("--scan-slot",type=int,choices=(0,1,2),default=0)
    args=p.parse_args()
    load=lambda path:json.loads(path.read_text(encoding="utf-8"))
    proposal,details=build(load(args.cross),load(args.catalogue),
                           load(args.candidate),
                           dt.datetime.now(ZoneInfo("Europe/Paris")).date(),
                           slot=args.scan_slot)
    args.output.write_text(json.dumps(proposal,ensure_ascii=False,indent=2)+"\n",
                           encoding="utf-8")
    args.report.write_text(json.dumps(details,ensure_ascii=False,indent=2)+"\n",
                           encoding="utf-8")
    print(json.dumps({
        "examined":details["examined"],
        "proposedPairs":details["stateCounts"].get(
            "publisher_bound_pairs_proposed",0),
        "privateApprovalApplied":False,
    }))


if __name__=="__main__":
    main()
