"""National discovery of entirely unregistered festivals through a fixed directory.

Festival names/years come from an untrusted private national discovery queue,
but NEVER authorize network access to their supplied URLs. Only a fixed public
directory host, with a bounded path derived from a sanitized title, is read
first. A unique visible directory link nominates an HTTPS organizer domain;
a safe DNS-pinned fresh fetch independently confirms current-year music genre
and exact dates. Two consecutive civil days create only a PRIVATE proposal.
The public publisher independently repeats both fetches before admission.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from dns_pinned_https import fetch_public_html
from national_generic_primary_domain_preflight import (
    _edition_name, _published, QUEUE_SCHEMA,
)
from grossesondes_generic_directory_edition import (
    directory_url, directory_urls, discover_directory_website,
    verify_primary, private_proposal, validate_private_proposal,
)
from grossesondes_institutional_edition import conflicts_with_signed_catalogue
from grossesondes_archived_html_intake import latest_patch, atomic_json

SCHEMA = "grossesondes.national-directory-first-party-private.v1"
STATE_KEY = "national_directory_first_party_observations_private"
MAX_CHECKS = 3
MAX_DOSSIERS = 200
MAX_SOURCES = 12


def eligible(queue, catalog, today):
    checked = date.fromisoformat(today)
    if (not isinstance(queue, dict) or queue.get("schema") != QUEUE_SCHEMA
            or queue.get("as_of") != today
            or queue.get("review_only") is not True
            or queue.get("safe_to_publish") is not False
            or queue.get("publication_authorized") is not False
            or not isinstance(queue.get("dossiers"), list)
            or len(queue["dossiers"]) > MAX_DOSSIERS
            or not isinstance(catalog, dict)
            or catalog.get("schema") != 1
            or not isinstance(catalog.get("festivals"), list)):
        raise ValueError("Invalid discovery queue or signed reference")
    selected = []
    seen_ids = set()
    for row in queue["dossiers"]:
        if (not isinstance(row, dict)
                or row.get("review_only") is False
                or row.get("publication_authorized") is not False
                or row.get("safe_to_publish") is not False
                or not isinstance(row.get("id"), str)
                or not row["id"].startswith("national-")
                or not 10 <= len(row["id"]) <= 130
                or row["id"] in seen_ids
                or not isinstance(row.get("sources"), list)
                or not 1 <= len(row["sources"]) <= MAX_SOURCES
                or any(not isinstance(s, dict) or
                       s.get("publication_authorized") is not False
                       for s in row["sources"])):
            continue
        seen_ids.add(row["id"])
        year = row.get("edition_year_hint")
        title = _edition_name(row.get("name_hint"), year)
        if (title is None or not checked.year <= year <= checked.year+3
                or directory_url(title) is None
                or _published(catalog, title, year)):
            continue
        # NO queue URLs, source paths, or arbitrary hostnames are propagated.
        selected.append({
            "dossier_id": row["id"], "title": title, "year": year,
            "directory_url": directory_url(title),
        })
    return sorted(selected, key=lambda x: (x["dossier_id"], x["title"]))


def proof_digest(source, website, dates, directory_ref=None):
    route = directory_ref or source["directory_url"]
    if route not in directory_urls(source["title"]):
        raise ValueError("Untrusted directory URL")
    return sha256(json.dumps({
        "id": source["dossier_id"],
        "title": source["title"],
        "year": source["year"],
        "site": website,
        "dates": list(dates),
        "directory": route,
    }, sort_keys=True).encode("utf-8")).hexdigest()


def examine(state, queue, catalog, today, directory_fetch=None,
            organizer_fetch=None, limit=MAX_CHECKS):
    current = date.fromisoformat(today)
    if (not isinstance(state, dict)
            or state.get("schema") != "grossesondes.source-watch.v1"
            or type(limit) is not int or not 0 <= limit <= MAX_CHECKS):
        raise ValueError("Unsafe national directory state")
    rows = eligible(queue, catalog, today)
    observed = state.setdefault(STATE_KEY, {})
    if not isinstance(observed, dict) or len(observed) > MAX_DOSSIERS:
        raise ValueError("Unsafe national directory proof memory")
    active = {x["dossier_id"] for x in rows}
    for key in list(observed):
        if key not in active:
            del observed[key]
    yesterday = (current - timedelta(days=1)).isoformat()
    def record(source):
        old = observed.get(source["dossier_id"])
        return old if isinstance(old, dict) else {}
    pending = [x for x in rows
               if record(x).get("lastSeen") == yesterday
               and isinstance(record(x).get("digest"), str)]
    other = [x for x in rows if x not in pending]
    fresh = [x for x in other if record(x).get("lastChecked") != today]
    repeated = [x for x in other if x not in fresh]
    def rotate(pool):
        if not pool:
            return pool
        offset = (current.toordinal() // 2 * MAX_CHECKS) % len(pool)
        return pool[offset:] + pool[:offset]
    selected = (pending + rotate(fresh) + rotate(repeated))[:limit]
    read_directory = directory_fetch or fetch_public_html
    read_organizer = organizer_fetch or fetch_public_html
    results = []
    for source in selected:
        key = source["dossier_id"]
        old = observed.pop(key, None)
        result = {
            "dossier_id": key, "status": "DIRECTORY_OR_SITE_UNVERIFIED",
            "review_only": True, "safe_to_publish": False,
            "publication_authorized": False, "publisher_gate_connected": False,
            "two_day_observation": False, "site_review_only": None,
            "directory_ref_review_only": None,
            "start_date_hint": None, "end_date_hint": None,
        }
        try:
            # A wrong compact slug is not evidence against a new festival:
            # the directory also uses hyphen-separated URLs. Only TWO URLs,
            # both derived from the edition NAME, may be contacted.
            directory_ref, site = discover_directory_website(
                source["title"], read_directory)
            if site is None:
                result["status"] = "DIRECTORY_OFFICIAL_LINK_UNPROVEN"
            else:
                # The website is re-derived from the directory on THIS run;
                # private links and OpenAgenda URLs never authorize a fetch.
                primary = read_organizer(site)
                dates = verify_primary(
                    primary, source["title"], source["year"], today)
                if dates is None:
                    result["status"] = "OFFICIAL_CURRENT_EDITION_NOT_PROVEN"
                else:
                    digest = proof_digest(source, site, dates, directory_ref)
                    continuous = bool(
                        isinstance(old, dict)
                        and old.get("digest") == digest
                        and old.get("lastSeen") in (yesterday, today)
                        and isinstance(old.get("firstSeen"), str)
                        and old["firstSeen"] < today
                        and (old["lastSeen"] == yesterday
                             or old.get("stable") is True))
                    # Only consecutive civil-day fresh observations validate.
                    observed[key] = {
                        "digest": digest,
                        "firstSeen": (
                            old["firstSeen"] if continuous else today),
                        "lastSeen": today, "lastChecked": today,
                        "directoryRef": directory_ref,
                        "stable": continuous,
                    }
                    result.update(
                        status=("TWO_DAY_DIRECTORY_FIRST_PARTY_PRIVATE"
                                if continuous else
                                "FIRST_DAY_DIRECTORY_FIRST_PARTY_PRIVATE"),
                        two_day_observation=continuous,
                        site_review_only=site,
                        directory_ref_review_only=directory_ref,
                        start_date_hint=dates[0], end_date_hint=dates[1])
        except (OSError, TypeError, ValueError, UnicodeError, KeyError):
            result["status"] = "DIRECTORY_OR_OFFICIAL_HTTPS_UNAVAILABLE"
        if key not in observed:
            # Negative status never preserves a previous positive digest.
            observed[key] = {"lastChecked": today}
        results.append(result)
    return {
        "schema": SCHEMA, "as_of": today,
        "review_only": True, "safe_to_publish": False,
        "publication_authorized": False, "publications": 0,
        "eligible_count": len(rows), "checked_count": len(results),
        "two_day_count": sum(r["two_day_observation"] for r in results),
        "rows": results,
    }


def stable_private_proposals(state, queue, catalog, report, today):
    if (not isinstance(report, dict) or report.get("schema") != SCHEMA
            or report.get("as_of") != today
            or report.get("review_only") is not True
            or report.get("safe_to_publish") is not False
            or report.get("publication_authorized") is not False
            or report.get("publications") != 0
            or not isinstance(report.get("rows"), list)
            or len(report["rows"]) > MAX_CHECKS):
        raise ValueError("Untrusted national directory report")
    candidates = {row["dossier_id"]: row
                  for row in eligible(queue, catalog, today)}
    records = state.get(STATE_KEY, {})
    if not isinstance(records, dict):
        raise ValueError("Missing trusted observation memory")
    approved = []
    seen = set()
    for row in report["rows"]:
        if (not isinstance(row, dict)
                or row.get("two_day_observation") is not True
                or row.get("status") != "TWO_DAY_DIRECTORY_FIRST_PARTY_PRIVATE"
                or row.get("publication_authorized") is not False):
            continue
        source = candidates.get(row.get("dossier_id"))
        if source is None or source["dossier_id"] in seen:
            continue
        site = row.get("site_review_only")
        directory_ref = row.get("directory_ref_review_only")
        if directory_ref not in directory_urls(source["title"]):
            continue
        dates = row.get("start_date_hint"), row.get("end_date_hint")
        record = records.get(source["dossier_id"])
        if (not isinstance(record, dict)
                or record.get("stable") is not True
                or record.get("lastSeen") != today
                or record.get("directoryRef") != directory_ref
                or record.get("digest") != proof_digest(
                    source, site, dates, directory_ref)):
            continue
        try:
            if not date.fromisoformat(record["firstSeen"]) < date.fromisoformat(today):
                continue
        except (KeyError, TypeError, ValueError):
            continue
        proposal = private_proposal(
            source["title"], site, dates, today,
            directory_ref=directory_ref)
        if (proposal is None or
                validate_private_proposal(proposal, today) is None):
            continue
        seen.add(source["dossier_id"])
        approved.append(proposal)
    return approved


def append_private_proposals(folder, catalog, history, state, queue,
                             report, today):
    if (not isinstance(history, dict) or history.get("schema") != 2
            or not isinstance(history.get("knownFestivals"), list)):
        raise ValueError("Invalid historical reference")
    proposals = stable_private_proposals(
        state, queue, catalog, report, today)
    if not proposals:
        return 0
    patch = latest_patch(folder, date.fromisoformat(today))
    occupied = {row.get("slug") for row in patch["additions"]
                if isinstance(row, dict)}
    added = 0
    for proposal in proposals:
        if (len(patch["additions"]) >= 100
                or proposal["slug"] in occupied
                or conflicts_with_signed_catalogue(
                    proposal, catalog["festivals"], history["knownFestivals"])):
            continue
        patch["additions"].append(proposal)
        occupied.add(proposal["slug"])
        added += 1
    if added:
        patch["generated_at"] = today
        atomic_json(folder / ("patch-" + today + ".json"), patch)
    return added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intake", required=True, type=Path)
    ap.add_argument("--catalog", required=True, type=Path)
    ap.add_argument("--history", required=True, type=Path)
    args = ap.parse_args()
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    def read(path):
        return json.loads(path.read_text(encoding="utf-8"))
    folder = args.intake
    state_path = folder / "source-watch-state.json"
    state = read(state_path)
    queue = read(folder / "national-festival-discovery-review.json")
    catalog, history = read(args.catalog), read(args.history)
    report = examine(state, queue, catalog, today)
    added = append_private_proposals(
        folder, catalog, history, state, queue, report, today)
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    (folder / "national-directory-edition-review.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print("Generic directory research: eligible=" +
          str(report["eligible_count"]) + ", checked=" +
          str(report["checked_count"]) + ", two_day=" +
          str(report["two_day_count"]) + ", private_additions=" +
          str(added) + ", public_publications=0")


if __name__ == "__main__":
    main()
