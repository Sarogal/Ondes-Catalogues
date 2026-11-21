"""OpenAgenda factual-data licence: event-level, attribution and safety."""
from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_openagenda_reuse_rights import (
    review_event_rights, OPEN_LICENSE_ID, OPEN_LICENSE_NAME,
)

DAY = date(2026, 11, 21)


def event():
    return {
        "uid": 1234, "state": 2, "status": 1,
        "updatedAt": "2026-11-20T11:24:30+01:00",
        "rights": {
            "license": {"id": "etalab-2.0", "name": "Licence Ouverte 2.0"},
            "licensor": {"name": "Le Liberté", "agendaUid": 333},
            "publisher": {"name": "Agenda d'une autre ville",
                          "agendaUid": 456},
        },
    }


class ReuseRightsTests(unittest.TestCase):
    def test_etalab_2_0_uses_per_event_licensor_not_publisher(self):
        out = review_event_rights(event(), DAY)
        self.assertTrue(out["licensed_factual_reuse_confirmed"])
        self.assertEqual(out["license_id"], OPEN_LICENSE_ID)
        self.assertEqual(out["licensor_attribution"], "Le Liberté")
        self.assertIn(OPEN_LICENSE_NAME, out["attribution_display"])
        self.assertIn("20/11/2026", out["attribution_display"])
        self.assertNotIn("Agenda d'une autre ville", out["attribution_display"])
        self.assertFalse(out["independent_organizer_verified"])
        self.assertFalse(out["publication_ready"])
        self.assertFalse(out["description_or_image_reuse_allowed_by_this_gate"])
        self.assertEqual(out["public_writes"], 0)

    def test_licensed_source_requires_exact_per_event_rights(self):
        for change in (
            {"rights": None},
            {"rights": {"license": None, "licensor": {"name": "Le Liberté"}}},
            {"rights": {"license": {"id": "copyright"},
                        "licensor": {"name": "Le Liberté"}}},
            {"rights": {"license": {"id": "etalab-2.0"}, "licensor": {}}},
            {"rights": {"license": {"id": "etalab-2.0"},
                        "licensor": {"name": "<script>bad</script>"}}},
            {"updatedAt": None},
            {"updatedAt": "2026-11-20T13:24:30"},
            {"updatedAt": "2031-01-01T01:20:00+01:00"},
            {"state": 3},
            {"removed": True},
        ):
            with self.subTest(change=change):
                e = event()
                e.update(change)
                out = review_event_rights(e, DAY)
                self.assertFalse(out["licensed_factual_reuse_confirmed"])
                self.assertIsNone(out["attribution_display"])
                self.assertFalse(out["publication_ready"])

    def test_unrelated_agenda_licence_does_not_authorize_new_event(self):
        first = event()
        second = dict(first, rights={
            "license": {"id": "proprietary"},
            "licensor": {"name": "Other source"}})
        self.assertTrue(
            review_event_rights(first, DAY)["licensed_factual_reuse_confirmed"])
        self.assertFalse(
            review_event_rights(second, DAY)["licensed_factual_reuse_confirmed"])

    def test_missing_attribution_date_never_defaults_to_review_date(self):
        e = event()
        del e["updatedAt"]
        out = review_event_rights(e, DAY)
        self.assertEqual(out["status"], "missing_source_last_update")
        self.assertIsNone(out["attribution_display"])


if __name__ == "__main__":
    unittest.main()
