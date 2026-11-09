#!/usr/bin/env python3
"""Second-pass recheck of family-venue session leads. NEVER a publication gate.

Inputs: private watcher output and public immutable catalogues.
Only re-reads *exact* allowlisted organizer pages; never accepts user-provided
URLs as permission. The report remains private and safe_to_publish=False.
An organizer's page alone is NOT independent evidence of a publishable event.
"""
import argparse
from datetime import date, datetime, timedelta
import json
import math
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from ptitesondes_place_agenda_curated import curated_leads
from ptitesondes_place_agenda_pace import detail_candidates, detail_url
from ptitesondes_place_agenda_watch import fetch, MAX_BYTES, SCHEMA, REPORT, norm

SCHEMA_PREFLIGHT = "ptitesondes.place_agenda_preflight.v1"
MAX_CANDIDATES = 24
HORIZON_DAYS = 183
PARIS = ZoneInfo("Europe/Paris")
EXACT_CURATED = {
    "montpellier-mille-formes-programme",
    "toulouse-pourquoi-pas-bebes-explorateurs",
}
PACE_SOURCE_ID = "pace-totems-official-agenda"


def meters(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    x = math.sin((lat2 - lat1) / 2) ** 2 + (
        math.cos(lat1) * math.cos(lat2)
        * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 6_371_000 * math.asin(min(1.0, math.sqrt(x)))


def require_inputs(report, registry, places, outings):
    if (not isinstance(report, dict)
            or report.get("schema") != REPORT
            or report.get("policy") != "no_automatic_publication"
            or not isinstance(report.get("event_candidates"), list)
            or len(report["event_candidates"]) > 250):
        raise ValueError("Rapport de découverte inconnu")
    if (not isinstance(registry, dict) or registry.get("schema") != SCHEMA
            or not isinstance(registry.get("sources"), list)):
        raise ValueError("Registre des sources non conforme")
    if (not isinstance(places, dict) or places.get("version") != 1
            or not isinstance(places.get("places"), list)):
        raise ValueError("Lieux publics non conformes")
    if (not isinstance(outings, dict) or outings.get("version") != 3
            or not isinstance(outings.get("events"), list)):
        raise ValueError("Sorties publiques non conformes")
    by_place = {p["id"]: p for p in places["places"]
                if isinstance(p, dict) and isinstance(p.get("id"), str)}
    if len(by_place) != len(places["places"]):
        raise ValueError("Identité des lieux ambigüe")
    for s in registry["sources"]:
        if (not isinstance(s, dict) or s.get("place_id") not in by_place
                or not isinstance(s.get("url"), str)):
            raise ValueError("Source non enregistrée")
    return by_place


def exact_source(lead, sources):
    """Only pre-reviewed extraction routes can be rechecked."""
    extraction = lead.get("extraction")
    url = lead.get("source_url")
    if not isinstance(url, str) or len(url) > 500:
        return None
    for source in sources:
        if source["place_id"] != lead["place_id"] or source["kind"] != "programme":
            continue
        if (extraction == "curated_official_schedule_v1"
                and source["id"] in EXACT_CURATED and url == source["url"]):
            return source
        if (extraction == "pace_official_event_detail_v1"
                and source["id"] == PACE_SOURCE_ID
                and detail_url(source["url"], url) == url):
            return source
    # Structured Event without a site-specific age and session verifier has
    # deliberately not been authorized for preflight by this component.
    return None


def valid_local_start(value, today):
    if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?[+-]\d{2}:\d{2}",
            value):
        return None
    try:
        stamp = datetime.fromisoformat(value)
        local = stamp.astimezone(PARIS)
        if (stamp.tzinfo is None or stamp.utcoffset() != local.utcoffset()
                or stamp.replace(tzinfo=None) != local.replace(tzinfo=None)):
            return None
        if not today <= local.date() <= today + timedelta(days=HORIZON_DAYS):
            return None
    except (ValueError, TypeError, OverflowError):
        return None
    return stamp


def already_listed(lead, place, published):
    """Conservative same-title/same-date duplication check, no fuzzy identity."""
    title, city = norm(lead["name"]), norm(place["city"])
    d = lead["start"][:10]
    for event in published["events"]:
        if not isinstance(event, dict) or norm(event.get("title")) != title:
            continue
        if norm(event.get("city")) != city:
            continue
        try:
            beginning = date.fromisoformat(event["date_start"])
            ending = date.fromisoformat(event.get("date_end") or event["date_start"])
            if not beginning <= date.fromisoformat(d) <= ending:
                continue
        except (ValueError, TypeError, KeyError):
            continue
        if isinstance(event.get("venue"), str) and (
                norm(event["venue"]) == norm(place["name"])
                or norm(place["name"]) in norm(event["venue"])):
            return True
        try:
            lat, lng = float(event["lat"]), float(event["lng"])
            if all(math.isfinite(v) for v in (lat, lng)):
                if meters((lat, lng), (place["lat"], place["lng"])) <= 65:
                    return True
        except (ValueError, TypeError, KeyError):
            pass
    return False


def review(report, registry, places, outings, today, getter=fetch):
    by_place = require_inputs(report, registry, places, outings)
    cache = {}
    rows = []
    unique = set()
    for lead in sorted(report["event_candidates"],
                       key=lambda item: str(item.get("start", "")) if isinstance(item, dict) else ""):
        info = {k: lead.get(k) for k in ("place_id", "name", "start", "source_url")}
        info["state"] = "deferred"
        if (not isinstance(lead, dict) or
                lead.get("status") != "requires_independent_session_proof"
                or not isinstance(lead.get("name"), str)
                or not 5 <= len(lead["name"].strip()) <= 180
                or lead.get("place_id") not in by_place
                or lead.get("end") is not None
                or valid_local_start(lead.get("start"), today) is None):
            info["reason"] = "invalid_candidate"
            rows.append(info)
            continue
        identity = (lead["place_id"], norm(lead["name"]), lead["start"],
                    lead.get("source_url"))
        if identity in unique:
            info["reason"] = "duplicate_candidate"
            rows.append(info)
            continue
        unique.add(identity)
        if already_listed(lead, by_place[lead["place_id"]], outings):
            info["reason"] = "already_in_public_catalogue"
            rows.append(info)
            continue
        source = exact_source(lead, registry["sources"])
        if source is None:
            info["reason"] = "not_on_preapproved_extraction_route"
            rows.append(info)
            continue
        if len(cache) >= MAX_CANDIDATES and lead["source_url"] not in cache:
            info["reason"] = "source_fetch_budget_exhausted"
            rows.append(info)
            continue
        url = lead["source_url"]
        if url not in cache:
            try:
                html = getter(url)
                if not isinstance(html, str) or len(html.encode("utf-8")) > MAX_BYTES:
                    raise ValueError("invalid_or_oversized")
                if lead["extraction"] == "curated_official_schedule_v1":
                    actual = curated_leads(source, html, today)
                else:
                    actual = detail_candidates(source, url, html, today)
                cache[url] = actual
            except (OSError, ValueError, TypeError, UnicodeError):
                cache[url] = None
        actual = cache[url]
        if actual is None:
            info["reason"] = "source_unavailable"
        elif any(all(item.get(k) == lead.get(k)
                     for k in ("place_id", "name", "start", "end", "source_url"))
                 for item in actual):
            # Source reconfirmed, but no independent second-source evidence,
            # category approval, cancellation check or public-authority patch.
            info["state"] = "source_reconfirmed_private_only"
            info["reason"] = "secondary_evidence_and_category_review_required"
        else:
            info["reason"] = "session_absent_or_changed_at_source"
        rows.append(info)
    counts = {}
    for row in rows:
        label = row["state"] + ":" + row["reason"]
        counts[label] = counts.get(label, 0) + 1
    return {
        "schema": SCHEMA_PREFLIGHT,
        "date": today.isoformat(),
        "safe_to_publish": False,
        "publish_authorized": False,
        "mode": "private_second_pass_only",
        "checked": len(rows),
        "source_pages_read": len(cache),
        "counts": dict(sorted(counts.items())),
        "records": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--places", type=Path, required=True)
    parser.add_argument("--outings", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    report = json.loads(args.input.read_text(encoding="utf-8"))
    registry = json.loads(args.sources.read_text(encoding="utf-8"))
    places = json.loads(args.places.read_text(encoding="utf-8"))
    outings = json.loads(args.outings.read_text(encoding="utf-8"))
    result = review(report, registry, places, outings, args.date)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "records"},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
