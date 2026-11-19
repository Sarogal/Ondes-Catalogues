"""Offline integration tests: OA v2 + independent GPS + organizer JSON-LD."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_openagenda_v2_joined_evidence import (
    diagnose_candidate, diagnose_batch,
)
from test_ptitesondes_openagenda_v2_geo_bridge import (
    SOURCE, PAGE, GEO_URL, BAN,
)
from test_ptitesondes_openagenda_v2_organizer_bridge import (
    LEAD as SAMPLE_LEAD, EVENT as SAMPLE_EVENT, AGENDA, ORGANIZER,
)

TODAY = date(2026, 11, 18)
LEAD = dict(SAMPLE_LEAD, city="Rouen", venue="Médiathèque des Familles")
EVENT = deepcopy(SAMPLE_EVENT)
EVENT["location"] = {
    "name": LEAD["venue"], "adminLevel4": LEAD["city"],
    "countryCode": "FR", "latitude": 49.42621, "longitude": 1.09697,
}
VISIBLE = (
    "<main><h1>Lecture pour enfants</h1>"
    "<p>Médiathèque des Familles — Rouen.</p>"
    "<p>Pour les enfants et familles.</p></main>"
)
SESSION = {
    "@context": "https://schema.org", "@type": "Event",
    "name": "Lecture pour enfants",
    "startDate": "2026-12-05T14:30:00+01:00",
    "eventStatus": "https://schema.org/EventScheduled",
    "location": {
        "@type": "Place", "name": "Médiathèque des Familles",
        "address": {"addressLocality": "Rouen"},
    },
}


def html(nodes=None, visible=VISIBLE):
    data = SESSION if nodes is None else nodes
    return "<html><body>" + visible + (
        "<script type='application/ld+json'>" +
        json.dumps(data) + "</script></body></html>")


def envelope():
    return {
        "lead": deepcopy(LEAD),
        "api_event": deepcopy(EVENT),
        "reviewed_agenda": deepcopy(AGENDA),
        "reviewed_venue_source": deepcopy(SOURCE),
        "venue_page": deepcopy(PAGE),
        "geocoder_request_url": GEO_URL,
        "geojson": deepcopy(BAN),
        "reviewed_organizer": deepcopy(ORGANIZER),
        "organizer_page": {"url": ORGANIZER["exact_url"], "html": html()},
    }


class JoinedEvidenceContract(unittest.TestCase):
    def test_real_adapters_combined_jsonld_without_visible_clocks(self):
        r = diagnose_candidate(envelope(), TODAY)
        self.assertEqual(r["stage"], "structural_evidence_complete_other_gates_pending")
        self.assertTrue(r["venue_verified"])
        self.assertTrue(r["openagenda_direct_verified"])
        self.assertTrue(r["organizer_session_verified"])
        self.assertTrue(r["family_audience_confirmed"])
        self.assertFalse(r["approval_granted"])
        self.assertFalse(r["publisher_connected"])
        self.assertEqual(r["public_writes"], 0)
        self.assertIn("reuse_rights", r["outstanding_gates"])
        self.assertIn("historic_deduplication", r["outstanding_gates"])
        self.assertNotIn("additions", r)

    def test_missing_venue_registry_or_address_is_blocked(self):
        for mutation in ("pin", "url", "geo"):
            c = envelope()
            if mutation == "pin":
                c["reviewed_venue_source"]["approved_host"] = "attacker.invalid"
            elif mutation == "url":
                c["venue_page"]["url"] = "https://attacker.invalid/event"
            else:
                c["geojson"] = {"type": "FeatureCollection", "features": []}
            with self.subTest(mutation=mutation):
                r = diagnose_candidate(c, TODAY)
                self.assertEqual(r["stage"], "independent_venue_not_verified")
                self.assertFalse(r["source_evidence_structurally_complete"])

    def test_collector_source_claim_cannot_override_reviewed_pins(self):
        c = envelope()
        c["lead"].update({
            "approved_host": "attacker.invalid",
            "exact_url": "https://attacker.invalid/event",
            "geography_verified": True, "approval_granted": True,
        })
        c["reviewed_venue_source"]["approved_host"] = "attacker.invalid"
        r = diagnose_candidate(c, TODAY)
        self.assertEqual(r["stage"], "independent_venue_not_verified")
        self.assertFalse(r["approval_granted"])

    def test_wrong_organizer_host_and_event_session_hold(self):
        for variant in ("host", "clock", "adult"):
            c = envelope()
            if variant == "host":
                c["reviewed_organizer"]["approved_host"] = "attacker.invalid"
            elif variant == "clock":
                c["organizer_page"]["html"] = html(
                    dict(SESSION, startDate="2026-12-06T14:30:00+01:00"))
            else:
                c["organizer_page"]["html"] = html(
                    visible=VISIBLE + "<p>Réservé aux adultes uniquement</p>")
            with self.subTest(variant=variant):
                r = diagnose_candidate(c, TODAY)
                self.assertEqual(r["stage"], "organizer_session_not_confirmed")
                self.assertFalse(r["source_evidence_structurally_complete"])

    def test_same_day_multiple_sessions_require_all_times(self):
        c = envelope()
        c["api_event"]["timings"].append({
            "begin": "2026-12-05T16:00:00+0100",
            "end": "2026-12-05T17:00:00+0100",
        })
        self.assertEqual(diagnose_candidate(c, TODAY)["stage"],
                         "organizer_session_not_confirmed")
        second = dict(SESSION, startDate="2026-12-05T16:00:00+01:00")
        c["organizer_page"]["html"] = html({"@graph": [SESSION, second]})
        self.assertEqual(diagnose_candidate(c, TODAY)["stage"],
                         "structural_evidence_complete_other_gates_pending")

    def test_uid_with_multiple_days_must_be_grouped_not_split(self):
        c = envelope()
        c["api_event"]["timings"].append({
            "begin": "2026-12-06T16:00:00+0100",
            "end": "2026-12-06T17:00:00+0100",
        })
        r = diagnose_candidate(c, TODAY)
        self.assertEqual(r["stage"], "multi_day_grouping_required")
        self.assertFalse(r["source_evidence_structurally_complete"])

    def test_wrong_uid_or_timezone_fails_direct_gate(self):
        for v in ("uid", "timezone"):
            c = envelope()
            if v == "uid":
                c["api_event"]["uid"] = 999999
            else:
                c["api_event"]["timezone"] = "America/New_York"
            self.assertEqual(
                diagnose_candidate(c, TODAY)["stage"],
                "openagenda_identity_or_sessions_not_verified")

    def test_fail_closed_invalid_case_and_no_raw_exception(self):
        for item in (None, {}, {"lead": {"source_url": "secret"}}, "oops"):
            r = diagnose_candidate(item, TODAY)
            self.assertEqual(r["stage"], "invalid_case")
            self.assertEqual(r["public_writes"], 0)
            self.assertNotIn("secret", repr(r))

    def test_aggregate_anonymous_no_candidate_contents(self):
        good = envelope()
        bad = envelope()
        bad["organizer_page"]["url"] = "https://private.example/secret"
        r = diagnose_batch([good, bad], TODAY)
        self.assertEqual(r["checked_leads"], 2)
        self.assertEqual(sum(r["reason_counts"].values()), 2)
        self.assertFalse(r["approval_granted"])
        self.assertFalse(r["contains_candidate_identifiers"])
        for forbidden in ("Lecture pour enfants", "Rouen", "12345678",
                          "https://", "private.example", "venue_page"):
            self.assertNotIn(forbidden, repr(r))

    def test_bound_and_publisher_invariance(self):
        with self.assertRaises(ValueError):
            diagnose_batch([], TODAY)
        with self.assertRaises(ValueError):
            diagnose_batch([envelope()] * 61, TODAY)
        for case in (envelope(), {"lead": {}}):
            r = diagnose_candidate(case, TODAY)
            self.assertFalse(r["approval_granted"])
            self.assertFalse(r["publisher_connected"])
            self.assertEqual(r["public_writes"], 0)


if __name__ == "__main__":
    unittest.main()
