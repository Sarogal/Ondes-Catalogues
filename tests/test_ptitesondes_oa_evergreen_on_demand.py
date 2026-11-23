"""Commercial evergreen service is a hold, not a 14-session showtime cap."""
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from ptitesondes_oa_evergreen_on_demand import ambiguous_on_demand_studio_series
from ptitesondes_oa_first_party_admission import admit_live_openagenda
from test_ptitesondes_open_world_release_rehearsal import (
    TODAY, DAY, AGENDA, lead, oa_event,
)
from test_ptitesondes_candidate_promotion import base


def long_days(count=50):
    return [{
        "begin": (DAY + timedelta(days=i)).isoformat() + "T10:00:00+01:00",
        "end": (DAY + timedelta(days=i)).isoformat() + "T11:00:00+01:00",
    } for i in range(count)]


def studio_bookings():
    record = deepcopy(oa_event())
    record["title"] = {"fr": "Créez et enregistrez votre musique en studio"}
    record["description"] = {
        "fr": "Atelier en studio professionnel pour enfants, "
              "team buildings et particuliers. Les entreprises participent."
    }
    record["conditions"] = {"fr": "Sur réservation, service payant."}
    record["timings"] = long_days()
    return record


class EvergreenCommercialStudioTests(unittest.TestCase):
    def test_same_generic_guard_applies_to_publisher_and_reconciliation(self):
        from ptitesondes_official_reconciliation import (
            ambiguous_on_demand_studio_series as existing_guard,
        )
        record = studio_bookings()
        days = {x["begin"][:10]: True for x in record["timings"]}
        self.assertTrue(ambiguous_on_demand_studio_series(record, days))
        self.assertTrue(existing_guard(record, days))
        item = dict(lead(), title="Créez et enregistrez votre musique en studio",
                    explicit_source_session_intervals=record["timings"])
        candidate, reason = admit_live_openagenda(
            item, DAY.isoformat(), AGENDA, record, base(), base(), TODAY)
        self.assertIsNone(candidate)
        self.assertEqual(reason, "oa_direct_evergreen_on_demand_review")

    def test_fifty_genuine_shows_have_no_arbitrary_session_limit(self):
        record = deepcopy(oa_event())
        record["title"] = {"fr": "Contes musicaux pour les tout-petits"}
        record["description"] = {
            "fr": "Un spectacle musical jeune public pour les enfants à dates annoncées."
        }
        record["conditions"] = {"fr": "Entrée libre"}
        record["timings"] = long_days()
        item = dict(lead(), title="Contes musicaux pour les tout-petits",
                    explicit_source_session_intervals=record["timings"])
        days = {x["begin"][:10]: True for x in record["timings"]}
        self.assertFalse(ambiguous_on_demand_studio_series(record, days))
        result, reason = admit_live_openagenda(
            item, DAY.isoformat(), AGENDA, record, base(), base(), TODAY)
        self.assertEqual(reason, "oa_direct_live_source_accepted")
        self.assertIsNotNone(result)

    def test_full_signals_required_not_just_studio_or_many_dates(self):
        record = studio_bookings()
        days = {x["begin"][:10]: True for x in record["timings"]}
        for changed in (
            {"conditions": {"fr": "Ouvert en accès libre"}},  # no bookable service
            {"description": {"fr": "Studio professionnel pour enfants"}},  # no corporate
            {"title": {"fr": "Festival musical jeunesse"},
             "description": {"fr": "Contes publics, entreprises bienvenues"}},  # no studio
        ):
            with self.subTest(change=changed):
                clone = dict(record, **changed)
                self.assertFalse(ambiguous_on_demand_studio_series(clone, days))
        self.assertFalse(ambiguous_on_demand_studio_series(
            record, dict(list(days.items())[:13])))
