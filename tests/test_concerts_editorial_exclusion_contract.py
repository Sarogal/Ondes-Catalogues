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


    def test_republication_by_different_id_or_alternate_openagenda_slug_blocked(self):
        base, current, ledger, today, fetch = self.setup_case()
        _, plans = contract.prepare(base, current, ledger, today, fetch=fetch)
        original = ledger["approvals"][0]
        alias = copy.deepcopy(original)
        alias["event"]["id"] = "different-id"
        self.assertTrue(contract.matches_excluded(alias, plans))
        alias["event"]["officialUrl"] = "https://openagenda.com/other/events/alternate-slug"
        self.assertTrue(contract.matches_excluded(alias, plans))
        alias["officialEvidence"][-1]["officialOpenAgendaEventUid"] = "42"
        self.assertFalse(contract.matches_excluded(alias, plans))
        alias["event"]["date"] = "2028-01-01"
        self.assertFalse(contract.matches_excluded(alias, plans))

    def test_actual_publisher_and_preflight_exclude_only_the_bound_event(self):
        from unittest import mock
        from automation.concerts import editorial_correction_preflight as preflight
        from scripts import concerts_cloud_sync as sync
        from scripts import concert_published_lineup_contract as lineup
        from test_concerts_openagenda_new_site_publisher import geo_fixture, existing

        _, _, _, today, _ = self.setup_case()
        record, venue, event, approval = fixture.EditorialGenreReconciliationTests().setup_case()
        # Use the real 127-event historical fixture, not a mocked merge.
        original_geo = sync.NEW_REFERENCE_GEO_SOURCES.pop(existing.VENUE_ID, None)
        self.addCleanup(lambda: sync.NEW_REFERENCE_GEO_SOURCES.__setitem__(
            existing.VENUE_ID, original_geo))
        base = geo_fixture.test_catalogue()
        anchor = next(v for v in base["venues"] if v["id"] not in
                      set(sync.NEW_REFERENCE_GEO_SOURCES) |
                      {sync.SECRET_PLACE_VENUE_ID, sync.REX_VENUE_ID})
        anchor.update({k: v for k, v in venue.items() if k != "id"})
        event["venueId"] = anchor["id"]
        event["artistIds"] = [base["artists"][0]["id"]]
        event["title"] = base["artists"][0]["name"]
        record["title"] = {"fr": event["title"]}
        approval["officialEvidence"][-1]["officialArtistNames"] = [event["title"]]
        # Bind the synthetic published snapshot and original approval.
        approval["event"] = copy.deepcopy(event)
        current = copy.deepcopy(base)
        current["events"].append(event)
        before = {"schema": sync.SCHEMA, "approvals": [approval], "venueApprovals": []}
        def fetch(url):
            return json.dumps({"total": 1, "events": [record]})
        with mock.patch.object(lineup, "network_fetch", side_effect=fetch):
            proposed, report = preflight.select(before, base, current, today, fetch=fetch)
            self.assertTrue(report["validatedByPublisher"], report)
            self.assertEqual(proposed["approvals"], before["approvals"])
            result, counts = sync.merge(base, current, proposed, today)
        self.assertEqual(counts["editorialExclusions"], 1)
        self.assertEqual(result["events"], base["events"])
        self.assertEqual(result["artists"], base["artists"])
        self.assertEqual(result["venues"], base["venues"])
        with mock.patch.object(lineup, "network_fetch",
                               side_effect=AssertionError("no historical fetch")):
            replay, stats = sync.merge(base, result, proposed, today)
        self.assertEqual(replay, result)
        self.assertEqual(stats["editorialExclusions"], 0)
        with self.assertRaises(ValueError):
            sync.merge(base, result, before, today)


if __name__ == "__main__":
    unittest.main()
