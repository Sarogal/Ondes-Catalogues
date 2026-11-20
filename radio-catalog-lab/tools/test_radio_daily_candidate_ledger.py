"""Offline safety tests: fresh/repeated/disappearing candidates, no publication."""
import copy
import unittest
from radio_daily_candidate_ledger import update_ledger

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def scan(day, candidates):
    return {
        "schemaVersion": 1, "scanDate": day, "publicationAllowed": False,
        "candidates": candidates,
    }


def row(uid=A, status="candidate_requires_qualification", duplicate=False):
    return {
        "stationuuid": uid, "name": "New Metal",
        "status": status, "duplicateIdentityRisk": duplicate,
    }


class CandidateLedgerTests(unittest.TestCase):
    def test_first_observation_is_not_auto_approved(self):
        ledger = update_ledger(scan("2026-11-20", [row()]))
        self.assertEqual(ledger["newCandidateCount"], 1)
        self.assertEqual(ledger["records"][0]["seenDays"], 1)
        self.assertFalse(ledger["records"][0]["repeatedObservation"])
        self.assertFalse(ledger["publicationAllowed"])
        self.assertEqual(ledger["automaticallyApprovedCount"], 0)

    def test_second_day_gives_repeated_evidence_not_publication(self):
        first = update_ledger(scan("2026-11-20", [row()]))
        second = update_ledger(scan("2026-11-21", [row()]), first)
        self.assertEqual(second["records"][0]["seenDays"], 2)
        self.assertTrue(second["records"][0]["repeatedObservation"])
        self.assertEqual(second["automaticallyApprovedCount"], 0)
        self.assertFalse(second["publicationAllowed"])

    def test_twice_same_day_does_not_gain_second_evidence_day(self):
        first = update_ledger(scan("2026-11-20", [row()]))
        second = update_ledger(scan("2026-11-20", [row()]), first)
        self.assertEqual(second["records"][0]["seenDays"], 1)
        self.assertFalse(second["records"][0]["repeatedObservation"])

    def test_absence_retains_historical_candidate_but_never_claims_present(self):
        first = update_ledger(scan("2026-11-20", [row()]))
        second = update_ledger(scan("2026-11-21", []), first)
        self.assertEqual(second["records"][0]["firstSeen"], "2026-11-20")
        self.assertEqual(second["records"][0]["lastSeen"], "2026-11-20")
        self.assertEqual(second["notSeenTodayCount"], 1)
        self.assertFalse(second["records"][0]["repeatedObservation"])

    def test_broken_stream_or_duplicate_never_is_promoted(self):
        first = update_ledger(scan("2026-11-20", [row()]))
        for bad in (
            row(status="needs_stream_check"),
            row(status="needs_duplicate_review", duplicate=True),
        ):
            with self.subTest(bad=bad):
                second = update_ledger(scan("2026-11-21", [bad]), first)
                self.assertFalse(second["records"][0]["repeatedObservation"])
                self.assertFalse(second["publicationAllowed"])

    def test_unrelated_radio_added_without_hardcoded_uuid_whitelist(self):
        first = update_ledger(scan("2026-11-20", [row()]))
        second = update_ledger(scan("2026-11-21", [row(B)]), first)
        self.assertEqual(len(second["records"]), 2)
        self.assertEqual(second["newCandidateCount"], 1)
        self.assertEqual(second["notSeenTodayCount"], 1)

    def test_future_previous_ledger_is_rejected(self):
        previous = update_ledger(scan("2026-11-21", [row()]))
        with self.assertRaises(ValueError):
            update_ledger(scan("2026-11-20", []), previous)

    def test_invalid_status_and_duplicate_uuids_rejected(self):
        with self.assertRaises(ValueError):
            update_ledger(scan("2026-11-20", [row(status="automatically_approved")]))
        with self.assertRaises(ValueError):
            update_ledger(scan("2026-11-20", [row(), row()]))

    def test_malformed_previous_cannot_authorize_publication(self):
        first = update_ledger(scan("2026-11-20", [row()]))
        bad = copy.deepcopy(first)
        bad["publicationAllowed"] = True
        with self.assertRaises(ValueError):
            update_ledger(scan("2026-11-21", [row()]), bad)

    def test_corrupt_previous_duplicate_uuids_rejected(self):
        first = update_ledger(scan("2026-11-20", [row()]))
        bad = copy.deepcopy(first)
        bad["records"].append(copy.deepcopy(bad["records"][0]))
        with self.assertRaises(ValueError):
            update_ledger(scan("2026-11-21", [row()]), bad)


if __name__ == "__main__":
    unittest.main()
