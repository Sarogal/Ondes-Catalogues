"""La Laiterie first-party event tag: Garage Rock is a named subgenre, not generic Rock.

Uses a synthetic HTML rendering of the published official layout for
THE LAST INTERNATIONALE + DAMANTRA, 10 February 2027. All publisher checks
run against the real code. Never publishes or fetches the web.
"""
import copy
import datetime as dt
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "automation" / "concerts"))
sys.path.insert(0, str(ROOT / "scripts"))

import laiterie_adapter as adapter
import laiterie_official_recheck as verifier
import concerts_cloud_sync as publisher

TODAY = dt.date(2026, 11, 16)
URL = "https://www.artefact.org/la-laiterie/evenements/the-last-internationale2027/"
SOURCE = {"name": "La Laiterie", "city": "Strasbourg",
          "department": "67", "url": adapter.AGENDA}
PAGE = """<html><body><main><section>
<p>Mercredi 10 février 2027</p>
<p>Ouverture des portes à 19h30</p>
<h1>THE LAST INTERNATIONALE</h1>
<h2>+ DAMANTRA</h2>
<p>Lieu</p><p>Laiterie, Grande Salle</p>
<p>Présentés par</p><p>Artefact PRL</p>
<p>Genre</p><p>#Rock'n'roll Alternative Rock Garage Rock</p>
</section><section>
<h2>Artistes</h2>
<h2>THE LAST INTERNATIONALE</h2><p>Groupe confirmé</p>
<h2>DAMANTRA</h2><p>Première partie nominative confirmée</p>
<h2>On vous recommande</h2><h2>Autre groupe</h2>
</section></main></body></html>"""


def catalogue():
    return {
        "schemaVersion": 1, "mode": "preview-public-unlisted",
        "venues": [{
            "id": "la-laiterie-strasbourg",
            "name": "La Laiterie", "city": "Strasbourg",
            "latitude": 48.5839, "longitude": 7.7455,
        }],
        "artists": [], "events": [],
    }


def candidate(page=PAGE):
    row = adapter.details(page, URL, SOURCE, TODAY.isoformat())
    row["reviewBucket"] = "genre_tag_review"
    row["possibleExistingConcert"] = False
    return row


class LaiterieGarageRockContractTests(unittest.TestCase):
    def test_exact_first_party_genre_and_two_named_acts_pass_real_publisher(self):
        cat = catalogue()
        initial = copy.deepcopy(cat)
        proposed = verifier.verify(candidate(), PAGE, cat, TODAY)
        self.assertEqual(proposed["event"]["title"],
                         "THE LAST INTERNATIONALE + DAMANTRA")
        self.assertEqual(proposed["event"]["artistIds"],
                         ["the-last-internationale", "damantra"])
        self.assertEqual(proposed["event"]["genres"], ["Garage Rock"])
        self.assertEqual(proposed["event"]["date"], "2027-02-10")
        self.assertIsNone(proposed["event"]["time"])
        self.assertEqual(proposed["newArtists"], [
            {"id": "the-last-internationale", "name": "THE LAST INTERNATIONALE"},
            {"id": "damantra", "name": "DAMANTRA"},
        ])
        event, added = publisher.validate_approval(
            proposed,
            {v["id"]: v for v in cat["venues"]},
            {a["id"]: a for a in cat["artists"]},
            TODAY,
        )
        self.assertEqual(event, proposed["event"])
        self.assertEqual(set(added), set(event["artistIds"]))
        self.assertEqual(cat, initial)

    def test_generic_rock_or_biography_mention_is_not_accepted(self):
        for bad in (
            PAGE.replace("#Rock'n'roll Alternative Rock Garage Rock",
                         "#Rock"),
            PAGE.replace("#Rock'n'roll Alternative Rock Garage Rock",
                         "#Alternative Rock"),
            PAGE.replace("#Rock'n'roll Alternative Rock Garage Rock",
                         "#Rock").replace(
                             "<p>Groupe confirmé</p>",
                             "<p>Ce groupe joue du Garage Rock</p>"),
        ):
            with self.subTest(bad=bad[:140]), self.assertRaisesRegex(
                    ValueError, "Genre"):
                verifier.verify(candidate(bad), bad, catalogue(), TODAY)

    def test_forged_genre_date_second_band_and_door_time_still_fail(self):
        signed = verifier.verify(candidate(), PAGE, catalogue(), TODAY)
        venues = {x["id"]: x for x in catalogue()["venues"]}
        for field, value in (
            ("genres", ["Alternative Rock"]),
            ("genres", ["Rock"]),
            ("date", "2027-02-11"),
            ("time", "19:30"),
            ("title", "THE LAST INTERNATIONALE"),
            ("artistIds", ["the-last-internationale"]),
            ("organizer", "Untrusted promoter"),
        ):
            altered = copy.deepcopy(signed)
            altered["event"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                publisher.validate_approval(altered, venues, {}, TODAY)
        invalid_html = PAGE.replace(
            "<h2>DAMANTRA</h2><p>Première partie",
            "<h2>INVENTED ACT</h2><p>Première partie")
        with self.assertRaises(ValueError):
            verifier.verify(candidate(), invalid_html, catalogue(), TODAY)


if __name__ == "__main__":
    unittest.main()
