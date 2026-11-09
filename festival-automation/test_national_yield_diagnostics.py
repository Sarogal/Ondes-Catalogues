"""Offline regression tests for private festival yield diagnostics."""
import unittest

from national_yield_diagnostics import diagnose, _watch

TODAY = "2026-11-09"


class YieldTests(unittest.TestCase):
    def state(self):
        return {"schema": "grossesondes.source-watch.v1"}

    def review(self):
        return {
            "schema": "grossesondes.national-editorial-reconciliation-private.v1",
            "as_of": TODAY, "safe_to_publish": False,
            "publication_authorized": False, "publications": 0,
            "dossiers_count": 2, "editorial_drafts_count": 1,
            "public_editions_count": 124, "historic_references_count": 173,
            "dossiers": [
                {"status": "RESEARCH_REQUIRED", "review_only": True,
                 "safe_to_publish": False, "publication_authorized": False,
                 "missing_checks": ["dates_missing", "organizer_missing"]},
                {"status": "PRIMARY_DATE_CLAIM_REVIEW", "review_only": True,
                 "safe_to_publish": False, "publication_authorized": False,
                 "missing_checks": ["organizer_missing"]},
            ],
        }

    def test_unobserved_is_not_zero_success(self):
        result = diagnose(self.state(), self.review(), TODAY)
        self.assertEqual(result["historical_watch"]["status"], "NOT_OBSERVED")
        self.assertEqual(result["institutional_watch"]["status"], "NOT_OBSERVED")
        self.assertEqual(result["blocking_reason_counts"]["organizer_missing"], 2)
        self.assertEqual(result["publications"], 0)

    def test_observed_attempts(self):
        state = self.state()
        state["institutional_future_checks_private"] = {
            "mauges-pit-fest": {
                "lastAttempted": TODAY, "candidate_seen": True,
                "institutional_status": "FUTURE_DATE_VISIBLE_UNVERIFIED",
                "first_party_status": "FUTURE_DATE_NOT_VISIBLE",
            }
        }
        state["historical_future_source_checks_private"] = {
            "les-gueules-de-bois": {
                "lastAttempted": TODAY, "status": "YEAR_MENTION_REVIEW_ONLY"
            }
        }
        result = diagnose(state, self.review(), TODAY)
        self.assertEqual(result["institutional_watch"]["candidate_checks_today"], 1)
        self.assertEqual(result["historical_watch"]["attempts_today"], 1)

    def test_old_attempt_is_not_todays_run(self):
        self.assertEqual(_watch({"les-gueules-de-bois": {
            "lastAttempted": "2026-11-08", "status": "YEAR_MENTION_REVIEW_ONLY"
        }}, "status", TODAY)["status"], "NOT_ATTEMPTED_TODAY")

    def test_no_publication_authorization(self):
        review = self.review()
        review["dossiers"][0]["publication_authorized"] = True
        with self.assertRaises(ValueError):
            diagnose(self.state(), review, TODAY)

    def test_bad_identity_is_rejected(self):
        state = self.state()
        state["institutional_future_checks_private"] = {
            "untrusted": {"lastAttempted": TODAY, "candidate_seen": True}
        }
        with self.assertRaises(ValueError):
            diagnose(state, self.review(), TODAY)

    def test_future_date_is_rejected(self):
        with self.assertRaises(ValueError):
            _watch({"les-gueules-de-bois": {
                "lastAttempted": "2027-01-01", "status": "UNAVAILABLE"
            }}, "status", TODAY)

    def test_count_mismatch_is_rejected(self):
        review = self.review()
        review["dossiers_count"] = 3
        with self.assertRaises(ValueError):
            diagnose(self.state(), review, TODAY)


if __name__ == "__main__":
    unittest.main()
