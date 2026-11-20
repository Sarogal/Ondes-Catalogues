"""Offline security, format and Ed25519 Dart-contract tests for radio release bundles."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from radio_catalog_release_packager import (
    BundleError, RELEASE_ID, SIGNING_CONTEXT, create_bundle, load_verified_predecessor,
    main, read_private_seed, read_public_key, signing_message, strict_json,
    validate_release_content, verify_bundle, wire_bytes, write_staging,
)
from test_radio_catalog_guard import station, catalog

TIMESTAMP = "2026-11-20T17:55:00Z"
# Deliberately public, synthetic, deterministic test key. NEVER use for real radio releases.
TEST_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))


def admitted(*, uid="go-station-000001", alias="legacy-uuid-001"):
    return station(uid, alias, approved=True, verified=True)


def payload(*stations, sequence=1):
    return wire_bytes(catalog(*stations, sequence=sequence))


def new_bundle(raw, *, sequence_previous=None, key=TEST_KEY, published=TIMESTAMP):
    return create_bundle(raw, key, key_id="synthetic-ci-key",
                         published_at=published, previous=sequence_previous)


def synthetic_public_key_bytes():
    return TEST_KEY.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


class RadioSignedReleasePackagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="go-radio-signed-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_exact_dart_pointer_signing_message(self):
        body = payload(admitted())
        draft = new_bundle(body)
        pointer = strict_json(draft.pointer_bytes, maximum=16384)
        expected = (
            "GO-RADIO-CATALOG-POINTER-V1\n"
            "1\n"
            "grosses-ondes-radio\n"
            "1\n"
            "2026-11-20T17:55:00Z\n"
            + hashlib.sha256(body).hexdigest() + "\n"
            + str(len(body)) + "\n"
            + "releases/" + hashlib.sha256(body).hexdigest() + ".json\n"
            + "synthetic-ci-key\n"
        ).encode()
        self.assertEqual(signing_message(pointer), expected)
        self.assertEqual(SIGNING_CONTEXT, "GO-RADIO-CATALOG-POINTER-V1\n")
        self.assertEqual(pointer["catalog_id"], RELEASE_ID)
        self.assertEqual(pointer["signature"]["algorithm"], "Ed25519")
        sig = base64.b64decode(pointer["signature"]["signature_base64"], validate=True)
        TEST_KEY.public_key().verify(sig, expected)

    def test_deterministic_immutable_release_and_pointer_sha(self):
        raw = payload(admitted())
        first = new_bundle(raw)
        second = new_bundle(raw)
        self.assertEqual(first, second)
        self.assertEqual(first.digest, hashlib.sha256(raw).hexdigest())
        self.assertEqual(first.release_path, f"releases/{first.digest}.json")
        self.assertEqual(first.station_count, 1)
        self.assertEqual(first.sequence, 1)
        verified = verify_bundle(
            first.pointer_bytes, first.catalog_bytes, TEST_KEY.public_key())
        self.assertEqual(verified, first)

    def test_staging_has_exact_expected_files_and_no_secret_or_media_artifact(self):
        raw = payload(admitted())
        bundle = new_bundle(raw)
        output = write_staging(self.root / "release-stage", bundle)
        paths = sorted(str(p.relative_to(output)) for p in output.rglob("*") if p.is_file())
        self.assertEqual(paths, [
            "current.json",
            "release-preview.json",
            f"releases/{bundle.digest}.json",
        ])
        self.assertEqual((output / "current.json").read_bytes(), bundle.pointer_bytes)
        self.assertEqual((output / bundle.release_path).read_bytes(), raw)
        meta = json.loads((output / "release-preview.json").read_text())
        self.assertEqual(meta["contentSha256"], bundle.digest)
        self.assertEqual(meta["stationCount"], 1)
        self.assertIs(meta["publicationAllowed"], False)
        self.assertIs(meta["stagingOnly"], True)
        self.assertNotIn("stream", str(meta).lower())
        with self.assertRaises(BundleError):
            write_staging(output, bundle)

    def test_bad_unsigned_legacy_cannot_be_signed_even_with_provided_key(self):
        with self.assertRaisesRegex(BundleError, "editorial gate failed"):
            new_bundle(payload(station()))
        candidate = admitted()
        candidate["streams"][0]["state"] = "candidate_verified"
        with self.assertRaisesRegex(BundleError, "editorial gate failed"):
            new_bundle(payload(candidate))
        candidate["streams"][0]["state"] = "verified"
        candidate["editorial"]["admission_state"] = "legacy_preserved"
        with self.assertRaisesRegex(BundleError, "editorial gate failed"):
            new_bundle(payload(candidate))

    def test_noninitial_release_cannot_skip_verified_previous(self):
        raw = payload(admitted(), sequence=2)
        with self.assertRaises(BundleError):
            new_bundle(raw)
        previous = catalog(admitted(), sequence=1)
        bundle = new_bundle(raw, sequence_previous=previous)
        self.assertEqual(bundle.sequence, 2)

    def test_signed_previous_preserves_all_radio_ids_and_legacy_aliases(self):
        first = admitted()
        previous = catalog(first, sequence=1)
        second = admitted(uid="go-station-000002", alias="new-uuid")
        updated = payload(first, second, sequence=2)
        bundle = new_bundle(updated, sequence_previous=previous)
        self.assertEqual(bundle.station_count, 2)
        self.assertEqual(
            verify_bundle(bundle.pointer_bytes, bundle.catalog_bytes,
                          TEST_KEY.public_key(), previous=previous).sequence, 2)
        missing = payload(second, sequence=2)
        with self.assertRaises(BundleError):
            new_bundle(missing, sequence_previous=previous)
        reassigned = copy.deepcopy(first)
        reassigned["legacy_aliases"] = ["renamed-id"]
        reassigned["radio_browser_uuids"][0]["uuid"] = "renamed-id"
        with self.assertRaises(BundleError):
            new_bundle(payload(reassigned, sequence=2), sequence_previous=previous)

    def test_predecessor_must_verify_before_reading_its_catalog(self):
        first = new_bundle(payload(admitted()))
        previous_dir = write_staging(self.root / "previous", first)
        loaded = load_verified_predecessor(previous_dir, TEST_KEY.public_key())
        self.assertEqual(loaded["release_sequence"], 1)
        other = Ed25519PrivateKey.generate()
        with self.assertRaisesRegex(BundleError, "signature"):
            load_verified_predecessor(previous_dir, other.public_key())
        # Corrupt the pointer; an attacker cannot switch to an unsigned prior.
        pointer_path = previous_dir / "current.json"
        p = json.loads(pointer_path.read_text())
        p["release_sequence"] = 200
        pointer_path.write_bytes(wire_bytes(p))
        with self.assertRaises(BundleError):
            load_verified_predecessor(previous_dir, TEST_KEY.public_key())

    def test_ed25519_catches_tampering_with_any_pointer_field(self):
        original = new_bundle(payload(admitted()))
        for field, new in (
            ("published_at", "2026-11-21T17:55:00Z"),
            ("release_sequence", 2),
            ("content_length", 999999),
        ):
            pointer = json.loads(original.pointer_bytes)
            pointer[field] = new
            with self.subTest(field=field), self.assertRaises(BundleError):
                verify_bundle(wire_bytes(pointer), original.catalog_bytes,
                              TEST_KEY.public_key())

    def test_catalog_tampering_and_key_substitution_rejected(self):
        original = new_bundle(payload(admitted()))
        tampered = original.catalog_bytes.replace(b"Radio fictive", b"Radio maligne")
        with self.assertRaisesRegex(BundleError, "mismatch"):
            verify_bundle(original.pointer_bytes, tampered, TEST_KEY.public_key())
        wrong_key = Ed25519PrivateKey.generate().public_key()
        with self.assertRaisesRegex(BundleError, "signature"):
            verify_bundle(original.pointer_bytes, original.catalog_bytes, wrong_key)

    def test_duplicate_json_fields_rejected_even_when_json_decode_accepts_them(self):
        with self.assertRaisesRegex(BundleError, "Duplicate JSON"):
            strict_json(b'{"schema_version":1,"schema_version":1}', maximum=1024)
        with self.assertRaises(BundleError):
            new_bundle(b'{"schema_version":1,"schema_version":1}')

    def test_invalid_clock_and_key_names_cannot_be_signed(self):
        raw = payload(admitted())
        for instant in ("2026-02-30T01:00:00Z", "2026-11-20T17:55:00+01:00",
                        "2026-11-20", "2026-11-20T17:55:00.123Z"):
            with self.subTest(instant=instant), self.assertRaises(BundleError):
                new_bundle(raw, published=instant)
        for key_id in ("../secrets", "", "unknown key", "x" * 100):
            with self.subTest(key_id=key_id), self.assertRaises(BundleError):
                create_bundle(raw, TEST_KEY, key_id=key_id, published_at=TIMESTAMP)

    def test_signature_is_required_beyond_incomplete_pointer_json_schema(self):
        bundle = new_bundle(payload(admitted()))
        pointer = json.loads(bundle.pointer_bytes)
        del pointer["signature"]
        with self.assertRaises(BundleError):
            verify_bundle(wire_bytes(pointer), bundle.catalog_bytes, TEST_KEY.public_key())

    def test_no_actual_output_on_rejected_catalogue(self):
        target = self.root / "should-not-exist"
        with self.assertRaises(BundleError):
            bundle = new_bundle(payload(station()))
            write_staging(target, bundle)
        self.assertFalse(target.exists())

    def test_signing_material_outside_repository_requires_file_mode_600(self):
        file = self.root / "local-test-only-ed25519-seed.txt"
        file.write_bytes(base64.b64encode(bytes(range(32))) + b"\n")
        file.chmod(0o644)
        if __import__("os").name != "nt":
            with self.assertRaisesRegex(BundleError, "chmod 600"):
                read_private_seed(file)
        file.chmod(0o600)
        key = read_private_seed(file)
        bundle = create_bundle(payload(admitted()), key,
                               key_id="synthetic-ci-key", published_at=TIMESTAMP)
        self.assertEqual(bundle.station_count, 1)
        public = self.root / "synthetic-public-key.txt"
        public.write_bytes(base64.b64encode(synthetic_public_key_bytes()))
        verify_bundle(bundle.pointer_bytes, bundle.catalog_bytes, read_public_key(public))
        with self.assertRaises(BundleError):
            read_private_seed(self.root / "missing-private.txt")

    def test_cli_rejects_missing_offline_guard_and_does_not_write_files(self):
        fixture = self.root / "fictional.json"
        fixture.write_bytes(payload(admitted()))
        key_path = self.root / "synthetic-private-key.txt"
        key_path.write_bytes(base64.b64encode(bytes(range(32))))
        key_path.chmod(0o600)
        args = [
            "--catalog", str(fixture), "--output-dir", str(self.root / "staged"),
            "--signing-key-file", str(key_path),
            "--key-id", "synthetic-ci-key", "--published-at", TIMESTAMP,
        ]
        with self.assertRaises(SystemExit) as e:
            main(args)
        self.assertEqual(e.exception.code, 2)
        self.assertFalse((self.root / "staged").exists())
        self.assertEqual(main(args + ["--offline-stage-only"]), 0)
        self.assertTrue((self.root / "staged/current.json").exists())

    def test_signer_never_opens_network(self):
        with patch.object(socket, "create_connection",
                          side_effect=AssertionError("Network forbidden")):
            bundle = new_bundle(payload(admitted()))
            output = write_staging(self.root / "offline", bundle)
            self.assertTrue((output / "current.json").is_file())

    def test_existing_or_untrusted_output_never_overwritten(self):
        bundle = new_bundle(payload(admitted()))
        directory = self.root / "nonempty"
        directory.mkdir()
        (directory / "important.txt").write_text("do not touch")
        with self.assertRaises(BundleError):
            write_staging(directory, bundle)
        self.assertEqual((directory / "important.txt").read_text(), "do not touch")

    def test_schema_rejects_unsupported_stream_metadata_before_signature(self):
        record = admitted()
        record["streams"][0]["codec"] = "x" * 100
        with self.assertRaises(BundleError):
            validate_release_content(payload(record))


if __name__ == "__main__":
    unittest.main()
