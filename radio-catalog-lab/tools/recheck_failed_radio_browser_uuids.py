#!/usr/bin/env python3
"""Seek alternative URLs for failed KNOWN radio stations from Radio Browser.

Uses the signed-staging historical UUIDs (not a closed station whitelist).
Discovered URLs are proposals until a separate short audio decode passes;
never overwrites an edited stream nor changes a public catalog.
"""
from __future__ import annotations
import argparse
import ipaddress
import json
import re
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

UUID = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
MIRRORS = ("de1.api.radio-browser.info", "nl1.api.radio-browser.info")


def is_public_url(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 2048:
        return False
    try:
        p = urlsplit(value)
        if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
            return False
        name = p.hostname.lower().rstrip(".")
        if name in ("localhost", "localhost.localdomain") or name.endswith(
                (".local", ".internal", ".localhost", ".onion")):
            return False
        try:
            return ipaddress.ip_address(name).is_global
        except ValueError:
            return "." in name
    except (ValueError, TypeError):
        return False


def fetch_uuids(uuids: list[str], opener=urlopen):
    if not uuids or len(uuids) > 70 or any(not UUID.fullmatch(x) for x in uuids):
        raise ValueError("invalid historical UUID set")
    q = urlencode({"uuids": ",".join(uuids)})
    errors = []
    for host in MIRRORS:
        u = f"https://{host}/json/stations/byuuid?{q}"
        try:
            with opener(Request(u, headers={"Accept": "application/json",
                    "User-Agent": "GrossesOndesCentralTestRepair/1.0"}), timeout=12) as response:
                raw = response.read(2*1024*1024+1)
                if getattr(response, "status", 200) != 200 or len(raw) > 2*1024*1024:
                    raise ValueError("invalid API response")
            result = json.loads(raw)
            if not isinstance(result, list):
                raise ValueError("directory response must be list")
            return result
        except (OSError, ValueError, UnicodeError) as e:
            errors.append(type(e).__name__)
    raise RuntimeError("directory unavailable: " + ",".join(errors))


def propose(catalog: dict, summary: dict, *, fetched: list[dict]):
    needed = summary.get("active_without_decoded_stream")
    if not isinstance(needed, list) or not needed or len(needed) > 200:
        raise ValueError("missing complete unsigned failure summary")
    byid = {s["go_station_id"]: s for s in catalog["stations"]}
    response = {}
    for station in fetched:
        if not isinstance(station, dict):
            continue
        uuid = str(station.get("stationuuid") or "").lower()
        if UUID.fullmatch(uuid):
            response.setdefault(uuid, []).append(station)
    rows = []
    for prior in needed:
        goid = prior.get("go_station_id")
        st = byid.get(goid)
        if not st or st["status"]["state"] != "active":
            raise ValueError("failed station identity unavailable")
        old_urls = {v["url"] for v in st["streams"]}
        proposals = []
        checked_uuids = [a for a in st["legacy_aliases"] if UUID.fullmatch(a.lower())]
        for uuid in checked_uuids:
            for record in response.get(uuid.lower(), []):
                for key in ("url_resolved", "url"):
                    u = record.get(key)
                    if not is_public_url(u):
                        continue
                    if u in old_urls or any(q["stream_url"] == u for q in proposals):
                        continue
                    proposals.append({
                        "stream_url": u, "directory_uuid": uuid,
                        "lastcheckok": record.get("lastcheckok"),
                        "name_reported": record.get("name"),
                        "possible_expiring_token": any(x in u.lower() for x in
                            ("token=", "auth=", "sid=", "expires=", "signature=")),
                        "verified": False, "replacement_authorized": False,
                    })
        rows.append({
            "go_station_id":goid,"name":st["display_name"],
            "historic_uuid_count":len(checked_uuids),
            "directory_record_found":any(response.get(x.lower()) for x in checked_uuids),
            "proposed_alternative_urls":proposals,
            "status":"live_audio_retry_required",
            "preserve_original_streams":True,
        })
    return {
        "scope":"OPEN_RADIO_BROWSER_EXISTING_STATIONS_REPAIR_CANDIDATES_ONLY",
        "stations_checked":len(rows),
        "candidate_alternative_streams":sum(len(s["proposed_alternative_urls"]) for s in rows),
        "publication_allowed":False,
        "canonical_stream_modified":False,
        "rows":rows,
    }


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--catalog",type=Path,required=True)
    ap.add_argument("--summary",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args()
    if args.out.exists():
        ap.error("will not overwrite previous evidence")
    original=json.loads(args.catalog.read_text(encoding="utf-8"))
    summary=json.loads(args.summary.read_text(encoding="utf-8"))
    ids={s["go_station_id"]:s for s in original["stations"]}
    failing=summary.get("active_without_decoded_stream",[])
    uuids=sorted({a.lower() for row in failing
                  for a in ids[row["go_station_id"]]["legacy_aliases"]
                  if UUID.fullmatch(a.lower())})
    directory=fetch_uuids(uuids)
    report=propose(original,summary,fetched=directory)
    args.out.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n", encoding="utf-8")
    print(json.dumps({"station_count":report["stations_checked"],
        "new_url_proposals":report["candidate_alternative_streams"],
        "no_signed_change":True}))
    for row in report["rows"]:
        print(row["go_station_id"],row["name"],"alternative_urls",
              len(row["proposed_alternative_urls"]),"found",row["directory_record_found"])


if __name__=="__main__":
    main()
