"""Dated official price tables, without a false sale-open assertion."""
import sys
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "festival-automation"))
from grossesondes_dated_ticket_tables import dated_ticket_table_summary, parse_dated_ticket_summary
from grossesondes_existing_official_updates import apply_independently_verified_updates
from grossesondes_cloud_sync import _verified_official_update_delta

SITE = "https://festival-exemple.fr/"
DAY = "2026-11-25"
ROW = {"slug": "festival-exemple-2027", "name": "Festival Exemple 2027",
       "startDate": "2027-06-25", "endDate": "2027-06-26",
       "officialSite": SITE, "price": None, "lineup": [], "bands": 0,
       "showOnMap": False, "lat": None, "lon": None, "city": None,
       "lastVerified": "2026-11-22"}

def table(one="pas de prevente", two="18 €", normal="25 €"):
    return ("<table><tr><th>Votre pass pour le Festival Exemple</th>"
            "<th>Prévente</th><th>Après la prévente</th></tr>"
            f"<tr><td>Pass 1 jour</td><td>{one}</td><td>15 €</td></tr>"
            f"<tr><td>Pass 2 jours</td><td>{two}</td><td>{normal}</td></tr>"
            "<tr><td>Moins de 12 ans (accompagné, entrée sans pass)</td>"
            "<td>Gratuit</td><td>Gratuit</td></tr></table>")

ANNOUNCE = ("<p>Le Festival Exemple revient les 25 et 26 juin 2027 !</p>"
            "<p>Les préventes seront disponibles à partir du 12 décembre 2026.</p>")
OLD = table("13 €", "15 €", "22 €")
MOBILE = ("<table><tr><th>Votre pass pour le Festival Exemple</th><th>Prévente</th></tr>"
          "<tr><td>Pass 1 jour</td><td>pas de prevente</td></tr>"
          "<tr><td>Pass 2 jours</td><td>18 €</td></tr>"
          "<tr><td>Moins de 12 ans (accompagné)</td><td>Gratuit</td></tr></table>")
HTML = "<main>" + OLD + ANNOUNCE + table() + MOBILE + "</main>"

class DatedGridTests(unittest.TestCase):
    def test_mixed_year_and_responsive_tables(self):
        result = dated_ticket_table_summary(HTML, ROW, DAY)
        self.assertIn("12/12/2026", result)
        self.assertIn("pas de prévente", result)
        self.assertIn("prévente 18 €", result)
        self.assertIn("après prévente 25 €", result)
        self.assertIn("Moins de 12 ans accompagnés : gratuit", result)
        self.assertNotIn("22 €", result)
        self.assertNotIn("officielle ouverte", result)
        self.assertIsNotNone(parse_dated_ticket_summary(result))

    def test_conflict_wrong_edition_missing_opening_and_partial_grid(self):
        for html in (
            HTML.replace("25 et 26 juin 2027", "26 et 27 juin 2027"),
            HTML.replace("25 et 26 juin 2027", "25 et 26 juin 2026"),
            HTML.replace("12 décembre 2026", "12 décembre 2027"),
            HTML.replace("seront disponibles", "pourraient être disponibles"),
            OLD + ANNOUNCE + table() + MOBILE.replace("18 €", "19 €"),
            ANNOUNCE + MOBILE,
            OLD,
            ANNOUNCE + "<div hidden>" + table() + "</div>",
        ):
            with self.subTest(html=html[:100]):
                self.assertIsNone(dated_ticket_table_summary(html, ROW, DAY))

    def test_publisher_updates_without_claiming_open_sales(self):
        signed = {"schema": 1, "generatedAt": DAY, "festivals": [ROW]}
        out, report = apply_independently_verified_updates(
            signed, signed, DAY, fetch=lambda _: HTML,
            commune_resolver=lambda *_: None, limit=1, tick=0)
        new = out["festivals"][0]
        self.assertEqual(new["price"], dated_ticket_table_summary(HTML, ROW, DAY))
        self.assertTrue(_verified_official_update_delta(ROW, new))
        self.assertEqual(report["accepted"], [ROW["slug"]])
        self.assertFalse(_verified_official_update_delta(
            new, dict(new, price="Pass 1 jour : 20 € — billetterie officielle ouverte")))
        self.assertFalse(_verified_official_update_delta(
            new, dict(new, price=new["price"].replace("12/12/2026", "12/12/2027"))))
        refreshed = HTML.replace("18 €", "19 €")
        updated, report = apply_independently_verified_updates(
            out, out, DAY, fetch=lambda _: refreshed,
            commune_resolver=lambda *_: None, limit=1, tick=0)
        self.assertIn("prévente 19 €", updated["festivals"][0]["price"])

if __name__ == "__main__":
    unittest.main()
