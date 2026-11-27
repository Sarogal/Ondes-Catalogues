#!/usr/bin/env python3
"""Independent OpenAgenda concert + NEW named French site paired approvals.

A discovery row has no authority. Every initial proposal re-fetches the exact
OpenAgenda-owned UID-scoped export, validates agenda, event, date, complete
lineup, musical genre, scheduling and published physical address; then BAN
and named OSM geometry independently authenticate the venue. The production
Publisher repeats the entire chain. No second event domain or OSM website
ownership of OpenAgenda is required. No city centre or unlocated site passes.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.concerts import openagenda_official_concert as oa
from automation.concerts import dynamic_new_site_approval_proposals as geography
from automation.concerts import event_site_pair_recheck as pairs
from automation.concerts import source_admission_intake as intake
from automation.concerts import source_evidence_probe as probe
from automation.concerts.independent_named_site_geo import _distance_meters
from scripts import concert_dynamic_new_site_source as publisher_source
from scripts import concert_event_site_contract as site_contract

SCHEMA = "grossesondes.concert.openagenda-new-site-proposals.v1"
MAX_CHECKS = 4
REVIEW_BUCKETS = frozenset({"genre_tag_review", "genre_unknown"})


def require(ok, reason):
    if not ok:
        raise ValueError("OpenAgenda new-site: " + reason)


def _site_key(name, city):
    return intake.normalized(name), intake.normalized(city)


def eligible(registry, catalogue, today):
    require(isinstance(today, dt.date) and not isinstance(today, dt.datetime)
            and isinstance(registry, dict)
            and registry.get("schema") == intake.REGISTRY_SCHEMA
            and isinstance(registry.get("items"), dict)
            and isinstance(catalogue, dict)
            and catalogue.get("schemaVersion") == 1
            and all(isinstance(catalogue.get(k), list) for k in
                    ("venues", "events", "artists")),
            "untrusted candidate registry or catalogue")
    mapped = {_site_key(v.get("name"), v.get("city"))
              for v in catalogue["venues"] if isinstance(v, dict)}
    published = {(e.get("officialUrl"), e.get("date"))
                 for e in catalogue["events"] if isinstance(e, dict)}
    result = []
    for entry in registry["items"].values():
        if not isinstance(entry, dict):
            continue
        candidate = entry.get("candidate")
        if (not isinstance(candidate, dict)
                or entry.get("status") != "pending_review"
                or type(entry.get("stableObservations")) is not int
                or entry["stableObservations"] < 1
                or candidate.get("source") != "agenda_officiel_openagenda"
                or candidate.get("reviewBucket") not in REVIEW_BUCKETS
                or candidate.get("possibleExistingConcert") is not False
                or candidate.get("publicationAllowed") is not False
                or candidate.get("reviewRequired") is not True
                or not all(isinstance(candidate.get(x), str)
                           and candidate[x].strip() for x in (
                               "venue", "city", "date", "leadArtist"))):
            continue
        url = candidate.get("eventDetailUrl") or candidate.get("sourceUrl")
        if (not oa.is_openagenda_event_url(url)
                or candidate.get("sourcePage") != url
                or candidate.get("sourceUrl") != url
                or _site_key(candidate["venue"], candidate["city"]) in mapped):
            continue
        try:
            day = dt.date.fromisoformat(candidate["date"])
            oa.official_export_url(candidate.get("openAgendaUid"),
                                   candidate.get("openAgendaEventUid"))
        except (TypeError, ValueError):
            continue
        if day < today or (url, candidate["date"]) in published:
            continue
        result.append((candidate["date"], url, candidate))
    # A finite network budget is NOT a whitelist of unknown cities/venues.
    # Genuine genre signals precede unclassified source hints, both rotate.
    result.sort(key=lambda x: (
        x[2]["reviewBucket"] != "genre_tag_review", x[0], x[1]))
    return result


def _unpublished_location(record):
    """Build only address research hints; NO coordinates or approval here."""
    require(isinstance(record, dict) and isinstance(record.get("location"), dict),
            "original physical place absent")
    place = record["location"]
    name, city, zip_code, address = (place.get("name"), place.get("city"),
                                      place.get("postalCode"), place.get("address"))
    require(all(isinstance(x, str) and 2 <= len(x.strip()) <= 220
                for x in (name, city, zip_code, address))
            and re.fullmatch(r"[0-9]{5}", zip_code) is not None
            and str(place.get("countryCode") or "").lower() in {
                "fr", "gp", "mq", "gf", "re", "yt", "nc", "pf",
                "wf", "pm", "bl", "mf",
            },
            "incomplete French street, named place or postal address")
    # The OA address often appends ", 76000 Rouen, France"; keep ONLY the
    # named street. Exact BAN proof must independently confirm its number,
    # postal code and municipality later.
    street = address.split(",", 1)[0].strip()
    require(4 <= len(street) <= 180, "original physical street missing")
    dept = (zip_code[:3] if zip_code.startswith(("97", "98"))
            else zip_code[:2])
    if zip_code.startswith("20"):
        # Corse 2A/2B: the INSEE commune code, when given, disambiguates.
        insee = str(place.get("insee") or "").upper()
        dept = insee[:2] if insee.startswith(("2A", "2B")) else ""
    require(site_contract.DEPT.fullmatch(dept) is not None,
            "official location department not independently identifiable")
    return {
        "name": name.strip(), "city": city.strip(), "address": street,
        "postalCode": zip_code, "department": dept, "region": "",
    }


def propose(row, catalogue, today, *, fetch=probe.safe_fetch):
    date, url, candidate = row
    require(oa.is_openagenda_event_url(url)
            and candidate.get("sourceUrl") == url
            and candidate.get("date") == date,
            "original source or date changed")
    agenda_uid, event_uid = (candidate.get("openAgendaUid"),
                             candidate.get("openAgendaEventUid"))
    cache = {}
    raw = fetch(oa.official_export_url(agenda_uid, event_uid), cache)
    try:
        doc = json.loads(raw)
        records = doc.get("events")
        require(doc.get("total") == 1 and isinstance(records, list)
                and len(records) == 1 and isinstance(records[0], dict),
                "original export does not contain unique event")
        place = _unpublished_location(records[0])
    except (TypeError, ValueError, KeyError, IndexError) as exc:
        raise ValueError("OpenAgenda new-site: original event data malformed") from exc
    require(_site_key(place["name"], place["city"]) ==
            _site_key(candidate["venue"], candidate["city"]),
            "official place changed from discovered location")
    # A syndicated public agenda is only a discovery hint. Authenticate
    # the original UID pair, exact event slug and origin permalink from
    # the fresh export before signing or checking for published duplicates.
    url = oa.original_event_url_from_export(
        raw, url, agenda_uid=agenda_uid, event_uid=event_uid)
    names, genres = oa.verified_export(
        raw, url, date, place, agenda_uid=agenda_uid, event_uid=event_uid)
    require(oa.observed_bill_matches(candidate["leadArtist"], names),
            "observed headliner no longer on original bill")
    require(not any(_site_key(v.get("name"), v.get("city")) ==
                    _site_key(place["name"], place["city"])
                    for v in catalogue["venues"] if isinstance(v, dict)),
            "venue already published, use existing-site recheck")
    # BAN address score and unique OSM named site are independent of OA.
    # Missing OA GPS does not matter, but a contradictory one must fail.
    geography._independent_geo(place, fetch, cache)
    official = records[0]["location"]
    lat, lon = official.get("latitude"), official.get("longitude")
    if lat is not None or lon is not None:
        require(type(lat) in (float, int) and type(lon) in (float, int)
                and all(math.isfinite(x) for x in (lat, lon))
                and _distance_meters(lat, lon, place["latitude"],
                                     place["longitude"]) <= 125,
                "OA GPS differs from independently named OSM feature")
    ids, fresh = pairs._artists(names, catalogue)
    lead_slug = intake.normalized(names[0]).replace(" ", "-")[:68]
    city_slug = intake.normalized(place["city"]).replace(" ", "-")[:70]
    event_id = "go-c-" + date.replace("-", "") + "-" + city_slug + "-" + lead_slug
    require(site_contract.SLUG.fullmatch(event_id) is not None
            and len(set(ids)) == len(names)
            and not any(e.get("id") == event_id
                or (e.get("officialUrl") == url and e.get("date") == date)
                or (e.get("date") == date and
                    e.get("venueId") == place["id"] and
                    bool(set(e.get("artistIds") or []) & set(ids)))
                for e in catalogue["events"] if isinstance(e, dict)),
            "existing or overlapping concert")
    checked = today.isoformat()
    event = {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": checked,
        "officialEvidence": [
            {"url": url, "proofType": "official-organizer-or-venue",
             "checkedAt": checked,
             "checkedFields": ["artists", "date", "venue", "genre"]},
            {"url": url, "proofType": publisher_source.OPENAGENDA_NEW_PROFILE,
             "checkedAt": checked,
             "checkedFields": list(publisher_source.OPENAGENDA_NEW_CHECKED),
             "officialArtistNames": names, "officialGenreLabels": genres,
             "officialOpenAgendaUid": str(agenda_uid),
             "officialOpenAgendaEventUid": str(event_uid),
             "namedOsmUrl": place["geoSource"]},
        ],
        "event": {
            "id": event_id, "title": " + ".join(names), "date": date,
            "time": None, "artistIds": ids, "venueId": place["id"],
            "genres": genres, "status": "confirmed",
            "officialUrl": url, "sourceType": "organisateur",
        },
        "newArtists": fresh,
    }
    site_approval = {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": checked,
        "venueKind": site_contract.PROFILE,
        "locationKind": "named-physical-site",
        "venue": place,
        "eventBinding": {
            "eventId": event_id, "eventDate": date,
            "eventOfficialUrl": url, "authoritySourceUrl": url,
            "authorityArtistId": None,
        },
        "officialEvidence": [
            {"url": url, "proofType": "official-event-location",
             "checkedAt": checked,
             "checkedFields": ["eventId", "date", "venueName", "city", "country"],
             "eventId": event_id, "venueName": place["name"],
             "city": place["city"], "country": "FR"},
            {"url": place["geoSource"], "proofType": "independent-osm-site",
             "checkedAt": checked,
             "checkedFields": ["venueName", "city", "coordinates", "country"],
             "venueName": place["name"], "city": place["city"],
             "country": "FR", "latitude": place["latitude"],
             "longitude": place["longitude"],
             "geoPrecision": place["geoPrecision"]},
        ],
    }
    original_venues = {v["id"]: v for v in catalogue["venues"]}
    original_artists = {a["id"]: a for a in catalogue["artists"]}
    # Re-fetch independently at the proposal boundary; then REAL Publisher
    # performs another full replay on the private preflight and cloud sync.
    publisher_source.verify_openagenda(
        event, site_approval, original_venues, original_artists, today,
        fetch=fetch)
    site_contract.validate(
        site_approval, today, [event], origin_venues=original_venues,
        origin_artists=original_artists, fetch=fetch)
    return event, site_approval


def build(registry, catalogue, before, today, *, slot=0, limit=MAX_CHECKS,
          fetch=probe.safe_fetch):
    require(isinstance(before, dict) and
            before.get("schema") == "grossesondes.concert.approvals.v1"
            and isinstance(before.get("approvals"), list)
            and isinstance(before.get("venueApprovals"), list)
            and type(slot) is int and slot in (0, 1, 2)
            and type(limit) is int and 1 <= limit <= 6,
            "private approval ledger or bounded scan invalid")
    selected = eligible(registry, catalogue, today)
    # Prefer leads already carrying an event-scoped metal/punk hint: the
    # broad OpenAgenda index also contains many nonmusic "metal" matches.
    # At the normal four-check budget use 3 priority + 1 unknown. The
    # unknown pool still rotates on every scheduled slot, so unknown bands
    # are never permanently excluded. This is scheduling ONLY: neither pool
    # grants trust and Publisher independently verifies every original event.
    priority = [x for x in selected
                if x[2]["reviewBucket"] == "genre_tag_review"]
    unknown = [x for x in selected
               if x[2]["reviewBucket"] != "genre_tag_review"]
    tick = (today - dt.date(2026, 11, 22)).days * 3 + slot
    if limit == 1 and priority and unknown:
        priority_quota = 0 if tick % 4 == 3 else 1
    else:
        priority_quota = (limit if not unknown else
                          max(1, limit - max(1, limit // 4)))
    priority_count = min(len(priority), priority_quota)
    unknown_count = min(len(unknown), limit - priority_count)
    chosen = (
        [priority[(tick * max(1, priority_count) + i) % len(priority)]
         for i in range(priority_count)] if priority else []
    )
    if unknown:
        chosen.extend(unknown[(tick * max(1, unknown_count) + i) %
                              len(unknown)] for i in range(unknown_count))
    if len(chosen) < min(limit, len(selected)):
        remaining = [row for row in selected if row not in chosen]
        start = (tick * limit) % len(remaining) if remaining else 0
        chosen.extend(remaining[(start + i) % len(remaining)]
                      for i in range(min(limit - len(chosen), len(remaining))))
    output = copy.deepcopy(before)
    current = copy.deepcopy(catalogue)
    signed_ids = {a.get("event", {}).get("id") for a in before["approvals"]
                  if isinstance(a, dict)}
    signed_sites = {a.get("venue", {}).get("id") for a in before["venueApprovals"]
                    if isinstance(a, dict)}
    states, reasons, checks = Counter(), Counter(), []
    for row in chosen:
        check = {"candidateId": str(row[2].get("candidateId", ""))[:120],
                 "date": row[0]}
        try:
            event, site = propose(row, current, today, fetch=fetch)
            eid, vid = event["event"]["id"], site["venue"]["id"]
            require(eid not in signed_ids and vid not in signed_sites,
                    "concert or venue already approved privately")
            output["approvals"].append(event)
            output["venueApprovals"].append(site)
            signed_ids.add(eid)
            signed_sites.add(vid)
            current["events"].append(event["event"])
            current["venues"].append(site["venue"])
            current["artists"].extend({**a, "aliases": []}
                                      for a in event["newArtists"])
            check["state"] = "publisher_bound_openagenda_event_site_pair"
        except (ValueError, KeyError, IndexError, TypeError, OSError,
                TimeoutError) as exc:
            check["state"] = "held_original_or_named_site_unverified"
            message = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            check["reason"] = re.sub(
                r"https?://\S+", "[url]", " ".join(message.split()))[:180]
            reasons[check["reason"]] += 1
        states[check["state"]] += 1
        checks.append(check)
    return output, {
        "schema": SCHEMA, "asOf": today.isoformat(), "scanSlot": slot,
        "eligibleUnknownSites": len(selected), "examined": len(chosen),
        "stateCounts": dict(states), "rejectionReasons": dict(reasons),
        "candidateChecks": checks,
        "privateApprovalApplied": False, "publicationAllowed": False,
    }


def main():
    parser = argparse.ArgumentParser()
    for field in ("registry", "catalogue", "candidate", "output", "report"):
        parser.add_argument("--" + field, type=Path, required=True)
    parser.add_argument("--scan-slot", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--limit", type=int, default=MAX_CHECKS)
    args = parser.parse_args()
    today = dt.datetime.now(ZoneInfo("Europe/Paris")).date()
    output, report = build(
        json.loads(args.registry.read_text(encoding="utf-8")),
        json.loads(args.catalogue.read_text(encoding="utf-8")),
        json.loads(args.candidate.read_text(encoding="utf-8")),
        today, slot=args.scan_slot, limit=args.limit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print("OpenAgenda new sites: publisher-bound private evidence checked")


if __name__ == "__main__":
    main()
