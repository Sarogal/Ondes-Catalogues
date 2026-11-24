#!/usr/bin/env python3
"""Final TEST v8 six-logo proof against genuine signed v7 with 363 favorite UUIDs.

3 Radio Metal ON logos + 3 other first-party publisher station images.
Validate every new asset from immutable SHA Git blobs, unchanged station
streams, identities, quarantines, 24 redirects, prior Ed25519-signature and
strict JSON/authoritative catalog publication guard. NO publishing/signing.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator,FormatChecker
from radio_catalog_release_packager import load_verified_predecessor,read_public_key
from radio_catalog_guard import validate_catalog
from audit_open_radio_artwork_inventory import inspect_bytes

ROOT=Path(__file__).resolve().parents[2]
SIGNED=ROOT/"grossesondes/radio-test-v2"
DRAFT=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-metalon-3-independent-3-20261123.json"
SCHEMA=ROOT/"radio-catalog-lab/schemas/radio_catalog_v1.schema.json"
BEFORE="f735884aa0841a86d88aaafe406e62b7a826cf9cd60f6a70285a0894326841aa"
PATH_BASE=("https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
           "feature/go-radio-v8-metalon-3-logos-20261123/")
LOGOS={
 "go-station-000218":("artwork/staging-metalon-v8/","64b499012b0e6f64ff0eca85ef69772e6e9c800c3661d4d73dad7e0b99e41503"),
 "go-station-000046":("artwork/staging-metalon-v8/","c17784a27ff5972c60ea10c716f2921f8a60b4af9e9d2015d13da5952389a31f"),
 "go-station-000024":("artwork/staging-metalon-v8/","ca6c81dc2248f5d04c93d0e7270ec7470503295604ccccd48c8d45545c7c8ad5"),
 "go-station-000006":("artwork/staging-independent-v8/","fdf5abb4bfb0837aa5ace1b1ebcd486d25eeee9ca976fbecdd7c0389117dcd99"),
 "go-station-000091":("artwork/staging-independent-v8/","f81d40082d032ac3511f979906ac6d71e025dd83b1729ab958d05668b6e7b175"),
 "go-station-000101":("artwork/staging-independent-v8/","6053589f3889f33ab799c196162c49436f11d24a63bbefebcc9d18bda1983b6d"),
}
EXT={"image/jpeg":".jpg","image/png":".png","image/webp":".webp"}


def check(cond:bool,msg:str)->None:
    if not cond:
        raise AssertionError(msg)


def main()->None:
    ptr=json.loads((SIGNED/"current.json").read_bytes())
    check(ptr["release_sequence"]==7 and ptr["content_sha256"]==BEFORE,
          "TEST active predecessor changed")
    signed=load_verified_predecessor(SIGNED,read_public_key(SIGNED/"TEST_PUBLIC_KEY.b64"))
    check(signed["release_sequence"]==7 and len(signed["stations"])==296,
          "Original Ed25519 TEST v7 missing")
    new=json.loads(DRAFT.read_bytes())
    schema=json.loads(SCHEMA.read_bytes())
    errors=list(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(new))
    check(not errors,"v8 JSON schema errors")
    check(not validate_catalog(new,mode="publish",previous=signed,
                               trusted_signed_history=True),
          "Signed v7->v8 publishing guard failed")
    check(new["release_sequence"]==8,"Wrong new release sequence")
    check(len(new["stations"])==296 and len(new["tombstones"])==24,
          "Unexpected station or tombstone count")
    check(new["tombstones"]==signed["tombstones"],
          "Previous signed redirect changed")
    active=[x for x in new["stations"] if x["status"]["state"]=="active"]
    check(len(active)==285 and sum(x["logo"] is None for x in active)==90,
          "Incorrect radio/added-logo coverage")
    check(sum(x["logo"] is not None for x in active)==195,
          "Missing one of 6 official logos")
    old={x["go_station_id"]:x for x in signed["stations"]}
    newer={x["go_station_id"]:x for x in new["stations"]}
    check(old.keys()==newer.keys(),"Identity lost")
    change={id_ for id_ in old if old[id_]!=newer[id_]}
    check(change==set(LOGOS),"Only six verified official logo rows can change")
    for id_ in change:
        s=newer[id_]
        without=deepcopy(s);without["logo"]=None
        check(without==old[id_],"Unreviewed non-logo edit in "+id_)
        part,digest=LOGOS[id_]
        m=s["logo"]
        check(m["sha256"]==digest and m["asset_id"]=="sha256:"+digest,
              "Wrong official station asset SHA")
        extension=EXT[m["mime_type"]]
        path="grossesondes/radio-test-v2/"+part+digest+extension
        check(m["url"]==PATH_BASE+path,"Unstable or incorrect URL for "+id_)
        blob=ROOT/path
        check(blob.is_file() and not blob.is_symlink(),"Missing SHA blob "+id_)
        body=blob.read_bytes()
        check(hashlib.sha256(body).hexdigest()==digest,"SHA mismatch "+id_)
        actual=inspect_bytes(body,content_type=m["mime_type"])
        check(actual=={
            "sha256":m["sha256"],"byte_size":m["byte_size"],
            "width":m["width"],"height":m["height"],
            "mime_type":m["mime_type"],
        },"Image dimensions/MIME/length wrong for "+id_)
    for directory in {part for part,_ in LOGOS.values()}:
        folder=SIGNED/directory
        check(len([f for f in folder.iterdir() if f.is_file()])==3,
              "Unexpected number of immutable official images")
    ids_old={x["go_station_id"] for x in signed["stations"]+signed["tombstones"]}
    ids_new={x["go_station_id"] for x in new["stations"]+new["tombstones"]}
    check(ids_old==ids_new and len(ids_old)==320,
          "Historical GO IDs were not preserved")
    alias_old={a:s["go_station_id"] for s in signed["stations"]+signed["tombstones"]
               for a in s["legacy_aliases"]}
    alias_new={a:s["go_station_id"] for s in new["stations"]+new["tombstones"]
               for a in s["legacy_aliases"]}
    check(alias_old==alias_new and len(alias_old)==363,
          "Favorites historical alias ownership changed")
    check(json.loads((SIGNED/"current.json").read_bytes())["release_sequence"]==7,
          "Active signed v7 pointer must remain unchanged")
    print(json.dumps({
        "result":"GO_RADIO_TEST_V8_SIX_FIRST_PARTY_SHA_FINAL_QA_PASS",
        "signed_predecessor":"Ed25519 v7 verified",
        "active_radios":285,
        "with_logo":195,
        "without_logo":90,
        "sha_objects_verified":6,
        "historical_go_ids":320,
        "historical_favorite_aliases":363,
        "redirects":24,
        "signed":False,
        "published":False,
    },sort_keys=True))


if __name__=="__main__":
    main()
