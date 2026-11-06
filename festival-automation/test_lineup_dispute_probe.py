"""Fail-closed tests for private festival roster discrepancies."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from lineup_dispute_probe import probe_disputes, load_curated
from source_qualification import (
    assess_candidate, visible_text, clean_url, normalized)
from watch_summary import render


EVENT = ("https://www.helloasso.com/associations/les-sapins-metaliks/"
         "evenements/les-sapins-metaliks-fest-viii")
ASSOCIATION = "https://www.helloasso.com/associations/les-sapins-metaliks"
CONFIG = {
    "sapins-metaliks-fest-viii-2026": {
        "public_artist": "Erocis",
        "alternative_artist": "Ogarya",
        "shared_artists": ["Muertissima", "Ritual", "Holls"],
        "urls": [EVENT, ASSOCIATION],
    },
}
EVENT_HTML = (
    "<h1>Les Sapins Metaliks Fest VIII</h1>"
    "<p>Du 14 au 15 novembre 2026</p>"
    "<p>Les Sapins Metaliks Fest VIII avec Ogarya, Muertissima, Ritual & Holls.</p>"
)
ASSOCIATION_HTML = (
    "<h1>Les Sapins Metaliks Fest VIII</h1>"
    "<p>Du 14 au 15 novembre 2026</p>"
    "<p>Les Sapins Metaliks Fest VIII avec Erocis, Muertissima, Ritual & Holls.</p>"
)


def leads(lineup=None):
    return [{
        "slug": "sapins-metaliks-fest-viii-2026",
        "name": "Les Sapins Metaliks Fest VIII",
        "organizer": "Les Sapins Métaliks",
        "start_date": "2026-11-14",
        "end_date": "2026-11-14",
        "lineup": lineup if lineup is not None
                  else ["Erocis", "Muertissima", "Ritual", "Holls"],
        "official_status": "NOT_VERIFIED",
        "allowed_to_publish": False,
        "candidate_urls": [EVENT, ASSOCIATION],
    }]


def run(rows=None, state=None, today="2026-11-05", specs=None, fetch=None, limit=2):
    return probe_disputes(
        leads() if rows is None else rows,
        {} if state is None else state,
        today, CONFIG if specs is None else specs,
        fetch if fetch is not None else lambda u: {
            EVENT: EVENT_HTML, ASSOCIATION: ASSOCIATION_HTML}[u],
        assess_candidate, visible_text, clean_url, normalized, limit=limit)


class DisputeProbeTests(unittest.TestCase):
    def test_both_association_pages_record_conflict_without_replacement(self):
        state = {}
        checks = run(state=state)
        self.assertEqual([x["signal"] for x in checks],
                         ["ALTERNATIVE_ONLY", "CATALOGUE_ONLY"])
        self.assertTrue(all(x["publication_authorized"] is False for x in checks))
        self.assertTrue(all(x["artist_update_authorized"] is False for x in checks))
        self.assertTrue(all(len(x["fingerprint_sha256"]) == 64 for x in checks))
        self.assertEqual(len(checks[0]["matched_shared_artists"]), 3)
        self.assertIn("lineup_dispute_last_checked", state)
        self.assertNotIn("artist_update_authorized", str(state))
        self.assertEqual(run(state=state), [])  # no 2nd network pass today

    def test_wrong_date_and_wrong_edition_never_signal_replacement(self):
        for html in (
            EVENT_HTML.replace("2026", "2025"),
            EVENT_HTML.replace("Fest VIII", "Fest VII"),
            "<script>" + EVENT_HTML + "</script><main>Voir nos autres dates</main>",
        ):
            with self.subTest(html=html):
                checks = run(fetch=lambda _: html, limit=1)
                self.assertEqual(checks[0]["signal"], "INSUFFICIENT_EDITION_MATCH")
                self.assertFalse(checks[0]["artist_update_authorized"])

    def test_names_without_shared_roster_context_are_not_evidence(self):
        result = run(fetch=lambda _: (
            "<h1>Les Sapins Metaliks Fest VIII</h1>"
            "<p>14 novembre 2026, Ogarya en première partie.</p>"), limit=1)
        self.assertEqual(result[0]["signal"], "INSUFFICIENT_ROSTER_CONTEXT")
        self.assertEqual(result[0]["matched_shared_artists"], [])

    def test_http_403_is_unknown_and_only_retried_next_day(self):
        state = {}
        attempted = []
        def denied(url):
            attempted.append(url)
            raise OSError("HTTP 403")
        checks = run(state=state, fetch=denied)
        self.assertEqual(len(attempted), 2)
        self.assertTrue(all(x["signal"] == "INACCESSIBLE_OR_UNKNOWN"
                            for x in checks))
        self.assertEqual(run(state=state, fetch=denied), [])
        self.assertEqual(len(attempted), 2)
        run(state=state, today="2026-11-06", fetch=denied)
        self.assertEqual(len(attempted), 4)

    def test_inactive_or_corrected_roster_disables_dispute_checks(self):
        checked = []
        def fetch(url):
            checked.append(url)
            return EVENT_HTML
        for lineup, today in [
            (["Ogarya", "Muertissima", "Ritual", "Holls"], "2026-11-05"),
            (["Erocis", "Muertissima", "Ritual", "Holls"], "2026-11-15"),
            (["Erocis", "Muertissima", "Ritual", "Holls"], "2026-10-01"),
        ]:
            self.assertEqual(run(rows=leads(lineup), today=today, fetch=fetch), [])
        self.assertEqual(checked, [])

    def test_rejects_off_queue_urls_and_untrusted_configuration(self):
        wrong = {s: {**v, "urls": ["https://other.example.org/stranger"]}
                 for s, v in CONFIG.items()}
        with self.assertRaises(ValueError):
            run(specs=wrong)
        for url in ["http://localhost/internal",
                    "https://127.0.0.1/private",
                    "https://www.helloasso.com.evil.fr/associations/les-sapins-metaliks"]:
            with self.subTest(url=url):
                bad = {s: {**v, "urls": [url]} for s, v in CONFIG.items()}
                with self.assertRaises(ValueError):
                    run(specs=bad)
        with self.assertRaises(ValueError):
            run(specs={"sapins-metaliks-fest-viii-2026": {
                **CONFIG["sapins-metaliks-fest-viii-2026"],
                "shared_artists": ["Holls", "Holls"]}})
        self.assertEqual(run(rows=[{**leads()[0], "allowed_to_publish": True}]), [])

    def test_summary_enforces_review_only_authorization(self):
        base = {"schema": "grossesondes.source-watch-report.v1",
                "date": "2026-11-05", "scanned": [], "unavailable": [],
                "coverage": {}, "source_reference_leads_review_only": [],
                "lineup_dispute_checks_review_only": run(limit=1)}
        summary = render(base)
        self.assertIn("Contrôles privés de programmations contradictoires", summary)
        self.assertIn("ALTERNATIVE_ONLY", summary)
        self.assertIn("publiées par cette veille : **0**", summary)
        base["lineup_dispute_checks_review_only"][0]["artist_update_authorized"] = True
        with self.assertRaises(ValueError):
            render(base)


if __name__ == "__main__":
    unittest.main()
