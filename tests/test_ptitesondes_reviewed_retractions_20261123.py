"""Exactly 51 audited commercial booking entries, never 27 historic sessions."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ptitesondes_reviewed_retractions import reviewed_retraction, digest

CAT = ROOT / "docs/ptitesondes/sorties.json"
MANIFEST = ROOT / "config/ptitesondes-reviewed-retractions-20261123.json"
SOURCE = (
    "https://openagenda.com/que-faire-a-paris/events/"
    "94896721_creez-et-enregistrez-votre-musique-en-studio"
)
PREFIX = "openagenda-94896721-"


def fixture():
    catalogue = json.loads(CAT.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    seen = {x["id"] for x in catalogue["events"]}
    # Deterministic after the one-off transaction has already removed the
    # targets: restore exact immutable reviewed snapshots in memory only.
    for row in manifest["approvals"]:
        expected = row["expected_event"]
        if expected["id"] not in seen:
            catalogue["events"].append(deepcopy(expected))
            seen.add(expected["id"])
    return catalogue, manifest


class CommercialBookingReversalTests(unittest.TestCase):
    def test_manifest_is_exactly_the_new_fifty_one_not_the_old_twenty_seven(self):
        document, manifest = fixture()
        approvals = manifest["approvals"]
        self.assertEqual(len(approvals), 51)
        self.assertEqual(manifest["reviewed_on"], "2026-11-23")
        self.assertEqual({x["action"] for x in approvals}, {"withdraw"})
        self.assertEqual({x["reason_code"] for x in approvals},
                         {"evergreen_commercial_studio_availability"})
        self.assertEqual({x["evidence_url"] for x in approvals}, {SOURCE})
        self.assertEqual({x["expected_event"]["source_url"] for x in approvals},
                         {SOURCE})
        expected = {x["expected_event"]["id"] for x in approvals}
        self.assertEqual(len(expected), 51)
        self.assertTrue(all(
            event_id.startswith(PREFIX)
            and "2026-12-19" <= event_id[len(PREFIX):] <= "2027-02-07"
            for event_id in expected
        ))
        # No old session has been selected for withdrawal.
        still_historical = [
            x for x in document["events"] if x["id"].startswith(PREFIX)
            and x["id"] not in expected
        ]
        self.assertEqual(len(still_historical), 27)

    def test_audited_retraction_preserves_every_other_event_and_all_fields(self):
        document, manifest = fixture()
        baseline = deepcopy(document)
        wanted = {x["expected_event"]["id"] for x in manifest["approvals"]}
        after, audit, changed = reviewed_retraction(document, manifest)
        self.assertTrue(changed)
        self.assertEqual(len(audit["withdrawn"]), 51)
        self.assertEqual(len(baseline["events"]) - len(after["events"]), 51)
        self.assertEqual(audit["catalogue_before_sha256"], digest(baseline))
        self.assertEqual(audit["catalogue_after_sha256"], digest(after))
        self.assertEqual({x["id"] for x in audit["withdrawn"]}, wanted)
        self.assertEqual(after["events"], [
            event for event in baseline["events"] if event["id"] not in wanted
        ])
        self.assertEqual(document, baseline)
        self.assertEqual(len([e for e in after["events"]
                              if e["id"].startswith(PREFIX)]), 27)

    def test_review_is_idempotent_and_never_publishes_events(self):
        document, manifest = fixture()
        corrected, _, changed = reviewed_retraction(document, manifest)
        self.assertTrue(changed)
        repeated, audit, changed_again = reviewed_retraction(corrected, manifest)
        self.assertFalse(changed_again)
        self.assertIsNone(audit)
        self.assertEqual(repeated, corrected)

    def test_changed_record_or_partial_retraction_fails_transactionally(self):
        original, manifest = fixture()
        target = manifest["approvals"][0]["expected_event"]["id"]
        mutated = deepcopy(original)
        next(x for x in mutated["events"] if x["id"] == target)["venue"] = "Autre salle"
        with self.assertRaisesRegex(ValueError, "reviewed_record_changed"):
            reviewed_retraction(mutated, manifest)
        partly_removed = deepcopy(original)
        partly_removed["events"] = [
            x for x in partly_removed["events"] if x["id"] != target
        ]
        with self.assertRaisesRegex(ValueError, "partially_applied_plan"):
            reviewed_retraction(partly_removed, manifest)

    def test_wrong_evidence_and_unauthorised_reason_are_refused(self):
        document, manifest = fixture()
        changed = deepcopy(manifest)
        changed["approvals"][0]["evidence_url"] = "https://other.example/claim"
        with self.assertRaisesRegex(ValueError, "invalid_approval_identity_or_reason"):
            reviewed_retraction(document, changed)
        changed = deepcopy(manifest)
        changed["approvals"][0]["reason_code"] = "anything_else"
        with self.assertRaisesRegex(ValueError, "invalid_reviewed_approval"):
            reviewed_retraction(document, changed)


if __name__ == "__main__":
    unittest.main()
