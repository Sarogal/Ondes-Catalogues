"""Private approval ledger transport: precise Git blob, no publish shortcuts."""
import base64
from io import BytesIO
import json
import unittest
from unittest import mock
from scripts import concerts_cloud_sync as sync
from scripts import concerts_private_approval_preview as preview


def wrapped(obj):
    body = json.dumps(obj).encode("utf-8")
    return {"type": "file", "size": len(body), "encoding": "base64",
            "content": base64.b64encode(body).decode("ascii"),
            "sha": "a" * 40}


class Response(BytesIO):
    status = 200


class PrivateLedgerBlobTests(unittest.TestCase):
    def setUp(self):
        self.raw = {"schema": sync.SCHEMA, "approvals": []}
        self.meta = wrapped(self.raw)

    def test_small_contents_base64_is_unchanged(self):
        with mock.patch.object(sync, "urlopen",
                               return_value=Response(
                                   json.dumps(self.meta).encode("utf-8"))) as api:
            self.assertEqual(sync.read_approvals("test-token"), self.raw)
        self.assertEqual(api.call_count, 1)

    def test_large_file_is_fetched_from_exact_private_blob_sha(self):
        large_meta = dict(self.meta, content="", encoding="none")
        calls = []
        def fetch(req, timeout):
            calls.append(req.full_url)
            payload = large_meta if len(calls) == 1 else self.meta
            return Response(json.dumps(payload).encode("utf-8"))
        with mock.patch.object(sync, "urlopen", side_effect=fetch):
            self.assertEqual(sync.read_approvals("test-token"), self.raw)
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            calls[1],
            "https://api.github.com/repos/Sarogal/GrossesOndes/git/blobs/" +
            self.meta["sha"])

    def test_blob_must_match_sha_and_size(self):
        large_meta = dict(self.meta, content="", encoding="none")
        for payload in (dict(self.meta, sha="b" * 40),
                        dict(self.meta, size=self.meta["size"]-1),
                        dict(self.meta, encoding="none", content="")):
            with self.subTest(payload=payload):
                with mock.patch.object(sync, "urlopen", side_effect=[
                    Response(json.dumps(large_meta).encode("utf-8")),
                    Response(json.dumps(payload).encode("utf-8")),
                ]):
                    with self.assertRaises(ValueError):
                        sync.read_approvals("test-token")

    def test_metadata_rejects_non_sha_or_unbounded_size(self):
        bad = [
            dict(self.meta, encoding="none", sha="../evil"),
            dict(self.meta, encoding="none",
                 size=sync.MAX_PRIVATE_APPROVAL_FILE_BYTES+1),
        ]
        for meta in bad:
            with self.subTest(meta=meta), mock.patch.object(
                    sync, "urlopen",
                    return_value=Response(json.dumps(meta).encode("utf-8"))):
                with self.assertRaises(ValueError):
                    sync.read_approvals("test-token")

    def test_private_pr_preflight_can_read_same_sha_addressed_blob(self):
        meta = dict(self.meta, encoding="none", content="")
        paths = []
        def fetch(path, token):
            paths.append(path)
            return meta if len(paths) == 1 else self.meta
        with mock.patch.object(preview, "github_json", side_effect=fetch):
            item = preview.github_approval("b"*40, "test-token")
        self.assertEqual(item, self.raw)
        self.assertEqual(paths[1], "/git/blobs/" + self.meta["sha"])

    def test_private_pr_preview_rejects_metadata_or_blob_spoofing(self):
        meta = dict(self.meta, encoding="none", content="")
        forged = dict(self.meta, sha="f"*40)
        with mock.patch.object(preview, "github_json",
                               side_effect=[meta, forged]):
            with self.assertRaises(ValueError):
                preview.github_approval("b"*40, "test-token")


if __name__ == "__main__":
    unittest.main()
