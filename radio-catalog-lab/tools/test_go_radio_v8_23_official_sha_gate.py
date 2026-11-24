#!/usr/bin/env python3
"""Strict unsigned TEST v8 audit: 23 original first-party radio logo SHA assets.

Compares latest unsigned v8 only against the genuine Ed25519-signed TEST
v7 predecessor, checks schema, 320 GO IDs, 363 UUID ownership, 24 redirects,
no unrelated station fields, 23 decoded image files and immutable URLs.
Never signs or publishes a release.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib,json
from pathlib import Path
from jsonschema import Draft202012Validator,FormatChecker
from radio_catalog_release_packager import load_verified_predecessor,read_public_key
from radio_catalog_guard import validate_catalog
from audit_open_radio_artwork_inventory import inspect_bytes
from test_go_radio_v8_16_firstparty_sha_gate import MAP as FIRST_16,SOURCE_V7
from stage_v8_seven_broadcaster_logos import SHA as NEW_7

ROOT=Path(__file__).resolve().parents[2]
SIGNED=ROOT/"grossesondes/radio-test-v2"
DOC=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-metalon-3-independent-3-firstparty-7-maximum-3-broadcaster-7-20261123.json"
SCHEMA=ROOT/"radio-catalog-lab/schemas/radio_catalog_v1.schema.json"
URL=("https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
     "feature/go-radio-v8-metalon-3-logos-20261123/")
MAPPING=dict(FIRST_16)
for sid,sha in NEW_7.items():
    assert sid not in MAPPING
    MAPPING[sid]=("grossesondes/radio-test-v2/artwork/staging-broadcasters-v8/",sha)

def main():
    ptr=json.loads((SIGNED/"current.json").read_bytes())
    assert ptr["release_sequence"]==7 and ptr["content_sha256"]==SOURCE_V7
    source=load_verified_predecessor(SIGNED,read_public_key(SIGNED/"TEST_PUBLIC_KEY.b64"))
    assert source["release_sequence"]==7
    candidate=json.loads(DOC.read_bytes())
    schema=json.loads(SCHEMA.read_bytes())
    assert not list(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(candidate))
    assert not validate_catalog(candidate,mode="publish",previous=source,
                                trusted_signed_history=True)
    assert candidate["release_sequence"]==8
    assert len(candidate["stations"])==296
    assert candidate["tombstones"]==source["tombstones"] and len(source["tombstones"])==24
    active=[s for s in candidate["stations"] if s["status"]["state"]=="active"]
    assert len(active)==285
    assert sum(s["logo"] is not None for s in active)==212
    assert sum(s["logo"] is None for s in active)==73
    old={s["go_station_id"]:s for s in source["stations"]}
    new={s["go_station_id"]:s for s in candidate["stations"]}
    assert old.keys()==new.keys()
    changed={sid for sid in old if old[sid]!=new[sid]}
    assert changed==set(MAPPING) and len(changed)==23
    seen=set()
    for sid in changed:
        past=old[sid];now=new[sid]
        assert past["logo"] is None
        without=deepcopy(now);without["logo"]=None
        assert without==past,"Non-logo field mutated for "+sid
        directory,sha=MAPPING[sid]
        d=now["logo"]
        suffix={"image/jpeg":".jpg","image/png":".png","image/webp":".webp"}[d["mime_type"]]
        path=directory+sha+suffix
        assert d["asset_id"]=="sha256:"+sha
        assert d["sha256"]==sha and d["url"]==URL+path
        data=(ROOT/path).read_bytes()
        assert hashlib.sha256(data).hexdigest()==sha
        assert inspect_bytes(data,content_type=d["mime_type"])=={
            k:d[k] for k in ("sha256","byte_size","width","height","mime_type")
        }
        assert sha not in seen,"Repeated generic image object across stations"
        seen.add(sha)
    assert len(seen)==23
    for path,count in {
      "grossesondes/radio-test-v2/artwork/staging-metalon-v8/":3,
      "grossesondes/radio-test-v2/artwork/staging-independent-v8/":3,
      "grossesondes/radio-test-v2/artwork/staging-official-site-v8/":7,
      "grossesondes/radio-test-v2/artwork/staging-maximum-v8/":3,
      "grossesondes/radio-test-v2/artwork/staging-broadcasters-v8/":7,
    }.items():
        assert len(list((ROOT/path).iterdir()))==count
    ids=lambda doc:{s["go_station_id"] for s in doc["stations"]+doc["tombstones"]}
    aliases=lambda doc:{alias:s["go_station_id"]
            for s in doc["stations"]+doc["tombstones"]
            for alias in s["legacy_aliases"]}
    assert ids(source)==ids(candidate) and len(ids(candidate))==320
    assert aliases(source)==aliases(candidate) and len(aliases(candidate))==363
    assert json.loads((SIGNED/"current.json").read_bytes())==ptr
    print(json.dumps({
      "result":"GO_V8_23_OFFICIAL_SHA_LOGOS_SIGNABLE_QA_PASS",
      "signed_v7_verified":True,"active_radios":285,
      "with_logo":212,"missing_logo":73,"new_image_shas":23,
      "go_ids_preserved":320,"favorite_uuids_preserved":363,
      "redirects_preserved":24,"v8_signed":False,"v8_published":False,
      "active_test_v7_unchanged":True
    },sort_keys=True))
if __name__=="__main__":main()
