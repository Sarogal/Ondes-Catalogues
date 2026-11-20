#!/usr/bin/env python3
"""National OpenAgenda agenda-index census, PRIVATE / read-only.

Uses the documented GET /v2/agendas API, unfiltered by place, category,
"official" flag or any hard-coded UID list. Pages are bounded and resumable.
An index entry is only a source DISCOVERY lead: no owner, organiser, licence,
event, venue, GPS, age or public access is verified here.
"""
import argparse
from collections import Counter
from datetime import date
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ptitesondes_openagenda_v2_direct_evidence import _valid_public_read_key

API = "https://api.openagenda.com/v2/agendas"
ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "ptitesondes.private_national_oa_index.v1"
STATE_SCHEMA = "ptitesondes.private_national_oa_index_cursor.v1"
MAX_BYTES = 450_000
MAX_CONFIG_BYTES = 60_000
PAGE_SIZE = 40
MAX_PAGES = 4
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,100}\Z")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def valid_cursor(after):
    return (isinstance(after, list) and len(after) == 2
            and all(type(n) is int and 0 < n < 10**15 for n in after))


def _validated_page(payload, size, old_cursor):
    if not isinstance(payload, dict):
        raise ValueError("invalid_oa_index_page")
    rows = payload.get("agendas")
    if not isinstance(rows, list) or len(rows) > size:
        raise ValueError("invalid_oa_index_rows")
    after = payload.get("after")
    if after is not None and (not valid_cursor(after)
                              or after == old_cursor
                              or not rows):
        raise ValueError("invalid_oa_index_cursor")
    clean = []
    known = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid_oa_index_item")
        uid, slug, name = row.get("uid"), row.get("slug"), row.get("title")
        if (type(uid) is not int or not 0 < uid < 10**12
                or uid in known
                or not isinstance(slug, str) or not SLUG.fullmatch(slug)
                or not isinstance(name, str) or not name.strip()
                or len(name) > 500):
            raise ValueError("invalid_oa_index_identity")
        known.add(uid)
        clean.append({"uid": uid, "slug": slug, "title": name})
    return clean, after


def read_index_page(public_read_key, after=None, *,
                    size=PAGE_SIZE, opener=None):
    """Public API reader with pinned origin, no redirects, bounded JSON."""
    if (not _valid_public_read_key(public_read_key)
            or type(size) is not int or not 1 <= size <= PAGE_SIZE
            or after is not None and not valid_cursor(after)):
        raise ValueError("invalid_oa_index_request")
    params = [("size", str(size))]
    if after is not None:
        params.extend([("after[]", str(n)) for n in after])
    url = API + "?" + urlencode(params)
    request = Request(url, headers={
        "key": public_read_key,
        "Accept": "application/json",
        "User-Agent": "PtitesOndesNationalOpenAgendaReadOnly/1.0",
    })
    fetch = opener or build_opener(NoRedirect()).open
    try:
        with fetch(request, timeout=20) as response:
            if response.status != 200 or response.geturl() != url:
                raise ValueError("unexpected_oa_index_endpoint")
            raw = response.read(MAX_BYTES + 1)
    except (OSError, TimeoutError):
        raise ValueError("oa_index_unavailable") from None
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("oa_index_size_invalid")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("oa_index_invalid_json") from None
    # No licence or organiser assertions are imported from this metadata.
    rows, cursor = _validated_page(payload, size, after)
    return {"agendas": rows, "after": cursor}


def scan_index_pages(configured, *, start_cursor=None, pages=MAX_PAGES,
                     reader=read_index_page, public_read_key=""):
    """Scan all types of agendas; return a private list of source leads.

    For each invocation, at most MAX_PAGES requests and PAGE_SIZE rows per
    request. The returned cursor lets a private scheduler cover France
    progressively without maintaining an exhaustive manually curated list.
    """
    if (not isinstance(configured, list)
            or any(type(uid) is not int or not 0 < uid < 10**12
                   for uid in configured)
            or len(set(configured)) != len(configured)
            or (start_cursor is not None and not valid_cursor(start_cursor))
            or type(pages) is not int or not 1 <= pages <= MAX_PAGES
            or not callable(reader)):
        raise ValueError("invalid_oa_index_scan")
    configured_set = set(configured)
    current = start_cursor
    visited = set()
    counts = Counter()
    candidates = []
    exhausted = False
    for _ in range(pages):
        payload = reader(public_read_key, current, size=PAGE_SIZE)
        rows, after = _validated_page(payload, PAGE_SIZE, current)
        counts["pages_read"] += 1
        for record in rows:
            uid = record["uid"]
            if uid in visited:
                raise ValueError("repeated_oa_agenda_in_cursor_scan")
            visited.add(uid)
            counts["public_agenda_identifiers_seen"] += 1
            if uid in configured_set:
                counts["configured_agenda_seen"] += 1
            else:
                counts["new_index_agendas_unverified"] += 1
                candidates.append({
                    "agenda_uid": uid,
                    "agenda_slug": record["slug"],
                    "agenda_title": record["title"],
                    "source_identity_only": True,
                    "owner_verified": False,
                    "organiser_verified": False,
                    "rights_reviewed": False,
                    "publisher_enabled": False,
                })
        if after is None:
            exhausted = True
            current = None
            break
        if tuple(after) in visited:
            # Defensive type distinction: an API cursor must not be an
            # untrusted event or agenda identity. Compare cursor pairs.
            raise ValueError("invalid_oa_index_cursor_reuse")
        current = after
    return {
        "schema": SCHEMA,
        "mode": "private_index_readonly_discovery_not_admission",
        "counts": dict(sorted(counts.items())),
        "new_agenda_candidates": candidates,
        "next_cursor": current,
        "index_pass_exhausted": exhausted,
        "owner_independently_verified": False,
        "publisher_connected": False,
        "publication_ready": False,
        "public_writes": 0,
    }


def _private_parent(path):
    parent = path.parent
    if (parent.is_symlink() or not parent.is_dir()
            or parent.resolve().is_relative_to(ROOT)
            or parent.stat().st_mode & 0o077):
        raise ValueError("private_directory_required")


def _private_input(path, max_bytes):
    _private_parent(path)
    if (path.is_symlink() or not path.is_file()
            or not 0 < path.stat().st_size <= max_bytes):
        raise ValueError("private_input_invalid")


def load_state(path):
    _private_parent(path)
    if not path.exists():
        return {"schema": STATE_SCHEMA, "after": None, "completed_passes": 0}
    _private_input(path, 1000)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(raw, dict)
            or set(raw) != {"schema", "after", "completed_passes"}
            or raw["schema"] != STATE_SCHEMA
            or raw["after"] is not None and not valid_cursor(raw["after"])
            or type(raw["completed_passes"]) is not int
            or not 0 <= raw["completed_passes"] < 10**9):
        raise ValueError("invalid_private_cursor_state")
    return raw


def _write_new_report(path, doc):
    _private_parent(path)
    if path.exists() or path.is_symlink():
        raise ValueError("private_report_must_be_new")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(doc, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def _write_state_atomic(path, state):
    _private_parent(path)
    if path.is_symlink():
        raise ValueError("private_state_symlink_forbidden")
    fd, temp = tempfile.mkstemp(prefix=".oa-index-state-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, sort_keys=True)
            stream.write("\n")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--private-source-config", type=Path, required=True)
    ap.add_argument("--private-cursor-state", type=Path, required=True)
    ap.add_argument("--output-private-report", type=Path, required=True)
    ap.add_argument("--execute-live", action="store_true")
    args = ap.parse_args()
    if (args.private_cursor_state.resolve() == args.output_private_report.resolve()
            or args.private_source_config.resolve() in (
                args.private_cursor_state.resolve(),
                args.output_private_report.resolve())):
        raise ValueError("private_paths_must_be_distinct")
    _private_input(args.private_source_config, MAX_CONFIG_BYTES)
    cfg = json.loads(args.private_source_config.read_text(encoding="utf-8"))
    if (not isinstance(cfg, dict)
            or cfg.get("schema") != "ptitesondes.sources.v1"
            or not isinstance(cfg.get("openagenda_agendas"), list)):
        raise ValueError("private_sources_invalid")
    state = load_state(args.private_cursor_state)
    _private_parent(args.output_private_report)
    if not args.execute_live:
        print(json.dumps({
            "mode": "dry_run", "configured_agendas": len(cfg["openagenda_agendas"]),
            "cursor_present": state["after"] is not None,
            "public_writes": 0,
        }))
        return
    key = os.environ.get("OPENAGENDA_READ_KEY", "")
    result = scan_index_pages(
        cfg["openagenda_agendas"], start_cursor=state["after"],
        public_read_key=key)
    next_state = {
        "schema": STATE_SCHEMA,
        "after": result["next_cursor"],
        "completed_passes": state["completed_passes"] + int(
            result["index_pass_exhausted"]),
    }
    _write_new_report(args.output_private_report, result)
    _write_state_atomic(args.private_cursor_state, next_state)
    # Only counts in stdout; metadata and cursors stay in the private dir.
    print(json.dumps({
        "mode": result["mode"], "counts": result["counts"],
        "completed_passes": next_state["completed_passes"],
        "index_pass_exhausted": result["index_pass_exhausted"],
        "public_writes": 0,
    }))


if __name__ == "__main__":
    main()
