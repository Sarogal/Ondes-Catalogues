"""One official edition title may prove a *commune*, never a venue entrance."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "festival-automation"))

from future_city_preflight import exact_edition_city

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
