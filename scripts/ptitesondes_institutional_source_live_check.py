"""Live read-only authority-host check for pre-reviewed institutional indexes.

Only the committed registry supplies URLs. Official city/authority pages and
source legal notices are fetched through the existing strict HTTPS/no-redirect
transport, never by event candidates. This proves only the current presence
of a link and page reachability; it does NOT prove legal reuse permission.
"""
import json
from urllib.parse import urlsplit

from ptitesondes_institutional_source_policy import (
    MANIFEST_PATH, MAX_REGISTRY_BYTES, _manifest_valid,
    corroborate_independent_authority_link,
)
from ptitesondes_openagenda_v2_geo_fetch import fetch_official_page

SCHEMA = "ptitesondes.institutional_source_live_authority_smoke.v1"
MAX_TO_CHECK = 15


def run_source_authority_check(reader=fetch_official_page):
    counts = {
        "registered": 0, "institutional_host_link_confirmed": 0,
        "authority_link_unconfirmed": 0, "publisher_notice_page_reachable": 0,
        "publisher_notice_page_unconfirmed": 0,
        "source_policy_reuse_pending": 0,
        "source_policy_reuse_restricted": 0,
        "source_policy_review_recorded_not_release": 0,
    }
    result = {
        "schema": SCHEMA, "stage": "registry_unavailable",
        "counts": counts,
        "publisher_licence_attested": False,
        "licence_or_reuse_rights_inferred_from_site": False,
        "organizer_event_attested": False,
        "publisher_connected": False, "publication_ready": False,
        "approval_granted": False, "public_writes": 0,
        "contains_source_names_or_urls": False,
    }
    try:
        if MANIFEST_PATH.stat().st_size > MAX_REGISTRY_BYTES:
            return result
        registry = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return result
    if (not _manifest_valid(registry)
            or not 1 <= len(registry["entries"]) <= MAX_TO_CHECK):
        return result
    for source in registry["entries"]:
        counts["registered"] += 1
        policy = source["reuse_policy_state"]
        if policy == "pending_source_legal_review":
            counts["source_policy_reuse_pending"] += 1
        elif policy == "restricted_do_not_reuse":
            counts["source_policy_reuse_restricted"] += 1
        else:
            counts["source_policy_review_recorded_not_release"] += 1
        authority = source["external_authority_url"]
        try:
            page = reader({
                "approved_host": urlsplit(authority).hostname,
                "exact_url": authority,
            })
            linked = corroborate_independent_authority_link(
                source, page, primary_source_host=source["approved_host"])
        except (KeyError, TypeError, ValueError, OSError):
            linked = False
        counts[
            "institutional_host_link_confirmed" if linked
            else "authority_link_unconfirmed"
        ] += 1
        notice = source["publisher_notice_url"]
        try:
            page = reader({
                "approved_host": urlsplit(notice).hostname,
                "exact_url": notice,
            })
            notice_ok = (isinstance(page, dict)
                         and page.get("url") == notice
                         and isinstance(page.get("html"), str)
                         and len(page["html"]) >= 100)
        except (KeyError, TypeError, ValueError, OSError):
            notice_ok = False
        counts[
            "publisher_notice_page_reachable" if notice_ok
            else "publisher_notice_page_unconfirmed"
        ] += 1
    return dict(result, stage="bounded_source_reference_check_completed")


if __name__ == "__main__":
    print(json.dumps(run_source_authority_check(), sort_keys=True))
