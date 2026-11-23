"""Conservative approximate map markers for already signed future towns."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "festival-automation"))

from grossesondes_existing_official_updates import apply_independently_verified_updates
from grossesondes_cloud_sync import (
    _certified_new_commune_delta, _verified_official_update_delta,
)

SITE = "https://www.festivaldelapoutre.fr/"
TODAY = "2026-11-23"
HTML = """<main><h1>Festival de la Poutre 2027</h1>
<p>4e édition du festival rock et metal : rendez-vous les 11 et 12 juin 2027.</p>
<p>La prochaine édition est en préparation, détails du lieu à confirmer.</p>
</main>"""
ROW = {
    "slug": "festival-de-la-poutre-2027",
    "name": "Festival de la Poutre 2027",
    "startDate": "2027-06-11", "endDate": "2027-06-12",
    "city": "Colonne", "department": "39",
    "venue": "Adresse générale à confirmer pour cette édition",
    "lat": None, "lon": None, "showOnMap": False,
    "geoPrecision": None, "futureVenueConfirmed": False,
    "officialSite": SITE, "status": "Confirmé",
    "notes": "Le site précis 2027 n'est pas encore confirmé.",
    "lineup": [], "bands": 0, "price": None,
    "lastVerified": "2026-11-22", "auditSources": [SITE],
}
COMMUNE = {
    "city": "Colonne", "lat": 46.84, "lon": 5.71,
    "codeInsee": "39157",
    "geoSource": "https://geo.api.gouv.fr/communes?nom=Colonne",
}


def doc(row):
    return {"schema": 1, "generatedAt": "2026-11-22",
            "festivals": [deepcopy(row)]}


class SignedCommuneCenterTests(unittest.TestCase):
    def scan(self, row=ROW, html=HTML, geocode=None):
        geocodes = []
        def resolver(city, dept):
            geocodes.append((city, dept))
            return COMMUNE if geocode is None else geocode
        snapshot = doc(row)
        updated, report = apply_independently_verified_updates(
            snapshot, snapshot, TODAY, fetch=lambda _: html,
            limit=1, tick=0, commune_resolver=resolver)
        return updated["festivals"][0], report, geocodes

    def test_current_official_weekend_and_signed_town_create_approximate_pin(self):
        row, report, calls = self.scan()
        self.assertEqual(calls, [("Colonne", "39")])
        self.assertEqual(report["accepted"], [ROW["slug"]])
        self.assertEqual(row["geoPrecision"], "commune")
        self.assertEqual(row["geoCity"], "Colonne")
        self.assertTrue(row["showOnMap"])
        self.assertEqual(row["geoVerification"]["markerMeaning"],
                         "centre_indicatif_de_commune")
        self.assertEqual(row["geoVerification"]["proofMode"],
                         "signed-city-current-edition-centre.v1")
        self.assertEqual(row["venue"], ROW["venue"])
        self.assertEqual(row["notes"], ROW["notes"])
        self.assertEqual(row["lineup"], [])
        self.assertEqual(row["price"], None)
        self.assertTrue(_verified_official_update_delta(ROW, row))
        self.assertFalse(_certified_new_commune_delta(ROW, row))
        isolated = deepcopy(ROW)
        for key in ("city", "lat", "lon", "showOnMap", "geoCity",
                    "geoPrecision", "geoInsee", "geoSource", "geoVerification"):
            if key in row:
                isolated[key] = row[key]
        self.assertTrue(_certified_new_commune_delta(
            ROW, isolated, allow_direct=True))
        self.assertFalse(_certified_new_commune_delta(
            ROW, isolated, allow_direct=False))

    def test_old_edition_or_different_dates_never_geocodes(self):
        for body in (
                HTML.replace("2027", "2026"),
                HTML.replace("11 et 12 juin", "13 et 14 juin"),
                HTML.replace("rendez-vous", "annulé : rendez-vous")):
            with self.subTest(body=body):
                row, _, calls = self.scan(html=body)
                self.assertEqual(calls, [])
                self.assertFalse(row["showOnMap"])
                self.assertIsNone(row["lat"])

    def test_no_guess_from_venue_or_missing_signed_city(self):
        for changes in (
                {"city": None}, {"department": None},
                {"futureVenueConfirmed": True},
                {"lat": 46.84}, {"showOnMap": True},
                {"geoVerification": {"unverified": True}},
                {"geoPrecision": "commune"}):
            row = dict(ROW, **changes)
            updated, _, calls = self.scan(row=row)
            self.assertEqual(calls, [])
            self.assertEqual(updated, row)

    def test_ambiguous_or_conflicting_government_match_is_rejected(self):
        for answer in (False, {}, dict(COMMUNE, city="Dole")):
            row, report, calls = self.scan(geocode=answer)
            self.assertEqual(calls, [("Colonne", "39")])
            self.assertNotIn(ROW["slug"], report["accepted"])
            self.assertFalse(row["showOnMap"])

    def test_forged_or_modified_venue_is_not_certified(self):
        row, _, _ = self.scan()
        fake = dict(row, venue="Invented precise festival gate")
        self.assertFalse(_verified_official_update_delta(ROW, fake))
        fake2 = dict(row, city="Other Town", geoCity="Other Town")
        self.assertFalse(_verified_official_update_delta(ROW, fake2))


if __name__ == "__main__":
    unittest.main()
