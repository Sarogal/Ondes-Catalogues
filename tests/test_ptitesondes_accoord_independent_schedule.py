"""Adversarial proof checks for one externally verified toddler-song series.

No generic music/child classifier is relaxed. Every session must be explicitly
listed on the live first-party organizer page, not inferred from recurrence.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from official_organizer_proof import organizer_url, reviewed_schedule
from ptitesondes_candidate_promotion import reviewed_accoord_category
from proof import norm

OA = "https://openagenda.com/nantesmetropole/events/contes-and-comptines"
OFFICIAL = "https://www.accoord.fr/agenda/contes-comptines/"
VENUE = "Centre socioculturel des Bourderies - ACCOORD"


def lead(**changes):
    base = {
        "collector": "opendatasoft-index", "external_id": "813941",
        "source_url": OA, "title": "Contes & comptines",
        "city": "Nantes", "venue": VENUE, "date_start": "2026-11-18",
        "date_end": "2026-11-18",
    }
    base.update(changes)
    return base


def row(**changes):
    base = {"uid": "813941", "title_fr": "Contes & comptines",
            "location_city": "Nantes", "location_name": VENUE,
            "description_fr": "Animation lecture et chansons"}
    base.update(changes)
    return base


def event(**changes):
    base = {
        "source_url": OA, "title": "Contes & comptines",
        "city": "Nantes", "venue": VENUE, "category": "conte-musical",
        "date_start": "2026-11-18", "date_end": "2026-11-18",
        "time": "10:00",
    }
    base.update(changes)
    return base


HEADING = "Contes & comptines - Accoord"
OFFICIAL_BODY = """
    Contes & comptines. Jeune public. En famille.
    Adresse 2A Rue de Saint Brévin, Nantes. 44100 Nantes.
    Animation livre et chanson pour les 0-3 ans.
    Retrouvez-nous à 10h pour une animation lecture.
    Ces temps sont accompagnés de musique.
    Les enfants sont sous la responsabilité de leur responsables légaux.
    Programmation:
    Mercredi 18 novembre 2026 De 10h à 11h30
    Mercredi 25 novembre 2026 De 10h à 11h30
    Gratuit. Adhésion ACCOORD requise (8.80€).
"""


class PinnedCategoryTests(unittest.TestCase):
    def test_only_exact_source_uid_and_venue_qualify(self):
        self.assertEqual(reviewed_accoord_category(lead(), row()),
                         ("conte-musical", "Conte musical"))
        wrong = [
            (lead(external_id="813942"), row()),
            (lead(collector="openagenda-v2"), row()),
            (lead(source_url=OA + "-lookalike"), row()),
            (lead(source_url="https://evil.example/events/813941"), row()),
            (lead(), row(title_fr="Adultes : contes & comptines")),
            (lead(), row(location_city="Rennes")),
            (lead(), row(location_name="Autre centre ACCOORD")),
        ]
        for i, (candidate, record) in enumerate(wrong):
            with self.subTest(i=i):
                self.assertIsNone(reviewed_accoord_category(candidate, record))

    def test_exact_live_organizer_mapping(self):
        self.assertEqual(organizer_url(event()), OFFICIAL)
        for change in (
            {"source_url": OA + "-other"},
            {"category": "concert"}, {"venue": "Salle du Moulin"},
            {"city": "Lille"}, {"title": "Comptines pour adultes"},
        ):
            with self.subTest(change=change):
                self.assertIsNone(organizer_url(event(**change)))


class ScheduleProofTests(unittest.TestCase):
    def check(self, e=None, body=OFFICIAL_BODY):
        return reviewed_schedule(e or event(), HEADING, body)

    def test_exact_day_age_music_address_and_paid_membership(self):
        ok, why = self.check()
        self.assertTrue(ok, why)

    def test_no_recurrence_inference_or_different_day(self):
        for day in ("2026-11-07", "2026-11-11", "2026-12-02",
                    "2026-10-07", "2027-11-18"):
            with self.subTest(day=day):
                ok, _ = self.check(event(date_start=day, date_end=day))
                self.assertFalse(ok)
        self.assertTrue(self.check(event(date_start="2026-11-25",
                                          date_end="2026-11-25"))[0])

    def test_no_wrong_hours_category_or_date_span(self):
        for change in ({"time": "09:00"}, {"time": "11:30"},
                       {"time": "10:00, 11:00"},
                       {"date_end": "2026-11-25"},
                       {"category": "concert"}):
            with self.subTest(change=change):
                self.assertFalse(self.check(event(**change))[0])

    def test_missing_age_venue_music_price_and_dates_block(self):
        missing = (
            "Animation livre et chanson pour les 0-3 ans",
            "2A Rue de Saint Brévin",
            "temps sont accompagnés de musique",
            "Mercredi 18 novembre 2026",
            "De 10h à 11h30",
            "Gratuit",
            "Adhésion ACCOORD requise",
        )
        for wording in missing:
            with self.subTest(wording=wording):
                self.assertFalse(self.check(body=OFFICIAL_BODY.replace(
                    wording, "information retirée"))[0])

    def test_cancellation_or_wrong_heading_blocks(self):
        self.assertFalse(self.check(body=OFFICIAL_BODY + " Séance annulée.")[0])
        self.assertFalse(reviewed_schedule(event(), "Programme culturel",
                                          OFFICIAL_BODY)[0])


if __name__ == "__main__":
    unittest.main()
