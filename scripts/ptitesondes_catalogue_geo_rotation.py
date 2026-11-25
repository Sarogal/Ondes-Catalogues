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


def rotate(catalogue, today, previous=None, *, researcher=research_group):
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
    # Prune only groups no longer requiring research. New work goes behind
    # existing pending work; neither a new group nor a failure can jump ahead.
    order = [k for k in pending if k in current]
    present = set(order)
    order.extend(k for k in current if k not in present)
    selected = order[:MAX_GROUPS]
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
    state = dict(schema=SCHEMA, pending=order[len(selected):] + selected,
                 latest=latest)
    summary = dict(group_count=len(groups), examined=len(selected),
                   never_examined=len(current.keys()-latest.keys()),
                   venue_points_found=sum(latest[k]["result"].get("status") ==
                                          "independent_venue_point_found"
                                          for k in selected),
                   publication_ready=False, public_writes=0)
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
    p.add_argument("--day", type=date.fromisoformat, required=True)
    p.add_argument("--live", action="store_true")
    a = p.parse_args()
    if not a.live:
        p.error("Explicit --live required")
    if a.state.is_symlink():
        raise ValueError("unsafe_state_path")
    catalogue = json.loads(a.catalogue.read_text(encoding="utf-8"))
    previous = json.loads(a.state.read_text(encoding="utf-8")) if a.state.exists() else None
    state, summary = rotate(catalogue, a.day, previous)
    write_state(a.state, state)
    print(json.dumps(summary))
