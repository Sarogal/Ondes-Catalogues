"""Offline current-edition tariff contracts."""
import unittest
from test_grosses_existing_official_updates import festival, doc, DAY, _verified_official_update_delta
from grossesondes_announced_tariffs import announced_tariffs, parse_announced_tariffs
from grossesondes_existing_official_updates import apply_independently_verified_updates
from future_city_preflight import exact_edition_city

SITE = "https://festival-exemple.fr/"
ROW = festival("festival-exemple", SITE, dates=("2027-02-06","2027-02-07"))
ROW.update(name="Festival Exemple 2027", city="Colonne")
HEAD = "<main><h1>Festival Exemple</h1><p>Festival Exemple revient les 6 et 7 février 2027 à Colonne.</p>"
LIST = HEAD + ("<h3>Tarifs</h3><ul><li>Pass 2 jours : à partir de 81€</li>"
               "<li>Pass samedi : 48€</li><li>Pass dimanche : 48€</li></ul></main>")
CARDS = HEAD + ("<h2>Billetterie</h2><h2>Pass 1 jour</h2><h2>30€</h2>"
    "<p>33€ sur place</p><p>Gratuit -12 ans</p><a>Je réserve</a>"
    "<h2>Pass 2 jours</h2><h2>50€</h2><p>55€ sur place</p>"
    "<p>Gratuit -12 ans</p><a>Je réserve</a></main>")

class AnnouncedTariffsTests(unittest.TestCase):
    def read(self, html):
        return announced_tariffs(html, ROW, DAY, exact_edition_city)

    def test_exact_weekend_list_and_unqualified_tariff_cards(self):
        self.assertEqual(self.read(LIST), "Tarifs annoncés — Pass 2 jours : dès 81 € ; Pass samedi : 48 € ; Pass dimanche : 48 €")
        self.assertEqual(self.read(CARDS), "Tarifs annoncés — Pass 1 jour : 30 €, sur place 33 € ; Pass 2 jours : 50 €, sur place 55 € ; Moins de 12 ans : gratuit")
        for html in (LIST, CARDS):
            summary = self.read(html)
            self.assertIsNotNone(parse_announced_tariffs(summary, ROW))
            self.assertNotIn("billetterie officielle ouverte", summary)
            self.assertTrue(_verified_official_update_delta(ROW, dict(ROW, price=summary)))
        original = doc(ROW)
        out, report = apply_independently_verified_updates(original, original, DAY,
            fetch=lambda _: LIST, limit=1, tick=0, commune_resolver=lambda *_: None)
        self.assertEqual(out["festivals"][0]["price"], self.read(LIST))
        self.assertEqual(report["accepted"], [ROW["slug"]])

    def test_reject_wrong_edition_conflicts_hidden_and_wrong_weekday(self):
        for bad in (LIST.replace("2027", "2026"),
                    LIST.replace("Pass samedi", "Pass lundi"),
                    LIST.replace("<h3>Tarifs", "<h3 hidden>Tarifs"),
                    LIST.replace("<h3>Tarifs", "<h3>Tarifs 2026"),
                    LIST.replace("<h3>Tarifs", "<p>10 et 11 février 2027</p><h3>Tarifs"),
                    LIST.replace("Pass dimanche", "Pass samedi"),
                    CARDS.replace("33€ sur place", "33€ épuisé")):
            self.assertIsNone(self.read(bad), bad)
        price = self.read(LIST)
        self.assertFalse(_verified_official_update_delta(dict(ROW, price=price),
            dict(ROW, price="Tarifs annoncés — Pass samedi : 48 €")))
        self.assertFalse(_verified_official_update_delta(ROW,
            dict(ROW, price="Tarifs annoncés — Pass lundi : 48 €")))
        self.assertFalse(_verified_official_update_delta(dict(ROW, price="Autre tarif"),
            dict(ROW, price=price)))

if __name__ == "__main__":
    unittest.main()
