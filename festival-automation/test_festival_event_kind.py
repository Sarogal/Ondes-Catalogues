"""Touring-concert safeguard shared by national preflight and publisher."""
from datetime import date
from pathlib import Path
import sys
from unittest import TestCase, main
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from festival_event_kind import touring_concert_stop
from national_institutional_edition_preflight import _exact_edition
from grossesondes_institutional_linked_edition import prove_dates

DAY = "2026-11-21"
SINGLE = date(2027, 2, 12)
FESTIVAL = (
    "<main><h1>Shred Fest 2027</h1>"
    "<p>Le SHRED FEST est un concept de festival itinérant annuel "
    "dans le monde entier, 39 concerts sans aucun jour de repos. "
    "Limoges, le 12 février 2027.</p></main>"
)
REGULAR = (
    "<main><h1>Festival des Nuits de Fer 2027</h1>"
    "<p>Concerts métal et punk le 12 février 2027 ; sur une scène "
    "unique. Un artiste vient de terminer sa tournée.</p></main>"
)


class TouringConcertStopTests(TestCase):
    def test_realistic_single_day_touring_stop_rejected(self):
        self.assertTrue(touring_concert_stop(FESTIVAL, SINGLE, SINGLE))

    def test_ordinary_one_day_festival_survives_artist_tour_mentions(self):
        self.assertFalse(touring_concert_stop(REGULAR, SINGLE, SINGLE))

    def test_multi_day_itinerant_festival_does_not_get_broadly_blocked(self):
        self.assertFalse(touring_concert_stop(
            FESTIVAL, SINGLE, date(2027, 2, 13)))

    def test_hidden_touring_claims_cannot_reclassify_festival(self):
        html = (REGULAR + "<script>" + FESTIVAL + "</script>"
                + '<div hidden>festival itinerant 39 concerts</div>')
        self.assertFalse(touring_concert_stop(html, SINGLE, SINGLE))

    def test_edition_prefilter_rejects_touring_stop_even_with_dates(self):
        source = {"title": "Shred Fest 2027", "year": 2027}
        with patch("national_institutional_edition_preflight.official_date",
                   return_value=(SINGLE, SINGLE)):
            self.assertIsNone(_exact_edition(FESTIVAL, source, DAY))
        with patch("national_institutional_edition_preflight.official_date",
                   return_value=(SINGLE, SINGLE)):
            self.assertEqual(_exact_edition(REGULAR, {
                "title": "Festival des Nuits de Fer 2027", "year": 2027
            }, DAY), (SINGLE.isoformat(), SINGLE.isoformat()))

    def test_publisher_independently_rejects_touring_stop(self):
        with patch("grossesondes_institutional_linked_edition.institutional_date",
                   return_value=(SINGLE, SINGLE)):
            self.assertIsNone(prove_dates(FESTIVAL, "Shred Fest 2027", 2027, DAY))
        with patch("grossesondes_institutional_linked_edition.institutional_date",
                   return_value=(SINGLE, SINGLE)):
            self.assertEqual(prove_dates(
                REGULAR, "Festival des Nuits de Fer 2027", 2027, DAY),
                (SINGLE.isoformat(), SINGLE.isoformat()))


if __name__ == "__main__":
    main()
