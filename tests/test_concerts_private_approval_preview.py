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
            ("reviewer", lambda row: row.update(reviewedBy="untrusted-candidate")),
            ("decision", lambda row: row.update(reviewDecision="pending")),
            ("invalidArtists", lambda row: row.update(newArtists="untrusted")),
            ("missingProof", lambda row: row["officialEvidence"].clear()),
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

    def test_fail_stage_is_fixed_and_private_exception_is_suppressed(self):
        secret = "PRIVATE_PROOF_NOT_FOR_PUBLIC_LOGS"
        for stage, callback in (
            ("READ_MAIN", lambda: ci.guarded("READ_MAIN", lambda: (_ for _ in ()).throw(ValueError(secret)))),
            ("READ_HEAD", lambda: ci.guarded("READ_HEAD", lambda: (_ for _ in ()).throw(ValueError(secret)))),
            ("MERGE", lambda: ci.guarded("MERGE", lambda: (_ for _ in ()).throw(ValueError(secret)))),
        ):
            with self.subTest(stage=stage):
                with self.assertRaises(ci.PrivatePreviewStageError) as result:
                    callback()
                self.assertEqual(result.exception.stage, stage)
                self.assertNotIn(secret, str(result.exception))

    def test_invalid_sha_is_rejected_before_any_api_query(self):
        for value in ("1;cat /etc/passwd", "refs/heads/main", "-1", "0001",
                      "7\nX", "a" * 39, "a" * 41):
            with self.subTest(ref=value), (
                    patch.object(ci, "github_approval",
                                 side_effect=AssertionError("network forbidden"))):
                with self.assertRaises(ValueError):
                    ci.preview(value, "fake-token", dt.date(2026, 11, 6))

    def test_real_cli_entrypoint_has_clock_and_no_private_value(self):
        # Unlike direct preview() calls, main() actually resolves the Paris
        # clock. This catches a missing datetime import before deployment.
        from contextlib import redirect_stdout
        from io import StringIO
        import os
        output = StringIO()
        with (patch.dict(os.environ, {"GROSSES_ONDES_INTAKE_READ_TOKEN": "fake-token"}),
              patch.object(ci.sys, "argv", ["cli", "--head-sha", "a" * 40]),
              patch.object(ci, "preview", return_value=4) as inspect,
              redirect_stdout(output)):
            self.assertEqual(ci.main(), 0)
        self.assertEqual(inspect.call_args.args[0], "a" * 40)
        self.assertEqual(inspect.call_args.args[1], "fake-token")
        self.assertIsInstance(inspect.call_args.args[2], dt.date)
        self.assertNotIn("fake-token", output.getvalue())
        self.assertIn("4 modification(s) vérifiée(s)", output.getvalue())

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


    def test_new_artists_accepted_only_when_publisher_adds_exact_signed_ids(self):
        proposal = copy.deepcopy(AFTER)
        proposal["approvals"][-1]["newArtists"] = [
            {"id": "official-new-band", "name": "Official New Band"}]
        proposal["approvals"][-1]["officialEvidence"] = [
            {"url": "https://venue.example/verified",
             "proofType": "official-organizer-or-venue"}]
        self.assertEqual(ci.approved_delta(BEFORE, proposal, PUBLISHED)[0],
                         [NEW_ROW["event"]["id"]])
        result = copy.deepcopy(PUBLISHED)
        result["events"].append({"id": NEW_ROW["event"]["id"]})
        result["artists"].append({"id": "official-new-band",
                                  "name": "Official New Band"})
        with (patch.object(ci.sync, "merge",
                           return_value=(result, dict(COUNT, newArtists=1))),
              patch.object(ci.sync, "protect_reference"),
              patch.object(ci.sync, "validate_catalogue")):
            self.assertEqual(ci.audit(BEFORE, proposal, {}, PUBLISHED,
                                      dt.date(2026, 11, 13)), 1)
        for altered in (
            dict(COUNT, newArtists=0),
            dict(COUNT, newArtists=2),
        ):
            with (patch.object(ci.sync, "merge",
                               return_value=(result, altered)),
                  self.assertRaises(ValueError)):
                ci.audit(BEFORE, proposal, {}, PUBLISHED,
                         dt.date(2026, 11, 13))
        swapped = copy.deepcopy(result)
        swapped["artists"][0]["id"] = "unreviewed"
        with (patch.object(ci.sync, "merge",
                           return_value=(swapped, dict(COUNT, newArtists=1))),
              self.assertRaises(ValueError)):
            ci.audit(BEFORE, proposal, {}, PUBLISHED,
                     dt.date(2026, 11, 13))

    def test_status_correction_is_append_only_exactly_one_event(self):
        row = {
            "eventId": OLD_ROW["event"]["id"],
            "reviewDecision": "approved",
            "reviewedBy": "independent-official-verifier",
            "reviewedAt": "2026-11-12",
            "eventPatch": {"status": "cancelled"},
            "officialEvidence": [{"url": "https://artist.example/tour",
                                  "proofType": "official-artist-tour-calendar"}],
        }
        before = dict(BEFORE, referenceEventStatusCorrections=[])
        after = dict(before, referenceEventStatusCorrections=[row])
        self.assertEqual(ci.approved_delta(before, after, PUBLISHED),
                         ([], [row]))
        updated = copy.deepcopy(PUBLISHED)
        updated["events"][0]["status"] = "cancelled"
        count = dict(COUNT, newEvents=0, correctedEvents=1)
        with (patch.object(ci.sync, "merge", return_value=(updated, count)),
              patch.object(ci.sync, "protect_reference"),
              patch.object(ci.sync, "validate_catalogue")):
            self.assertEqual(ci.audit(before, after, {}, PUBLISHED,
                                      dt.date(2026, 11, 13)), 1)
        for bad in (
            dict(after, approvals=AFTER["approvals"]),
            dict(after, referenceEventStatusCorrections=[row, row]),
            dict(after, referenceEventStatusCorrections=[
                dict(row, reviewedBy="untrusted")]),
            dict(after, referenceEventStatusCorrections=[
                dict(row, eventId="unknown-id")]),
            dict(after, venueApprovals=[]),
        ):
            with self.subTest(bad=str(bad)[:100]), self.assertRaises(ValueError):
                ci.approved_delta(before, bad, PUBLISHED)
        tampered = copy.deepcopy(updated)
        tampered["events"][0]["title"] = "Altered lineup"
        with (patch.object(ci.sync, "merge", return_value=(tampered, count)),
              self.assertRaises(ValueError)):
            ci.audit(before, after, {}, PUBLISHED, dt.date(2026, 11, 13))
        wrong_count = dict(count, correctedEvents=0)
        with (patch.object(ci.sync, "merge",
                           return_value=(updated, wrong_count)),
              self.assertRaises(ValueError)):
            ci.audit(before, after, {}, PUBLISHED, dt.date(2026, 11, 13))

    def test_status_append_cannot_mutate_prior_signature_or_add_venues(self):
        prior = {"eventId": "historical", "reviewDecision": "approved"}
        before = dict(BEFORE, referenceEventStatusCorrections=[prior])
        new_row = {
            "eventId": OLD_ROW["event"]["id"],
            "reviewDecision": "approved",
            "reviewedBy": "independent-official-verifier",
            "eventPatch": {"status": "cancelled"},
            "officialEvidence": [{"url": "https://artist.example/tour"}],
        }
        altered = dict(before, referenceEventStatusCorrections=[
            dict(prior, reviewDecision="modified"), new_row])
        with self.assertRaises(ValueError):
            ci.approved_delta(before, altered, PUBLISHED)
        altered = dict(before, referenceEventStatusCorrections=[new_row])
        with self.assertRaises(ValueError):
            ci.approved_delta(before, altered, PUBLISHED)


if __name__ == "__main__":
    unittest.main()
