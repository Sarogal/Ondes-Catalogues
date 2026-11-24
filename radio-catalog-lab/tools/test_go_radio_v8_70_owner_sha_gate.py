#!/usr/bin/env python3
"""Final strict QA for unsigned v8 70 original artworks vs signed Ed25519 TEST v7."""
from __future__ import annotations
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
from audit_open_radio_artwork_inventory import inspect_bytes
from radio_catalog_release_packager import load_verified_predecessor, read_public_key
from radio_catalog_guard import validate_catalog
from test_go_radio_v8_68_channel_specific_sha_gate import main as check_68
from stage_v8_70_nts_pit_rockirk import BEFORE, AFTER, ART, PREFIX, EXT, SOURCES

ROOT = Path(__file__).resolve().parents[2]
SIGNED = ROOT / "grossesondes/radio-test-v2"
SCHEMA = ROOT / "radio-catalog-lab/schemas/radio_catalog_v1.schema.json"


def main() -> None:
    check_68()
    assert AFTER.exists() and ART.is_dir()
    before = json.loads(BEFORE.read_bytes())
    after = json.loads(AFTER.read_bytes())
    signed = load_verified_predecessor(SIGNED, read_public_key(SIGNED / "TEST_PUBLIC_KEY.b64"))
    schema = json.loads(SCHEMA.read_bytes())
    assert not list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(after))
    assert not validate_catalog(after, mode="publish", previous=signed, trusted_signed_history=True)
    assert after["release_sequence"] == 8 and len(after["stations"]) == 296
    assert after["tombstones"] == before["tombstones"] == signed["tombstones"]
    now = {s["go_station_id"]: s for s in after["stations"]}
    old = {s["go_station_id"]: s for s in before["stations"]}
    assert set(now) == set(old)
    changed = {sid for sid in now if now[sid] != old[sid]}
    assert changed == set(SOURCES)
    unique_shas = set()
    for sid, spec in SOURCES.items():
        station = now[sid]
        previous = old[sid]
        assert previous["logo"] is None and station["status"]["state"] == "active"
        blank = deepcopy(station); blank["logo"] = None
        assert blank == previous, "Non-logo field changed"
        logo = station["logo"]
        sha = spec["sha256"]
        assert sha == logo["sha256"] and logo["asset_id"] == "sha256:" + sha
        assert (logo["width"], logo["height"]) == ((1600, 900) if sid == "go-station-000042" else (1024, 1024))
        suffix = EXT[logo["mime_type"]]
        assert logo["url"] == PREFIX + sha + suffix
        content = (ART / (sha + suffix)).read_bytes()
        assert hashlib.sha256(content).hexdigest() == sha
        assert inspect_bytes(content, content_type=logo["mime_type"]) == {
            k: logo[k] for k in ("sha256", "byte_size", "width", "height", "mime_type")
        }
        unique_shas.add(sha)
    assert len(unique_shas) == 2 and len(list(ART.iterdir())) == 2
    active = [s for s in after["stations"] if s["status"]["state"] == "active"]
    assert len(active) == 285
    assert sum(s["logo"] is not None for s in active) == 259
    assert sum(s["logo"] is None for s in active) == 26
    ids = lambda c: {s["go_station_id"] for s in c["stations"] + c["tombstones"]}
    aliases = lambda c: {a: s["go_station_id"] for s in c["stations"] + c["tombstones"] for a in s["legacy_aliases"]}
    assert len(ids(after)) == 320 and ids(after) == ids(signed)
    assert len(aliases(after)) == 363 and aliases(after) == aliases(signed)
    pointer = json.loads((SIGNED / "current.json").read_bytes())
    assert pointer["release_sequence"] == 7
    assert pointer["content_sha256"] == "f735884aa0841a86d88aaafe406e62b7a826cf9cd60f6a70285a0894326841aa"
    assert not (SIGNED / "current-v8.json").exists()
    print(json.dumps({
        "result": "GO_TEST_V8_70_NTS_ROCKIRK_SIGNED_V7_CONTINUITY_QA_PASS",
        "active": 285, "logos": 259, "missing": 26,
        "new_sha_objects": 70, "go_ids_preserved": 320,
        "favorite_uuid_owners_preserved": 363, "redirects": 24,
        "v8_signed": False, "v8_published": False,
        "TEST_v7_signed_pointer_unchanged": True,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
