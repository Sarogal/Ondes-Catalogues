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
    scan_municipal_page, _safe_url,
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
MAX_OA_UNVERIFIED_URLS = 500  # finite storage budget, NOT a source allowlist


def _blank(status):
    return {
        "schema": SCHEMA, "status": status,
        "municipality_from_live_oa_not_registry": False,
        "municipal_origins_verified_by_dila": 0,
        "municipal_homepages_checked": 0,
        "municipal_homepages_unavailable": 0,
        "source_links_found_in_pages": 0,
        "private_link_reports": [],
        "private_unverified_oa_web_leads": [],
        "oa_link_partition_required": False,
        "venue_alias_requires_independent_recheck": False,
        "organizer_domain_attested": False,
        "source_rights_reviewed": False,
        "events_independently_attested": False,
        "venue_geography_verified": False,
        "publisher_connected": False, "publication_ready": False,
        "approval_granted": False, "public_writes": 0,
    }


def _candidate_links_from_openagenda(event):
    """Collect HTTPS research links from public OA metadata, never attest them.

    No domain/organizer/venue/city vocabulary is used. These are documented
    structural OA fields, and the same unlisted HTTPS rules apply to ALL
    destinations. No destination is fetched or treated as official here.
    """
    found, seen = [], set()

    def collect(url, field):
        candidate = _safe_url(url)
        if not candidate or candidate in seen:
            return
        seen.add(candidate)
        found.append({
            "url": candidate, "source_field": field,
            "candidate_only": True, "owner_verified": False,
            "source_rights_reviewed": False,
            "publication_ready": False,
        })

    if isinstance(event, dict):
        collect(event.get("canonicalUrl"), "canonicalUrl")
        location = event.get("location")
        if isinstance(location, dict):
            collect(location.get("website"), "location.website")
            loc_links = location.get("links")
            if isinstance(loc_links, list):
                if len(loc_links) > MAX_OA_UNVERIFIED_URLS:
                    return [], True
                for item in loc_links:
                    if isinstance(item, dict):
                        collect(item.get("url") or item.get("value"),
                                "location.links")
                    else:
                        collect(item, "location.links")
        for field in ("registration", "links"):
            links = event.get(field)
            if not isinstance(links, list):
                continue
            if len(links) > MAX_OA_UNVERIFIED_URLS:
                return [], True
            for item in links:
                if isinstance(item, dict):
                    if field == "registration" and item.get("type") != "link":
                        continue
                    collect(item.get("value") or item.get("url"), field)
                else:
                    collect(item, field)
        if len(found) > MAX_OA_UNVERIFIED_URLS:
            return [], True
    return found, False


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


def _same_venue_label_contained_for_research(original, live):
    """Recognize an expanded ROOM LABEL as a lead, never as identity proof.

    "L'Étage" versus "Le Liberté // L'Étage" may be the same venue, but
    could also describe different rooms: only the next independent venue
    proof can resolve it. It never grants published or geocoded status.
    """
    if not isinstance(original, str) or not isinstance(live, str):
        return False
    a, b = norm(original), norm(live)
    if not a or a == b or len(a) < 5:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(a)
                     + r"(?![a-z0-9])", b) is not None


def _same_exact_sessions_ignoring_order(first, second):
    """OA session order is non-semantic; multiplicity and offsets are not."""
    if not isinstance(first, list) or not isinstance(second, list):
        return False
    def pairs(data):
        if any(type(x) is not dict or set(x) != {"begin", "end"}
               or not isinstance(x["begin"], str)
               or not isinstance(x["end"], str) for x in data):
            return None
        return sorted((x["begin"], x["end"]) for x in data)
    a, b = pairs(first), pairs(second)
    return a is not None and b is not None and bool(a) and a == b


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
            or type(event.get("uid")) is not int or event["uid"] != eid):
        return _blank("live_oa_event_uid_conflict")
    # The OA v2 detail API can express the same published/rescheduled status
    # either as an integer or as {"id": integer, "label": ...}. The original
    # national reader already accepts both. Never accept a missing, cancelled,
    # symbolic or otherwise untrusted status.
    status = event.get("status")
    if isinstance(status, dict):
        status = status.get("id")
    if (type(event.get("state")) is not int or event["state"] != 2
            or event.get("removed") is True
            or type(status) is not int or status not in (1, 2)):
        return _blank("live_oa_event_unpublished_or_cancelled")
    # An identity/timing conflict blocks admission, NOT independent
    # investigation. Preserve only safe, untrusted OA-linked HTTPS source
    # leads so the next private cycle can research the organizer's page.
    # Never infer organizer ownership, location or a published session here.
    source_leads, needs_partition = _candidate_links_from_openagenda(event)

    def held_with_leads(reason):
        held = _blank(reason)
        held["private_unverified_oa_web_leads"] = source_leads
        held["oa_link_partition_required"] = needs_partition
        return held

    if (not isinstance(event.get("location"), dict)
            or not _french_location(event["location"])):
        return _blank("live_oa_location_not_french_or_missing")
    if norm(_french_text(event, "title")) != norm(lead["title"]):
        return held_with_leads("live_oa_event_title_changed")
    loc = event["location"]
    city = loc.get("adminLevel4")
    venue = loc.get("name")
    if (not isinstance(city, str) or not 1 <= len(city) <= 120
            or not norm(city)
            or not isinstance(venue, str) or not 1 <= len(venue) <= 180
            or not norm(venue)):
        return held_with_leads("live_oa_city_or_venue_missing")
    if (isinstance(lead.get("city_unverified"), str)
            and norm(lead["city_unverified"]) != norm(city)):
        return held_with_leads("live_oa_city_changed")
    if (isinstance(lead.get("country_code_unverified"), str)
            and lead["country_code_unverified"] != loc.get("countryCode")):
        return held_with_leads("live_oa_country_changed")
    earlier_venue = lead.get("venue_unverified")
    venue_label_changed = (
        isinstance(earlier_venue, str)
        and norm(earlier_venue) != norm(venue))
    if (venue_label_changed
            and not _same_venue_label_contained_for_research(
                earlier_venue, venue)):
        return held_with_leads("live_oa_venue_changed")
    timings, _ = _time_sessions(event.get("timings"), today)
    if not _same_exact_sessions_ignoring_order(
            timings, lead["explicit_source_session_intervals"]):
        return held_with_leads("live_oa_explicit_session_changed")

    # A structurally valid OA website is a research lead only. Neither OA
    # nor its canonical link can certify ownership or the right to reuse.

    # This is a **query**, not a whitelist. Any new place name is eligible
    # for an independent authority lookup, including overseas municipalities.
    try:
        directory = directory_reader(city)
    except (OSError, ValueError, TypeError, KeyError, TimeoutError):
        return held_with_leads("dila_municipal_directory_unavailable")
    hosts = municipal_site_hosts(city, directory)
    if not hosts:
        return held_with_leads("dila_municipal_domain_not_verified")
    if len(hosts) > MAX_REFERENCE_URLS:
        return held_with_leads("dila_municipal_hosts_ambiguous")

    out = held_with_leads("municipal_homepage_source_research_only")
    # An expanded venue display label triggers research, NEVER admission.
    out["venue_alias_requires_independent_recheck"] = venue_label_changed
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
        "live_oa_event_uid_conflict",
        "live_oa_event_unpublished_or_cancelled",
        "live_oa_location_not_french_or_missing",
        "live_oa_event_title_changed",
        "live_oa_city_or_venue_changed",
        "live_oa_city_or_venue_missing",
        "live_oa_city_changed", "live_oa_venue_changed",
        "live_oa_country_changed",
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
