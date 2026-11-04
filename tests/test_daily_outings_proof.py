import unittest
from unittest.mock import patch
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from proof_text import verify_event,consecutive_official_dates,age_is_written
from venue_registry import verified_location

THEATRE={
 "id":"nantes-fourmi-de-pain-2027-04-25",
 "title":"Fourmi de pain","source_url":"https://www.theatre-jeanne.com/spectacle/fourmi-de-pain/2027-04-25/",
 "city":"Nantes","venue":"Théâtre de Jeanne","lat":47.20457,"lng":-1.57551,
 "date_start":"2027-04-25","date_end":"2027-05-02",
 "time":"25/04 et 02/05 : 15:00 ; 26 au 30/04 : 14:30 ; 01/05 : 16:00",
 "age_min":2,"age_max":8,
 "price":"10 € enfant (18 mois–11 ans) / 12 € adulte, hors frais de réservation"
}
PAGE=("<html><title>Fourmi de pain - Théâtre de Jeanne</title>"
 "<h1>FOURMI DE PAIN</h1><p>Théâtre de Jeanne - Nantes</p>"
 "<p>Conseillé de 2 à 8 ans</p><p>VACANCES PRINTEMPS 2027</p>"
 "<p>DU 25 AVRIL AU 2 MAI</p>"
 "<p>Les dimanches 25 avril et 2 mai à 15h</p>"
 "<p>Du lundi 26 au vendredi 30 avril à 14h30</p>"
 "<p>Samedi 1er mai à 16h</p>"
 "<p>Tarif âge 18 mois à 11 ans 10 €, Tarif 12 ans à adultes 12 €</p></html>")
PARIS={
 "id":"paris-sur-les-pas-de-simeon-2027-02-28",
 "title":"Sur les pas de Siméon",
 "source_url":"https://philharmoniedeparis.fr/fr/activite/atelier-concert-pour-les-tout-petits/29702-sur-les-pas-de-simeon",
 "city":"Paris","venue":"Philharmonie de Paris – Salle de conférence",
 "lat":48.89191,"lng":2.39419,
 "date_start":"2027-02-28","date_end":"2027-02-28",
 "time":"09:30, 10:30 et 11:30",
 "age_min":0.25,"age_max":3,"price":"12 € enfant / 16 € adulte",
}
PARIS_PAGE=("<html><title>Sur les pas de Siméon</title><h1>Sur les pas de Siméon</h1>"
 "<p>28 Fév 09h30, 28 Fév 10h30, 28 Fév 11h30</p>"
 "<p>De 3 mois à 3 ans ; Salle de conférence - Philharmonie</p></html>")
PARIS_AGENDA=("<html><h1>Atelier-concert pour les tout-petits</h1>"
 "<p>Dimanche 28 février 2027 09h30 Sur les pas de Siméon</p>"
 "<p>Salle de conférence - Philharmonie</p><p>12 € Enfant | 16 € Adulte</p></html>")

class DailyProofTests(unittest.TestCase):
    def test_openagenda_explicit_session_under_month_heading(self):
        from proof_text import official_openagenda_explicit_month_day
        event = {
            "source_url": "https://openagenda.com/nantesmetropole/events/77081258_jeune-public",
            "date_start": "2027-02-10", "date_end": "2027-02-10",
            "time": "14:30",
        }
        page = "Février 2027 Mercredi 10 14:30 - 15:20 Dimanche 14 15:00 - 15:50"
        self.assertTrue(official_openagenda_explicit_month_day(event, page))
        self.assertFalse(official_openagenda_explicit_month_day(
            dict(event, date_start="2027-02-11", date_end="2027-02-11"), page))
        self.assertFalse(official_openagenda_explicit_month_day(
            dict(event, time="15:00"), page))
        self.assertFalse(official_openagenda_explicit_month_day(
            dict(event, source_url="https://example.net/foo"), page))
        self.assertFalse(official_openagenda_explicit_month_day(
            event, page.replace("Février 2027", "Février 2026")))
        self.assertFalse(official_openagenda_explicit_month_day(
            dict(event, date_end="2027-02-14"), page))
        self.assertFalse(official_openagenda_explicit_month_day(
            event, page.replace("Mercredi 10", "Jeudi 10")))

    def test_exact_openagenda_month_day_with_independent_venue(self):
        event = {
            "source_url": "https://openagenda.com/nantesmetropole/events/77081258_jeune-public",
            "title": "Un animal, des amis mots",
            "date_start": "2027-02-10", "date_end": "2027-02-10",
            "time": "14:30", "city": "Nantes", "venue": "Théâtre de Jeanne",
            "lat": 47.20457, "lng": -1.57551,
        }
        source = ("<html><head><title>Un animal, des amis mots</title></head>"
                  "<body><h1>Un animal, des amis mots</h1>"
                  "<p>Théâtre de Jeanne, Nantes</p>"
                  "<h2>Février 2027</h2><p>Mercredi 10</p>"
                  "<p>14:30 - 15:20</p><p>Dimanche 14</p>"
                  "<p>15:00 - 15:50</p></body></html>")
        with patch("proof_text.read", return_value=(source, "")):
            ok, reason = verify_event(event, [])
        self.assertTrue(ok, reason)
        with patch("proof_text.read", return_value=(source.replace("14:30", "16:30"), "")):
            self.assertFalse(verify_event(event, [])[0])
        with patch("proof_text.read", return_value=(source.replace("Mercredi 10", "Mercredi 11"), "")):
            self.assertFalse(verify_event(event, [])[0])

    def test_theatre_nantes_registered_geo(self):
        self.assertTrue(verified_location(THEATRE)[0])
        self.assertFalse(verified_location(dict(THEATRE,lat=49.109836,lng=6.167706))[0])
    def test_new_independently_mapped_venues(self):
        locations = [
            ("Montpellier", "Maison pour tous Rosa Parks", 43.63367, 3.83351),
            ("Montpellier", "Maison pour tous George Sand", 43.61888, 3.89398),
            ("Montpellier", "Maison pour tous Michel Colucci", 43.5937, 3.84013),
            ("Le Haillan", "L'Entrepôt", 44.8743, -0.677071),
            ("Versailles", "Hôtel des Menus-Plaisirs", 48.8005798, 2.1338217),
        ]
        for city, venue, lat, lng in locations:
            e = {"city": city, "venue": venue, "lat": lat, "lng": lng}
            self.assertTrue(verified_location(e)[0], (city, venue))
            self.assertFalse(verified_location(dict(e, lat=lat + 0.2))[0])

    def test_2026_11_02_venue_points_accept_only_confirmed_coordinates(self):
        cases = [
            ("Goussainville", "Médiathèque municipale François Mauriac",
             49.0355, 2.461),
            ("Cabriès", "Auditorium Pierre Malbosc",
             43.440834, 5.381883),
        ]
        for city, venue, lat, lng in cases:
            place = {"city": city, "venue": venue, "lat": lat, "lng": lng}
            self.assertTrue(verified_location(place)[0], place)
            self.assertFalse(verified_location(dict(place, lng=lng + 0.01))[0])
        # The old Goussainville GPS was ~220 m away from the official library.
        self.assertFalse(verified_location({
            "city": "Goussainville", "venue": "Médiathèque municipale François Mauriac",
            "lat": 49.035198, "lng": 2.45797})[0])


    def test_openagenda_calendar_dates_under_month_headings(self):
        from proof_text import official_openagenda_grouped_day
        common={
          "source_url":"https://openagenda.com/fr/lecture-publique/events/5049582_eveil-musical-1255167",
          "date_start":"2026-11-28","date_end":"2026-11-28"}
        html=("Eveil musical Novembre 2026 Samedi 28 11:00 - 12:00 "
              "Décembre 2026 Samedi 19 11:00 - 12:00")
        self.assertTrue(official_openagenda_grouped_day(common,html))
        self.assertTrue(official_openagenda_grouped_day(
            dict(common,date_start="2026-12-19",date_end="2026-12-19"),html))
        self.assertFalse(official_openagenda_grouped_day(
            dict(common,date_start="2026-11-21",date_end="2026-11-21"),html))
        self.assertFalse(official_openagenda_grouped_day(
            common,html.replace("Novembre 2026","Novembre 2025")))
        self.assertFalse(official_openagenda_grouped_day(
            dict(common,source_url="https://example.org/"),html))

    def test_openagenda_0_to_6_age_range_verified(self):
        e = {"age_min":0,"age_max":6}
        self.assertTrue(age_is_written(e,"Sur inscription, de 0-6 ans, accompagnés de leurs parents."))
        self.assertFalse(age_is_written(e,"Sur inscription, de 2-6 ans, accompagnés."))
        self.assertFalse(age_is_written({"age_min":0,"age_max":8},
                       "Sur inscription, de 0-6 ans, accompagnés."))

    def test_openagenda_recurrence_full_independent_proof(self):
        from proof_text import verify_event
        venue={
          "city":"Goussainville","venue":"Médiathèque municipale François Mauriac",
          "lat":49.0355,"lng":2.461,"title":"Éveil musical",
          "source_url":"https://openagenda.com/fr/lecture-publique/events/5049582_eveil-musical-1255167",
          "time":"11:00–12:00","date_start":"2026-11-28",
          "date_end":"2026-11-28","age_min":0,"age_max":6}
        page=("<html><head><title>Éveil musical | Médiathèques de Roissy</title></head>"
              "<body><h1>Éveil musical</h1><h2>Novembre 2026</h2>"
              "<p>Samedi 28</p><p>11:00 - 12:00</p>"
              "<h2>Décembre 2026</h2><p>Samedi 19</p><p>11:00 - 12:00</p>"
              "<p>Médiathèque municipale François Mauriac, Goussainville</p>"
              "<p>Sur inscription, de 0-6 ans, accompagnés de leurs parents.</p></body></html>")
        with patch("proof_text.read",return_value=(page,"")):
            ok,reason=verify_event(venue,[])
        self.assertTrue(ok,reason)


    def test_versailles_monthly_session_requires_exact_year_and_day(self):
        from proof_text import official_versailles_monthly_session, VERSAILLES_BEBE_BAROQUE_URL
        event={"source_url":VERSAILLES_BEBE_BAROQUE_URL,
               "date_start":"2026-12-16", "date_end":"2026-12-16"}
        html=("Bébé baroque Décembre 2026 Mercredi 16 "
              "09:30 - 10:15 10:30 - 11:15")
        self.assertTrue(official_versailles_monthly_session(event,html))
        self.assertFalse(official_versailles_monthly_session(event,html.replace("2026","2025")))
        self.assertFalse(official_versailles_monthly_session(event,html.replace("16","18")))
        self.assertFalse(official_versailles_monthly_session(
            dict(event,source_url="https://openagenda.com/fr/other"),html))
        self.assertFalse(official_versailles_monthly_session(
            dict(event,date_start="2026-11-18",date_end="2026-11-18"),html))

    def test_versailles_official_age_phrase(self):
        self.assertTrue(age_is_written({"age_min":0,"age_max":3},"De 0 à 3 ans"))
        self.assertFalse(age_is_written({"age_min":0,"age_max":3},"De 1 à 3 ans"))
        self.assertFalse(age_is_written({"age_min":0,"age_max":4},"De 0 à 3 ans"))

    def test_versailles_full_source_including_prices_and_times(self):
        from proof_text import VERSAILLES_BEBE_BAROQUE_URL
        event={
            "source_url":VERSAILLES_BEBE_BAROQUE_URL,
            "title":"Bébé baroque : atelier musical pour les tout-petits",
            "city":"Versailles", "venue":"Hôtel des Menus-Plaisirs",
            "lat":48.8005798, "lng":2.1338217,
            "date_start":"2026-12-16", "date_end":"2026-12-16",
            "time":"09:30 et 10:30 (45 min par séance)",
            "price":"15 € pour 1 enfant et 1 accompagnateur (tarifs réduits possibles)",
            "age_min":0,"age_max":3
        }
        html=("<html><head><title>Bébé baroque : atelier musical pour les tout-petits</title></head>"
              "<body><h1>Bébé baroque : atelier musical pour les tout-petits</h1>"
              "<h2>Décembre 2026</h2><p>Mercredi 16</p>"
              "<p>09:30 - 10:15</p><p>10:30 - 11:15</p>"
              "<p>15 € pour 1 enfant + 1 accompagnateur</p>"
              "<p>De 0 à 3 ans</p><p>Hôtel des Menus-Plaisirs</p></body></html>")
        with patch("proof_text.read",return_value=(html,"")):
            ok,reason=verify_event(event,[])
        self.assertTrue(ok,reason)
        with patch("proof_text.read",return_value=(html.replace("Décembre 2026","Décembre 2025"),"")):
            self.assertFalse(verify_event(event,[])[0])

    def test_nantes_same_month_series(self):
        self.assertTrue(consecutive_official_dates(
            "VACANCES PRINTEMPS 2027 DU 17 AU 24 AVRIL",
            "2027-04-17","2027-04-24"))
    def test_nantes_two_month_series(self):
        self.assertTrue(consecutive_official_dates(
            "VACANCES PRINTEMPS 2027 DU 25 AVRIL AU 2 MAI",
            "2027-04-25","2027-05-02"))
    def test_wrong_year_series_rejected(self):
        self.assertFalse(consecutive_official_dates(
            "VACANCES PRINTEMPS 2026 DU 25 AVRIL AU 2 MAI",
            "2027-04-25","2027-05-02"))
    def test_nonconsecutive_series_rejected(self):
        self.assertFalse(consecutive_official_dates(
            "VACANCES PRINTEMPS 2027 DU 25 AVRIL AU 2 MAI",
            "2027-04-25","2027-05-12"))
    def test_nantes_full_evidence(self):
        with patch("proof_text.read",return_value=(PAGE,"")):
            ok,reason=verify_event(dict(THEATRE),[])
        self.assertTrue(ok,reason)
    def test_nantes_age_range_parsing(self):
        self.assertTrue(age_is_written(THEATRE,"Conseillé de 2 à 8 ans"))
        self.assertFalse(age_is_written(THEATRE,"Conseillé de 4 à 8 ans"))
    def test_minimum_age_of_one_year_can_be_stated_as_twelve_months(self):
        e = {"age_min": 1}
        self.assertTrue(age_is_written(e, "Tout-petits à partir de 12 mois"))
        self.assertFalse(age_is_written(e, "Tout-petits à partir de 6 mois"))
        self.assertFalse(age_is_written({"age_min": 2}, "Tout-petits à partir de 12 mois"))

    def test_paris_fallback_with_strong_official_agenda(self):
        def page(url):
            return (PARIS_AGENDA if "/agenda-selection/" in url else PARIS_PAGE,"")
        with patch("proof_text.read",side_effect=page):
            ok,reason=verify_event(dict(PARIS),[])
        self.assertTrue(ok,reason)
    def test_paris_fallback_not_on_other_year(self):
        def page(url):
            if "/agenda-selection/" in url:
                return PARIS_AGENDA.replace("2027","2026"),""
            return PARIS_PAGE,""
        with patch("proof_text.read",side_effect=page):
            self.assertFalse(verify_event(dict(PARIS),[])[0])
    def test_paris_fallback_must_have_12_and_16_prices(self):
        def page(url):
            if "/agenda-selection/" in url:
                return PARIS_AGENDA.replace("16 €","15 €"),""
            return PARIS_PAGE,""
        with patch("proof_text.read",side_effect=page):
            self.assertFalse(verify_event(dict(PARIS),[])[0])
    def test_js_only_openagenda_is_explicitly_deferred(self):
        event = {
            "title": "Éveil musical", "city": "Goussainville",
            "venue": "Médiathèque municipale François Mauriac",
            "lat": 49.0355, "lng": 2.461,
            "source_url": "https://openagenda.com/fr/lecture-publique/events/5049582_eveil-musical-1255167",
            "date_start": "2026-11-28", "date_end": "2026-11-28",
            "time": "11:00"
        }
        html = ('<html><title>Éveil musical | OpenAgenda</title>'
                '<body><main><p>Loading...</p></main></body></html>')
        with patch("proof_text.read", return_value=(html, "")):
            ok, reason = verify_event(event, [])
        self.assertFalse(ok)
        self.assertIn("dynamique", reason)
        self.assertIn("JavaScript", reason)

    def test_real_official_openagenda_session_not_rejected_as_loading(self):
        event = {
            "title": "Éveil musical", "city": "Goussainville",
            "venue": "Médiathèque municipale François Mauriac",
            "lat": 49.0355, "lng": 2.461,
            "source_url": "https://openagenda.com/fr/lecture-publique/events/5049582_eveil-musical-1255167",
            "date_start": "2026-11-28", "date_end": "2026-11-28",
            "time": "11:00"
        }
        html = ('<html><title>Éveil musical | OpenAgenda</title>'
                '<h1>Éveil musical</h1><p>Novembre 2026 Samedi 28</p>'
                '<p>11:00 - 12:00</p>'
                '<p>Médiathèque municipale François Mauriac à Goussainville</p>'
                '<p>Some loading placeholder follows later.</p></html>')
        with patch("proof_text.read", return_value=(html, "")):
            ok, reason = verify_event(event, [])
        self.assertTrue(ok, reason)

    def test_nantes_missing_times_rejected(self):
        with patch("proof_text.read",return_value=(PAGE.replace("14h30","15h30"),"")):
            self.assertFalse(verify_event(dict(THEATRE),[])[0])

if __name__=="__main__":
    unittest.main()
