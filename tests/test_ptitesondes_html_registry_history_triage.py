"""Adversarial offline contract for the non-publishing HTML provenance triage."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_html_registry_history_triage import triage_independent_context

VENUE = {
    "city": "Montpellier",
    "aliases": ["Maison pour tous Albert Camus"],
    "lat": 43.60,
    "lng": 3.85,
    "official": "https://mpt.montpellier.fr/maisons/albert-camus",
    "geo_source": "https://www.openstreetmap.org/way/123456",
}
LEAD = {
    "title": "Atelier yoga enfants",
    "city": "Montpellier",
    "venue": "Maison pour tous Albert Camus",
    "date_start": "2026-11-21",
    "start_local": "09:15",
    "source_url": "https://mpt.montpellier.fr/evenement/atelier-yoga-enfants",
}
EVENT = {
    "title": LEAD["title"],
    "city": LEAD["city"],
    "venue": LEAD["venue"],
    "date_start": LEAD["date_start"],
    "date_end": LEAD["date_start"],
    "time": LEAD["start_local"],
    "source_url": "https://other-institution.test/evenement/yoga",
}


def context(events=None, legacy=None, public=None):
    return {
        "legacy_venues": [deepcopy(VENUE)] if legacy is None else legacy,
        "public_places": [] if public is None else public,
        "historical_catalogue": {
            "updated_at": "2026-11-19T08:00:00+01:00",
            "events": [] if events is None else events,
        },
    }


class IndependentRegistryHistoryContract(unittest.TestCase):
    def test_exact_reviewed_name_city_and_two_distinct_sources_match_only(self):
        out = triage_independent_context(LEAD, context())
        self.assertEqual(out["venue_status"], "matched")
        self.assertEqual(out["history_status"], "clear")
        self.assertTrue(out["venue_registry_is_previously_reviewed_not_refetched"])
        for k in ("individual_session_independently_attested",
                  "organizer_independently_attested", "rights_reviewed",
                  "approval_granted", "publication_ready"):
            self.assertFalse(out[k])
        self.assertEqual(out["public_writes"], 0)
        serialized = json.dumps(out)
        for private in ("Montpellier", "Albert Camus", "atelier-yoga", "3.85",
                        "source_url", "coordinates", "catalogue"):
            self.assertNotIn(private, serialized)

    def test_nearby_or_lookalike_names_cannot_claim_a_venue(self):
        for name, city in (
            ("Maison pour tous Albert Camus (annexe)", "Montpellier"),
            ("Maison pour tous Albert Camus", "Lattes"),
            ("Maison pour tous Albert Camuss", "Montpellier"),
        ):
            with self.subTest(name=name, city=city):
                out = triage_independent_context(
                    dict(LEAD, venue=name, city=city), context())
                self.assertEqual(out["venue_status"], "missing")

    def test_duplicate_registry_names_fail_closed_even_if_same_building(self):
        out = triage_independent_context(LEAD, context(
            legacy=[VENUE], public=[deepcopy(VENUE)]))
        self.assertEqual(out["venue_status"], "ambiguous")
        self.assertFalse(out["approval_granted"])

    def test_untrusted_registry_geographic_provenance_never_passes(self):
        variants = [
            dict(VENUE, geo_source=VENUE["official"]),
            dict(VENUE, geo_source="http://www.openstreetmap.org/way/123456"),
            dict(VENUE, lat=0, lng=0),
            dict(VENUE, lat=float("nan")),
            dict(VENUE, geo_source="https://www.openstreetmap.org.evil.test/way/1234"),
        ]
        # A malicious *different but plausible* geocoding host alone cannot
        # be proved authoritative by this stage. This test checks the actual
        # structural failure cases only; host authority remains a gate later.
        for row in variants[:4]:
            with self.subTest(row=row):
                out = triage_independent_context(LEAD, context(legacy=[row]))
                self.assertEqual(out["venue_status"], "untrusted")
        self.assertEqual(triage_independent_context(
            LEAD, context(legacy=[variants[-1]]))["venue_status"],
            "matched")  # Shape does not attest the host's real authority.

    def test_cross_source_duplicate_is_held_even_with_different_url(self):
        out = triage_independent_context(LEAD, context(events=[EVENT]))
        self.assertEqual(out["history_status"], "duplicate")
        self.assertFalse(out["publication_ready"])

    def test_other_clock_shared_url_and_missing_clock_are_ambiguous(self):
        for row in (
            dict(EVENT, time="10:30"),
            dict(EVENT, time="10:30 et 11:30"),
            dict(EVENT, title="Autre animation", source_url=LEAD["source_url"]),
        ):
            with self.subTest(row=row):
                self.assertEqual(triage_independent_context(
                    LEAD, context(events=[row]))["history_status"], "ambiguous")

    def test_different_event_and_source_without_collision_is_clear(self):
        other = dict(EVENT, title="Autre sortie", source_url="https://elsewhere.test/a")
        self.assertEqual(triage_independent_context(
            LEAD, context(events=[other]))["history_status"], "clear")

    def test_malformed_context_and_corrupt_historical_identity_fail_closed(self):
        for corrupt in (None, {}, {"events": []},
                        dict(context(), public_places="forged")):
            with self.subTest(corrupt=corrupt):
                out = triage_independent_context(LEAD, corrupt)
                self.assertEqual(out["venue_status"], "not_checked")
                self.assertEqual(out["history_status"], "not_checked")
        self.assertEqual(triage_independent_context(
            LEAD, context(events=[dict(EVENT, city=None)]))["history_status"],
            "not_checked")

    def test_candidate_cannot_override_independent_registry_or_write(self):
        forged = dict(LEAD, lat=VENUE["lat"], lng=VENUE["lng"],
                      approved=True, source="claim-by-collector")
        out = triage_independent_context(forged, context(legacy=[]))
        self.assertEqual(out["venue_status"], "missing")
        self.assertEqual(out["history_status"], "clear")
        self.assertFalse(out["approval_granted"])
        self.assertEqual(out["public_writes"], 0)


if __name__ == "__main__":
    unittest.main()
