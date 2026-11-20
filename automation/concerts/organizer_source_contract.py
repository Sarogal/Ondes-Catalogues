"""Strict first-party concert-organizer authority, independent of artist roster.

A COMMITTED authority permits only a fetch of the organizer's own individual
event page. It does not certify a band, genre, show, location, source submitted
by discovery, or publication. Every event still needs fresh independent proof.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

MANIFEST = Path(__file__).with_name("organizer-official-sources.json")
SCHEMA = "grossesondes.concert.reviewed_organizer_sources.v1"
FIELDS = frozenset({
    "id", "name", "url", "host", "eventPathPrefix", "enabled",
    "checkedAt", "officialEvidenceUrl", "notes",
})
ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
HOST = re.compile(r"(?:[a-z0-9-]+\.)+[a-z]{2,24}\Z")
PREFIX = re.compile(r"/(?:[a-z0-9-]{2,45}/){1,3}\Z")
DETAIL = re.compile(r"[a-z0-9](?:[a-z0-9-]{1,158}[a-z0-9])?/?\Z")


def _require(condition, reason):
    if not condition:
        raise ValueError("Concert organizer authority: " + reason)


def _url(value):
    _require(isinstance(value, str) and len(value) <= 2048,
             "invalid HTTPS URL")
    try:
        uri = urlsplit(value)
        _require(uri.scheme == "https" and HOST.fullmatch(uri.hostname or "")
                 and uri.port is None and not uri.username and not uri.password
                 and not uri.query and not uri.fragment and bool(uri.path),
                 "unreviewed or unsafe authority URL")
        return uri
    except (TypeError, ValueError):
        raise ValueError("Concert organizer authority: malformed URL")


def read_sources(path=MANIFEST):
    content = json.loads(Path(path).read_text(encoding="utf-8"))
    _require(isinstance(content, dict) and set(content) == {"schema", "policy", "sources"}
             and content["schema"] == SCHEMA and isinstance(content["policy"], str),
             "authority manifest invalid")
    rows = content.get("sources")
    _require(isinstance(rows, list) and 1 <= len(rows) <= 200,
             "authority source list invalid")
    known_ids, known_urls = set(), set()
    for row in rows:
        _require(isinstance(row, dict) and set(row) == FIELDS,
                 "authority source structure invalid")
        _require(isinstance(row["id"], str) and ID.fullmatch(row["id"])
                 and isinstance(row["name"], str)
                 and 3 <= len(row["name"].strip()) <= 120
                 and type(row["enabled"]) is bool
                 and isinstance(row["notes"], str)
                 and len(row["notes"]) <= 800,
                 "authority source identity invalid")
        host = row["host"]
        prefix = row["eventPathPrefix"]
        _require(isinstance(host, str) and HOST.fullmatch(host)
                 and isinstance(prefix, str) and PREFIX.fullmatch(prefix)
                 and row["url"] == "https://" + host + prefix,
                 "authority host and path scope invalid")
        u = _url(row["url"])
        evidence = _url(row["officialEvidenceUrl"])
        _require(u.hostname == evidence.hostname
                 and evidence.path != u.path,
                 "organizer ownership evidence not first-party")
        try:
            checked = dt.date.fromisoformat(row["checkedAt"])
        except (TypeError, ValueError):
            raise ValueError("Concert organizer authority: invalid review date")
        _require(checked >= dt.date(2020, 1, 1),
                 "authority review date implausible")
        _require(row["id"] not in known_ids and row["url"] not in known_urls,
                 "duplicated organizer authority")
        known_ids.add(row["id"])
        known_urls.add(row["url"])
    return rows


def scoped_event_url(spec, value):
    """Exactly one official event slug within reviewed organizer scope."""
    if not isinstance(spec, dict):
        return False
    try:
        url = _url(value)
    except ValueError:
        return False
    if url.hostname != spec.get("host"):
        return False
    prefix = spec.get("eventPathPrefix")
    if not isinstance(prefix, str) or not url.path.startswith(prefix):
        return False
    return DETAIL.fullmatch(url.path[len(prefix):]) is not None


def trusted_organizer_lead(lead, *, sources=None):
    if not isinstance(lead, dict) or (
            lead.get("source") != "organizer_official_event_detail"
            or lead.get("sourceRole") != "organizer_official"
            or lead.get("sourceUrl") != lead.get("eventDetailUrl")
            or lead.get("artistId") is not None):
        return None
    rows = read_sources() if sources is None else sources
    matches = [entry for entry in rows
               if isinstance(entry, dict) and entry.get("enabled") is True
               and entry.get("id") == lead.get("organizerSourceId")
               and entry.get("url") == lead.get("sourcePage")
               and scoped_event_url(entry, lead.get("eventDetailUrl"))]
    return matches[0] if len(matches) == 1 else None
