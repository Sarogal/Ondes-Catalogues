"""Exact 53-record park opening-hours correction; preserve all other data."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ptitesondes_reviewed_retractions import reviewed_retraction, digest

IDS = set(["openagenda-23913876-2026-11-26","openagenda-23913876-2026-11-27","openagenda-23913876-2026-11-28","openagenda-23913876-2026-11-29","openagenda-23913876-2026-11-30","openagenda-23913876-2026-12-01","openagenda-23913876-2026-12-02","openagenda-23913876-2026-12-03","openagenda-23913876-2026-12-04","openagenda-23913876-2026-12-05","openagenda-23913876-2026-12-06","openagenda-23913876-2026-12-07","openagenda-23913876-2026-12-08","openagenda-23913876-2026-12-09","openagenda-23913876-2026-12-10","openagenda-23913876-2026-12-11","openagenda-23913876-2026-12-12","openagenda-23913876-2026-12-13","openagenda-23913876-2026-12-14","openagenda-23913876-2026-12-15","openagenda-23913876-2026-12-16","openagenda-23913876-2026-12-17","openagenda-23913876-2026-12-18","openagenda-23913876-2026-12-19","openagenda-23913876-2026-12-20","openagenda-23913876-2026-12-21","openagenda-23913876-2026-12-22","openagenda-23913876-2026-12-23","openagenda-23913876-2026-12-24","openagenda-23913876-2026-12-25","openagenda-23913876-2026-12-26","openagenda-23913876-2026-12-27","openagenda-23913876-2026-12-28","openagenda-23913876-2026-12-29","openagenda-23913876-2026-12-30","openagenda-23913876-2026-12-31","openagenda-23913876-2027-01-01","openagenda-23913876-2027-01-02","openagenda-23913876-2027-01-03","openagenda-23913876-2027-01-04","openagenda-23913876-2027-01-05","openagenda-23913876-2027-01-06","openagenda-23913876-2027-01-07","openagenda-23913876-2027-01-08","openagenda-23913876-2027-01-09","openagenda-23913876-2027-01-10","openagenda-23913876-2027-01-11","openagenda-23913876-2027-01-12","openagenda-23913876-2027-01-13","openagenda-23913876-2027-01-14","openagenda-23913876-2027-01-15","openagenda-23913876-2027-01-16","openagenda-23913876-2027-01-17"])


def fixture():
    catalogue = json.loads((ROOT / "docs/ptitesondes/sorties.json").read_text())
    manifest = json.loads((ROOT / "config/ptitesondes-reviewed-retractions-20261125-hameau.json").read_text())
    present = {e["id"] for e in catalogue["events"]}
    for row in manifest["approvals"]:
        if row["expected_event"]["id"] not in present:
            catalogue["events"].append(deepcopy(row["expected_event"]))
    return catalogue, manifest


class HameauRetractionTests(unittest.TestCase):
    def test_exact_reviewed_ids_and_immutable_remainder(self):
        original, manifest = fixture()
        snapshot = deepcopy(original)
        self.assertEqual({row["expected_event"]["id"] for row in manifest["approvals"]}, IDS)
        self.assertEqual(len(manifest["approvals"]), 53)
        corrected, audit, changed = reviewed_retraction(original, manifest)
        self.assertTrue(changed)
        self.assertEqual(corrected["events"], [e for e in original["events"] if e["id"] not in IDS])
        self.assertEqual(original, snapshot)
        self.assertEqual({x["id"] for x in audit["withdrawn"]}, IDS)
        self.assertEqual(audit["catalogue_before_sha256"], digest(original))
        self.assertEqual(audit["catalogue_after_sha256"], digest(corrected))
        self.assertEqual(reviewed_retraction(corrected, manifest), (corrected, None, False))

    def test_changed_or_partially_removed_record_rejected(self):
        original, manifest = fixture()
        modified = deepcopy(original)
        next(e for e in modified["events"] if e["id"] in IDS)["time"] = "00:00"
        with self.assertRaises(ValueError):
            reviewed_retraction(modified, manifest)
        removed = deepcopy(original)
        removed["events"] = [e for e in removed["events"] if e["id"] != sorted(IDS)[0]]
        with self.assertRaises(ValueError):
            reviewed_retraction(removed, manifest)

    def test_park_evidence_must_match_exact_uid_and_official_host(self):
        original, manifest = fixture()
        for url in ("https://example.org/fr/le-parc/le-hameau-enchante/",
                    "https://www.duboeuf.com/fr/le-parc/other/"):
            with self.subTest(url=url):
                bad = deepcopy(manifest)
                bad["approvals"][0]["evidence_url"] = url
                with self.assertRaises(ValueError):
                    reviewed_retraction(original, bad)
