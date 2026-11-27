"""Independent Publisher-side recheck of open-world place research.

Read-only preview: private identities are leads, not attestations. Re-read
OSM, the independently authenticated municipality and the exact venue page.
No public catalogue mutations and no candidate identifiers in public logs.
"""
import argparse
import base64
from collections import Counter
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

from private_intake import github, PATH, BRANCH
from ptitesondes_dila_municipal_domains import fetch_dila, approved_municipal_page_host
from ptitesondes_open_world_permanent_place_research import (
    STATE_SCHEMA, _identity, fetch_named, _inspect,
)
from ptitesondes_unlisted_source_safe_recheck import read_unknown_https

from ptitesondes_open_world_permanent_place_draft import build_draft, fetch_admin
from ptitesondes_open_world_permanent_place_ban import (
    discover_official_ban, discover_independent_cultural_ban, build_ban_draft,
)
from ptitesondes_generic_venue_ign_corroboration import fetch_ign

MAX_BYTES = 900000
MAX_RECHECK = 6


def read_private(token):
    if not token:
        raise ValueError("missing_private_place_token")
    name = PATH + "/lieux-open-world-research.json"
    try:
        obj = github(quote(name, safe="/") + "?ref=" + quote(BRANCH, safe=""), token)
    except HTTPError as e:
        if e.code == 404:
            return None
        raise
    if obj.get("encoding") != "base64" or obj.get("path") != name:
        raise ValueError("invalid_private_place_file")
    raw = base64.b64decode("".join(obj["content"].split()), validate=True)
    if not 0 < len(raw) <= MAX_BYTES or obj.get("size") != len(raw):
        raise ValueError("invalid_private_place_size")
    sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if sha != obj.get("sha"):
        raise ValueError("invalid_private_place_blob")
    return json.loads(raw)


def review_drafts(private, today, *, osm_fetch=fetch_named, page_read=read_unknown_https,
           directory_fetch=fetch_dila, admin_fetch=fetch_admin, ban_fetch=fetch_ign,
           cultural_lookup=None):
    counts = Counter()
    drafts = []
    summary = {"private_candidates": 0, "rechecked": 0,
               "independently_corroborated": 0, "complete_draft_records": 0, "counts": {},
               "publication_ready": False, "public_writes": 0}
    if private is None:
        summary["counts"] = {"private_research_not_yet_available": 1}
        return drafts, summary
    if (type(today) is not date or not isinstance(private, dict)
            or private.get("schema") != STATE_SCHEMA
            or not isinstance(private.get("records"), list)
            or len(private["records"]) > 4000):
        raise ValueError("invalid_private_place_research")
    candidates = []
    seen = set()
    for row in private["records"]:
        if not isinstance(row, dict) or row.get("public_eligible") is not False:
            raise ValueError("invalid_private_place_permissions")
        key = _identity(row)
        if key in seen:
            raise ValueError("duplicate_private_place")
        seen.add(key)
        if row.get("status") != "independent_evidence_found":
            continue
        evidence = row.get("evidence")
        if not isinstance(evidence, dict) or evidence.get("public_eligible") is not False:
            raise ValueError("invalid_private_place_evidence")
        # Deliberately ignore private GPS, postal code, URL and OSM object.
        # The only consumed lead is the exact city/name pair.
        lead = {"city": row["city"], "venue": row["venue"]}
        # The BAN route consumes an untrusted page hint only, never its
        # saved coordinates, address, municipality code or activities.
        if evidence.get("method") == "dila_official_place_address_plus_ban":
            lead["ban_route"] = True
            lead["possible_website_unverified"] = evidence.get("official_url")
        if evidence.get("method") == "culture_directory_official_place_address_plus_ban":
            lead["cultural_ban_route"] = True
        candidates.append((key, lead))
    summary["private_candidates"] = len(candidates)
    candidates.sort(key=lambda pair: pair[0])
    if candidates:
        start = (today.toordinal() * MAX_RECHECK) % len(candidates)
        candidates = (candidates[start:] + candidates[:start])[:MAX_RECHECK]
    cache = {}
    for _, lead in candidates:
        summary["rechecked"] += 1
        city = lead["city"]
        try:
            if lead.get("cultural_ban_route"):
                fresh = discover_independent_cultural_ban(
                    lead, cultural_lookup=cultural_lookup, page_read=page_read,
                    ban_fetch=ban_fetch, admin_fetch=admin_fetch)
                if fresh is None:
                    counts["fresh_cultural_ban_evidence_unavailable"] += 1
                    continue
                summary["independently_corroborated"] += 1
                counts["fresh_cultural_ban_place_evidence"] += 1
                draft = build_ban_draft(fresh, today)
                if draft is not None:
                    drafts.append(draft)
                    summary["complete_draft_records"] += 1
                else:
                    counts["draft_facts_not_complete"] += 1
                continue
            if city not in cache:
                cache[city] = directory_fetch(city)
            directory = cache[city]
            if lead.get("ban_route"):
                fresh = discover_official_ban(lead, directory_fetch=lambda _: directory,
                    page_read=page_read, ban_fetch=ban_fetch, admin_fetch=admin_fetch)
                if fresh is None:
                    counts["fresh_ban_evidence_unavailable"] += 1
                    continue
                summary["independently_corroborated"] += 1
                counts["fresh_ban_place_evidence"] += 1
                draft = build_ban_draft(fresh, today)
                if draft is not None:
                    drafts.append(draft)
                    summary["complete_draft_records"] += 1
                else:
                    counts["draft_facts_not_complete"] += 1
                continue
            pages = {}
            maps = []
            def mapped(city, venue):
                value = osm_fetch(city, venue)
                maps.append(value)
                return value
            def official_read(url):
                if not approved_municipal_page_host(url, city, directory):
                    raise ValueError("municipal_authority_not_confirmed")
                pages[url] = page_read(url)
                return pages[url]
            status, proof = _inspect(lead, mapped, official_read)
            if proof is not None:
                counts["fresh_municipal_place_evidence"] += 1
                summary["independently_corroborated"] += 1
                try:
                    admin = admin_fetch(proof["lat"], proof["lng"])
                    draft = build_draft(city, lead["venue"], proof["postal_code"],
                                        proof["official_url"], pages[proof["official_url"]],
                                        maps[0], admin, today)
                    if draft is not None:
                        drafts.append(draft)
                        summary["complete_draft_records"] += 1
                    else:
                        counts["draft_facts_not_complete"] += 1
                except (ValueError, OSError, TypeError, KeyError, UnicodeError):
                    counts["draft_admin_unavailable"] += 1
            else:
                counts[status] += 1
        except (ValueError, OSError, TypeError, KeyError, UnicodeError):
            counts["independent_source_unavailable"] += 1
    summary["counts"] = dict(counts)
    return drafts, summary


def review(private, today, **kwargs):
    """Public-log-safe diagnostic API; never returns candidate details."""
    return review_drafts(private, today, **kwargs)[1]


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    today = datetime.now(ZoneInfo("Europe/Paris")).date()
    try:
        summary = review(read_private(os.getenv("PRIVATE_INTAKE_READ_TOKEN")), today)
    except (ValueError, OSError, TypeError, KeyError, UnicodeError):
        summary = {"counts": {"private_recheck_unavailable": 1},
                   "publication_ready": False, "public_writes": 0}
    print(json.dumps(summary, sort_keys=True))
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("### Lieux inconnus : contre-preuve indépendante (lecture seule)\n")
            for key in ("private_candidates", "rechecked", "independently_corroborated", "complete_draft_records"):
                f.write(f"- {key}: {summary.get(key, 0)}\n")
            for key, n in sorted(summary["counts"].items()):
                f.write(f"- {key}: {n}\n")


if __name__ == "__main__":
    main()
