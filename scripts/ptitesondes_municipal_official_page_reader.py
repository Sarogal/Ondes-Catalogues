#!/usr/bin/env python3
"""Read official municipal venue pages discovered from OpenAgenda + DILA.

LIVE READ-ONLY and opt-in. All providers have pinned origins: OpenAgenda's
public-read API, DILA official directory, and a single candidate municipal
website corroborated independently with DILA. No publisher, no Git writes.
"""
import json
import re
from collections import defaultdict
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlsplit

from proof import norm
from ptitesondes_dila_municipal_domains import (
    fetch_dila, verified_oa_location_website, oa_location_identity_matches,
    municipal_site_hosts,
)
from ptitesondes_openagenda_v2_direct_evidence import (
    _source_parts, read_direct_agenda_v2, read_direct_v2,
)
from ptitesondes_candidate_promotion import api_record
from ptitesondes_ods_oa_source_binding import (
    ods_source_parts, ods_immutable_source_match, ods_origin_agenda_uid,
    independently_confirm_ods_agenda,
)

MAX_LEADS = 4000
MAX_AGENDAS = 60
MAX_UIDS_PER_VENUE = 3
MAX_HTML_BYTES = 350_000
MAX_HTML_URL = 600


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_official_html(url, opener=None):
    """Bounded HTML read. Caller MUST DILA-confirm URL before invoking."""
    if (not isinstance(url, str) or not 1 <= len(url) <= MAX_HTML_URL
            or not url.startswith("https://")):
        raise ValueError("invalid_official_page_url")
    get = opener or build_opener(NoRedirect()).open
    with get(Request(url, headers={
        "Accept": "text/html,application/xhtml+xml",
        "User-Agent": "PtitesOndesMunicipalVenueReadOnly/1.0",
    }), timeout=20) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("official_page_redirect_or_non_200")
        content_type = response.headers.get("Content-Type", "")
        if not isinstance(content_type, str) or not (
                content_type.lower().startswith("text/html")
                or content_type.lower().startswith("application/xhtml+xml")):
            raise ValueError("official_page_not_html")
        body = response.read(MAX_HTML_BYTES + 1)
    if len(body) > MAX_HTML_BYTES or not body:
        raise ValueError("official_page_oversized_or_empty")
    # Avoid content-based fallback to arbitrary network encodings.
    charset = "latin-1" if "iso-8859-1" in content_type.lower() else "utf-8"
    return body.decode(charset, errors="replace")


class MunicipalOfficialPageReader:
    """Provide `official_page_get` and `dila_directory_get` callbacks.

    Strong requirements: every source agenda UID must be from the separately
    reviewed private configuration; every event UID must bind exactly to its
    first-party OA page in the private backlog; DILA must independently
    confirm the site hostname. Any doubt returns no page.
    """

    def __init__(self, leads, agenda_uids, public_read_key, *,
                 agenda_reader=read_direct_agenda_v2,
                 event_reader=read_direct_v2,
                 directory_reader=fetch_dila,
                 html_reader=read_official_html,
                 ods_reader=api_record):
        if (not isinstance(leads, list) or len(leads) > MAX_LEADS
                or not isinstance(agenda_uids, list)
                or len(agenda_uids) > MAX_AGENDAS
                or not all(type(x) is int and 0 < x < 10**13 for x in agenda_uids)
                or len(set(agenda_uids)) != len(agenda_uids)
                or not isinstance(public_read_key, str) or not public_read_key
                or not all(callable(v) for v in (
                    agenda_reader, event_reader, directory_reader,
                    html_reader, ods_reader))):
            raise ValueError("invalid_private_reader_configuration")
        self.key = public_read_key
        self.agenda_uids = tuple(agenda_uids)
        self.agenda_reader = agenda_reader
        self.event_reader = event_reader
        self.ods_reader = ods_reader
        self.directory_reader = directory_reader
        self.html_reader = html_reader
        self.directory_cache = {}
        self.page_cache = {}
        self.agenda_map = None
        self.dynamic_agenda_slug_map = {}
        self.source_index = defaultdict(set)
        for row in leads:
            if not isinstance(row, dict):
                continue
            source_url = row.get("source_url")
            kind = row.get("collector")
            uid = row.get("external_id")
            if (not isinstance(uid, str)
                    or not re.fullmatch(r"[0-9]{1,12}", uid)):
                continue
            if kind == "openagenda-v2":
                parts = _source_parts(source_url)
                slug = parts[0] if parts is not None and parts[1] == uid else None
            elif kind == "opendatasoft-index":
                # ODS canonical URLs usually contain human readable event
                # slugs, not immutable UIDs; binding to UID happens ONLY
                # after a separate exact-UID ODS record lookup.
                slug = ods_source_parts(source_url)
            else:
                continue
            city, venue = norm(row.get("city")), norm(row.get("venue"))
            if city and venue and slug is not None:
                self.source_index[(city, venue)].add(
                    (slug, uid, kind, source_url))

    def _agendas(self):
        if self.agenda_map is None:
            current = {}
            ambiguous = set()
            for uid in self.agenda_uids:
                try:
                    doc = self.agenda_reader(uid, self.key)
                    if (not isinstance(doc, dict) or str(doc.get("uid")) != str(uid)
                            or not isinstance(doc.get("slug"), str)
                            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,100}",
                                                doc["slug"])):
                        continue
                    slug = doc["slug"]
                    if slug in current:
                        ambiguous.add(slug)
                    else:
                        current[slug] = uid
                except (OSError, ValueError, TypeError, KeyError, TimeoutError):
                    continue
            for slug in ambiguous:
                current.pop(slug, None)
            self.agenda_map = current
        return self.agenda_map

    def dila_directory_get(self, city):
        # Error must propagate to the caller's fail-closed handler; cache
        # only successful complete documents, never absence or timeouts.
        key = norm(city)
        if not key:
            raise ValueError("invalid_city")
        if key not in self.directory_cache:
            self.directory_cache[key] = self.directory_reader(city)
        return self.directory_cache[key]

    def source_record_for_group(self, group, uid):
        """Return a UID-bound, *untrusted* search center from OA or ODS.

        This method does NOT prove GPS or authorize any publication.
        In particular, a direct OA lead is not forced through the ODS mirror.
        Ambiguous slugs, conflicting collector entries, unpublished events,
        and missing/invalid coordinates fail closed.
        """
        import math
        if (not isinstance(group, dict)
                or not isinstance(uid, str)
                or not re.fullmatch(r"[0-9]{1,12}", uid)
                or not isinstance(group.get("uids"), list)
                or uid not in group["uids"]):
            raise ValueError("source_group_or_uid_invalid")
        city, venue = norm(group.get("city")), norm(group.get("venue"))
        if not city or not venue:
            raise ValueError("source_group_identity_invalid")
        options = {(slug, kind, source_url)
                   for slug, row_uid, kind, source_url
                   in self.source_index.get((city, venue), set())
                   if row_uid == uid}
        if len(options) != 1:
            raise ValueError("source_uid_origin_ambiguous_or_missing")
        slug, kind, source_url = next(iter(options))
        if kind == "opendatasoft-index":
            row = self.ods_reader(uid)
            if not ods_immutable_source_match(group, uid, source_url, row):
                raise ValueError("ods_source_identity_mismatch")
            return row
        if kind != "openagenda-v2":
            raise ValueError("unrecognized_source_collector")
        agenda_uid = self._agendas().get(slug)
        if agenda_uid is None:
            raise ValueError("oa_agenda_not_independently_bound")
        record = self.event_reader(agenda_uid, uid, self.key)
        if not oa_location_identity_matches(group, record):
            raise ValueError("oa_source_identity_mismatch")
        location = record["location"]
        lat, lon = location.get("latitude"), location.get("longitude")
        if (type(lat) not in (float, int) or type(lon) not in (float, int)
                or not math.isfinite(lat) or not math.isfinite(lon)
                or not -90 <= lat <= 90 or not -180 <= lon <= 180):
            raise ValueError("oa_source_coordinates_invalid")
        # Return the legacy shape expected by source_center(); the point is
        # still ONLY a search hint. Independent municipal + BAN checks remain.
        return {"uid": uid, "location_city": group["city"],
                "location_name": group["venue"],
                "location_coordinates": {"lat": lat, "lon": lon}}

    def official_page_get(self, group):
        """Return a DILA-approved website page and its HTML, or (None,None)."""
        if not isinstance(group, dict):
            return None, None
        city, venue = norm(group.get("city")), norm(group.get("venue"))
        options = sorted(self.source_index.get((city, venue), ()))
        if not options:
            return None, None
        ids = group.get("uids")
        if not isinstance(ids, list) or not ids:
            return None, None
        options = [(slug, uid, kind, url)
                   for slug, uid, kind, url in options if uid in ids]
        if not options:
            return None, None
        # High-volume venues have many independent dated occurrences.
        # Sample a bounded 3 UID identities, without pretending to have
        # checked every event. Per-session publication checks are separate.
        options = options[:MAX_UIDS_PER_VENUE]
        try:
            directory = self.dila_directory_get(group["city"])
        except (ValueError, OSError, KeyError, TypeError, TimeoutError):
            return None, None
        mapping = self._agendas()
        found = set()
        for slug, uid, kind, source_url in options:
            agenda_uid = mapping.get(slug)
            if kind == "opendatasoft-index":
                try:
                    ods = self.ods_reader(uid)
                    if not ods_immutable_source_match(
                            group, uid, source_url, ods):
                        return None, None
                except (ValueError, OSError, TypeError, KeyError, TimeoutError):
                    return None, None
                declared = ods_origin_agenda_uid(ods)
                if agenda_uid is not None:
                    # Curated agenda identity wins; ODS cannot contradict it.
                    if declared is not None and declared != agenda_uid:
                        return None, None
                else:
                    # Dynamic source discovery is allowed for place RESEARCH
                    # only, after double checking immutable agenda UID+slug
                    # against OpenAgenda's own API. This is NOT a venue
                    # owner/license attestation or publication permission.
                    if (declared is None
                            or declared in mapping.values()
                            or (slug in self.dynamic_agenda_slug_map
                                and self.dynamic_agenda_slug_map[slug]
                                != declared)
                            or any(s != slug and val == declared for s, val
                                   in self.dynamic_agenda_slug_map.items())):
                        return None, None
                    confirmed = self.dynamic_agenda_slug_map.get(slug)
                    if confirmed is None:
                        confirmed = independently_confirm_ods_agenda(
                            ods, slug, self.agenda_reader, self.key)
                        if confirmed is None:
                            return None, None
                        self.dynamic_agenda_slug_map[slug] = confirmed
                    agenda_uid = confirmed
            if agenda_uid is None:
                return None, None
            try:
                record = self.event_reader(agenda_uid, uid, self.key)
            except (ValueError, OSError, TypeError, KeyError, TimeoutError):
                return None, None
            if not oa_location_identity_matches(group, record):
                return None, None
            raw_website = record["location"].get("website")
            if raw_website in (None, ""):
                # An absent OA URL is not negative evidence. A DILA-proven
                # municipality root can still lead to the exact named place.
                continue
            website = verified_oa_location_website(group, record, directory)
            if website is None:
                # A *conflicting* declared URL must not silently fall back
                # to the city homepage and hide the contradiction.
                return None, None
            found.add(website)
        if len(found) > 1:
            return None, None
        if found:
            url = next(iter(found))
        else:
            homes = municipal_site_hosts(group["city"], directory)
            if len(homes) != 1:
                return None, None
            url = "https://" + next(iter(homes)) + "/"
        if url not in self.page_cache:
            try:
                self.page_cache[url] = self.html_reader(url)
            except (ValueError, OSError, TypeError, KeyError,
                    TimeoutError, UnicodeError):
                return None, None
        html = self.page_cache[url]
        # A municipality homepage sometimes mentions a venue but lacks its
        # exact address. Only a single visible, same-site, exact-name link
        # may lead to ONE extra municipal venue page (never free crawling).
        if urlsplit(url).path in ("", "/"):
            from ptitesondes_municipal_venue_link_discovery import (
                exact_named_venue_page,
            )
            target = exact_named_venue_page(
                group["venue"], url, html, group["city"], directory)
            if target is not None:
                if target not in self.page_cache:
                    try:
                        self.page_cache[target] = self.html_reader(target)
                    except (ValueError, OSError, TypeError, KeyError,
                            TimeoutError, UnicodeError):
                        return None, None
                return target, self.page_cache[target]
            if not found:
                # Missing OA location.website: an official homepage is
                # NOT a named venue page and cannot serve as a venue proof.
                return None, None
        return url, html
