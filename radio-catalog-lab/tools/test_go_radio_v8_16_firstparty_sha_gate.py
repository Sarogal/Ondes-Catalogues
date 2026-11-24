#!/usr/bin/env python3
"""Final Ed25519 predecessor + all 16 distinct radio logo originals v8 gate."""
from __future__ import annotations
from copy import deepcopy
import hashlib,json
from pathlib import Path
from jsonschema import Draft202012Validator,FormatChecker
from radio_catalog_release_packager import load_verified_predecessor,read_public_key
from radio_catalog_guard import validate_catalog
from audit_open_radio_artwork_inventory import inspect_bytes
from test_go_radio_v8_13_official_sha_gate import MAPPED as THIRTEEN, SOURCE_V7
from stage_v8_maximum_three_channel_logos import EXPECTED as MAXIMUM

ROOT=Path(__file__).resolve().parents[2]
SIGNED=ROOT/"grossesondes/radio-test-v2"
DOC=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-metalon-3-independent-3-firstparty-7-maximum-3-20261123.json"
SCHEMA=ROOT/"radio-catalog-lab/schemas/radio_catalog_v1.schema.json"
BASE=("https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
      "feature/go-radio-v8-metalon-3-logos-20261123/")
MAP=dict(THIRTEEN)
for sid,sha in MAXIMUM.items():
    assert sid not in MAP
    MAP[sid]=("grossesondes/radio-test-v2/artwork/staging-maximum-v8/",sha)

def main():
    ptr=json.loads((SIGNED/"current.json").read_bytes())
    assert ptr["release_sequence"]==7 and ptr["content_sha256"]==SOURCE_V7
    old=load_verified_predecessor(SIGNED,read_public_key(SIGNED/"TEST_PUBLIC_KEY.b64"))
    assert old["release_sequence"]==7
    doc=json.loads(DOC.read_bytes())
    schema=json.loads(SCHEMA.read_bytes())
    assert not list(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(doc))
    assert not validate_catalog(doc,mode="publish",previous=old,
                                trusted_signed_history=True)
    assert doc["release_sequence"]==8 and len(doc["stations"])==296
    assert doc["tombstones"]==old["tombstones"] and len(doc["tombstones"])==24
    active=[x for x in doc["stations"] if x["status"]["state"]=="active"]
    assert len(active)==285
    assert sum(x["logo"] is not None for x in active)==205
    assert sum(x["logo"] is None for x in active)==80
    before={x["go_station_id"]:x for x in old["stations"]}
    after={x["go_station_id"]:x for x in doc["stations"]}
    assert before.keys()==after.keys()
    changed={sid for sid in before if before[sid]!=after[sid]}
    assert changed==set(MAP) and len(changed)==16
    all_hashes=set()
    for sid in changed:
        b=before[sid];a=after[sid]
        assert b["logo"] is None
        x=deepcopy(a);x["logo"]=None
        assert x==b, "Unexpected non-logo edit in "+sid
        directory,sha=MAP[sid]
        desc=a["logo"]
        ext={"image/jpeg":".jpg","image/png":".png","image/webp":".webp"}[desc["mime_type"]]
        loc=directory+sha+ext
        assert desc["sha256"]==sha and desc["asset_id"]=="sha256:"+sha
        assert desc["url"]==BASE+loc
        payload=(ROOT/loc).read_bytes()
        assert hashlib.sha256(payload).hexdigest()==sha
        assert inspect_bytes(payload,content_type=desc["mime_type"])=={
            k:desc[k] for k in ("sha256","byte_size","width","height","mime_type")}
        assert sha not in all_hashes,"Duplicated logo blobs"
        all_hashes.add(sha)
    assert len(all_hashes)==16
    for directory,count in {
      "grossesondes/radio-test-v2/artwork/staging-metalon-v8/":3,
      "grossesondes/radio-test-v2/artwork/staging-independent-v8/":3,
      "grossesondes/radio-test-v2/artwork/staging-official-site-v8/":7,
      "grossesondes/radio-test-v2/artwork/staging-maximum-v8/":3,
    }.items():
        assert len(list((ROOT/directory).iterdir()))==count
    ids=lambda d:{s["go_station_id"] for s in d["stations"]+d["tombstones"]}
    aliases=lambda d:{a:s["go_station_id"] for s in d["stations"]+d["tombstones"]
                      for a in s["legacy_aliases"]}
    assert ids(old)==ids(doc) and len(ids(doc))==320
    assert aliases(old)==aliases(doc) and len(aliases(doc))==363
    assert json.loads((SIGNED/"current.json").read_bytes())==ptr
    print(json.dumps({
      "result":"GO_V8_16_FIRSTPARTY_ORIGINAL_SHAS_COMPLETE_QA_PASS",
      "signed_v7_verified":True,"active_stations":285,
      "logo_covered":205,"logo_missing":80,"new_sha_files":16,
      "go_station_ids":320,"favorite_uuid_owners":363,"redirects":24,
      "v8_signed":False,"v8_published":False,"active_test_v7_unchanged":True
    },sort_keys=True))
if __name__=="__main__":main()
