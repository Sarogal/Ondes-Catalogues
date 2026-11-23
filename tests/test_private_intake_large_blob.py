"""GitHub Contents >1 MiB must use pinned blob reads with integrity checks."""
import base64
from datetime import date
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from private_intake import (
    latest, github, MAX_PRIVATE_PATCH, PATH, BRANCH,
)

TODAY = date(2026, 11, 23)
TOKEN = "read-only-test-token"


def fixture(*, size=1_300_000):
    # A 1.3 MiB raw patch is *larger* than GitHub's 1 MiB Contents inline
    # limit. Only the Git Blob endpoint is allowed to produce its bytes.
    document = {
        "generated_at": TODAY.isoformat(),
        "open_world_research": [],
        "synthetic_test_padding": "x" * size,
    }
    raw = json.dumps(document).encode("utf-8")
    sha = hashlib.sha1(
        b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
    ).hexdigest()
    item = {
        "type": "file", "name": "patch-2026-11-23.json",
        "path": PATH + "/patch-2026-11-23.json",
        "sha": sha, "size": len(raw),
    }
    blob = {
        "encoding": "base64", "content": base64.b64encode(raw).decode(),
        "sha": sha, "size": len(raw),
    }
    return document, item, blob


class PrivateIntakeLargeBlobTests(unittest.TestCase):
    def test_large_patch_reads_immutable_blob_instead_of_none_encoding(self):
        original, item, blob = fixture()
        calls = []
        def reader(path, token, *, blob=False):
            calls.append((path, token, blob))
            return blob_response if blob else [item]
        blob_response = blob
        with patch("private_intake.github", side_effect=reader):
            loaded, path = latest(TOKEN, TODAY)
        self.assertEqual(loaded, original)
        self.assertEqual(path, item["path"])
        self.assertEqual(calls[0][2], False)
        self.assertEqual(calls[1], (item["sha"], TOKEN, True))
        self.assertEqual(len(calls), 2)

    def test_blob_sha_and_size_are_not_trusted_without_matching_bytes(self):
        _, item, blob = fixture(size=16)
        variants = [
            dict(blob, sha="0" * 40),
            dict(blob, size=blob["size"] + 1),
            dict(blob, content=base64.b64encode(b"other").decode()),
            dict(blob, encoding="none", content=""),
            dict(blob, content="!!notbase64!!"),
        ]
        for bad in variants:
            with self.subTest(bad=list(bad)):
                def reader(path, token, *, blob=False):
                    return bad if blob else [item]
                with patch("private_intake.github", side_effect=reader):
                    with self.assertRaises(ValueError):
                        latest(TOKEN, TODAY)

    def test_untrusted_path_sha_and_oversized_metadata_fail_before_blob_read(self):
        _, item, blob = fixture(size=12)
        for changed in (
            dict(item, sha="missing"),
            dict(item, path="automation-intake/ptitesondes/other.json"),
            dict(item, size=MAX_PRIVATE_PATCH + 1),
        ):
            with self.subTest(changed=changed):
                with patch("private_intake.github", return_value=[changed]) as mock:
                    with self.assertRaises(ValueError):
                        latest(TOKEN, TODAY)
                    self.assertEqual(mock.call_count, 1)

    def test_file_and_blob_endpoints_are_restricted(self):
        with self.assertRaises(ValueError):
            github("../admin/secrets", TOKEN)
        with self.assertRaises(ValueError):
            github("a" * 39 + "/oops", TOKEN, blob=True)
        with self.assertRaises(ValueError):
            github("0" * 40 + "?ref=main", TOKEN, blob=True)

    def test_old_or_wrong_dated_payload_fails_closed(self):
        _, item, blob = fixture(size=5)
        wrong_payload = {"generated_at": "2026-11-22"}
        raw = json.dumps(wrong_payload).encode()
        sha = hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw
        ).hexdigest()
        wrong_item = dict(item, sha=sha, size=len(raw))
        wrong_blob = dict(blob, sha=sha, size=len(raw),
                          content=base64.b64encode(raw).decode())
        def reader(path, token, *, blob=False):
            return wrong_blob if blob else [wrong_item]
        with patch("private_intake.github", side_effect=reader):
            with self.assertRaisesRegex(ValueError, "Date différente"):
                latest(TOKEN, TODAY)
