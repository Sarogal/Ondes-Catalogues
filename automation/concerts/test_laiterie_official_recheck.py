"""La Laiterie: independent, exact first-party recheck and publisher contract.

All publisher assertions call the REAL production validator. No network,
secrets or private registry are involved.
"""
from __future__ import annotations

import copy
import datetime as dt
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "automation" / "concerts"))

import concerts_cloud_sync as publisher
import laiterie_adapter as adapter
import laiterie_official_recheck as verifier
import official_recheck as engine

TODAY = dt.date(2026, 11, 9)
URL = ("https://www.artefact.org/la-laiterie/evenements/"
       "peter-hook-2027/")
SOURCE = {"name": "La Laiterie", "city": "Strasbourg", "department": "67",
          "url": adapter.AGENDA}
PAGE = """<html><body><main><section>
<p>Vendredi 2 avril 2027</p>
<p>Ouverture des portes à 19h30</p>
<h1>PETER HOOK & THE LIGHT</h1>
<p>A Joy Division Celebration</p>
<p>Lieu</p><p>Laiterie, Grande Salle</p>
<p>Présentés par</p><p>Artefact PRL</p>
<p>Genre</p><p>#Rock New wave Post-Punk</p>
</section><section>
<h2>Artistes</h2>
<h2>PETER HOOK & THE LIGHT</h2>
<p>20h45 sur scène</p>
<p>Le groupe est annoncé en tournée européenne.</p>
<h2>On vous recommande</h2>
<h2>Autre artiste le mois prochain</h2>
</section></main></body></html>"""


def catalogue():
    return {"schemaVersion": 1, "mode": "preview-public-unlisted",
            "venues": [{
                "id": "la-laiterie-strasbourg", "name": "La Laiterie",
                "city": "Strasbourg", "latitude": 48.5839,
                "longitude": 7.7455,
            }],
            "artists": [{
                "id": "peter-hook-and-the-light",
                "name": "Peter Hook and The Light", "aliases": [],
            }],
            "events": []}


def candidate():
    result = adapter.details(PAGE, URL, SOURCE, TODAY.isoformat())
    result.update({"reviewBucket": "genre_tag_review",
                   "possibleExistingConcert": False})
    return result


def signed():
    return verifier.verify(candidate(), PAGE, catalogue(), TODAY)


def publisher_review(row):
    c = catalogue()
    venues = {x["id"]: x for x in c["venues"]}
    artists = {x["id"]: x for x in c["artists"]}
    return publisher.validate_approval(row, venues, artists, TODAY)


class LaiterieOfficialRecheckTests(unittest.TestCase):
    def test_independent_recheck_requires_named_artist_section(self):
        row = signed()
        self.assertEqual(row["event"]["artistIds"], ["peter-hook-and-the-light"])
        self.assertEqual(row["event"]["genres"], ["Post Punk"])
        self.assertIsNone(row["event"]["time"])
        self.assertEqual(row["officialEvidence"][0]["officialArtistNames"],
                         ["Peter Hook and The Light"])
        self.assertEqual(row["newArtists"], [])
        self.assertEqual(row["reviewedBy"], "automated-official-recheck")

    def test_same_signed_output_passes_real_publisher(self):
        row = signed()
        event, new = publisher_review(row)
        self.assertEqual(event, row["event"])
        self.assertEqual(new, {})

    def test_only_one_official_named_artist_may_pass(self):
        variants = [
            PAGE.replace("<h2>On vous recommande</h2>",
                         "<h2>+ HIDDEN SUPPORT</h2><h2>On vous recommande</h2>"),
            PAGE.replace("<h2>PETER HOOK & THE LIGHT</h2>",
                         "<h2>SOME OTHER BAND</h2>"),
            PAGE.replace("<h2>Artistes</h2>", ""),
            PAGE.replace("<h1>PETER HOOK & THE LIGHT</h1>",
                         "<h1>PETER HOOK & THE LIGHT + GUEST</h1>"),
            PAGE.replace("#Rock New wave Post-Punk", "#Chanson electro"),
            PAGE.replace("Laiterie, Grande Salle", "Salle différente"),
            PAGE.replace("Vendredi 2 avril 2027", "Vendredi 3 avril 2027"),
            PAGE.replace("Artefact PRL", "CONCERT REPORTÉ"),
        ]
        for html in variants:
            with self.subTest(variant=html[:110]), self.assertRaises(ValueError):
                verifier.verify(candidate(), html, catalogue(), TODAY)

    def test_discovery_duplicate_and_new_artist_never_pass(self):
        for key, value in (
            ("reviewBucket", "possible_duplicate"),
            ("possibleExistingConcert", True),
            ("publicationAllowed", True),
            ("officialDetailFound", False),
            ("sourcePage", "https://example.net/agenda"),
        ):
            altered = candidate()
            altered[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                verifier.verify(altered, PAGE, catalogue(), TODAY)
        c = catalogue()
        c["artists"] = []
        with self.assertRaisesRegex(ValueError, "canonique"):
            verifier.verify(candidate(), PAGE, c, TODAY)

    def test_already_published_or_same_venue_day_artist_is_held(self):
        c = catalogue()
        c["events"].append({"id": "existing", "date": "2027-04-02",
                            "venueId": "la-laiterie-strasbourg",
                            "artistIds": ["peter-hook-and-the-light"]})
        with self.assertRaisesRegex(ValueError, "déjà connu"):
            verifier.verify(candidate(), PAGE, c, TODAY)

    def test_publisher_rejects_name_date_venue_genre_and_evidence_spoofing(self):
        for key, value in (
            ("title", "Some Other Band"),
            ("date", "2027-04-03"),
            ("venueId", "another-venue"),
            ("artistIds", ["unlisted-band"]),
            ("time", "19:30"),
            ("genres", ["Electro"]),
            ("organizer", "Other Venue"),
            ("id", "go-c-20270402-strasbourg-wrong"),
        ):
            row = copy.deepcopy(signed())
            row["event"][key] = value
            with self.subTest(field=key), self.assertRaises((ValueError, KeyError)):
                publisher_review(row)
        for key, value in (
            ("sourceStructure", "generic-agenda"),
            ("officialArtistNames", ["Other band"]),
            ("checkedFields", ["artists", "date", "venue"]),
            ("proofType", "aggregator"),
            ("checkedAt", "2026-11-01"),
        ):
            row = copy.deepcopy(signed())
            row["officialEvidence"][0][key] = value
            with self.subTest(field=key), self.assertRaises(ValueError):
                publisher_review(row)

    def test_publisher_rejects_outside_url_or_new_artists(self):
        for url in (
            "https://example.org/la-laiterie/evenements/peter-hook-2027/",
            "http://www.artefact.org/la-laiterie/evenements/peter-hook-2027/",
            "https://www.artefact.org/la-laiterie/evenements/peter-hook-2027/?utm=1",
            "https://www.artefact.org/la-laiterie/programmation/",
        ):
            row = copy.deepcopy(signed())
            row["event"]["officialUrl"] = url
            with self.subTest(url=url), self.assertRaises(ValueError):
                publisher_review(row)
        row = copy.deepcopy(signed())
        row["newArtists"] = [{"id": "invented", "name": "Invented"}]
        with self.assertRaises(ValueError):
            publisher_review(row)

    def test_interday_stability_is_mandatory_and_process_idempotent(self):
        approvals = {"schema": "grossesondes.concert.approvals.v1",
                     "approvals": []}
        c = catalogue()
        reg = {"items": {"laiterie": {
            "candidate": candidate(), "status": "pending_review",
            "observations": 22, "stableObservations": 1,
        }}}
        def fail(*args):
            raise AssertionError("A single observation must not refetch")
        out, report = engine.process(reg, c, approvals, TODAY, fetch=fail)
        self.assertEqual(report["evaluated"], 0)
        self.assertEqual(out["approvals"], [])
        reg["items"]["laiterie"]["stableObservations"] = 2
        result, report = engine.process(
            reg, c, approvals, TODAY, fetch=lambda url, cache: PAGE)
        self.assertEqual(len(report["newApprovals"]), 1)
        self.assertEqual(result["approvals"][0]["event"]["id"],
                         "go-c-20270402-strasbourg-peter-hook-and-the-light")
        again, report = engine.process(reg, c, result, TODAY, fetch=fail)
        self.assertEqual(report["alreadyApprovedSkipped"], 1)
        self.assertEqual(again, result)


if __name__ == "__main__":
    unittest.main()
