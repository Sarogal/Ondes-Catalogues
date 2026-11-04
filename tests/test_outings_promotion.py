import unittest
from datetime import date
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))

from outings_promotion import (
    build_event, category_for, get_ods, official_family, preview,
    timings_on_day, venue_for,
)

TODAY = date(2026, 11, 4)
URL = "https://openagenda.com/nantes/events/un-animal-des-amis-mots"
LEAD = {
    "title": "Jeune public - Concert/Conte musical - Un animal, des amis mots",
    "city": "Nantes", "venue": "Théâtre de Jeanne",
    "source_url": URL, "date_start": "2027-02-10",
    "date_end": "2027-02-10", "external_id": "12345678",
    "collector": "opendatasoft-index"
}
ROW = {
    "uid": "12345678",
    "title_fr": LEAD["title"], "description_fr": "Spectacle pour enfants",
    "canonicalurl": URL, "originagenda_title": "Théâtre de Jeanne",
    "location_city": "Nantes", "location_name": "Théâtre de Jeanne",
    "location_countrycode": "FR", "location_department": "Loire-Atlantique",
    "location_region": "Pays de la Loire",
    "location_coordinates": {"lat": 47.20457, "lon": -1.57551},
    "timings": '[{"begin":"2027-02-10T14:30:00+01:00","end":"2027-02-10T15:15:00+01:00"},'
               '{"begin":"2027-02-12T14:30:00+01:00","end":"2027-02-12T15:15:00+01:00"}]',
    "status": '{"id": 1}',
    "age_min": 3, "age_max": 8,
}
PUBLIC = {"events": [{"id": "historic", "title": "Autre",
                     "city": "Nantes", "venue": "Théâtre de Jeanne",
                     "date_start": "2026-12-10"}]}


class PromotionPreviewTests(unittest.TestCase):
    def test_age_music_family_mandatory(self):
        self.assertTrue(official_family(LEAD["title"], ""))
        self.assertFalse(official_family("Ciné-concert Metropolis", ""))
        self.assertFalse(official_family("Enfance et bricolage", ""))
        self.assertTrue(official_family("Éveil musical", "atelier en médiathèque"))

    def test_official_venue_only(self):
        self.assertIsNotNone(venue_for("Nantes", "Théâtre de Jeanne"))
        self.assertIsNone(venue_for("Nantes", "Théâtre inconnu"))
        self.assertIsNone(venue_for("Paris", "Théâtre de Jeanne"))

    def test_occurrences_do_not_bridge_dates(self):
        self.assertEqual(timings_on_day(ROW["timings"], "2027-02-10"), ["14:30"])
        self.assertEqual(timings_on_day(ROW["timings"], "2027-02-11"), [])

    def test_build_well_supported_event(self):
        event, reason = build_event(LEAD, ROW, TODAY)
        self.assertIsNotNone(event, reason)
        self.assertEqual(event["time"], "14:30")
        self.assertEqual(event["date_start"], event["date_end"])
        self.assertEqual(event["lat"], 47.20457)
        self.assertEqual(event["age_min"], 3)
        self.assertEqual(event["category"], "conte-musical")
        self.assertNotIn("price", event)
        self.assertNotIn("description", event)

    def test_geo_disagreement_rejected(self):
        event, reason = build_event(LEAD, dict(ROW, location_coordinates={
            "lat": 48.85777, "lon": 2.34613}), TODAY)
        self.assertIsNone(event)
        self.assertIn("contradictoires", reason)

    def test_cancelled_or_unknown_not_promoted(self):
        for status in ('{"id": 2}', '{"id": 3}', "not json", None):
            with self.subTest(status=status):
                event, reason = build_event(LEAD, dict(ROW, status=status), TODAY)
                self.assertIsNone(event)

    def test_absent_day_rejected(self):
        event, _ = build_event(dict(LEAD, date_start="2027-02-11", date_end="2027-02-11"), ROW, TODAY)
        self.assertIsNone(event)

    def test_changed_title_and_source_rejected(self):
        for changed in (dict(ROW, title_fr="Autre événement"),
                        dict(ROW, canonicalurl="https://example.org/not-official")):
            event, _ = build_event(LEAD, changed, TODAY)
            self.assertIsNone(event)

    def test_invalid_age_is_not_silently_assumed(self):
        event, reason = build_event(LEAD, dict(ROW, age_min=80), TODAY)
        self.assertIsNone(event)
        self.assertIn("âge", reason)

    def test_city_or_venue_mismatch(self):
        for changed in (dict(ROW, location_city="Bordeaux"),
                        dict(ROW, location_name="Théâtre inconnu")):
            event, _ = build_event(LEAD, changed, TODAY)
            self.assertIsNone(event)

    def test_official_proof_is_required(self):
        seen = []
        def checker(event, originals):
            seen.append(event["id"])
            return False, "page officielle indisponible"
        report = preview([LEAD], PUBLIC, TODAY, fetch=lambda _: ROW, verify=checker)
        self.assertEqual(report["accepted"], [])
        self.assertEqual(report["public_changes"], 0)
        self.assertEqual(len(seen), 1)
        self.assertEqual(report["rejected_by_reason"]["page officielle indisponible"], 1)

    def test_proof_acceptance_is_dry_run_only(self):
        report = preview([LEAD], PUBLIC, TODAY, fetch=lambda _: ROW,
                         verify=lambda event, originals: (True, "preuve"))
        self.assertEqual(len(report["accepted"]), 1)
        self.assertEqual(report["public_changes"], 0)
        self.assertEqual(len(PUBLIC["events"]), 1)
        self.assertEqual(report["network_requests"], 1)

    def test_cached_index_for_multiple_discontinuous_days(self):
        second = dict(LEAD, date_start="2027-02-12", date_end="2027-02-12")
        report = preview([LEAD, second], PUBLIC, TODAY, fetch=lambda _: ROW,
                         verify=lambda event, originals: (True, "preuve"))
        self.assertEqual(len(report["accepted"]), 2)
        self.assertEqual(report["network_requests"], 1)

    def test_known_published_signature_no_duplicate(self):
        event, _ = build_event(LEAD, ROW, TODAY)
        existing = {"events": PUBLIC["events"] + [dict(event, id="old-different-id")]}
        report = preview([LEAD], existing, TODAY, fetch=lambda _: ROW,
                         verify=lambda event, originals: (True, "preuve"))
        self.assertEqual(len(report["accepted"]), 0)
        self.assertEqual(report["rejected_by_reason"]["déjà publié"], 1)

    def test_nonregistered_venue_never_fetches_remote(self):
        unknown = dict(LEAD, venue="Autre lieu")
        def should_not_fetch(_):
            self.fail("No remote call should happen")
        report = preview([unknown], PUBLIC, TODAY, fetch=should_not_fetch)
        self.assertEqual(report["examined"], 0)
        self.assertEqual(report["accepted"], [])

if __name__ == "__main__":
    unittest.main()
