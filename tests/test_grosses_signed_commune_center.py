"""Conservative approximate map markers for already signed future towns."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "festival-automation"))

from grossesondes_existing_official_updates import (apply_independently_verified_updates,
    signed_programmer_city_url, signed_programmer_current_city)
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




PROGRAMMER = "https://www.programmation-officielle.fr/festivals/"
PREVIOUS_HOME = """<main><h1>Festival de la Poutre 2026</h1>
<p>Rendez-vous les 10 et 11 juin 2026.</p></main>"""
PROGRAMMER_HTML = """<main>
<h2>Festival de la Poutre</h2>
<p>Production : Mairie de Colonne
Organisation : Association exemple
Programmation et communication : Partenaire officiel</p>
<p>Prochaine édition : 11 et 12 juin 2027</p>
<h2>Autre Festival</h2>
<p>Production : Mairie de Troyes</p>
<p>Prochaine édition : 18 et 19 juillet 2027</p>
</main>"""
SIGNED_PROGRAMMER_ROW = dict(
    ROW, source=PROGRAMMER,
    sourceConfidence="Organisateur/programmateur officiel : partenaire signé",
    auditSources=[SITE, PROGRAMMER])


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

    def scan_programmer(self, row=None, *, home=PREVIOUS_HOME,
                        partner=PROGRAMMER_HTML):
        row = deepcopy(row or SIGNED_PROGRAMMER_ROW)
        fetched, resolved = [], []
        def fetch(url):
            fetched.append(url)
            if url == SITE:
                return home
            if url == PROGRAMMER:
                return partner
            raise AssertionError("Unexpected network root")
        def geocode(city, department):
            resolved.append((city, department))
            return COMMUNE
        published = doc(row)
        result, report = apply_independently_verified_updates(
            published, published, TODAY, fetch=fetch,
            commune_resolver=geocode, limit=1, tick=0)
        return result["festivals"][0], report, fetched, resolved

    def test_signed_programmer_current_edition_city_can_make_commune_marker(self):
        self.assertEqual(signed_programmer_city_url(SIGNED_PROGRAMMER_ROW),
                         PROGRAMMER)
        self.assertTrue(signed_programmer_current_city(
            PROGRAMMER_HTML, SIGNED_PROGRAMMER_ROW))
        row, report, fetched, geocodes = self.scan_programmer()
        self.assertEqual(geocodes, [("Colonne", "39")])
        self.assertIn(SITE, fetched)
        self.assertEqual(fetched.count(PROGRAMMER), 1)
        self.assertTrue(row["showOnMap"])
        self.assertEqual(row["geoPrecision"], "commune")
        self.assertEqual(row["geoVerification"]["officialSite"], SITE)
        self.assertEqual(row["geoVerification"]["proofMode"],
                         "signed-city-current-edition-centre.v1")
        self.assertEqual(row["venue"], ROW["venue"])
        self.assertEqual(row["notes"], ROW["notes"])
        self.assertEqual(row["price"], ROW["price"])
        self.assertEqual(row["lineup"], [])
        self.assertTrue(_verified_official_update_delta(
            SIGNED_PROGRAMMER_ROW, row))
        self.assertEqual(report["accepted"], [ROW["slug"]])

    def test_programmer_section_strict_negatives_do_not_geocode(self):
        cases = [
            PROGRAMMER_HTML.replace("11 et 12 juin", "13 et 14 juin"),
            PROGRAMMER_HTML.replace("2027", "2026"),
            PROGRAMMER_HTML.replace(
                "Production : Mairie de Colonne",
                "Production : Mairie de Troyes"),
            PROGRAMMER_HTML.replace(
                "Prochaine édition : 11 et 12 juin 2027",
                "Prochaine édition : 11 et 12 juin 2026"),
            PROGRAMMER_HTML.replace(
                "Prochaine édition : 11 et 12 juin 2027",
                "Édition annulée : 11 et 12 juin 2027"),
            PROGRAMMER_HTML.replace(
                "<p>Prochaine édition : 11 et 12 juin 2027</p>",
                "<p>Prochaine édition : 11 et 12 juin 2027</p>"
                "<p>Autre édition : 18 et 19 juillet 2027</p>"),
            PROGRAMMER_HTML.replace(
                "<h2>Festival de la Poutre</h2>",
                "<h2>Festival de la Poutre 2026</h2>"),
        ]
        for html in cases:
            with self.subTest(html=html[:100]):
                row, _, _, calls = self.scan_programmer(partner=html)
                self.assertFalse(row["showOnMap"])
                self.assertIsNone(row["lat"])
                self.assertEqual(calls, [])

    def test_programmer_source_must_be_official_and_pre_signed(self):
        changes = [
            {"sourceConfidence": "Magazine généraliste"},
            {"auditSources": [SITE]},
            {"source": "https://inconnue.fr/programme"},
            {"department": None},
            {"city": None},
        ]
        for fields in changes:
            with self.subTest(fields=fields):
                candidate = dict(SIGNED_PROGRAMMER_ROW, **fields)
                row, _, fetched, calls = self.scan_programmer(row=candidate)
                self.assertEqual(calls, [])
                self.assertFalse(row["showOnMap"])
                self.assertNotIn(PROGRAMMER, fetched)

    def test_programmer_cannot_overrule_conflicting_organizer_dates(self):
        home = """<main><h1>Festival de la Poutre 2027</h1>
        <p>Rendez-vous les 18 et 19 juin 2027.</p></main>"""
        row, _, fetched, calls = self.scan_programmer(home=home)
        self.assertEqual(calls, [])
        self.assertFalse(row["showOnMap"])
        self.assertNotIn(PROGRAMMER, fetched)

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
