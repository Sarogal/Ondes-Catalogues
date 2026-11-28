"""Real Publisher regressions for exact, signed OpenAgenda bill repairs."""
import copy
import json
import unittest
from unittest import mock

from automation.concerts import published_lineup_patch_builder as builder
from automation.concerts import promotional_correction_preflight as preflight
from scripts import concert_openagenda_bill_identity as identity
from scripts import concert_published_lineup_contract as contract
from scripts import concerts_cloud_sync as sync
import test_concerts_openagenda_new_site_publisher as fixture


class PublishedOpenAgendaBillRepair(unittest.TestCase):
    def setUp(self):
        old = sync.NEW_REFERENCE_GEO_SOURCES.pop(fixture.existing.VENUE_ID, None)
        self.assertIsNotNone(old)
        self.addCleanup(lambda: sync.NEW_REFERENCE_GEO_SOURCES.__setitem__(
            fixture.existing.VENUE_ID, old))

    def initial(self, old_names, title, description="Concert punk."):
        base = fixture.geo_fixture.test_catalogue()
        empty = fixture.geo_fixture.before()
        fetch, _ = fixture.official_get(changes={
            "title": {"fr": title},
            "keywords": {"fr": ["punk"]},
            "longDescription": {"fr": description},
        })
        # Recreate an old published error without modifying the real catalogue.
        # The runner imports the source verifier under both package and
        # top-level module names. Patch only the historical parser in both
        # namespaces while constructing the signed legacy fixture.
        from automation.concerts import openagenda_official_concert as package_oa
        import openagenda_official_concert as top_oa
        from contextlib import ExitStack
        with ExitStack() as stack:
            for module in {fixture.oa, package_oa, top_oa}:
                stack.enter_context(mock.patch.object(
                    module, "verified_export", return_value=(old_names, ["punk"])))
            stack.enter_context(mock.patch.object(
                fixture.signer.probe, "safe_fetch", side_effect=fetch))
            approved, report = fixture.producer.build(
                fixture.observation(name=title, leadArtist=old_names[0]),
                base, empty, fixture.TODAY, fetch=fetch)
            self.assertEqual(len(approved["approvals"]), 1, report)
            published, counts = sync.merge(base, base, approved, fixture.TODAY)
        self.assertEqual(counts["newEvents"], 1, counts)
        return base, published, approved, fetch

    def test_exact_repairs_preflight_and_historical_new_site_replay(self):
        cases = (
            (["Example Band", "guest - Place Libre, Tours"],
             "Example Band + guest - Place Libre, Tours",
             "Concert punk.", ["Example Band"]),
            (["Example Band", "GUESTS"], "Example Band + GUESTS",
             "Concert punk.", ["Example Band"]),
            (["Example Band", "guests : Other Band"],
             "Example Band + guests : Other Band", "Concert punk.",
             ["Example Band", "Other Band"]),
            (["Example Band | Other Band"], "Example Band | Other Band",
             "<h2>Example Band</h2><p>Concert punk.</p><h2>Other Band</h2>",
             ["Example Band", "Other Band"]),
        )
        for old, title, body, names in cases:
            with self.subTest(title=title):
                base, current, ledger, fetch = self.initial(old, title, body)
                report = builder.build_promotional(current, ledger, fixture.TODAY,
                                                   fetch=fetch)
                self.assertEqual(len(report["proposals"]), 1, report)
                row = report["proposals"][0]
                self.assertEqual(row["officialEvidence"][0]["proofType"], identity.PROOF)
                self.assertEqual(row["officialEvidence"][0]["confirmedArtists"], names)
                self.assertEqual(row["oldArtistIds"], current["events"][-1]["artistIds"])
                with mock.patch.object(contract, "network_fetch",
                                       side_effect=lambda url: fetch(url, {})):
                    proposed, status = preflight.select(ledger, report, base, current,
                                                        fixture.TODAY)
                    self.assertTrue(status["validatedByPublisher"], status)
                    after, stats = sync.merge(base, current, proposed, fixture.TODAY)
                self.assertEqual(proposed["approvals"], ledger["approvals"])
                self.assertEqual(proposed["venueApprovals"], ledger["venueApprovals"])
                self.assertEqual(stats["correctedEvents"], 1)
                self.assertEqual(stats["newEvents"], 0)
                self.assertEqual(after["events"][:-1], current["events"][:-1])
                self.assertEqual(after["events"][-1]["title"], " + ".join(names))
                self.assertEqual(after["events"][-1]["artistIds"], row["artistIds"])
                self.assertEqual(after["venues"], current["venues"])
                self.assertEqual(after["artists"][:len(current["artists"])], current["artists"])
                # The new room was originally tied to the erroneous first event.
                # Its historical binding must still pass after the bill changes.
                with mock.patch.object(contract, "network_fetch",
                                       side_effect=AssertionError("historical replay must be offline")):
                    replay, counts = sync.merge(base, after, proposed, fixture.TODAY)
                self.assertEqual(replay, after)
                self.assertEqual(counts["correctedEvents"], 0)
                bad = copy.deepcopy(row)
                bad["officialEvidence"][0]["confirmedArtists"][0] = "Unrelated"
                with self.assertRaises(ValueError):
                    contract.plan(bad, ledger["approvals"][0], current, fixture.TODAY)

    def test_city_suffix_at_new_site_reconciles_existing_artist_and_replays(self):
        base, current, ledger, fetch = self.initial(
            ["KAMELOT - TOURS"], "KAMELOT - TOURS",
            "Kamelot est un groupe de metal.")
        report = builder.build_promotional(current, ledger, fixture.TODAY, fetch=fetch)
        self.assertEqual(len(report["proposals"]), 1, report)
        row = report["proposals"][0]
        self.assertEqual(row["artistIds"], ["kamelot"])
        self.assertEqual(row["newArtists"], [])
        self.assertEqual(row["officialEvidence"][0]["proofType"], contract.PROMOTIONAL_PROOF)
        with mock.patch.object(contract, "network_fetch",
                               side_effect=lambda url: fetch(url, {})):
            proposed, status = preflight.select(ledger, report, base, current, fixture.TODAY)
            self.assertTrue(status["validatedByPublisher"], status)
            after, counts = sync.merge(base, current, proposed, fixture.TODAY)
        self.assertEqual(counts["correctedEvents"], 1)
        self.assertEqual(counts["newEvents"], 0)
        self.assertEqual(counts["newArtists"], 0)
        self.assertEqual(after["events"][-1]["artistIds"], ["kamelot"])
        self.assertEqual(after["venues"], current["venues"])
        self.assertEqual(proposed["approvals"], ledger["approvals"])
        self.assertEqual(proposed["venueApprovals"], ledger["venueApprovals"])
        with mock.patch.object(contract, "network_fetch",
                               side_effect=AssertionError("offline historical replay")):
            replay, counts = sync.merge(base, after, proposed, fixture.TODAY)
        self.assertEqual(replay, after)
        self.assertEqual(counts["correctedEvents"], 0)
        from scripts import concert_retired_artist_identity as retirement
        bad_id = row["oldArtistIds"][0]
        self.assertIn(bad_id, retirement.candidates(base, after, proposed, fixture.TODAY))
        forged = copy.deepcopy(ledger["approvals"][0])
        forged["officialEvidence"][1]["namedOsmUrl"] = "https://www.openstreetmap.org/node/123"
        with self.assertRaises(ValueError):
            contract.plan(row, forged, current, fixture.TODAY)
        unavailable, _ = fixture.official_get(changes={
            "title": {"fr": "KAMELOT - TOURS"},
            "longDescription": {"fr": "KAMELOT - TOURS"},
        })
        self.assertFalse(builder.build_promotional(
            current, ledger, fixture.TODAY, fetch=unavailable)["proposals"])

    def test_preflight_composes_independent_maintenance_deltas(self):
        base, current, ledger, fetch = self.initial(
            ["Example Band", "guests : Other Band"],
            "Example Band + guests : Other Band")
        report = builder.build_promotional(current, ledger, fixture.TODAY,
                                           fetch=fetch)
        row = report["proposals"][0]
        proposal = copy.deepcopy(ledger)
        proposal["lineupCorrections"] = [row]
        with mock.patch.object(contract, "network_fetch",
                               side_effect=lambda url: fetch(url, {})):
            before, counts_before = sync.merge(base, current, ledger, fixture.TODAY)
            after, counts_after = sync.merge(base, current, proposal, fixture.TODAY)

        # Exercise the exact-delta comparator with the independently
        # validated Publisher's simultaneous exclusion and retirement.
        # The individual maintenance contracts have their own real-Publisher
        # tests; no authority is granted by the comparator's mock.
        original = copy.deepcopy(current)
        excluded = dict(current["events"][-1], id="other-event")
        orphan = {"id": "orphan", "name": "Orphan Identity", "aliases": []}
        original["events"].append(excluded)
        original["artists"].append(orphan)
        receipt = {"eventId": "other-event", "reason": "venue-name-genre-contamination",
                   "date": fixture.TODAY.isoformat()}
        ledger["editorialCorrections"] = [{"originalEvent": excluded}]
        ledger["artistIdentityRetirements"] = [{"artistId": "orphan"}]
        for cat, stats in ((before, counts_before), (after, counts_after)):
            cat["editorialExclusions"] = [receipt]
            cat["retiredArtistIds"] = ["orphan"]
            stats.update(editorialExclusions=1, deferredEditorialCorrections=0,
                         retiredArtists=1)
        with mock.patch.object(sync, "merge", side_effect=[
                (before, counts_before), (after, counts_after)]):
            proposed, status = preflight.select(ledger, report, base, original,
                                                fixture.TODAY)
        self.assertTrue(status["validatedByPublisher"], status)
        self.assertEqual(proposed["editorialCorrections"], ledger["editorialCorrections"])
        self.assertEqual(proposed["artistIdentityRetirements"], ledger["artistIdentityRetirements"])
        self.assertEqual(proposed["lineupCorrections"], [row])
        for altered in (dict(after, retiredArtistIds=["orphan", "other"]),
                        dict(after, events=after["events"][1:])):
            with mock.patch.object(sync, "merge", side_effect=[
                    (before, counts_before), (altered, counts_after)]):
                rejected, status = preflight.select(ledger, report, base, original,
                                                    fixture.TODAY)
            self.assertEqual(rejected, ledger)
            self.assertEqual(status["held"], 1)
            self.assertFalse(status["validatedByPublisher"])
            self.assertTrue(status["heldDiagnostics"])

    def test_ambiguous_pipe_and_network_failure_never_sign_correction(self):
        base, current, ledger, fetch = self.initial(
            ["Example Band | Other Band"], "Example Band | Other Band",
            "Example Band | Other Band")
        report = builder.build_promotional(current, ledger, fixture.TODAY, fetch=fetch)
        self.assertFalse(report["proposals"])
        def unavailable(url, cache):
            raise OSError("offline")
        report = builder.build_promotional(current, ledger, fixture.TODAY, fetch=unavailable)
        self.assertFalse(report["proposals"])


if __name__ == "__main__":
    unittest.main()
