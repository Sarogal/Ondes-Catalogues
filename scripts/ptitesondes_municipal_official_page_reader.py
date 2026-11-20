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

from proof import norm
from ptitesondes_dila_municipal_domains import (
    fetch_dila, verified_oa_location_website,
)
from ptitesondes_openagenda_v2_direct_evidence import (
    _source_parts, read_direct_agenda_v2, read_direct_v2,
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
                 html_reader=read_official_html):
        if (not isinstance(leads, list) or len(leads) > MAX_LEADS
                or not isinstance(agenda_uids, list)
                or len(agenda_uids) > MAX_AGENDAS
                or not all(type(x) is int and 0 < x < 10**13 for x in agenda_uids)
                or len(set(agenda_uids)) != len(agenda_uids)
                or not isinstance(public_read_key, str) or not public_read_key
                or not all(callable(v) for v in (
                    agenda_reader, event_reader, directory_reader, html_reader))):
            raise ValueError("invalid_private_reader_configuration")
        self.key = public_read_key
        self.agenda_uids = tuple(agenda_uids)
        self.agenda_reader = agenda_reader
        self.event_reader = event_reader
        self.directory_reader = directory_reader
        self.html_reader = html_reader
        self.directory_cache = {}
        self.page_cache = {}
        self.agenda_map = None
        self.source_index = defaultdict(set)
        for row in leads:
            if not isinstance(row, dict) or row.get("collector") != "openagenda-v2":
                continue
            parts = _source_parts(row.get("source_url"))
            if (parts is None
                    or not isinstance(row.get("external_id"), str)
                    or row["external_id"] != parts[1]
                    or not re.fullmatch(r"[0-9]{1,12}", row["external_id"])):
                continue
            city, venue = norm(row.get("city")), norm(row.get("venue"))
            if city and venue:
                self.source_index[(city, venue)].add((parts[0], parts[1]))

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

    def official_page_get(self, group):
        """Return a DILA-approved website page and its HTML, or (None,None)."""
        if not isinstance(group, dict):
            return None, None
        city, venue = norm(group.get("city")), norm(group.get("venue"))
        options = sorted(self.source_index.get((city, venue), ()))
        # Do not blindly pick one from conflicting or excessive sources.
        if not options or len(options) > MAX_UIDS_PER_VENUE:
            return None, None
        ids = group.get("uids")
        if not isinstance(ids, list) or not ids:
            return None, None
        options = [(slug, uid) for slug, uid in options if uid in ids]
        if not options or len(options) > MAX_UIDS_PER_VENUE:
            return None, None
        try:
            directory = self.dila_directory_get(group["city"])
        except (ValueError, OSError, KeyError, TypeError, TimeoutError):
            return None, None
        mapping = self._agendas()
        found = set()
        for slug, uid in options:
            agenda_uid = mapping.get(slug)
            if agenda_uid is None:
                return None, None
            try:
                record = self.event_reader(agenda_uid, uid, self.key)
            except (ValueError, OSError, TypeError, KeyError, TimeoutError):
                return None, None
            website = verified_oa_location_website(group, record, directory)
            if website is None:
                return None, None
            found.add(website)
        if len(found) != 1:
            return None, None
        url = next(iter(found))
        if url not in self.page_cache:
            try:
                self.page_cache[url] = self.html_reader(url)
            except (ValueError, OSError, TypeError, KeyError,
                    TimeoutError, UnicodeError):
                return None, None
        return url, self.page_cache[url]
