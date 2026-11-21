"""Read-only public catalogue drift check for P'tites Ondes.

The previously checked-out docs JSON is not proof of the *served* GitHub
Pages content. Fetch the fixed live URL, verify shape and compare canonical
hashes without exposing event payloads, credentials or arbitrary URLs.

This diagnostic never publishes, signs evidence, approves a source or
grants the right to use a candidate; freshness is an indicator about the
last DATA content change, not proof that a scheduled workflow did/did not run.
"""
from datetime import datetime, timedelta
import json
from pathlib import Path
from urllib.request import Request, HTTPRedirectHandler, build_opener
from zoneinfo import ZoneInfo

from merge_policy import byid
from ptitesondes_nonmusical_catalogue_shape_dryrun import _hash

SCHEMA = "ptitesondes.public_catalogue_live_drift_readonly.v1"
LIVE_URL = "https://sarogal.github.io/Ondes-Catalogues/ptitesondes/sorties.json"
LOCAL_PATH = Path(__file__).resolve().parents[1] / "docs/ptitesondes/sorties.json"
MAX_BYTES = 8_000_000
MAX_AGE_HOURS = 24
TIMEOUT = 20


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _strict_json(source):
    if isinstance(source, bytes):
        text = source.decode("utf-8-sig")
    elif isinstance(source, str):
        text = source
    else:
        raise ValueError("invalid_json_input")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("oversized_document")
    def fail_constant(value):
        raise ValueError("invalid_number")
    doc = json.loads(text, parse_constant=fail_constant)
    if not isinstance(doc, dict):
        raise ValueError("not_catalogue")
    byid(doc)
    if not isinstance(doc.get("updated_at"), str):
        raise ValueError("no_update_time")
    moment = datetime.fromisoformat(doc["updated_at"])
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("naive_catalogue_timestamp")
    if not 2000 <= moment.year <= 2100:
        raise ValueError("invalid_timestamp_year")
    return doc, moment


def _out(stage):
    return {
        "schema": SCHEMA,
        "stage": stage,
        "live_event_count": 0,
        "local_event_count": 0,
        "live_data_timestamp": None,
        "same_data_as_checked_out_repository": False,
        "data_last_changed_within_24h": False,
        "data_age_is_not_workflow_run_proof": True,
        "live_fetch_does_not_grant_publisher_permission": True,
        "catalogue_event_fields_in_output": False,
        "publisher_connected": False,
        "rights_reviewed": False,
        "approval_granted": False,
        "publication_ready": False,
        "public_writes": 0,
    }


def _read_live(reader=None):
    """GET exact pinned HTTPS site, bounded bytes, no redirects or credentials."""
    req = Request(LIVE_URL, headers={
        "Accept": "application/json",
        "User-Agent": "PtitesOndesCatalogueDriftAudit/1.0",
    })
    get = reader or build_opener(_NoRedirect()).open
    try:
        with get(req, timeout=TIMEOUT) as reply:
            if reply.status != 200 or reply.geturl() != LIVE_URL:
                raise ValueError("live_redirect_or_http_status")
            media = (reply.headers.get("Content-Type", "")
                     .split(";", 1)[0].strip().lower())
            if media not in ("application/json", "text/json"):
                raise ValueError("live_not_json")
            raw = reply.read(MAX_BYTES + 1)
    except Exception:
        raise ValueError("live_catalogue_unavailable") from None
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("live_catalogue_invalid_size")
    return raw


def check_served_catalogue(now, *, reader=None, local_file=LOCAL_PATH):
    """Use injected reader/path only in tests. Production URL stays fixed."""
    out = _out("catalogue_not_verified")
    if (not isinstance(now, datetime) or now.tzinfo is None
            or now.utcoffset() is None):
        return _out("invalid_clock")
    try:
        path = Path(local_file)
        if path.stat().st_size > MAX_BYTES:
            raise ValueError("repo_catalogue_oversized")
        local, _ = _strict_json(path.read_bytes())
    except (OSError, UnicodeError, TypeError, ValueError, OverflowError):
        return _out("checked_out_reference_invalid")
    out["local_event_count"] = len(local["events"])
    try:
        live, changed = _strict_json(_read_live(reader=reader))
    except (OSError, UnicodeError, TypeError, ValueError, OverflowError):
        return dict(out, stage="live_catalogue_unavailable_or_invalid")
    out["live_event_count"] = len(live["events"])
    out["live_data_timestamp"] = changed.isoformat()
    # Allow no future clock skew to accidentally mark a source "fresh".
    age = now.astimezone(ZoneInfo("UTC")) - changed.astimezone(ZoneInfo("UTC"))
    fresh = timedelta(0) <= age <= timedelta(hours=MAX_AGE_HOURS)
    equal = _hash(local) == _hash(live)
    out["data_last_changed_within_24h"] = fresh
    out["same_data_as_checked_out_repository"] = equal
    out["stage"] = (
        "live_catalogue_differs_from_repository"
        if not equal else
        "matching_data_last_updated_over_24h_ago"
        if not fresh else
        "matching_live_catalogue_recent_data_change"
    )
    return out


if __name__ == "__main__":
    print(json.dumps(check_served_catalogue(
        datetime.now(ZoneInfo("Europe/Paris"))), ensure_ascii=False,
        sort_keys=True))
