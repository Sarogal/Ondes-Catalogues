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
from grossesondes_cloud_sync import build_candidate, verify_published_head
from grossesondes_preview import CAL_URL, HIS_URL


def calendars():
    """Build a frozen approval fixture; daily public data may legitimately evolve."""
    live = json.loads(
        (ROOT / "docs/grossesondes/festivals.json").read_text(encoding="utf-8")
    )
    approval = load_approval()
    n = approval["baselineReference"]["calendarCount"]
    original = copy.deepcopy(live)
    assert len(original["festivals"]) >= n + len(approval["additions"])
    assert original["festivals"][n]["slug"] == approval["additions"][0]["slug"]
    original["festivals"] = original["festivals"][:n]
    original["generatedAt"] = approval["baselineReference"]["generatedAt"]
    lookup = {r["slug"]: r for r in original["festivals"]}
    for item in approval["changes"]:
        for field, diff in item["changes"].items():
            assert field in lookup[item["slug"]]
            lookup[item["slug"]][field] = copy.deepcopy(diff["before"])
    # The certificate tests target the frozen 30/10 approval, not a later daily deployment.
    return original, approved_calendar(original, approval)


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

    def test_signed_current_calendar_does_not_revert_validated_updates(self):
        # The historic 30 Oct approval must coexist with independently
        # verified later publications, without requiring a false rebase.
        original, _ = calendars()
        _, public_history = archives()
        current = json.loads(
            (ROOT / "docs/grossesondes/festivals.json").read_text(encoding="utf-8")
        )
        head = verify_published_head(current)
        self.assertEqual(head["calendarCount"], len(current["festivals"]))
        self.assertEqual(head["generatedAt"], current["generatedAt"])
        old_history = copy.deepcopy(public_history)
        old_history["updatedAt"] = "2026-10-22"
        old_history["knownFestivals"] = old_history["knownFestivals"][:170]
        result, report = build_candidate(
            {"festivals.json": original, "festival-history.json": old_history},
            {"festivals.json": current, "festival-history.json": public_history},
            safe_patch(), {}, current["generatedAt"], trusted_published=True
        )
        self.assertEqual(result, current)
        self.assertFalse(report["changed"])
        self.assertEqual(report["trusted_calendar_base"],
                         "publication_precedente_signee")

    def test_signed_head_rejects_memory_tampering_with_same_metadata(self):
        current = json.loads(
            (ROOT / "docs/grossesondes/festivals.json").read_text(encoding="utf-8")
        )
        current["festivals"][0]["name"] = "Faux nom non approuvé"
        with self.assertRaisesRegex(ValueError, "version Git signée"):
            verify_published_head(current)

    def test_signed_head_rejects_removed_calendar_entry(self):
        current = json.loads(
            (ROOT / "docs/grossesondes/festivals.json").read_text(encoding="utf-8")
        )
        current["festivals"].pop()
        with self.assertRaises(ValueError):
            verify_published_head(current)

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

    def test_previously_published_muscadeath_keeps_verified_record(self):
        original, published = calendars()
        staged = copy.deepcopy(original)
        older = copy.deepcopy(load_approval()["additions"][0])
        older["notes"] = "Ancienne formulation issue du patch cumulatif"
        staged["festivals"].append(older)
        result = merge_staged_with_approved(original, staged, published)
        self.assertEqual(result, published)

    def test_published_muscadeath_cannot_gain_unverified_date(self):
        original, published = calendars()
        staged = copy.deepcopy(original)
        older = copy.deepcopy(load_approval()["additions"][0])
        older["startDate"] = "2027-07-14"
        staged["festivals"].append(older)
        with self.assertRaises(ValueError):
            merge_staged_with_approved(original, staged, published)

    def test_published_muscadeath_cannot_change_official_source(self):
        original, published = calendars()
        staged = copy.deepcopy(original)
        older = copy.deepcopy(load_approval()["additions"][0])
        older["source"] = "https://example.org/"
        staged["festivals"].append(older)
        with self.assertRaises(ValueError):
            merge_staged_with_approved(original, staged, published)

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
