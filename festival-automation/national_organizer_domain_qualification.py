"""Private qualification of previously unknown organizer/edition websites.

Trusted source is ALWAYS a code-reviewed institutional index revisited by
the existing independent publisher logic. Two-day private link state only
selects the edition; every target is rederived from fresh institutional HTML.
The new site is contacted through DNS-pinned, TLS-verified public HTTPS only.
Verifying edition wording does NOT establish website ownership and cannot
create a public patch or an officialSite.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from dns_pinned_https import fetch_public_html, safe_public_url
from national_institutional_edition_preflight import stable_private_proposals
from national_institutional_organizer_preflight import (
    SCHEMA as LINKS_SCHEMA, STATE_KEY,
    verified_event_website_links, website_link_digest,
)

SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
from grossesondes_institutional_edition import (
    independently_fetch, institutional_date, validate_independent,
)
from grossesondes_structured_edition import no_same_edition_jsonld_contradiction

SCHEMA = "grossesondes.national-organizer-domain-qualification-private.v1"
MAX_INSTITUTIONAL_LINK_ROWS = 2
MAX_DOMAIN_PROBES = 2


def _fresh_authorized_domain_targets(
        state, queue, dates_report, links_report, today, institution_fetch):
    """Reconstruct target URLs from the independently fetched trusted page.

    Untrusted report URLs or observation-state URLs NEVER authorize a fetch.
    """
    if (not isinstance(links_report, dict)
            or links_report.get("schema") != LINKS_SCHEMA
            or links_report.get("as_of") != today
            or links_report.get("review_only") is not True
            or links_report.get("safe_to_publish") is not False
            or links_report.get("publication_authorized") is not False
            or links_report.get("ownership_proven") is not False
            or links_report.get("official_site_authorized") is not False
            or not isinstance(links_report.get("rows"), list)
            or len(links_report["rows"]) > MAX_INSTITUTIONAL_LINK_ROWS):
        raise ValueError("Unsafe organizer link report")
    proposals = stable_private_proposals(state, queue, dates_report, today)
    indexed = {proposal["slug"]: proposal for proposal in proposals}
    records = state.get(STATE_KEY, {})
    if not isinstance(records, dict):
        raise ValueError("Missing private link observations")
    targets = []
    seen = set()
    for row in links_report["rows"]:
        if (not isinstance(row, dict)
                or row.get("status") != "TWO_DAY_INSTITUTIONAL_ORGANIZER_LINK_PRIVATE"
                or row.get("two_day_link_observation") is not True):
            continue
        proposal = indexed.get(row.get("slug"))
        if proposal is None or proposal["slug"] in seen:
            continue
        seen.add(proposal["slug"])
        supplied = row.get("candidate_urls")
        if (not isinstance(supplied, list) or not 1 <= len(supplied) <= 4
                or not all(isinstance(url, str) for url in supplied)):
            continue
        record = records.get(proposal["source"])
        if not isinstance(record, dict):
            continue
        try:
            first_seen = date.fromisoformat(record["firstSeen"])
            last_seen = date.fromisoformat(record["lastSeen"])
            actual_date = date.fromisoformat(today)
        except (KeyError, TypeError, ValueError):
            continue
        if not first_seen < actual_date or last_seen != actual_date:
            continue
        try:
            trusted_html = independently_fetch(
                proposal, today,
                **({"fetch": institution_fetch}
                   if institution_fetch is not None else {}))
            if (trusted_html is None
                    or validate_independent(proposal, trusted_html, today) is None):
                continue
            actual_urls = verified_event_website_links(proposal, trusted_html)
            # Every target must still be linked from this institution's
            # exact edition and match the stable private observation digest.
            if (not actual_urls or supplied != actual_urls
                    or record.get("digest") != website_link_digest(
                        proposal, actual_urls)):
                continue
            for url in actual_urls:
                if safe_public_url(url) is not None:
                    targets.append((proposal, url))
        except (OSError, ValueError, UnicodeError, TypeError, KeyError):
            continue
    return targets


def qualify_organizer_domains(state, queue, dates_report, links_report, today,
                              institution_fetch=None, site_fetch=None):
    date.fromisoformat(today)
    if (not isinstance(state, dict)
            or state.get("schema") != "grossesondes.source-watch.v1"):
        raise ValueError("Unsafe private state")
    targets = _fresh_authorized_domain_targets(
        state, queue, dates_report, links_report, today, institution_fetch)
    # Rotate a strictly bounded number of novel URLs. One unavailable
    # domain must never starve every other eligible organizer.
    targets.sort(key=lambda x: (x[0]["slug"], x[1]))
    if targets:
        begin = (date.fromisoformat(today).toordinal() * MAX_DOMAIN_PROBES) % len(targets)
        selected = [targets[(begin + i) % len(targets)]
                    for i in range(min(MAX_DOMAIN_PROBES, len(targets)))]
    else:
        selected = []
    read_site = fetch_public_html if site_fetch is None else site_fetch
    rows = []
    for proposal, url in selected:
        row = {
            "slug": proposal["slug"],
            "candidate_url": url,
            "status": "DOMAIN_CURRENT_EDITION_UNVERIFIED",
            "review_only": True,
            "safe_to_publish": False,
            "publication_authorized": False,
            "official_site_authorized": False,
            "ownership_proven": False,
            "publisher_gate_connected": False,
            "edition_visible_dates_confirmed": False,
        }
        try:
            html = read_site(url)
            year = date.fromisoformat(proposal["startDate"]).year
            dates = institutional_date(html, proposal["name"], year)
            expected = (proposal["startDate"], proposal["endDate"])
            if (dates is not None
                    and tuple(x.isoformat() for x in dates) == expected
                    and no_same_edition_jsonld_contradiction(
                        html, proposal["name"], *dates)):
                row["status"] = "DOMAIN_CURRENT_EDITION_DATES_RECHECKED_PRIVATE"
                row["edition_visible_dates_confirmed"] = True
            else:
                row["status"] = "DOMAIN_EDITION_CLAIMS_NOT_MATCHED"
        except (OSError, ValueError, UnicodeError, TypeError, KeyError):
            # Never expose redirects, response body, DNS answers or headers.
            row["status"] = "DOMAIN_HTTPS_OR_EVIDENCE_UNAVAILABLE"
        rows.append(row)
    return {
        "schema": SCHEMA, "as_of": today,
        "review_only": True, "safe_to_publish": False,
        "publication_authorized": False, "official_site_authorized": False,
        "ownership_proven": False, "publications": 0,
        "candidate_links_verified_today": len(targets),
        "domains_probed_today": len(rows),
        "domain_edition_dates_confirmed_today": sum(
            x["edition_visible_dates_confirmed"] for x in rows),
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
    result = qualify_organizer_domains(
        read("source-watch-state.json"),
        read("national-festival-discovery-review.json"),
        read("national-institutional-edition-preflight.json"),
        read("national-institutional-organizer-links.json"), today)
    path = folder / "national-institutional-organizer-domain-review.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print("Organizer-domain qualification private: links="
          + str(result["candidate_links_verified_today"])
          + ", sites=" + str(result["domains_probed_today"])
          + ", matching editions="
          + str(result["domain_edition_dates_confirmed_today"])
          + ", publications=0")


if __name__ == "__main__":
    main()
