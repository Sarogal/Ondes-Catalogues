#!/usr/bin/env python3
"""Separate Ed25519 TEST artwork sidecar packager (never publishes).

Protocol is distinct from the RADIO catalog signature context. It maps
existing and future historical UUIDs to verified visual artwork without
changing radio content or making any station active. The signing seed is
NEVER read in CI or stored in this repository.
"""
from __future__ import annotations

import argparse
import base64
import binascii
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)

CONTEXT="GO-RADIO-ARTWORK-POINTER-V1\n"
CATALOG_ID="grosses-ondes-artwork"
UUID=re.compile(r"^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$",re.I)
SHA=re.compile(r"^[a-f0-9]{64}$")
UTC=re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
KEY=re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")
MAX_BODY=2*1024*1024
MAX_POINTER=12*1024


class ArtworkBundleError(ValueError): pass


def wire(doc:dict)->bytes:
    return (json.dumps(doc,sort_keys=True,ensure_ascii=False,
                       separators=(",",":"),allow_nan=False)+"\n").encode("utf-8")


def strict_json(body:bytes,limit:int)->dict:
    if not isinstance(body,bytes) or len(body)==0 or len(body)>limit:
        raise ArtworkBundleError("Invalid JSON byte length")
    def unique(pairs):
        data={}
        for k,v in pairs:
            if k in data:raise ArtworkBundleError("Duplicate JSON key")
            data[k]=v
        return data
    try: result=json.loads(body.decode("utf-8"),object_pairs_hook=unique)
    except ArtworkBundleError:raise
    except (ValueError,UnicodeError) as e:
        raise ArtworkBundleError("Invalid JSON") from e
    if not isinstance(result,dict):
        raise ArtworkBundleError("Expected JSON object")
    return result


def valid_date(s:str)->bool:
    if not isinstance(s,str) or not UTC.fullmatch(s):return False
    try: d=datetime.fromisoformat(s.replace("Z","+00:00"))
    except ValueError:return False
    return d.tzinfo is not None and d.utcoffset().total_seconds()==0


def public_https(u:str)->bool:
    if not isinstance(u,str) or len(u)>2048:return False
    try:
        p=urlsplit(u)
        if p.scheme!="https" or not p.hostname or p.username or \
           p.password or p.fragment or p.port not in (None,443):return False
        h=p.hostname.lower().rstrip(".")
        if "." not in h or h.endswith((".local",".internal",".localhost")):return False
        try:
            ip=ipaddress.ip_address(h.strip("[]"))
            return ip.is_global
        except ValueError:
            return bool(re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,251}[a-z0-9]",h))
    except (ValueError,TypeError):return False


def validate_body(raw:bytes,previous:dict|None=None)->dict:
    d=strict_json(raw,MAX_BODY)
    if set(d)!={
        "schema_version","catalog_id","release_sequence","generated_at",
        "source_radio_catalog_min_sequence","scope",
        "production_publication_allowed","selection_mode","assets",
    }:raise ArtworkBundleError("Unexpected artwork body fields")
    if (d["schema_version"]!=1 or d["catalog_id"]!=CATALOG_ID or
            d["scope"]!="TEST_ONLY" or
            d["production_publication_allowed"] is not False or
            d["selection_mode"]!="manual_visual_review_of_open_discovery_candidates" or
            not valid_date(d["generated_at"]) or
            type(d["source_radio_catalog_min_sequence"]) is not int or
            d["source_radio_catalog_min_sequence"]<4):
        raise ArtworkBundleError("Invalid TEST-only artwork identity")
    n=d["release_sequence"]
    if type(n) is not int or n<1 or \
       (previous is None and n!=1) or \
       (previous is not None and n<=previous["release_sequence"]):
        raise ArtworkBundleError("Invalid sequence or rollback")
    arr=d["assets"]
    if not isinstance(arr,list) or not 1<=len(arr)<=10000:
        raise ArtworkBundleError("Invalid image asset count")
    seen=set()
    for row in arr:
        if not isinstance(row,dict) or set(row)!={
            "legacy_media_id","station_name","logo","source","replace_existing_logo",
        }:raise ArtworkBundleError("Unexpected artwork assignment")
        u=row["legacy_media_id"]
        if not isinstance(u,str) or not UUID.fullmatch(u) or u in seen:
            raise ArtworkBundleError("Bad or repeated station UUID")
        seen.add(u)
        if (not isinstance(row["station_name"],str) or
                not row["station_name"].strip() or
                row["replace_existing_logo"] is not False):
            raise ArtworkBundleError("Replacement or unnamed station")
        logo=row["logo"]; source=row["source"]
        if not isinstance(logo,dict) or set(logo)!={
            "asset_id","sha256","url","byte_size","width","height","mime_type","revision",
        }:raise ArtworkBundleError("Malformed immutable artwork descriptor")
        sha=logo["sha256"]
        if (not isinstance(sha,str) or not SHA.fullmatch(sha) or
                logo["asset_id"]!="sha256:"+sha or
                not public_https(logo["url"]) or
                type(logo["byte_size"]) is not int or not 128<=logo["byte_size"]<=2097152 or
                type(logo["width"]) is not int or
                type(logo["height"]) is not int or
                not 192<=logo["width"]<=4096 or not 192<=logo["height"]<=4096 or
                logo["width"]*logo["height"]>12_000_000 or
                logo["mime_type"] not in ("image/jpeg","image/png","image/webp") or
                logo["revision"]!=1):
            raise ArtworkBundleError("Invalid signed image specification")
        if not isinstance(source,dict) or set(source)!={
            "provider","official_station_page","station_slug",
            "visual_identity_evidence","review_scope",
        }:raise ArtworkBundleError("Malformed first-party source evidence")
        # A signed publisher may certify any official radio/CDN, not only
        # laut.fm. Manual station-identity/visual review is still mandatory.
        # Do NOT treat the unsigned public v5 manifest as that approval.
        provider=source["provider"]
        page=source["official_station_page"]
        slug=source["station_slug"]
        visual=source["visual_identity_evidence"]
        if (not isinstance(provider,str) or not 1<=len(provider.strip())<=128 or
                not isinstance(page,str) or not public_https(page) or
                not isinstance(slug,str) or not 1<=len(slug.strip())<=160 or
                any(ord(c)<32 for c in slug) or
                source["review_scope"]!="test_only" or
                not isinstance(visual,str) or len(visual.strip())<15):
            raise ArtworkBundleError("Source/visual-identity review missing")
        # Retain the exact historic first-party constraints for all laut.fm
        # fixtures; the general path is not a bypass of their trusted mapping.
        if provider=="laut.fm" and (
                page!="https://laut.fm/"+slug or
                not re.fullmatch(r"https://assets\.laut\.fm/[a-f0-9]{24,80}",
                                 logo["url"])):
            raise ArtworkBundleError("Unverified laut.fm station-image relation")
    if [r["legacy_media_id"] for r in arr]!=sorted(seen):
        raise ArtworkBundleError("Assignments must be sorted by historical UUID")
    return d


def sign_message(p:dict)->bytes:
    return (CONTEXT+
        str(p["schema_version"])+"\n"+
        p["catalog_id"]+"\n"+
        str(p["release_sequence"])+"\n"+
        p["published_at"]+"\n"+
        p["content_sha256"]+"\n"+
        str(p["content_length"])+"\n"+
        p["content_path"]+"\n"+
        p["scope"]+"\n"+
        p["signature"]["key_id"]+"\n").encode("utf-8")


def sign_pending(body:bytes,secret:Ed25519PrivateKey,key_id:str,
                 published_at:str,previous:dict|None=None)->bytes:
    d=validate_body(body,previous)
    if not valid_date(published_at) or not isinstance(key_id,str) or not KEY.fullmatch(key_id):
        raise ArtworkBundleError("Invalid test signing metadata")
    sha=hashlib.sha256(body).hexdigest()
    p={
        "schema_version":1,"catalog_id":CATALOG_ID,
        "release_sequence":d["release_sequence"],
        "published_at":published_at,"scope":"TEST_ONLY",
        "content_sha256":sha,"content_length":len(body),
        "content_path":f"releases/{sha}.json",
        "signature":{"algorithm":"Ed25519","key_id":key_id,"signature_base64":""},
    }
    p["signature"]["signature_base64"]=base64.b64encode(
        secret.sign(sign_message(p))).decode("ascii")
    pointer=wire(p)
    verify(pointer,body,secret.public_key(),previous)
    return pointer


def verify(pointer_bytes:bytes,body:bytes,key:Ed25519PublicKey,
           previous:dict|None=None)->dict:
    p=strict_json(pointer_bytes,MAX_POINTER)
    if set(p)!={
        "schema_version","catalog_id","release_sequence","published_at",
        "scope","content_sha256","content_length","content_path","signature",
    }:raise ArtworkBundleError("Unexpected pointer fields")
    sig=p["signature"]
    if (not isinstance(sig,dict) or set(sig)!={
            "algorithm","key_id","signature_base64"} or
            sig["algorithm"]!="Ed25519" or
            not isinstance(sig["key_id"],str) or not KEY.fullmatch(sig["key_id"]) or
            p["schema_version"]!=1 or p["catalog_id"]!=CATALOG_ID or
            p["scope"]!="TEST_ONLY" or not valid_date(p["published_at"])):
        raise ArtworkBundleError("Invalid signed sidecar pointer")
    sha=hashlib.sha256(body).hexdigest()
    if (p["content_sha256"]!=sha or p["content_path"]!=f"releases/{sha}.json" or
            type(p["content_length"]) is not int or p["content_length"]!=len(body)):
        raise ArtworkBundleError("Immutable artwork body digest mismatch")
    try:
        raw=base64.b64decode(sig["signature_base64"],validate=True)
        if len(raw)!=64:raise ArtworkBundleError("Malformed Ed25519 signature")
        key.verify(raw,sign_message(p))
    except (InvalidSignature,binascii.Error,ValueError,TypeError) as e:
        raise ArtworkBundleError("Invalid TEST artwork signature") from e
    d=validate_body(body,previous)
    if d["release_sequence"]!=p["release_sequence"]:
        raise ArtworkBundleError("Sequence mismatch")
    return d


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pointer",type=Path,required=True)
    parser.add_argument("--body",type=Path,required=True)
    parser.add_argument("--trusted-public-key",type=Path,required=True)
    args=parser.parse_args()
    public=Ed25519PublicKey.from_public_bytes(
        base64.b64decode(args.trusted_public_key.read_bytes().strip(),validate=True)
    )
    verified=verify(args.pointer.read_bytes(),args.body.read_bytes(),public)
    print(json.dumps({
        "status":"GO_SIGNED_ARTWORK_TEST_PENDING_VERIFIED",
        "assets":len(verified["assets"]),
        "sequence":verified["release_sequence"],
        "production":False,
    }))


if __name__=="__main__":main()
