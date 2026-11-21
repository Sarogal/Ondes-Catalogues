"""Adversarial offline coverage of national OpenAgenda event exploration."""
from datetime import date
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ptitesondes_openagenda_national_event_research import (
    SCHEMA, MAX_PAGE_EVENTS, STATE_SCHEMA, _state, _write_new, _write_state,
    read_events_page, validate_events_page, scan_agenda,
    select_index_candidate, propose_event, valid_after, main,
)
from ptitesondes_openagenda_public_agenda_index import SCHEMA as INDEX_SCHEMA

DAY = date(2026, 11, 21)
KEY = "oa_pk_private_test_read_key_20261121"
AGENDA = {"agenda_uid": 719191, "agenda_slug": "agenda-demo"}


def event(uid=73201, title="Concert pour enfants",
          desc="Pour les familles et les enfants, concert musical.",
          city="Ville fictive", venue="Place du village",
          country="FR", times=6):
    timings = []
    for i in range(times):
        timings.append({
            "begin": f"2026-12-12T{8+i:02d}:00:00+01:00",
            "end": f"2026-12-12T{8+i:02d}:45:00+01:00",
        })
    return {
        "uid": uid, "title": {"fr": title}, "description": {"fr": desc},
        "state": 2, "status": 1, "removed": False,
        "location": {"name": venue, "adminLevel4": city,
                     "countryCode": country, "latitude": 44.5,
                     "longitude": 2.25},
        "timings": timings,
    }


def api_agenda(uid, key):
    return {"uid": uid, "slug": "agenda-demo"}


def index(candidates=None):
    if candidates is None:
        candidates = [{
            "agenda_uid": AGENDA["agenda_uid"],
            "agenda_slug": AGENDA["agenda_slug"],
            "source_identity_only": True, "publisher_enabled": False,
        }]
    return {
        "schema": INDEX_SCHEMA,
        "mode": "private_index_readonly_discovery_not_admission",
        "publication_ready": False, "public_writes": 0,
        "new_agenda_candidates": candidates,
    }


class Response:
    def __init__(self, request, obj):
        self.status = 200
        self.url = request.full_url
        self.buffer = io.BytesIO(json.dumps(obj).encode("utf-8"))
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def geturl(self): return self.url
    def read(self, size=-1): return self.buffer.read(size)


class NationalOAEventResearchTests(unittest.TestCase):
    def test_unknown_numberless_place_can_be_discovered_with_six_shows(self):
        document = event(times=6)
        proposal, code = propose_event(document, AGENDA, DAY)
        self.assertEqual(code, "editorial_candidate")
        self.assertEqual(proposal["editorial_category_proposal"], "concert")
        self.assertEqual(proposal["venue_unverified"], "Place du village")
        self.assertTrue(proposal["requires_new_venue_search"])
        self.assertEqual(proposal["explicit_source_session_days"], ["2026-12-12"])
        self.assertFalse(proposal["location_verified"])
        self.assertFalse(proposal["official_organiser_verified"])
        self.assertFalse(proposal["rights_reviewed"])
        self.assertFalse(proposal["session_verified"])
        self.assertFalse(proposal["publication_ready"])

    def test_storytelling_and_youth_shows_are_not_classified_as_generic_leisure(self):
        for title, category in (
            ("Heure du conte pour enfants", "lecture-jeunesse"),
            ("Spectacle de marionnettes pour enfants", "spectacle-jeunesse"),
            ("Théâtre jeune public", "spectacle-jeunesse"),
            ("Éveil musical pour bébés", "eveil-musical"),
            ("Comptines pour les tout-petits", "eveil-musical"),
            ("Atelier sonore pour enfants", "atelier-musical"),
        ):
            with self.subTest(title=title):
                x, status = propose_event(event(title=title, desc="Pour enfants"), AGENDA, DAY)
                self.assertEqual(status, "editorial_candidate")
                self.assertEqual(x["editorial_category_proposal"], category)

    def test_work_title_uses_long_description_for_youth_performance(self):
        doc = event(title="Le Voyage des étoiles", desc="")
        doc["longDescription"] = {
            "fr": "Spectacle de marionnettes pour enfants et familles."
        }
        proposed, status = propose_event(doc, AGENDA, DAY)
        self.assertEqual(status, "editorial_candidate")
        self.assertEqual(proposed["editorial_category_proposal"],
                         "spectacle-jeunesse")
        self.assertFalse(proposed["publication_ready"])
        self.assertFalse(proposed["official_organiser_verified"])

    def test_rescheduled_openagenda_event_is_research_not_publication(self):
        for status_value in (2, {"id": 2, "label": {"fr": "Reprogrammé"}}):
            with self.subTest(status=status_value):
                doc = event(title="Conte musical jeune public", desc="Pour enfants")
                doc["status"] = status_value
                proposed, reason = propose_event(doc, AGENDA, DAY)
                self.assertEqual(reason, "editorial_candidate")
                self.assertTrue(proposed["requires_reprogramming_verification"])
                self.assertFalse(proposed["session_verified"])
                self.assertFalse(proposed["publication_ready"])
        for impossible in (3, 4, 5, 6):
            with self.subTest(rejected_status=impossible):
                doc = event()
                doc["status"] = impossible
                proposed, reason = propose_event(doc, AGENDA, DAY)
                self.assertIsNone(proposed)
                self.assertEqual(reason, "cancelled_or_unconfirmed_event")

    def test_venue_research_is_not_limited_to_known_city_and_name(self):
        for city, venue in (("Ville fictive", None),
                            (None, "Scène temporaire"),
                            ("Ville fictive", "Place sans numéro")):
            with self.subTest(city=city, venue=venue):
                proposed, reason = propose_event(
                    event(city=city, venue=venue), AGENDA, DAY)
                self.assertEqual(reason, "editorial_candidate")
                self.assertTrue(proposed["requires_new_venue_search"])
                self.assertFalse(proposed["location_verified"])

    def test_gouter_sport_nature_and_crafts_not_promoted(self):
        for title in (
            "Goûter au parc pour enfants",
            "Balade nature en famille",
            "Visite de ferme pour enfants",
            "Atelier de poterie pour enfants",
            "Initiation au judo pour enfants",
            "Jeux de société pour enfants",
        ):
            with self.subTest(title=title):
                output, status = propose_event(
                    event(title=title, desc="Animation familiale pour enfants"),
                    AGENDA, DAY)
                self.assertIsNone(output)
                self.assertEqual(status, "editorial_evidence_not_yet_recognised")

    def test_adult_explicit_exclusion_or_cancelled_cannot_be_emitted(self):
        cases = (
            {**event(), "description": {"fr": "Réservé aux adultes, interdit aux enfants"}},
            {**event(), "status": 4},
            {**event(), "state": 1},
            {**event(), "removed": True},
            {**event(), "uid": True},
        )
        for doc in cases:
            with self.subTest(typ=doc.get("status")):
                x, status = propose_event(doc, AGENDA, DAY)
                self.assertIsNone(x)
                self.assertNotEqual(status, "editorial_candidate")

    def test_numeric_published_status_may_have_localized_label(self):
        doc = event()
        doc["status"] = {"id": 1, "label": {"fr": "Programmé"}}
        outcome, reason = propose_event(doc, AGENDA, DAY)
        self.assertEqual(reason, "editorial_candidate")
        self.assertEqual(outcome["editorial_category_proposal"], "concert")
        for forbidden in ({"id": 4, "label": {"fr": "Annulé"}},
                          {"id": "1"}, True):
            with self.subTest(status=forbidden):
                doc["status"] = forbidden
                self.assertEqual(
                    propose_event(doc, AGENDA, DAY)[1],
                    "cancelled_or_unconfirmed_event")

    def test_no_schedule_does_not_invent_any_event_time(self):
        bad = event(times=0)
        proposed, _ = propose_event(bad, AGENDA, DAY)
        self.assertEqual(proposed["explicit_source_session_days"], [])
        self.assertEqual(proposed["session_research_status"],
                         "no_usable_future_dated_session")
        self.assertFalse(proposed["publication_ready"])
        missing = event(times=1)
        missing["timings"] = [{"begin": "2026-12-12"}]
        proposed, _ = propose_event(missing, AGENDA, DAY)
        self.assertEqual(proposed["explicit_source_session_days"], [])

    def test_missing_geo_does_not_make_a_venue_known_or_a_source_certain(self):
        doc = event(country="GP")
        doc["location"].pop("latitude")
        item, _ = propose_event(doc, AGENDA, DAY)
        self.assertEqual(item["country_code_unverified"], "GP")
        self.assertTrue(item["french_territory_claim_present"])
        self.assertFalse(item["location_verified"])
        doc["location"]["countryCode"] = "ZZ"
        item, _ = propose_event(doc, AGENDA, DAY)
        self.assertFalse(item["french_territory_claim_present"])

    def test_api_read_is_bounded_and_allows_event_string_cursors(self):
        requests = []
        def fake(req, timeout):
            self.assertEqual(timeout, 24)
            requests.append(req)
            return Response(req, {"events": [event()], "after": ["0", "000001758268800",
                                                          "1758472200000", "5335740"]})
        result = read_events_page(AGENDA["agenda_uid"], KEY, opener=fake)
        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(result["after"][1], "000001758268800")
        self.assertEqual(requests[0].get_header("Key"), KEY)
        url = requests[0].full_url
        self.assertTrue(url.startswith("https://api.openagenda.com/v2/agendas/719191/events?"))
        self.assertIn("relative%5B%5D=current", url)
        self.assertIn("relative%5B%5D=upcoming", url)
        self.assertNotIn(KEY, url)
        self.assertNotIn("search=", url)
        self.assertNotIn("city=", url)

    def test_api_string_cursor_roundtrip_preserves_leading_zeroes(self):
        requests = []
        def fake(req, timeout):
            requests.append(req.full_url)
            return Response(req, {"events": [], "after": None})
        cursor = ["0", "000001758268800", "1758472200000", "5335740"]
        result = read_events_page(AGENDA["agenda_uid"], KEY, after=cursor, opener=fake)
        self.assertEqual(result["after"], None)
        self.assertIn("after%5B%5D=000001758268800", requests[0])
        self.assertFalse(valid_after([1, 2]))
        self.assertFalse(valid_after(["123&evil=true"]))

    def test_scan_paginates_and_keeps_unclassified_events_as_count_only(self):
        seen = []
        def reader(uid, key, after, size):
            seen.append(after)
            if after is None:
                return {"events": [event(1), event(2, title="Goûter pour enfants",
                                            desc="Goûter familial au parc")],
                        "after": ["0", "001"]}
            return {"events": [event(3, title="Heure du conte pour enfants",
                                     desc="Pour les tout-petits")],
                    "after": None}
        report = scan_agenda(AGENDA, KEY, DAY, read_agenda=api_agenda,
                             read_page=reader)
        self.assertEqual(seen, [None, ["0", "001"]])
        self.assertEqual(report["counts"]["public_event_uids_seen"], 3)
        self.assertEqual(report["counts"]["editorial_candidate"], 2)
        self.assertEqual(len(report["event_leads"]), 2)
        self.assertEqual(len(report["unclassified_editorial_research_only"]), 1)
        hint = report["unclassified_editorial_research_only"][0]
        self.assertEqual(hint["event_uid"], 2)
        self.assertIsNone(hint["editorial_category_proposal"])
        self.assertFalse(hint["publication_ready"])
        self.assertFalse(hint["publisher_connected"])
        self.assertEqual(hint["public_writes"], 0)
        self.assertTrue(report["agenda_scan_complete"])
        self.assertEqual(report["public_writes"], 0)
        self.assertFalse(report["publication_ready"])
        self.assertNotIn("additions", report)

    def test_new_artistic_format_is_preserved_for_review_but_never_handoff(self):
        # A new expression must not disappear simply because no regex knows
        # how to map it into the historic six musical categories.
        unknown = event(
            uid=97111, title="Voyage sonore aux mille murmures",
            desc="Expérience d'écoute immersive et racontée pour les familles",
            city="Nouvelle commune", venue="Parvis sans adresse")
        report = scan_agenda(
            AGENDA, KEY, DAY, read_agenda=api_agenda,
            read_page=lambda *args, **kwargs: {
                "events": [unknown], "after": None})
        self.assertEqual(report["event_leads"], [])
        self.assertEqual(len(report["unclassified_editorial_research_only"]), 1)
        item = report["unclassified_editorial_research_only"][0]
        self.assertEqual(item["title"], "Voyage sonore aux mille murmures")
        self.assertEqual(item["venue_unverified"], "Parvis sans adresse")
        self.assertEqual(item["country_code_unverified"], "FR")
        self.assertTrue(item["french_territory_claim_present"])
        self.assertEqual(item["explicit_source_session_days"], ["2026-12-12"])
        self.assertIsNone(item["editorial_category_proposal"])
        self.assertFalse(item["source_organizer_independently_verified"])
        self.assertFalse(item["venue_verified"])
        self.assertFalse(item["rights_reviewed"])
        self.assertFalse(item["publication_ready"])
        self.assertEqual(item["public_writes"], 0)
        self.assertNotIn("additions", report)

    def test_unclassified_overseas_and_unknown_geography_are_retained(self):
        for code, expected in (("GP", True), ("PF", True), ("ZZ", False)):
            with self.subTest(country=code):
                lead = event(
                    uid=97800, country=code,
                    title="Voyage sonore aux mille murmures",
                    desc="Expérience d'écoute immersive et racontée pour les familles",
                    city="Village sans liste de lieux", venue="Parvis du village")
                report = scan_agenda(
                    AGENDA, KEY, DAY, read_agenda=api_agenda,
                    read_page=lambda *args, **kwargs: {
                        "events": [lead], "after": None})
                self.assertEqual(report["event_leads"], [])
                self.assertEqual(len(
                    report["unclassified_editorial_research_only"]), 1)
                item = report["unclassified_editorial_research_only"][0]
                self.assertEqual(item["country_code_unverified"], code)
                self.assertIs(item["french_territory_claim_present"], expected)
                self.assertEqual(len(item[
                    "explicit_source_session_intervals"]), 6)
                self.assertFalse(item["publication_ready"])
                self.assertEqual(item["public_writes"], 0)

    def test_generic_gouter_stays_outside_admission_even_if_research_keeps_it(self):
        irrelevant = event(uid=97112, title="Goûter au parc pour enfants",
                           desc="Un goûter familial au parc")
        report = scan_agenda(
            AGENDA, KEY, DAY, read_agenda=api_agenda,
            read_page=lambda *args, **kwargs: {
                "events": [irrelevant], "after": None})
        self.assertEqual(report["event_leads"], [])
        self.assertEqual(len(report["unclassified_editorial_research_only"]), 1)
        self.assertFalse(report["unclassified_editorial_research_only"][0]["publication_ready"])

    def test_ambiguous_or_repeated_cursor_and_uid_fail(self):
        with self.assertRaisesRegex(ValueError, "invalid_event_page_cursor"):
            validate_events_page({"events": [event()], "after": ["1"]}, ["1"])
        with self.assertRaisesRegex(ValueError, "duplicate_event_uid"):
            validate_events_page({"events": [event(), event()], "after": None})
        pages = iter([
            {"events": [event(1)], "after": ["1"]},
            {"events": [event(2)], "after": ["2"]},
            {"events": [event(3)], "after": ["1"]},
        ])
        with self.assertRaisesRegex(ValueError, "repeated_event_pagination_cursor"):
            scan_agenda(AGENDA, KEY, DAY, read_agenda=api_agenda,
                        read_page=lambda *a, **k: next(pages))
        with self.assertRaisesRegex(ValueError, "independent_agenda_uid_slug"):
            scan_agenda(AGENDA, KEY, DAY,
                        read_agenda=lambda uid,key: {"uid":uid, "slug":"wrong"},
                        read_page=lambda *a, **k: None)

    def test_cursor_returns_after_three_pages_without_completing(self):
        i = [0]
        def reader(*args, **kwargs):
            i[0] += 1
            return {"events": [event(i[0])], "after": [str(i[0])]}
        out = scan_agenda(AGENDA, KEY, DAY, pages=3,
                          read_agenda=api_agenda, read_page=reader)
        self.assertEqual(out["counts"]["pages_read"], 3)
        self.assertEqual(out["next_cursor"], ["3"])
        self.assertFalse(out["agenda_scan_complete"])

    def test_only_verified_shape_of_private_index_may_be_selected(self):
        self.assertEqual(select_index_candidate(index(), 0), AGENDA)
        for bad in (
            {**index(), "publication_ready": True},
            {**index(), "mode": "invented"},
            index([{"agenda_uid": 1, "agenda_slug": "valid",
                    "source_identity_only": False, "publisher_enabled": False}]),
            index([{"agenda_uid": 1, "agenda_slug": "invalid/sneaky",
                    "source_identity_only": True, "publisher_enabled": False}]),
            index([index()["new_agenda_candidates"][0]] * 2),
        ):
            with self.subTest(bad=str(bad)[:40]):
                with self.assertRaises(ValueError):
                    select_index_candidate(bad, 0)

    def test_private_report_cursor_binds_selected_source_digest(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = root / "cursor.json"
            report = root / "results.json"
            empty = _state(state, "a" * 64, AGENDA["agenda_uid"])
            self.assertIsNone(empty["after"])
            _write_new(report, {"schema": SCHEMA, "event_leads": [],
                                "public_writes": 0})
            with self.assertRaisesRegex(ValueError, "private_report_must_be_unique"):
                _write_new(report, {})
            _write_state(state, {**empty, "after": ["001"]})
            self.assertEqual(_state(state, "a" * 64, AGENDA["agenda_uid"])["after"],
                             ["001"])
            with self.assertRaisesRegex(ValueError, "private_cursor_state_mismatch"):
                _state(state, "b" * 64, AGENDA["agenda_uid"])
            self.assertEqual(state.stat().st_mode & 0o777, 0o600)

    def test_default_cli_only_checks_private_files_and_never_reaches_network(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.json"
            source.write_text(json.dumps(index()), encoding="utf-8")
            cursor, out = root / "cursor.json", root / "research.json"
            with patch.object(sys, "argv", [
                "prog", "--private-agenda-index-report", str(source),
                "--candidate-index", "0", "--private-cursor-state", str(cursor),
                "--output-private-report", str(out), "--day", str(DAY),
            ]), patch("ptitesondes_openagenda_national_event_research.scan_agenda",
                       side_effect=AssertionError("no network on dry-run")):
                main()
            self.assertFalse(cursor.exists())
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
