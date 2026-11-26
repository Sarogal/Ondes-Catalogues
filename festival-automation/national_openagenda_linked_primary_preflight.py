"""OpenAgenda event -> first-party festival website preflight.

Only a public OpenAgenda link re-derived from the independently scanned
OpenData national queue can nominate a festival website. The private feed,
dates and website remain untrusted; the separate cloud Publisher must repeat
both HTTP checks before an append-only edition is accepted.
A current verified first-party observation can be proposed immediately;
two-day stability remains a diagnostic, not publication authority.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from dns_pinned_https import fetch_public_html
from national_openagenda_research import (SOURCE as OPENAGENDA_DATASET,
                                          validated_leads as validated_openagenda_leads)
from national_professional_profile_discovery import discover as discover_professional_profiles
from national_generic_primary_domain_preflight import (
    _edition_name, _published, QUEUE_SCHEMA,
)
from grossesondes_openagenda_linked_edition import (
    event_url, attributed_site, verify_official_site_pages,
    private_proposal, validate_private_proposal, municipal_selector,
    prove_municipal_edition,
)
from grossesondes_institutional_edition import conflicts_with_signed_catalogue
from grossesondes_archived_html_intake import latest_patch, atomic_json

SCHEMA = "grossesondes.national-openagenda-linked-private.v1"
STATE_KEY = "national_openagenda_linked_first_party_observations_private"
MAX_CHECKS = 4
MAX_DOSSIERS = 200
MAX_SOURCES_PER_DOSSIER = 12


def eligible(queue, catalogue, today):
    current = date.fromisoformat(today)
    if (not isinstance(queue, dict) or queue.get("schema") != QUEUE_SCHEMA
            or queue.get("as_of") != today
            or queue.get("review_only") is not True
            or queue.get("safe_to_publish") is not False
            or queue.get("publication_authorized") is not False
            or not isinstance(queue.get("dossiers"), list)
            or len(queue["dossiers"]) > MAX_DOSSIERS
            or not isinstance(catalogue, dict)
            or catalogue.get("schema") != 1
            or not isinstance(catalogue.get("festivals"), list)):
        raise ValueError("Unsafe OpenAgenda discovery input")
    selected, seen = [], set()
    for dossier in queue["dossiers"]:
        if (not isinstance(dossier, dict)
                or dossier.get("publication_authorized") is not False
                or dossier.get("safe_to_publish") is not False
                or not re.fullmatch(r"national-[a-z0-9-]{8,120}",
                                    str(dossier.get("id", "")))
                or not isinstance(dossier.get("sources"), list)
                or len(dossier["sources"]) > MAX_SOURCES_PER_DOSSIER):
            continue
        year = dossier.get("edition_year_hint")
        title = _edition_name(dossier.get("name_hint"), year)
        if (title is None or not current.year <= year <= current.year + 3
                or _published(catalogue, title, year)):
            continue
        # An unverified date hint affects ordering ONLY. Never pass it to
        # the independent proof or authorize a publication with it.
        hints = []
        raw_hints = dossier.get("date_hints")
        if isinstance(raw_hints, list):
            for hint in raw_hints[:30]:
                if not isinstance(hint, dict):
                    continue
                try:
                    start = date.fromisoformat(hint["start_date"])
                except (ValueError, TypeError, KeyError):
                    continue
                if start.year == year and start >= current:
                    hints.append(start.isoformat())
        for source in dossier["sources"]:
            if (not isinstance(source, dict)
                    or source.get("kind") != "OPENAGENDA_PUBLIC_RESEARCH_ONLY"
                    or source.get("publication_authorized") is not False
                    or source.get("discovered_via") != OPENAGENDA_DATASET
                    or event_url(source.get("url")) is None):
                continue
            try:
                first = date.fromisoformat(source["firstSeen"])
                last = date.fromisoformat(source["lastSeen"])
            except (ValueError, TypeError, KeyError):
                continue
            key = (dossier["id"], source["url"])
            if (not first <= last <= current
                    or (current - last).days > 30 or key in seen):
                continue
            seen.add(key)
            selected.append({
                "dossier_id": dossier["id"], "title": title,
                "year": year, "url": source["url"],
                "priority_date_hint": min(hints, default=None),
                "municipality": (dossier.get("city_hint")
                                 if municipal_selector(dossier.get("city_hint"))
                                 else None),
            })
    return sorted(selected, key=lambda x: (x["title"], x["url"]))


def digest(source, site, dates, municipality=None):
    data = {
        "dossier": source["dossier_id"], "event": source["url"],
        "title": source["title"], "year": source["year"],
        "site": site, "dates": list(dates),
    }
    if municipality is not None:
        data["municipality"] = municipality
    return sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()


def examine(state, queue, catalogue, today, *, event_fetch=None,
            organizer_fetch=None, limit=MAX_CHECKS):
    current = date.fromisoformat(today)
    if (not isinstance(state, dict)
            or state.get("schema") != "grossesondes.source-watch.v1"
            or type(limit) is not int or not 0 <= limit <= MAX_CHECKS):
        raise ValueError("Unsafe OpenAgenda watch state")
    sources = eligible(queue, catalogue, today)
    observed = state.setdefault(STATE_KEY, {})
    if not isinstance(observed, dict) or len(observed) > MAX_DOSSIERS:
        raise ValueError("Unsafe OpenAgenda observations")
    active = {s["url"] for s in sources}
    for key in list(observed):
        if key not in active:
            del observed[key]
    yesterday = (current - timedelta(days=1)).isoformat()
    def old(s):
        row = observed.get(s["url"])
        return row if isinstance(row, dict) else {}
    def priority(s):
        hint = s["priority_date_hint"]
        # Unknown dates in the current year are potentially urgent. Use
        # December 31 as their coarse ordering hint, not an edition date.
        return (hint or f'{s["year"]}-12-31', s["title"], s["url"])

    def last_checked(s):
        try:
            day = date.fromisoformat(old(s).get("lastChecked"))
            return day if day <= current else date.min
        except (TypeError, ValueError):
            return date.min

    fresh = [s for s in sources if last_checked(s) != current]
    repeated = [s for s in sources if last_checked(s) == current]
    # Never recheck a dossier today while another eligible one is unchecked.
    # Oldest-first guarantees that future-year and long-running candidates
    # advance too, even when today's queue contains new urgent candidates.
    selected = (sorted(fresh, key=lambda s: (last_checked(s), priority(s)))
                + sorted(repeated, key=priority))[:limit]
    read_event = event_fetch or fetch_public_html
    read_site = organizer_fetch or fetch_public_html
    output = []
    current_hints = {lead['source_url']: lead.get('professional_source_hints_review_only')
                     for lead in validated_openagenda_leads(state, today)}
    for source in selected:
        url = source["url"]
        prior = observed.pop(url, {})
        row = {
            "dossier_id": source["dossier_id"],
            "status": "OPENAGENDA_OR_SITE_UNPROVEN",
            "review_only": True, "safe_to_publish": False,
            "publication_authorized": False,
            "publisher_gate_connected": False,
            "two_day_observation": False, "event_ref_review_only": url,
            "site_review_only": None,
            "start_date_hint": None, "end_date_hint": None,
        }
        site, dates, municipality = None, None, None
        try:
            page = read_event(url)
            site = attributed_site(page, source["title"], url)
            if site is None:
                row["status"] = "OPENAGENDA_OFFICIAL_LINK_UNPROVEN"
            else:
                dates = verify_official_site_pages(
                    site, read_site(site), source["title"], source["year"],
                    today, fetch=read_site)
                if dates is None:
                    row["status"] = "FIRST_PARTY_EDITION_UNPROVEN"
        except (OSError, ValueError, TypeError, UnicodeError, KeyError):
            row["status"] = "OPENAGENDA_OR_FIRST_PARTY_HTTPS_UNAVAILABLE"
        # OpenAgenda is discovery only. A government-attributed municipality
        # may independently prove its own event, even if OA cannot be read.
        # Do not bypass a reachable attributed organizer whose edition
        # proof failed (it may explicitly contradict the municipal agenda).
        if dates is None and site is None and source["municipality"] is not None:
            direct = prove_municipal_edition(
                source["municipality"], source["title"], today, fetch=read_site)
            if direct is not None:
                site, dates = direct
                municipality = source["municipality"]
        if dates is not None:
            signature = digest(source, site, dates, municipality)
            stable = bool(
                isinstance(prior, dict)
                and prior.get("digest") == signature
                and prior.get("lastSeen") in (yesterday, today)
                and isinstance(prior.get("firstSeen"), str)
                and prior["firstSeen"] < today
                and (prior.get("lastSeen") == yesterday
                     or prior.get("stable") is True))
            observed[url] = {
                "digest": signature,
                "firstSeen": prior["firstSeen"] if stable else today,
                "lastSeen": today, "lastChecked": today,
                "site": site, "stable": stable,
                "municipality": municipality,
            }
            row.update(
                status=("TWO_DAY_OPENAGENDA_FIRST_PARTY_PRIVATE" if stable
                        else "FIRST_DAY_OPENAGENDA_FIRST_PARTY_PRIVATE"),
                two_day_observation=stable, site_review_only=site,
                start_date_hint=dates[0], end_date_hint=dates[1],
                municipality_review_only=municipality,
            )
        # Only a fresh validated OpenData lead may initiate bounded ticket/profile
        # research. No discovered website enters the existing proposal gate.
        if dates is None and current_hints.get(url) is not None:
            row["professional_research_review_only"] = discover_professional_profiles(
                current_hints[url], source["title"], source["year"], fetch=read_site)
        if url not in observed:
            observed[url] = {"lastChecked": today}
        output.append(row)
    return {
        "schema": SCHEMA, "as_of": today,
        "review_only": True, "safe_to_publish": False,
        "publication_authorized": False, "publications": 0,
        "eligible_count": len(sources), "checked_count": len(output),
        "two_day_count": sum(r["two_day_observation"] for r in output),
        "rows": output,
    }


def stable_private_proposals(state, queue, catalogue, report, today):
    if (not isinstance(report, dict) or report.get("schema") != SCHEMA
            or report.get("as_of") != today
            or report.get("review_only") is not True
            or report.get("safe_to_publish") is not False
            or report.get("publication_authorized") is not False
            or report.get("publications") != 0
            or not isinstance(report.get("rows"), list)
            or len(report["rows"]) > MAX_CHECKS):
        raise ValueError("Untrusted OpenAgenda report")
    source_map = {
        (s["dossier_id"], s["url"]): s
        for s in eligible(queue, catalogue, today)
    }
    records = state.get(STATE_KEY, {})
    if not isinstance(records, dict):
        raise ValueError("Invalid observation registry")
    accepted, slugs = [], set()
    for row in report["rows"]:
        if (not isinstance(row, dict)
                or row.get("status") not in (
                    "FIRST_DAY_OPENAGENDA_FIRST_PARTY_PRIVATE",
                    "TWO_DAY_OPENAGENDA_FIRST_PARTY_PRIVATE")
                or row.get("two_day_observation") is not (
                    row.get("status") == "TWO_DAY_OPENAGENDA_FIRST_PARTY_PRIVATE")
                or row.get("publication_authorized") is not False):
            continue
        key = row.get("dossier_id"), row.get("event_ref_review_only")
        source = source_map.get(key)
        if source is None:
            continue
        record = records.get(source["url"])
        dates = row.get("start_date_hint"), row.get("end_date_hint")
        site = row.get("site_review_only")
        municipality = row.get("municipality_review_only")
        if municipality is not None and municipality != source["municipality"]:
            continue
        if (not isinstance(record, dict)
                or record.get("municipality") != municipality
                or record.get("stable") is not row["two_day_observation"]
                or record.get("lastSeen") != today
                or record.get("lastChecked") != today
                or record.get("site") != site
                or record.get("digest") != digest(source, site, dates, municipality)):
            continue
        try:
            first_seen = date.fromisoformat(record["firstSeen"])
            current_day = date.fromisoformat(today)
            if (first_seen > current_day
                    or (row["two_day_observation"] and first_seen >= current_day)
                    or (not row["two_day_observation"] and first_seen != current_day)):
                continue
        except (TypeError, ValueError, KeyError):
            continue
        proposal = private_proposal(
            source["title"], site, dates, today, event_ref=source["url"],
            municipality=municipality)
        if (proposal is None or proposal["slug"] in slugs
                or validate_private_proposal(proposal, today) is None):
            continue
        slugs.add(proposal["slug"])
        accepted.append(proposal)
    return accepted


def append_private_proposals(folder, catalog, history, state, queue, report, today):
    if (not isinstance(history, dict) or history.get("schema") != 2
            or not isinstance(history.get("knownFestivals"), list)):
        raise ValueError("Unsafe festival history")
    additions = stable_private_proposals(
        state, queue, catalog, report, today)
    if not additions:
        return 0
    patch = latest_patch(folder, date.fromisoformat(today))
    used = {row.get("slug") for row in patch["additions"]
            if isinstance(row, dict)}
    added = 0
    for row in additions:
        if (len(patch["additions"]) >= 100 or row["slug"] in used
                or conflicts_with_signed_catalogue(
                    row, catalog["festivals"], history["knownFestivals"])):
            continue
        patch["additions"].append(row)
        used.add(row["slug"])
        added += 1
    if added:
        patch["generated_at"] = today
        atomic_json(folder / ("patch-" + today + ".json"), patch)
    return added


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--intake", required=True, type=Path)
    p.add_argument("--catalog", required=True, type=Path)
    p.add_argument("--history", required=True, type=Path)
    a = p.parse_args()
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    def read(path):
        return json.loads(path.read_text(encoding="utf-8"))
    folder = a.intake
    state_path = folder / "source-watch-state.json"
    state = read(state_path)
    queue = read(folder / "national-festival-discovery-review.json")
    catalogue, history = read(a.catalog), read(a.history)
    report = examine(state, queue, catalogue, today)
    added = append_private_proposals(
        folder, catalogue, history, state, queue, report, today)
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    (folder / "national-openagenda-linked-edition-review.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print("OpenAgenda linked publisher preflight eligible=" +
          str(report["eligible_count"]) + " checked=" +
          str(report["checked_count"]) + " J1=" +
          str(report["two_day_count"]) + " private_additions=" +
          str(added) + " publications=0")


if __name__ == "__main__":
    main()
