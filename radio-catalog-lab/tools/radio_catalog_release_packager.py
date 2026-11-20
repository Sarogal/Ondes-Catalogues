#!/usr/bin/env python3
"""Offline release bundle generator for Grosses Ondes radio catalogue v1.

This is a LOCAL PACKAGER, never a publisher. It performs zero HTTP requests,
never pushes Git commits, and refuses to package unreviewed legacy imports.
Private Ed25519 signing material must stay OUTSIDE the repository and CI.

Requires cryptography + jsonschema. Only signed, immutable bytes are output;
current.json is a signed pointer, not an unsigned redirect.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)
from jsonschema import Draft202012Validator, FormatChecker

from radio_catalog_guard import validate_catalog

MAX_CATALOG_BYTES = 10 * 1024 * 1024
MAX_POINTER_BYTES = 16 * 1024
MAX_INPUT_BYTES = 15 * 1024 * 1024
RELEASE_ID = "grosses-ondes-radio"
KEY_ID_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")
SHA_RE = re.compile(r"[a-f0-9]{64}\Z")
UTC_RE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\Z")
SIGNING_CONTEXT = "GO-RADIO-CATALOG-POINTER-V1\n"
SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
REPOSITORY = Path(__file__).resolve().parents[2]


class BundleError(ValueError):
    """Sanitized packaging error, never includes station URLs or key material."""


def strict_json(raw: bytes, *, maximum: int) -> dict:
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= maximum:
        raise BundleError("Invalid JSON input size")
    def unique_pairs(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise BundleError("Duplicate JSON object key")
            result[name] = value
        return result
    try:
        document = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_pairs)
    except (ValueError, UnicodeError) as error:
        raise BundleError("Invalid or noncanonical JSON input") from error
    if not isinstance(document, dict):
        raise BundleError("Top-level JSON object required")
    return document


def wire_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def valid_utc(value: str) -> bool:
    if not isinstance(value, str) or UTC_RE.fullmatch(value) is None:
        return False
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.utcoffset() == dt.timedelta(0)


def _validate_schema(data: dict, schema_name: str) -> None:
    schema = strict_json((SCHEMAS / schema_name).read_bytes(), maximum=MAX_INPUT_BYTES)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    if not validator.is_valid(data):
        # Fail without echoing untrusted potentially secret stream URLs.
        raise BundleError(f"{schema_name}: schema validation failed")


def validate_release_content(catalog_bytes: bytes, previous: dict | None = None) -> dict:
    catalog = strict_json(catalog_bytes, maximum=MAX_CATALOG_BYTES)
    _validate_schema(catalog, "radio_catalog_v1.schema.json")
    errors = validate_catalog(catalog, mode="publish", previous=previous)
    if errors:
        raise BundleError(f"Radio editorial gate failed ({len(errors)} issue(s))")
    if not valid_utc(catalog.get("generated_at")):
        raise BundleError("Catalog generated_at must be a valid UTC timestamp")
    sequence = catalog["release_sequence"]
    if type(sequence) is not int or sequence < 1:
        raise BundleError("Invalid release sequence")
    if previous is not None and (
        type(previous.get("release_sequence")) is not int or
        sequence <= previous["release_sequence"]
    ):
        raise BundleError("Release sequence did not increase")
    if previous is None and sequence != 1:
        raise BundleError("Non-initial release requires VERIFIED predecessor")
    return catalog


def signing_message(pointer: dict) -> bytes:
    """Byte-for-byte parity with CentralCatalogPointer.signatureMessage (Dart)."""
    return (
        SIGNING_CONTEXT
        + f"{pointer['schema_version']}\n"
        + f"{pointer['catalog_id']}\n"
        + f"{pointer['release_sequence']}\n"
        + f"{pointer['published_at']}\n"
        + f"{pointer['content_sha256']}\n"
        + f"{pointer['content_length']}\n"
        + f"{pointer['content_path']}\n"
        + f"{pointer['signature']['key_id']}\n"
    ).encode("utf-8")


@dataclass(frozen=True)
class ReleaseBundle:
    pointer_bytes: bytes
    catalog_bytes: bytes
    digest: str
    release_path: str
    sequence: int
    station_count: int
    tombstone_count: int


def verify_bundle(
    pointer_bytes: bytes, catalog_bytes: bytes, public_key: Ed25519PublicKey,
    *, previous: dict | None = None,
) -> ReleaseBundle:
    pointer = strict_json(pointer_bytes, maximum=MAX_POINTER_BYTES)
    _validate_schema(pointer, "radio_catalog_pointer_v1.schema.json")
    expected_fields = {
        "schema_version", "catalog_id", "release_sequence", "published_at",
        "content_sha256", "content_length", "content_path", "signature",
    }
    if set(pointer) != expected_fields:
        raise BundleError("Unexpected pointer fields or missing signature")
    sig = pointer.get("signature")
    if not isinstance(sig, dict) or set(sig) != {
        "algorithm", "key_id", "signature_base64",
    } or sig.get("algorithm") != "Ed25519":
        raise BundleError("Invalid signed pointer fields")
    if not isinstance(sig.get("key_id"), str) or not KEY_ID_RE.fullmatch(sig["key_id"]):
        raise BundleError("Invalid signing key identifier")
    if not valid_utc(pointer.get("published_at")):
        raise BundleError("Invalid signed publication timestamp")
    if pointer.get("schema_version") != 1 or pointer.get("catalog_id") != RELEASE_ID:
        raise BundleError("Unexpected pointer catalog identity")
    try:
        signature = base64.b64decode(sig["signature_base64"], validate=True)
    except (ValueError, binascii.Error, TypeError) as error:
        raise BundleError("Malformed pointer signature") from error
    if len(signature) != 64:
        raise BundleError("Invalid Ed25519 signature length")
    digest = hashlib.sha256(catalog_bytes).hexdigest()
    if (pointer.get("content_sha256") != digest or
        type(pointer.get("content_length")) is not int or
        pointer["content_length"] != len(catalog_bytes) or
        pointer.get("content_path") != f"releases/{digest}.json"):
        raise BundleError("Pointer digest, length or immutable path mismatch")
    try:
        public_key.verify(signature, signing_message(pointer))
    except InvalidSignature as error:
        raise BundleError("Ed25519 signature verification failed") from error
    document = validate_release_content(catalog_bytes, previous)
    if pointer["release_sequence"] != document["release_sequence"]:
        raise BundleError("Pointer and payload release sequence mismatch")
    return ReleaseBundle(
        pointer_bytes=pointer_bytes,
        catalog_bytes=catalog_bytes,
        digest=digest,
        release_path=pointer["content_path"],
        sequence=document["release_sequence"],
        station_count=len(document["stations"]),
        tombstone_count=len(document["tombstones"]),
    )


def create_bundle(
    catalog_bytes: bytes, private_key: Ed25519PrivateKey,
    *, key_id: str, published_at: str, previous: dict | None = None,
) -> ReleaseBundle:
    if not KEY_ID_RE.fullmatch(key_id):
        raise BundleError("Invalid signing key identifier")
    if not valid_utc(published_at):
        raise BundleError("Publication timestamp must be explicit valid UTC")
    catalog = validate_release_content(catalog_bytes, previous)
    digest = hashlib.sha256(catalog_bytes).hexdigest()
    pointer = {
        "schema_version": 1,
        "catalog_id": RELEASE_ID,
        "release_sequence": catalog["release_sequence"],
        "published_at": published_at,
        "content_sha256": digest,
        "content_length": len(catalog_bytes),
        "content_path": f"releases/{digest}.json",
        "signature": {
            "algorithm": "Ed25519",
            "key_id": key_id,
            "signature_base64": "",
        },
    }
    signature = private_key.sign(signing_message(pointer))
    pointer["signature"]["signature_base64"] = base64.b64encode(signature).decode("ascii")
    raw_pointer = wire_bytes(pointer)
    if len(raw_pointer) > MAX_POINTER_BYTES:
        raise BundleError("Signed pointer too large")
    return verify_bundle(raw_pointer, catalog_bytes, private_key.public_key(),
                         previous=previous)


def _read_limited(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise BundleError("Input path must be a regular file")
    if path.stat().st_size > maximum:
        raise BundleError("Input file exceeds size limit")
    return path.read_bytes()


def read_private_seed(path: Path) -> Ed25519PrivateKey:
    """Never print or upload keys. Only base64 32-byte seeds, outside repo."""
    path = path.expanduser()
    if path.is_symlink() or not path.is_file():
        raise BundleError("Signing seed must be a regular file")
    resolved = path.resolve()
    if resolved.is_relative_to(REPOSITORY):
        raise BundleError("Signing key MUST be outside the source repository")
    if os.name != "nt" and (stat.S_IMODE(path.stat().st_mode) & 0o077):
        raise BundleError("Signing seed file must be private (chmod 600)")
    raw = _read_limited(path, 128)
    try:
        seed = base64.b64decode(raw.strip(), validate=True)
    except (binascii.Error, ValueError) as error:
        raise BundleError("Invalid base64 signing seed file") from error
    if len(seed) != 32:
        raise BundleError("Ed25519 signing seed must be exactly 32 bytes")
    return Ed25519PrivateKey.from_private_bytes(seed)


def read_public_key(path: Path) -> Ed25519PublicKey:
    raw = _read_limited(path, 128)
    try:
        key = base64.b64decode(raw.strip(), validate=True)
    except (binascii.Error, ValueError) as error:
        raise BundleError("Malformed Ed25519 public key file") from error
    if len(key) != 32:
        raise BundleError("Ed25519 public key must be exactly 32 bytes")
    return Ed25519PublicKey.from_public_bytes(key)


def load_verified_predecessor(directory: Path, trusted_public_key: Ed25519PublicKey) -> dict:
    pointer_bytes = _read_limited(directory / "current.json", MAX_POINTER_BYTES)
    pointer = strict_json(pointer_bytes, maximum=MAX_POINTER_BYTES)
    path = pointer.get("content_path")
    if not isinstance(path, str) or not re.fullmatch(r"releases/[a-f0-9]{64}\.json", path):
        raise BundleError("Invalid predecessor content path")
    body = _read_limited(directory / path, MAX_CATALOG_BYTES)
    verified = verify_bundle(pointer_bytes, body, trusted_public_key)
    return strict_json(verified.catalog_bytes, maximum=MAX_CATALOG_BYTES)


def write_staging(directory: Path, bundle: ReleaseBundle) -> Path:
    """Never overwrite existing output; caller later distributes independently."""
    destination = directory.resolve()
    if destination.exists():
        raise BundleError("Release staging directory already exists")
    parent = destination.parent
    if not parent.is_dir():
        raise BundleError("Release staging parent must already exist")
    staging = Path(tempfile.mkdtemp(prefix=".go-radio-bundle-pending-", dir=parent))
    try:
        (staging / "releases").mkdir()
        (staging / bundle.release_path).write_bytes(bundle.catalog_bytes)
        (staging / "current.json").write_bytes(bundle.pointer_bytes)
        summary = {
            "schemaVersion": 1,
            "releaseSequence": bundle.sequence,
            "contentSha256": bundle.digest,
            "pointerSha256": hashlib.sha256(bundle.pointer_bytes).hexdigest(),
            "stationCount": bundle.station_count,
            "tombstoneCount": bundle.tombstone_count,
            "stagingOnly": True,
            "publicationAllowed": False,
        }
        (staging / "release-preview.json").write_bytes(wire_bytes(summary))
        if destination.exists():
            raise BundleError("Release output path became occupied")
        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--signing-key-file", type=Path, required=True,
                        help="Base64 private Ed25519 seed in chmod-600 file OUTSIDE repo")
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--published-at", required=True,
                        help="Explicit UTC time e.g. 2026-11-20T17:00:00Z")
    parser.add_argument("--previous-bundle-dir", type=Path)
    parser.add_argument("--previous-public-key-file", type=Path)
    parser.add_argument("--offline-stage-only", action="store_true",
                        help="Mandatory safety guard; never publishes remotely")
    args = parser.parse_args(argv)
    if not args.offline_stage_only:
        parser.error("Explicit --offline-stage-only required; this cannot publish")
    if bool(args.previous_bundle_dir) != bool(args.previous_public_key_file):
        parser.error("Signed predecessor and its trusted public key must be supplied together")

    previous = None
    if args.previous_bundle_dir:
        previous = load_verified_predecessor(
            args.previous_bundle_dir, read_public_key(args.previous_public_key_file))
    body = _read_limited(args.catalog, MAX_CATALOG_BYTES)
    secret = read_private_seed(args.signing_key_file)
    bundle = create_bundle(body, secret, key_id=args.key_id,
                           published_at=args.published_at, previous=previous)
    output = write_staging(args.output_dir, bundle)
    print(json.dumps({
        "status": "OFFLINE_SIGNED_STAGING_ONLY_NOT_PUBLISHED",
        "directory": str(output),
        "release_sequence": bundle.sequence,
        "stations": bundle.station_count,
        "sha256": bundle.digest,
        "publicationAllowed": False,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
