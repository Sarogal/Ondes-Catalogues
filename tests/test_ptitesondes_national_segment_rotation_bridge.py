"""Offline fairness, unclassified coverage, replay and real module integration."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from ptitesondes_national_segment_rotation_bridge import (
    SCHEMA, STATE_SCHEMA, rotate_private_national_segment,
    public_redacted_national_segment_summary,
)
from ptitesondes_open_world_candidate_rotation import SCHEMA as ROTATION_SCHEMA
from test_ptitesondes_open_world_admission_diagnostics import (
    lead as event_lead, source_event, page as event_page,
    dila, MUNICIPAL, SOURCE,
)

DAY = date(2026, 11, 21)
KEY = "oa_pk_" + "x" * 40
HOME = "https://www.ville-les-bois.fr/"


def item(uid, *, known=True, city="Ville-les-Bois", session=True):
    start = datetime(2026, 12, 5, 14, tzinfo=timezone(timedelta(hours=1)))
    row = {
        "agenda_uid": 81300,
        "agenda_slug": "new-unlisted-national-agenda",
        "event_uid": uid, "title": f"Création artistique {uid}",
        "city_unverified": city,
        "venue_unverified": "Place du village",
        "explicit_source_session_intervals": [{
            "begin": start.isoformat(),
            "end": (start + timedelta(minutes=55)).isoformat(),
        }] if session else [],
        "publication_ready": False, "public_writes": 0,
    }
    if not known:
        row.update({
            "editorial_category_proposal": None,
            "review_state":
                "unknown_activity_requires_official_editorial_evidence",
            "source_organizer_independently_verified": False,
            "rights_reviewed": False,
            "venue_verified": False,
            "publisher_connected": False,
        })
    return row


def segment(known=(101, 102), unknown=(103, 104), *, has_city=True):
    published = [item(uid, city="Ville-les-Bois" if has_city else None)
                 for uid in known]
    unclassified = [item(uid, known=False) for uid in unknown]
    all_items = published + unclassified
    return {
        "schema": "ptitesondes.private_oa_agenda_event_exploration.v1",
        "mode": "private_research_event_leads_only",
        "agenda_uid": 81300,
        "agenda_slug": "new-unlisted-national-agenda",
        "counts": {
            "pages_read": 1, "public_event_uids_seen": len(all_items)
        },
        "event_leads": published,
        "unclassified_editorial_research_only": unclassified,
        "next_cursor": None, "agenda_scan_complete": True,
        "no_publisher_bridge": True, "publication_ready": False,
        "public_writes": 0,
        "campaign_meta": {
            "source_sha256": "a" * 64, "scan_day": DAY.isoformat(),
            "agenda_index": 0, "segment": 0, "start_cursor": None,
        },
    }


def fake_rotation(lead, key, today, previous_checkpoint=None, **options):
    return {
        "schema": ROTATION_SCHEMA,
        "status": "private_daily_discovery_pass_exhausted",
        "private_checkpoint": {
            "event_uid": lead["event_uid"],
            "old_cursor": previous_checkpoint,
        },
        "organizer_identity_verified": False,
        "authoritative_duplicate_check": False,
        "source_rights_reviewed": False,
        "publisher_connected": False,
        "publication_ready": False, "public_writes": 0,
    }


def run(document=None, previous=None, *, budget=2, rotator=fake_rotation):
    return rotate_private_national_segment(
        document if document is not None else segment(),
        DAY, KEY, previous, event_budget=budget, rotator=rotator)


class NationalSegmentBridgeTests(unittest.TestCase):
    def test_all_known_and_unclassified_get_fair_round_robin_slots(self):
        doc = segment(known=(101, 102), unknown=(103, 104))
        rotator = Mock(side_effect=fake_rotation)
        first = run(doc, budget=2, rotator=rotator)
        self.assertEqual(first["category_proposed_considered"], 2)
        self.assertEqual(first["unclassified_considered"], 0)
        self.assertEqual(first["private_state"]["next_index"], 2)
        second = run(doc, first["private_state"],
                     budget=2, rotator=rotator)
        self.assertEqual(second["category_proposed_considered"], 0)
        self.assertEqual(second["unclassified_considered"], 2)
        self.assertEqual(second["private_state"]["next_index"], 0)
        self.assertEqual(second["full_passes_completed"], 1)
        self.assertEqual(second["status"],
                         "national_segment_full_discovery_completed_today")
        self.assertEqual([call.args[0]["event_uid"]
                          for call in rotator.call_args_list],
                         [101, 102, 103, 104])
        self.assertFalse(second["publication_ready"])
        self.assertEqual(second["public_writes"], 0)

    def test_no_fixed_genre_venue_or_agenda_names_for_unknown_candidates(self):
        doc = segment(known=(), unknown=(999551,))
        doc["unclassified_editorial_research_only"][0][
            "title"] = "L'invention sonore au pays des histoires"
        out = run(doc)
        self.assertEqual(out["unclassified_considered"], 1)
        self.assertEqual(out["completed_discovery_pass_this_cycle"], 1)
        self.assertFalse(out["organizer_ownership_verified"])

    def test_absent_location_or_session_is_held_not_deleted(self):
        doc = segment(known=(), unknown=(103, 104))
        doc["unclassified_editorial_research_only"][0][
            "city_unverified"] = None
        doc["unclassified_editorial_research_only"][1][
            "explicit_source_session_intervals"] = []
        backend = Mock(side_effect=AssertionError("should not call"))
        out = run(doc, rotator=backend)
        self.assertEqual(out["held_for_future_research"], 2)
        self.assertEqual([r["status"]
                          for r in out["private_state"]["items"]], [
            "missing_municipality_for_research",
            "missing_exact_sessions_for_research",
        ])
        self.assertEqual(out["full_passes_completed"], 1)
        backend.assert_not_called()
        next_pass = run(doc, out["private_state"], rotator=backend)
        self.assertEqual(next_pass["held_for_future_research"], 2)
        self.assertEqual(next_pass["full_passes_completed"], 2)

    def test_network_hold_does_not_starve_other_events(self):
        doc = segment(known=(101, 102), unknown=(103,))
        rotator = Mock(side_effect=lambda lead, *args, **kwargs: {
            **fake_rotation(lead, *args, **kwargs),
            "status": ("live_source_bootstrap_not_confirmed"
                       if lead["event_uid"] == 101
                       else "private_daily_discovery_pass_exhausted"),
        })
        a = run(doc, budget=2, rotator=rotator)
        self.assertEqual(a["private_state"]["next_index"], 2)
        b = run(doc, a["private_state"], budget=2, rotator=rotator)
        self.assertEqual(b["unclassified_considered"], 1)
        self.assertEqual(b["private_state"]["items"][0]["status"],
                         "live_source_bootstrap_not_confirmed")
        self.assertEqual(b["status"], "national_segment_research_in_progress")
        c = run(doc, b["private_state"], budget=2, rotator=rotator)
        self.assertEqual(c["events_considered_this_cycle"], 2)
        self.assertEqual(c["private_state"]["items"][0]["attempts"], 2)

    def test_changing_segment_identity_or_day_invalidates_cursor(self):
        doc = segment()
        first = run(doc)
        mutated = deepcopy(doc)
        mutated["event_leads"][0]["title"] = "Another artistic work"
        self.assertEqual(run(mutated, first["private_state"])["status"],
                         "stale_or_tampered_segment_cursor")
        self.assertEqual(rotate_private_national_segment(
            doc, date(2026, 11, 22), KEY, first["private_state"],
            rotator=fake_rotation)["status"],
            "invalid_private_campaign_segment")

    def test_forged_campaign_metadata_or_approvals_cannot_admit_items(self):
        doc = segment()
        for mutate in (
            lambda d: d.update(publication_ready=True),
            lambda d: d.update(no_publisher_bridge=False),
            lambda d: d["event_leads"][0].update(publication_ready=True),
            lambda d: d["campaign_meta"].update(
                start_cursor=["cursor with invalid whitespace", 42]),
            lambda d: d.update(agenda_uid=999),
        ):
            bad = deepcopy(doc)
            mutate(bad)
            out = run(bad)
            self.assertEqual(out["status"], "invalid_private_campaign_segment")
            self.assertEqual(out["public_writes"], 0)

    def test_duplicate_uid_between_unknown_and_known_is_rejected(self):
        doc = segment()
        doc["unclassified_editorial_research_only"][0][
            "event_uid"] = 101
        self.assertEqual(run(doc)["status"],
                         "invalid_private_campaign_segment")

    def test_forged_rotation_positive_permissions_are_held(self):
        doc = segment(known=(101,), unknown=())
        def unsafe(lead, *args, **kwargs):
            return dict(fake_rotation(lead, *args, **kwargs),
                        publisher_connected=True)
        out = run(doc, rotator=unsafe)
        self.assertEqual(out["private_state"]["items"][0]["status"],
                         "upstream_segment_candidate_untrusted")
        self.assertEqual(out["completed_discovery_pass_this_cycle"], 0)
        self.assertFalse(out["publication_ready"])

    def test_injected_state_and_wrong_id_block_before_network(self):
        doc = segment()
        first = run(doc)
        corrupted = deepcopy(first["private_state"])
        corrupted["items"][0]["event_uid"] += 100
        net = Mock(side_effect=AssertionError("unexpected network"))
        out = run(doc, corrupted, rotator=net)
        self.assertEqual(out["status"], "stale_or_tampered_segment_cursor")
        net.assert_not_called()
        corrupted = deepcopy(first["private_state"])
        corrupted["source_sha256"] = "0" * 64
        self.assertEqual(run(doc, corrupted)["status"],
                         "stale_or_tampered_segment_cursor")

    def test_live_intermediate_pipeline_runs_for_unknown_oa_event(self):
        item = event_lead()
        document = segment(known=(), unknown=(item["event_uid"],))
        unknown = document["unclassified_editorial_research_only"][0]
        unknown.update(item)
        # The national segment is bound to the exact new agenda discovered
        # by OA; it must never be cross-linked to a different agenda.
        document["agenda_uid"] = item["agenda_uid"]
        document["agenda_slug"] = item["agenda_slug"]
        unknown["editorial_category_proposal"] = None
        unknown["review_state"] = (
            "unknown_activity_requires_official_editorial_evidence")
        pages = {
            "https://www.ville-les-bois.fr/":
                "<html><body><a href='agenda/sorties'>Agenda</a></body></html>",
            MUNICIPAL: event_page(item, True),
            SOURCE: event_page(item, False),
        }
        options = {
            "directory_reader": lambda city: dila(),
            "html_reader": lambda url: pages[url],
            "oa_agenda_reader": lambda uid, key: {
                "uid": item["agenda_uid"], "slug": item["agenda_slug"]},
            "oa_event_reader": lambda uid, eid, key: source_event(item),
            "pages_per_cycle": 1, "sources_per_cycle": 1,
        }
        first = rotate_private_national_segment(
            document, DAY, KEY, rotator_options=options)
        self.assertEqual(first["unclassified_considered"], 1)
        self.assertEqual(first["private_state"]["items"][0]["status"],
                         "private_rotation_in_progress")
        second = rotate_private_national_segment(
            document, DAY, KEY, first["private_state"],
            rotator_options=options)
        self.assertEqual(second["status"],
                         "national_segment_full_discovery_completed_today")
        review = second["private_reviews"][0]["research"]
        self.assertEqual(review["source_candidates_examined"], 1)
        self.assertTrue(all(
            entry["three_source_exact_claims"]
            for entry in review["private_research_reviews"][0][
                "diagnostic"]["private_session_diagnostics"]))
        self.assertFalse(review["publication_ready"])

    def test_public_report_redacts_identifiers_and_exact_times(self):
        doc = segment()
        out = run(doc)
        public = public_redacted_national_segment_summary(out)
        redacted = json.dumps(public)
        for value in ("2026-12-05", "Ville-les-Bois", "agenda",
                      "Création artistique", "https://"):
            self.assertNotIn(value, redacted)
        with self.assertRaises(ValueError):
            public_redacted_national_segment_summary(
                dict(out, source_rights_reviewed=True))
        with self.assertRaises(ValueError):
            public_redacted_national_segment_summary(
                dict(out, publication_ready=True))


if __name__ == "__main__":
    unittest.main()
