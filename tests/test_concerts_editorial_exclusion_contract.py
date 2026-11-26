"""Independent editorial exclusion ledger and replay tests (no network)."""
import copy
import datetime as dt
import json
import unittest

from scripts import concert_editorial_exclusion_contract as contract
import test_concerts_editorial_genre_reconciliation as fixture


class EditorialExclusionContractTests(unittest.TestCase):
    def setup_case(self):
        record, venue, event, approval = (
            fixture.EditorialGenreReconciliationTests().setup_case())
        today = dt.date.fromisoformat(event["date"])
        def fetch(url):
            return json.dumps({"total": 1, "events": [record]})
        proof = contract.evidence.verify(approval, event, venue, today, fetch=fetch)
        row = contract.signed_proposal(event, proof)
        other = dict(event, id="other-event", title="Other event")
        baseline = {"events": [other], "venues": [venue], "artists": []}
        current = dict(baseline, events=[other, event])
        ledger = {"approvals": [approval], contract.KEY: [row]}
        return baseline, current, ledger, today, fetch

    def test_exact_removal_and_offline_idempotent_replay(self):
        base, current, ledger, today, fetch = self.setup_case()
        original = copy.deepcopy(current)
        internal, plans = contract.prepare(base, current, ledger, today, fetch=fetch)
        result, count = contract.apply(internal, plans)
        self.assertEqual(count, 1)
        self.assertEqual(result["events"], base["events"])
        self.assertEqual(result["venues"], current["venues"])
        self.assertEqual(result["artists"], current["artists"])
        self.assertEqual(current, original)
        self.assertEqual(result[contract.RECEIPTS], [{
            "eventId": current["events"][-1]["id"],
            "date": today.isoformat(), "reason": "venue-name-genre-contamination"}])
        internal, plans = contract.prepare(base, result, ledger,
            today + dt.timedelta(days=60),
            fetch=lambda url: self.fail("historical replay must be offline"))
        self.assertEqual(internal["events"], original["events"])
        again, count = contract.apply(internal, plans)
        self.assertEqual(again, result)
        self.assertEqual(count, 0)

    def test_network_failure_preserves_event_and_other_additions(self):
        base, current, ledger, today, _ = self.setup_case()
        def unavailable(url):
            raise OSError("unavailable")
        internal, plans = contract.prepare(base, current, ledger, today,
                                           fetch=unavailable)
        added = dict(current["events"][0], id="new-event")
        internal["events"].append(added)
        result, count = contract.apply(internal, plans)
        self.assertEqual(count, 0)
        self.assertEqual(result["events"], current["events"] + [added])
        self.assertNotIn(contract.RECEIPTS, result)

    def test_unsigned_or_forged_receipt_and_absent_original_refused(self):
        base, current, ledger, today, fetch = self.setup_case()
        internal, plans = contract.prepare(base, current, ledger, today, fetch=fetch)
        result, _ = contract.apply(internal, plans)
        for forged, signatures in (
            (result, {"approvals": ledger["approvals"]}),
            (dict(result, editorialExclusions=[]), ledger),
            (dict(result, editorialExclusions=[dict(result[contract.RECEIPTS][0],
                                                    reason="cancelled")]), ledger),
            (dict(current, editorialExclusions=result[contract.RECEIPTS]), ledger),
        ):
            with self.assertRaises(ValueError):
                contract.prepare(base, forged, signatures, today, fetch=fetch)

    def test_private_history_tamper_and_reference_target_refused(self):
        base, current, ledger, today, fetch = self.setup_case()
        for field, value in (("oldGenres", ["metal"]), ("eventUid", 1),
                             ("reason", "cancelled")):
            bad = copy.deepcopy(ledger)
            bad[contract.KEY][0]["evidence"][field] = value
            with self.assertRaises(ValueError):
                contract.prepare(base, current, bad, today, fetch=fetch)
        with self.assertRaises(ValueError):
            contract.prepare(current, current, ledger, today, fetch=fetch)


if __name__ == "__main__":
    unittest.main()
