#!/usr/bin/env python3
"""Gate 29 official original image SHA blobs against real signed TEST v7 Ed25519.

Never sign/publish, mutate TEST current pointer, APK, main, or production.
Preserves all 320 GO station IDs, 363 alias/UUID owners, 24 redirects.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib,json
from pathlib import Path
from jsonschema import Draft202012Validator,FormatChecker
from radio_catalog_release_packager import load_verified_predecessor,read_public_key
from radio_catalog_guard import validate_catalog
from audit_open_radio_artwork_inventory import inspect_bytes
from test_go_radio_v8_23_official_sha_gate import MAPPING as FIRST23,SOURCE_V7
from stage_v8_six_more_official_logos import SHAS as NEW6

ROOT=Path(__file__).resolve().parents[2]
SIGNED=ROOT/"grossesondes/radio-test-v2"
CANDIDATE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-metalon-3-independent-3-firstparty-7-maximum-3-broadcaster-7-indep6-20261123.json"
SCHEMA=ROOT/"radio-catalog-lab/schemas/radio_catalog_v1.schema.json"
RAW="https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/feature/go-radio-v8-metalon-3-logos-20261123/"
ALL=dict(FIRST23)
for sid,sha in NEW6.items():
    assert sid not in ALL
    ALL[sid]=("grossesondes/radio-test-v2/artwork/staging-indep-six-v8/",sha)
def run():
    ptr=json.loads((SIGNED/"current.json").read_bytes())
    assert ptr["release_sequence"]==7 and ptr["content_sha256"]==SOURCE_V7
    old=load_verified_predecessor(SIGNED,read_public_key(SIGNED/"TEST_PUBLIC_KEY.b64"))
    assert old["release_sequence"]==7
    current=json.loads(CANDIDATE.read_bytes())
    schema=json.loads(SCHEMA.read_bytes())
    assert not list(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(current))
    assert not validate_catalog(current,mode="publish",previous=old,
                               trusted_signed_history=True)
    assert current["release_sequence"]==8 and len(current["stations"])==296
    assert current["tombstones"]==old["tombstones"] and len(current["tombstones"])==24
    active=[s for s in current["stations"] if s["status"]["state"]=="active"]
    assert len(active)==285
    assert sum(s["logo"] is not None for s in active)==218
    assert sum(s["logo"] is None for s in active)==67
    prev={s["go_station_id"]:s for s in old["stations"]}
    next_={s["go_station_id"]:s for s in current["stations"]}
    assert prev.keys()==next_.keys()
    changed={sid for sid in prev if prev[sid]!=next_[sid]}
    assert changed==set(ALL) and len(changed)==29
    digests=set()
    for sid in changed:
        station=next_[sid]
        assert prev[sid]["logo"] is None
        copy=deepcopy(station);copy["logo"]=None
        assert copy==prev[sid], "Unrelated field changed "+sid
        folder,sha=ALL[sid]
        logo=station["logo"]
        suffix={"image/jpeg":".jpg","image/png":".png","image/webp":".webp"}[logo["mime_type"]]
        relative=folder+sha+suffix
        assert logo["sha256"]==sha and logo["asset_id"]=="sha256:"+sha
        assert logo["url"]==RAW+relative
        img=(ROOT/relative).read_bytes()
        assert hashlib.sha256(img).hexdigest()==sha
        decoded=inspect_bytes(img,content_type=logo["mime_type"])
        assert decoded=={k:logo[k] for k in ("sha256","byte_size","width","height","mime_type")}
        assert sha not in digests, "Duplicated/generic logo for different station"
        digests.add(sha)
    assert len(digests)==29
    for folder,num in {
      "grossesondes/radio-test-v2/artwork/staging-metalon-v8/":3,
      "grossesondes/radio-test-v2/artwork/staging-independent-v8/":3,
      "grossesondes/radio-test-v2/artwork/staging-official-site-v8/":7,
      "grossesondes/radio-test-v2/artwork/staging-maximum-v8/":3,
      "grossesondes/radio-test-v2/artwork/staging-broadcasters-v8/":7,
      "grossesondes/radio-test-v2/artwork/staging-indep-six-v8/":6,
    }.items():
        assert len(list((ROOT/folder).iterdir()))==num
    ids=lambda cat:{s["go_station_id"] for s in cat["stations"]+cat["tombstones"]}
    owners=lambda cat:{a:s["go_station_id"] for s in cat["stations"]+cat["tombstones"] for a in s["legacy_aliases"]}
    assert ids(old)==ids(current) and len(ids(current))==320
    assert owners(old)==owners(current) and len(owners(current))==363
    assert json.loads((SIGNED/"current.json").read_bytes())==ptr
    print(json.dumps({
        "result":"GO_TEST_V8_29_ORIGINAL_SHA_RADIO_LOGOS_COMPLETE_QA_PASS",
        "signed_v7_ed25519_predecessor_verified":True,
        "active_radios":285,"active_logos":218,"remaining_without_logo":67,
        "new_images_verified_sha256":29,
        "go_ids_preserved":320,"favorite_uuids_preserved":363,
        "redirects_preserved":24,"v8_signed":False,"v8_published":False,
        "active_test_v7_unchanged":True
    },sort_keys=True))
if __name__=="__main__":run()
