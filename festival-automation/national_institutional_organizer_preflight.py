"""Generic, private-only organizer-domain link reproof for national festivals.

A newly encountered website is NEVER fetched or trusted by this module.
Only independently re-fetched, code-reviewed institutional index -> detail
chains may create research references. Identical references must persist on
two different consecutive days. This does not prove website ownership,
create a publication patch, or bypass the independent publisher.
"""
import argparse
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

from festival_website_discovery import event_website_links
from national_institutional_edition_preflight import stable_private_proposals
from source_qualification import clean_url, classify, normalized

SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
from grossesondes_institutional_edition import independently_fetch, validate_independent

SCHEMA = "grossesondes.national-institutional-organizer-links-private.v1"
STATE_KEY = "national_institutional_organizer_links_private"
MAX_CHECKS = 2


def reprove_organizer_links(state, queue, dates_report, today, fetch=None):
    """Return a bounded private research trail, with no unknown-domain requests.

    The state itself is not allowed to authorize a URL. Date proposals first
    have to pass the existing trusted-index, two-day and digest gates; a fresh
    independent institutional index -> detail chain is then verified again.
    """
    current = date.fromisoformat(today)
    if (not isinstance(state, dict)
            or state.get("schema") != "grossesondes.source-watch.v1"):
        raise ValueError("Invalid source-watch state")
    observations = state.setdefault(STATE_KEY, {})
    if not isinstance(observations, dict):
        raise ValueError("Invalid organizer-domain observation registry")
    proposals = stable_private_proposals(state, queue, dates_report, today)
    if len(proposals) > MAX_CHECKS:
        raise ValueError("Unbounded institutional proposal list")
    yesterday = (current - timedelta(days=1)).isoformat()
    rows = []
    for proposal in proposals:
        detail = proposal["source"]
        row = {
            "slug": proposal["slug"],
            "status": "INSTITUTIONAL_ORGANIZER_LINK_NOT_RECHECKED",
            "review_only": True,
            "safe_to_publish": False,
            "publication_authorized": False,
            "ownership_proven": False,
            "official_site_authorized": False,
            "candidate_urls": [],
            "two_day_link_observation": False,
        }
        old = observations.pop(detail, None)
        try:
            html = independently_fetch(
                proposal, today,
                **({"fetch": fetch} if fetch is not None else {}))
            if html is None or validate_independent(proposal, html, today) is None:
                row["status"] = "INDEPENDENT_INSTITUTIONAL_REPROOF_FAILED"
                rows.append(row)
                continue
            base_name = re.sub(r"\s+20[2-4][0-9]$", "", proposal["name"]).strip()
            # The detail is a verified institutional source, not a new
            # code-reviewed organizer. Override only its role for extraction;
            # target URLs still go through the usual third-party filters.
            role = lambda url: ("INSTITUTION" if url == detail else classify(url))
            links = event_website_links(
                html, detail, base_name,
                proposal["startDate"], proposal["endDate"],
                clean_url, role, normalized)
            urls = sorted({x["candidate_url"] for x in links
                           if isinstance(x, dict) and isinstance(
                               x.get("candidate_url"), str)})[:4]
            if not urls:
                row["status"] = "NO_EXACT_EVENT_ORGANIZER_WEBSITE_LINK"
                rows.append(row)
                continue
            digest = sha256(json.dumps({
                "index": proposal["originSlug"],
                "detail": detail,
                "edition": proposal["name"],
                "dates": [proposal["startDate"], proposal["endDate"]],
                "links": urls,
            }, sort_keys=True).encode("utf-8")).hexdigest()
            same = (isinstance(old, dict)
                    and old.get("digest") == digest
                    and old.get("lastSeen") in (yesterday, today)
                    and isinstance(old.get("firstSeen"), str))
            try:
                first = date.fromisoformat(old["firstSeen"]) if same else current
                consecutive = (same and first < current
                               and old["lastSeen"] == yesterday)
            except (ValueError, TypeError):
                first, consecutive = current, False
            observations[detail] = {
                "digest": digest, "firstSeen": first.isoformat(),
                "lastSeen": today,
            }
            row.update(
                status=("TWO_DAY_INSTITUTIONAL_ORGANIZER_LINK_PRIVATE"
                        if consecutive else
                        "FIRST_DAY_INSTITUTIONAL_ORGANIZER_LINK_PRIVATE"),
                candidate_urls=urls,
                two_day_link_observation=consecutive,
            )
        except (OSError, ValueError, TypeError, UnicodeError, KeyError):
            row["status"] = "INDEPENDENT_INSTITUTIONAL_REPROOF_FAILED"
        rows.append(row)

    # A stale private record may not become an authorization or persist forever.
    for key, value in list(observations.items()):
        try:
            recent = date.fromisoformat(value["lastSeen"])
            if not 0 <= (current - recent).days <= 14:
                del observations[key]
        except (TypeError, ValueError, KeyError):
            del observations[key]
    return {
        "schema": SCHEMA, "as_of": today,
        "review_only": True, "safe_to_publish": False,
        "publication_authorized": False, "ownership_proven": False,
        "official_site_authorized": False,
        "publications": 0, "checked_count": len(rows),
        "two_day_link_count": sum(x["two_day_link_observation"] for x in rows),
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", required=True, type=Path)
    args = parser.parse_args()
    folder = args.intake
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    def read(name):
        return json.loads((folder / name).read_text(encoding="utf-8"))
    state = read("source-watch-state.json")
    result = reprove_organizer_links(
        state, read("national-festival-discovery-review.json"),
        read("national-institutional-edition-preflight.json"), today)
    (folder / "source-watch-state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (folder / "national-institutional-organizer-links.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Institutional organizer-link review only: checked="
          + str(result["checked_count"]) + ", stable-links="
          + str(result["two_day_link_count"]) + ", publications=0")


if __name__ == "__main__":
    main()
