"""Fresh historical GPS correction rehearsal. No public writes.

The private rotation checkpoint is a queue hint, never a proof or patch.
Rebuild the exact group from the current catalogue, repeat geographic
research, then re-read each event's own structured first-party identity.
Only missing coordinates may be filled; existing valid points are untouched.
"""
import argparse
from datetime import date
from hashlib import sha256
import json
import re
from pathlib import Path

from proof import LD, walk, norm, meters
from ptitesondes_catalogue_geo_research import research_queue, point
from ptitesondes_catalogue_geo_rotation import identity, SCHEMA, write_state
from ptitesondes_catalogue_geo_proof_batch import research_group
from ptitesondes_unlisted_source_safe_recheck import read_unknown_https
from ptitesondes_dynamic_municipal_source_links import _safe_url
from ptitesondes_shared_venue_location_evidence import _coordinates

MAX_GROUPS = 3
MAX_EVENTS = 12
MAX_EVENTS_PER_GROUP = 4
PROGRESS_SCHEMA = "ptitesondes.historical_gps_correction_progress.v1"
MAX_HTML = 350000
MAX_AGE = 7
GEO_FIELDS = frozenset(("lat", "lng", "geo_precision", "geo_verified_at"))
ERRORS = (OSError, ValueError, KeyError, TypeError, TimeoutError, UnicodeError)


def digest(doc):
    return sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")).hexdigest()


def _same(a, b):
    return (isinstance(a, str) and isinstance(b, str)
            and bool(a.strip()) and norm(a) == norm(b))


def structured_event_identity(event, html):
    """Single exact dated structured Event with its named venue and city.

    No fuzzy title, unrelated footer, generic city or inferred date range.
    Unknown, cancelled, moved or conflicting records remain uncorrected.
    """
    if not isinstance(html, str) or not 30 <= len(html) <= MAX_HTML:
        return False
    parser = LD()
    try:
        parser.feed(html)
        parser.close()
        if not 1 <= len(parser.blocks) <= 20:
            return False
        matches = []
        for block in parser.blocks:
            for node in walk(json.loads(block)):
                types = node.get("@type", [])
                types = [types] if isinstance(types, str) else types
                if not isinstance(types, list) or not any(
                        isinstance(t, str) and t.lower().endswith("event")
                        for t in types):
                    continue
                if not _same(node.get("name"), event.get("title")):
                    continue
                start = str(node.get("startDate", ""))[:10]
                end = str(node.get("endDate", node.get("startDate", "")))[:10]
                if start != event.get("date_start") or end != event.get("date_end"):
                    continue
                date.fromisoformat(start)
                date.fromisoformat(end)
                status = node.get("eventStatus")
                if status not in (None, "EventScheduled", "https://schema.org/EventScheduled",
                                  "http://schema.org/EventScheduled"):
                    return False
                mode = node.get("eventAttendanceMode")
                if mode is not None and mode not in (
                        "OfflineEventAttendanceMode", "MixedEventAttendanceMode",
                        "https://schema.org/OfflineEventAttendanceMode",
                        "https://schema.org/MixedEventAttendanceMode"):
                    return False
                loc = node.get("location")
                if not isinstance(loc, dict) or not _same(loc.get("name"), event.get("venue")):
                    return False
                address = loc.get("address")
                if not isinstance(address, dict) or not _same(
                        address.get("addressLocality"), event.get("city")):
                    return False
                country = address.get("addressCountry")
                if country is not None and norm(country) not in ("fr", "france", "gp", "mq", "gf", "re", "yt"):
                    return False
                matches.append(node)
        return len(matches) == 1
    except ERRORS + (RecursionError, OverflowError):
        return False


def _witness(result, group):
    if (not isinstance(result, dict)
            or result.get("status") != "independent_venue_point_found"
            or result.get("publication_ready") is not False
            or result.get("event_identity_recheck_required") is not True
            or not _same(result.get("city"), group["city"])
            or not _same(result.get("venue"), group["venue"])):
        return None
    v = result.get("venue_point")
    if not isinstance(v, dict) or not _safe_url(v.get("official")):
        return None
    p = _coordinates((v.get("lat"), v.get("lng")))
    if p is None or p == (0, 0) or not isinstance(v.get("geo_source"), str) or not v["geo_source"].strip():
        return None
    return p, v["official"], v["geo_source"]


def _fifo(previous, current):
    current = list(current)
    allowed = set(current)
    retained = [key for key in previous if key in allowed]
    present = set(retained)
    return retained + [key for key in current if key not in present]


def _progress(progress):
    if progress is None:
        return dict(schema=PROGRESS_SCHEMA, pending=[], events={})
    if (not isinstance(progress, dict) or progress.get("schema") != PROGRESS_SCHEMA
            or not isinstance(progress.get("pending"), list)
            or not isinstance(progress.get("events"), dict)):
        raise ValueError("invalid_correction_progress")
    def unique_strings(values):
        return (isinstance(values, list)
                and all(isinstance(x, str) and 1 <= len(x) <= 500 for x in values)
                and len(set(values)) == len(values))
    def key_ok(key):
        return isinstance(key, str) and re.fullmatch(r"[a-f0-9]{64}", key)
    if (not unique_strings(progress["pending"])
            or not all(key_ok(k) for k in progress["pending"])
            or not all(key_ok(k) and unique_strings(v)
                       for k, v in progress["events"].items())):
        raise ValueError("invalid_correction_progress_identity")
    return progress


def preview(catalogue, today, checkpoint, *, progress=None, researcher=research_group,
            source_reader=read_unknown_https):
    """Return a counterfactual catalogue and audit, never change input."""
    if (not isinstance(checkpoint, dict) or checkpoint.get("schema") != SCHEMA
            or not isinstance(checkpoint.get("latest"), dict)):
        raise ValueError("invalid_research_checkpoint")
    groups = research_queue(catalogue, today)["research_groups"]
    byid = {e["id"]: e for e in catalogue["events"]}
    previous = _progress(progress)
    candidates = {}
    for g in groups:
        entry = checkpoint["latest"].get(identity(g))
        if not isinstance(entry, dict) or not g["missing_ids"]:
            continue
        try:
            age = (today - date.fromisoformat(entry["day"])).days
            old = _witness(entry.get("result"), g)
        except ERRORS:
            continue
        if 0 <= age <= MAX_AGE and old is not None:
            candidates[identity(g)] = (g, old)
    changes, examined, source_reads = {}, 0, 0
    reasons = {"fresh_proof_missing_or_changed": 0, "event_identity_unconfirmed": 0}
    order = _fifo(previous["pending"], candidates)
    event_queues = {key: _fifo(previous["events"].get(key, []), g["missing_ids"])
                    for key, (g, _) in candidates.items()}
    selected = order[:MAX_GROUPS]
    for key in selected:
        g, old = candidates[key]
        examined += 1
        try:
            fresh = _witness(researcher(g, today), g)
            if fresh is None or fresh[1:] != old[1:] or meters(fresh[0], old[0]) > 3:
                reasons["fresh_proof_missing_or_changed"] += 1
                continue
        except ERRORS:
            reasons["fresh_proof_missing_or_changed"] += 1
            continue
        queue = event_queues[key]
        attempted = queue[:MAX_EVENTS_PER_GROUP]
        event_queues[key] = queue[len(attempted):] + attempted
        for eid in attempted:
            assert source_reads < MAX_EVENTS
            event = byid[eid]
            if point(event) is not None:
                continue
            source_reads += 1
            try:
                url = event.get("source_url")
                if not _safe_url(url) or not structured_event_identity(event, source_reader(url)):
                    reasons["event_identity_unconfirmed"] += 1
                    continue
            except ERRORS:
                reasons["event_identity_unconfirmed"] += 1
                continue
            lat, lng = fresh[0]
            corrected = dict(event, lat=lat, lng=lng, geo_precision="venue",
                             geo_verified_at=today.isoformat())
            changes[eid] = (corrected, {"id": eid, "before_sha256": digest(event),
                             "after_sha256": digest(corrected), "official": fresh[1],
                             "geo_source": fresh[2], "event_source": url,
                             "lat": lat, "lng": lng})
    result = dict(catalogue, events=[changes[e["id"]][0] if e["id"] in changes else e
                                    for e in catalogue["events"]])
    assert len(result["events"]) == len(catalogue["events"])
    for before, after in zip(catalogue["events"], result["events"]):
        assert {k:v for k,v in before.items() if k not in GEO_FIELDS} == {
            k:v for k,v in after.items() if k not in GEO_FIELDS}
    return result, dict(schema="ptitesondes.historical_gps_correction_preview.v1",
                        day=today.isoformat(), candidate_groups=len(candidates),
                        examined_groups=examined, source_reads=source_reads,
                        proposed_count=len(changes), reasons=reasons,
                        before_sha256=digest(catalogue), after_sha256=digest(result),
                        proposals=[v[1] for v in changes.values()],
                        progress=dict(schema=PROGRESS_SCHEMA,
                                      pending=order[len(selected):] + selected,
                                      events=event_queues),
                        publication_ready=False, public_writes=0)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--catalogue", type=Path, required=True)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--progress", type=Path, required=True)
    p.add_argument("--acceslibre-hints", type=Path)
    p.add_argument("--day", type=date.fromisoformat, required=True)
    p.add_argument("--live", action="store_true")
    args = p.parse_args()
    if not args.live:
        p.error("Explicit --live required")
    catalogue = json.loads(args.catalogue.read_text(encoding="utf-8"))
    checkpoint = json.loads(args.state.read_text(encoding="utf-8"))
    if args.progress.is_symlink():
        raise ValueError("unsafe_progress_path")
    previous = json.loads(args.progress.read_text(encoding="utf-8")) if args.progress.exists() else None
    from ptitesondes_acceslibre_geo_hints import load_hints, hinted_researcher
    _, report = preview(catalogue, args.day, checkpoint, progress=previous,
        researcher=hinted_researcher(load_hints(args.acceslibre_hints, args.day)))
    write_state(args.progress, report["progress"])
    # Do not export private research details to the public runner log.
    print(json.dumps({k: report[k] for k in (
        "candidate_groups", "examined_groups", "source_reads", "proposed_count",
        "reasons", "publication_ready", "public_writes")}))
