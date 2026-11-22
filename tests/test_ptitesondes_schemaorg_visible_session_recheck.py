"""Schema.org promotion tests: fresh trusted index + visible exact sessions."""
from copy import deepcopy
from datetime import date, datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from ptitesondes_schemaorg_private_intake import (
    _from_lead, reconcile_schemaorg_hints, _stage_private, _file,
)
from ptitesondes_schemaorg_visible_session_recheck import (
    recheck_schemaorg_visible_sessions,
)
from ptitesondes_schemaorg_visible_recheck_cycle import run_recheck
from ptitesondes_real_family_source_adapters import parse_montpellier_mpt_detail
from ptitesondes_institutional_source_policy import MANIFEST_PATH
from test_ptitesondes_html_index_detail_funnel import (
    MPT_TEMPLATE, ONE, PIN,
)
from test_ptitesondes_nonmusical_html_gate_router import CONTEXT

TODAY = date(2026, 11, 20)
NOW = datetime(2026, 11, 20, 14, 0, tzinfo=ZoneInfo("Europe/Paris"))
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
PINS = {"schema": "ptitesondes.schemaorg_trusted_source_timezones.v1",
        "entries": [{"source_id": "montpellier-mpt", "timezone": "Europe/Paris"}]}


def hints():
    leads = parse_montpellier_mpt_detail(MPT_TEMPLATE, ONE, TODAY)
    out = []
    for lead in leads:
        raw = {
            "source_url": lead["source_url"], "title": lead["title"],
            "city": lead["city"], "venue": lead["venue"],
            "date_start": lead["date_start"],
            "start_local": lead["start_local"],
            "category_hint_only": lead["category"],
            "official_session_independently_proved": False,
            "organizer_independently_attested": False,
            "approved": False, "published": False,
        }
        out.append(_from_lead(raw, TODAY))
    return out


def fresh_index(pin):
    return {"stage": "routing_suggestions_only",
            "private_routing_proposals": [
                {"url": ONE, "approved": False}]}


class SchemaOrgVisibleRecheckTests(unittest.TestCase):
    def verify(self, candidates=None, index_reader=fresh_index,
               child_reader=None, **kwargs):
        if child_reader is None:
            child_reader = lambda p: {"url": p["exact_url"], "html": MPT_TEMPLATE}
        return recheck_schemaorg_visible_sessions(
            [], hints() if candidates is None else candidates,
            TODAY, MANIFEST, PINS, deepcopy(CONTEXT),
            index_reader=index_reader,
            child_reader=child_reader, **kwargs)

    def test_two_clock_slots_rechecked_from_one_current_child(self):
        fetched = []
        def read(pin):
            fetched.append(pin["exact_url"])
            return {"url": pin["exact_url"], "html": MPT_TEMPLATE}
        result = self.verify(child_reader=read)
        report = result["report"]
        self.assertEqual(report["source_index_rechecked"], 1)
        self.assertEqual(report["child_pages_refetched"], 1)
        self.assertEqual(fetched, [ONE])
        self.assertEqual(report["visible_same_block_sessions"], 2)
        self.assertEqual(report["new_private_review_sessions"], 2)
        self.assertEqual(len(result["private_review_queue"]), 2)
        self.assertEqual(
            {r["start_local"] for r in result["private_review_queue"]},
            {"09:15", "10:30"})
        self.assertTrue(all(r["safe_to_publish"] is False
                            and r["approved"] is False
                            and r["published"] is False
                            for r in result["private_review_queue"]))

    def test_different_index_cannot_be_faked_from_hint(self):
        missing = lambda pin: {
            "stage": "routing_suggestions_only",
            "private_routing_proposals": [],
        }
        result = self.verify(index_reader=missing)
        self.assertEqual(result["report"]["unlisted_on_current_index_held"], 2)
        self.assertEqual(result["report"]["child_pages_refetched"], 0)
        self.assertEqual(result["private_review_queue"], [])

    def test_rejected_source_index_never_promotes(self):
        result = self.verify(index_reader=lambda pin: {
            "stage": "index_unavailable",
            "private_routing_proposals": [{"url": ONE, "approved": False}],
        })
        self.assertEqual(result["report"]["source_indexes_unavailable"], 1)
        self.assertEqual(result["private_review_queue"], [])

    def test_structured_jsonld_claim_without_visible_clock_stays_a_hint(self):
        result = self.verify(child_reader=lambda pin: {
            "url": ONE,
            "html": "<html><body><main>Atelier enfants au centre culturel</main>"
                    "<script type='application/ld+json'>"
                    + json.dumps({
                        "@type": "Event", "name": "Atelier enfants",
                        "startDate": "2026-11-22T09:15:00+01:00",
                    })
                    + "</script></body></html>",
        })
        self.assertEqual(result["report"]["visible_same_block_sessions"], 0)
        self.assertEqual(result["report"]["without_visible_exact_session_held"], 2)
        self.assertEqual(result["private_review_queue"], [])

    def test_unclassified_hints_stay_in_discovery_queue(self):
        a = hints()
        original = a[0]
        a[0] = _from_lead({
            "source_url": original["source_url"],
            "title": original["title"], "city": original["city"],
            "venue": original["venue"], "date_start": original["date_start"],
            "start_local": original["start_local"],
            "category_hint_only": None,
            "official_session_independently_proved": False,
            "organizer_independently_attested": False,
            "approved": False, "published": False,
        }, TODAY)
        result = self.verify(candidates=a)
        self.assertEqual(result["report"]["unclassified_hints_held"], 1)
        self.assertEqual(result["report"]["new_private_review_sessions"], 1)

    def test_explicitly_restricted_source_cannot_enter_review(self):
        manifest = deepcopy(MANIFEST)
        manifest["entries"][0]["reuse_policy_state"] = "restricted_do_not_reuse"
        result = recheck_schemaorg_visible_sessions(
            [], hints(), TODAY, manifest, PINS, deepcopy(CONTEXT),
            index_reader=fresh_index,
            child_reader=lambda pin: {"url": ONE, "html": MPT_TEMPLATE})
        self.assertEqual(result["report"]["unregistered_source_hints_held"], 2)
        self.assertEqual(result["private_review_queue"], [])

    def test_previous_private_reviews_survive_index_outage(self):
        first = self.verify()["private_review_queue"]
        r = recheck_schemaorg_visible_sessions(
            first, hints(), TODAY, MANIFEST, PINS, deepcopy(CONTEXT),
            index_reader=lambda pin: {"stage": "unavailable"},
            child_reader=lambda pin: {"url": ONE, "html": MPT_TEMPLATE})
        self.assertEqual(r["private_review_queue"], first)
        self.assertEqual(r["report"]["source_indexes_unavailable"], 1)

    def test_public_report_never_contains_identifiers_or_source(self):
        result = self.verify()
        dump = json.dumps(result["report"], ensure_ascii=False)
        for private in ("Montpellier", "09:15", "10:30", ONE,
                        "MPT", "html-review-", "source_url",
                        "2026-11-22", "Albert Camus"):
            self.assertNotIn(private, dump)
        self.assertFalse(result["report"]["publisher_connected"])
        self.assertFalse(result["report"]["approved"])
        self.assertEqual(result["report"]["public_writes"], 0)

    def test_live_catalogue_mismatch_blocks_stage_even_if_hints_are_good(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            subprocess.run(
                ["git", "init", "-q", "-b", "automation/ptitesondes-intake",
                 str(root)], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(root), "remote", "add", "origin",
                 "https://github.com/Sarogal/PtitesOndes"],
                check=True, capture_output=True)
            path = _file(root)
            _stage_private(path, hints())
            with patch(
                "ptitesondes_schemaorg_visible_recheck_cycle._independent_context"
            ) as get_context:
                with self.assertRaisesRegex(
                        ValueError, "schemaorg_live_catalogue_mismatch"):
                    run_recheck(
                        root, NOW, mode="stage",
                        live_checker=lambda now: {
                            "same_data_as_checked_out_repository": False})
                get_context.assert_not_called()
            self.assertFalse((root / "automation-intake/ptitesondes/"
                              "html-review-candidates.json").exists())

    def test_private_runner_preview_only_returns_anonymous_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            subprocess.run(
                ["git", "init", "-q", "-b", "automation/ptitesondes-intake",
                 str(root)], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(root), "remote", "add", "origin",
                 "https://github.com/Sarogal/PtitesOndes"],
                check=True, capture_output=True)
            _stage_private(_file(root), hints())
            with patch(
                    "ptitesondes_schemaorg_visible_recheck_cycle._independent_context",
                    return_value=deepcopy(CONTEXT)), patch(
                    "ptitesondes_schemaorg_visible_recheck_cycle._validated_manifest",
                    return_value=deepcopy(MANIFEST)), patch(
                    "ptitesondes_schemaorg_visible_recheck_cycle._validate_pins",
                    return_value=deepcopy(PINS)):
                report = run_recheck(
                    root, NOW, mode="preview",
                    live_checker=lambda now: {
                        "same_data_as_checked_out_repository": True,
                        "live_event_count": 549, "local_event_count": 549,
                        "public_writes": 0, "publication_ready": False,
                        "approval_granted": False,
                    },
                    review_runner=lambda existing, hints, today, manifest, pins, context, **kw: {
                        "private_review_queue": existing,
                        "report": {
                            "public_writes": 0, "publisher_connected": False,
                            "publication_ready": False, "selected_hints": len(hints),
                        },
                    })
            self.assertEqual(report["selected_hints"], 2)
            self.assertTrue(report["live_catalogue_refetched_matching"])
            self.assertNotIn("Montpellier", json.dumps(report))
            self.assertFalse((root / "automation-intake/ptitesondes/"
                              "html-review-candidates.json").exists())


if __name__ == "__main__":
    unittest.main()
