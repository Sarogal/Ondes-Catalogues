#!/usr/bin/env python3
"""Review-only HLS manifest progression and bounded packed-audio evidence.

No key, init-map or byte-range retrieval. No raw URLs or bytes in reports.
A moving media sequence is not proof of decodable live audio.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import re
import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlunsplit

from radio_daily_qualification_dossiers import index, safe_digest
from radio_stream_technical_probe import validate_endpoint, public_resolved_ips, REDIRECT_CODES, frame_chain
from radio_stream_recheck_ledger import parse_day, SHA256_RE

MAX_MANIFEST = 65536
MAX_SEGMENT = 4096
MAX_STATIONS = 4
MAX_INPUT = 12 * 1024 * 1024
MAX_WAIT = 12
MAX_REQUESTS = 12
MAX_SECONDS = 45


def safe_target(parent, child):
    target = urljoin(parent, child)
    a, b = validate_endpoint(parent), validate_endpoint(target)
    if a.scheme == "https" and b.scheme != "https":
        raise ValueError("TLS downgrade")
    return target


def parse_manifest(data, url):
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_MANIFEST:
        raise ValueError("manifest size")
    lines = [x.strip() for x in data.decode("utf-8-sig").splitlines() if x.strip()]
    if not lines or lines[0] != "#EXTM3U" or len(lines) > 1024:
        raise ValueError("not bounded M3U")
    tags = [x for x in lines if x.startswith("#EXT-X-")]
    if not tags:
        return {"kind": "ordinary_playlist"}
    if any(x.startswith(("#EXT-X-KEY:", "#EXT-X-SESSION-KEY:", "#EXT-X-MAP:",
                         "#EXT-X-BYTERANGE:", "#EXT-X-PART:", "#EXT-X-SKIP:",
                         "#EXT-X-DEFINE:", "#EXT-X-I-FRAMES-ONLY")) for x in tags):
        return {"kind": "unsupported_hls_features"}
    variants = []
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF:"):
            if i+1 >= len(lines) or lines[i+1].startswith("#"):
                raise ValueError("missing variant")
            # Prefer explicitly audio-only codecs; otherwise leave variant
            # format unconfirmed until actual segment inspection.
            match = re.search(r'(?:^|,)CODECS="([^"]+)"', line.split(":",1)[1])
            codecs = match.group(1).lower().split(",") if match else []
            audio_only = bool(codecs) and all(x.strip().startswith(("mp4a.", "mp3", "ac-3", "ec-3", "opus")) for x in codecs)
            variants.append((not audio_only, safe_target(url, lines[i+1])))
    if variants:
        if len(variants) > 16:
            raise ValueError("variant budget")
        return {"kind": "master", "variant": sorted(variants)[0][1]}
    seq = None
    duration = None
    pending = False
    segments = []
    ended = False
    vod = False
    for line in lines:
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            raw = line.split(":",1)[1]
            if seq is not None or not re.fullmatch(r"[0-9]{1,18}", raw):
                raise ValueError("invalid sequence")
            seq = int(raw)
        elif line.startswith("#EXT-X-TARGETDURATION:"):
            raw = line.split(":",1)[1]
            if duration is not None or not re.fullmatch(r"[0-9]{1,3}", raw):
                raise ValueError("invalid target duration")
            duration = int(raw)
        elif line == "#EXT-X-ENDLIST":
            ended = True
        elif line == "#EXT-X-PLAYLIST-TYPE:VOD":
            vod = True
        elif line.startswith("#EXTINF:"):
            if pending:
                raise ValueError("missing segment")
            value = line.split(":",1)[1].split(",",1)[0]
            if not re.fullmatch(r"[0-9]{1,4}(?:\.[0-9]{1,9})?", value) or float(value) <= 0:
                raise ValueError("invalid segment duration")
            pending = True
        elif not line.startswith("#"):
            if not pending or len(segments) >= 128:
                raise ValueError("invalid segment listing")
            segments.append(safe_target(url, line))
            pending = False
    if pending or not segments or not duration:
        raise ValueError("incomplete media playlist")
    return {"kind": "media", "sequence": seq if seq is not None else 0,
            "targetDuration": duration, "segments": segments, "finite": ended or vod}


class BoundedFetch:
    def __init__(self):
        self.deadline = time.monotonic() + MAX_SECONDS
        self.requests = 0

    def __call__(self, url, limit):
        seen = set()
        for _ in range(4):
            if url in seen or self.requests >= MAX_REQUESTS:
                raise ValueError("request budget or cycle")
            seen.add(url)
            self.requests += 1
            p = validate_endpoint(url)
            host = p.hostname
            port = p.port or (443 if p.scheme == "https" else 80)
            ip = public_resolved_ips(host, port)[0]
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("deadline")
            kwargs = {"timeout": min(4, remaining)}
            if p.scheme == "https":
                c = http.client.HTTPSConnection(host, port, context=ssl.create_default_context(), **kwargs)
            else:
                c = http.client.HTTPConnection(host, port, **kwargs)
            def pinned(address, timeout=None, source_address=None):
                if address != (host,port):
                    raise ValueError("unexpected target")
                return socket.create_connection((ip,port), timeout=min(4,max(.1,self.deadline-time.monotonic())))
            c._create_connection = pinned
            try:
                c.request("GET", urlunsplit(("", "", p.path or "/", p.query, "")),
                          headers={"Accept-Encoding":"identity", "Connection":"close",
                                   "User-Agent":"GrossesOndesHLSPreview/1.0", "Cache-Control":"no-cache"})
                response = c.getresponse()
                if response.status in REDIRECT_CODES:
                    location = response.getheader("Location")
                    if not location:
                        raise ValueError("missing redirect")
                    url = safe_target(url,location)
                    continue
                if response.status != 200 or (response.getheader("Content-Encoding") or "identity").lower() != "identity":
                    raise ValueError("unsupported response")
                body = bytearray()
                cap = limit+1 if limit == MAX_MANIFEST else limit
                while len(body) < cap:
                    if time.monotonic() >= self.deadline:
                        raise TimeoutError("deadline")
                    chunk = response.read1(min(8192,cap-len(body)))
                    if not chunk:
                        break
                    body.extend(chunk)
                if not body or len(body)>limit:
                    raise ValueError("body size")
                return url,bytes(body)
            finally:
                c.close()
        raise ValueError("redirect budget")


def observe(url, *, fetch=None, sleep=time.sleep):
    if fetch is None:
        fetch = BoundedFetch()
    final, first_bytes = fetch(url, MAX_MANIFEST)
    safe_target(url,final)
    first = parse_manifest(first_bytes,final)
    if first["kind"] == "master":
        variant = first["variant"]
        final, first_bytes = fetch(variant,MAX_MANIFEST)
        safe_target(variant,final)
        first = parse_manifest(first_bytes,final)
    if first["kind"] != "media":
        return {"verdict": first["kind"]}
    if first["finite"]:
        return {"verdict":"finite_hls_review"}
    if first["targetDuration"] > MAX_WAIT:
        return {"verdict":"long_target_duration_review","targetDuration":first["targetDuration"]}
    sleep(max(2,first["targetDuration"]+0.5))
    second_url, second_bytes = fetch(final,MAX_MANIFEST)
    safe_target(final,second_url)
    second = parse_manifest(second_bytes,second_url)
    if second["kind"] != "media" or second["finite"]:
        return {"verdict":"changed_or_finite_manifest_review"}
    # Compare actual sequence positions, not signed URI/query churn.
    first_last = first["sequence"] + len(first["segments"])-1
    second_last = second["sequence"] + len(second["segments"])-1
    advanced = second["sequence"] >= first["sequence"] and second_last > first_last
    if not advanced:
        return {"verdict":"manifest_not_advanced","firstLastSequence":first_last,"secondLastSequence":second_last}
    # Only inspect the latest complete segment. No decryption or init maps.
    target = second["segments"][-1]
    segment_url, segment = fetch(target,MAX_SEGMENT)
    safe_target(target,segment_url)
    codec = frame_chain(segment)
    return {"verdict":"advancing_hls_audio_frame_indication" if codec else "advancing_hls_manifest_only",
            "firstLastSequence":first_last,"secondLastSequence":second_last,
            "targetDuration":second["targetDuration"],"segmentSampleBytes":len(segment),
            "frameCodec":codec or None,"firstManifestSha256":hashlib.sha256(first_bytes).hexdigest(),
            "secondManifestSha256":hashlib.sha256(second_bytes).hexdigest()}


def collect(discovery,reconciliation,audio,*,previous=None,limit=0,probe=observe):
    day=parse_day(discovery.get("scanDate"))
    if not 0<=limit<=MAX_STATIONS:
        raise ValueError("station budget")
    if (discovery.get("schemaVersion")!=1 or discovery.get("publicationAllowed") is not False
            or reconciliation.get("schemaVersion")!=1 or reconciliation.get("scanDate")!=day
            or reconciliation.get("automaticAdmissionAllowed") is not False
            or reconciliation.get("catalogChanged") is not False
            or audio.get("schemaVersion")!=1 or audio.get("observationDate")!=day
            or audio.get("publicationAllowed") is not False or audio.get("technicallyQualifiedCount")!=0):
        raise ValueError("invalid inputs")
    candidates,rec,a=index(discovery,"candidates"),index(reconciliation,"candidates"),index(audio,"records")
    if set(candidates)!=set(rec):
        raise ValueError("UUID mismatch")
    old={}
    if previous is not None:
        if (previous.get("schemaVersion")!=1 or previous.get("publicationAllowed") is not False
                or previous.get("technicallyQualifiedCount")!=0 or parse_day(previous["scanDate"])>day):
            raise ValueError("invalid prior")
        old=index(previous,"records")
        for row in old.values():
            if (row.get("publicationAllowed") is not False or row.get("technicalQualified") is not False
                    or parse_day(row["observedDate"])>day or not SHA256_RE.fullmatch(row.get("streamSha256") or "")):
                raise ValueError("invalid prior row")
    result={uid:dict(row,observedInScan=False) for uid,row in old.items() if uid not in candidates}
    queue=[]
    for uid,row in sorted(candidates.items()):
        url=row.get("streamUrl")
        digest=safe_digest(url)
        if rec[uid]["classification"]!="unmapped_candidate" or not digest:
            continue
        if row.get("editorialSignal")=="electronic_context_review":
            continue
        prior=old.get(uid)
        if prior and prior["streamSha256"]==digest:
            result[uid]=dict(prior,observedInScan=True)
            if prior["observedDate"]==day:
                continue
        evidence=a.get(uid,{})
        if evidence.get("streamSha256")!=digest or evidence.get("lastVerdict")!="playlist_pending":
            continue
        if evidence.get("technicalQualified") is not False or evidence.get("publicationAllowed") is not False:
            raise ValueError("unexpected approval")
        try:
            validate_endpoint(url)
        except ValueError:
            continue
        queue.append((uid in result,uid,url,digest))
    selected=sorted(queue)[:limit]
    def check(item):
        _,uid,url,digest=item
        try:
            e=probe(url)
        except (OSError,ValueError,http.client.HTTPException,UnicodeError):
            e={"verdict":"manifest_or_connection_review"}
        return uid,{"stationuuid":uid,"streamSha256":digest,"observedDate":day,
                    "observedInScan":True,"technicalQualified":False,"publicationAllowed":False,**e}
    with ThreadPoolExecutor(max_workers=2) as pool:
        for uid,row in pool.map(check,selected):
            result[uid]=row
    rows=[result[k] for k in sorted(result)]
    return {"schemaVersion":1,"scanDate":day,"publicationAllowed":False,"technicallyQualifiedCount":0,
            "attemptedCount":len(selected),
            "advancingManifestCount":sum(x["verdict"] in ("advancing_hls_audio_frame_indication","advancing_hls_manifest_only") for x in rows),
            "audioFrameCount":sum(x["verdict"]=="advancing_hls_audio_frame_indication" for x in rows),
            "records":rows}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ("discovery","reconciliation","audio","output"):
        p.add_argument("--"+key,type=Path,required=True)
    p.add_argument("--previous",type=Path)
    p.add_argument("--limit",type=int,default=0)
    p.add_argument("--allow-network",action="store_true")
    a=p.parse_args()
    if a.limit and not a.allow_network:
        p.error("network must be explicit")
    def load(path):
        if path.stat().st_size>MAX_INPUT:
            raise ValueError("oversized input")
        return json.loads(path.read_text())
    report=collect(*(load(getattr(a,k)) for k in ("discovery","reconciliation","audio")),
                   previous=load(a.previous) if a.previous else None,limit=a.limit)
    payload=json.dumps(report,indent=2)+"\n"
    if len(payload.encode())>MAX_INPUT:
        raise ValueError("oversized report")
    a.output.write_text(payload)
    print("RADIO_HLS_PREVIEW_ONLY",{k:v for k,v in report.items() if k!="records"})


if __name__=="__main__":
    main()
