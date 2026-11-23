#!/usr/bin/env python3
"""End-to-end GROSSES ONDES TEST v7 gate: signed v6 → 13 dedupes + 19 SHA logos.

Checks: real Ed25519 predecessor, original 13 merger guard, immutability
of all unrelated station fields, preservation of 363 UUID owners / 320 GO
IDs, 14 first-party LAUT + 4 first-party YouRadio image objects byte by byte.

No private signing seed, publisher, TEST pointer mutation or APK building.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator,FormatChecker
from radio_catalog_release_packager import load_verified_predecessor,read_public_key
from radio_catalog_guard import validate_catalog
from audit_open_radio_artwork_inventory import inspect_bytes
from test_go_radio_v7_13_dedupe import main as test_merges

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v7-13-programs-dedupe-20261123.json"
TARGET=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v7-13-programs-lautfm-14-exclusive-5-20261123.json"
SCHEMA=ROOT/"radio-catalog-lab/schemas/radio_catalog_v1.schema.json"
SIGNED=ROOT/"grossesondes/radio-test-v2"
SHA_V6="40215a58967a8b7a83b322c9f02645a9bc2bf319385442e5d89277e0b0d6d861"
PREFIX="https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/feature/go-radio-v7-13-dedupe-20261123/"
EXPECTED_DIRECTORIES={
    "grossesondes/radio-test-v2/artwork/staging-lautfm-v7/":14,
    "grossesondes/radio-test-v2/artwork/staging-exclusive-v7/":4,
}
ALLOWED_EXT={"image/jpeg":"jpg","image/png":"png","image/webp":"webp"}


def main()->None:
    test_merges()
    ptr=json.loads((SIGNED/"current.json").read_bytes())
    assert ptr["release_sequence"]==6 and ptr["content_sha256"]==SHA_V6
    previous=load_verified_predecessor(SIGNED,read_public_key(SIGNED/"TEST_PUBLIC_KEY.b64"))
    baseline=json.loads(BASE.read_bytes())
    target=json.loads(TARGET.read_bytes())
    schema=json.loads(SCHEMA.read_bytes())
    errs=list(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(target))
    assert not errs,[(x.json_path,x.message) for x in errs[:5]]
    guard=validate_catalog(target,mode="publish",previous=previous,
                           trusted_signed_history=True)
    assert not guard,guard[:8]
    assert target["release_sequence"]==7
    assert len(target["stations"])==296
    assert len(target["tombstones"])==24
    assert baseline["tombstones"]==target["tombstones"]
    assert sum(x["status"]["state"]=="active" for x in target["stations"])==285
    assert sum(x["logo"] is not None for x in target["stations"])==194
    assert sum(x["status"]["state"]=="active" and x["logo"] is not None
               for x in target["stations"])==189
    assert sum(x["status"]["state"]=="active" and x["logo"] is None
               for x in target["stations"])==96

    old={x["go_station_id"]:x for x in baseline["stations"]}
    new={x["go_station_id"]:x for x in target["stations"]}
    assert old.keys()==new.keys()
    changed=[]
    references={}
    for goid,s in new.items():
        before=old[goid]
        if before==s:
            continue
        assert before["logo"] is None and s["logo"] is not None,goid
        after_without_logo=dict(s)
        after_without_logo["logo"]=None
        assert before==after_without_logo,"Unreviewed metadata/stream mutation "+goid
        logo=s["logo"]
        sha=logo["sha256"]
        assert logo["asset_id"]=="sha256:"+sha
        assert sha==sha.lower() and len(sha)==64
        ext=ALLOWED_EXT[logo["mime_type"]]
        directory=next((key for key in EXPECTED_DIRECTORIES
                        if logo["url"].startswith(PREFIX+key)),None)
        assert directory is not None,"Logo URL is not an immutable dev SHA object"
        assert logo["url"]==PREFIX+directory+sha+"."+ext
        blob_path=ROOT/directory/(sha+"."+ext)
        assert blob_path.is_file() and not blob_path.is_symlink()
        raw=blob_path.read_bytes()
        assert hashlib.sha256(raw).hexdigest()==sha
        actual=inspect_bytes(raw,content_type=logo["mime_type"])
        assert actual=={
            "sha256":sha,"byte_size":logo["byte_size"],
            "width":logo["width"],"height":logo["height"],
            "mime_type":logo["mime_type"],
        }
        references.setdefault(directory,set()).add(sha)
        changed.append(goid)
    assert len(changed)==19
    assert {key:len(val) for key,val in references.items()}==EXPECTED_DIRECTORIES
    assert set(changed)=={
        'go-station-000040','go-station-000056','go-station-000066',
        'go-station-000070','go-station-000075','go-station-000078',
        'go-station-000082','go-station-000124','go-station-000127',
        'go-station-000135','go-station-000162','go-station-000166',
        'go-station-000169','go-station-000315','go-station-000204',
        'go-station-000272','go-station-000274','go-station-000299',
        'go-station-000311',
    }
    assert new["go-station-000204"]["logo"]["sha256"]==(
        new["go-station-000274"]["logo"]["sha256"])
    assert (new["go-station-000204"]["streams"][0]["url"]!=
            new["go-station-000274"]["streams"][0]["url"]),(
             "Do not fuse the separate regular and Hits radio channels")
    all_ids_old={x["go_station_id"] for x in previous["stations"]+previous["tombstones"]}
    all_ids_new={x["go_station_id"] for x in target["stations"]+target["tombstones"]}
    assert all_ids_old==all_ids_new and len(all_ids_old)==320
    prev_uuids={a:x["go_station_id"] for x in previous["stations"]+previous["tombstones"]
                for a in x["legacy_aliases"]}
    next_uuids={a:x["go_station_id"] for x in target["stations"]+target["tombstones"]
                for a in x["legacy_aliases"]}
    assert prev_uuids==next_uuids and len(prev_uuids)==363
    assert json.loads((SIGNED/"current.json").read_bytes())["release_sequence"]==6

    print(json.dumps({
        "result":"GO_RADIO_TEST_V7_FULL_PRE_SIGNING_QA_PASS",
        "source_verified":"Ed25519 signed v6",
        "groups_consolidated":13,
        "active_before":304,
        "active_after":285,
        "historical_go_ids":320,
        "legacy_uuids_preserved":363,
        "signed_redirect_tombstones_in_candidate":24,
        "new_logo_station_descriptors":19,
        "new_sha_objects":18,
        "active_logos_after":189,
        "active_without_logo_after":96,
        "candidate_signed":False,
        "candidate_published":False,
        "v6_test_pointer_unchanged":True,
    },sort_keys=True))


if __name__=="__main__":
    main()
