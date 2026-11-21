#!/usr/bin/env python3
"""Independently propose atomic event+NEW venue from its OWN first-party website.

No artist/venue/domain/organizer registry is used as authority. A private
discovery candidate is ONLY a lead. The official individual Event proves the
dated bill and at least one artist's music genre. French government BAN and
one independently named OSM site + its website prove physical site ownership.
The full LIVE Publisher repeats these proofs before any private signature
or public catalogue insertion; reports never confer publication authority.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.concerts import dynamic_new_site_approval_proposals as geo_producer
from automation.concerts import event_site_pair_recheck as pairs
from automation.concerts import official_rss_jsonld_bridge as bridge
from automation.concerts import source_admission_intake as intake
from automation.concerts import source_evidence_probe as probe
from automation.concerts import venue_address_osm_source as address_osm
from scripts import concert_dynamic_new_site_source as live
from scripts import concert_event_site_contract as contract

SCHEMA = "grossesondes.concert.self-attributed-new-site-proposals.v1"
MAX_CHECKS = 4
REVIEW_BUCKETS = {"genre_tag_review", "genre_unknown"}


def require(condition, message):
    if not condition:
        raise ValueError("Independent new venue: " + message)


def _norm(text):
    return intake.normalized(text)


def _detail(candidate):
    url = candidate.get("eventDetailUrl") or candidate.get("sourceUrl")
    host = intake.valid_https(url)
    require(host and bridge.official_event_url(
        url, "https://" + host + "/") and
        urlsplit(url).path.strip("/") and
        not urlsplit(url).query and not urlsplit(url).fragment,
        "individual HTTPS official detail required")
    page = candidate.get("sourcePage") or candidate.get("sourceUrl")
    require(intake.valid_https(page) == host,
            "source observation and detail must be first party")
    return url


def eligible(registry, catalogue, today):
    require(isinstance(registry, dict)
            and registry.get("schema") == intake.REGISTRY_SCHEMA
            and isinstance(registry.get("items"), dict)
            and isinstance(catalogue, dict)
            and catalogue.get("schemaVersion") == 1
            and all(isinstance(catalogue.get(k), list)
                    for k in ("venues", "events", "artists"))
            and isinstance(today, dt.date)
            and not isinstance(today, dt.datetime),
            "invalid private candidate registry or public catalogue")
    known = {(_norm(v.get("name")), _norm(v.get("city")))
             for v in catalogue["venues"] if isinstance(v, dict)}
    published = {(e.get("officialUrl"), e.get("date"))
                 for e in catalogue["events"] if isinstance(e, dict)}
    rows = []
    for row in registry["items"].values():
        if not isinstance(row, dict):
            continue
        c = row.get("candidate")
        if (not isinstance(c, dict)
                or row.get("status") != "pending_review"
                or type(row.get("stableObservations")) is not int
                or row["stableObservations"] < 2
                or c.get("reviewBucket") not in REVIEW_BUCKETS
                or c.get("publicationAllowed") is not False
                or c.get("reviewRequired") is not True
                or c.get("possibleExistingConcert") is not False
                or not isinstance(c.get("venue"), str)
                or not isinstance(c.get("city"), str)
                or not isinstance(c.get("leadArtist"), str)
                or not c["leadArtist"].strip()
                or not isinstance(c.get("date"), str)
                or (_norm(c["venue"]), _norm(c["city"])) in known):
            continue
        try:
            date = dt.date.fromisoformat(c["date"])
            url = _detail(c)
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
        if date < today or (url, c["date"]) in published:
            continue
        rows.append((c["date"], url, c))
    # Daily rotation covers every unknown site; no source/domain/artist list.
    rows.sort(key=lambda x: (x[0], x[1]))
    return rows


def propose(row, catalogue, today, *, fetch=probe.safe_fetch):
    date, url, candidate = row
    require(url == _detail(candidate), "first-party event source changed")
    cache = {}
    try:
        html = fetch(url, cache)
    except (ValueError, OSError, TimeoutError) as ex:
        raise ValueError("official_event_fetch: " + str(ex)) from ex
    require(isinstance(html, str) and 100 <= len(html) <= probe.MAX_BYTES,
            "individual first-party event content unavailable")
    lead = candidate["leadArtist"].split(" + ")[0].strip()
    require(lead, "named first-party headliner absent")
    observation = {
        "date": date, "name": candidate["name"], "leadArtist": lead,
        "venue": candidate["venue"], "city": candidate["city"],
    }
    try:
        _raw, names, _unnamed, genres, site = pairs._official_event(
            observation, html, url, today)
    except (ValueError, TypeError, KeyError) as ex:
        raise ValueError("official_event_content: " + str(ex)) from ex
    require(contract.relevant_genres(genres),
            "no explicit metal/rock/punk evidence attached to the actual event")
    try:
        geo_producer._independent_geo(site, fetch, cache)
        homepage, independently_named = address_osm.website_from_address(
            site, fetch=fetch, cache=cache)
    except (ValueError, OSError, TimeoutError) as ex:
        raise ValueError("independent_named_site: " + str(ex)) from ex
    require(independently_named == site["geoSource"]
            and live.domain(homepage) == live.domain(url),
            "OSM named venue does not independently own event domain")
    require(not any(
        _norm(v.get("name")) == _norm(site["name"])
        and _norm(v.get("city")) == _norm(site["city"])
        for v in catalogue["venues"] if isinstance(v, dict)),
        "site already published; use the known-site path")

    ids, fresh = pairs._artists(names, catalogue)
    event_id = (
        "go-c-" + date.replace("-", "") + "-" +
        _norm(site["city"]).replace(" ", "-")[:72] + "-" +
        _norm(names[0]).replace(" ", "-")[:72])
    require(contract.SLUG.fullmatch(event_id) is not None
            and len(set(ids)) == len(ids)
            and not any(
                e.get("id") == event_id or
                (e.get("officialUrl") == url and e.get("date") == date) or
                (e.get("date") == date and
                 e.get("venueId") == site["id"] and
                 bool(set(e.get("artistIds") or []) & set(ids)))
                for e in catalogue["events"] if isinstance(e, dict)),
            "event identifier overlaps a published concert")
    checked = today.isoformat()
    event = {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": checked,
        "officialEvidence": [
            {"url": url, "proofType": "official-organizer-or-venue",
             "checkedAt": checked,
             "checkedFields": ["artists", "date", "venue", "genre"]},
            {"url": url, "proofType": live.SELF_PROFILE,
             "checkedAt": checked, "checkedFields": list(live.SELF_CHECKED),
             "officialArtistNames": names, "officialGenreLabels": genres,
             "namedOsmUrl": site["geoSource"],
             "officialSiteWebsite": homepage},
        ],
        "event": {
            "id": event_id, "title": " + ".join(names), "date": date,
            "time": None, "artistIds": ids, "venueId": site["id"],
            "genres": genres, "status": "confirmed", "officialUrl": url,
            "sourceType": "organisateur",
        },
        "newArtists": fresh,
    }
    site_proof = {
        "url": url, "proofType": "official-event-location",
        "checkedAt": checked,
        "checkedFields": ["eventId", "date", "venueName", "city", "country"],
        "eventId": event_id, "venueName": site["name"],
        "city": site["city"], "country": "FR",
    }
    geo_proof = {
        "url": site["geoSource"], "proofType": "independent-osm-site",
        "checkedAt": checked,
        "checkedFields": ["venueName", "city", "coordinates", "country"],
        "venueName": site["name"], "city": site["city"],
        "country": "FR", "latitude": site["latitude"],
        "longitude": site["longitude"], "geoPrecision": site["geoPrecision"],
    }
    site_approval = {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": checked, "venueKind": contract.PROFILE,
        "locationKind": "named-physical-site", "venue": site,
        "eventBinding": {
            "eventId": event_id, "eventDate": date, "eventOfficialUrl": url,
            "authoritySourceUrl": homepage, "authorityArtistId": None,
        },
        "officialEvidence": [site_proof, geo_proof],
    }
    # The same network verifier is called again by the real Publisher,
    # whose private preflight prevents publication of a mere producer claim.
    live.verify_self(
        event, site_approval,
        {v["id"]: v for v in catalogue["venues"]},
        {a["id"]: a for a in catalogue["artists"]},
        today, fetch=fetch)
    contract.validate(
        site_approval, today, [event],
        origin_venues={v["id"]: v for v in catalogue["venues"]},
        origin_artists={a["id"]: a for a in catalogue["artists"]},
        fetch=fetch)
    return event, site_approval


def build(registry, catalogue, before, today, *, slot=0,
          limit=MAX_CHECKS, fetch=probe.safe_fetch):
    require(isinstance(before, dict)
            and before.get("schema") == "grossesondes.concert.approvals.v1"
            and isinstance(before.get("approvals"), list)
            and isinstance(before.get("venueApprovals"), list)
            and type(slot) is int and slot in (0, 1, 2)
            and type(limit) is int and 1 <= limit <= 6,
            "private paired approval ledger or network budget invalid")
    available = eligible(registry, catalogue, today)
    start = ((today - dt.date(2026, 11, 21)).days * 3 + slot) * limit
    chosen = [available[(start + i) % len(available)]
              for i in range(min(len(available), limit))] if available else []
    output = copy.deepcopy(before)
    current = copy.deepcopy(catalogue)
    signed_ids = {x.get("event", {}).get("id")
                  for x in output["approvals"] if isinstance(x, dict)}
    signed_sites = {x.get("venue", {}).get("id")
                    for x in output["venueApprovals"] if isinstance(x, dict)}
    states, reasons, checks = Counter(), Counter(), []
    for day, url, candidate in chosen:
        name = str(candidate.get("candidateId", ""))[:120]
        row = {"candidateId": name, "date": day}
        try:
            event, site = propose((day, url, candidate), current, today, fetch=fetch)
            eid, sid = event["event"]["id"], site["venue"]["id"]
            require(eid not in signed_ids and sid not in signed_sites
                    and len(output["venueApprovals"]) -
                    len(before["venueApprovals"]) < 6,
                    "duplicate or excessive private new-site pair")
            output["approvals"].append(event)
            output["venueApprovals"].append(site)
            signed_ids.add(eid)
            signed_sites.add(sid)
            current["events"].append(event["event"])
            current["venues"].append(site["venue"])
            current["artists"].extend(
                {**a, "aliases": []} for a in event["newArtists"])
            row["state"] = "publisher_bound_event_site_pair"
            states[row["state"]] += 1
        except (ValueError, TypeError, KeyError, IndexError,
                OSError, TimeoutError) as ex:
            row["state"] = "held_source_or_site_unverified"
            # Do not expose untrusted URLs or personal data in diagnostics.
            reason = str(ex) if isinstance(ex, ValueError) else type(ex).__name__
            reason = re.sub(r"https?://\S+", "[url]", " ".join(reason.split()))[:180]
            row["reason"] = reason
            reasons[reason] += 1
            states[row["state"]] += 1
        checks.append(row)
    return output, {
        "schema": SCHEMA, "asOf": today.isoformat(), "scanSlot": slot,
        "eligibleUnknownSites": len(available), "examined": len(chosen),
        "stateCounts": dict(sorted(states.items())),
        "candidateChecks": checks,
        "rejectionReasons": dict(sorted(reasons.items())),
        "privateApprovalApplied": False,
        "publicationAllowed": False,
    }


def main():
    parser = argparse.ArgumentParser()
    for key in ("registry", "catalogue", "candidate", "output", "report"):
        parser.add_argument("--" + key, required=True, type=Path)
    parser.add_argument("--scan-slot", type=int, default=0, choices=(0, 1, 2))
    parser.add_argument("--limit", type=int, default=MAX_CHECKS)
    args = parser.parse_args()
    today = dt.datetime.now(ZoneInfo("Europe/Paris")).date()
    proposed, report = build(
        json.loads(args.registry.read_text(encoding="utf-8")),
        json.loads(args.catalogue.read_text(encoding="utf-8")),
        json.loads(args.candidate.read_text(encoding="utf-8")),
        today, slot=args.scan_slot, limit=args.limit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(
        proposed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(json.dumps(
        report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Unknown site official concert: independent private pair review completed")


if __name__ == "__main__":
    main()
