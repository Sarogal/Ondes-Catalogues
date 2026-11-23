#!/usr/bin/env python3
"""Final pre-signing CI for three official Radio Metal ON logos in unsigned v8.

Source of truth: real TEST v7 Ed25519 signature, immutable payload and
320 station IDs / 363 UUID favorite owners. Only three null logos may change;
verify each first-party original image by its 2nd-download SHA blob and MIME.

No signing, no TEST v7 pointer changes, no main/Play Store edits.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from radio_catalog_release_packager import read_public_key, load_verified_predecessor
from radio_catalog_guard import validate_catalog
from audit_open_radio_artwork_inventory import inspect_bytes

ROOT=Path(__file__).resolve().parents[2]
RELEASE=ROOT/"grossesondes/radio-test-v2"
DRAFT=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-metalon-3-official-logos-20261123.json"
SCHEMA=ROOT/"radio-catalog-lab/schemas/radio_catalog_v1.schema.json"
V7_SHA="f735884aa0841a86d88aaafe406e62b7a826cf9cd60f6a70285a0894326841aa"
LOGO_PREFIX=("https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
             "feature/go-radio-v8-metalon-3-logos-20261123/"
             "grossesondes/radio-test-v2/artwork/staging-metalon-v8/")
ASSETS=RELEASE/"artwork/staging-metalon-v8"
EXPECTED={
    "go-station-000218":"64b499012b0e6f64ff0eca85ef69772e6e9c800c3661d4d73dad7e0b99e41503",
    "go-station-000046":"c17784a27ff5972c60ea10c716f2921f8a60b4af9e9d2015d13da5952389a31f",
    "go-station-000024":"ca6c81dc2248f5d04c93d0e7270ec7470503295604ccccd48c8ad5",
}
EXT={"image/png":".png","image/jpeg":".jpg","image/webp":".webp"}


def check(condition,message):
    if not condition:
        raise AssertionError(message)


def main():
    pointer=json.loads((RELEASE/"current.json").read_bytes())
    check(pointer["release_sequence"]==7 and pointer["content_sha256"]==V7_SHA,
          "Active TEST pointer not signed v7")
    verified=load_verified_predecessor(
        RELEASE,read_public_key(RELEASE/"TEST_PUBLIC_KEY.b64"))
    old_bytes=(RELEASE/"releases"/(V7_SHA+".json")).read_bytes()
    check(hashlib.sha256(old_bytes).hexdigest()==V7_SHA,"Source v7 SHA changed")
    original=json.loads(old_bytes)
    check(verified==original,"Ed25519 signed predecessor differs from payload")
    nxt=json.loads(DRAFT.read_bytes())
    schema=json.loads(SCHEMA.read_bytes())
    issues=list(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(nxt))
    check(not issues,"Malformed unsigned v8 JSON schema")
    check(not validate_catalog(
        nxt,mode="publish",previous=verified,trusted_signed_history=True),
          "v8 does not meet signed predecessor publishing guard")
    check(nxt["release_sequence"]==8,"Not v8")
    check(len(nxt["stations"])==296,"A station was added or removed")
    check(len(nxt["tombstones"])==24 and nxt["tombstones"]==original["tombstones"],
          "Old signed redirects changed")
    active=[x for x in nxt["stations"] if x["status"]["state"]=="active"]
    check(len(active)==285,"Active radio count changed")
    check(sum(x["logo"] is None for x in active)==93,"Unexpected remaining missing logos")
    check(sum(x["logo"] is not None for x in active)==192,"Unexpected logo count")

    old={x["go_station_id"]:x for x in original["stations"]}
    new={x["go_station_id"]:x for x in nxt["stations"]}
    check(old.keys()==new.keys(),"GO identities changed")
    changed={goid for goid in old if old[goid]!=new[goid]}
    check(changed==set(EXPECTED),"Unrelated radio metadata edited")
    for id_,previous in old.items():
        if id_ not in EXPECTED:
            continue
        station=new[id_]
        expected=EXPECTED[id_]
        image=station["logo"]
        check(previous["status"]["state"]=="active" and previous["logo"] is None,
              "Unexpected overwritten existing station logo")
        without=dict(station);without["logo"]=None
        check(without==previous,"Radio metadata other than logo changed")
        check(image["sha256"]==expected and image["asset_id"]=="sha256:"+expected,
              "Wrong content-addressed official logo")
        ext=EXT[image["mime_type"]]
        check(image["url"]==LOGO_PREFIX+expected+ext,
              "New artwork not on reviewed development branch path")
        blob=ASSETS/(expected+ext)
        check(blob.is_file(),"Missing original image blob")
        body=blob.read_bytes()
        check(hashlib.sha256(body).hexdigest()==expected,"Official image SHA mismatch")
        metadata=inspect_bytes(body,content_type=image["mime_type"])
        check(metadata=={
            "sha256":image["sha256"],"byte_size":image["byte_size"],
            "mime_type":image["mime_type"],"width":image["width"],
            "height":image["height"]},"Official logo MIME/size/bytes mismatch")
    check(len([x for x in ASSETS.iterdir() if x.is_file()])==3,
          "Unexpected extra SHA objects")
    owners_before={u:s["go_station_id"] for s in original["stations"]+original["tombstones"]
                   for u in s["legacy_aliases"]}
    owners_after={u:s["go_station_id"] for s in nxt["stations"]+nxt["tombstones"]
                  for u in s["legacy_aliases"]}
    check(owners_before==owners_after and len(owners_before)==363,
          "Historical favorite UUID ownership changed")
    ids_before={s["go_station_id"] for s in original["stations"]+original["tombstones"]}
    ids_after={s["go_station_id"] for s in nxt["stations"]+nxt["tombstones"]}
    check(ids_before==ids_after and len(ids_before)==320,"Historical GO IDs changed")
    check(json.loads((RELEASE/"current.json").read_bytes())["release_sequence"]==7,
          "Original active TEST pointer changed")
    print(json.dumps({
        "result":"GO_RADIO_V8_METALON_3_LOGO_FULL_PRESIGN_QA_PASS",
        "signed_source":"TEST v7 Ed25519 verified",
        "active_radios":285,
        "new_verified_first_party_station_logos":3,
        "active_with_logo":192,
        "active_without_logo":93,
        "go_station_ids_preserved":320,
        "favorite_uuid_owners_preserved":363,
        "tombstone_redirects_preserved":24,
        "unsigned_only":True,
        "active_test_v7_pointer_unchanged":True,
    },sort_keys=True))


if __name__=="__main__":
    main()
