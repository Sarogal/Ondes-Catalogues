"""End-to-end no-network test: official venue + OSM, NO second website."""
import copy
import datetime as dt
import unittest
from unittest import mock

from automation.concerts import dynamic_osm_official_proposals as pipeline
from scripts import concert_dynamic_existing_venue as identity
from scripts import concerts_cloud_sync as publisher
from automation.concerts import approval_preflight
import test_concerts_dynamic_existing_venue as fixture

TODAY = dt.date(2026, 11, 21)
BASE = fixture.BASE
URL = fixture.EVENT


def registry(stable=2, *, source="agenda_officiel_structuré",
             venue="Le Bikini", city="Ramonville-Saint-Agne",
             bucket="genre_tag_review", url=URL):
    return {"schema": "grossesondes.concert.intake.v1",
            "items": {"new-unique": {
                "status": "pending_review", "stableObservations": stable,
                "candidate": {
                    "candidateId": "new-unique", "source": source,
                    "sourceUrl": url, "sourcePage": url,
                    "eventDetailUrl": url,
                    "date": "2027-03-05", "name": "Groupe Libre 1",
                    "leadArtist": "Groupe Libre 1",
                    "venue": venue, "city": city, "department": "31",
                    "reviewBucket": bucket, "possibleExistingConcert": False,
                    "publicationAllowed": False, "reviewRequired": True,
                }}}
            }


class SingleOSMOfficialPublisherTests(unittest.TestCase):
    def setUp(self):
        # The reference fixture has a historical location migration, which
        # is unrelated to this new admission contract and checked elsewhere.
        old = publisher.NEW_REFERENCE_GEO_SOURCES.pop(
            fixture.VENUE_ID, None)
        self.assertIsNotNone(old)
        self.addCleanup(lambda: publisher.NEW_REFERENCE_GEO_SOURCES.__setitem__(
            fixture.VENUE_ID, old))

    def test_unknown_artists_and_domain_publish_via_real_publisher(self):
        fetch = fixture.fake_fetch()
        reads = []
        def single_source(url, cache):
            self.assertNotEqual(url, fixture.WITNESS)
            reads.append(url)
            return fetch(url, cache)
        proposals, report = pipeline.build(
            registry(), BASE,
            {"schema": publisher.SCHEMA, "approvals": []},
            TODAY, slot=0, limit=8, fetch=single_source)
        self.assertEqual(report["eligibleQueue"], 1)
        self.assertEqual(report["examined"], 1)
        self.assertEqual(report["stateCounts"],
                         {"independently_verified_proposal": 1})
        self.assertFalse(report["publicationAllowed"])
        self.assertFalse(report["privateApprovalApplied"])
        self.assertEqual(len(proposals["approvals"]), 1)
        app = proposals["approvals"][0]
        self.assertEqual(app["officialEvidence"][0]["proofType"],
                         identity.OSM_SINGLE_PROFILE)
        self.assertNotIn("corroboratingEventUrl", app["officialEvidence"][0])
        self.assertEqual(len(app["newArtists"]), 8)
        with mock.patch.object(identity, "safe_fetch",
                               side_effect=single_source):
            accepted = approval_preflight.check_append_only(
                {"schema": publisher.SCHEMA, "approvals": []},
                proposals, TODAY)
            self.assertEqual(len(accepted), 1)
            merged, stats = publisher.merge(BASE, BASE, proposals, TODAY)
        self.assertEqual(stats["newEvents"], 1)
        self.assertEqual(stats["newArtists"], 8)
        self.assertEqual(stats["newVenues"], 0)
        self.assertEqual(merged["events"][-1]["officialUrl"], URL)
        self.assertIn(URL, reads)
        self.assertTrue(any("api.openstreetmap.org" in x for x in reads))
        self.assertNotIn(fixture.WITNESS, reads)
        with mock.patch.object(identity, "safe_fetch",
                               side_effect=AssertionError("replay must not refetch")):
            same, again = publisher.merge(BASE, merged, proposals, TODAY)
        self.assertEqual(again["newEvents"], 0)
        self.assertEqual(same, merged)

    def test_unknown_genre_discovery_may_be_proven_by_exact_event_performer(self):
        leads = pipeline.eligible(registry(bucket="genre_unknown"), BASE, TODAY)
        self.assertEqual(len(leads), 1)
        app = pipeline.propose(leads[0], BASE, TODAY,
                               fetch=fixture.fake_fetch())
        self.assertEqual(app["event"]["genres"], ["Black Metal"])

    def test_no_stability_festival_third_party_or_unknown_venue_can_qualify(self):
        for change in (
            lambda r: r["items"]["new-unique"].update(stableObservations=1),
            lambda r: r["items"]["new-unique"]["candidate"].update(
                reviewBucket="festival_overlap_review"),
            lambda r: r["items"]["new-unique"]["candidate"].update(
                source="third_party_calendar_lead"),
            lambda r: r["items"]["new-unique"]["candidate"].update(
                venue="An Unknown Square"),
            lambda r: r["items"]["new-unique"]["candidate"].update(
                city="Paris"),
            lambda r: r["items"]["new-unique"]["candidate"].update(
                sourcePage="https://other-source.fr/calendar/"),
            lambda r: r["items"]["new-unique"]["candidate"].update(
                sourceUrl="https://unknown-source.fr/event/",
                eventDetailUrl="https://unknown-source.fr/event/",
                sourcePage="https://unknown-source.fr/event/"),
            lambda r: r["items"]["new-unique"]["candidate"].update(
                publicationAllowed=True),
        ):
            case = registry()
            change(case)
            with self.subTest(change=change):
                if "unknown-source.fr" in str(case):
                    # Valid but unverified sources may enter research, never
                    # pass attribution/Publisher on their own.
                    candidates = pipeline.eligible(case, BASE, TODAY)
                    self.assertEqual(len(candidates), 1)
                    proposals, state = pipeline.build(
                        case, BASE,
                        {"schema": publisher.SCHEMA, "approvals": []},
                        TODAY, fetch=fixture.fake_fetch())
                    self.assertEqual(len(proposals["approvals"]), 0)
                    self.assertEqual(state["examined"], 1)
                else:
                    self.assertEqual(
                        pipeline.eligible(case, BASE, TODAY), [])

    def test_forged_geometry_and_changed_artist_date_genre_fail_closed(self):
        bad_pages = [
            fixture.page(URL, date="2027-03-06"),
            fixture.page(URL, venue_name="Wrong Hall"),
            fixture.page(URL, genres=False),
            fixture.page(URL, music=False),
            fixture.page(URL, country="BE"),
            fixture.page(URL, names=["Unrelated Artist"]),
        ]
        for altered in bad_pages:
            def tampered(url, cache):
                return (altered if url == URL else fixture.osm())
            with self.subTest(altered=altered[:80]):
                out, summary = pipeline.build(
                    registry(), BASE,
                    {"schema": publisher.SCHEMA, "approvals": []},
                    TODAY, fetch=tampered)
                self.assertEqual(len(out["approvals"]), 0)
                self.assertEqual(summary["stateCounts"],
                    {"held_event_or_source_not_verified": 1})
        def fake_osm(url, cache):
            return (fixture.osm(website="https://attacker.fr")
                    if url.startswith("https://api.openstreetmap.org/")
                    else fixture.page(URL))
        result, _ = pipeline.build(
            registry(), BASE,
            {"schema": publisher.SCHEMA, "approvals": []},
            TODAY, fetch=fake_osm)
        self.assertEqual(result["approvals"], [])

    def test_publisher_rejects_forged_profile_and_extra_fields(self):
        app = pipeline.propose(pipeline.eligible(registry(), BASE, TODAY)[0],
                               BASE, TODAY, fetch=fixture.fake_fetch())
        with mock.patch.object(identity, "safe_fetch",
                               side_effect=fixture.fake_fetch()):
            for field, value in (
                ("namedOsmUrl", "https://www.openstreetmap.org/node/9"),
                ("officialGenreLabels", ["Jazz"]),
                ("officialArtistNames", ["Fake Musician"]),
                ("corroboratingEventUrl", fixture.WITNESS),
                ("proofType", "made-up-profile"),
            ):
                changed = copy.deepcopy(app)
                changed["officialEvidence"][0][field] = value
                with self.subTest(field=field), self.assertRaises(ValueError):
                    publisher.validate_approval(
                        changed,
                        {v["id"]: v for v in BASE["venues"]},
                        {a["id"]: a for a in BASE["artists"]}, TODAY)

    def test_scan_budget_rotates_across_any_number_of_candidate_events(self):
        cases = registry()
        proto = next(iter(cases["items"].values()))
        cases["items"] = {}
        for i in range(80):
            row = copy.deepcopy(proto)
            url = "https://official-unknown.fr/agenda/band-%03d/" % i
            row["candidate"]["sourceUrl"] = url
            row["candidate"]["eventDetailUrl"] = url
            row["candidate"]["sourcePage"] = url
            row["candidateId"] = str(i)
            cases["items"][str(i)] = row
        checked = set()
        for day_offset in range(4):
            for slot in (0, 1, 2):
                day = TODAY + dt.timedelta(days=day_offset)
                selected = pipeline.eligible(cases, BASE, day)
                start = (((day - TODAY).days * 3 + slot) * 8) % len(selected)
                sample = [selected[(start + x) % len(selected)]
                          for x in range(8)]
                checked.update(url for url, date, vid, c in sample)
        self.assertEqual(len(checked), 80)


if __name__ == "__main__":
    unittest.main()
