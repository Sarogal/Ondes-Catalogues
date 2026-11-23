#!/usr/bin/env python3
"""Validate v6 TEST draft + exact staged 14 RADIO BOB! SHA object bytes.

No signing or publishing. Asserts signed TEST v5 predecessor unchanged, v6
redirections preserved, exactly 19 additional BOB logos and all 14 objects
content-verified. Source images are verified for byte length, SHA, MIME and
dimensions; the separate official page/title evidence is documented in the
audit workflow. This is a development branch only.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from audit_open_radio_artwork_inventory import inspect_bytes
from radio_catalog_guard import validate_catalog
from radio_catalog_release_packager import load_verified_predecessor, read_public_key
from probe_bob_official_channel_tile_sha_v6 import target_rows

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = ROOT / "radio-catalog-lab/full-staging/UNSIGNED-radio-v6-radcap-3-duplicate-families-20261123.json"
ENRICHED = ROOT / "radio-catalog-lab/full-staging/UNSIGNED-radio-v6-radcap-bob-3-duplicate-families-20261123.json"
IMAGE_FOLDER = ROOT / "grossesondes/radio-test-v2/artwork/staging-unpublished"
TEST_ROOT = ROOT / "grossesondes/radio-test-v2"
EXPECTED_V5_SHA = "dfa7543e33cfe4a1937acc78ba78fa388b019fa9de2e514ec856df1be38637e0"


def main() -> None:
    old_pointer = json.loads((TEST_ROOT / "current.json").read_text())
    assert old_pointer["release_sequence"] == 5
    assert old_pointer["content_sha256"] == EXPECTED_V5_SHA
    previous = load_verified_predecessor(
        TEST_ROOT, read_public_key(TEST_ROOT / "TEST_PUBLIC_KEY.b64"))
    original = json.loads(ORIGINAL.read_text())
    v6 = json.loads(ENRICHED.read_text())
    schema = json.loads((ROOT / "radio-catalog-lab/schemas/radio_catalog_v1.schema.json").read_text())
    issues = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(v6))
    assert not issues, [(e.json_path, e.message) for e in issues[:3]]
    assert validate_catalog(v6, mode="publish", previous=previous,
                            trusted_signed_history=True) == [], "Publish gate rejected draft"
    assert original["release_sequence"] == v6["release_sequence"] == 6
    assert original["tombstones"] == v6["tombstones"]
    assert len(v6["stations"]) == 315
    assert sum(s["status"]["state"] == "active" for s in v6["stations"]) == 304
    assert len(v6["tombstones"]) == 5
    assert sum(s["logo"] is not None for s in v6["stations"]) == 190
    original_by_id = {s["go_station_id"]:s for s in original["stations"]}
    updated_by_id = {s["go_station_id"]:s for s in v6["stations"]}
    assert set(original_by_id) == set(updated_by_id)
    changed = []
    for goid, was in original_by_id.items():
        now = updated_by_id[goid]
        if was != now:
            assert was["logo"] is None and now["logo"] is not None, goid
            check = dict(now)
            check["logo"] = None
            assert check == was, "Altered radio beyond logo: " + goid
            changed.append(goid)
    assert len(changed) == 19
    matched_streams = target_rows(original)
    assert set(changed) == set(sum(matched_streams.values(), []))
    img_paths = list(IMAGE_FOLDER.glob("*.webp"))
    assert len(img_paths) == 14
    official_sha = set()
    for goid in changed:
        logo = updated_by_id[goid]["logo"]
        assert logo["revision"] == 1
        digest = logo["sha256"]
        assert logo["asset_id"] == "sha256:" + digest
        assert logo["url"] == (
            "https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
            "feature/go-radio-v6-dedupe-logo-audit-20261123/"
            "grossesondes/radio-test-v2/artwork/staging-unpublished/"
            + digest + ".webp")
        path = IMAGE_FOLDER / (digest + ".webp")
        assert path.is_file() and not path.is_symlink()
        blob = path.read_bytes()
        assert hashlib.sha256(blob).hexdigest() == digest
        assert inspect_bytes(blob, content_type="image/webp") == {
            "sha256": digest,
            "byte_size": logo["byte_size"],
            "width": logo["width"],
            "height": logo["height"],
            "mime_type": logo["mime_type"],
        }
        official_sha.add(digest)
    assert len(official_sha) == 14
    assert all(p.stem in official_sha for p in img_paths)
    radcap = [s for s in v6["stations"] if "radcap.ru" in
              (s.get("homepage") or "").lower() or
              "radcap" in s["display_name"].lower() or
              "radio caprice" in s["display_name"].lower() or
              "caprice radio" in s["display_name"].lower()]
    assert len(radcap) == 73 and all(s["logo"] is not None for s in radcap)
    print(json.dumps({
        "result":"GO_RADIO_V6_190_SIGNABLE_LOGOS_QA_PASS",
        "prev_signed_v5_unchanged":True,
        "new_bob_logo_references":len(changed),
        "new_bob_sha_objects":len(official_sha),
        "all_radcap_signed_logo_references":73,
        "station_rows":315,
        "tombstone_redirects":5,
        "active":304,
        "total_logo_descriptors":190,
        "release_signed":False,
        "release_published":False
    }, sort_keys=True))


if __name__ == "__main__":
    main()
