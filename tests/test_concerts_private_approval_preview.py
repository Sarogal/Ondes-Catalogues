"""Offline tests of the *read-only* private-approval preview safeguards.

No secret, GitHub API or private repository access is required by these tests.
"""
import copy
import datetime as dt
import unittest
from unittest.mock import patch

from scripts import concerts_private_approval_preview as ci


OLD_ROW = {"event": {"id": "go-c-20261201-test-old"}}
NEW_ROW = {
    "reviewDecision": "approved",
    "reviewedBy": "independent-official-verifier",
    "reviewedAt": "2026-11-06",
    "officialEvidence": [
        {"url": "https://venue.example/live", "proofType": "official-organizer-or-venue"},
        {"url": "https://artist.example/tour", "proofType": "official-artist-tour-calendar"},
    ],
    "event": {"id": "go-c-20261202-test-new"},
    "newArtists": [],
}
BEFORE = {
    "schema": "grossesondes.concert.approvals.v1",
    "approvals": [OLD_ROW],
    "venueApprovals": [{"venue": {"id": "known-venue"}}],
}
AFTER = dict(BEFORE, approvals=[OLD_ROW, NEW_ROW])
PUBLISHED = {"events": [{"id": "go-c-20261201-test-old"}],
             "artists": [], "venues": []}
COUNT = {"newEvents": 1, "newArtists": 0, "newVenues": 0,
         "correctedEvents": 0, "correctedVenues": 0, "held": []}


class PrivateApprovalReadOnlyTests(unittest.TestCase):
    def test_exactly_one_append_and_no_private_content_output(self):
        self.assertEqual(ci.append_only(BEFORE, AFTER, PUBLISHED),
                         ["go-c-20261202-test-new"])

    def test_prior_signed_approval_mutation_and_reorder_rejected(self):
        for altered in (
            dict(AFTER, approvals=[dict(OLD_ROW, event={"id": "other"}), NEW_ROW]),
            dict(AFTER, approvals=[NEW_ROW, OLD_ROW]),
            dict(AFTER, venueApprovals=[]),
            dict(AFTER, schema="untrusted-schema"),
            dict(AFTER, approvals=[OLD_ROW]),
            dict(AFTER, approvals=[OLD_ROW, NEW_ROW, NEW_ROW]),
        ):
            with self.subTest(altered=str(altered)[:40]), self.assertRaises(ValueError):
                ci.append_only(BEFORE, altered, PUBLISHED)

    def test_requires_existing_signer_and_no_unsigned_support_act(self):
        for mutation in (
            ("reviewer", lambda row: row.update(reviewedBy="automated-official-recheck")),
            ("decision", lambda row: row.update(reviewDecision="pending")),
            ("newArtist", lambda row: row.update(newArtists=[{"id": "a", "name": "A"}])),
            ("missingProof", lambda row: row["officialEvidence"].pop()),
            ("duplicateId", lambda row: row["event"].update(id=OLD_ROW["event"]["id"])),
        ):
            key, change = mutation
            candidate = copy.deepcopy(AFTER)
            change(candidate["approvals"][-1])
            with self.subTest(key=key), self.assertRaises(ValueError):
                ci.append_only(BEFORE, candidate, PUBLISHED)

    def test_read_only_simulation_and_no_existing_event_change(self):
        after = copy.deepcopy(PUBLISHED)
        after["events"].append({"id": NEW_ROW["event"]["id"]})
        with (patch.object(ci.sync, "merge", return_value=(after, COUNT)),
              patch.object(ci.sync, "protect_reference"),
              patch.object(ci.sync, "validate_catalogue")):
            self.assertEqual(
                ci.audit(BEFORE, AFTER, {}, PUBLISHED, dt.date(2026, 11, 6)), 1)
        self.assertEqual(PUBLISHED["events"], [{"id": OLD_ROW["event"]["id"]}])

    def test_held_events_corrections_and_other_bypass_are_rejected(self):
        correct = copy.deepcopy(PUBLISHED)
        correct["events"].append({"id": NEW_ROW["event"]["id"]})
        for wrong in (
            dict(COUNT, held=[{"candidateId": "x", "reason": "not verified"}]),
            dict(COUNT, correctedEvents=1),
            dict(COUNT, newVenues=1),
            dict(COUNT, newArtists=1),
            dict(COUNT, newEvents=0),
        ):
            with self.subTest(wrong=wrong), (
                    patch.object(ci.sync, "merge", return_value=(correct, wrong))):
                with self.assertRaises(ValueError):
                    ci.audit(BEFORE, AFTER, {}, PUBLISHED,
                             dt.date(2026, 11, 6))

    def test_invalid_sha_is_rejected_before_any_api_query(self):
        for value in ("1;cat /etc/passwd", "refs/heads/main", "-1", "0001",
                      "7\nX", "a" * 39, "a" * 41):
            with self.subTest(ref=value), (
                    patch.object(ci, "github_approval",
                                 side_effect=AssertionError("network forbidden"))):
                with self.assertRaises(ValueError):
                    ci.preview(value, "fake-token", dt.date(2026, 11, 6))

    def test_only_pinned_sha_and_main_json_are_requested(self):
        refs = []
        def approved(ref, token):
            refs.append(ref)
            return BEFORE if ref == "main" else AFTER
        with (patch.object(ci, "github_approval", side_effect=approved),
              patch.object(ci, "read_json", side_effect=({}, PUBLISHED)),
              patch.object(ci, "audit", return_value=1)):
            self.assertEqual(ci.preview("a" * 40, "fake-token",
                                        dt.date(2026, 11, 6)), 1)
        self.assertEqual(refs, ["main", "a" * 40])


if __name__ == "__main__":
    unittest.main()
