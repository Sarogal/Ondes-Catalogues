"""Offline regression tests for private festival yield diagnostics."""
from copy import deepcopy
import unittest

from national_yield_diagnostics import diagnose, _watch

TODAY = "2026-11-09"


class YieldTests(unittest.TestCase):
    def state(self):
        return {"schema": "grossesondes.source-watch.v1"}

    def review(self):
        return {
            "schema": "grossesondes.national-editorial-reconciliation-private.v1",
            "as_of": TODAY, "review_only": True, "safe_to_publish": False,
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

    def comparable(self, day=TODAY):
        result = self.review()
        result["as_of"] = day
        result["dossiers"][0]["id"] = "national-" + "a"*20
        result["dossiers"][1]["id"] = "national-" + "b"*20
        return result

    def test_progress_without_previous_review_is_unknown(self):
        result = diagnose(self.state(), self.review(), TODAY)
        self.assertEqual(result["progress_since_previous_review"]["status"],
                         "NOT_OBSERVED")
        self.assertNotIn("new_dossiers", result["progress_since_previous_review"])

    def test_real_research_signal_gain_is_not_a_publication(self):
        old = self.comparable("2026-11-08")
        current = self.comparable()
        current["dossiers"][0].update(
            status="ARCHIVAL_VISIBLE_DATE_HINT_REVIEW",
            historical_homepage_date_hints_review_only=[{
                "start_date_hint": "2027-05-07",
                "end_date_hint": "2027-05-08",
                "season_hint": None}],
            archive_identity_hints=[{
                "slug": "le-gros-tonneau", "last_known_year": 2026,
                "prior_edition_organizer_review_only": "Canard Zébré",
                "prior_edition_department_review_only": "63"}],
            missing_checks=["organizer_missing", "independent_date_confirmation"])
        got = diagnose(self.state(), current, TODAY, previous_review=old)
        delta = got["progress_since_previous_review"]
        self.assertEqual(delta["status"], "COMPARED")
        self.assertEqual(delta["previous_as_of"], "2026-11-08")
        self.assertEqual(delta["evidence_gained_dossiers"], 1)
        self.assertEqual(delta["research_hints_gained_dossiers"], 1)
        self.assertEqual(delta["blockers_removed_dossiers"], 1)
        self.assertEqual(delta["unchanged_existing_dossiers"], 1)
        self.assertEqual(delta["changed_dossiers"][0]["evidence_added"],
                         ["homepage_date_hint"])
        self.assertIn("historical_organizer_hint",
                      delta["changed_dossiers"][0]["research_hints_added"])
        self.assertEqual(got["publications"], 0)
        self.assertFalse(got["safe_to_publish"])

    def test_new_press_claim_is_progress_but_never_publication(self):
        from targeted_press_edition_watch import SOURCES as PRESS
        old = self.comparable("2026-11-08")
        current = self.comparable()
        source = PRESS["mauges-angers"]
        hint = {
            "claim_id": "next-edition",
            "start_date_hint": "2027-10-08",
            "end_date_hint": "2027-10-09",
            "season_hint": None, "review_only": True,
            "publication_authorized": False, "edition_dates_verified": False,
            "independence_verified": False,
        }
        row = current["dossiers"][0]
        row["press_date_observations_review_only"] = [{
            "article_url": source["url"], "publisher": source["publisher"],
            "observed_at": TODAY, "claims": [hint],
            "review_only": True, "publisher_origin_assessed": False,
            "independence_verified": False, "publication_authorized": False,
        }]
        delta = diagnose(self.state(), current, TODAY, old)[
            "progress_since_previous_review"]
        self.assertEqual(delta["evidence_gained_dossiers"], 1)
        self.assertEqual(delta["changed_dossiers"][0]["evidence_added"],
                         ["press_article_date_claim"])
        self.assertFalse(current["dossiers"][0]["publication_authorized"])
        self.assertFalse(current["dossiers"][0]["safe_to_publish"])
        old = deepcopy(current)
        old["as_of"] = "2026-11-10"
        current["dossiers"][0]["press_date_observations_review_only"][0][
            "observed_at"] = "2026-11-11"
        delta = diagnose(self.state(), current, TODAY, old)[
            "progress_since_previous_review"]
        self.assertEqual(delta["evidence_gained_dossiers"], 0)

    def test_invalid_press_provenance_in_history_fails_closed(self):
        from targeted_press_edition_watch import SOURCES as PRESS
        old = self.comparable("2026-11-08")
        current = self.comparable()
        old["dossiers"][0]["press_date_observations_review_only"] = [{
            "article_url": PRESS["mauges-angers"]["url"],
            "publisher": "Angers Info",
            "claims": [{
                "start_date_hint": "2027-10-08",
                "end_date_hint": "2027-10-09",
                "review_only": True, "edition_dates_verified": False,
                "independence_verified": False,
                "publication_authorized": False}],
            "review_only": True, "publisher_origin_assessed": False,
            "independence_verified": True, "publication_authorized": False,
        }]
        with self.assertRaises(ValueError):
            diagnose(self.state(), current, TODAY, old)

    def test_repeat_observation_date_is_not_progress(self):
        old = self.comparable("2026-11-08")
        current = self.comparable()
        primary = {
            "dates_visible_in_primary": True,
            "start_date_hint": "2027-08-13", "end_date_hint": "2027-08-14",
            "observed_at": "2026-11-08",
        }
        old["dossiers"][1]["primary_observation"] = deepcopy(primary)
        primary["observed_at"] = TODAY
        current["dossiers"][1]["primary_observation"] = primary
        delta = diagnose(self.state(), current, TODAY, old)[
            "progress_since_previous_review"]
        self.assertEqual(delta["unchanged_existing_dossiers"], 2)
        self.assertEqual(delta["evidence_gained_dossiers"], 0)
        self.assertEqual(delta["changed_dossiers"], [])

    def test_lost_hint_is_reported_as_loss_not_advancement(self):
        old = self.comparable("2026-11-08")
        current = self.comparable()
        old["dossiers"][0]["historical_homepage_date_hints_review_only"] = [{
            "start_date_hint": "2027-02-13",
            "end_date_hint": "2027-02-13",
            "season_hint": "summer",
        }]
        delta = diagnose(self.state(), current, TODAY, old)[
            "progress_since_previous_review"]
        self.assertEqual(delta["evidence_lost_dossiers"], 1)
        self.assertEqual(delta["evidence_gained_dossiers"], 0)
        self.assertEqual(delta["changed_dossiers"][0]["evidence_lost"],
                         ["homepage_date_hint"])

    def test_addition_and_disappearance_are_not_called_publication(self):
        old = self.comparable("2026-11-08")
        current = self.comparable()
        current["dossiers"] = current["dossiers"][1:]
        current["dossiers_count"] = 1
        d = diagnose(self.state(), current, TODAY, old)[
            "progress_since_previous_review"]
        self.assertEqual(d["disappeared_dossiers"], 1)
        self.assertEqual(d["new_dossiers"], 0)
        self.assertEqual(d["evidence_gained_dossiers"], 0)

    def test_invalid_prior_review_fails_closed(self):
        old = self.comparable("2026-11-08")
        current = self.comparable()
        cases = [
            lambda d: d.update(as_of="2027-01-01"),
            lambda d: d.update(publication_authorized=True),
            lambda d: d["dossiers"][1].update(id=d["dossiers"][0]["id"]),
            lambda d: d["dossiers"][0].update(safe_to_publish=True),
            lambda d: d.update(dossiers_count=3),
        ]
        for change in cases:
            injected = deepcopy(old)
            change(injected)
            with self.assertRaises(ValueError):
                diagnose(self.state(), current, TODAY,
                         previous_review=injected)

    def test_same_day_runs_are_explicit(self):
        old = self.comparable()
        current = deepcopy(old)
        current["dossiers"][0]["status"] = "ARCHIVAL_VISIBLE_DATE_HINT_REVIEW"
        delta = diagnose(self.state(), current, TODAY, old)[
            "progress_since_previous_review"]
        self.assertEqual(delta["status"], "COMPARED_SAME_DAY")
        self.assertEqual(len(delta["changed_dossiers"]), 1)

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
