#!/usr/bin/env python3
"""Discover candidate logo sources and decode bounded same-host HTTPS images.

No image files, raw source URLs, approval, catalog changes or publication.
The Radio Browser homepage is self-reported, not proof of official ownership.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from radio_catalog_logo_pilot_probe import checked_https_url, decode_image, fetch_strict_https
from radio_stream_recheck_ledger import valid_uuid, parse_day

MAX_IMAGES = 8
MAX_INPUT_BYTES = 10_000_000


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def source_class(home: object, image: object) -> tuple[str, str | None]:
    if not isinstance(image, str) or not image.strip():
        return "missing_source", None
    try:
        img = urlsplit(image)
        checked_https_url(image, img.hostname or "")
        if img.query:
            return "query_source_review", None
        if not isinstance(home, str):
            return "homepage_unconfirmed", None
        site = urlsplit(home)
        if (site.scheme not in ("http", "https") or not site.hostname
                or site.username or site.password or site.fragment):
            return "homepage_unconfirmed", None
        if (site.hostname.removeprefix("www.") !=
                (img.hostname or "").removeprefix("www.")):
            return "external_image_host_review", None
        return "same_reported_host", image
    except (ValueError, TypeError):
        return "unsafe_or_unsupported_source", None


def review(discovery: dict, reconciliation: dict, stream: dict, *, limit: int = 0,
           fetch=fetch_strict_https, decode=decode_image, previous=None) -> dict:
    if not 0 <= limit <= MAX_IMAGES:
        raise ValueError("Image probe budget exceeded")
    if (discovery.get("schemaVersion") != 1 or discovery.get("publicationAllowed") is not False
            or reconciliation.get("schemaVersion") != 1
            or reconciliation.get("automaticAdmissionAllowed") is not False
            or reconciliation.get("catalogChanged") is not False
            or stream.get("schemaVersion") != 1 or stream.get("publicationAllowed") is not False
            or stream.get("technicallyQualifiedCount") != 0
            or discovery.get("scanDate") != reconciliation.get("scanDate")
            or discovery.get("scanDate") != stream.get("observationDate")):
        raise ValueError("Untrusted or mismatched preview inputs")
    def index(rows):
        if not isinstance(rows, list) or len(rows) > 20000:
            raise ValueError("Invalid source rows")
        out = {}
        for row in rows:
            uid = valid_uuid(row.get("stationuuid"))
            if uid in out:
                raise ValueError("Duplicate candidate UUID")
            out[uid] = row
        return out
    candidates = index(discovery["candidates"])
    reconciled = index(reconciliation["candidates"])
    evidence = index(stream["records"])
    if set(candidates) != set(reconciled):
        raise ValueError("Candidate/reconciliation mismatch")
    day = parse_day(discovery["scanDate"])
    cached = {}
    if previous is not None:
        if (previous.get("schemaVersion") != 1 or previous.get("publicationAllowed") is not False
                or previous.get("approvedLogoCount") != 0 or parse_day(previous["scanDate"]) > day):
            raise ValueError("Invalid previous artwork evidence")
        for old in index(previous["records"]).values():
            if old.get("logoApproved") is not False or old.get("publicationAllowed") is not False:
                raise ValueError("Invalid previous artwork approval")
            source = old.get("sourceSha256")
            if old.get("retrieval") != "decoded_unapproved":
                continue
            image = old.get("imageSha256")
            observed = parse_day(old.get("observedDate"))
            if (not isinstance(source, str) or not re.fullmatch("[0-9a-f]{64}", source)
                    or not isinstance(image, str) or not re.fullmatch("[0-9a-f]{64}", image)
                    or observed > day or old.get("mime") not in ("image/png", "image/jpeg", "image/webp")
                    or any(type(old.get(k)) is not int or not 64 <= old[k] <= 4096 for k in ("width", "height"))
                    or type(old.get("byteLength")) is not int or not 1 <= old["byteLength"] <= 2097152):
                raise ValueError("Malformed previous artwork evidence")
            cached[source] = {k: old[k] for k in ("retrieval", "imageSha256", "mime", "width", "height", "byteLength", "observedDate")}
    rows, queue = [], []
    for uid, row in sorted(candidates.items()):
        if reconciled[uid]["classification"] != "unmapped_candidate":
            continue
        kind, url = source_class(row.get("homepage"), row.get("favicon"))
        old = evidence.get(uid, {})
        current = (isinstance(row.get("streamUrl"), str)
                   and old.get("streamSha256") == digest(row["streamUrl"])
                   and old.get("lastVerdict") == "audio_sample_ok")
        rank = (2 if current and old.get("liveFrameEvidenceDates") else 1 if current else 0)
        result = {"stationuuid": uid, "sourceClass": kind,
                  "sourceSha256": digest(url) if url else None,
                  "audioEvidenceRank": rank, "retrieval": "not_attempted",
                  "logoApproved": False, "publicationAllowed": False}
        rows.append(result)
        if url and rank and row.get("editorialSignal") == "target_genre_indication":
            if digest(url) in cached:
                result.update(cached[digest(url)])
            else:
                queue.append((-rank, uid, url, result))
    # Group identical URLs for one network request; never imply shared station identity.
    groups = {}
    for _, uid, url, row in sorted(queue):
        groups.setdefault(url, []).append(row)
    for url, group in list(groups.items())[:limit]:
        try:
            data, mime = fetch(url, urlsplit(url).hostname)
            decoded, width, height = decode(data)
            if mime != decoded:
                raise ValueError("MIME mismatch")
            metadata = {"retrieval": "decoded_unapproved",
                        "imageSha256": hashlib.sha256(data).hexdigest(),
                        "mime": decoded, "width": width, "height": height,
                        "byteLength": len(data), "observedDate": day}
        except Exception:
            metadata = {"retrieval": "failed_review"}
        for row in group:
            row.update(metadata)
    return {"schemaVersion": 1, "scanDate": discovery["scanDate"],
            "publicationAllowed": False, "approvedLogoCount": 0,
            "candidateCount": len(rows), "attemptedSourceCount": min(limit, len(groups)),
            "decodedCandidateCount": sum(x["retrieval"] == "decoded_unapproved" for x in rows),
            "records": rows}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("discovery", "reconciliation", "stream", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--previous", type=Path)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--allow-network", action="store_true")
    a = p.parse_args()
    if a.limit and not a.allow_network:
        p.error("Network must be explicitly enabled")
    def load(path):
        if path.stat().st_size > MAX_INPUT_BYTES:
            raise ValueError("Input too large")
        return json.loads(path.read_text(encoding="utf-8"))
    result = review(load(a.discovery), load(a.reconciliation), load(a.stream), limit=a.limit,
                    previous=load(a.previous) if a.previous else None)
    a.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("RADIO_LOGO_PREVIEW_ONLY candidates=%d sources_attempted=%d decoded=%d approved=0 published=false"
          % (result["candidateCount"], result["attemptedSourceCount"], result["decodedCandidateCount"]))


if __name__ == "__main__":
    main()
