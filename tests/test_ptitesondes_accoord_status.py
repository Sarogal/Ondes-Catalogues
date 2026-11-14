"""Private per-date Accoord diagnosis: no data leakage or publication side effects."""
from datetime import date
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ptitesondes_accoord_status import SCHEMA, UID, build

TODAY = date(2026, 11, 14)
URL = "https://openagenda.com/nantesmetropole/events/contes-and-comptines"


def lead(day, url=URL):
    return {
        "external_id": UID, "collector": "openagenda-v2",
        "title": "Contes & comptines", "source_url": url,
        "date_start": day, "date_end": day,
        "city": "Nantes",
        "venue": "Centre socioculturel des Bourderies - ACCOORD",
    }


def preview(*days):
    return {"additions": [
        {"id": "openagenda-813941-" + day, "date_start": day}
        for day in days
    ]}


def report(details=None, accepted=0):
    details = [] if details is None else details
    return {
        "date": TODAY.isoformat(), "mode": "preview_no_public_write",
        "checked": len(details) + accepted,
        "accepted_preflight": accepted, "details": details,
    }


def inputs():
    days = [
        "2026-11-18", "2026-11-25", "2026-12-02",
        "2026-12-09", "2026-12-16", "2026-12-23",
        "2026-12-30",
    ]
    backlog = [lead(d) for d in days] + [
        lead("2026-11-04"),
        dict(lead("2026-12-05"), external_id="111"),
    ]
    backlog[-2] = dict(backlog[-2], source_url="https://example.invalid/bad")
    public = {"events": [{
        "id": "openagenda-813941-2026-11-25",
        "title": "Contes & comptines",
        "date_start": "2026-11-25", "date_end": "2026-11-25",
        "city": "Nantes", "venue": "Centre socioculturel des Bourderies - ACCOORD",
        "source_url": URL,
    }], "updated_at": "2026-11-14T11:49:25+01:00"}
    patch = preview("2026-12-02")
    preflight = preview("2026-12-09")
    decision = {
        "date": "2026-12-16", "source_url": URL,
        "status": "unverified",
        "reason": "date complète non confirmée avec texte privé NE_PAS_COPIER",
    }
    # Legitimate UID but untrusted collector URL should remain unreviewable.
    backlog[-3] = lead("2026-12-30", url="https://example.invalid/bad")
    return backlog, public, patch, preflight, report([decision], 1)


class AccoordStatusTests(unittest.TestCase):
    def test_statuses_are_mutually_exclusive_and_no_evidence_leaks(self):
        data = build(*inputs(), previous=None, today=TODAY)
        self.assertEqual(data["schema"], SCHEMA)
        self.assertEqual(data["series_uid"], UID)
        self.assertEqual(data["total_future"], 7)
        status = {x["date"]: x for x in data["sessions"]}
        self.assertEqual(status["2026-11-18"]["status"], "awaiting_batch")
        self.assertEqual(status["2026-11-25"]["status"], "published")
        self.assertEqual(status["2026-12-02"]["status"], "approved_private")
        self.assertEqual(status["2026-12-09"]["status"], "prevalidated_not_approved")
        self.assertEqual(status["2026-12-16"]["status"], "checked_not_approved")
        self.assertEqual(status["2026-12-16"]["last_reason_group"], "date_or_time")
        self.assertEqual(status["2026-12-30"]["status"], "blocked_at_entry")
        self.assertEqual(data["status_counts"], {
            "approved_private": 1, "awaiting_batch": 2,
            "blocked_at_entry": 1, "checked_not_approved": 1,
            "prevalidated_not_approved": 1, "published": 1,
        })
        encoded = json.dumps(data)
        for forbidden in ("https://", "Contes & comptines", "NE_PAS_COPIER",
                          "source_url", "geo_source", "lat", "lng"):
            self.assertNotIn(forbidden, encoded)

    def test_earlier_rejection_survives_rotation_but_state_does_not(self):
        backlog, public, patch, preflight, current = inputs()
        original = build(backlog, public, patch, preflight, current, None, TODAY)
        fresh = build(backlog, public, patch, preview(),
                      report(), original, TODAY)
        by_day = {x["date"]: x for x in fresh["sessions"]}
        self.assertEqual(by_day["2026-12-16"]["status"], "awaiting_batch")
        self.assertEqual(by_day["2026-12-16"]["last_result"], "rejected")
        self.assertEqual(by_day["2026-12-16"]["last_reason_group"], "date_or_time")
        self.assertEqual(by_day["2026-12-16"]["last_reviewed_on"], TODAY.isoformat())

    def test_future_published_wins_over_stale_prior_rejection(self):
        backlog, public, patch, preflight, current = inputs()
        prior = build(backlog, public, patch, preflight, current, None, TODAY)
        public["events"].append(dict(
            public["events"][0], id="openagenda-813941-2026-12-16",
            date_start="2026-12-16", date_end="2026-12-16"))
        result = build(backlog, public, patch, preview(), report(), prior, TODAY)
        row = next(x for x in result["sessions"] if x["date"] == "2026-12-16")
        self.assertEqual(row["status"], "published")
        self.assertEqual(row["last_reason_group"], "date_or_time")

    def test_reject_bad_report_and_inconsistent_prevalidation(self):
        backlog, public, patch, preflight, current = inputs()
        with self.assertRaises(ValueError):
            build(backlog, public, patch, preflight, report([], 0), None, TODAY)
        current["date"] = "2026-11-13"
        with self.assertRaises(ValueError):
            build(backlog, public, patch, preflight, current, None, TODAY)

    def test_refuse_arbitrary_prior_reason_and_unmatched_raw_decisions(self):
        backlog, public, patch, preflight, current = inputs()
        previous = build(backlog, public, patch, preflight, current, None, TODAY)
        bad = json.loads(json.dumps(previous))
        row = next(x for x in bad["sessions"] if x["date"] == "2026-12-16")
        row["last_reason_group"] = "secret:raw_url"
        with self.assertRaises(ValueError):
            build(backlog, public, patch, preview(), report(), bad, TODAY)
        # Another UID/URL may be checked but MUST NOT reclassify Accoord.
        alien = {"date": "2026-12-23",
                 "source_url": "https://openagenda.com/another/events/x",
                 "status": "unverified", "reason": "horaire manquant"}
        data = build(backlog, public, patch, preview(),
                     report([alien]), None, TODAY)
        matched = next(x for x in data["sessions"] if x["date"] == "2026-12-23")
        self.assertEqual(matched["status"], "awaiting_batch")

    def test_expired_or_ambiguous_sessions_are_not_guessed(self):
        backlog, public, patch, preflight, current = inputs()
        future = [x for x in backlog if x["date_start"] >= TODAY.isoformat()
                  and x["external_id"] == UID]
        self.assertEqual(len(future), 7)
        corrupt = [dict(x) for x in backlog]
        corrupt[0]["date_end"] = "2026-11-19"
        with self.assertRaises(ValueError):
            build(corrupt, public, patch, preflight, current, None, TODAY)


if __name__ == "__main__":
    unittest.main()
