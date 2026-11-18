"""End-to-end, all-offline and append-only-safe fallback rehearsal.

Real public API reads and publisher execution are intentionally NOT performed.
Every datum is synthetic; no key, private backlog or GitHub write is used.
"""
from copy import deepcopy
from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_openagenda_v2_direct_evidence import review_direct_v2
from ptitesondes_openagenda_v2_preintegration import (
    agenda_identity_for_review, independently_linked_agenda, group_multi_day,
    ods_fallback_preflight,
)

SOURCE = {
    "agenda_uid": "919191", "agenda_slug": "ville-test",
    "timezone": "Europe/Paris",
    "institution_url": "https://www.municipalite.example.org/",
    "authority_reference_url": "https://www.municipalite.example.org/culture",
}
LEAD = {
    "source_url": "https://openagenda.com/ville-test/events/12345678_une-sortie",
    "external_id": "12345678", "title": "Une sortie pour enfants",
    "city": "Villeurbanne", "venue": "Bibliothèque du test",
    "date_start": "2026-12-05", "date_end": "2026-12-05",
}
VENUE = {"city": "Villeurbanne", "aliases": ["Bibliothèque du test"],
         "lat": 45.76, "lng": 4.9}
ONE = {"begin": "2026-12-05T14:00:00+0100",
       "end": "2026-12-05T15:00:00+0100"}
EVENT = {
    "uid": 12345678, "state": 2, "status": 1,
    "attendanceMode": 1, "timezone": "Europe/Paris",
    "title": {"fr": "Une sortie pour enfants"},
    "description": {"fr": "Séance pour les familles et enfants"},
    "location": {"name": "Bibliothèque du test",
                 "adminLevel4": "Villeurbanne", "countryCode": "FR",
                 "latitude": 45.76, "longitude": 4.9},
    "rights": {"license": {"id": "etalab-2.0", "name": "Licence Ouverte"},
               "licensor": {"name": "Commune test"}},
    "timings": [ONE],
}


def inspect(lead=None, event=None, ods="uid_absent", historic=False, page=True):
    ld, ev = deepcopy(lead or LEAD), deepcopy(event or EVENT)
    proof = review_direct_v2(ld, ev, {
        "agenda_slug": "ville-test", "agenda_uid": "919191",
        "timezone": "Europe/Paris",
    }, VENUE, date(2026, 11, 18))
    identity = agenda_identity_for_review(
        {"uid": 919191, "slug": "ville-test"}, SOURCE)
    official = {
        "url": SOURCE["authority_reference_url"],
        "text": '<a href="https://openagenda.com/fr/ville-test">Agenda officiel</a>'
    }
    linked = independently_linked_agenda(identity, SOURCE, official) if page else False
    grouping = group_multi_day(ev)
    return ods_fallback_preflight(ods, proof, identity, grouping,
                                  historic_uid_exists=historic,
                                  independently_linked=linked)


class FullOfflineCircuit(unittest.TestCase):
    def test_missing_ods_valid_direct_source_reaches_only_remaining_gates(self):
        answer = inspect()
        self.assertEqual(answer["route"], "direct_source_candidate_for_remaining_gates")
        self.assertFalse(answer["publisher_connected"])
        self.assertFalse(answer["approval_granted"])
        self.assertEqual(answer["public_writes"], 0)
        self.assertNotIn("additions", answer)

    def test_ods_has_conflicting_row_never_bypassed(self):
        self.assertEqual(inspect(ods="conflicting")["route"], "hold")
        self.assertEqual(inspect(ods="found")["route"], "hold")

    def test_organizer_authority_link_not_present(self):
        x = inspect(page=False)
        self.assertEqual(x["route"], "hold")
        self.assertEqual(x["reason"], "institutional_agenda_link_not_verified")

    def test_historical_uid_blocks_every_source(self):
        self.assertEqual(inspect(historic=True)["reason"],
                         "historical_uid_exists_or_unknown")

    def test_multi_day_one_uid_exhibition_never_expands_to_daily_events(self):
        x = deepcopy(EVENT)
        for day in range(6, 30):
            x["timings"].append({
                "begin": f"2026-12-{day:02d}T14:00:00+0100",
                "end": f"2026-12-{day:02d}T15:00:00+0100",
            })
        self.assertEqual(inspect(event=x)["reason"], "multi_day_requires_grouping")
        self.assertEqual(group_multi_day(x)["explicit_day_count"], 25)

    def test_source_age_venue_or_license_failure_stops_before_routing(self):
        cases = [
            dict(EVENT, status=6),
            dict(EVENT, rights={"license": "etalab-2.0"}),
            dict(EVENT, description={"fr": "Réservé aux adultes"}),
            dict(EVENT, location=dict(EVENT["location"], latitude=45.79)),
        ]
        for item in cases:
            with self.subTest(item=item):
                self.assertEqual(inspect(event=item)["reason"],
                                 "direct_source_not_verified")


if __name__ == "__main__":
    unittest.main()
