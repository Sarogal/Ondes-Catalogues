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
from datetime import date
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
    day_root = Path(research_root) / "reports" / today.isoformat()
    if not day_root.is_dir():
        return [], {"reports": 0, "pairs": 0, "candidate_dossiers": 0,
                    "queued": 0, "more_dossiers_deferred": 0}
    if day_root.is_symlink():
        raise ValueError("symlink_private_research_directory")
    reports = sorted(day_root.glob("*.json"))
    if len(reports) > MAX_PRIVATE_REPORTS:
        raise ValueError("private_report_capacity_exceeded")
    by_ref = {}
    for path in reports:
        if not DAY_REF.fullmatch(path.name):
            raise ValueError("untrusted_private_research_filename")
        data, _ = report_reader(path, MAX_RESEARCH_BYTES)
        if (not isinstance(data, dict) or data.get("ref") != path.stem
                or data.get("day") != today.isoformat()
                or not isinstance(data.get("review"), dict)
                or data["review"].get("publication_ready") is not False
                or data["review"].get("public_writes") != 0):
            raise ValueError("invalid_private_national_research_result")
        by_ref[path.stem] = data["review"]
    proposals = []
    pair_count = 0
    seen = set()
    for entry in inventory_reader(Path(observation_root)):
        ref = _inventory_key(entry)
        review = by_ref.get(ref)
        if review is None:
            continue
        lead = _future_original(entry, today)
        if lead is None or not _safe_research_lead(lead, today):
            continue
        # Untrusted OA URLs do not attest authorship. Prefer a specific
        # canonicalUrl but also investigate other exact HTTPS OA links.
        oa_urls = []
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
        if not oa_urls:
            continue
        pairs = []
        for pair in review.get("private_research_reviews", []):
            if not isinstance(pair, dict):
                continue
            municipal, target = (_https(pair.get("municipal_url")),
                                 _https(pair.get("source_url")))
            # Discovered municipal <a> links remain only research hints.
            if municipal and target and _host(municipal) and _host(target):
                pairs.append((_host(target), municipal))
        pair_count += len(pairs)
        if not pairs:
            continue
        for _priority, host, official_event_url in sorted(set(oa_urls)):
            for related_host, municipal_url in pairs:
                if host != related_host:
                    continue
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
    # Four independent reviews per day can cover successive partitions. A
    # bounded time budget is NOT a permanent semantic denylist.
    first = (batch_index * MAX_DOSSIERS) % len(proposals) if proposals else 0
    count = min(MAX_DOSSIERS, len(proposals))
    chosen = (proposals[first:first+count]
              + proposals[:max(0, first+count-len(proposals))])
    return chosen, {
        "reports": len(reports), "pairs": pair_count,
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
    # Never merge untrusted research into additions. Publisher recomputes all
    # evidence and rejects any dossier whose origin/GPS/clock/rights disagree.
    return {**patch, "open_world_research": dossiers}


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
    _atomic_json(args.output_file,
                 attach_research_dossiers(patch, rows, args.day))
    # Do not print URLs, names, place or event IDs to public Actions.
    print(json.dumps({"schema": SCHEMA, **report}, sort_keys=True))


if __name__ == "__main__":
    main()
