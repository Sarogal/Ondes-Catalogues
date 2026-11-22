#!/usr/bin/env python3
"""No-network artwork SHA/decoder checks and non-publication safeguards."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import sys
import unittest

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from probe_open_radio_artwork import (
    CandidateError, evaluate, inspect_image_bytes,
)
from PIL import Image

MANIFEST = TOOLS.parents[1] / "grossesondes/radio-test-apk/candidates/punk_official_sources.json"


class OfficialArtCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_logo_candidates_remain_unreviewed(self):
        report = evaluate(self.document, network=False)
        self.assertFalse(report["publication_allowed"])
        self.assertFalse(report["signed_release_generated"])
        self.assertEqual(len(report["radios"]), 2)
        for row in report["radios"]:
            self.assertTrue(row["logo_editorial_review_required"])
            self.assertTrue(row["logo_evidence"])
            for logo in row["logo_evidence"]:
                self.assertFalse(logo["image_bytes_decoded"])
                self.assertFalse(logo["catalogue_logo_published"])
                self.assertFalse(logo["editorially_approved"])

    def test_valid_synthetic_logo_has_digest_dimensions(self):
        image = Image.new("RGB", (96, 96), color=(10, 10, 10))
        buf = BytesIO()
        image.save(buf, "PNG")
        result = inspect_image_bytes(buf.getvalue())
        self.assertEqual(result["image_format"], "PNG")
        self.assertEqual(result["width"], 96)
        self.assertEqual(len(result["sha256"]), 64)

    def test_corrupt_and_too_large_bytes_refused(self):
        with self.assertRaises(CandidateError):
            inspect_image_bytes(b"not an image" * 50)
        with self.assertRaises(CandidateError):
            inspect_image_bytes(b"x" * (2 * 1024 * 1024 + 1))

    def test_decoder_rejects_tiny_images(self):
        image = Image.new("RGB", (10, 10), color=(10, 10, 10))
        buf = BytesIO()
        image.save(buf, "PNG")
        with self.assertRaises(CandidateError):
            inspect_image_bytes(buf.getvalue())

    def test_never_accept_status_verified(self):
        document = deepcopy(self.document)
        document["candidates"][0]["logo_candidates"][0]["state"] = "verified"
        with self.assertRaises(CandidateError):
            evaluate(document, network=False)


if __name__ == "__main__":
    unittest.main()
