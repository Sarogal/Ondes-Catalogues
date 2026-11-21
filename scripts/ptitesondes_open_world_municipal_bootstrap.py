"""PRIVATE open-world bridge: any discovered OA event -> DILA municipal sources.

No configured agenda, municipality, organizer, venue, activity, keyword or
domain allowlist. Start from a national OA v2 UID+slug/event research item,
re-read it from OA, check its exact timings and public/physical French
location, then use DILA to discover *that municipality's* current homepage.

The municipality's links are ONLY leads: a directory-certified city domain
does NOT certify the linked organizer, performer, venue, session, licence,
fees, age, geography, or publication rights. No publisher or cron changes.
"""
from datetime import date
import re

from proof import norm
from ptitesondes_dila_municipal_domains import (
    fetch_dila, municipal_site_hosts,
)
from ptitesondes_dynamic_municipal_source_links import (
    scan_municipal_page,
)
from ptitesondes_openagenda_national_event_research import (
    _french_text, _time_sessions, MAX_TIMINGS,
)
from ptitesondes_openagenda_v2_direct_evidence import (
    _french_location, _valid_public_read_key,
    read_direct_agenda_v2, read_direct_v2,
)
from ptitesondes_unlisted_source_safe_recheck import read_unknown_https

SCHEMA = "ptitesondes.open_world_municipal_bootstrap.v1"
MAX_REFERENCE_URLS = 5  # DILA itself permits up to five verified municipal homes


def _blank(status):
    return {
        "schema": SCHEMA, "status": status,
        "municipality_from_live_oa_not_registry": False,
        "municipal_origins_verified_by_dila": 0,
        "municipal_homepages_checked": 0,
        "municipal_homepages_unavailable": 0,
        "source_links_found_in_pages": 0,
        "private_link_reports": [],
        "organizer_domain_attested": False,
        "source_rights_reviewed": False,
        "events_independently_attested": False,
        "venue_geography_verified": False,
        "publisher_connected": False, "publication_ready": False,
        "approval_granted": False, "public_writes": 0,
    }


def _safe_research_lead(lead, today):
    if (type(lead) is not dict or type(today) is not date
            or type(lead.get("agenda_uid")) is not int
            or not 0 < lead["agenda_uid"] < 10**12
            or type(lead.get("event_uid")) is not int
            or not 0 < lead["event_uid"] < 10**12
            or not isinstance(lead.get("agenda_slug"), str)
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,100}",
                                lead["agenda_slug"])
            or not isinstance(lead.get("title"), str)
            or not 0 < len(lead["title"]) <= 300
            or lead.get("publication_ready") is not False
            or lead.get("public_writes") != 0
            or type(lead.get("explicit_source_session_intervals")) is not list
            or not 1 <= len(lead["explicit_source_session_intervals"])
                   <= MAX_TIMINGS):
        return False
    return all(
        type(row) is dict and set(row) == {"begin", "end"}
        and all(type(row[x]) is str and len(row[x]) <= 40
                for x in ("begin", "end"))
        for row in lead["explicit_source_session_intervals"]
    )


def bootstrap_municipal_sources(
        lead, key, today, *,
        agenda_reader=read_direct_agenda_v2,
        event_reader=read_direct_v2,
        directory_reader=fetch_dila,
        municipal_html_reader=read_unknown_https):
    """No known agenda required. All network readers are independently pinned.

    An official municipal homepage is identified only from the DILA directory,
    never from self-advertised OA location.website or source/organizer metadata.
    """
    if (not _safe_research_lead(lead, today)
            or not _valid_public_read_key(key)
            or not all(callable(x) for x in (
                agenda_reader, event_reader,
                directory_reader, municipal_html_reader))):
        return _blank("invalid_private_oa_lead")
    uid, eid, slug = (
        lead["agenda_uid"], lead["event_uid"], lead["agenda_slug"])
    try:
        agenda = agenda_reader(uid, key)
        if (not isinstance(agenda, dict)
                or str(agenda.get("uid")) != str(uid)
                or agenda.get("slug") != slug):
            return _blank("live_oa_agenda_identity_conflict")
        event = event_reader(uid, eid, key)
    except (OSError, ValueError, TypeError, KeyError, TimeoutError):
        return _blank("oa_live_metadata_unavailable")
    if (not isinstance(event, dict)
            or type(event.get("uid")) is not int or event["uid"] != eid
            or type(event.get("state")) is not int or event["state"] != 2
            or event.get("removed") is True
            or type(event.get("status")) is not int
            or event["status"] not in (1, 2)
            or not isinstance(event.get("location"), dict)
            or not _french_location(event["location"])
            or norm(_french_text(event, "title")) != norm(lead["title"])):
        return _blank("live_oa_event_identity_or_location_conflict")
    loc = event["location"]
    city = loc.get("adminLevel4")
    venue = loc.get("name")
    if (not isinstance(city, str) or not 1 <= len(city) <= 120
            or not norm(city)
            or not isinstance(venue, str) or not 1 <= len(venue) <= 180
            or not norm(venue)
            or (isinstance(lead.get("city_unverified"), str)
                and norm(lead["city_unverified"]) != norm(city))
            or (isinstance(lead.get("venue_unverified"), str)
                and norm(lead["venue_unverified"]) != norm(venue))
            or (isinstance(lead.get("country_code_unverified"), str)
                and lead["country_code_unverified"]
                != loc.get("countryCode"))):
        return _blank("live_oa_city_or_venue_changed")
    timings, _ = _time_sessions(event.get("timings"), today)
    if (not timings or timings !=
            lead["explicit_source_session_intervals"]):
        return _blank("live_oa_explicit_session_changed")

    # This is a **query**, not a whitelist. Any new place name is eligible
    # for an independent authority lookup, including overseas municipalities.
    try:
        directory = directory_reader(city)
    except (OSError, ValueError, TypeError, KeyError, TimeoutError):
        return _blank("dila_municipal_directory_unavailable")
    hosts = municipal_site_hosts(city, directory)
    if not hosts:
        return _blank("dila_municipal_domain_not_verified")
    if len(hosts) > MAX_REFERENCE_URLS:
        return _blank("dila_municipal_hosts_ambiguous")

    out = _blank("municipal_homepage_source_research_only")
    out["municipality_from_live_oa_not_registry"] = True
    out["municipal_origins_verified_by_dila"] = len(hosts)
    for host in sorted(hosts):
        url = "https://" + host + "/"
        try:
            html = municipal_html_reader(url)
            result = scan_municipal_page(
                city, directory, {"url": url, "html": html})
        except (OSError, ValueError, TypeError, KeyError, TimeoutError,
                UnicodeError):
            out["municipal_homepages_unavailable"] += 1
            continue
        if result["status"] != "private_source_link_research_only":
            out["municipal_homepages_unavailable"] += 1
            continue
        out["municipal_homepages_checked"] += 1
        out["source_links_found_in_pages"] += result["total_links_on_page"]
        # A homepage can have thousands of linked paths; retain its cursor,
        # not only its first 40, for a later private continuation.
        out["private_link_reports"].append({
            "municipal_page_url": url, "source_links": result,
        })
    if out["municipal_homepages_unavailable"]:
        out["status"] = ("municipal_sources_partial_research"
                         if out["municipal_homepages_checked"]
                         else "all_municipal_homepages_unavailable")
    return out


def public_redacted_municipal_bootstrap(result):
    """Aggregate only; never emit municipality, URL or source event IDs."""
    allowed = {
        "invalid_private_oa_lead", "live_oa_agenda_identity_conflict",
        "oa_live_metadata_unavailable",
        "live_oa_event_identity_or_location_conflict",
        "live_oa_city_or_venue_changed",
        "live_oa_explicit_session_changed",
        "dila_municipal_directory_unavailable",
        "dila_municipal_domain_not_verified",
        "dila_municipal_hosts_ambiguous",
        "municipal_homepage_source_research_only",
        "municipal_sources_partial_research",
        "all_municipal_homepages_unavailable",
    }
    if (not isinstance(result, dict) or result.get("schema") != SCHEMA
            or result.get("status") not in allowed
            or any(result.get(k) is not False for k in (
                "organizer_domain_attested", "source_rights_reviewed",
                "events_independently_attested", "venue_geography_verified",
                "publisher_connected", "publication_ready",
                "approval_granted"))
            or result.get("public_writes") != 0):
        raise ValueError("invalid_open_world_bootstrap_result")
    return {
        "schema": SCHEMA + ".aggregate",
        "status": result["status"],
        "homepages_checked": result["municipal_homepages_checked"],
        "homepages_unavailable":
            result["municipal_homepages_unavailable"],
        "new_links_found": result["source_links_found_in_pages"],
        "publisher_connected": False, "publication_ready": False,
        "public_writes": 0,
    }
