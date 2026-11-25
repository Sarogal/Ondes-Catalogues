#!/usr/bin/env python3
"""Read-only verification of the public signed TEST v8 catalog. Public key only."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

BASE_URL = (
    "https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
    "feature/go-radio-test-v2-isolated-20261123/grossesondes/radio-test-v2/"
)
EXPECTED_V8 = "f57e65f24f5ddd3a567907b28903fc309ea4c16747873b39f8d5a44348266f40"
PUBLIC_KEY_B64 = "mxOGcUsk4/HFKkhNWVTpToPEuAEuc8SNZ68Y68v0KMw="
KEY_ID = "go-apk-test-20261122-v2"
SIGNING_CONTEXT = "GO-RADIO-CATALOG-POINTER-V1\n"
MAX_POINTER = 16384
MAX_CATALOG = 10 * 1024 * 1024
SHA_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def fail(message: str) -> None:
    raise ValueError(message)


def strict_json(raw: bytes) -> dict:
    def no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                fail("Duplicate JSON field")
            result[key] = value
        return result
    doc = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=no_duplicate_keys)
    if not isinstance(doc, dict):
        fail("Expected JSON object")
    return doc


def fetch(url: str, max_bytes: int) -> bytes:
    if not url.startswith(BASE_URL):
        fail("Fetch attempted outside reviewed TEST catalog base")
    request = Request(url, headers={"User-Agent": "GrossesOndes-Preprod-Audit/1.0"})
    with urlopen(request, timeout=25) as response:
        if response.url != url or response.status != 200:
            fail("Unapproved redirect or unavailable HTTPS source")
        body = response.read(max_bytes + 1)
    if not body or len(body) > max_bytes:
        fail("Missing or oversized remote object")
    return body


def verify_remote() -> tuple[dict, dict]:
    p_raw = fetch(BASE_URL + "current.json", MAX_POINTER)
    pointer = strict_json(p_raw)
    signature = pointer.get("signature", {})
    if not isinstance(signature, dict):
        fail("Invalid signature descriptor")
    if (pointer.get("release_sequence") != 8 or
        pointer.get("schema_version") != 1 or
        pointer.get("catalog_id") != "grosses-ondes-radio" or
        signature.get("key_id") != KEY_ID or
        signature.get("algorithm") != "Ed25519"):
        fail("Unexpected TEST v8 signed identity, algorithm or key")
    sha = pointer.get("content_sha256")
    if sha != EXPECTED_V8 or not SHA_PATTERN.fullmatch(sha):
        fail("Published TEST pointer differs from specifically audited v8")
    relative = "releases/" + sha + ".json"
    if pointer.get("content_path") != relative:
        fail("Nonimmutable or unexpected release path")
    raw = fetch(BASE_URL + relative, MAX_CATALOG)
    if hashlib.sha256(raw).hexdigest() != sha or pointer.get("content_length") != len(raw):
        fail("Signed catalog hash or length mismatch")
    message = (
        SIGNING_CONTEXT
        + str(pointer["schema_version"]) + "\n"
        + str(pointer["catalog_id"]) + "\n"
        + str(pointer["release_sequence"]) + "\n"
        + str(pointer["published_at"]) + "\n"
        + sha + "\n"
        + str(pointer["content_length"]) + "\n"
        + relative + "\n"
        + KEY_ID + "\n"
    ).encode("utf-8")
    Ed25519PublicKey.from_public_bytes(base64.b64decode(PUBLIC_KEY_B64)).verify(
        base64.b64decode(signature["signature_base64"], validate=True), message)
    catalog = strict_json(raw)
    if catalog.get("release_sequence") != 8 or catalog.get("catalog_id") != pointer["catalog_id"]:
        fail("Signed pointer/content mismatch")
    return pointer, catalog

