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
    def test_theatre_nantes_registered_geo(self):
        self.assertTrue(verified_location(THEATRE)[0])
        self.assertFalse(verified_location(dict(THEATRE,lat=49.109836,lng=6.167706))[0])
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
    def test_nantes_missing_times_rejected(self):
        with patch("proof_text.read",return_value=(PAGE.replace("14h30","15h30"),"")):
            self.assertFalse(verify_event(dict(THEATRE),[])[0])

if __name__=="__main__":
    unittest.main()
