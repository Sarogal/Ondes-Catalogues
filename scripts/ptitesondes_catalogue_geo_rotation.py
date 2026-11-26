"""Persistent FIFO research rotation for existing outings. No public writes.

The queue is rebuilt from the current catalogue each cycle. Stable geographic
identities, not a numeric offset into a changing sorted list, determine order.
The state is private research only; stored results are never publication proof.
"""
import argparse
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from proof import norm
from ptitesondes_catalogue_geo_research import research_queue
from ptitesondes_catalogue_geo_proof_batch import MAX_GROUPS, research_group

SCHEMA = "ptitesondes.catalogue_geo_rotation.v1"


def identity(group):
    parts = [norm(group.get(k) or "") for k in
             ("department", "region", "city", "venue")]
    return sha256(json.dumps(parts, ensure_ascii=False,
                             separators=(",", ":")).encode()).hexdigest()


def rotate(catalogue, today, previous=None, *, researcher=research_group, priority_keys=()):
    groups = research_queue(catalogue, today)["research_groups"]
    current = {identity(g): g for g in groups}
    if len(current) != len(groups):
        raise ValueError("ambiguous_research_group")
    if previous is None:
        previous = dict(schema=SCHEMA, pending=[], latest={})
    if (not isinstance(previous, dict) or previous.get("schema") != SCHEMA
            or not isinstance(previous.get("pending"), list)
            or not isinstance(previous.get("latest"), dict)):
        raise ValueError("invalid_rotation_state")
    pending = previous["pending"]
    if (not all(isinstance(k, str) and re.fullmatch("[a-f0-9]{64}", k)
                for k in pending) or len(set(pending)) != len(pending)
            or not all(isinstance(k, str) and re.fullmatch("[a-f0-9]{64}", k)
                       and isinstance(v, dict)
                       for k, v in previous["latest"].items())):
        raise ValueError("invalid_rotation_identity")
    # Prune only groups no longer requiring research. Reserve FIFO capacity;
    # at most one slot per cycle may accelerate a newly actionable hint.
    order = [k for k in pending if k in current]
    present = set(order)
    order.extend(k for k in current if k not in present)
    priority = set(priority_keys)
    selected = order[:MAX_GROUPS]
    accelerated = 0
    if MAX_GROUPS >= 2 and len(order) > MAX_GROUPS:
        # Preserve the first MAX_GROUPS-1 FIFO places. Select the oldest
        # hinted group from the remaining queue; no group can starve.
        candidate = next((k for k in order[MAX_GROUPS-1:] if k in priority), None)
        if candidate is not None and candidate not in selected:
            selected = selected[:-1] + [candidate]
            accelerated = 1
    latest = {k: v for k, v in previous["latest"].items() if k in current}
    for key in selected:
        group = current[key]
        try:
            result = researcher(group, today)
            if not isinstance(result, dict) or result.get("publication_ready") is not False:
                raise ValueError("invalid_research_result")
        except (OSError, ValueError, TypeError, KeyError, TimeoutError):
            result = dict(status="research_retry_later", publication_ready=False)
        latest[key] = dict(day=today.isoformat(), result=result)
    selected_set = set(selected)
    state = dict(schema=SCHEMA, pending=[k for k in order if k not in selected_set] + selected,
                 latest=latest)
    summary = dict(group_count=len(groups), examined=len(selected),
                   never_examined=len(current.keys()-latest.keys()),
                   accelerated_hints=accelerated,
                   venue_points_found=sum(latest[k]["result"].get("status") ==
                                          "independent_venue_point_found"
                                          for k in selected),
                   publication_ready=False, public_writes=0)
    # Fixed provider names only; never log URLs, exception messages or private IDs.
    providers = ("dila", "administrative", "official_html", "ban", "osm_nearby", "osm_named")
    provider_totals = {}
    for key in selected:
        counters = latest[key]["result"].get("provider_diagnostics", {})
        if not isinstance(counters, dict):
            continue
        for provider in providers:
            row = counters.get(provider)
            if (not isinstance(row, dict) or type(row.get("calls")) is not int
                    or type(row.get("errors")) is not int
                    or not 0 <= row["errors"] <= row["calls"] <= 100):
                continue
            total = provider_totals.setdefault(provider, {"calls": 0, "errors": 0})
            for field in ("calls", "errors"):
                total[field] += row[field]
    summary["provider_diagnostics"] = provider_totals
    return state, summary


def write_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    if path.is_symlink() or temporary.is_symlink():
        raise ValueError("unsafe_state_path")
    with temporary.open("w", encoding="utf-8") as handle:
        os.chmod(temporary, 0o600)
        json.dump(state, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temporary, path)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--catalogue", type=Path, required=True)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--acceslibre-hints", type=Path)
    p.add_argument("--day", type=date.fromisoformat, required=True)
    p.add_argument("--live", action="store_true")
    a = p.parse_args()
    if not a.live:
        p.error("Explicit --live required")
    if a.state.is_symlink():
        raise ValueError("unsafe_state_path")
    catalogue = json.loads(a.catalogue.read_text(encoding="utf-8"))
    previous = json.loads(a.state.read_text(encoding="utf-8")) if a.state.exists() else None
    from ptitesondes_acceslibre_geo_hints import load_hints, hinted_researcher
    hints = load_hints(a.acceslibre_hints, a.day)
    # Any validated advisory point can now discover a venue website.
    # The single accelerated slot remains bounded; all other groups retain FIFO.
    priority_keys = {key for key, value in hints.items()
                     if isinstance(value, dict) and isinstance(value.get("hint"), dict)
                     and value.get("independent_recheck_required") is True}
    state, summary = rotate(catalogue, a.day, previous,
        researcher=hinted_researcher(hints), priority_keys=priority_keys)
    write_state(a.state, state)
    from ptitesondes_generic_venue_osm_preflight import osm_transport_diagnostics
    summary["osm_transport_diagnostics"] = osm_transport_diagnostics()
    print(json.dumps(summary))
