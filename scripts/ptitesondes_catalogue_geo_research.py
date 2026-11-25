"""Read-only catalogue GPS research queue; existing points are hints, never proof."""
import argparse
from collections import defaultdict
from datetime import date
import json
import math
from pathlib import Path
from proof import norm, meters


def point(e):
    a, b = e.get("lat"), e.get("lng")
    if (type(a) in (int, float) and type(b) in (int, float)
            and math.isfinite(a) and math.isfinite(b)
            and -90 <= a <= 90 and -180 <= b <= 180 and (a, b) != (0, 0)):
        return a, b
    return None


def active(e, today):
    try:
        return date.fromisoformat(e.get("date_end") or e["date_start"]) >= today
    except (KeyError, TypeError, ValueError):
        return True


def research_queue(doc, today):
    events = doc["events"]
    ids = [e["id"] for e in events]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate_catalogue_ids")
    groups, owners = {}, defaultdict(set)
    incomplete = []
    active_count = missing_count = 0
    for e in events:
        live, p = active(e, today), point(e)
        active_count += int(live)
        missing_count += int(live and p is None)
        city, venue = norm(e.get("city") or ""), norm(e.get("venue") or "")
        if not city or not venue:
            if live and p is None:
                incomplete.append(e["id"])
            continue
        key = (norm(e.get("department") or ""), norm(e.get("region") or ""), city, venue)
        g = groups.setdefault(key, dict(city=e["city"], venue=e["venue"],
            department=e.get("department"), region=e.get("region"),
            active_ids=[], missing_ids=[], points=defaultdict(list), source_urls=set()))
        if live:
            g["active_ids"].append(e["id"])
            if p is None:
                g["missing_ids"].append(e["id"])
            if isinstance(e.get("source_url"), str):
                g["source_urls"].add(e["source_url"])
        if p is not None:
            g["points"][p].append(e["id"])
            owners[p].add((city, venue))
    shared = {p for p, names in owners.items() if len(names) > 1}
    queue = []
    for g in groups.values():
        if not g["active_ids"]:
            continue
        pts = sorted(g["points"])
        reasons = []
        if g["missing_ids"]:
            reasons.append("missing_coordinates")
        if any(meters(a, b) > 65 for i, a in enumerate(pts) for b in pts[i+1:]):
            reasons.append("inconsistent_same_venue_points")
        if any(p in shared for p in pts):
            reasons.append("point_shared_by_different_venue_names")
        if reasons:
            queue.append(dict(city=g["city"], venue=g["venue"], region=g["region"],
                department=g["department"], reasons=reasons,
                active_ids=sorted(g["active_ids"]), missing_ids=sorted(g["missing_ids"]),
                source_urls=sorted(g["source_urls"]), independent_proof_required=True,
                point_hints=[dict(lat=p[0], lng=p[1], event_ids=sorted(g["points"][p]))
                             for p in pts]))
    queue.sort(key=lambda g: (-len(g["missing_ids"]), -len(g["active_ids"]),
                              norm(g["city"]), norm(g["venue"]), g["active_ids"]))
    return dict(schema="ptitesondes.public_catalogue_geo_research.v1",
                day=today.isoformat(), catalogue_count=len(events),
                active_count=active_count, active_without_valid_point=missing_count,
                shared_exact_points=len(shared), incomplete_identity_ids=sorted(incomplete),
                research_groups=queue, publication_ready=False, public_writes=0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--day", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    print(json.dumps(research_queue(json.loads(args.catalogue.read_text(encoding="utf-8")),
                                    args.day), ensure_ascii=False, indent=2))
