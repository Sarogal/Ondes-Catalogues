"""Private, resumable open-world research for permanent venues.

Uses exact OSM name/city queries and safe public HTTPS reads. All outputs
are research hints, never publication permission. The caller must persist
the returned cursor privately; no names, URLs or points go to public logs.
"""
from datetime import date
from hashlib import sha256
import json
import re
from collections import Counter
from time import monotonic

from ptitesondes_family_national_source_preflight import norm_text
from ptitesondes_generic_venue_osm_preflight import fetch_osm_query, MAX_ELEMENTS
from ptitesondes_unlisted_source_safe_recheck import read_unknown_https
from ptitesondes_delegated_source_authority import _url_host, _same_host
from ptitesondes_independent_venue_site_proof import _osm_website_host
from ptitesondes_open_world_permanent_place_evidence import corroborate_place

SCHEMA = "ptitesondes.private_open_world_place_research.v1"
DEFAULT_BATCH = 6
MAX_BATCH = 36
LIVE_BUDGET_SECONDS = 600
MAX_CONSECUTIVE_UNAVAILABLE = 3
MAX_RECORDS = 4000
SKIP = ("already_public", "unlikely_family_venue")


def _identity(row):
    city, venue = row.get("city"), row.get("venue")
    if any(not isinstance(s, str) or not 2 <= len(s) <= 180
           or any(ord(c) < 32 or ord(c) == 127 for c in s)
           for s in (city, venue)):
        raise ValueError("invalid_place_identity")
    key = [norm_text(city), norm_text(venue)]
    if not all(key):
        raise ValueError("invalid_place_identity")
    return sha256(json.dumps(key, ensure_ascii=False).encode()).hexdigest()


def named_query(city, venue):
    # JSON-quoted literals, not regex patterns or caller-supplied Overpass.
    _identity({"city": city, "venue": venue})
    name, town = (json.dumps(s, ensure_ascii=False) for s in (venue, city))
    return ('[out:json][timeout:20];nwr["name"=%s]["addr:city"=%s];'
            'out center tags %d;' % (name, town, MAX_ELEMENTS))


def _typographic_pattern(value):
    """Anchored, bounded regex derived solely from normalized ASCII tokens.

    The regex is a search expansion, never evidence or a fuzzy identity match.
    Accent classes and punctuation variants cover common French OSM names.
    """
    groups = {
        "a": "[aàâäáãå]", "c": "[cç]", "e": "[eéèêë]",
        "i": "[iîïíì]", "o": "[oôöóòõ]", "u": "[uùûüú]",
        "y": "[yÿý]", "n": "[nñ]",
    }
    value = norm_text(value)
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9 ]{2,180}", value):
        return None
    tokens = value.split()
    if not tokens:
        return None
    parts = ["".join(groups.get(c, c) for c in token) for token in tokens]
    pattern = "^" + "[[:space:][:punct:]’–—]+".join(parts) + "$"
    return pattern if len(pattern) <= 2000 else None


def typographic_query(city, venue):
    _identity({"city": city, "venue": venue})
    a, b = _typographic_pattern(venue), _typographic_pattern(city)
    if not a or not b:
        return None
    # JSON encoding provides the Overpass string escaping; no input-supplied
    # regex metacharacters are copied to the generated pattern.
    return ('[out:json][timeout:20];nwr["name"~%s,i]["addr:city"~%s,i];'
            'out center tags %d;' % (json.dumps(a, ensure_ascii=False),
                                    json.dumps(b, ensure_ascii=False), MAX_ELEMENTS))


def fetch_named(city, venue):
    # Use the normalized search as the primary query when supported so a
    # literal match cannot hide a second typographically equivalent object.
    query = typographic_query(city, venue) or named_query(city, venue)
    return fetch_osm_query(query, pathway="named",
                           unavailable="independent_place_map_unavailable")


def _inspect(row, osm_fetch, page_read):
    city, venue = row["city"], row["venue"]
    try:
        osm = osm_fetch(city, venue)
        if (not isinstance(osm, dict) or osm.get("remark")
                or not isinstance(osm.get("elements"), list)
                or len(osm["elements"]) >= MAX_ELEMENTS):
            return "map_response_incomplete", None
        matches = []
        for obj in osm["elements"]:
            if not isinstance(obj, dict) or not isinstance(obj.get("tags"), dict):
                continue
            t = obj["tags"]
            if norm_text(t.get("name")) == norm_text(venue):
                c = norm_text(t.get("addr:city"))
                if not c or c == norm_text(city):
                    matches.append(obj)
        if len(matches) != 1:
            return "map_identity_missing_or_ambiguous", None
        obj = matches[0]
        tags = obj["tags"]
        if (obj.get("type") != "node" or tags.get("amenity") not in
                ("library", "toy_library")
                or norm_text(tags.get("addr:city")) != norm_text(city)):
            return "map_feature_requires_other_proof", None
        postcode = tags.get("addr:postcode")
        if not isinstance(postcode, str) or not re.fullmatch(r"\d{5}", postcode):
            return "map_postcode_missing", None
        hinted = row.get("historical_address_unverified")
        if isinstance(hinted, dict) and hinted.get("postal_code") not in (None, postcode):
            return "postal_evidence_conflict", None
        websites = [tags[k] for k in ("website", "contact:website") if k in tags]
        hosts = [_osm_website_host(s) for s in websites]
        if not hosts or any(h is None or not _same_host(h, hosts[0]) for h in hosts):
            return "map_website_missing_or_conflicting", None
        # The OA/directory URL is only a research hint and must share the
        # independently mapped host. No follow of arbitrary links/redirects.
        urls = list(dict.fromkeys(s for s in
                    [*websites, row.get("possible_website_unverified")]
                    if isinstance(s, str) and _url_host(s)
                    and _same_host(_url_host(s), hosts[0])))
        if not urls:
            return "official_venue_page_missing", None
        for url in urls[:2]:
            try:
                html = page_read(url)
                proof = corroborate_place(city, venue, postcode, url, html, osm)
                if proof is not None:
                    return "independent_evidence_found", proof
            except (OSError, ValueError, TypeError, UnicodeError):
                continue
        return "official_page_unavailable_or_unmatched", None
    except (OSError, ValueError, TypeError, KeyError, OverflowError, UnicodeError):
        return "research_source_unavailable", None


def research(report, previous, today, *, limit=DEFAULT_BATCH,
             osm_fetch=fetch_named, page_read=read_unknown_https,
             time_budget=None, clock=monotonic, stop_on_outage=False):
    if (type(today) is not date or type(limit) is not int or not 1 <= limit <= MAX_BATCH
            or not isinstance(report, dict) or report.get("schema") !=
            "ptitesondes.place_review.v1" or not isinstance(report.get("records"), list)
            or len(report["records"]) > MAX_RECORDS):
        raise ValueError("invalid_place_research_input")
    if (time_budget is not None and
            (type(time_budget) is not int or not 1 <= time_budget <= LIVE_BUDGET_SECONDS)
            or not callable(clock) or type(stop_on_outage) is not bool):
        raise ValueError("invalid_place_research_budget")
    if previous is None:
        previous = {"schema": SCHEMA, "sequence": 0, "attempts": {}}
    if (not isinstance(previous, dict) or set(previous) != {"schema", "sequence", "attempts"}
            or previous["schema"] != SCHEMA or type(previous["sequence"]) is not int
            or previous["sequence"] < 0 or not isinstance(previous["attempts"], dict)
            or len(previous["attempts"]) > MAX_RECORDS
            or any(not re.fullmatch(r"[0-9a-f]{64}", k) or type(v) is not int
                   or not 1 <= v <= previous["sequence"]
                   for k, v in previous["attempts"].items())):
        raise ValueError("invalid_place_research_cursor")
    rows = {}
    seen = set()
    for row in report["records"]:
        if not isinstance(row, dict) or any(row.get(flag) is not False for flag in
                ("public_eligible", "gps_verified", "official_site_verified")):
            raise ValueError("invalid_private_place_permissions")
        key = _identity(row)
        if key in seen:
            raise ValueError("duplicate_place_identity")
        seen.add(key)
        if row.get("status") not in SKIP:
            rows[key] = row
    # Least recently attempted, including failures. No permanent blacklist.
    # Historical candidates are included even without an event UID.
    attempts = {k: v for k, v in previous["attempts"].items() if k in rows}
    selected = sorted(rows, key=lambda k: (attempts.get(k, 0), k))[:limit]
    seq = previous["sequence"]
    results = []
    started = clock() if time_budget is not None else None
    consecutive_unavailable = 0
    stop_reason = "batch_complete"
    for key in selected:
        if started is not None and clock() - started >= time_budget:
            stop_reason = "time_budget"
            break
        if stop_on_outage and consecutive_unavailable >= MAX_CONSECUTIVE_UNAVAILABLE:
            stop_reason = "provider_outage"
            break
        row = rows[key]
        status, proof = _inspect(row, osm_fetch, page_read)
        if status in ("research_source_unavailable", "map_response_incomplete"):
            consecutive_unavailable += 1
        else:
            consecutive_unavailable = 0
        seq += 1
        attempts[key] = seq
        results.append({"city": row["city"], "venue": row["venue"],
                        "status": status, "observed_at": today.isoformat(),
                        "evidence": proof, "public_eligible": False})
    state = {"schema": SCHEMA, "sequence": seq, "attempts": attempts}
    summary = {"eligible_for_research": len(rows), "examined": len(results),
               "unattempted": len(set(rows) - set(attempts)),
               "selected": len(selected), "stop_reason": stop_reason,
               "counts": dict(Counter(r["status"] for r in results)),
               "publication_ready": False, "public_writes": 0}
    return results, state, summary


STATE_SCHEMA = "ptitesondes.private_open_world_place_research_state.v1"


def cycle(report, previous, today, **kwargs):
    """Keep the latest private result for every still-known identity."""
    if previous is None:
        previous = {"schema": STATE_SCHEMA, "cursor": None, "records": []}
    if (not isinstance(previous, dict) or previous.get("schema") != STATE_SCHEMA
            or set(previous) != {"schema", "cursor", "records"}
            or not isinstance(previous["records"], list)
            or len(previous["records"]) > MAX_RECORDS):
        raise ValueError("invalid_place_research_state")
    saved = {}
    for row in previous["records"]:
        if (not isinstance(row, dict) or row.get("public_eligible") is not False
                or (row.get("evidence") is not None and
                    (not isinstance(row["evidence"], dict)
                     or row["evidence"].get("public_eligible") is not False))):
            raise ValueError("invalid_saved_place_research")
        key = _identity(row)
        if key in saved:
            raise ValueError("duplicate_saved_place_research")
        saved[key] = row
    results, cursor, summary = research(report, previous["cursor"], today, **kwargs)
    active = {_identity(row) for row in report["records"] if row.get("status") not in SKIP}
    saved = {k: v for k, v in saved.items() if k in active}
    for row in results:
        saved[_identity(row)] = row
    summary["stored_private_results"] = len(saved)
    return {"schema": STATE_SCHEMA, "cursor": cursor,
            "records": [saved[k] for k in sorted(saved)]}, summary


def main():
    import argparse
    from pathlib import Path
    from ptitesondes_national_backlog_bridge import _atomic_json, _read
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--qualification", type=Path, required=True)
    p.add_argument("--previous", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--date", type=date.fromisoformat, required=True)
    args = p.parse_args()
    report = _read(args.qualification, 4_000_000)
    previous = (_read(args.previous, 6_000_000)
                if args.previous.exists() or args.previous.is_symlink() else None)
    state, summary = cycle(report, previous, args.date, limit=MAX_BATCH,
                           time_budget=LIVE_BUDGET_SECONDS, stop_on_outage=True)
    _atomic_json(args.output, state)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
