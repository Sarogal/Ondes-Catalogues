"""CINOR/Outre-mer: fail-closed contract for ODS evidence, no publications."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_candidate_promotion import (
    FIELDS, verified_french_country, reconciled_openagenda_url, make_event,
)

FIRST_PARTY = ("https://openagenda.com/fr/reseau-des-mediatheques-cinor/"
               "events/55943123_activite-manuelle-8019889")
ODS_CANONICAL = ("https://openagenda.com/office-de-tourisme-intercommunal-"
                 "du-nord-de-la-reunion/events/activite-manuelle-8019889")


def cinor_row(**overrides):
    row = {
        "uid": "55943123", "title_fr": "Activité manuelle",
        "description_fr": "Réalisation d’un calendrier de l’avent sapin avec Marie-Pierre.",
        "canonicalurl": ODS_CANONICAL,
        "location_city": "Saint-Denis",
        "location_name": "Bibliothèque Intercommunale Alain Lorraine",
        "location_department": "La Réunion",
        "location_region": "La Réunion",
        "location_countrycode": "RE",
        "location_coordinates": {"lat": -20.892702, "lon": 55.451302},
        "originagenda_title": "Réseau de Lecture Publique de la CINOR",
        "originagenda_uid": "9278749",
        "timings": [{"begin": "2026-11-18T14:00:00+04:00",
                     "end": "2026-11-18T16:00:00+04:00"}],
        "status": {"id": 1},
        "age_min": 6, "age_max": 8, "conditions_fr": "Sur inscription",
    }
    row.update(overrides)
    return row


def cinor_lead(**overrides):
    l = {
        "collector": "openagenda-v2", "external_id": "55943123",
        "title": "Activité manuelle", "city": "Saint-Denis",
        "venue": "Bibliothèque Intercommunale Alain Lorraine",
        "date_start": "2026-11-18", "date_end": "2026-11-18",
        "source_url": FIRST_PARTY,
    }
    l.update(overrides)
    return l


class OverseasCountryAndCinorAliasTests(unittest.TestCase):
    def test_real_cinor_country_location_is_verified(self):
        self.assertTrue(verified_french_country(cinor_row()))
        self.assertIn("originagenda_uid", FIELDS.split(","))

    def test_five_french_departments_require_matching_region_and_department(self):
        examples = [
            ("GP", "Guadeloupe"), ("MQ", "Martinique"),
            ("GF", "Guyane"), ("RE", "La Réunion"), ("YT", "Mayotte"),
        ]
        for code, name in examples:
            with self.subTest(code=code):
                self.assertTrue(verified_french_country(
                    cinor_row(location_countrycode=code,
                              location_region=name, location_department=name)))
                self.assertFalse(verified_french_country(
                    cinor_row(location_countrycode=code,
                              location_region="Occitanie", location_department=name)))
                self.assertFalse(verified_french_country(
                    cinor_row(location_countrycode=code,
                              location_region=name, location_department="Hérault")))

    def test_foreign_and_other_codes_not_admitted(self):
        for code in ("US", "BE", "MG", "FRANCE", "FRA", "PF", "PM", "NC",
                     "WF", "BL", "MF", "re", "", None, "RE-EVIL"):
            with self.subTest(country=code):
                self.assertFalse(verified_french_country(
                    cinor_row(location_countrycode=code)))
        self.assertTrue(verified_french_country(
            cinor_row(location_countrycode="FR",
                      location_department="Hérault", location_region="Occitanie")))

    def test_verified_ods_alias_returns_original_pinned_cinor_page(self):
        self.assertEqual(
            reconciled_openagenda_url(cinor_lead(), cinor_row()),
            FIRST_PARTY)

    def test_ods_alias_requires_exact_uid_origin_urls_and_library(self):
        bad_rows = (
            {"originagenda_uid": "40287481"},
            {"originagenda_uid": "55943123"},
            {"originagenda_title": "Un autre réseau"},
            {"canonicalurl": ODS_CANONICAL + "-bad"},
            {"location_city": "Paris"},
            {"location_name": "Une autre bibliothèque"},
            {"title_fr": "Concert de musique"},
        )
        for modified in bad_rows:
            with self.subTest(modified=modified):
                with self.assertRaisesRegex(ValueError, "canonique"):
                    reconciled_openagenda_url(cinor_lead(), cinor_row(**modified))
        with self.assertRaisesRegex(ValueError, "canonique"):
            reconciled_openagenda_url(
                cinor_lead(source_url=FIRST_PARTY.replace(
                    "reseau-des-mediatheques-cinor", "autre-agenda")),
                cinor_row())

    def test_different_event_uid_cannot_borrow_cinor_alias(self):
        with self.assertRaisesRegex(ValueError, "canonique"):
            reconciled_openagenda_url(
                cinor_lead(external_id="55943124"),
                cinor_row())

    def test_valid_country_and_alias_do_not_bypass_non_music_category(self):
        with self.assertRaisesRegex(ValueError, "familiale musicale"):
            make_event(cinor_lead(), cinor_row(),
                       {"lat": -20.89270, "lng": 55.45130},
                       date(2026, 11, 16))

    def test_country_mismatch_still_stops_before_category(self):
        for invalid in (
            cinor_row(location_countrycode="BE"),
            cinor_row(location_region="Occitanie"),
            cinor_row(location_department="Paris"),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "Pays, région"):
                    make_event(cinor_lead(), invalid,
                               {"lat": -20.89270, "lng": 55.45130},
                               date(2026, 11, 16))

    def test_exact_session_time_and_gps_remain_mandatory(self):
        with self.assertRaisesRegex(ValueError, "Position source incompatible"):
            make_event(cinor_lead(), cinor_row(),
                       {"lat": -20.995, "lng": 55.321},
                       date(2026, 11, 16))
        with self.assertRaisesRegex(ValueError, "Séance datée"):
            make_event(cinor_lead(), cinor_row(timings=[]),
                       {"lat": -20.89270, "lng": 55.45130},
                       date(2026, 11, 16))


if __name__ == "__main__":
    unittest.main()
