"""Offline fail-closed tests: private approval preflight never publishes by itself."""
import copy
import datetime as dt
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import approval_preflight as gate

TODAY = dt.date(2026, 11, 9)


def event(i="go-c-20270401-example"):
    return {"id": i, "title": "Example", "date": "2027-04-01",
            "artistIds": ["example"], "venueId": "venue",
            "genres": ["Metal"], "status": "confirmed", "time": None,
            "officialUrl": "https://example.org/agenda/example",
            "sourceType": "salle", "organizer": "Venue"}


def row(i="go-c-20270401-example"):
    return {"reviewDecision": "approved",
            "reviewedBy": "automated-official-recheck",
            "reviewedAt": TODAY.isoformat(),
            "event": event(i), "newArtists": [],
            "officialEvidence": [{"url": "https://example.org/agenda/example",
                                  "proofType": "official-organizer-or-venue",
                                  "checkedAt": TODAY.isoformat(),
                                  "checkedFields": ["artists", "date", "venue", "genre"]}]}


def prior():
    return {"schema": "grossesondes.concert.approvals.v1",
            "version": 1, "approvals": [],
            "venueApprovals": [], "referenceCorrections": []}


def publisher_accept(reference, current, approvals, today):
    out = copy.deepcopy(current)
    for item in approvals["approvals"]:
        out["events"].append({**item["event"], "confidence": "official"})
    return out, {"newEvents": len(approvals["approvals"])}


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.before = prior()
        self.after = copy.deepcopy(self.before)
        self.after["approvals"].append(row())
        self.catalogue = {"events": []}

    def test_exact_publisher_acceptance_required(self):
        result = gate.validate_proposal(
            self.before, self.after, {}, self.catalogue, TODAY, publisher_accept)
        self.assertEqual(result["publishableEvents"], 1)
        self.assertTrue(result["validatedByPublisher"])

    def test_no_new_approvals_does_not_call_publisher(self):
        def fail(*args):
            self.fail("Publisher must not run without new approvals")
        stats = gate.validate_proposal(
            self.before, self.before, {}, self.catalogue, TODAY, fail)
        self.assertEqual(stats["publishableEvents"], 0)

    def test_publisher_holds_a_candidate(self):
        def hold(reference, current, approvals, today):
            return copy.deepcopy(current), {"newEvents": 0}
        with self.assertRaisesRegex(ValueError, "held or modified"):
            gate.validate_proposal(self.before, self.after, {}, self.catalogue,
                                   TODAY, hold)

    def test_publisher_cannot_silently_change_event_fields(self):
        def change(reference, current, approvals, today):
            return {"events": [{**event(), "date": "2027-04-02"}]}, {}
        with self.assertRaisesRegex(ValueError, "held or modified"):
            gate.validate_proposal(self.before, self.after, {}, self.catalogue,
                                   TODAY, change)

    def test_publisher_cannot_return_unexpected_number_of_events(self):
        def extra(reference, current, approvals, today):
            return {"events": [event(), {"id": "other"}]}, {}
        with self.assertRaisesRegex(ValueError, "Unexpected number"):
            gate.validate_proposal(self.before, self.after, {}, self.catalogue,
                                   TODAY, extra)

    def test_already_published_event_is_refused(self):
        with self.assertRaisesRegex(ValueError, "already in the public"):
            gate.validate_proposal(self.before, self.after, {},
                                   {"events": [event()]}, TODAY, publisher_accept)

    def test_approved_history_must_be_append_only(self):
        old = prior()
        old["approvals"] = [row("go-c-20270501-previous")]
        proposed = copy.deepcopy(old)
        proposed["approvals"][0]["event"]["title"] = "Tampered"
        with self.assertRaisesRegex(ValueError, "modified or removed"):
            gate.check_append_only(old, proposed, TODAY)

    def test_reviewer_and_date_cannot_be_spoofed(self):
        for key, value in (("reviewedBy", "human"),
                           ("reviewedAt", "2026-11-01"),
                           ("reviewDecision", "pending")):
            proposed = copy.deepcopy(self.after)
            proposed["approvals"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.check_append_only(self.before, proposed, TODAY)

    def test_protected_private_fields_cannot_change(self):
        proposed = copy.deepcopy(self.after)
        proposed["venueApprovals"].append({"venue": "unreviewed"})
        with self.assertRaisesRegex(ValueError, "metadata changed"):
            gate.check_append_only(self.before, proposed, TODAY)

    def test_duplicate_approval_ids_are_rejected(self):
        proposed = copy.deepcopy(self.after)
        proposed["approvals"].append(copy.deepcopy(row()))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            gate.check_append_only(self.before, proposed, TODAY)

    def test_more_than_sixteen_approvals_are_rejected(self):
        proposed = copy.deepcopy(self.before)
        proposed["approvals"] = [row(f"go-c-20270401-example-{i}") for i in range(17)]
        with self.assertRaisesRegex(ValueError, "Too many"):
            gate.check_append_only(self.before, proposed, TODAY)

    def test_no_change_to_source_documents(self):
        previous = copy.deepcopy(self.before)
        proposed = copy.deepcopy(self.after)
        gate.validate_proposal(previous, proposed, {}, self.catalogue, TODAY,
                               publisher_accept)
        self.assertEqual(previous, self.before)
        self.assertEqual(proposed, self.after)


if __name__ == "__main__":
    unittest.main()
