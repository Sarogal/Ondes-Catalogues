"""One official edition title may prove a *commune*, never a venue entrance."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "festival-automation"))

from future_city_preflight import exact_edition_city
from grossesondes_existing_official_updates import apply_independently_verified_updates
from grossesondes_cloud_sync import _verified_official_update_delta, safe_target

SITE = "https://www.mozhell.fr/fr/"
ROW = {
    "slug": "mozhell-open-air-2027",
    "name": "MozHell Open Air 2027",
    "startDate": "2027-07-23", "endDate": "2027-07-25",
    "officialSite": SITE, "city": None,
}
TITLE = ("<head><title>MozHell Open Air - Festival Métal "
         "23 24 25 Juillet 2027 - Insming (57)</title></head>")


class FirstPartyCityTitleTests(unittest.TestCase):
    def test_realistic_2027_title_proves_only_current_commune(self):
        result = exact_edition_city(TITLE + "<main>Édition 2027</main>", ROW)
        self.assertEqual(result, {
            "slug": ROW["slug"], "city": "Insming", "source": SITE
        })

    def test_signed_official_edition_adds_indicative_pin_without_private_delay(self):
        row = {
            **ROW, "lineup": [], "bands": 0, "price": None,
            "showOnMap": False, "venue": None, "lat": None, "lon": None,
            "lastVerified": "2026-11-18", "department": "57",
        }
        signed = {"schema": 1, "generatedAt": "2026-11-18", "festivals": [row]}
        home = TITLE + (
            "<main><h1>MozHell Open Air 2027</h1>"
            "<p>Festival métal 23 24 25 juillet 2027</p></main>"
        )
        official_calls, government_calls = [], []
        def fetch(url):
            official_calls.append(url)
            return home
        def commune(city, department):
            government_calls.append((city, department))
            return {
                "city": "Insming", "lat": 48.953, "lon": 6.87,
                "codeInsee": "57346",
                "geoSource": "https://geo.api.gouv.fr/communes?nom=Insming",
            }
        next_doc, report = apply_independently_verified_updates(
            signed, signed, "2026-11-22", fetch=fetch,
            limit=1, tick=0, commune_resolver=commune)
        new = next_doc["festivals"][0]
        self.assertEqual(official_calls, [SITE])
        self.assertEqual(government_calls, [("Insming", "57")])
        self.assertEqual(report["accepted"], [ROW["slug"]])
        self.assertTrue(new["showOnMap"])
        self.assertEqual(new["city"], "Insming")
        self.assertEqual(new["geoPrecision"], "commune")
        self.assertEqual(new["geoVerification"]["markerMeaning"],
                         "centre_indicatif_de_commune")
        self.assertEqual(new["geoVerification"]["proofMode"],
                         "current-edition-commune-direct-official.v1")
        self.assertIsNone(new["venue"])
        self.assertEqual(new["lineup"], [])
        self.assertTrue(_verified_official_update_delta(row, new))
        baseline_rows = [{"slug": f"baseline-{i}"} for i in range(90)]
        baseline = {"schema": 1, "festivals": baseline_rows}
        published = {"schema": 1, "festivals": baseline_rows + [row]}
        candidate = {"schema": 1, "festivals": baseline_rows + [new]}
        self.assertTrue(safe_target(
            baseline, candidate, published,
            verified_official_updates=frozenset({ROW["slug"]})))
        forged = dict(new, venue="Supposed festival entrance")
        self.assertFalse(_verified_official_update_delta(row, forged))
        self.assertFalse(_verified_official_update_delta(
            row, dict(new, lat=-1.0)))

    def test_no_geo_without_current_edition_in_visible_first_party_content(self):
        row = {
            **ROW, "lineup": [], "bands": 0, "showOnMap": False,
            "lat": None, "lon": None,
        }
        signed = {"schema": 1, "generatedAt": "2026-11-18", "festivals": [row]}
        history = TITLE.replace("2027", "2026")
        calls = []
        out, report = apply_independently_verified_updates(
            signed, signed, "2026-11-22", fetch=lambda _: history,
            limit=1, tick=0,
            commune_resolver=lambda *args: calls.append(args))
        self.assertEqual(out, signed)
        self.assertEqual(report["accepted"], [])
        self.assertEqual(calls, [])

    def test_wrong_year_or_wrong_day_never_sets_a_pin(self):
        for title in (
            TITLE.replace("2027", "2026"),
            TITLE.replace("23 24 25", "20 21 22"),
            TITLE.replace("MozHell Open Air", "Autre Festival"),
            TITLE.replace("2027", "2026 et 2027"),
            TITLE.replace(" - Insming (57)", ""),
        ):
            with self.subTest(title=title):
                self.assertIsNone(exact_edition_city(title, ROW))

    def test_conflicting_visible_city_blocks_title_claim(self):
        html = (TITLE + "<main><p>MozHell Open Air 2027 "
                "du 23 au 25 juillet 2027 à Strasbourg.</p></main>")
        self.assertIsNone(exact_edition_city(html, ROW))


if __name__ == "__main__":
    unittest.main()
