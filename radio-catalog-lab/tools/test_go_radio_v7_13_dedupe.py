#!/usr/bin/env python3
"""Audited UNSIGNED TEST v7 checks against the REAL Ed25519-signed TEST v6.

13 program-equivalent groups, 19 new tombstone redirects, 320 historical GO
IDs and ALL UUID owners preserved. Sound files are not streamed by the gate;
it checks exact broadcaster stream identifiers and each preserved variant.
No push, signing, pointer changes or APK publication.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from radio_catalog_guard import validate_catalog
from radio_catalog_release_packager import load_verified_predecessor, read_public_key

ROOT=Path(__file__).resolve().parents[2]
TEST=ROOT/"grossesondes/radio-test-v2"
V7=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v7-13-programs-dedupe-20261123.json"
PLAN=ROOT/"radio-catalog-lab/audits/2026-11-23/v7-13-group-merge-plan.json"
SCHEMA=ROOT/"radio-catalog-lab/schemas/radio_catalog_v1.schema.json"
EXPECTED_V6="40215a58967a8b7a83b322c9f02645a9bc2bf319385442e5d89277e0b0d6d861"
V2_PUBLIC_SHA="94dc2c933c5d909498987195855d121d10a7edc56a9d879b48aa1a01fdcaa18b"
EXPECTED_SURVIVORS={
    "go-station-000290":("000003","000139"),
    "go-station-000159":("000013","000253"),
    "go-station-000131":("000106",),
    "go-station-000158":("000238",),
    "go-station-000250":("000276",),
    "go-station-000049":("000231",),
    "go-station-000300":("000061",),
    "go-station-000119":("000072",),
    "go-station-000288":("000112",),
    "go-station-000185":("000060","000097","000149"),
    "go-station-000177":("000143","000208","000269"),
    "go-station-000073":("000148",),
    "go-station-000150":("000105",),
}
SAFE_PRIMARY_URLS={
    "go-station-000177":"https://streams.fluxfm.de/metalfm/mp3-128/fluxfm.de_webplayer/",
    "go-station-000073":"https://stream.rockantenne.de/heavy-metal/stream/aacp",
    "go-station-000150":"https://radios.rtbf.be/wr-c21-metal-128.mp3",
}


def check(ok:bool,message:str)->None:
    if not ok:
        raise AssertionError(message)


def main()->None:
    pointer=json.loads((TEST/"current.json").read_bytes())
    check(pointer["release_sequence"]==6, "source is not TEST v6")
    check(pointer["content_sha256"]==EXPECTED_V6, "unexpected signed TEST v6 SHA")
    pub=(TEST/"TEST_PUBLIC_KEY.b64").read_bytes().strip()
    import base64
    check(hashlib.sha256(base64.b64decode(pub,validate=True)).hexdigest()
          ==V2_PUBLIC_SHA, "not the same TEST v2 Ed25519 key")
    prev=load_verified_predecessor(TEST,read_public_key(TEST/"TEST_PUBLIC_KEY.b64"))
    check(prev["release_sequence"]==6, "signed predecessor is not v6")
    check(len(prev["stations"])==315 and len(prev["tombstones"])==5, "v6 counts changed")
    next_=json.loads(V7.read_bytes())
    schema=json.loads(SCHEMA.read_bytes())
    bad=sorted(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(next_),
               key=lambda e:list(map(str,e.path)))
    check(not bad, "v7 schema invalid: "+repr([(e.json_path,e.message) for e in bad[:3]]))
    check(next_["release_sequence"]==7, "v7 sequence mismatch")
    check(len(next_["stations"])==296, "v7 station count mismatch")
    check(sum(s["status"]["state"]=="active" for s in next_["stations"])==285,
          "v7 active count mismatch")
    check(len(next_["tombstones"])==24, "v7 tombstone count mismatch")
    check(sum(s["logo"] is not None for s in next_["stations"])==175,
          "v7 overall SHA logo descriptor count mismatch")
    check(sum(s["status"]["state"]=="active" and s["logo"] is not None
              for s in next_["stations"])==170, "v7 active logo mismatch")

    issues=validate_catalog(next_,mode="publish",previous=prev,
                            trusted_signed_history=True)
    check(not issues,"publish guard rejects v7: "+repr(issues[:8]))

    old_st={x["go_station_id"]:x for x in prev["stations"]}
    new_st={x["go_station_id"]:x for x in next_["stations"]}
    old_t={x["go_station_id"]:x for x in prev["tombstones"]}
    new_t={x["go_station_id"]:x for x in next_["tombstones"]}
    check(len(new_st)==296 and len(new_t)==24,"duplicate GO identifiers")
    check(set(old_st)|set(old_t)==set(new_st)|set(new_t),
          "320 GO station IDs not preserved")
    check(not(set(new_st)&set(new_t)),"GO ID both station and tombstone")
    for goid,old in old_t.items():
        check(new_t.get(goid)==old,"previous v6 signed redirect mutated: "+goid)

    old_uuids={}
    for row in prev["stations"]+prev["tombstones"]:
        for alias in row["legacy_aliases"]:
            check(alias not in old_uuids,"old historical alias collision")
            old_uuids[alias]=row["go_station_id"]
    new_uuids={}
    for row in next_["stations"]+next_["tombstones"]:
        for alias in row["legacy_aliases"]:
            check(alias not in new_uuids,"new historical alias collision")
            new_uuids[alias]=row["go_station_id"]
    check(old_uuids==new_uuids,"legacy favorite/Android Auto ID owner lost or reassigned")

    plan=json.loads(PLAN.read_bytes())
    check(plan["source_sequence"]==6 and plan["target_sequence"]==7 and
          plan["signature"]=="NONE" and plan["publication"]=="NONE",
          "unsafe v7 plan marked signed/published")
    check(len(plan["mapping"])==13, "incorrect number of program merges")
    expected_losers={
        "go-station-"+i:survivor for survivor,allids in EXPECTED_SURVIVORS.items()
        for i in allids
    }
    check(len(expected_losers)==19,"incorrect retiree map")
    check(set(old_st)-set(new_st)==set(expected_losers),
          "unexpected removed station or missed consolidation")
    check(set(new_t)-set(old_t)==set(expected_losers),"wrong 19 new tombstones")
    expected_titles={x["primary_go_id"]:x for x in plan["mapping"]}
    check(set(expected_titles)==set(EXPECTED_SURVIVORS),"unexpected survivor IDs")
    for gone,winner in expected_losers.items():
        old=old_st[gone]
        tomb=new_t[gone]
        check(tomb["reason_code"]=="merged_into_station" and
              tomb.get("redirect_to")==winner,
              "retired GO ID lacks explicit valid signed redirect")
        check(tomb["legacy_aliases"]==old["legacy_aliases"],
              "retiree lost UUIDs")

    for goid,old in old_st.items():
        if goid in expected_losers:
            continue
        current=new_st[goid]
        if goid not in EXPECTED_SURVIVORS:
            check(current==old,"unrelated station changed: "+goid)
            continue
        rec=expected_titles[goid]
        originals=[old_st[goid]]+[old_st["go-station-"+i]
                                  for i in EXPECTED_SURVIVORS[goid]]
        check(rec["retired"]==["go-station-"+i
                              for i in EXPECTED_SURVIVORS[goid]],
              "plan retiree membership wrong")
        expected_urls=[
            stream["url"] for src in originals for stream in src["streams"]
        ]
        actual_urls=[stream["url"] for stream in current["streams"]]
        check(sorted(expected_urls)==sorted(actual_urls),
              "stream removed, duplicated or invented in "+goid)
        check(len({x["stream_id"] for x in current["streams"]})==
              len(current["streams"]),"stream IDs duplicate in "+goid)
        check([x["priority"] for x in current["streams"]]==
              list(range(len(current["streams"]))),
              "stream priorities not a dense stable sequence in "+goid)
        check(current["display_name"].strip() != "",
              "invalid retained station name")
        check(current["logo"]==old["logo"],"survivor logo replaced without review")
        check(current["status"]==old["status"],"survivor status changed")
        check(current["legacy_aliases"]==old["legacy_aliases"],
              "survivor UUID ownership mutated")
        check(current["radio_browser_uuids"]==old["radio_browser_uuids"],
              "survivor UUID registry mutated")
        check(current["genres"]==old["genres"],"survivor genre mutated")
        check(current["homepage"]==old["homepage"],"survivor homepage mutated")
        check(current["editorial"]["evidence_refs"]==
              list(dict.fromkeys(
                  ref for src in originals
                  for ref in src["editorial"].get("evidence_refs",[])
              )),"original editorial admission evidence lost")
        for field in old:
            if field not in {"streams","display_name","editorial"}:
                check(old[field]==current[field],
                      "unexpected survivor mutation "+goid+" "+field)
        for stream in current["streams"]:
            check(stream["state"]=="verified", "unverified source variant merged")

    for goid,url in SAFE_PRIMARY_URLS.items():
        check(new_st[goid]["streams"][0]["url"]==url,
              "unsafe/expired first-choice URL for "+goid)

    check(sum(s["status"]["state"]=="quarantined" for s in new_st.values())==11,
          "previously quarantined radios lost/activated")
    check(sum(1 for s in next_["stations"] if s["status"]["state"]=="active"
              and s["logo"] is None)==115,
          "missing-descriptor active radio count unexpected")
    print(json.dumps({
        "result":"GO_RADIO_V7_DRAFT_13_MERGE_PREFLIGHT_PASS",
        "signed_predecessor":"TEST v6 Ed25519 verified",
        "go_station_ids_preserved":320,
        "historical_uuid_owners_preserved":len(old_uuids),
        "program_groups_consolidated":13,
        "new_redirects":19,
        "total_redirects":24,
        "active_before":304,
        "active_after":285,
        "quarantined_after":11,
        "active_logo_descriptors_after":170,
        "missing_logo_descriptors_after":115,
        "v7_signed":False,
        "v7_published":False,
        "active_test_v6_pointer_unchanged":True,
    },sort_keys=True))


if __name__=="__main__":
    main()
