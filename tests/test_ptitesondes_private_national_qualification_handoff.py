"""Offline adversarial tests: national events become UNVERIFIED private intake leads."""
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ptitesondes_private_national_qualification_handoff import (
    SCHEMA, handoff, main, verified_report, _canonical_url,
)
from ptitesondes_openagenda_public_agenda_index import SCHEMA as INDEX_SCHEMA

DAY = date(2026, 11, 21)
KEY = "oa_pk_national_handoff_offline_key"
DIGEST = "a" * 64
AGENDA = {"agenda_uid": 719191, "agenda_slug": "agenda-demo"}


def index():
    return {
        "schema": INDEX_SCHEMA,
        "mode": "private_index_readonly_discovery_not_admission",
        "publication_ready": False, "public_writes": 0,
        "new_agenda_candidates": [{
            **AGENDA, "source_identity_only": True, "publisher_enabled": False,
        }],
    }


def event(uid=12345, title="Les histoires du ciel",
          description="Spectacle de marionnettes pour enfants et familles.",
          city="Montpellier", venue="Place de la Comédie",
          country="FR", status=1, day="2026-12-12"):
    return {
        "uid": uid, "title": {"fr": title},
        "description": {"fr": description}, "state": 2,
        "status": status, "removed": False,
        "canonicalUrl": f"https://openagenda.com/agenda-demo/events/{uid}_les-histoires-du-ciel",
        "location": {"adminLevel4": city, "name": venue,
                     "countryCode": country},
        "timings": [{
            "begin": f"{day}T10:00:00+01:00",
            "end": f"{day}T11:00:00+01:00",
        }],
    }


def original(uid=12345, title="Les histoires du ciel", days=None):
    return {
        "agenda_uid": AGENDA["agenda_uid"],
        "agenda_slug": AGENDA["agenda_slug"],
        "event_uid": uid, "title": title,
        "editorial_category_proposal": "spectacle-jeunesse",
        "explicit_source_session_days": days or ["2026-12-12"],
        "publication_ready": False, "public_writes": 0,
    }


def segment(leads=None):
    if leads is None:
        leads = [original()]
    return {
        "schema": "ptitesondes.private_oa_agenda_event_exploration.v1",
        "mode": "private_research_event_leads_only",
        **AGENDA,
        "counts": {"pages_read": 1, "public_event_uids_seen": len(leads)},
        "event_leads": leads,
        "next_cursor": None, "agenda_scan_complete": True,
        "no_publisher_bridge": True, "publication_ready": False,
        "public_writes": 0,
        "campaign_meta": {
            "source_sha256": DIGEST, "scan_day": DAY.isoformat(),
            "agenda_index": 0, "segment": 0, "start_cursor": None,
        },
    }


class PrivateNationalHandoffTests(unittest.TestCase):
    def test_numberless_public_square_becomes_backlog_not_public_patch(self):
        calls = []
        def fetch(agenda_uid, event_uid, key):
            calls.append((agenda_uid, event_uid, key))
            return event()
        result = handoff(index(), DIGEST, segment(), DAY, KEY, fetcher=fetch)
        self.assertEqual(calls, [(719191, 12345, KEY)])
        self.assertEqual(result["schema"], SCHEMA)
        self.assertEqual(result["mode"], "private_intake_research_only")
        lead, = result["backlog_leads"]
        self.assertEqual(set(lead), {
            "title", "source_url", "date_start", "date_end", "city",
            "venue", "reason", "collector", "external_id",
        })
        self.assertEqual(lead["venue"], "Place de la Comédie")
        self.assertEqual(lead["collector"], "openagenda-v2")
        self.assertEqual(lead["external_id"], "12345")
        self.assertEqual(lead["date_start"], "2026-12-12")
        self.assertFalse(result["publication_ready"])
        self.assertFalse(result["safe_to_publish"])
        self.assertFalse(result["publisher_connected"])
        self.assertEqual(result["public_writes"], 0)
        self.assertNotIn("additions", result)
        self.assertNotIn("approved", result)

    def test_rechecks_direct_source_not_only_untrusted_research_report(self):
        for changed in (
            event(uid=22222), event(title="Autre œuvre"),
            event(status=4), {**event(), "state": 1},
            event(description="Goûter familial au parc pour enfants",
                  title="Goûter familial au parc"),
            event(country="BE"), event(city=None, venue="Lieu temporaire"),
            {**event(), "canonicalUrl": "https://example.org/agenda-demo/events/12345_fake"},
            {**event(), "canonicalUrl": "https://openagenda.com/agenda-demo/events/12345_fake?secret=1"},
        ):
            with self.subTest(changed=changed):
                out = handoff(index(), DIGEST, segment(), DAY, KEY,
                              fetcher=lambda *_: changed)
                self.assertEqual(out["backlog_leads"], [])
                self.assertEqual(len(out["research_holds"]), 1)
                self.assertFalse(out["publication_ready"])
                self.assertEqual(out["public_writes"], 0)

    def test_reprogrammed_event_kept_as_research_hold(self):
        result = handoff(index(), DIGEST, segment(), DAY, KEY,
                         fetcher=lambda *_: event(status=2))
        self.assertEqual(result["backlog_leads"], [])
        self.assertEqual(result["research_holds"][0]["reason"],
                         "rescheduled_event_needs_independent_confirmation")

    def test_overseas_candidate_kept_without_inventing_coordinates(self):
        out = handoff(index(), DIGEST, segment(), DAY, KEY,
                      fetcher=lambda *_: event(country="GP", city="Pointe-à-Pitre",
                                               venue="Place de la Victoire"))
        one, = out["backlog_leads"]
        self.assertEqual(one["city"], "Pointe-à-Pitre")
        self.assertEqual(one["venue"], "Place de la Victoire")
        self.assertNotIn("lat", one)
        self.assertNotIn("lng", one)
        self.assertNotIn("geo_verified_at", one)

    def test_changed_dates_are_not_silently_added(self):
        api = event()
        api["timings"].append({
            "begin": "2026-12-13T10:00:00+01:00",
            "end": "2026-12-13T11:00:00+01:00",
        })
        out = handoff(index(), DIGEST, segment(), DAY, KEY,
                      fetcher=lambda *_: api)
        self.assertEqual([x["date_start"] for x in out["backlog_leads"]],
                         ["2026-12-12"])
        self.assertEqual(out["research_holds"][0]["reason"],
                         "additional_dates_need_research")
        shifted = event(day="2026-12-14")
        out = handoff(index(), DIGEST, segment(), DAY, KEY,
                      fetcher=lambda *_: shifted)
        self.assertEqual(out["backlog_leads"], [])
        self.assertEqual(out["research_holds"][0]["reason"],
                         "all_source_session_days_changed")

    def test_bounded_offset_resumes_without_assuming_known_agendas(self):
        leads = [original(uid=i) for i in range(100, 123)]
        fetch = Mock(side_effect=lambda agenda_uid, uid, key: event(uid=uid))
        a = handoff(index(), DIGEST, segment(leads), DAY, KEY,
                    max_fetch=12, fetcher=fetch)
        b = handoff(index(), DIGEST, segment(leads), DAY, KEY,
                    offset=a["next_offset"], max_fetch=12, fetcher=fetch)
        self.assertEqual(a["events_examined"], 12)
        self.assertEqual(b["events_examined"], 11)
        self.assertFalse(a["finished_segment"])
        self.assertTrue(b["finished_segment"])
        self.assertEqual(fetch.call_count, 23)
        self.assertEqual(len(a["backlog_leads"] + b["backlog_leads"]), 23)
        with self.assertRaisesRegex(ValueError, "invalid_private_handoff_arguments"):
            handoff(index(), DIGEST, segment(leads), DAY, KEY,
                    max_fetch=100, fetcher=fetch)

    def test_malformed_or_forged_reports_fail_before_network(self):
        bads = (
            {**segment(), "publication_ready": True},
            {**segment(), "no_publisher_bridge": False},
            {**segment(), "campaign_meta": {
                **segment()["campaign_meta"], "source_sha256": "b" * 64}},
            {**segment(), "campaign_meta": {
                **segment()["campaign_meta"], "scan_day": "2026-11-20"}},
            {**segment(), "event_leads": [original(), original()]},
            {**segment(), "event_leads": [{**original(), "public_writes": 1}]},
            {**segment(), "event_leads": [{**original(), "event_uid": True}]},
            {**segment(), "event_leads": [{**original(), "agenda_uid": 999}]},
        )
        network = Mock(side_effect=AssertionError("No API on forged report"))
        for bad in bads:
            with self.subTest(bad=str(bad)[:100]):
                with self.assertRaises(ValueError):
                    handoff(index(), DIGEST, bad, DAY, KEY, fetcher=network)
        network.assert_not_called()

    def test_research_failure_does_not_publish_or_log_sensitive_details(self):
        out = handoff(index(), DIGEST, segment(), DAY, KEY,
                      fetcher=Mock(side_effect=ValueError(
                          "private event identity with hidden token")))
        self.assertEqual(out["backlog_leads"], [])
        self.assertEqual(out["research_holds"][0]["reason"],
                         "direct_event_read_unavailable")
        self.assertNotIn("token", json.dumps(out))

    def test_dry_run_requires_private_reports_and_never_contacts_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = index()
            raw = json.dumps(doc).encode("utf-8")
            report = segment()
            report["campaign_meta"]["source_sha256"] = sha256(raw).hexdigest()
            src = root / "index.json"
            inp = root / "segment.json"
            dst = root / "handoff.json"
            src.write_bytes(raw)
            inp.write_text(json.dumps(report), encoding="utf-8")
            with patch.object(sys, "argv", [
                "prog", "--private-agenda-index-report", str(src),
                "--private-segment-report", str(inp),
                "--private-output-report", str(dst),
                "--day", str(DAY),
            ]), patch("ptitesondes_private_national_qualification_handoff.read_direct_v2",
                       side_effect=AssertionError("No network in default dryrun")):
                main()
            self.assertFalse(dst.exists())


if __name__ == "__main__":
    unittest.main()
