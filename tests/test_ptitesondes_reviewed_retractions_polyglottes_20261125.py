"""Exact six-record mixed programme correction; preserve all other data."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ptitesondes_reviewed_retractions import reviewed_retraction, digest

IDS = set(["openagenda-88464730-2026-11-28","openagenda-88464730-2026-12-01","openagenda-88464730-2026-12-02","openagenda-88464730-2026-12-03","openagenda-88464730-2026-12-04","openagenda-88464730-2026-12-05"])


def fixture():
    catalogue = json.loads((ROOT / "docs/ptitesondes/sorties.json").read_text())
    manifest = json.loads((ROOT / "config/ptitesondes-reviewed-retractions-20261125-polyglottes.json").read_text())
    present = {e["id"] for e in catalogue["events"]}
    for row in manifest["approvals"]:
        if row["expected_event"]["id"] not in present:
            catalogue["events"].append(deepcopy(row["expected_event"]))
    return catalogue, manifest


class PolyglottesRetractionTests(unittest.TestCase):
    def test_exact_reviewed_ids_and_immutable_remainder(self):
        original, manifest = fixture()
        snapshot = deepcopy(original)
        self.assertEqual({row["expected_event"]["id"] for row in manifest["approvals"]}, IDS)
        self.assertEqual(len(manifest["approvals"]), 6)
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

    def test_mixed_programme_evidence_must_match_exact_uid_and_official_host(self):
        original, manifest = fixture()
        for url in ("https://example.org/que-faire-a-nantes/agenda/88464730_fake",
                    "https://metropole.nantes.fr/que-faire-a-nantes/agenda/1_other"):
            with self.subTest(url=url):
                bad = deepcopy(manifest)
                bad["approvals"][0]["evidence_url"] = url
                with self.assertRaises(ValueError):
                    reviewed_retraction(original, bad)
