"""Tests offline des liens Drupal et ICS de La Malterie."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import malterie_adapter as m

BASE="https://www.lamalterie.com/agenda/Concert/liste"
VENUE={"name":"La Malterie","city":"Lille","department":"59","url":BASE}

class MalterieTests(unittest.TestCase):
    def test_liens_officiels_seulement(self):
        html=(
            '<a href="/fr/evenement/3713/ical">Krallice</a>'
            '<a href="https://lamalterie.com/fr/evenement/3713/ical">Doublon</a>'
            '<a href="https://evil.example/fr/evenement/4/ical">Non</a>'
            '<a href="/fr/evenement/4555/ical">Fange</a>'
            '<a href="/agenda/Concert/liste">Non</a>'
            '<a href="/fr/evenement/9999/ical?redirect=x">Non</a>'
        )
        urls=m.ics_event_urls(html,BASE)
        self.assertEqual(len(urls),2)
        self.assertEqual(urls[0],"https://www.lamalterie.com/fr/evenement/3713/ical")
        self.assertEqual(urls[1],"https://www.lamalterie.com/fr/evenement/4555/ical")

    def test_ical_exactement_un_evenement(self):
        ics=("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:event3713\n"
             "SUMMARY:KRALLICE + FANGE\n"
             "DTSTART;TZID=Europe/Paris:20261104T200000\n"
             "LOCATION:La Malterie, Lille\nEND:VEVENT\nEND:VCALENDAR")
        rows=m.event_records(ics,"https://www.lamalterie.com/fr/evenement/3713/ical",
                             VENUE,"2026-11-01")
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["date"],"2026-11-04")
        self.assertEqual(rows[0]["source"],"agenda_officiel_malterie_ical")
        self.assertFalse(rows[0]["publicationAllowed"])
        self.assertTrue(rows[0]["venueToConfirm"])

    def test_ical_vide_refuse(self):
        self.assertEqual(m.event_records("BEGIN:VCALENDAR\nEND:VCALENDAR",BASE,VENUE,"2026-11-01"),[])

    def test_multiple_vevent_refuse_ambigu(self):
        body=("BEGIN:VCALENDAR\n"
              "BEGIN:VEVENT\nSUMMARY:ABC\nDTSTART:20261104T200000\nEND:VEVENT\n"
              "BEGIN:VEVENT\nSUMMARY:DEF\nDTSTART:20261105T200000\nEND:VEVENT\n"
              "END:VCALENDAR")
        self.assertEqual(m.event_records(body,BASE,VENUE,"2026-11-01"),[])

    def test_repli_liste_dates_et_genres(self):
        page = (
            '<h2>Concerts</h2>'
            '<h2>[Muzzix] LUN19h | Dérive</h2>'
            '<p>lundi 23 novembre 2026 / 19h00 par Muzzix</p>'
            '<h2><a href="/evenement/concert/krallice-fange">KRALLICE (us-black metal) + FANGE (metal indus)</a></h2>'
            '<p>mercredi 4 novembre 2026 - 20h00 / 23h30</p>'
            '<p>Billetterie</p>'
            '<h2>Release party Deûle (synth doom) + ANA IESU (indus black)</h2>'
            '<p>vendredi 6 novembre 2026 / 20h00</p>'
        )
        rows=m.list_fallback_candidates(page,BASE,VENUE,"2026-11-01")
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]["date"],"2026-11-04")
        self.assertIn("/evenement/concert/krallice-fange",rows[0]["sourceUrl"])
        self.assertEqual(rows[1]["date"],"2026-11-06")
        self.assertTrue(all(x["publicationAllowed"] is False for x in rows))

    def test_repli_pas_de_date_supposee(self):
        page='<h2>FANGE (metal)</h2><p>mercredi 4 novembre / 20h</p>'
        self.assertEqual(m.list_fallback_candidates(page,BASE,VENUE,"2026-11-01"),[])

    def test_fiche_officielle_krallice_fange(self):
        sample = (
          '<body><h2>Cerbère Coryphée présente :<br/>'
          'KRALLICE <sup>us-black metal</sup><br/>'
          '+ FANGE <sup>fr-metal indus</sup></h2>'
          '<p>mercredi 4 novembre 2026 - 20h00 / 23h30</p>'
          '</body>'
        )
        url="https://www.lamalterie.com/evenement/concert/krallice-fange"
        rows=m.list_fallback_candidates(sample,url,VENUE,"2026-11-01")
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["date"],"2026-11-04")
        self.assertEqual(rows[0]["sourceUrl"],url)
        self.assertIn("KRALLICE",rows[0]["name"])

    def test_fiche_html_avec_br_non_ferme(self):
        body=(
            '<h2>Cerbère Coryphée présente :<br>'
            'KRALLICE <sup>us-black metal</sup><br>'
            '+ FANGE <sup>fr-metal indus</sup></h2>'
            '<p>mercredi 4 novembre 2026 - 20h00</p>'
        )
        result=m.list_fallback_candidates(
            body,"https://www.lamalterie.com/evenement/concert/krallice",
            VENUE,"2026-11-01")
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]["date"],"2026-11-04")

    def test_urls_fiches_et_securite(self):
        body=(
          '<a href="/evenement/concert/krallice-fange">A</a>'
          '<a href="https://evil.example/evenement/concert/other">Bad</a>'
          '<a href="/evenement/concert/krallice-fange#comments">Duplicate</a>'
          '<a href="/evenement/concert/release-party-deule">B</a>'
          '<a href="/fr/evenement/3713/ical">ICS not a detail</a>'
        )
        urls=m.detail_urls(body,BASE)
        self.assertEqual(len(urls),2)
        self.assertEqual(urls[0],"https://www.lamalterie.com/evenement/concert/krallice-fange")

    def test_date_passee_refusee(self):
        body=("BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:KRALLICE\nDTSTART:20251004T200000"
              "\nEND:VEVENT\nEND:VCALENDAR")
        self.assertEqual(m.event_records(body,BASE,VENUE,"2026-11-01"),[])

if __name__=="__main__":
    unittest.main()
