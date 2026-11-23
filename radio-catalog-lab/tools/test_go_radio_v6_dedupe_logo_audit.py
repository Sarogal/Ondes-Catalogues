#!/usr/bin/env python3
"""Regression gate for an UNSIGNED v6 draft; never publish without private TEST signing.

Source v5 is verified with its real pinned Ed25519 public key before comparison.
Tests retain every historical GO ID and Radio Browser UUID through signed
tombstone redirects; do not confuse BOB Wacken and RauteMusik Wacken.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from radio_catalog_guard import validate_catalog
from radio_catalog_release_packager import load_verified_predecessor, read_public_key

ROOT = Path(__file__).resolve().parents[2]
V5 = ROOT / "grossesondes" / "radio-test-v2"
V6 = ROOT / "radio-catalog-lab" / "full-staging" / "UNSIGNED-radio-v6-radcap-3-duplicate-families-20261123.json"
SCHEMA = ROOT / "radio-catalog-lab" / "schemas" / "radio_catalog_v1.schema.json"
RADCAP_SHA = "899ec2235f73eff7578cfefaa55e311c5f324437a7794365a17298f9f764fd8c"
EXPECTED_REDIRECTS = {
    "go-station-000151": "go-station-000016",  # RauteMusik Wacken
    "go-station-000154": "go-station-000089",  # La Grosse Radio METAL
    "go-station-000010": "go-station-000233",  # BOB! Wacken MP3
    "go-station-000122": "go-station-000233",  # BOB! Wacken AAC
    "go-station-000246": "go-station-000233",  # BOB! Wacken MP3
}


def require(ok: bool, detail: str) -> None:
    if not ok:
        raise AssertionError(detail)


def main() -> None:
    # Fail closed if the signed predecessor changed or was not actually signed.
    previous = load_verified_predecessor(
        V5, read_public_key(V5 / "TEST_PUBLIC_KEY.b64"))
    candidate = json.loads(V6.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(candidate),
        key=lambda e: list(map(str, e.path)),
    )
    require(not errors, f"Draft v6 schema failed: {errors[:2]}")
    require(previous["release_sequence"] == 5, "Signed predecessor is not v5")
    require(candidate["release_sequence"] == 6, "Draft sequence is not v6")
    require(len(previous["stations"]) == 320, "Predecessor count changed")
    require(len(candidate["stations"]) == 315, "Unexpected candidate station count")
    require(len(candidate["tombstones"]) == 5, "Unexpected tombstone count")
    require(sum(s["status"]["state"] == "active"
                for s in candidate["stations"]) == 304, "Unexpected active count")
    require(sum(s["logo"] is not None for s in candidate["stations"]) == 171,
            "Logo coverage not exactly 171 signed references")

    old = {s["go_station_id"]: s for s in previous["stations"]}
    current = {s["go_station_id"]: s for s in candidate["stations"]}
    tombstones = {s["go_station_id"]: s for s in candidate["tombstones"]}
    require(set(old) == set(current) | set(tombstones),
            "Historical GO IDs must remain in station or tombstone")
    require(not (set(current) & set(tombstones)), "GO ID still active after tombstone")
    require({key: t.get("redirect_to") for key, t in tombstones.items()}
            == EXPECTED_REDIRECTS, "Missing, wrong or extra signed merge redirect")

    old_alias = {uuid: s["go_station_id"]
                 for s in previous["stations"] for uuid in s["legacy_aliases"]}
    new_alias = {uuid: s["go_station_id"]
                 for s in candidate["stations"] + candidate["tombstones"]
                 for uuid in s["legacy_aliases"]}
    require(old_alias == new_alias, "Historical Radio Browser alias ownership changed")
    require(sum(map(lambda x: len(x["legacy_aliases"]), previous["stations"]))
            == len(new_alias), "Historical aliases duplicated or lost")

    # All three already accepted RadCap logos have IDENTICAL verified SHA and
    # source URL, so one generic RADIO CAPRICE brand image may cover the rest.
    brand = lambda s: (
        any(x in s["display_name"].lower() for x in
            ("radcap", "radio caprice", "caprice radio"))
        or "radcap.ru" in (s.get("homepage") or "").lower()
    )
    inherited = old["go-station-000133"]["logo"]
    require(inherited["sha256"] == RADCAP_SHA, "Unexpected RadCap source logo")
    require(all(old[id]["logo"] == inherited for id in
                ["go-station-000059", "go-station-000133", "go-station-000141"]),
            "RadCap three historical logos no longer identical")
    radcap = [s for s in candidate["stations"] if brand(s)]
    require(len(radcap) == 73, "Wrong RadCap station group")
    require(all(s["logo"] == inherited for s in radcap),
            "Unqualified or absent shared RadCap signed logo")

    for station_id, old_entry in old.items():
        if station_id in tombstones:
            require(tombstones[station_id]["legacy_aliases"] == old_entry["legacy_aliases"],
                    f"Historical aliases lost on {station_id}")
            require(tombstones[station_id]["reason_code"] == "merged_into_station",
                    "Merge tombstone has wrong reason")
            continue
        fresh = current[station_id]
        expected = copy.deepcopy(old_entry)
        if brand(expected) and expected["logo"] is None:
            expected["logo"] = inherited
        if station_id in EXPECTED_REDIRECTS.values():
            # Only the audio variant list may increase on the survivor.
            expected["streams"] = fresh["streams"]
            original = old_entry["streams"]
            require(fresh["streams"][:len(original)] == original,
                    f"Survivor {station_id} lost its primary stream")
            for stream in fresh["streams"][len(original):]:
                require(stream["state"] == "verified", "Unverified merged stream")
            require(len({v["priority"] for v in fresh["streams"]})
                    == len(fresh["streams"]), "Duplicate stream priorities")
            require(len({v["stream_id"] for v in fresh["streams"]})
                    == len(fresh["streams"]), "Duplicate stream IDs")
        require(expected == fresh,
                f"Unexpected station mutation beyond approved logo/merge: {station_id}")

    # Different broadcaster URLs: they both have Wacken stations but are NOT
    # the same program and must NEVER be merged across RADIO BOB!/RauteMusik.
    require("rautemusik.fm" in current["go-station-000016"]["streams"][0]["url"],
            "RauteMusik winner must stay independent")
    require("radiobob.de" in current["go-station-000233"]["streams"][0]["url"],
            "RADIO BOB! winner must stay independent")
    require(len(current["go-station-000016"]["streams"]) == 2,
            "RauteMusik must preserve HTTP+HTTPS variants")
    require(len(current["go-station-000089"]["streams"]) == 2,
            "La Grosse Radio must preserve both stream endpoints")
    require(len(current["go-station-000233"]["streams"]) == 4,
            "RADIO BOB! Wacken must preserve 3 MP3 + 1 AAC")
    require(any(s["codec"] == "AAC" for s in
                current["go-station-000233"]["streams"]),
            "AAC Wacken variant lost")

    guard_issues = validate_catalog(
        candidate, mode="publish", previous=previous,
        trusted_signed_history=True)
    require(guard_issues == [], f"Publication contract validation failed: {guard_issues[:6]}")
    require(not (V5 / "UNSIGNED-radio-v6-radcap-3-duplicate-families-20261123.json").exists(),
            "Signed production TEST directory unexpectedly changed")
    print(json.dumps({
        "result": "GO_RADIO_V6_UNPUBLISHED_MIGRATION_PREFLIGHT_PASS",
        "predecessor": "real Ed25519 signed v5",
        "v6_release_signed": False,
        "radio_count_before": 320,
        "radio_count_after": 315,
        "active_before": 309,
        "active_after": 304,
        "alias_ownership": "preserved",
        "redirect_tombstones": 5,
        "radcap_signed_brand_logo_before": 3,
        "radcap_signed_brand_logo_after": 73,
        "all_radio_bob_unique_channels_preserved": True,
        "old_TEST_v5_pointer_modified": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
