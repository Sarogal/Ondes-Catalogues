"""Adversarial offline smoke tests: no key, real network or private lead data."""
from datetime import date
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_openagenda_v2_live_smoke import (
    diagnostic, ods_exact_uid_state, _valid_cases, MAX_ODS_BYTES,
)

CASE = {
    "lead": {
        "external_id": "12345678",
        "source_url": "https://openagenda.com/fr/ville-test/events/12345678_seance-test",
        "title": "Séance test", "date_start": "2026-12-05",
        "date_end": "2026-12-05", "city": "Villeurbanne",
        "venue": "Bibliothèque test",
    },
    "reviewed_agenda": {
        "agenda_slug": "ville-test", "agenda_uid": "919191",
        "timezone": "Europe/Paris",
    },
    "registered_venue": {
        "city": "Villeurbanne", "aliases": ["Bibliothèque test"],
        "lat": 45.758, "lng": 4.8998,
    },
}
EVENT = {
    "uid": 12345678, "state": 2, "status": 1,
    "attendanceMode": 1, "timezone": "Europe/Paris",
    "title": {"fr": "Séance test"},
    "description": {"fr": "Activité pour les enfants et les familles"},
    "rights": {
        "license": {"id": "etalab-2.0"},
        "licensor": {"name": "Organisme fictif"},
    },
    "location": {
        "name": "Bibliothèque test", "adminLevel4": "Villeurbanne",
        "countryCode": "FR", "latitude": 45.758, "longitude": 4.8998,
    },
    "timings": [
        {"begin": "2026-12-05T14:00:00+0100",
         "end": "2026-12-05T15:00:00+0100"},
    ],
}


class Response:
    def __init__(self, payload, redirected=False, status=200):
        self.payload = payload
        self.redirected = redirected
        self.status = status
        self.url = None
    def __call__(self, request, timeout):
        self.url = request.full_url
        self.request = request
        self.timeout = timeout
        return self
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def geturl(self):
        return self.url + "/redirect" if self.redirected else self.url
    def read(self, amount):
        self.max_read = amount
        return json.dumps(self.payload).encode("utf-8")


class ExactOdsRead(unittest.TestCase):
    def test_zero_results_exact_uid_absence(self):
        response = Response({"total_count": 0, "results": []})
        state = ods_exact_uid_state("12345678", opener=response)
        self.assertEqual(state, "uid_absent")
        self.assertEqual(response.timeout, 18)
        self.assertIn("uid%3D%2712345678%27", response.url)
        self.assertEqual(response.max_read, MAX_ODS_BYTES + 1)
        self.assertNotIn("key=", response.url)

    def test_one_matching_uid_is_present_not_missing(self):
        x = Response({"total_count": 1, "results": [{"uid": "12345678"}]})
        self.assertEqual(ods_exact_uid_state("12345678", opener=x), "uid_present")

    def test_ambiguous_redirected_unavailable_or_malformed_not_absent(self):
        for payload, redirect, status in (
            ({"total_count": 0, "results": []}, True, 200),
            ({"total_count": 0, "results": []}, False, 401),
            ({"results": []}, False, 200),
            ({"total_count": 1, "results": []}, False, 200),
        ):
            with self.subTest(payload=payload, redirect=redirect, status=status):
                self.assertEqual(
                    ods_exact_uid_state("12345678",
                                        opener=Response(payload, redirect, status)),
                    "unknown" if redirect or status != 200 or "total_count" not in payload
                    else "conflicting",
                )
        self.assertEqual(ods_exact_uid_state("12' OR 1=1"), "unknown")


class ConfidentialAggregation(unittest.TestCase):
    def test_live_structural_evidence_still_is_not_approval(self):
        def direct(a, e, key):
            self.assertEqual(a, "919191")
            self.assertEqual(e, "12345678")
            self.assertTrue(key.startswith("oa_pk_"))
            return EVENT
        x = diagnostic([CASE], "oa_pk_" + "x" * 30,
                       ods_lookup=lambda uid: "uid_absent",
                       direct_lookup=direct, today=date(2026, 11, 18))
        self.assertEqual(x["counts"]["direct_structural_evidence"], 1)
        self.assertEqual(x["counts"]["single_day_structure"], 1)
        self.assertEqual(x["counts"]["ods_uid_absent"], 1)
        self.assertFalse(x["approval_granted"])
        self.assertFalse(x["organizer_independently_attested"])
        self.assertEqual(x["public_writes"], 0)
        report = json.dumps(x)
        for disallowed in ("12345678", "919191", "Villeurbanne",
                           "openagenda.com", "oa_pk_", "Séance test"):
            self.assertNotIn(disallowed, report)

    def test_multi_day_one_uid_held_not_expanded(self):
        ev = dict(EVENT, timings=EVENT["timings"] + [{
            "begin": "2026-12-06T14:00:00+0100",
            "end": "2026-12-06T15:00:00+0100",
        }])
        report = diagnostic([CASE], "oa_pk_" + "x" * 30,
                            ods_lookup=lambda uid: "uid_absent",
                            direct_lookup=lambda a, e, k: ev,
                            today=date(2026, 11, 18))
        self.assertEqual(report["counts"]["multi_day_hold"], 1)
        self.assertEqual(report["checked"], 1)
        self.assertFalse(report["publisher_connected"])

    def test_direct_malformed_and_ods_failure_do_not_throw_private_context(self):
        def no_network(uid):
            raise RuntimeError("PRIVATE KEY INSIDE TRANSPORT")
        def bad_direct(a, e, k):
            raise RuntimeError("PRIVATE KEY INSIDE TRANSPORT")
        report = diagnostic([CASE], "oa_pk_" + "x" * 30,
                            ods_lookup=no_network, direct_lookup=bad_direct,
                            today=date(2026, 11, 18))
        out = json.dumps(report)
        self.assertEqual(report["counts"]["ods_unknown"], 1)
        self.assertEqual(report["counts"]["direct_unavailable_or_invalid"], 1)
        self.assertNotIn("PRIVATE KEY", out)

    def test_reject_unbounded_or_invalid_case_batches(self):
        for batch in ([], [CASE] * 13, [{}], [{"lead": {}}]):
            with self.subTest(batch=batch):
                with self.assertRaises(ValueError):
                    _valid_cases(batch)


if __name__ == "__main__":
    unittest.main()
