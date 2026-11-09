"""Rockstore Montpellier: official single known act and REAL publisher contract.

Fictitious HTML fixture, official-shaped first party path, no network or
private candidate material. Existing manual signed IDs stay protected.
"""
from __future__ import annotations

import copy
import datetime as dt
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "automation" / "concerts"))

import concerts_cloud_sync as publisher
import official_recheck as engine
import rockstore_adapter as source
import rockstore_official_recheck as recheck
from test_rockstore_adapter import MASS, SOURCE, mass

NOW = dt.date(2026, 11, 9)
URL = "https://rockstore.fr/vulves-assassines-21-mai-2027/"
PAGE = """<html><head><title>Rockstore</title></head><body>
<nav>Concerts</nav><main>
<h1>VULVES ASSASSINES</h1>
<p>Vendredi 21 Mai 2027 à 20h</p>
<p>Punk-Rap/</p>
<p>VULVES ASSASSINES jouent une musique punk.</p>
</main><footer>Rockstore Montpellier</footer></body></html>"""


def catalogue():
    return {
        "schemaVersion": 1, "mode": "preview-public-unlisted",
        "venues": [{
            "id": "rockstore-montpellier", "name": "Rockstore",
            "city": "Montpellier", "latitude": 43.60624, "longitude": 3.88137,
        }],
        "artists": [
            {"id": "vulves-assassines", "name": "Vulves Assassines", "aliases": []},
            {"id": "mass-hysteria", "name": "Mass Hysteria", "aliases": []},
        ],
        "events": [],
    }


def candidate():
    data = source.detail_candidate(PAGE, URL, SOURCE, NOW.isoformat())
    data.update({"reviewBucket": "genre_tag_review",
                 "possibleExistingConcert": False})
    return data


def signed():
    return recheck.verify(candidate(), PAGE, catalogue(), NOW)


def publish_gate(approval):
    c = catalogue()
    return publisher.validate_approval(
        approval,
        {v["id"]: v for v in c["venues"]},
        {a["id"]: a for a in c["artists"]},
        NOW,
    )


class RockstoreOfficialRecheckTests(unittest.TestCase):
    def test_independent_official_recheck_has_no_inferred_music_start(self):
        approval = signed()
        event = approval["event"]
        self.assertEqual(event["id"],
                         "go-c-20270521-montpellier-vulves-assassines")
        self.assertEqual(event["genres"], ["Punk"])
        self.assertEqual(event["artistIds"], ["vulves-assassines"])
        self.assertIsNone(event["time"])
        self.assertEqual(approval["newArtists"], [])
        self.assertEqual(approval["officialEvidence"][0]["officialArtistNames"],
                         ["Vulves Assassines"])

    def test_real_publisher_accepts_same_signed_dossier(self):
        proposal = signed()
        event, new = publish_gate(proposal)
        self.assertEqual(event, proposal["event"])
        self.assertEqual(new, {})

    def test_first_party_date_and_music_tag_must_match_discovery(self):
        variants = [
            PAGE.replace("Vendredi 21 Mai 2027", "Vendredi 20 Mai 2027"),
            PAGE.replace("Vendredi 21 Mai 2027", "Vendredi 21 Mai"),
            PAGE.replace("VULVES ASSASSINES", "ANOTHER BAND"),
            PAGE.replace("Punk-Rap/", "Rap/"),
            PAGE.replace("Punk-Rap/", "Rock/"),
            PAGE.replace("jouent une musique punk",
                         "ANNULÉ, spectacle supprimé"),
            PAGE.replace("jouent une musique punk",
                         "Avec un SPECIAL GUEST encore inconnu"),
            PAGE.replace("jouent une musique punk",
                         "Première partie à annoncer"),
        ]
        for page in variants:
            with self.subTest(page=page[:100]), self.assertRaises(ValueError):
                recheck.verify(candidate(), page, catalogue(), NOW)

    def test_unknown_band_and_multi_artist_bill_are_held(self):
        c = catalogue()
        c["artists"] = c["artists"][1:]
        with self.assertRaisesRegex(ValueError, "canonique"):
            recheck.verify(candidate(), PAGE, c, NOW)
        page = PAGE.replace(
            "<h1>VULVES ASSASSINES</h1>",
            "<h1>VULVES ASSASSINES + UNKNOWN SUPPORT</h1>")
        with self.assertRaises(ValueError):
            recheck.verify(candidate(), page, catalogue(), NOW)

    def test_candidate_from_other_source_or_review_bucket_cannot_pass(self):
        for key, value in [
            ("reviewBucket", "possible_duplicate"),
            ("possibleExistingConcert", True),
            ("publicationAllowed", True),
            ("officialDetailFound", False),
            ("sourcePage", "https://other.example/agenda"),
            ("genreToConfirm", False),
        ]:
            with self.subTest(key=key):
                c = candidate()
                c[key] = value
                with self.assertRaises(ValueError):
                    recheck.verify(c, PAGE, catalogue(), NOW)

    def test_venue_day_artist_or_exact_url_duplicate_is_held(self):
        c = catalogue()
        c["events"].append({
            "id": "published", "date": "2027-05-21",
            "venueId": "rockstore-montpellier", "artistIds": ["vulves-assassines"],
            "officialUrl": "https://rockstore.fr/other-show-21-mai-2027/",
        })
        with self.assertRaisesRegex(ValueError, "deja publie"):
            recheck.verify(candidate(), PAGE, c, NOW)
        c["events"][0]["artistIds"] = ["another-act"]
        c["events"][0]["officialUrl"] = URL
        with self.assertRaisesRegex(ValueError, "deja publie"):
            recheck.verify(candidate(), PAGE, c, NOW)

    def test_publisher_rejects_altered_identity_venue_date_genre_and_clock(self):
        for field, value in [
            ("title", "Other Band"),
            ("date", "2027-05-22"),
            ("venueId", "different-venue"),
            ("artistIds", ["fake-act"]),
            ("id", "go-c-20270521-montpellier-fake-act"),
            ("genres", ["Rap"]),
            ("organizer", "Other company"),
            ("time", "20:00"),
        ]:
            with self.subTest(field=field):
                a = copy.deepcopy(signed())
                a["event"][field] = value
                with self.assertRaises((ValueError, KeyError)):
                    publish_gate(a)

    def test_publisher_rejects_pretend_evidence_and_nonofficial_url(self):
        for field, value in [
            ("proofType", "third-party-calendar"),
            ("sourceStructure", "guess"),
            ("officialArtistNames", ["Fake"]),
            ("checkedAt", "2026-11-08"),
            ("checkedFields", ["artists", "date"]),
        ]:
            a = copy.deepcopy(signed())
            a["officialEvidence"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                publish_gate(a)
        for url in [
            "https://fake.example/vulves-assassines-21-mai-2027/",
            "https://rockstore.fr/other-show-21-mai-2027/",
            "https://rockstore.fr/vulves-assassines-21-mai-2027/?utm=1",
            "http://rockstore.fr/vulves-assassines-21-mai-2027/",
        ]:
            a = copy.deepcopy(signed())
            a["event"]["officialUrl"] = url
            with self.subTest(url=url), self.assertRaises(ValueError):
                publish_gate(a)

    def test_existing_historic_signed_rockstore_must_not_be_overridden(self):
        c = catalogue()
        old = source.detail_candidate(mass(), MASS, SOURCE, NOW.isoformat())
        old.update({"reviewBucket": "genre_tag_review",
                    "possibleExistingConcert": False})
        unsigned = recheck.verify(old, mass(), c, NOW)
        self.assertEqual(unsigned["event"]["id"],
                         "go-c-20261119-montpellier-mass-hysteria")
        with self.assertRaises(ValueError):
            publish_gate(unsigned)

    def test_only_two_distinct_day_sightings_can_trigger_official_fetch(self):
        c = catalogue()
        approvals = {"schema": "grossesondes.concert.approvals.v1",
                     "approvals": []}
        reg = {"items": {"x": {
            "status": "pending_review", "candidate": candidate(),
            "observations": 300, "stableObservations": 1,
        }}}
        def forbidden(*args):
            raise AssertionError("No recheck before two independent days")
        result, report = engine.process(reg, c, approvals, NOW, fetch=forbidden)
        self.assertEqual(report["evaluated"], 0)
        self.assertEqual(result, approvals)
        reg["items"]["x"]["stableObservations"] = 2
        result, report = engine.process(
            reg, c, approvals, NOW, fetch=lambda url, cache: PAGE)
        self.assertEqual(len(report["newApprovals"]), 1)
        again, report2 = engine.process(reg, c, result, NOW, fetch=forbidden)
        self.assertEqual(report2["alreadyApprovedSkipped"], 1)
        self.assertEqual(again, result)


if __name__ == "__main__":
    unittest.main()
