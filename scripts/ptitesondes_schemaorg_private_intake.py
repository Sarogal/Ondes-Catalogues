#!/usr/bin/env python3
"""Schema.org -> PRIVATE discovery hints, not validated HTML sessions.

A separately committed institutional policy registry fixes the exact index,
host and child path; a second committed mapping fixes the territory timezone.
The collector never chooses a URL, host, local clock offset or source policy.
Even a true source URL with structured JSON-LD is only an unverified HINT.
It cannot enter the HTML-reviewed queue or any publication patch.
"""
import argparse
from datetime import date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from proof import norm
from ptitesondes_family_national_scope import FAMILY_TYPES, LEGACY_MUSICAL
from ptitesondes_generic_schemaorg_event_discovery import (
    parse_schemaorg_private_event_hints, SOURCE_TIMEZONES,
)
from ptitesondes_official_html_index_discovery import discover_live_html_event_pages
from ptitesondes_openagenda_v2_geo_fetch import fetch_official_page
from ptitesondes_html_private_queue_cycle import (
    _private_target, _validated_manifest,
)
from ptitesondes_institutional_source_policy import _manifest_valid

SCHEMA = "ptitesondes.schemaorg_private_hints_queue.v1"
PINS_SCHEMA = "ptitesondes.schemaorg_trusted_source_timezones.v1"
PINS_FILE = (Path(__file__).resolve().parents[1]
             / "config/ptitesondes_schemaorg_source_timezones.json")
STORAGE = Path("automation-intake/ptitesondes/html-schemaorg-hints.json")
MAX_STORE_BYTES = 2_000_000
MAX_QUEUE = 4000
MAX_BATCH = 400
MAX_SOURCES_PER_RUN = 3
MAX_PAGES_PER_SOURCE = 20
CLOCK = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d\Z")
FIELDS = frozenset((
    "schema", "hint_id", "source_url", "title", "city", "venue",
    "date_start", "start_local", "category_hint_only", "source_format",
    "review_state", "first_seen", "last_seen", "observations",
    "first_party_visible_session_rechecked", "organizer_verified",
    "venue_geocoded", "rights_reviewed", "approved", "published",
))


def _text(value, limit=180):
    return (type(value) is str and 1 <= len(value) <= limit
            and value.strip() == value
            and re.search(r"[\x00-\x1f\x7f<>]", value) is None)


def _day(value):
    if type(value) is not str:
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _source_url(url, host=None, prefix=None):
    if not _text(url, 1000):
        return False
    try:
        p = urlsplit(url)
        return (p.scheme == "https" and p.hostname
                and p.username is None and p.password is None
                and p.port in (None, 443) and not p.query and not p.fragment
                and not p.path.startswith("//") and ".." not in p.path
                and "%" not in p.path
                and (host is None or p.hostname == host)
                and (prefix is None or p.path.startswith(prefix)))
    except ValueError:
        return False


def _hint_id(row):
    identity = (
        row["source_url"], norm(row["title"]), norm(row["city"]),
        norm(row["venue"]), row["date_start"], row["start_local"],
    )
    digest = hashlib.sha256(json.dumps(
        identity, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()[:32]
    return "schemaorg-hint-" + digest


def _validate_hint(item):
    if (type(item) is not dict or set(item) != FIELDS
            or item.get("schema") != SCHEMA
            or item.get("review_state") != "await_visible_first_party_confirmation"
            or item.get("first_party_visible_session_rechecked") is not False
            or item.get("organizer_verified") is not False
            or item.get("venue_geocoded") is not False
            or item.get("rights_reviewed") is not False
            or item.get("approved") is not False
            or item.get("published") is not False
            or item.get("source_format") != "schema_org_jsonld"
            or not _source_url(item.get("source_url"))
            or not all(_text(item.get(k), lim) for k, lim in (
                ("title", 180), ("city", 120), ("venue", 160)))
            or not _day(item.get("date_start"))
            or not _day(item.get("first_seen"))
            or not _day(item.get("last_seen"))
            or item["first_seen"] > item["last_seen"]
            or type(item.get("start_local")) is not str
            or not CLOCK.fullmatch(item["start_local"])
            or (item.get("category_hint_only") is not None
                and (item["category_hint_only"] not in FAMILY_TYPES
                     or item["category_hint_only"] in LEGACY_MUSICAL))
            or type(item.get("observations")) is not int
            or not 1 <= item["observations"] <= 10**8
            or item.get("hint_id") != _hint_id(item)):
        raise ValueError("invalid_schemaorg_hint_record")


def _from_lead(lead, today, previous=None):
    if (type(lead) is not dict
            or lead.get("approved") is not False
            or lead.get("published") is not False
            or lead.get("official_session_independently_proved") is not False
            or lead.get("organizer_independently_attested") is not False):
        raise ValueError("schemaorg_claim_not_proof")
    row = {
        "schema": SCHEMA,
        "source_url": lead.get("source_url"), "title": lead.get("title"),
        "city": lead.get("city"), "venue": lead.get("venue"),
        "date_start": lead.get("date_start"),
        "start_local": lead.get("start_local"),
        "category_hint_only": lead.get("category_hint_only"),
        "source_format": "schema_org_jsonld",
        "review_state": "await_visible_first_party_confirmation",
        "first_seen": previous["first_seen"] if previous else today.isoformat(),
        "last_seen": today.isoformat(),
        "observations": min(previous["observations"] + 1, 10**8)
        if previous else 1,
        "first_party_visible_session_rechecked": False,
        "organizer_verified": False, "venue_geocoded": False,
        "rights_reviewed": False, "approved": False, "published": False,
    }
    if not _day(row["date_start"]) or row["date_start"] < today.isoformat():
        raise ValueError("schemaorg_hint_not_future")
    # Every review key includes exact day AND local clock, never a date range.
    if not all(_text(row.get(k), lim) for k, lim in (
            ("source_url", 1000), ("title", 180),
            ("city", 120), ("venue", 160))):
        raise ValueError("schemaorg_hint_not_factual")
    row["hint_id"] = _hint_id(row)
    _validate_hint(row)
    return row


def reconcile_schemaorg_hints(existing, incoming, today):
    """Conserve vetted private claims and returns anonymous counts."""
    if (type(today) is not date or type(existing) is not list
            or type(incoming) is not list or len(existing) > MAX_QUEUE
            or len(incoming) > MAX_BATCH):
        raise ValueError("schemaorg_reconcile_bad_input")
    stored = {}
    for item in existing:
        _validate_hint(item)
        if item["hint_id"] in stored:
            raise ValueError("schemaorg_duplicate_stored_id")
        stored[item["hint_id"]] = dict(item)
    counts = {
        "schema": SCHEMA, "incoming_hints": len(incoming),
        "existing_hints": len(stored), "new_hints": 0,
        "reobserved_hints": 0, "malformed_hints_held": 0,
        "expired_hints_archived": 0, "total_hints": 0,
        "unclassified_hints": 0,
        "public_writes": 0, "publisher_connected": False,
        "publication_ready": False, "approved": False,
    }
    # Archive only records whose event date has *already* passed. These
    # cannot appear as new upcoming outings. Reports are only counts.
    for key in list(stored):
        if stored[key]["date_start"] < today.isoformat():
            del stored[key]
            counts["expired_hints_archived"] += 1
    seen = set()
    for lead in incoming:
        try:
            if type(lead) is not dict:
                raise ValueError("invalid_hint")
            row = _from_lead(lead, today)
            rid = row["hint_id"]
            if rid in seen:
                continue
            seen.add(rid)
            previous = stored.get(rid)
            row = _from_lead(lead, today, previous)
            if previous is None:
                if len(stored) >= MAX_QUEUE:
                    raise ValueError("schemaorg_private_queue_capacity")
                counts["new_hints"] += 1
            else:
                counts["reobserved_hints"] += 1
            stored[rid] = row
        except (ValueError, TypeError, KeyError, AttributeError):
            counts["malformed_hints_held"] += 1
    out = sorted(stored.values(), key=lambda r: r["hint_id"])
    counts["total_hints"] = len(out)
    counts["unclassified_hints"] = sum(
        r["category_hint_only"] is None for r in out)
    return {"queue": out, "report": counts}


def curated_schemaorg_sources(manifest, pins):
    """Any independently registered site with a reviewed timezone qualifies.

    No city allowlist or event-specific branch. No source from a candidate,
    feed, title or fetched JSON-LD can register itself.
    """
    if (not _manifest_valid(manifest)
            or type(pins) is not dict
            or set(pins) != {"schema", "entries"}
            or pins["schema"] != PINS_SCHEMA
            or type(pins["entries"]) is not list
            or len(pins["entries"]) > 300):
        raise ValueError("schemaorg_pins_invalid")
    by_id = {}
    for pin in pins["entries"]:
        if (type(pin) is not dict
                or set(pin) != {"source_id", "timezone"}
                or not _text(pin.get("source_id"), 100)
                or type(pin.get("timezone")) is not str
                or pin["timezone"] not in SOURCE_TIMEZONES
                or pin["source_id"] in by_id):
            raise ValueError("schemaorg_pin_invalid")
        by_id[pin["source_id"]] = pin["timezone"]
    manifest_ids = {e["source_id"] for e in manifest["entries"]}
    if not set(by_id) <= manifest_ids:
        raise ValueError("schemaorg_pin_unknown_institution")
    return [dict(entry, timezone=by_id[entry["source_id"]])
            for entry in manifest["entries"]
            if entry["source_id"] in by_id
            and entry["reuse_policy_state"] != "restricted_do_not_reuse"]


def _validate_pins():
    if not PINS_FILE.is_file() or PINS_FILE.stat().st_size > 30_000:
        raise ValueError("schemaorg_pins_unavailable")
    try:
        return json.loads(PINS_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise ValueError("schemaorg_pins_invalid") from None


def sample_registered_schemaorg_source(
        source, today, *, page_limit=12, batch=0,
        discoverer=discover_live_html_event_pages,
        page_reader=fetch_official_page,
        parser=parse_schemaorg_private_event_hints):
    """Actual bounded index + same-host child GET, PRIVATE hints only."""
    if (type(source) is not dict or type(today) is not date
            or type(page_limit) is not int
            or not 1 <= page_limit <= MAX_PAGES_PER_SOURCE
            or type(batch) is not int or batch < 0
            or type(source.get("timezone")) is not str
            or source["timezone"] not in SOURCE_TIMEZONES
            or not _source_url(source.get("index_url"),
                               source.get("approved_host"))):
        raise ValueError("schemaorg_source_invalid")
    pin = {"approved_host": source["approved_host"],
           "exact_index_url": source["index_url"]}
    report = {
        "source_index_available": False,
        "same_host_links": 0, "child_pages_read": 0,
        "pages_unavailable": 0, "private_hints_observed": 0,
    }
    discover = discoverer(pin)
    if (type(discover) is not dict
            or discover.get("stage") != "routing_suggestions_only"
            or type(discover.get("private_routing_proposals")) is not list):
        return {"hints": [], "report": report}
    report["source_index_available"] = True
    candidates = []
    for item in discover["private_routing_proposals"]:
        if type(item) is not dict:
            continue
        url = item.get("url")
        if (_source_url(url, source["approved_host"],
                        source["child_prefix"])
                and item.get("approved") is False):
            candidates.append(url)
    children = sorted(set(candidates))
    report["same_host_links"] = len(children)
    if children:
        # Rotating window avoids recurring first-page bias. No numeric
        # suffix, path naming or title supplies event identity.
        start = (batch * page_limit) % len(children)
        selected = (children + children)[start:start + min(page_limit, len(children))]
    else:
        selected = []
    hints = []
    for url in selected:
        try:
            page = page_reader({
                "approved_host": source["approved_host"], "exact_url": url,
            })
            result = parser(
                page, {"approved_host": source["approved_host"],
                       "exact_child_url": url,
                       "child_prefix": source["child_prefix"],
                       "timezone": source["timezone"]}, today)
            if (type(result) is not dict
                    or result.get("publication_ready") is not False
                    or result.get("approved") is not False
                    or result.get("public_writes") != 0
                    or type(result.get("private_leads")) is not list):
                raise ValueError("schemaorg_parser_unsafe")
            # The extracted source_url must still equal independently
            # selected child page. This is not event attestation.
            if any(type(l) is not dict or l.get("source_url") != url
                   for l in result["private_leads"]):
                raise ValueError("schemaorg_wrong_child_source")
            if len(hints) + len(result["private_leads"]) > MAX_BATCH:
                raise ValueError("schemaorg_source_batch_overflow")
            hints.extend(result["private_leads"])
            report["child_pages_read"] += 1
        except (OSError, ValueError, TypeError, KeyError, TimeoutError):
            report["pages_unavailable"] += 1
    report["private_hints_observed"] = len(hints)
    return {"hints": hints, "report": report}


def run_schemaorg_cycle(
        existing, now, *, manifest=None, pins=None, source_batch=0,
        max_sources=2, page_limit=12, source_reader=sample_registered_schemaorg_source):
    """Bounded global round-robin; no access to private repo or publish."""
    if (type(now) is not datetime or now.tzinfo is None
            or now.utcoffset() is None
            or type(source_batch) is not int or source_batch < 0
            or type(max_sources) is not int
            or not 1 <= max_sources <= MAX_SOURCES_PER_RUN
            or type(page_limit) is not int
            or not 1 <= page_limit <= MAX_PAGES_PER_SOURCE):
        raise ValueError("schemaorg_bad_cycle")
    manifest = _validated_manifest() if manifest is None else manifest
    pins = _validate_pins() if pins is None else pins
    sources = curated_schemaorg_sources(manifest, pins)
    total_batches = max(1, (len(sources) + max_sources - 1) // max_sources)
    selected_batch = source_batch % total_batches
    selected = sources[selected_batch * max_sources:(selected_batch + 1) * max_sources]
    # Allow an overseas local day behind metropolitan time. Source readers
    # use their own independently pinned timezone for exact future dates.
    # Retain the prior UTC day rather than prematurely expiring a Guadeloupe
    # evening session while it is already tomorrow in mainland France.
    today = (now.astimezone(ZoneInfo("UTC")) - timedelta(days=1)).date()
    current = reconcile_schemaorg_hints(existing, [], today)["queue"]
    counts = {
        "schema": SCHEMA, "registered_sources": len(manifest["entries"]),
        "independently_pinned_sources": len(sources),
        "source_batches_total": total_batches,
        "sources_selected": len(selected), "sources_sampled": 0,
        "sources_unavailable": 0, "pages_read": 0,
        "private_hints_observed": 0, "new_private_hints": 0,
        "unclassified_private_hints": 0, "total_private_hints": 0,
        "public_writes": 0, "publisher_connected": False,
        "publication_ready": False, "approved": False,
    }
    for source in selected:
        local_day = now.astimezone(ZoneInfo(source["timezone"])).date()
        try:
            batch = source_reader(
                source, local_day, page_limit=page_limit,
                batch=now.toordinal() * 4 + now.hour // 6)
            if (type(batch) is not dict or type(batch.get("hints")) is not list
                    or type(batch.get("report")) is not dict
                    or type(batch["report"].get("child_pages_read")) is not int
                    or batch["report"]["child_pages_read"] < 1):
                raise ValueError("schemaorg_source_empty")
            # Never carry a source's injected permission status into queue.
            for item in batch["hints"]:
                if not _source_url(
                        item.get("source_url") if type(item) is dict else None,
                        source["approved_host"], source["child_prefix"]):
                    raise ValueError("schemaorg_source_scope_violation")
            merged = reconcile_schemaorg_hints(current, batch["hints"], today)
            current = merged["queue"]
            counts["sources_sampled"] += 1
            counts["pages_read"] += batch["report"]["child_pages_read"]
            counts["private_hints_observed"] += len(batch["hints"])
            counts["new_private_hints"] += merged["report"]["new_hints"]
        except (OSError, ValueError, KeyError, TypeError, TimeoutError):
            counts["sources_unavailable"] += 1
    counts["unclassified_private_hints"] = sum(
        x["category_hint_only"] is None for x in current)
    counts["total_private_hints"] = len(current)
    return {"queue": current, "report": counts}


def _file(root):
    """Path is derived from an authenticated, branch-checked private repo."""
    target = _private_target(root)
    return target.parents[2] / STORAGE


def _read_private(path):
    if not path.exists():
        return []
    if (path.is_symlink() or not path.is_file()
            or path.stat().st_size > MAX_STORE_BYTES):
        raise ValueError("invalid_existing_private_hints")
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise ValueError("invalid_existing_private_hints") from None
    return reconcile_schemaorg_hints(rows, [], date(2000, 1, 1))["queue"]


def _stage_private(path, rows):
    if path.is_symlink():
        raise ValueError("schemaorg_private_path_symlink")
    reconcile_schemaorg_hints(rows, [], date(2000, 1, 1))
    body = (json.dumps(rows, ensure_ascii=False, indent=2, allow_nan=False)
            + "\n").encode("utf-8")
    if len(body) > MAX_STORE_BYTES:
        raise ValueError("schemaorg_private_file_too_large")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".schemaorg-hints-")
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(body)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--state-checkout", type=Path, required=True)
    p.add_argument("--mode", choices=("preview", "stage"), default="preview")
    p.add_argument("--source-batch", type=int, default=0)
    p.add_argument("--page-limit", type=int, default=12)
    args = p.parse_args()
    try:
        dest = _file(args.state_checkout)
        existing = _read_private(dest)
        outcome = run_schemaorg_cycle(
            existing, datetime.now(ZoneInfo("Europe/Paris")),
            source_batch=args.source_batch, page_limit=args.page_limit)
        if args.mode == "stage":
            _stage_private(dest, outcome["queue"])
        print(json.dumps(dict(outcome["report"], mode=args.mode),
                         ensure_ascii=False, sort_keys=True))
    except (ValueError, TypeError, KeyError, OSError, UnicodeError):
        raise SystemExit("PRIVATE_SCHEMAORG_INTAKE_FAILED_CLOSED") from None


if __name__ == "__main__":
    main()
