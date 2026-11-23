#!/usr/bin/env python3
"""Complete unsigned GO TEST v8 candidate safety gate: 13 publisher logos.

Reads the real, Ed25519-verified active signed TEST v7. Compares the
13-logo candidate with the signed catalog, requiring only 13 previously
null logo fields to change. Verifies 13 immutable content-addressed images
byte-for-byte, all 320 GO station IDs, 363 original UUID owners, 24
signed redirect tombstones, active streams and original station metadata.

No signing, no APK recompilation, no live TEST or production publication.
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
from test_go_radio_v8_six_logo_full_gate import LOGOS as ORIGINAL_SIX
from stage_v8_seven_official_site_brand_logos import APPROVED as SEVEN

ROOT=Path(__file__).resolve().parents[2]
SIGNED=ROOT/"grossesondes/radio-test-v2"
CANDIDATE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-metalon-3-independent-3-firstparty-7-20261123.json"
SCHEMA=ROOT/"radio-catalog-lab/schemas/radio_catalog_v1.schema.json"
BASE_URL=("https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
          "feature/go-radio-v8-metalon-3-logos-20261123/")
SOURCE_V7="f735884aa0841a86d88aaafe406e62b7a826cf9cd60f6a70285a0894326841aa"
EXT={"image/jpeg":".jpg","image/png":".png","image/webp":".webp"}
MAPPED={
    k:("grossesondes/radio-test-v2/"+part,sha)
    for k,(part,sha) in ORIGINAL_SIX.items()
}
for id_,(_,_,sha) in SEVEN.items():
    if id_ in MAPPED:
        raise AssertionError("13 source identities overlap")
    MAPPED[id_]=(
        "grossesondes/radio-test-v2/artwork/staging-official-site-v8/",sha)


def check(ok:bool,message:str)->None:
    if not ok:
        raise AssertionError(message)


def main():
    pointer=json.loads((SIGNED/"current.json").read_bytes())
    check(pointer["release_sequence"]==7 and pointer["content_sha256"]==SOURCE_V7,
          "Active TEST v7 pointer changed during dev audit")
    old=load_verified_predecessor(SIGNED,read_public_key(SIGNED/"TEST_PUBLIC_KEY.b64"))
    check(old["release_sequence"]==7 and len(old["stations"])==296,
          "Not the expected Ed25519 signed v7")
    doc=json.loads(CANDIDATE.read_bytes())
    schema=json.loads(SCHEMA.read_bytes())
    errors=list(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(doc))
    check(not errors,"Unsigned v8 JSON Schema validation failed")
    check(not validate_catalog(doc,mode="publish",previous=old,
                               trusted_signed_history=True),
          "Signed predecessor continuity/publication guard rejected v8")
    check(doc["release_sequence"]==8,"Not TEST v8 unsigned candidate")
    check(len(doc["stations"])==296 and len(doc["tombstones"])==24,
          "Unexpected active/quarantined station or tombstone count")
    check(doc["tombstones"]==old["tombstones"],"Pre-existing signed redirects changed")
    active=[s for s in doc["stations"] if s["status"]["state"]=="active"]
    check(len(active)==285,"Radio active count changed")
    check(sum(s["logo"] is not None for s in active)==202 and
          sum(s["logo"] is None for s in active)==83,
          "Incorrect 13 new logos coverage")
    old_st={s["go_station_id"]:s for s in old["stations"]}
    new_st={s["go_station_id"]:s for s in doc["stations"]}
    check(old_st.keys()==new_st.keys(),"Radio disappeared or was introduced")
    mutated={id_ for id_ in old_st if old_st[id_]!=new_st[id_]}
    check(mutated==set(MAPPED) and len(mutated)==13,
          "Unexpected modifications outside 13 permitted station logos")

    all_sha=set()
    by_dir={}
    for id_ in sorted(mutated):
        before=old_st[id_]
        now=new_st[id_]
        no_logo=deepcopy(now);no_logo["logo"]=None
        check(before["logo"] is None and no_logo==before,
              "Changes outside artwork descriptor for "+id_)
        directory,expected=MAPPED[id_]
        desc=now["logo"]
        extension=EXT.get(desc["mime_type"])
        check(extension is not None and
              desc["asset_id"]=="sha256:"+expected and
              desc["sha256"]==expected,
              "Wrong content-addressed publisher image for "+id_)
        relative=directory+expected+extension
        check(desc["url"]==BASE_URL+relative,
              "Unsigned v8 artwork URL not immutable dev SHA path")
        file=ROOT/relative
        check(file.is_file() and not file.is_symlink(),
              "New official SHA file missing")
        original=file.read_bytes()
        check(hashlib.sha256(original).hexdigest()==expected,
              "Image bytes SHA mismatch")
        decoded=inspect_bytes(original,content_type=desc["mime_type"])
        check(decoded=={
            "sha256":expected,
            "byte_size":desc["byte_size"],
            "width":desc["width"],
            "height":desc["height"],
            "mime_type":desc["mime_type"],
        },"Image bytes size/MIME/dimensions mismatch")
        check(expected not in all_sha,"Unexpected duplicate SHA logo among different sources")
        all_sha.add(expected)
        by_dir[directory]=by_dir.get(directory,0)+1
    check(len(all_sha)==13,"Missing one of 13 firstparty publisher SHA objects")
    check(sorted(by_dir.values())==[3,3,7],
          "Official original image files grouped incorrectly")
    for directory,count in by_dir.items():
        check(len([x for x in (ROOT/directory).iterdir() if x.is_file()])==count,
              "Extra object inserted in original SHA directory")

    ids_old={s["go_station_id"] for s in old["stations"]+old["tombstones"]}
    ids_new={s["go_station_id"] for s in doc["stations"]+doc["tombstones"]}
    check(ids_old==ids_new and len(ids_new)==320,"GO ID continuity violation")
    aliases_before={a:s["go_station_id"] for s in old["stations"]+old["tombstones"]
                    for a in s["legacy_aliases"]}
    aliases_after={a:s["go_station_id"] for s in doc["stations"]+doc["tombstones"]
                   for a in s["legacy_aliases"]}
    check(aliases_before==aliases_after and len(aliases_after)==363,
          "Historical favorite UUID owner changed")
    check(json.loads((SIGNED/"current.json").read_bytes())["release_sequence"]==7,
          "Live TEST pointer changed")
    print(json.dumps({
        "result":"GO_RADIO_TEST_V8_13_FIRSTPARTY_SHA_COMPLETE_QA_PASS",
        "source":"ED25519_SIGNED_TEST_V7_VERIFIED",
        "active_stations":285,
        "active_logos_after":202,
        "active_without_logo_after":83,
        "new_logo_descriptors":13,
        "new_original_sha_blobs":13,
        "go_station_ids_preserved":320,
        "favorite_uuids_preserved":363,
        "tombstones_preserved":24,
        "v8_signed":False,
        "v8_published":False,
        "live_test_v7_unchanged":True,
    },sort_keys=True))


if __name__=="__main__":
    main()
