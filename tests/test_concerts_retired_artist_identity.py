"""Offline regressions for the narrowly scoped orphan identity retirement."""
import copy
import unittest
from unittest import mock

from automation.concerts import published_lineup_patch_builder as builder
from scripts import concert_published_lineup_contract as lineup
from scripts import concert_retired_artist_identity as retirement
from scripts import concerts_cloud_sync as sync
import test_concerts_published_openagenda_bill_identity as fixture


class ArtistRetirementTests(unittest.TestCase):
    def setUp(self):
        fixture.PublishedOpenAgendaBillRepair.setUp(self)
        self.today = fixture.fixture.TODAY

    def corrected(self):
        base, before, ledger, fetch = fixture.PublishedOpenAgendaBillRepair.initial(
            self, ["Example Band", "GUESTS"], "Example Band + GUESTS")
        report = builder.build_promotional(before, ledger, self.today, fetch=fetch)
        self.assertEqual(len(report["proposals"]), 1, report)
        row = report["proposals"][0]
        ledger = copy.deepcopy(ledger)
        ledger["lineupCorrections"] = [row]
        with mock.patch.object(lineup, "network_fetch",
                               side_effect=lambda url: fetch(url, {})):
            after, stats = sync.merge(base, before, ledger, self.today)
        self.assertEqual(stats["correctedEvents"], 1)
        return base, after, ledger, row["oldArtistIds"][-1]

    def test_exact_retirement_preserves_private_history_and_replays(self):
        base, current, ledger, bad = self.corrected()
        original_ledger = copy.deepcopy(ledger)
        old_artist = next(a for a in current["artists"] if a["id"] == bad)
        result, n = retirement.retire(base, current, ledger, self.today)
        self.assertEqual(n, 1)
        self.assertEqual(result[retirement.KEY], [bad])
        self.assertEqual(result["artists"], [a for a in current["artists"] if a["id"] != bad])
        self.assertEqual(result["events"], current["events"])
        self.assertEqual(result["venues"], current["venues"])
        self.assertEqual(ledger, original_ledger)
        restored, ids = retirement.restore(base, result, ledger, self.today)
        self.assertEqual(ids, {bad})
        self.assertIn(old_artist, restored["artists"])
        again, n = retirement.retire(base, restored, ledger, self.today, ids)
        self.assertEqual(again, result)
        self.assertEqual(n, 0)

    def test_keep_reference_referenced_pending_and_authority_artists(self):
        base, current, ledger, bad = self.corrected()
        # An unreferenced real artist with no identity correction is not a target.
        current["artists"].append({"id": "real-inactive-band",
                                   "name": "Real Inactive Band", "aliases": []})
        self.assertNotIn("real-inactive-band",
                         retirement.candidates(base, current, ledger, self.today))
        pending = copy.deepcopy(ledger)
        new = copy.deepcopy(pending["approvals"][-1])
        new["event"]["id"] = "different-signed-event"
        pending["approvals"].append(new)
        self.assertNotIn(bad, retirement.candidates(base, current, pending, self.today))
        authority = copy.deepcopy(ledger)
        authority["venueApprovals"][0]["eventBinding"]["authorityArtistId"] = bad
        self.assertNotIn(bad, retirement.candidates(base, current, authority, self.today))
        protected = copy.deepcopy(base)
        protected["artists"].append(next(a for a in current["artists"] if a["id"] == bad))
        self.assertNotIn(bad, retirement.candidates(protected, current, ledger, self.today))
        live = copy.deepcopy(current)
        live["events"][0]["artistIds"].append(bad)
        self.assertNotIn(bad, retirement.candidates(base, live, ledger, self.today))

    def test_no_forged_receipt_or_unapproved_cleanup(self):
        base, current, ledger, bad = self.corrected()
        result, _ = retirement.retire(base, current, ledger, self.today)
        for receipts in ([bad, bad], ["unknown-artist"]):
            forged = dict(result, retiredArtistIds=receipts)
            with self.assertRaises(ValueError):
                retirement.restore(base, forged, ledger, self.today)
        unsigned = copy.deepcopy(ledger)
        unsigned["lineupCorrections"] = []
        with self.assertRaises(ValueError):
            retirement.restore(base, result, unsigned, self.today)
        forged = copy.deepcopy(result)
        forged["events"][-1]["history"][-1]["change"] = "forged correction"
        with self.assertRaises(ValueError):
            retirement.restore(base, forged, ledger, self.today)


if __name__ == "__main__":
    unittest.main()
