import copy
import datetime as dt
import unittest

from automation.concerts import existing_venue_geo_preflight as preflight
from scripts import concert_existing_venue_geo_contract as contract
from test_concerts_existing_venue_geo_contract import fixture, TODAY


def inputs():
    data, proof, row = fixture()
    ledger = {"schema": preflight.sync.SCHEMA, "approvals": []}
    report = {"schema": preflight.evidence.SCHEMA + ".scan",
              "asOf": TODAY.isoformat(), "proposals": [proof],
              "publicationAllowed": False, "publisherAuthorityGranted": False}
    return data, ledger, report, row


def publisher(reference, current, ledger, today):
    result = copy.deepcopy(current)
    counts = {"correctedVenues": 0, "newEvents": 1, "held": []}
    # Simulate unrelated already-approved pending publication.
    result["events"].append({"id": "other-pending", "venueId": "other"})
    for row in ledger.get(contract.KEY, []):
        result["venues"][0].update(row["venuePatch"])
        counts["correctedVenues"] += 1
    return result, counts


class ExistingVenueGeoPreflightTests(unittest.TestCase):
    def test_accepts_exact_geo_delta_alongside_pending_concert(self):
        data, ledger, report, row = inputs()
        previous = copy.deepcopy(ledger)
        proposed, out = preflight.select(ledger, report, data, data, TODAY,
                                         publisher=publisher)
        self.assertEqual(proposed[contract.KEY], [row])
        self.assertEqual(ledger, previous)
        self.assertTrue(out["validatedByPublisher"])
        self.assertFalse(out["applied"])

    def test_rejects_unrelated_event_or_artist_delta(self):
        for key in ("events", "artists"):
            data, ledger, report, row = inputs()
            def mutated(*args):
                result, counts = publisher(*args)
                if args[2].get(contract.KEY):
                    result[key].append({"id": "unexpected"})
                return result, counts
            proposed, out = preflight.select(ledger, report, data, data, TODAY,
                                             publisher=mutated)
            self.assertEqual(proposed, ledger)
            self.assertFalse(out["validatedByPublisher"])

    def test_deferred_or_missing_replay_cannot_be_signed(self):
        data, ledger, report, row = inputs()
        def deferred(reference, current, proposed, today):
            return publisher(reference, current, ledger, today)
        proposed, out = preflight.select(ledger, report, data, data, TODAY,
                                         publisher=deferred)
        self.assertEqual(proposed, ledger)
        self.assertEqual(out["status"], "held")

    def test_stale_or_self_authorizing_report_is_rejected_before_publisher(self):
        for change in ({"asOf": "2026-11-24"}, {"publicationAllowed": True},
                       {"publisherAuthorityGranted": True}):
            data, ledger, report, row = inputs()
            proposed, out = preflight.select(ledger, dict(report, **change),
                                             data, data, TODAY,
                                             publisher=lambda *args: self.fail("must not call"))
            self.assertEqual(proposed, ledger)
            self.assertFalse(out["validatedByPublisher"])

    def test_existing_signed_venue_is_not_duplicated(self):
        data, ledger, report, row = inputs()
        ledger[contract.KEY] = [row]
        proposed, out = preflight.select(ledger, report, data, data, TODAY,
                                         publisher=lambda *args: self.fail("must not call"))
        self.assertEqual(proposed, ledger)
        self.assertEqual(out["examined"], 0)


    def test_renewal_exact_delta_removes_only_one_deferred_correction(self):
        data, ledger, report, old = inputs()
        day = TODAY + dt.timedelta(days=8)
        ledger[contract.KEY] = [old]
        report["asOf"] = day.isoformat()
        def replay(reference, current, signed, today):
            result = copy.deepcopy(current)
            result["events"].append({"id": "other-pending"})
            counts = {"correctedVenues": 0, "newEvents": 1, "held": [],
                      "deferredGeoCorrections": 1}
            if len(signed[contract.KEY]) == 2:
                result["venues"][0].update(signed[contract.KEY][-1]["venuePatch"])
                counts["correctedVenues"] += 1
                del counts["deferredGeoCorrections"]
            return result, counts
        proposed, out = preflight.select(ledger, report, data, data, day,
                                         publisher=replay)
        self.assertTrue(out["validatedByPublisher"])
        self.assertTrue(out["renewal"])
        self.assertEqual(proposed[contract.KEY][0], old)
        self.assertEqual(proposed[contract.KEY][1]["reviewedAt"], day.isoformat())
        self.assertEqual(len(ledger[contract.KEY]), 1)

    def test_changed_target_renewal_remains_unapproved(self):
        data, ledger, report, old = inputs()
        day = TODAY + dt.timedelta(days=8)
        ledger[contract.KEY] = [old]
        report["asOf"] = day.isoformat()
        report["proposals"][0]["venuePatch"]["latitude"] = 49.0
        proposed, out = preflight.select(ledger, report, data, data, day,
                                         publisher=lambda *args: self.fail("must not call"))
        self.assertEqual(proposed, ledger)
        self.assertFalse(out["validatedByPublisher"])
