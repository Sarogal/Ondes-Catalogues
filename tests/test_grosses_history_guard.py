import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from grossesondes_history_guard import (
    load_registry, validate_history_extension
)
from grossesondes_preview import audit
from grossesondes_cloud_sync import build_candidate
from test_grosses_preview import samples


def history_pair():
    extended = json.loads((ROOT / "docs/grossesondes/festival-history.json").read_text(encoding="utf-8"))
    original = copy.deepcopy(extended)
    original["knownFestivals"] = original["knownFestivals"][:170]
    original["updatedAt"] = "2026-10-22"
    return original, extended


class HistoricalExtensionTests(unittest.TestCase):
    def test_real_173_extension_only(self):
        original, extended = history_pair()
        self.assertEqual(len(original["knownFestivals"]), 170)
        self.assertEqual(len(extended["knownFestivals"]), 173)
        self.assertEqual(validate_history_extension(original, extended), 3)
        self.assertEqual([x["slug"] for x in extended["knownFestivals"][170:]],
                         load_registry()["approvedSlugs"])

    def test_original_170_still_allowed(self):
        original, _ = history_pair()
        self.assertEqual(validate_history_extension(original, original), 0)

    def test_removed_old_archive_blocked(self):
        original, extended = history_pair()
        extended["knownFestivals"].pop(8)
        with self.assertRaises(ValueError):
            validate_history_extension(original, extended)

    def test_old_archive_modified_blocked(self):
        original, extended = history_pair()
        extended["knownFestivals"][3]["name"] = "Nom modifié"
        with self.assertRaises(ValueError):
            validate_history_extension(original, extended)

    def test_old_archive_reordered_blocked(self):
        original, extended = history_pair()
        extended["knownFestivals"][1], extended["knownFestivals"][2] = (
            extended["knownFestivals"][2], extended["knownFestivals"][1])
        with self.assertRaises(ValueError):
            validate_history_extension(original, extended)

    def test_unapproved_punk_archive_blocked(self):
        original, extended = history_pair()
        registry = load_registry()
        unapproved = next(x for x in registry["additions"]
                          if x["slug"] == "festival-de-la-mer-landunvez")
        extended["knownFestivals"].append(unapproved)
        with self.assertRaises(ValueError):
            validate_history_extension(original, extended)

    def test_unknown_addition_blocked(self):
        original, extended = history_pair()
        extended["knownFestivals"].append({"slug": "inconnu", "name": "Inconnu"})
        with self.assertRaises(ValueError):
            validate_history_extension(original, extended)

    def test_duplicates_blocked(self):
        original, extended = history_pair()
        extended["knownFestivals"][-1]["slug"] = original["knownFestivals"][0]["slug"]
        with self.assertRaises(ValueError):
            validate_history_extension(original, extended)

    def test_extra_metadata_blocked(self):
        original, extended = history_pair()
        extended["notes"] = "différent"
        with self.assertRaises(ValueError):
            validate_history_extension(original, extended)

    def test_edit_approved_date_blocked(self):
        original, extended = history_pair()
        extended["knownFestivals"][-1]["endDate"] = "2027-07-15"
        with self.assertRaises(ValueError):
            validate_history_extension(original, extended)

    def test_edit_official_proof_blocked(self):
        original, extended = history_pair()
        extended["knownFestivals"][-1]["source"] = "https://example.org/"
        with self.assertRaises(ValueError):
            validate_history_extension(original, extended)

    def test_preview_accepts_exact_historical_append(self):
        cal, old_stub, patch = samples()
        registry = load_registry()
        ext_stub = copy.deepcopy(old_stub)
        ext_stub["updatedAt"] = registry["releaseDate"]
        ext_stub["knownFestivals"] += [
            next(x for x in registry["additions"] if x["slug"] == slug)
            for slug in registry["approvedSlugs"]
        ]
        report = audit(cal, ext_stub, patch, cal, old_stub)
        self.assertEqual(report["deleted"], 0)
        self.assertEqual(report["current_history"], 173)

    def test_cloud_candidate_accepts_exact_historical_append(self):
        from test_grosses_stage import fixtures
        cal, old_history, patch = fixtures()
        reg = load_registry()
        mirror_history = copy.deepcopy(old_history)
        mirror_history["updatedAt"] = reg["releaseDate"]
        mirror_history["knownFestivals"] += [
            next(x for x in reg["additions"] if x["slug"] == slug)
            for slug in reg["approvedSlugs"]
        ]
        snapshot = {"festivals.json": cal, "festival-history.json": old_history}
        published = {"festivals.json": cal, "festival-history.json": mirror_history}
        out, report = build_candidate(snapshot, published, patch, {}, "2026-10-30")
        self.assertFalse(report["changed"])
        self.assertEqual(len(out["festivals"]), 100)
        self.assertTrue(report["unchanged_history"])

    def test_cloud_rejects_undeclared_historical_append(self):
        from test_grosses_stage import fixtures
        cal, old_history, patch = fixtures()
        mirror = copy.deepcopy(old_history)
        mirror["knownFestivals"].append({"slug": "unknown", "name": "Unverified"})
        snapshot = {"festivals.json": cal, "festival-history.json": old_history}
        published = {"festivals.json": cal, "festival-history.json": mirror}
        with self.assertRaises(ValueError):
            build_candidate(snapshot, published, patch, {}, "2026-10-30")


if __name__ == "__main__":
    unittest.main()
