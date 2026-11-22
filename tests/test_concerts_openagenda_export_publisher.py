"""One actual OpenAgenda-owned JSON export can publish an existing-venue gig.

No JSON-LD, OSM witness, artist allowlist or second event page is needed.
The publisher independently re-fetches the same first-party export.
"""
import copy
import datetime as dt
import json
import unittest
from unittest import mock

from automation.concerts import dynamic_osm_official_proposals as producer
from automation.concerts import openagenda_official_concert as oa
from automation.concerts import approval_preflight
from scripts import concert_dynamic_existing_venue as identity
from scripts import concerts_cloud_sync as publisher
import test_concerts_dynamic_existing_venue as fixture

TODAY = dt.date(2026, 11, 22)
DAY = "2027-03-05"
URL = "https://openagenda.com/fr/shotgun/events/87654321_eight-unknown-metal-bands"
EXPORT = "https://openagenda.com/agendas/9969608/events.json?uid=87654321&limit=1"


def registry():
    return {"schema": "grossesondes.concert.intake.v1",
            "items": {"from-openagenda": {
                "status": "pending_review", "stableObservations": 1,
                "candidate": {
                    "candidateId": "from-openagenda",
                    "source": "agenda_officiel_openagenda",
                    "sourceUrl": URL, "sourcePage": URL,
                    "eventDetailUrl": URL,
                    "openAgendaUid": "9969608",
                    "openAgendaEventUid": "87654321",
                    "date": DAY, "name": " + ".join(fixture.NAMES),
                    "leadArtist": fixture.NAMES[0],
                    "venue": "Le Bikini", "city": "Ramonville-Saint-Agne",
                    "department": "31", "reviewBucket": "genre_tag_review",
                    "possibleExistingConcert": False,
                    "publicationAllowed": False, "reviewRequired": True,
                }}}}


def official_export(**changes):
    venue = next(v for v in fixture.BASE["venues"]
                 if v["id"] == fixture.VENUE_ID)
    record = {
        "uid": 87654321, "slug": "eight-unknown-metal-bands",
        "status": 1, "firstDate": DAY, "lastDate": DAY,
        "originAgenda": {"uid": 9969608, "slug": "shotgun"},
        "title": {"fr": " + ".join(fixture.NAMES)},
        "keywords": {"fr": ["Black Metal", "punk"]},
        "location": {
            "name": "Le Bikini", "city": "Ramonville-Saint-Agne",
            "postalCode": "31520", "countryCode": "fr",
            "address": venue["address"] + ", 31520 Ramonville-Saint-Agne, France",
        },
    }
    record.update(changes)
    return json.dumps({"total": 1, "events": [record]}, ensure_ascii=False)


class OpenAgendaFirstPartyExportContract(unittest.TestCase):
    def setUp(self):
        self.catalogue = copy.deepcopy(fixture.BASE)
        old = publisher.NEW_REFERENCE_GEO_SOURCES.pop(fixture.VENUE_ID, None)
        if old is not None:
            self.addCleanup(lambda: publisher.NEW_REFERENCE_GEO_SOURCES.__setitem__(
                fixture.VENUE_ID, old))

    def test_publisher_accepts_official_export_without_json_ld(self):
        observed = []
        def get(url, cache):
            observed.append(url)
            self.assertEqual(url, EXPORT, "only the original OpenAgenda export")
            return official_export()
        self.assertEqual(oa.official_export_url("9969608", "87654321"), EXPORT)
        with mock.patch.object(identity, "safe_fetch", side_effect=get):
            before = {"schema": publisher.SCHEMA, "approvals": []}
            proposals, report = producer.build(
                registry(), self.catalogue, before, TODAY, fetch=get)
            self.assertEqual(report["stateCounts"],
                             {"independently_verified_proposal": 1}, report)
            signed = proposals["approvals"][0]
            proof = signed["officialEvidence"][0]
            self.assertEqual(proof["proofType"], identity.OPENAGENDA_PROFILE)
            self.assertEqual(proof["officialOpenAgendaUid"], "9969608")
            self.assertEqual(proof["officialOpenAgendaEventUid"], "87654321")
            self.assertEqual(len(signed["newArtists"]), 8)
            self.assertEqual(len(approval_preflight.check_append_only(
                before, proposals, TODAY)), 1)
            published, stats = publisher.merge(
                self.catalogue, self.catalogue, proposals, TODAY)
            self.assertEqual(stats["newEvents"], 1, stats["held"])
            self.assertEqual(stats["newArtists"], 8)
            self.assertEqual(published["events"][-1]["officialUrl"], URL)
        self.assertGreaterEqual(len(observed), 3)
        self.assertEqual(set(observed), {EXPORT})

    def test_forged_ambiguous_or_wrong_style_export_never_approves(self):
        failures = (
            {"status": 2},
            {"firstDate": "2027-03-06"},
            {"originAgenda": {"uid": 987654, "slug": "shotgun"}},
            {"originAgenda": {"uid": 9969608, "slug": "forged"}},
            {"uid": 87654322},
            {"slug": "another-event"},
            {"title": {"fr": "Festival des arts métal"}},
            {"keywords": {"fr": ["Hardcore Techno"]}},
            {"location": {"name": "Another Venue", "city": "Paris",
                           "countryCode": "fr"}},
        )
        for corrupt in failures:
            with self.subTest(corrupt=corrupt):
                def get(url, cache):
                    self.assertEqual(url, EXPORT)
                    return official_export(**corrupt)
                proposals, result = producer.build(
                    registry(), self.catalogue,
                    {"schema": publisher.SCHEMA, "approvals": []},
                    TODAY, fetch=get)
                self.assertEqual(proposals["approvals"], [])
                self.assertEqual(result["stateCounts"],
                    {"held_event_or_source_not_verified": 1})

    def test_untrusted_ids_cannot_change_first_party_origin(self):
        for ids in ((-1, 87654321), ("9969608/evil", "87654321"),
                    (9969608, "1?x=2"), (False, 87654321)):
            with self.subTest(ids=ids):
                with self.assertRaises(ValueError):
                    oa.official_export_url(*ids)


if __name__ == "__main__":
    unittest.main()
