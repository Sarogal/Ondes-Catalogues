#!/usr/bin/env python3
"""Verify signed catalogue predecessors; default to the pinned public TEST v8."""
import argparse
import base64
import hashlib
import json
import re
from pathlib import Path

from radio_daily_v9_generator import BASELINE
from radio_catalog_guard import validate_catalog

KEY_ID = "go-apk-test-20261122-v2"
PUBLIC_KEY = "mxOGcUsk4/HFKkhNWVTpToPEuAEuc8SNZ68Y68v0KMw="
FIELDS = ("schema_version", "catalog_id", "release_sequence", "published_at",
          "content_sha256", "content_length", "content_path")

def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs)

def verify_pointer(raw, *, expected_sha=BASELINE, expected_sequence=8, public_key=PUBLIC_KEY, key_id=KEY_ID):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    if not 0 < len(raw) <= 16384:
        raise ValueError("pointer size")
    if (type(expected_sequence) is not int or expected_sequence < 8
            or not isinstance(expected_sha,str) or not re.fullmatch(r"[a-f0-9]{64}",expected_sha)):
        raise ValueError("invalid trusted predecessor anchor")
    p = strict_json(raw)
    if (set(p) != set(FIELDS) | {"signature"} or p["schema_version"] != 1
            or p["catalog_id"] != "grosses-ondes-radio" or type(p["release_sequence"]) is not int or p["release_sequence"] != expected_sequence
            or p["content_sha256"] != expected_sha or p["content_path"] != f"releases/{expected_sha}.json"
            or type(p["content_length"]) is not int or not 0 < p["content_length"] <= 10485760):
        raise ValueError("unexpected pinned predecessor")
    sig = p["signature"]
    if set(sig) != {"algorithm", "key_id", "signature_base64"} or sig["algorithm"] != "Ed25519" or sig["key_id"] != key_id:
        raise ValueError("unexpected signature identity")
    message = ("GO-RADIO-CATALOG-POINTER-V1\n" +
               "".join(str(p[k]) + "\n" for k in FIELDS) + key_id + "\n").encode()
    Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key, validate=True)).verify(
        base64.b64decode(sig["signature_base64"], validate=True), message)
    return p

def validate_shape(doc):
    from jsonschema import Draft202012Validator, FormatChecker
    schema = strict_json((Path(__file__).resolve().parents[1]/"schemas"/"radio_catalog_v1.schema.json").read_bytes())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = list(validator.iter_errors(doc))
    if errors:
        raise ValueError("schema mismatch: " + "; ".join("/".join(map(str,e.absolute_path)) + ":" + str(e.validator) for e in errors[:10]))
    if validate_catalog(doc, mode="staging"):
        raise ValueError("catalog guard mismatch")
    active = {s["go_station_id"] for s in doc["stations"] if s["status"]["state"] == "active"}
    for t in doc["tombstones"]:
        if "redirect_to" in t and t["redirect_to"] not in active:
            raise ValueError("redirect must target an active station")
    ids = {s["go_station_id"] for s in doc["stations"] + doc["tombstones"]}
    logos = {}
    for s in doc["stations"] + doc["tombstones"]:
        if any(a in ids and a != s["go_station_id"] for a in s["legacy_aliases"]):
            raise ValueError("alias shadows permanent identity")
        logo = s.get("logo")
        if logo:
            key = logo["sha256"]
            metadata = tuple(logo[k] for k in ("byte_size","width","height","mime_type"))
            if logos.setdefault(key, metadata) != metadata:
                raise ValueError("inconsistent logo digest metadata")

def verify_baseline(pointer, body, *, expected_sha=BASELINE, expected_sequence=8, public_key=PUBLIC_KEY, key_id=KEY_ID):
    p = verify_pointer(pointer, expected_sha=expected_sha, expected_sequence=expected_sequence, public_key=public_key, key_id=key_id)
    if len(body) != p["content_length"] or hashlib.sha256(body).hexdigest() != expected_sha:
        raise ValueError("catalog bytes mismatch")
    doc = strict_json(body)
    if doc["release_sequence"] != expected_sequence:
        raise ValueError("catalog sequence mismatch")
    validate_shape(doc)
    return doc

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pointer", type=Path, required=True)
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--candidate", type=Path)
    a = p.parse_args()
    if a.pointer.stat().st_size > 16384 or a.baseline.stat().st_size > 10485760:
        raise ValueError("input too large")
    doc = verify_baseline(a.pointer.read_bytes(), a.baseline.read_bytes())
    if a.candidate:
        if a.candidate.stat().st_size > 10485760:
            raise ValueError("candidate too large")
        candidate = strict_json(a.candidate.read_bytes())
        validate_shape(candidate)
        if (candidate["release_sequence"] != 9
                or len(candidate["stations"]) <= len(doc["stations"])
                or candidate["stations"][:len(doc["stations"])] != doc["stations"]
                or candidate["tombstones"] != doc["tombstones"]):
            raise ValueError("candidate is not additive")
    print("PINNED_TEST_V8_ED25519_VERIFIED", len(doc["stations"]), len(doc["tombstones"]))

if __name__ == "__main__":
    main()
