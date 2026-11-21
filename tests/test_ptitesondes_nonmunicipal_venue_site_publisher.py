"""Unknown non-municipal venue admission, exact OSM website and live OA.

No real host, venue or city is enumerated in the Publisher. Test the connected
existing append-only merge and adversarial failures, without network/writes.
"""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from test_ptitesondes_open_world_patch_bridge import dossier, private_patch
from test_ptitesondes_open_world_release_rehearsal import (
    TODAY, DAY, KEY, POINT, VENUE, CITY, lead, oa_event, official_page,
)
from test_ptitesondes_candidate_promotion import base
from ptitesondes_open_world_patch_bridge import merge_verified_open_world
from ptitesondes_independent_venue_site_proof import (
    mint_named_osm_venue_website_proof,
    verified_named_osm_venue_website,
)

SOURCE = "https://example-live-venue.test/events/conte-musical"


def osm(*, website=SOURCE, extra=False, offset=0, place=VENUE):
    element = {"type": "node", "id": 722001,
               "lat": POINT[0] + offset, "lon": POINT[1],
               "tags": {"name": place, "website": website,
                        "addr:city": CITY, "addr:country": "FR"}}
    found = [element]
    if extra:
        found.append({**element, "id": 722002})
    return {"elements": found}


def run(*, osm_data=None, webpage=None, oa_data=None, event_url=SOURCE,
        venue_url=None, private=None):
    reference = base()
    if private is None:
        private = private_patch(reference, [
            dossier(official_event_url=event_url,
                    official_venue_url=event_url if venue_url is None else venue_url)
        ])
    def official(url):
        if url != event_url:
            raise AssertionError("untrusted external source was fetched")
        return official_page() if webpage is None else webpage
    def independent(center):
        if center != POINT:
            raise AssertionError("OSM center must come from live OA UID")
        return osm() if osm_data is None else osm_data
    return reference, merge_verified_open_world(
        reference, reference, private, TODAY, KEY,
        agenda_reader=lambda uid, key: {
            "uid": lead()["agenda_uid"], "slug": lead()["agenda_slug"]},
        event_reader=lambda agenda_uid, event_uid, key: (
            oa_event() if oa_data is None else oa_data),
        directory_reader=lambda city: {"results": []},
        official_reader=official,
        osm_reader=independent,
        ign_reader=lambda query: (_ for _ in ()).throw(
            AssertionError("no municipal BAN fallback when site verified")),
        legacy_checker=lambda candidate, original: (False, "unknown_candidate"),
    )


class IndependentVenueWebsitePublisherTests(unittest.TestCase):
    def test_unknown_venue_and_nonmunicipal_site_reach_actual_merge(self):
        reference, (published, audit, bridge) = run()
        self.assertEqual(audit["ajoutes"], 1)
        self.assertEqual(bridge["admitted_to_merge"], 1)
        self.assertEqual(bridge["publisher_accepted_new"], 1)
        self.assertEqual(bridge["held"], 0)
        self.assertFalse(bridge["publication_complete"])
        self.assertEqual(len(published["events"]), len(reference["events"]) + 1)
        self.assertEqual(published["events"][:-1], reference["events"])
        self.assertEqual(published["events"][-1]["source_url"], SOURCE)
        self.assertEqual(published["events"][-1]["time"], "10:00 ; 15:00")

    def test_missing_conflicting_ambiguous_and_unrelated_osm_never_promote(self):
        cases = [
            {"elements": []},
            osm(website="https://impostor.example.net/venue"),
            osm(extra=True),
            osm(offset=0.01),
            osm(place="Another venue"),
            {"elements": [{**osm()["elements"][0], "tags": {
                "name": VENUE, "website": SOURCE,
                "contact:website": "https://wrong.example.net/a"}}]},
        ]
        for bogus in cases:
            with self.subTest(bogus=bogus):
                ref, (published, audit, report) = run(osm_data=bogus)
                self.assertEqual(published, ref)
                self.assertEqual(audit["ajoutes"], 0)
                self.assertEqual(report["admitted_to_merge"], 0)
                self.assertEqual(report["held"], 1)

    def test_a_second_nonmunicipal_venue_url_cannot_inherit_source_authority(self):
        ref, (published, audit, report) = run(
            venue_url="https://another.example.net/venues/unknown")
        self.assertEqual(published, ref)
        self.assertEqual(report["admitted_to_merge"], 0)

    def test_exact_site_cannot_override_private_or_cancelled_access(self):
        ref, (published, audit, report) = run(
            webpage=official_page(school_only=True))
        self.assertEqual(published, ref)
        self.assertEqual(audit["ajoutes"], 0)
        self.assertEqual(report["held"], 1)

    def test_untrusted_source_time_change_does_not_gain_approval(self):
        changed = oa_event(hours=(11, 16))
        ref, (published, audit, report) = run(oa_data=changed)
        self.assertEqual(published, ref)
        self.assertEqual(audit["ajoutes"], 0)
        self.assertEqual(report["admitted_to_merge"], 0)

    def test_plain_dict_never_verifies_as_website_proof(self):
        self.assertFalse(verified_named_osm_venue_website(
            {"approved": True, "official_page": SOURCE}, SOURCE,
            CITY, VENUE, TODAY))
        proof = mint_named_osm_venue_website_proof(
            {"city": CITY, "venue": VENUE, "key": [
                __import__("proof").norm(CITY), __import__("proof").norm(VENUE)]},
            SOURCE, POINT, osm(), TODAY)
        self.assertIsNotNone(proof)
        self.assertTrue(verified_named_osm_venue_website(
            proof, SOURCE, CITY, VENUE, TODAY))
        self.assertFalse(verified_named_osm_venue_website(
            proof, "https://another.test/venue", CITY, VENUE, TODAY))


if __name__ == "__main__":
    unittest.main()
