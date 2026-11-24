#!/usr/bin/env python3
"""GO TEST v8 53 original station-logo SHA/Ed25519 continuity preflight.

No signature/private key, no change to existing signed TEST v7, production,
main, or APK. All 53 station changes are strictly null->verified logo only.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib,json
from pathlib import Path
from jsonschema import Draft202012Validator,FormatChecker
from radio_catalog_release_packager import load_verified_predecessor,read_public_key
from radio_catalog_guard import validate_catalog
from audit_open_radio_artwork_inventory import inspect_bytes
from test_go_radio_v8_49_official_sha_gate import MAPPED as OLD49,SOURCE_V7,RAW
from stage_v8_four_pcradio_zeno_art import SHA as FOUR

ROOT=Path(__file__).resolve().parents[2]
SIGNED=ROOT/"grossesondes/radio-test-v2"
CANDIDATE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-53-official-sha-logos-20261123.json"
SCHEMA=ROOT/"radio-catalog-lab/schemas/radio_catalog_v1.schema.json"
MAPPED=dict(OLD49)
for sid,digest in FOUR.items():
    assert sid not in MAPPED
    MAPPED[sid]=("grossesondes/radio-test-v2/artwork/staging-four-platform-v8/",digest)
def main():
    pointer=json.loads((SIGNED/"current.json").read_bytes())
    assert pointer["release_sequence"]==7 and pointer["content_sha256"]==SOURCE_V7
    old=load_verified_predecessor(SIGNED,read_public_key(SIGNED/"TEST_PUBLIC_KEY.b64"))
    assert old["release_sequence"]==7 and len(old["stations"])==296
    doc=json.loads(CANDIDATE.read_bytes())
    schema=json.loads(SCHEMA.read_bytes())
    assert not list(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(doc))
    assert not validate_catalog(doc,mode="publish",previous=old,trusted_signed_history=True)
    assert doc["release_sequence"]==8 and len(doc["stations"])==296
    assert doc["tombstones"]==old["tombstones"] and len(doc["tombstones"])==24
    active=[s for s in doc["stations"] if s["status"]["state"]=="active"]
    assert len(active)==285
    assert sum(s["logo"] is None for s in active)==43
    assert sum(s["logo"] is not None for s in active)==242
    before={s["go_station_id"]:s for s in old["stations"]}
    now={s["go_station_id"]:s for s in doc["stations"]}
    assert before.keys()==now.keys()
    changed={sid for sid in before if before[sid]!=now[sid]}
    assert changed==set(MAPPED) and len(changed)==53
    shas=set()
    for sid in changed:
        previous=before[sid];station=now[sid]
        assert previous["logo"] is None
        blank=deepcopy(station);blank["logo"]=None
        assert blank==previous,"Unexpected change outside logo for "+sid
        directory,sha=MAPPED[sid]
        logo=station["logo"]
        extension={"image/jpeg":".jpg","image/png":".png","image/webp":".webp"}[logo["mime_type"]]
        relative=directory+sha+extension
        assert logo["sha256"]==sha and logo["asset_id"]=="sha256:"+sha
        assert logo["url"]==RAW+relative
        image=(ROOT/relative).read_bytes()
        assert hashlib.sha256(image).hexdigest()==sha
        metadata=inspect_bytes(image,content_type=logo["mime_type"])
        assert metadata=={k:logo[k] for k in ("sha256","byte_size","width","height","mime_type")}
        assert sha not in shas,"Repeated/generic image across station identities"
        shas.add(sha)
    assert len(shas)==53
    for directory,count in {
        "artwork/staging-metalon-v8/":3,
        "artwork/staging-independent-v8/":3,
        "artwork/staging-official-site-v8/":7,
        "artwork/staging-maximum-v8/":3,
        "artwork/staging-broadcasters-v8/":7,
        "artwork/staging-indep-six-v8/":6,
        "artwork/staging-exact-six-v8/":6,
        "artwork/staging-eight-more-v8/":8,
        "artwork/staging-three-more-v8/":3,
        "artwork/staging-three-further-v8/":3,
        "artwork/staging-four-platform-v8/":4,
    }.items():
        assert len(list((SIGNED/directory).iterdir()))==count
    ids=lambda c:{s["go_station_id"] for s in c["stations"]+c["tombstones"]}
    aliases=lambda c:{a:s["go_station_id"] for s in c["stations"]+c["tombstones"] for a in s["legacy_aliases"]}
    assert ids(old)==ids(doc) and len(ids(doc))==320
    assert aliases(old)==aliases(doc) and len(aliases(doc))==363
    assert json.loads((SIGNED/"current.json").read_bytes())==pointer
    print(json.dumps({
        "result":"GO_TEST_V8_53_ORIGINAL_CHANNEL_SHAS_COMPLETE_QA_PASS",
        "signed_v7_ed25519_predecessor_verified":True,
        "active_radios":285,"active_with_logo":242,"missing_logo":43,
        "verified_new_sha_objects":53,"go_ids_preserved":320,
        "favorite_uuid_owners_preserved":363,"redirects_preserved":24,
        "v8_signed":False,"v8_published":False,"active_TEST_v7_unchanged":True,
    },sort_keys=True))
if __name__=="__main__":main()
