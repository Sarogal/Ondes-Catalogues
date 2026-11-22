#!/usr/bin/env python3
"""Read PRIVATE national research into bounded Publisher research dossiers.

The output is NOT an approval: it provides only page URLs the publisher can
read and challenge independently. New names/domains/venues/genres are never
compared to a closed registry. Source URLs and raw research remain PRIVATE.
No network access; all live authority, venue, rights, dates and duplicate
checks happen in the Publisher, never in this producer.

Designed for the same runner that already checks out the private intake state.
Never run against a public repository checkout or log candidate names/URLs.
"""
import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from merge_policy import ORIGIN
from ptitesondes_national_backlog_bridge import (
    _atomic_json, _inventory, _inventory_key, _read,
)
from ptitesondes_national_openworld_research_cycle import _future_original
from ptitesondes_open_world_municipal_bootstrap import _safe_research_lead
from ptitesondes_delegated_source_authority import _url_host

SCHEMA = "ptitesondes.private_open_world_dossier_intake.v1"
MAX_DOSSIERS = 30
MAX_PRIVATE_REPORTS = 10000
# Recent PRIVATE research is a rotating hint cache, never a cached approval.
# The Publisher always re-reads all official evidence before an addition.
MAX_REPORT_AGE_DAYS = 14
MAX_RESEARCH_BYTES = 1_500_000
DAY_REF = re.compile(r"[a-f0-9]{64}\.json\Z")


def _https(url):
    if not isinstance(url, str) or not 8 <= len(url) <= 1800:
        return None
    try:
        parts = urlsplit(url)
        if (parts.scheme != "https" or not parts.hostname
                or parts.username or parts.password
                or parts.port not in (None, 443)
                or parts.fragment or parts.path in ("", "/")):
            return None
        return url
    except ValueError:
        return None


def _host(url):
    if _https(url) is None:
        return None
    host = _url_host(url)
    return host.removeprefix("www.") if host else None


def _day_sessions(lead, today):
    future = []
    for item in lead["explicit_source_session_intervals"]:
        try:
            d = date.fromisoformat(item["begin"][:10])
        except (ValueError, TypeError):
            return []
        if today <= d <= date.fromordinal(today.toordinal() + 184):
            future.append(d.isoformat())
    return sorted(set(future))


def collect_research_dossiers(observation_root, research_root, today,
                              *, batch_index=0, inventory_reader=_inventory,
                              report_reader=_read):
    """Produce untrusted research, never trusted source/site evidence."""
    if (type(today) is not date or type(batch_index) is not int
            or not 0 <= batch_index < 4
            or not callable(inventory_reader) or not callable(report_reader)):
        raise ValueError("invalid_private_dossier_schedule")
    # A crawler can find a municipal backlink in one run and the matching
    # OpenAgenda URL on a different run. Do not lose those untrusted clues
    # at midnight or when a per-event crawl advances to its next page.
    by_ref = {}
    report_count = 0
    for age_days in range(MAX_REPORT_AGE_DAYS + 1):
        scan_day = today - timedelta(days=age_days)
        day_root = Path(research_root) / "reports" / scan_day.isoformat()
        if not day_root.exists():
            continue
        if not day_root.is_dir() or day_root.is_symlink():
            raise ValueError("unsafe_private_research_directory")
        reports = sorted(day_root.glob("*.json"))
        report_count += len(reports)
        if report_count > MAX_PRIVATE_REPORTS:
            raise ValueError("private_report_capacity_exceeded")
        for path in reports:
            if not DAY_REF.fullmatch(path.name):
                raise ValueError("untrusted_private_research_filename")
            data, _ = report_reader(path, MAX_RESEARCH_BYTES)
            review = data.get("review") if isinstance(data, dict) else None
            if (not isinstance(data, dict)
                    or data.get("ref") != path.stem
                    or data.get("day") != scan_day.isoformat()
                    or type(review) is not dict
                    or review.get("schema") !=
                        "ptitesondes.private_open_world_candidate_rotation.v1"
                    or review.get("publication_ready") is not False
                    or review.get("public_writes") != 0):
                raise ValueError("invalid_private_national_research_result")
            by_ref.setdefault(path.stem, []).append(review)
    proposals = []
    pair_count = 0
    seen = set()
    for entry in inventory_reader(Path(observation_root)):
        ref = _inventory_key(entry)
        reviews = by_ref.get(ref, [])
        if not reviews:
            continue
        lead = _future_original(entry, today)
        if lead is None or not _safe_research_lead(lead, today):
            continue
        # Untrusted OA URLs do not attest authorship. Prefer a specific
        # canonicalUrl but also investigate other exact HTTPS OA links.
        oa_urls = []
        pairs = []
        for review in reviews:
            for source in review.get("private_unverified_oa_web_leads", []):
                if (not isinstance(source, dict)
                        or source.get("candidate_only") is not True
                        or source.get("owner_verified") is not False
                        or source.get("publication_ready") is not False
                        or source.get("source_rights_reviewed") is not False):
                    continue
                candidate = _https(source.get("url"))
                host = _host(candidate)
                if candidate and host:
                    oa_urls.append((0 if source.get("source_field")
                                    == "canonicalUrl" else 1, host, candidate))
            for pair in review.get("private_research_reviews", []):
                if not isinstance(pair, dict):
                    continue
                municipal, target = (_https(pair.get("municipal_url")),
                                     _https(pair.get("source_url")))
                # Historical discovery is untrusted. The Publisher must
                # fetch fresh independent authority, session and geography.
                if municipal and target and _host(municipal) and _host(target):
                    pairs.append((_host(target), municipal))
        pair_count += len(set(pairs))
        if not oa_urls:
            continue
        for priority, host, official_event_url in sorted(set(oa_urls)):
            matching = sorted(set(
                municipal_url for related_host, municipal_url in pairs
                if host == related_host))
            # A municipal event page can be linked DIRECTLY from OA while
            # its page stays internal to the municipal crawler. That crawler
            # only records EXTERNAL links, so an external-link prerequisite
            # silently loses all direct municipal calendars. This fallback is
            # a research REQUEST only: DILA, venue GPS and exact sessions
            # are verified later by the Publisher. Never allow the fallback
            # to mint authority for an arbitrary OA-supplied website.
            if priority == 0 and not matching:
                matching = [official_event_url]
            # The OA venue's declared website is a candidate for research
            # even when there is no external link from a municipality.
            # This does NOT make OA's self-declared link authoritative:
            # the Publisher must find a separately named OSM/DILA venue,
            # exact live sessions, legal factual reuse and no duplication.
            if priority == 1 and not matching:
                # Only the location.website field can act as an unpaired
                # venue-site clue; registrations/marketing links cannot.
                independent_venue_home = any(
                    source.get("url") == official_event_url
                    and source.get("source_field") == "location.website"
                    for review in reviews
                    for source in review.get("private_unverified_oa_web_leads", [])
                    if isinstance(source, dict)
                )
                if independent_venue_home:
                    matching = [official_event_url]
            for municipal_url in matching:
                municipal_host = _host(municipal_url)
                dossier = {
                    "lead": lead,
                    "date_start": None,
                    "official_event_url": official_event_url,
                    "official_venue_url": municipal_url,
                }
                if host != municipal_host:
                    dossier["municipal_source_reference_url"] = municipal_url
                for day in _day_sessions(lead, today):
                    key = (str(lead["event_uid"]), day,
                           official_event_url, municipal_url)
                    if key in seen:
                        continue
                    seen.add(key)
                    proposals.append(dict(dossier, date_start=day))
    proposals.sort(key=lambda x: (
        x["date_start"], x["lead"]["agenda_uid"],
        x["lead"]["event_uid"], x["official_event_url"],
        x["official_venue_url"]))
    # The four daily review slots are disjoint. If the queue is larger
    # than four slots, rotate through further waves on following days;
    # discovery limits are work budgets, not candidate denylist rules.
    daily_capacity = 4 * MAX_DOSSIERS
    waves = (len(proposals) + daily_capacity - 1) // daily_capacity
    wave = today.toordinal() % waves if waves else 0
    first = wave * daily_capacity + batch_index * MAX_DOSSIERS
    chosen = proposals[first:first + MAX_DOSSIERS]
    return chosen, {
        "reports": report_count, "pairs": pair_count,
        "candidate_dossiers": len(proposals), "queued": len(chosen),
        "more_dossiers_deferred": max(0, len(proposals)-len(chosen)),
    }


def attach_research_dossiers(patch, dossiers, today):
    if (not isinstance(patch, dict)
            or patch.get("schema") != "ptitesondes.patch.v1"
            or patch.get("generated_at") != today.isoformat()
            or patch.get("safe_to_publish") is not False
            or not isinstance(patch.get("source"), dict)
            or patch["source"].get("url") != ORIGIN
            or not isinstance(patch.get("additions"), list)
            or not isinstance(patch.get("updates"), list)
            or not isinstance(patch.get("deferred"), list)
            or not isinstance(dossiers, list)
            or len(dossiers) > MAX_DOSSIERS
            or ("open_world_research" in patch
                and (not isinstance(patch["open_world_research"], list)
                     or len(patch["open_world_research"]) > MAX_DOSSIERS))):
        raise ValueError("invalid_private_dossier_patch")
    # Private collection has four daily slots, but the cloud Publisher may
    # read the patch only after several slots have been processed. Replacing
    # this field with the *last* slot (often empty) silently deleted earlier
    # valid research requests before the Publisher could inspect them.
    #
    # Keep the oldest outstanding requests in this bounded daily patch until
    # its next refresh. Remaining discoveries remain in the private research
    # reports for deterministic future-day rotation. No cached approval is
    # created: each request is independently rechecked at publication time.
    pending = []
    keys = set()
    for item in [*patch.get("open_world_research", []), *dossiers]:
        if type(item) is not dict or type(item.get("lead")) is not dict:
            raise ValueError("invalid_private_dossier_queue_entry")
        lead = item["lead"]
        values = (
            lead.get("agenda_uid"), lead.get("event_uid"),
            item.get("date_start"), item.get("official_event_url"),
            item.get("official_venue_url"),
            item.get("municipal_source_reference_url"),
        )
        if (type(values[0]) is not int or type(values[1]) is not int
                or any(not isinstance(v, str) for v in values[2:5])
                or values[5] is not None and not isinstance(values[5], str)):
            raise ValueError("invalid_private_dossier_queue_identity")
        if values in keys:
            continue
        keys.add(values)
        if len(pending) < MAX_DOSSIERS:
            pending.append(item)
    return {**patch, "open_world_research": pending}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--observation-root", type=Path, required=True)
    ap.add_argument("--research-root", type=Path, required=True)
    ap.add_argument("--patch-file", type=Path, required=True)
    ap.add_argument("--output-file", type=Path, required=True)
    ap.add_argument("--day", type=date.fromisoformat, required=True)
    ap.add_argument("--batch-index", type=int, default=0)
    args = ap.parse_args()
    repo = Path(__file__).resolve().parents[1].resolve()
    for folder in (args.observation_root, args.research_root,
                   args.patch_file.parent, args.output_file.parent):
        if folder.resolve().is_relative_to(repo):
            raise ValueError("private_dossier_inputs_must_not_be_in_public_checkout")
    if args.output_file == args.patch_file:
        raise ValueError("publisher_patch_requires_separate_atomic_output")
    patch, _ = _read(args.patch_file, 1_500_000)
    rows, report = collect_research_dossiers(
        args.observation_root, args.research_root, args.day,
        batch_index=args.batch_index)
    combined = attach_research_dossiers(patch, rows, args.day)
    _atomic_json(args.output_file, combined)
    # Do not print URLs, names, place or event IDs to public Actions.
    # A candidate held in a private report is never counted as published.
    report["queued_for_publisher"] = len(combined["open_world_research"])
    report["pending_queue_capacity_deferred"] = max(
        0, len(patch.get("open_world_research", [])) + len(rows)
        - report["queued_for_publisher"])
    print(json.dumps({"schema": SCHEMA, **report}, sort_keys=True))


if __name__ == "__main__":
    main()
