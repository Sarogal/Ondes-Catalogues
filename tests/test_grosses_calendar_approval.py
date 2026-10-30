import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from grossesondes_calendar_approval import (
    load_approval, approved_calendar, check_known_calendar,
    merge_staged_with_approved
)
from grossesondes_cloud_sync import build_candidate
from grossesondes_preview import CAL_URL, HIS_URL


def calendars():
    published = json.loads(
        (ROOT / "docs/grossesondes/festivals.json").read_text(encoding="utf-8")
    )
    original = copy.deepcopy(published)
    approved = load_approval()
    assert original["festivals"][-1]["slug"] == "muscadeath-2027"
    original["festivals"].pop()
    original["generatedAt"] = approved["baselineReference"]["generatedAt"]
    lookup = {r["slug"]: r for r in original["festivals"]}
    for patch in approved["changes"]:
        for field, diff in patch["changes"].items():
            assert lookup[patch["slug"]][field] == diff["after"]
            lookup[patch["slug"]][field] = copy.deepcopy(diff["before"])
    return original, published


def archives():
    published = json.loads(
        (ROOT / "docs/grossesondes/festival-history.json").read_text(encoding="utf-8")
    )
    old = copy.deepcopy(published)
    old["updatedAt"] = "2026-10-22"
    old["knownFestivals"] = old["knownFestivals"][:170]
    return old, published


def safe_patch():
    return {
        "schema": "grossesondes.patch.v1",
        "generated_at": "2026-10-30",
        "safe_to_publish": False,
        "source": {
            "festivals": {"url": CAL_URL, "generatedAt": "2026-10-25", "count": 123},
            "history": {"url": HIS_URL, "updatedAt": "2026-10-22", "count": 170},
        },
        "additions": [], "updates": [],
        "history_additions": [], "history_updates": [], "deferred": [],
    }


class TrustedPublishedCalendarTests(unittest.TestCase):
    def test_reconstructs_exact_published_124(self):
        original, published = calendars()
        self.assertEqual(len(original["festivals"]), 123)
        self.assertEqual(approved_calendar(original), published)
        self.assertEqual(check_known_calendar(original, published), "copie_approuvee_124")

    def test_original_123_still_accepted(self):
        original, _ = calendars()
        self.assertEqual(check_known_calendar(original, original), "reference_originale")

    def test_tampered_approval_registry_blocked(self):
        registry = ROOT / "reviews/grossesondes-approved-calendar-delta-2026-10-30.json"
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "approval.json"
            p.write_bytes(registry.read_bytes().replace(b"2026-10-30", b"2026-10-31", 1))
            with self.assertRaises(ValueError):
                load_approval(p)

    def test_deleted_published_festival_blocked(self):
        original, published = calendars()
        published["festivals"].pop(9)
        with self.assertRaises(ValueError):
            check_known_calendar(original, published)

    def test_public_date_tampering_blocked(self):
        original, published = calendars()
        published["festivals"][2]["startDate"] = "2027-12-31"
        with self.assertRaises(ValueError):
            check_known_calendar(original, published)

    def test_extra_unknown_public_festival_blocked(self):
        original, published = calendars()
        published["festivals"].append({"slug": "fake-2027", "name": "Fake"})
        with self.assertRaises(ValueError):
            check_known_calendar(original, published)

    def test_already_verified_lineup_survives_empty_patch(self):
        original, published = calendars()
        result = merge_staged_with_approved(original, copy.deepcopy(original), published)
        self.assertEqual(result, published)

    def test_new_proven_field_does_not_revert_others(self):
        original, published = calendars()
        staged = copy.deepcopy(original)
        target = next(x for x in staged["festivals"] if x["slug"] == "cernunnos-pagan-fest")
        target["lineup"] += ["Test uniquement"]
        result = merge_staged_with_approved(original, staged, published)
        actual = next(x for x in result["festivals"] if x["slug"] == "cernunnos-pagan-fest")
        self.assertEqual(actual["lineup"][-1], "Test uniquement")
        originally_approved = next(x for x in published["festivals"]
                                   if x["slug"] == "cernunnos-pagan-fest")
        self.assertEqual(actual["lineup"][:-1], originally_approved["lineup"])
        self.assertEqual(actual["bands"], 21)
        self.assertEqual(actual["price"], next(x for x in published["festivals"]
                                                if x["slug"] == "cernunnos-pagan-fest")["price"])
        self.assertEqual(len(result["festivals"]), 124)

    def test_no_deletion_in_stage_candidate(self):
        original, published = calendars()
        staged = copy.deepcopy(original)
        staged["festivals"].pop(5)
        with self.assertRaises(ValueError):
            merge_staged_with_approved(original, staged, published)

    def test_cloud_does_not_undo_previously_verified_edits(self):
        original, published = calendars()
        old_history, pub_history = archives()
        snapshot = {"festivals.json": original, "festival-history.json": old_history}
        mirror = {"festivals.json": published, "festival-history.json": pub_history}
        proposed, report = build_candidate(snapshot, mirror, safe_patch(), {}, "2026-10-30")
        self.assertEqual(proposed, published)
        self.assertFalse(report["changed"])
        self.assertEqual(report["candidate_total"], 124)
        self.assertEqual(report["trusted_calendar_base"], "publication_approuvee_124")

    def test_cloud_blocks_unapproved_mirror_edit(self):
        original, published = calendars()
        old_history, pub_history = archives()
        snapshot = {"festivals.json": original, "festival-history.json": old_history}
        published["festivals"][0]["name"] = "NOM MODIFIÉ SANS PREUVE"
        mirror = {"festivals.json": published, "festival-history.json": pub_history}
        with self.assertRaises(ValueError):
            build_candidate(snapshot, mirror, safe_patch(), {}, "2026-10-30")


if __name__ == "__main__":
    unittest.main()
