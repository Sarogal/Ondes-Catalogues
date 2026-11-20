"""Two-day private observations of NEW festival sites linked by institutions.

A listed domain is visited only AFTER a fresh independently reviewed regional
index → exact detail → visibly attributed festival website chain. A private
patch is emitted only after identical dates + domain on two different days;
the publisher must independently rebuild that entire network chain.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from national_detail_qualification import _eligible_sources
from dns_pinned_https import fetch_public_html

SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
from grossesondes_institutional_linked_edition import (
    private_proposal, validate_private_proposal, trusted_live_link, prove_dates,
    conflicts_with_signed_catalogue,
)
from grossesondes_archived_html_intake import latest_patch, atomic_json

SCHEMA = "grossesondes.national-institutional-linked-dates-private.v1"
STATE_KEY = "national_institutional_linked_dates_private"
MAX_CHECKS = 2


def _digest(source, site, dates):
    return sha256(json.dumps({
        "index": source["index_url"], "index_page": source["index_page"],
        "detail": source["url"], "name": source["title"],
        "year": source["year"], "website": site, "dates": dates,
    }, sort_keys=True).encode("utf-8")).hexdigest()


def eligible(state, queue, today):
    sources = _eligible_sources(state, queue, today, due_only=False)
    # The institutional index identity is re-derived from the approved
    # regional registry; never allow a private URL to create a fetch root.
    return sorted(sources, key=lambda x: (x["dossier_id"], x["url"]))


def run(state, queue, today, institution_fetch=None, organizer_fetch=None,
        limit=MAX_CHECKS):
    current = date.fromisoformat(today)
    if (not isinstance(state, dict)
            or state.get("schema") != "grossesondes.source-watch.v1"
            or type(limit) is not int or not 0 <= limit <= MAX_CHECKS):
        raise ValueError("Invalid institutional linked-site preflight")
    observed = state.setdefault(STATE_KEY, {})
    if not isinstance(observed, dict) or len(observed) > 200:
        raise ValueError("Invalid private linked-site observations")
    sources = eligible(state, queue, today)
    active = {x["url"] for x in sources}
    for key in list(observed):
        if key not in active:
            del observed[key]
    yesterday = (current - timedelta(days=1)).isoformat()
    # Only FIRST-day positive evidence has priority the next day. Mature
    # proofs must not permanently starve new institutional leads.
    def pending_second_day(source):
        rec = observed.get(source["url"])
        return (isinstance(rec, dict) and isinstance(rec.get("digest"), str)
                and rec.get("firstSeen") == yesterday
                and rec.get("lastSeen") == yesterday)
    pending = [x for x in sources if pending_second_day(x)]
    others = [x for x in sources if not pending_second_day(x)]
    fresh = [x for x in others if not (
        isinstance(observed.get(x["url"]), dict)
        and observed[x["url"]].get("lastChecked") == today)]
    repeated = [x for x in others if x not in fresh]
    def rotate(rows):
        if not rows:
            return rows
        shift = (current.toordinal() // 2 * MAX_CHECKS) % len(rows)
        return rows[shift:] + rows[:shift]
    selected = (pending + rotate(fresh) + rotate(repeated))[:limit]
    read_site = fetch_public_html if organizer_fetch is None else organizer_fetch
    rows = []
    for source in selected:
        old = observed.pop(source["url"], None)
        row = {
            "dossier_id": source["dossier_id"], "slug": None,
            "status": "INSTITUTION_LINKED_SITE_UNAVAILABLE",
            "review_only": True, "safe_to_publish": False,
            "publication_authorized": False, "publisher_gate_connected": False,
            "two_day_observation": False,
            "website_review_only": None, "start_date_hint": None,
            "end_date_hint": None,
        }
        try:
            kwargs = ({"institution_fetch": institution_fetch}
                      if institution_fetch is not None else {})
            site = trusted_live_link(source, today, **kwargs)
            if site is None:
                row["status"] = "TRUSTED_INDEX_DETAIL_LINK_NOT_PROVEN"
                observed[source["url"]] = {"lastChecked": today}
                rows.append(row)
                continue
            html = read_site(site)
            dates = prove_dates(html, source["title"], source["year"], today)
            if dates is None:
                row["status"] = "LINKED_SITE_EXACT_DATES_NOT_PROVEN"
                observed[source["url"]] = {"lastChecked": today}
                rows.append(row)
                continue
            digest = _digest(source, site, dates)
            same = (isinstance(old, dict)
                    and old.get("digest") == digest
                    and old.get("lastSeen") in (yesterday, today)
                    and isinstance(old.get("firstSeen"), str))
            try:
                first = date.fromisoformat(old["firstSeen"]) if same else current
                continuous = same and first < current and old["lastSeen"] in (today, yesterday)
            except (ValueError, TypeError):
                first, continuous = current, False
            observed[source["url"]] = {
                "digest": digest, "firstSeen": first.isoformat(),
                "lastSeen": today, "lastChecked": today,
            }
            proposal = private_proposal(source, site, dates, today)
            if proposal is None:
                observed[source["url"]] = {"lastChecked": today}
                rows.append(row)
                continue
            row.update(
                slug=proposal["slug"], website_review_only=site,
                start_date_hint=dates[0], end_date_hint=dates[1],
                status=("TWO_DAY_INSTITUTION_LINKED_DATES_PRIVATE"
                        if continuous else "FIRST_DAY_INSTITUTION_LINKED_DATES_PRIVATE"),
                two_day_observation=continuous,
            )
        except (OSError, ValueError, UnicodeError, TypeError, KeyError):
            row["status"] = "INSTITUTION_LINKED_SITE_UNAVAILABLE"
        if source["url"] not in observed:
            # Rejected link or failed HTTPS must erase any previous digest.
            observed[source["url"]] = {"lastChecked": today}
        rows.append(row)
    # Bound stale state to prevent a removed institutional link being
    # resurrected as a future publisher authorization.
    for key, value in list(observed.items()):
        try:
            last = date.fromisoformat(
                value.get("lastChecked", value.get("lastSeen")))
            if not 0 <= (current - last).days <= 7:
                del observed[key]
        except (ValueError, TypeError, KeyError):
            del observed[key]
    return {
        "schema": SCHEMA, "as_of": today,
        "review_only": True, "safe_to_publish": False,
        "publication_authorized": False, "publications": 0,
        "checked_count": len(rows),
        "two_day_observations_count": sum(x["two_day_observation"] for x in rows),
        "rows": rows,
    }


def stable_private_proposals(state, queue, report, today):
    if (not isinstance(report, dict) or report.get("schema") != SCHEMA
            or report.get("as_of") != today
            or report.get("review_only") is not True
            or report.get("safe_to_publish") is not False
            or report.get("publication_authorized") is not False
            or report.get("publications") != 0
            or not isinstance(report.get("rows"), list)
            or len(report["rows"]) > MAX_CHECKS):
        raise ValueError("Untrusted linked-site report")
    sources = eligible(state, queue, today)
    records = state.get(STATE_KEY, {})
    proposals, seen = [], set()
    for row in report["rows"]:
        if (not isinstance(row, dict)
                or row.get("two_day_observation") is not True
                or row.get("status") != "TWO_DAY_INSTITUTION_LINKED_DATES_PRIVATE"
                or row.get("publication_authorized") is not False):
            continue
        dates = row.get("start_date_hint"), row.get("end_date_hint")
        site = row.get("website_review_only")
        matching = []
        for source in sources:
            if source["dossier_id"] != row.get("dossier_id"):
                continue
            record = records.get(source["url"])
            if not isinstance(record, dict):
                continue
            if (record.get("digest") != _digest(source, site, dates)
                    or record.get("lastSeen") != today):
                continue
            try:
                first = date.fromisoformat(record["firstSeen"])
                if first >= date.fromisoformat(today):
                    continue
            except (ValueError, KeyError, TypeError):
                continue
            matching.append(source)
        if len(matching) != 1:
            continue
        proposal = private_proposal(matching[0], site, dates, today)
        if (proposal is None or proposal["slug"] != row.get("slug")
                or proposal["slug"] in seen
                or validate_private_proposal(proposal, today) is None):
            continue
        proposals.append(proposal)
        seen.add(proposal["slug"])
    return proposals


def append_private_proposals(folder, catalog, history, state, queue, report, today):
    if (not isinstance(catalog, dict) or catalog.get("schema") != 1
            or not isinstance(catalog.get("festivals"), list)
            or not isinstance(history, dict) or history.get("schema") != 2
            or not isinstance(history.get("knownFestivals"), list)):
        raise ValueError("Invalid signed catalogue and archives")
    proposals = stable_private_proposals(state, queue, report, today)
    if not proposals:
        return 0
    patch = latest_patch(folder, date.fromisoformat(today))
    occupied = {x.get("slug") for x in patch["additions"] if isinstance(x, dict)}
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    args = parser.parse_args()
    folder = args.intake
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    state_path = folder / "source-watch-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    queue = json.loads((folder / "national-festival-discovery-review.json")
                       .read_text(encoding="utf-8"))
    report = run(state, queue, today)
    added = append_private_proposals(
        folder,
        json.loads(args.catalog.read_text(encoding="utf-8")),
        json.loads(args.history.read_text(encoding="utf-8")),
        state, queue, report, today)
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (folder / "national-institutional-linked-dates.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Linked organizer preflight: checked="
          + str(report["checked_count"])
          + ", stable=" + str(report["two_day_observations_count"])
          + ", private_patch_additions=" + str(added)
          + ", direct_publications=0")


if __name__ == "__main__":
    main()
