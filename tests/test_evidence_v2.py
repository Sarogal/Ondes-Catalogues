import unittest
from unittest.mock import patch
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from proof_text import verify_event,present_date,visible_time,price_is_written,age_is_written
from venue_registry import verified_location

YUMI={
"id":"montpellier-les-aventures-de-yumi-2026-11-08",
"title":"Les aventures de Yumi",
"source_url":"https://mpt.montpellier.fr/evenement/les-aventures-de-yumi",
"city":"Montpellier","venue":"Maison pour tous Marcel Pagnol",
"lat":43.60143,"lng":3.85050,
"date_start":"2026-11-08","date_end":"2026-11-08",
"time":"14:30","price":"Gratuit / sur inscription","age_min":2}
PAGE="<html><head><title>Les aventures de Yumi</title></head><body><h1>Les aventures de Yumi</h1><p>8 novembre 2026 - 14:30 &gt; 15:15</p><p>Maison pour tous Marcel Pagnol</p><p>Gratuit sur inscription. À partir de 2 ans.</p></body></html>"

class EvidenceTests(unittest.TestCase):
    def test_yumi_verified_by_official_text_and_geo(self):
        with patch("proof_text.read",return_value=(PAGE,"")):
            yes,reason=verify_event(dict(YUMI),[])
        self.assertTrue(yes,reason)

    def test_missing_date_rejected(self):
        with patch("proof_text.read",return_value=(PAGE.replace("8 novembre 2026","9 novembre 2026"),"")):
            yes,reason=verify_event(dict(YUMI),[])
        self.assertFalse(yes)

    def test_missing_age_rejected(self):
        with patch("proof_text.read",return_value=(PAGE.replace("2 ans","10 ans"),"")):
            yes,reason=verify_event(dict(YUMI),[])
        self.assertFalse(yes)

    def test_missing_price_rejected(self):
        with patch("proof_text.read",return_value=(PAGE.replace("Gratuit sur inscription","Sur rendez-vous"),"")):
            yes,reason=verify_event(dict(YUMI),[])
        self.assertFalse(yes)

    def test_wrong_venue_rejected(self):
        with patch("proof_text.read",return_value=(PAGE.replace("Maison pour tous Marcel Pagnol","Maison pour tous Voltaire"),"")):
            yes,reason=verify_event(dict(YUMI),[])
        self.assertFalse(yes)

    def test_wrong_title_rejected(self):
        with patch("proof_text.read",return_value=(PAGE.replace("Les aventures de Yumi","Une autre aventure"),"")):
            yes,reason=verify_event(dict(YUMI),[])
        self.assertFalse(yes)

    def test_far_coords_rejected_without_fetch(self):
        bad=dict(YUMI,lat=43.8,lng=3.8)
        with patch("proof_text.read",side_effect=AssertionError("network accessed")):
            self.assertFalse(verify_event(bad,[])[0])

    def test_venue_registry(self):
        self.assertTrue(verified_location(YUMI)[0])
        self.assertFalse(verified_location(dict(YUMI,city="Paris"))[0])

    def test_french_dates_leading_zero(self):
        self.assertTrue(present_date("07 Avr 2027 à 19H00","2027-04-07"))
        self.assertTrue(present_date("du 07/04/2027 au 08/04/2027","2027-04-07"))
        self.assertFalse(present_date("07 Avr 2026","2027-04-07"))

    def test_multiple_times_must_all_match(self):
        a="16 Jan 2027 11H00. 17 Jan 2027 10H00 et 11H30"
        self.assertTrue(visible_time(a,"16/01 : 11:00 ; 17/01 : 10:00 et 11:30"))
        self.assertFalse(visible_time(a,"11:00 ; 10:00 et 12:30"))

    def test_read_failure_rejected(self):
        with patch("proof_text.read",return_value=(None,"site inaccessible")):
            self.assertEqual(verify_event(dict(YUMI),[])[0],False)

if __name__=="__main__":
    unittest.main()
