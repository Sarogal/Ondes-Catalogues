"""Exact reviewed recruitment correction; preserve all other data."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ptitesondes_reviewed_retractions import reviewed_retraction, digest

IDS = {"openagenda-21002913-2026-12-01"}


def fixture():
    catalogue = json.loads((ROOT / "docs/ptitesondes/sorties.json").read_text())
    manifest = json.loads((ROOT / "config/ptitesondes-reviewed-retractions-20261126-recruitment.json").read_text())
    present = {e["id"] for e in catalogue["events"]}
    for row in manifest["approvals"]:
        if row["expected_event"]["id"] not in present:
            catalogue["events"].append(deepcopy(row["expected_event"]))
    return catalogue, manifest


class RecruitmentRetractionTests(unittest.TestCase):
    def test_exact_reviewed_ids_and_immutable_remainder(self):
        original, manifest = fixture()
        snapshot = deepcopy(original)
        self.assertEqual({row["expected_event"]["id"] for row in manifest["approvals"]}, IDS)
        self.assertEqual(len(manifest["approvals"]), 1)
        corrected, audit, changed = reviewed_retraction(original, manifest)
        self.assertTrue(changed)
        self.assertEqual(corrected["events"], [e for e in original["events"] if e["id"] not in IDS])
        self.assertEqual(original, snapshot)
        self.assertEqual({x["id"] for x in audit["withdrawn"]}, IDS)
        self.assertEqual(audit["catalogue_before_sha256"], digest(original))
        self.assertEqual(audit["catalogue_after_sha256"], digest(corrected))
        self.assertEqual(reviewed_retraction(corrected, manifest), (corrected, None, False))

    def test_changed_record_rejected(self):
        original, manifest = fixture()
        modified = deepcopy(original)
        next(e for e in modified["events"] if e["id"] in IDS)["time"] = "00:00"
        with self.assertRaises(ValueError):
            reviewed_retraction(modified, manifest)

    def test_recruitment_evidence_must_match_exact_source(self):
        original, manifest = fixture()
        for url in ("https://example.org/event",
                    "https://openagenda.com/other/events/21002913_demo"):
            with self.subTest(url=url):
                bad = deepcopy(manifest)
                bad["approvals"][0]["evidence_url"] = url
                with self.assertRaises(ValueError):
                    reviewed_retraction(original, bad)
