"""Offline privacy / UID dedup contract for private candidate geometry census."""
from datetime import date
from pathlib import Path
import copy
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_oa2_backlog_geo_coverage import audit_backlog_geo_coverage


TODAY = date(2026, 11, 18)


def case(uid="1234", day="2026-12-05", city="Rouen", venue="Bibliothèque fictive",
         collector="openagenda-v2"):
    return {
        "external_id": uid, "date_start": day, "date_end": day,
        "city": city, "venue": venue, "collector": collector,
        "title": "Texte privé de l'événement",
        "source_url": "https://openagenda.com/fr/foo/events/seance-fictive",
    }


def located(row):
    if row["city"] == "Rouen" and row["venue"] == "Bibliothèque fictive":
        return {"city": "Rouen", "aliases": ["Bibliothèque fictive"],
                "lat": 49.4, "lng": 1.09}
    return None


class GeoBacklogCoverageTests(unittest.TestCase):
    def test_future_multi_day_one_uid_not_thirty_new_events(self):
        leads = [
            case(day=f"2026-12-{d:02d}") for d in range(1, 31)
        ]
        result = audit_backlog_geo_coverage(
            leads, TODAY, location_lookup=located)
        c = result["counts"]
        self.assertEqual(c["future_leads_in_active_window"], 30)
        self.assertEqual(c["active_future_unique_uids"], 1)
        self.assertEqual(c["active_future_unique_uid_days"], 30)
        self.assertEqual(c["active_future_multi_day_uid_groups"], 1)
        self.assertEqual(c["active_future_multi_day_uid_days"], 30)
        self.assertEqual(c["active_future_venue_city_pairs"], 1)
        self.assertEqual(c["uids_all_venues_exactly_in_existing_registry"], 1)
        self.assertFalse(result["approval_granted"])
        self.assertFalse(result["venue_identity_match_proves_actual_openagenda_gps"])

    def test_mixed_geo_same_uid_does_not_count_as_fully_located(self):
        leads = [
            case(uid="987", venue="Bibliothèque fictive"),
            case(uid="987", day="2026-12-06",
                 venue="Bibliothèque inconnue"),
            case(uid="999", venue="Bibliothèque fictive"),
        ]
        c = audit_backlog_geo_coverage(
            leads, TODAY, location_lookup=located)["counts"]
        self.assertEqual(c["active_future_unique_uids"], 2)
        self.assertEqual(c["leads_with_exact_existing_registry_identity"], 2)
        self.assertEqual(c["leads_without_exact_existing_registry_identity"], 1)
        self.assertEqual(c["uids_all_venues_exactly_in_existing_registry"], 1)
        self.assertEqual(c["uids_with_any_venue_missing_or_ambiguous"], 1)

    def test_expired_undated_and_far_future_held_outside_active_window(self):
        rows = [
            case(day="2026-11-17"),
            case(day="2026-11-18"),
            case(day="2027-11-19"),
            case(day="not-a-date"),
            case(day="2026-02-29"),
        ]
        c = audit_backlog_geo_coverage(
            rows, TODAY, location_lookup=located)["counts"]
        self.assertEqual(c["expired_leads"], 1)
        self.assertEqual(c["missing_or_invalid_day"], 2)
        self.assertEqual(c["future_leads_any_horizon"], 2)
        self.assertEqual(c["future_leads_in_active_window"], 1)
        self.assertEqual(c["outside_184_day_active_window"], 1)

    def test_duplicate_uid_and_day_are_still_one_uid_day(self):
        lead = case()
        c = audit_backlog_geo_coverage(
            [lead, copy.deepcopy(lead)], TODAY,
            location_lookup=located)["counts"]
        self.assertEqual(c["active_future_unique_uids"], 1)
        self.assertEqual(c["active_future_unique_uid_days"], 1)
        self.assertEqual(c["future_leads_in_active_window"], 2)

    def test_undated_legacy_history_keeps_report_private(self):
        leads = [
            {"title": "Confidentiel", "source_url": "https://example.org"},
            case(uid="invalid", venue="Inconnue",
                 collector="unrecognized-source"),
            case(uid="123", collector="opendatasoft-index"),
            {"date_start": "2026-11-19", "collector": ["not", "hashable"]},
        ]
        report = audit_backlog_geo_coverage(
            leads, TODAY, location_lookup=located)
        output = json.dumps(report)
        for secret in ("Confidentiel", "openagenda.com", "Bibliothèque",
                       "Rouen", "123", "example.org", "oa_pk_"):
            self.assertNotIn(secret, output)
        self.assertEqual(report["counts"]["raw_leads"], 4)
        self.assertEqual(report["counts"]["missing_or_invalid_uid"], 2)
        self.assertEqual(report["counts"]["collector_not_admissible"], 2)
        self.assertFalse(report["contains_candidate_identifiers"])

    def test_malformed_location_match_never_counts_as_attestation(self):
        for bad in (False, True, [], "yes", 12):
            c = audit_backlog_geo_coverage(
                [case()], TODAY, location_lookup=lambda _: bad)["counts"]
            self.assertEqual(c["leads_without_exact_existing_registry_identity"], 1)
            self.assertEqual(c["uids_all_venues_exactly_in_existing_registry"], 0)

    def test_missing_venue_not_assigned_default_town_center(self):
        row = case(venue="")
        c = audit_backlog_geo_coverage(
            [row], TODAY, location_lookup=lambda _: self.fail("No lookup allowed")
        )["counts"]
        self.assertEqual(c["missing_city_or_venue"], 1)
        self.assertEqual(c["venue_identity_unavailable"], 1)
        self.assertEqual(c["uids_with_any_venue_missing_or_ambiguous"], 1)

    def test_overseas_city_remains_separate_from_mainland_homonym(self):
        rows = [
            case(uid="1", city="Saint-Denis", venue="Bibliothèque fictive"),
            case(uid="2", city="Saint-Denis (La Réunion)",
                 venue="Bibliothèque fictive"),
        ]
        c = audit_backlog_geo_coverage(
            rows, TODAY, location_lookup=lambda r: (
                {"city": r["city"]} if "Réunion" in r["city"] else None
            ))["counts"]
        self.assertEqual(c["active_future_venue_city_pairs"], 2)
        self.assertEqual(c["uids_all_venues_exactly_in_existing_registry"], 1)

    def test_source_breakdown_whitelisted_no_leak(self):
        rows = [case(uid="1", collector="openagenda-v2"),
                case(uid="2", collector="opendatasoft-index"),
                case(uid="3", collector="PRIVATE_KEY_XXXXX"),
                case(uid="4", collector=[])]
        a = audit_backlog_geo_coverage(
            rows, TODAY, location_lookup=located)
        self.assertEqual(a["collector_counts"], {
            "openagenda-v2": 1,
            "opendatasoft-index": 1,
            "unrecognized_or_legacy": 2,
        })
        self.assertNotIn("PRIVATE_KEY_XXXXX", json.dumps(a))
        self.assertEqual(a["counts"]["collector_not_admissible"], 2)

    def test_malformed_rows_safe_and_bounded(self):
        c = audit_backlog_geo_coverage(
            [None, [], "", {}], TODAY,
            location_lookup=located)["counts"]
        self.assertEqual(c["malformed_rows"], 3)
        self.assertEqual(c["missing_or_invalid_day"], 1)
        for bad in (None, "x", [case()] * 4001):
            with self.assertRaises(ValueError):
                audit_backlog_geo_coverage(bad, TODAY, location_lookup=located)

    def test_registry_exception_cannot_promote_or_leak(self):
        def bad(_):
            raise ValueError("PRIVATE_TOKEN=oa_pk_1234")
        result = audit_backlog_geo_coverage(
            [case()], TODAY, location_lookup=bad)
        self.assertEqual(result["counts"][
            "leads_without_exact_existing_registry_identity"], 1)
        self.assertNotIn("oa_pk_", json.dumps(result))
        self.assertFalse(result["publisher_connected"])
        self.assertEqual(result["public_writes"], 0)


if __name__ == "__main__":
    unittest.main()
