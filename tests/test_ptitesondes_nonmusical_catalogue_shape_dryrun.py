"""Adversarial offline rehearsal against the public repository's actual catalogue.

No publisher, tokens, network, mutation, patches, or event data leave outputs.
"""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ptitesondes_nonmusical_catalogue_shape_dryrun import (
    SCHEMA, PACKET_KEYS, MAX_CANDIDATES, SHAPE_STAGES, _hash, _prototype,
    _collision, simulate_nonmusical_catalogue_shape,
)
from ptitesondes_real_family_source_adapters import (
    parse_montpellier_mpt_detail,
)
from test_ptitesondes_html_index_detail_funnel import (
    MPT_TEMPLATE, ONE, PIN,
)

DAY = date(2026, 11, 20)
CATALOGUE = json.loads(
    (ROOT / "docs/ptitesondes/sorties.json").read_text(encoding="utf-8"))
PUBLIC_SHA = _hash(CATALOGUE)
LEADS = parse_montpellier_mpt_detail(MPT_TEMPLATE, ONE, DAY)
VENUE = {
    "city": "Montpellier",
    "aliases": ["Maison pour tous Albert Camus"],
    "lat": 43.60, "lng": 3.85,
    "official": "https://mpt.montpellier.fr/maisons/albert-camus",
    "geo_source": "https://www.openstreetmap.org/way/12345",
}
ADMIN = {
    "city": "Montpellier",
    "department": "Hérault (34)",
    "region": "Occitanie",
    "source_label": "Maisons pour tous — source officielle à contrôler",
}


def packet(lead=None, admin=None, venue=None, catalogue=None):
    pub = deepcopy(CATALOGUE if catalogue is None else catalogue)
    return {
        "lead": deepcopy(LEADS[0] if lead is None else lead),
        "page": {"url": ONE, "html": MPT_TEMPLATE},
        "trusted_index": deepcopy(PIN),
        "child_prefix": "/evenement/",
        "independent_context": {
            "legacy_venues": [
                deepcopy(VENUE if venue is None else venue)],
            "public_places": [],
            "historical_catalogue": pub,
        },
        "admin_pin": deepcopy(ADMIN if admin is None else admin),
    }


DEFAULT = object()


def simulate(rows=DEFAULT, public=None, expected=None, today=DAY):
    p = deepcopy(CATALOGUE if public is None else public)
    ins = [packet(catalogue=p)] if rows is DEFAULT else deepcopy(rows)
    return simulate_nonmusical_catalogue_shape(
        ins, p, today,
        expected_snapshot_sha256=(
            _hash(p) if expected is None else expected))


class GenericNonmusicalShapeTests(unittest.TestCase):
    def assert_not_a_publisher(self, out):
        self.assertEqual(out["schema"], SCHEMA)
        for key in ("rights_reviewed", "source_organizer_independently_attested",
                    "fresh_independent_gps_verified",
                    "publisher_schema_approved", "publisher_connected",
                    "publication_ready", "approval_granted",
                    "private_event_fields_exposed"):
            self.assertIs(out[key], False, key)
        for key in ("no_publisher_patch_constructed",
                    "requires_independently_fetched_live_catalogue",
                    "expected_catalogue_sha_is_consistency_only",
                    "planning_timestamps_are_not_signed_proof",
                    "current_catalogue_unchanged",
                    "existing_music_publisher_unchanged",
                    "unknown_price_is_never_free",
                    "unknown_ages_remain_unasserted"):
            self.assertIs(out[key], True, key)
        self.assertEqual(out["public_writes"], 0)
        self.assertNotIn("events", out)
        self.assertNotIn("additions", out)
        self.assertNotIn("patch", out)
        dump = json.dumps(out)
        for secret in ("Montpellier", "snoezelen",
                       "mpt.montpellier.fr", "Hérault",
                       "09:15", "43.6", "3.85", "source_url"):
            self.assertNotIn(secret, dump)

    def test_static_hypothetical_structure_is_valid_against_real_549_catalogue(self):
        before = deepcopy(CATALOGUE)
        self.assertGreaterEqual(len(CATALOGUE["events"]), 100)
        self.assertEqual(len(LEADS), 2)
        out = simulate()
        self.assertEqual(out["input_candidates"], 1)
        self.assertEqual(out["current_catalogue_records"], len(CATALOGUE["events"]))
        self.assertEqual(out["hypothetical_structural_matches_only"], 1)
        self.assertEqual(out["blockers"][
            "hypothetical_shape_valid_but_all_release_proofs_missing"], 1)
        self.assertEqual(out["hypothetical_catalogue_total_if_all_other_gates_existed"],
                         len(CATALOGUE["events"]) + 1)
        self.assertEqual(before, CATALOGUE)
        self.assert_not_a_publisher(out)

    def test_two_distinct_source_verified_time_slots_can_be_modeled(self):
        rows = [packet(lead=x) for x in LEADS]
        out = simulate(rows)
        self.assertEqual(out["hypothetical_structural_matches_only"], 2)
        self.assertEqual(out["blockers"]["historical_exact_duplicate"], 0)
        self.assertEqual(out["blockers"][
            "historical_ambiguous_cross_source_collision"], 0)
        self.assert_not_a_publisher(out)

    def test_same_session_twice_is_detected_before_staging(self):
        rows = [packet(), packet()]
        out = simulate(rows)
        self.assertEqual(out["hypothetical_structural_matches_only"], 1)
        self.assertEqual(out["blockers"]["historical_exact_duplicate"], 1)
        self.assert_not_a_publisher(out)

    def test_original_unknown_age_and_price_have_neutral_synthetic_fields(self):
        item = packet()
        event, reason = _prototype(
            item["lead"], item["page"], item["trusted_index"],
            item["child_prefix"], item["independent_context"],
            item["admin_pin"], DAY,
        )
        self.assertIsNone(reason)
        self.assertIsNotNone(event)
        self.assertEqual(event["price"], "Voir conditions")
        self.assertNotIn("Gratuit", event.values())
        self.assertNotIn("age_min", event)
        self.assertNotIn("age_max", event)
        self.assertEqual(event["age_label"], "En famille")
        self.assertEqual(event["category"], "atelier-sensoriel")
        self.assertEqual(event["category_label"], "Atelier sensoriel")
        self.assertNotIn("bébé", event["description"])
        self.assertEqual(event["lat"], VENUE["lat"])
        # These timestamps have never been independently attested.
        self.assertEqual(event["verified_at"], DAY.isoformat())
        self.assert_not_a_publisher(simulate())

    def test_historical_duplicate_across_other_source_hosts_is_blocked(self):
        item = packet()
        event, reason = _prototype(
            item["lead"], item["page"], item["trusted_index"],
            item["child_prefix"], item["independent_context"],
            item["admin_pin"], DAY)
        self.assertIsNone(reason)
        published = deepcopy(CATALOGUE)
        published["events"].append(dict(event,
            id="other-aggregator-duplicate",
            source_url="https://another-official.example/event/001"))
        out = simulate([packet(catalogue=published)], public=published)
        self.assertEqual(out["blockers"]["historical_duplicate"], 1)
        self.assertEqual(out["hypothetical_structural_matches_only"], 0)
        self.assert_not_a_publisher(out)

    def test_published_same_page_different_clock_is_ambiguous_not_discarded(self):
        item = packet()
        event, _ = _prototype(
            item["lead"], item["page"], item["trusted_index"],
            item["child_prefix"], item["independent_context"],
            item["admin_pin"], DAY)
        published = deepcopy(CATALOGUE)
        published["events"].append(dict(event, id="other-session",
                                        time="08:30"))
        result = simulate([packet(catalogue=published)], public=published)
        self.assertEqual(result["hypothetical_structural_matches_only"], 0)
        self.assertEqual(result["blockers"][
            "historical_collision_ambiguous"], 1)
        self.assert_not_a_publisher(result)

    def test_unrelated_day_from_same_source_is_not_duplicate_by_itself(self):
        item = packet()
        event, _ = _prototype(
            item["lead"], item["page"], item["trusted_index"],
            item["child_prefix"], item["independent_context"],
            item["admin_pin"], DAY)
        older = dict(event, id="other-day", date_start="2026-12-21",
                     date_end="2026-12-21", time=event["time"])
        self.assertIsNone(_collision(event, [older]))
        self.assert_not_a_publisher(simulate())

    def test_catalogue_hash_mismatch_refuses_all_proposed_changes(self):
        out = simulate(expected="0" * 64)
        self.assertEqual(out["hypothetical_structural_matches_only"], 0)
        self.assertEqual(out["blockers"]["historical_snapshot_not_current"], 1)
        self.assert_not_a_publisher(out)

    def test_historical_snapshot_in_packet_cannot_differ_from_current(self):
        rows = [packet()]
        rows[0]["independent_context"]["historical_catalogue"]["events"] = []
        out = simulate(rows)
        self.assertEqual(out["blockers"]["historical_snapshot_not_current"], 1)
        self.assertEqual(out["hypothetical_structural_matches_only"], 0)
        self.assert_not_a_publisher(out)

    def test_future_or_stale_snapshot_requires_refresh_even_if_hash_is_right(self):
        published = deepcopy(CATALOGUE)
        published["updated_at"] = "2026-11-10T09:00:00+01:00"
        out = simulate([packet(catalogue=published)], public=published)
        self.assertEqual(out["blockers"]["historical_snapshot_unchecked"], 1)
        self.assertEqual(out["hypothetical_structural_matches_only"], 0)
        self.assert_not_a_publisher(out)

    def test_untrusted_administrative_fields_do_not_pass_shape(self):
        for bad in (
            {"city": "Nîmes", "department": "Gard (30)",
             "region": "Occitanie", "source_label": "Unverified"},
            dict(ADMIN, region="<script>x</script>"),
            dict(ADMIN, source_label=""),
            dict(ADMIN, region="Occitanie", approved=True),
            dict(ADMIN, department=None),
        ):
            with self.subTest(bad=bad):
                out = simulate([packet(admin=bad)])
                self.assertEqual(out["blockers"][
                    "admin_pin_unreviewed_or_invalid"], 1)
                self.assert_not_a_publisher(out)

    def test_untrusted_venue_registry_cannot_invent_coordinates(self):
        fake = deepcopy(VENUE)
        fake["geo_source"] = fake["official"]
        out = simulate([packet(venue=fake)])
        self.assertEqual(out["hypothetical_structural_matches_only"], 0)
        # The earlier independent context router catches the untrusted source.
        self.assertEqual(out["blockers"]["reviewed_venue_untrusted"], 1)
        self.assert_not_a_publisher(out)

    def test_unknown_music_or_unreviewed_taxonomy_is_not_admitted(self):
        for category in ("concert", "atelier-musical", "unknown-category", None):
            item = packet()
            item["lead"]["category"] = category
            out = simulate([item])
            self.assertEqual(out["hypothetical_structural_matches_only"], 0)
            self.assertEqual(out["blockers"]["nonmusical_scope_unrecognized"], 1)
            self.assert_not_a_publisher(out)

    def test_forged_approved_or_licence_on_collector_cannot_enable_release(self):
        item = packet()
        item["lead"].update({
            "rights_reviewed": True, "legal_licence": "open",
            "published": True, "approved": True,
            "independent_gps_verified": True,
            "publisher_schema_approved": True,
        })
        out = simulate([item])
        self.assertEqual(out["hypothetical_structural_matches_only"], 1)
        self.assert_not_a_publisher(out)

    def test_false_source_url_or_wrong_clock_blocks_source(self):
        for changes in (
            {"source_url": "https://evil.example/evenement/fake"},
            {"start_local": "19:15"},
            {"title": "This does not match official page"},
        ):
            with self.subTest(change=changes):
                item = packet()
                item["lead"].update(changes)
                out = simulate([item])
                self.assertEqual(out["hypothetical_structural_matches_only"], 0)
                self.assertEqual(out["blockers"]["session_source_unverified"], 1)
                self.assert_not_a_publisher(out)

    def test_invalid_and_oversized_input_is_held(self):
        cases = (
            None, {}, [{"lead": 1}], [packet()] * (MAX_CANDIDATES + 1)
        )
        for rows in cases:
            with self.subTest(kind=type(rows).__name__):
                out = simulate(rows)
                self.assertEqual(out["blockers"]["invalid_catalogue_or_input"], 1)
                self.assert_not_a_publisher(out)

    def test_bad_current_catalogue_or_bad_expected_hash_holds(self):
        for bad in (
            {}, {"version": 4, "events": [], "updated_at": "2026-11-20"},
            dict(CATALOGUE, events=[]),
        ):
            with self.subTest(bad=bad.get("version")):
                out = simulate([packet()], public=bad)
                self.assertEqual(out["blockers"]["invalid_catalogue_or_input"], 1)
                self.assert_not_a_publisher(out)
        self.assertEqual(simulate(expected="xyz")["blockers"][
            "invalid_catalogue_or_input"], 1)

    def test_input_and_catalogue_immutable_after_rehearsal(self):
        packets = [packet(), packet(lead=LEADS[1])]
        catalogue = deepcopy(CATALOGUE)
        before_packets = deepcopy(packets)
        before_catalogue = deepcopy(catalogue)
        out = simulate_nonmusical_catalogue_shape(
            packets, catalogue, DAY, expected_snapshot_sha256=_hash(catalogue))
        self.assertEqual(packets, before_packets)
        self.assertEqual(catalogue, before_catalogue)
        self.assert_not_a_publisher(out)


if __name__ == "__main__":
    unittest.main()
