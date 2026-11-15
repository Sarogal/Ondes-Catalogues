"""Regression rules: Maps may help find a festival, never certify its next site."""
import unittest
from map_reference import (
    MOZHELL_MAP_URL, MOZHELL_MAP_COORDS, assess_mozhell_organizer_maps
)

FR = """<html><body><p>Le festival a lieu dans le village d'INSMING en Moselle
(57670), 5 rue de l'Albe.</p><h3>Horaires 2027</h3>
<p>Vendredi 23 juillet : 17h</p><p>Samedi 24 juillet : 13h</p>
<p>Dimanche 25 juillet : 13h</p><a href="%s">Itinéraire</a></body></html>""" % MOZHELL_MAP_URL
EN = """<html><body><p>The festival takes place in the village of INSMING
in Moselle (57670), 13 rue de l'Albe.</p>
<p>Friday; July 24 : 6:00 pm</p><p>Sunday, July 26 : 2:00 pm</p>
<a href="%s"><span>Itinerary</span></a></body></html>""" % MOZHELL_MAP_URL


class OrganizerLinkedMapsTests(unittest.TestCase):
    def test_official_poi_coordinates_do_not_claim_2027_venue(self):
        report = assess_mozhell_organizer_maps(FR, EN)
        self.assertIsNotNone(report)
        self.assertEqual(report["coordinates"]["lat"], MOZHELL_MAP_COORDS[0])
        self.assertEqual(report["coordinates"]["lon"], MOZHELL_MAP_COORDS[1])
        self.assertTrue(report["official_addresses_disagree"])
        self.assertEqual(report["addresses_private"]["fr"], "5 rue de l'Albe")
        self.assertEqual(report["addresses_private"]["en"], "13 rue de l'Albe")
        self.assertTrue(report["english_access_page_has_2026_timetable"])
        self.assertFalse(report["future_edition_exact_venue_confirmed"])
        self.assertFalse(report["publication_authorized"])

    def test_absent_link_is_not_google_evidence(self):
        self.assertIsNone(assess_mozhell_organizer_maps(
            FR.replace("Itinéraire", "Autre lieu"), EN))

    def test_fake_lookalike_domain_refused(self):
        self.assertIsNone(assess_mozhell_organizer_maps(
            FR.replace("https://www.google.com", "https://www.google.com.evil.invalid"), EN))

    def test_wrong_poi_id_refused_even_if_coordinates_match(self):
        self.assertIsNone(assess_mozhell_organizer_maps(
            FR.replace("0x61c10102323eb346", "0x0000000000000000"), EN))

    def test_different_map_marker_refused(self):
        self.assertIsNone(assess_mozhell_organizer_maps(
            FR.replace("!4d6.8717186", "!4d6.8917186"), EN))

    def test_old_edition_access_times_do_not_corroborate_2027(self):
        self.assertIsNone(assess_mozhell_organizer_maps(
            FR.replace("Vendredi 23 juillet", "Vendredi 24 juillet"), EN))

    def test_script_injection_does_not_count_as_visible_google_link(self):
        payload = ('<script><a href="' + MOZHELL_MAP_URL +
                   '">Itinéraire</a></script>')
        self.assertIsNone(assess_mozhell_organizer_maps(
            FR.replace('<a href="' + MOZHELL_MAP_URL + '">Itinéraire</a>', payload), EN))

    def test_duplicate_itinerary_links_require_manual_review(self):
        extra = '<a href="' + MOZHELL_MAP_URL + '">Itinéraire</a>'
        self.assertIsNone(assess_mozhell_organizer_maps(
            FR.replace("</body>", extra + "</body>"), EN))

    def test_no_html_or_oversized_html_rejected(self):
        self.assertIsNone(assess_mozhell_organizer_maps("", EN))
        self.assertIsNone(assess_mozhell_organizer_maps(FR, "x" * 1_400_001))


if __name__ == "__main__":
    unittest.main()
