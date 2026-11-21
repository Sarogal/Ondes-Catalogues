"""Isolated no-publisher admission diagnostics, including unnumbered outdoor GPS."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
# Reuse immutable reviewed DILA/OSM test fixtures; they mint the actual proof.
sys.path.insert(0, str(ROOT / "tests"))
from test_ptitesondes_unnumbered_official_geo_proof import (
    mint as mint_unnumbered, directory as dila, CITY, VENUE, POINT,
)
from ptitesondes_open_world_admission_diagnostics import (
    inspect_open_world_candidate, public_redacted_admission_summary,
)

DAY = date(2026, 11, 21)
KEY = "oa_pk_" + "n" * 40
SOURCE = "https://nouveau-programmateur.fr/contes"
MUNICIPAL = "https://www.ville-les-bois.fr/agenda/sorties"


def time_slot(hour):
    start = datetime(2026, 12, 5, hour,
                     tzinfo=timezone(timedelta(hours=1)))
    return {"begin": start.isoformat(timespec="seconds"),
            "end": (start + timedelta(minutes=40))
                .isoformat(timespec="seconds")}


def lead(*hours, title="Conte musical pour enfants"):
    return {
        "agenda_uid": 809913, "agenda_slug": "agenda-nouveau-organisateur",
        "event_uid": 999401, "title": title, "city_unverified": CITY,
        "venue_unverified": VENUE,
        "explicit_source_session_intervals": [
            time_slot(h) for h in (hours or (10, 15))],
        "publication_ready": False, "public_writes": 0,
    }


def source_event(item, **changes):
    event = {
        "uid": item["event_uid"], "state": 2, "status": 1,
        "removed": False, "title": {"fr": item["title"]},
        "description": {"fr": "Un spectacle de contes pour enfants en famille."},
        "timings": item["explicit_source_session_intervals"],
        "location": {
            "name": VENUE, "adminLevel4": CITY,
            "countryCode": "FR",
            "latitude": POINT[0], "longitude": POINT[1]},
    }
    event.update(changes)
    return event


def page(item, municipal):
    events = [{
        "@type": "ChildrensEvent", "name": item["title"],
        "startDate": p["begin"], "endDate": p["end"],
        "location": {
            "name": VENUE,
            "address": {"addressLocality": CITY}},
    } for p in item["explicit_source_session_intervals"]]
    return ("<html><body>"
            + ("<a href='" + SOURCE + "'>Programme</a>" if municipal else "")
            + "<script type='application/ld+json'>"
            + json.dumps({"@graph": events}, ensure_ascii=False)
            + "</script></body></html>")


def inspect(item=None, *, location_proof=None, event=None,
            municipal_html=None, organizer_html=None, snapshot=None,
            directory=None, event_reader=None):
    item = item or lead()
    return inspect_open_world_candidate(
        item, MUNICIPAL, SOURCE, KEY, DAY,
        location_proof=location_proof,
        public_catalogue_snapshot=snapshot,
        oa_event_reader=event_reader or (lambda uid, eid, key:
            event if event is not None else source_event(item)),
        oa_agenda_reader=lambda uid, key: {
            "uid": item["agenda_uid"], "slug": item["agenda_slug"]},
        dila_reader=lambda city: directory if directory is not None else dila(),
        municipal_html_reader=lambda url:
            municipal_html if municipal_html is not None else page(item, True),
        organizer_html_reader=lambda url:
            organizer_html if organizer_html is not None else page(item, False))


class OpenWorldDiagnosticsTests(unittest.TestCase):
    def test_real_existing_unnumbered_proof_correlates_every_time_slot(self):
        item = lead(9, 10, 11, 14, 15, 17)
        evidence = mint_unnumbered()
        self.assertIsNotNone(evidence)
        result = inspect(item, location_proof=evidence)
        self.assertEqual(result["status"],
                         "private_cross_source_admission_diagnostic_only")
        self.assertEqual(result["geography_status"],
                         "independent_named_location_correlated")
        self.assertEqual(
            result["editorial_category_proposal"]["category"],
            "conte-musical")
        self.assertEqual(result["editorial_status"],
                         "recognized_activity_proposal_not_admission")
        self.assertEqual(len(result["private_session_diagnostics"]), 6)
        self.assertTrue(all(
            row["three_source_exact_claims"] and
            row["independently_correlated_location"]
            for row in result["private_session_diagnostics"]))
        self.assertTrue(all(
            "source_reuse_rights_unreviewed" in row["publication_blockers"]
            and "organizer_identity_and_authorship_unproven"
                in row["publication_blockers"]
            and "no_publisher_bridge" in row["publication_blockers"]
            for row in result["private_session_diagnostics"]))
        self.assertFalse(result["publication_ready"])
        self.assertFalse(result["publisher_connected"])
        self.assertEqual(result["public_writes"], 0)

    def test_per_event_open_licence_removes_only_factual_rights_hold(self):
        item = lead()
        original = source_event(item)
        original["rights"] = {
            "license": {"id": "etalab-2.0"},
            "licensor": {"name": "La Scène sans registre"},
            "publisher": {"name": "Agenda fédérateur distinct"},
        }
        original["updatedAt"] = "2026-11-20T19:00:00+01:00"
        result = inspect(item, event=original,
                         location_proof=mint_unnumbered())
        self.assertTrue(result["oa_factual_reuse_open_license"])
        self.assertEqual(result["oa_licensor_attribution"],
                         "La Scène sans registre")
        self.assertIn("20/11/2026", result["oa_attribution_display"])
        self.assertFalse(result["source_reuse_rights_verified"])
        self.assertFalse(any(
            "source_reuse_rights_unreviewed" in x["publication_blockers"]
            for x in result["private_session_diagnostics"]))
        self.assertTrue(all(
            "organizer_identity_and_authorship_unproven"
            in x["publication_blockers"]
            and "no_publisher_bridge" in x["publication_blockers"]
            for x in result["private_session_diagnostics"]))
        self.assertFalse(result["publication_ready"])
        self.assertEqual(result["public_writes"], 0)

    def test_unknown_venue_is_not_a_discovery_block_but_geo_remains_pending(self):
        result = inspect()
        self.assertEqual(len(result["private_session_diagnostics"]), 2)
        self.assertTrue(all(row["three_source_exact_claims"]
                            for row in result["private_session_diagnostics"]))
        self.assertEqual(result["geography_status"],
                         "location_independent_proof_pending")
        self.assertTrue(all("independent_location_research_needed"
                            in row["publication_blockers"]
                            for row in result["private_session_diagnostics"]))

    def test_forged_proof_dictionary_cannot_certify_unknown_location(self):
        fake = {"city": CITY, "venue": VENUE,
                "lat": POINT[0], "lng": POINT[1], "verified": True}
        self.assertEqual(inspect(location_proof=fake)["geography_status"],
                         "location_proof_missing_stale_or_conflicting")

    def test_official_location_point_disagrees_with_current_oa(self):
        item = lead()
        changed = source_event(item, location={
            "name": VENUE, "adminLevel4": CITY, "countryCode": "FR",
            "latitude": 43.2, "longitude": 2.25})
        result = inspect(item, event=changed,
                         location_proof=mint_unnumbered())
        self.assertEqual(result["geography_status"],
                         "location_proof_missing_stale_or_conflicting")
        self.assertFalse(any(x["independently_correlated_location"]
                             for x in result["private_session_diagnostics"]))

    def test_missing_coordinates_cannot_be_replaced_by_forged_source(self):
        item = lead()
        changed = source_event(item, location={
            "name": VENUE, "adminLevel4": CITY, "countryCode": "FR"})
        result = inspect(item, event=changed,
                         location_proof=mint_unnumbered())
        self.assertEqual(result["geography_status"],
                         "location_independent_proof_pending")

    def test_new_artistic_wording_is_researched_and_not_rejected(self):
        item = lead(title="Bric-à-sons célestes pour familles")
        live = source_event(item, description={"fr":
            "Une création inédite pour les enfants et familles."})
        result = inspect(item, event=live,
                         location_proof=mint_unnumbered())
        self.assertEqual(result["editorial_status"],
                         "new_activity_needs_editorial_research")
        self.assertTrue(all(x["three_source_exact_claims"] for x
                            in result["private_session_diagnostics"]))
        self.assertTrue(all(
            "editorial_activity_requires_review" in x["publication_blockers"]
            for x in result["private_session_diagnostics"]))
        self.assertFalse(result["publication_ready"])

    def test_adult_only_source_is_not_automatically_recategorized(self):
        item = lead(title="Conte musical pour enfants")
        live = source_event(item, description={"fr":
            "Événement réservé aux adultes uniquement."})
        result = inspect(item, event=live,
                         location_proof=mint_unnumbered())
        self.assertEqual(result["editorial_status"],
                         "explicit_adult_only_not_family")
        self.assertTrue(result["source_claimed_adults_only"])
        self.assertTrue(all(
            "source_explicitly_adult_only" in x["publication_blockers"]
            for x in result["private_session_diagnostics"]))

    def test_public_snapshot_duplicate_is_only_a_hint(self):
        item = lead()
        row = {
            "title": item["title"], "city": CITY, "venue": VENUE,
            "date_start": "2026-12-05", "date_end": "2026-12-06"}
        out = inspect(item, snapshot=[row])
        self.assertEqual(out["source_catalogue_duplicate_hints"], 1)
        self.assertFalse(out["historical_duplicate_check_authoritative"])
        self.assertTrue(all(
            "potential_public_duplicate_requires_recheck"
            in x["publication_blockers"]
            for x in out["private_session_diagnostics"]))

    def test_possible_duplicate_is_limited_to_its_actual_calendar_day(self):
        item = lead(10, 15)
        other_day = {
            field: value.replace("2026-12-05", "2026-12-06")
            for field, value in time_slot(10).items()}
        item["explicit_source_session_intervals"].append(other_day)
        snapshot = [{
            "title": item["title"], "city": CITY, "venue": VENUE,
            "date_start": "2026-12-05", "date_end": "2026-12-05"}]
        out = inspect(item, snapshot=snapshot,
                      location_proof=mint_unnumbered())
        self.assertEqual(out["source_catalogue_duplicate_hints"], 1)
        self.assertEqual(len(out["private_session_diagnostics"]), 3)
        self.assertTrue(all(
            "potential_public_duplicate_requires_recheck"
            in row["publication_blockers"]
            for row in out["private_session_diagnostics"][:2]))
        self.assertNotIn(
            "potential_public_duplicate_requires_recheck",
            out["private_session_diagnostics"][2]["publication_blockers"])

    def test_invalid_private_intervals_fail_closed_without_exceptions(self):
        bad = lead()
        bad["explicit_source_session_intervals"][0]["begin"] = "bad-date"
        out = inspect(bad)
        self.assertEqual(out["status"], "invalid_private_candidate_sessions")
        self.assertFalse(out["publication_ready"])
        malformed = lead()
        malformed["explicit_source_session_intervals"].append(
            deepcopy(malformed["explicit_source_session_intervals"][0]))
        out = inspect(malformed)
        self.assertEqual(out["status"], "invalid_private_candidate_sessions")
        public = public_redacted_admission_summary([out])
        self.assertEqual(public["sessions_examined"], 0)

    def test_missing_or_changed_organizer_session_blocks_precise_only(self):
        item = lead(10, 15)
        changed = page(item, False).replace(
            time_slot(10)["begin"], time_slot(11)["begin"])
        out = inspect(item, organizer_html=changed)
        self.assertEqual(len(out["private_session_diagnostics"]), 2)
        self.assertFalse(out["private_session_diagnostics"][0][
            "three_source_exact_claims"])
        self.assertTrue(out["private_session_diagnostics"][1][
            "three_source_exact_claims"])

    def test_organizer_source_changes_after_oa_review_holds_all_claims(self):
        item = lead()
        event = source_event(item)
        event["status"] = 2
        out = inspect(item, event=event)
        self.assertTrue(all(not x["three_source_exact_claims"]
                            for x in out["private_session_diagnostics"]))
        self.assertFalse(out["publication_ready"])

    def test_api_event_reader_called_once_and_provides_geo_point(self):
        item = lead()
        reader = Mock(return_value=source_event(item))
        inspect(item, event_reader=reader,
                location_proof=mint_unnumbered())
        reader.assert_called_once_with(
            item["agenda_uid"], item["event_uid"], KEY)

    def test_unsafe_caller_supplied_flags_never_create_an_approval(self):
        item = lead()
        item["publication_ready"] = True
        out = inspect(item, location_proof=mint_unnumbered())
        self.assertEqual(out["status"], "invalid_private_candidate")
        self.assertFalse(out["publication_ready"])

    def test_unknown_city_not_listed_becomes_research_not_falsified(self):
        out = inspect(directory={"total_count": 0, "results": []})
        self.assertEqual(out["cross_source_status"],
                         "municipal_page_not_correlated_with_dila")
        self.assertFalse(any(
            row["three_source_exact_claims"]
            for row in out["private_session_diagnostics"]))
        self.assertFalse(out["publication_ready"])

    def test_public_aggregate_contains_no_venues_dates_or_sources(self):
        item = lead()
        result = inspect(item, location_proof=mint_unnumbered())
        public = public_redacted_admission_summary([result])
        raw = json.dumps(public)
        self.assertEqual(public["sessions_examined"], 2)
        for key in (item["title"], CITY, VENUE, SOURCE, "2026-12-05"):
            self.assertNotIn(key, raw)
        with self.assertRaises(ValueError):
            public_redacted_admission_summary(
                [dict(result, source_reuse_rights_verified=True)])
        with self.assertRaises(ValueError):
            public_redacted_admission_summary(
                [dict(result, publisher_connected=True)])


if __name__ == "__main__":
    unittest.main()
