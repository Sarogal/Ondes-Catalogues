#!/usr/bin/env python3
"""Validateur éditorial sans réseau du catalogue Grosses Ondes v1.

Sépare clairement un import legacy non qualifié (staging) d'une publication
admissible. Le JSON Schema est un garde-fou complémentaire, pas un substitut.
Usage:
  python radio_catalog_guard.py draft.json --mode staging
  python radio_catalog_guard.py candidate.json --mode publish --previous last.json
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

GO_ID = re.compile(r"^go-station-[0-9]{6,}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
COUNTRY = re.compile(r"^[A-Z]{2}$")
STATUSES = {"active", "quarantined", "retired"}
STREAM_STATES = {"candidate", "candidate_verified", "verified", "suspected_unavailable", "disabled"}


def safe_url(value, https_only=False):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in (("https",) if https_only else ("http", "https")):
            return False
        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
            return False
        host = parsed.hostname.lower().rstrip(".")
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".local") or host.endswith(".internal"):
            return False
        try:
            addr = ipaddress.ip_address(host)
            if not addr.is_global:
                return False
        except ValueError:
            if "." not in host:
                return False
        return True
    except (ValueError, TypeError):
        return False


def validate_catalog(document, *, mode="staging", previous=None):
    issues = []
    if mode not in ("staging", "publish"):
        return ["mode must be staging or publish"]
    if not isinstance(document, dict):
        return ["catalog must be an object"]
    if document.get("schema_version") != 1 or document.get("catalog_id") != "grosses-ondes-radio":
        issues.append("unsupported schema_version or catalog_id")
    if type(document.get("release_sequence")) is not int or document["release_sequence"] < 1:
        issues.append("release_sequence must be a positive integer")
    stations = document.get("stations")
    tombstones = document.get("tombstones")
    if not isinstance(stations, list) or not stations:
        issues.append("stations must be a non-empty list")
        stations = []
    if not isinstance(tombstones, list):
        issues.append("tombstones must be a list")
        tombstones = []

    id_map = {}
    alias_owner = {}
    for index, station in enumerate(stations):
        prefix = f"station[{index}]"
        if not isinstance(station, dict):
            issues.append(prefix + " must be an object")
            continue
        goid = station.get("go_station_id")
        if not isinstance(goid, str) or not GO_ID.fullmatch(goid):
            issues.append(prefix + " missing/invalid go_station_id")
            continue
        if goid in id_map:
            issues.append(prefix + f" duplicate go_station_id {goid}")
        id_map[goid] = station
        if not isinstance(station.get("display_name"), str) or not station["display_name"].strip():
            issues.append(prefix + " empty name")
        country = station.get("country_code")
        if country is not None and (not isinstance(country, str) or not COUNTRY.fullmatch(country)):
            issues.append(prefix + " invalid country_code")
        genres = station.get("genres")
        if not isinstance(genres, list) or not genres or not all(isinstance(g, str) and g.strip() for g in genres) or len(set(genres)) != len(genres):
            issues.append(prefix + " invalid genres")
        homepage = station.get("homepage")
        if homepage not in (None, "") and not safe_url(homepage):
            issues.append(prefix + " unsafe homepage")
        aliases = station.get("legacy_aliases")
        ids = station.get("radio_browser_uuids")
        if not isinstance(aliases, list) or not all(isinstance(x, str) and x.strip() for x in aliases) or len(set(aliases)) != len(aliases):
            issues.append(prefix + " invalid legacy_aliases")
            aliases = []
        if not isinstance(ids, list):
            issues.append(prefix + " invalid radio_browser_uuids")
            ids = []
        for row in ids:
            if not isinstance(row, dict) or not isinstance(row.get("uuid"), str) or not row["uuid"] or row.get("state") not in ("current", "historical"):
                issues.append(prefix + " malformed radio_browser_uuids")
                continue
            if row["uuid"] not in aliases:
                issues.append(prefix + f" Radio Browser UUID absent from legacy_aliases: {row['uuid']}")
        for alias in aliases:
            owner = alias_owner.setdefault(alias, goid)
            if owner != goid:
                issues.append(prefix + f" legacy alias collision {alias} ({owner}/{goid})")

        status = station.get("status")
        state = status.get("state") if isinstance(status, dict) else None
        if state not in STATUSES:
            issues.append(prefix + " invalid status")
        streams = station.get("streams")
        if not isinstance(streams, list):
            issues.append(prefix + " streams missing")
            streams = []
        if state == "active" and not streams:
            issues.append(prefix + " active station with no streams")
        stream_ids, priorities = set(), set()
        verified = 0
        for j, stream in enumerate(streams):
            sprefix = f"{prefix}.streams[{j}]"
            if not isinstance(stream, dict):
                issues.append(sprefix + " invalid stream object")
                continue
            sid = stream.get("stream_id")
            if not isinstance(sid, str) or not sid or sid in stream_ids:
                issues.append(sprefix + " missing/duplicate stream_id")
            else:
                stream_ids.add(sid)
            p = stream.get("priority")
            if type(p) is not int or p < 0 or p in priorities:
                issues.append(sprefix + " missing/duplicate priority")
            else:
                priorities.add(p)
            url = stream.get("url")
            if not safe_url(url):
                issues.append(sprefix + " unsafe stream URL")
            else:
                scheme = urlsplit(url).scheme
                if scheme != stream.get("protocol"):
                    issues.append(sprefix + " protocol mismatch")
            if stream.get("state") not in STREAM_STATES:
                issues.append(sprefix + " unknown stream state")
            if stream.get("state") == "verified":
                verified += 1
        logo = station.get("logo")
        if logo is not None:
            if not isinstance(logo, dict):
                issues.append(prefix + " invalid logo")
            else:
                digest = logo.get("sha256")
                if not isinstance(digest, str) or not SHA256.fullmatch(digest) or logo.get("asset_id") != f"sha256:{digest}":
                    issues.append(prefix + " logo asset ID/digest inconsistency")
                if not safe_url(logo.get("url"), https_only=True):
                    issues.append(prefix + " unsafe logo URL")
                if type(logo.get("byte_size")) is not int or not 0 < logo["byte_size"] <= 8 * 1024 * 1024:
                    issues.append(prefix + " invalid logo byte_size")
        editorial = station.get("editorial")
        decision = editorial.get("admission_state") if isinstance(editorial, dict) else None
        if decision not in ("approved", "legacy_preserved"):
            issues.append(prefix + " invalid editorial approval state")
        if mode == "publish" and state == "active":
            if decision != "approved":
                issues.append(prefix + " active station not approved for publication")
            if not isinstance(editorial.get("reviewed_at"), str) or not editorial["reviewed_at"].strip():
                issues.append(prefix + " missing editorial review timestamp")
            if verified < 1:
                issues.append(prefix + " active station has no verified stream")

    for i, tombstone in enumerate(tombstones):
        prefix = f"tombstone[{i}]"
        if not isinstance(tombstone, dict):
            issues.append(prefix + " must be object")
            continue
        goid = tombstone.get("go_station_id")
        if not isinstance(goid, str) or not GO_ID.fullmatch(goid):
            issues.append(prefix + " invalid go_station_id")
            continue
        if goid in id_map:
            issues.append(prefix + f" duplicate go_station_id {goid} in active list")
        id_map[goid] = tombstone
        aliases = tombstone.get("legacy_aliases", [])
        if not isinstance(aliases, list):
            issues.append(prefix + " invalid legacy_aliases")
            aliases = []
        for alias in aliases:
            if not isinstance(alias, str) or not alias:
                issues.append(prefix + " invalid legacy alias")
                continue
            owner = alias_owner.setdefault(alias, goid)
            if owner != goid:
                issues.append(prefix + f" alias reassigned {alias} ({owner}/{goid})")

    if previous is not None:
        before = previous.get("stations", []) + previous.get("tombstones", [])
        for old in before:
            if not isinstance(old, dict):
                continue
            oldid = old.get("go_station_id")
            if oldid not in id_map:
                issues.append(f"previously known go_station_id lost: {oldid}")
                continue
            old_aliases = set(old.get("legacy_aliases", []))
            new_aliases = set(id_map[oldid].get("legacy_aliases", []))
            for lost in sorted(old_aliases - new_aliases):
                issues.append(f"historical alias lost for {oldid}: {lost}")
        if mode == "publish" and type(previous.get("release_sequence")) is int:
            if document.get("release_sequence", 0) <= previous["release_sequence"]:
                issues.append("release_sequence did not increase")
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--mode", choices=["staging", "publish"], default="staging")
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args()
    doc = json.loads(args.catalog.read_text(encoding="utf-8"))
    prev = json.loads(args.previous.read_text(encoding="utf-8")) if args.previous else None
    errors = validate_catalog(doc, mode=args.mode, previous=prev)
    if errors:
        print(f"REFUS ({len(errors)} anomalie(s)) :")
        for error in errors[:80]:
            print(" - " + error)
        raise SystemExit(1)
    print(f"OK mode={args.mode}: {len(doc['stations'])} station(s), {len(doc['tombstones'])} tombstones, release={doc['release_sequence']}")


if __name__ == "__main__":
    main()
