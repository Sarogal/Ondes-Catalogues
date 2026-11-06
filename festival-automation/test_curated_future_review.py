"""Private evidence dossiers never import unverified research as public fields."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import unittest
sys.path.insert(0, str(Path(__file__).parent))

from curated_future_lead_watch import load_leads, PRIVATE_STATUS
from curated_future_review import build_dossiers, valid_observation, SCHEMA

DAY = "2026-11-05"
LEADS = load_leads(json.loads(
    Path(__file__).with_name("curated_future_leads.json").read_text(encoding="utf-8")))


def observed(lead, first="2026-11-05", last="2026-11-05"):
    return {
        "status": PRIVATE_STATUS,
        "publication_authorized": False,
        "firstSeen": first, "lastSeen": last,
        "lastVisibleDigest": "a" * 64,
        "claim": [lead["name"], lead["start_date"], lead["end_date"],
                  lead["date_phrase"], lead["source_url"]],
    }


def state(rows=None):
    return {"schema": "grossesondes.source-watch.v1",
            "curated_future_lead_observations": rows or {}}


class EditorialReviewTests(unittest.TestCase):
    def test_five_review_dossiers_with_no_public_fields(self):
        first = LEADS[3]
        pending = state({first["id"]: observed(first)})
        result = build_dossiers(LEADS, pending, {"festivals": []}, DAY)
        self.assertEqual(result["schema"], SCHEMA)
        self.assertEqual(result["total"], 5)
        self.assertEqual(result["source_seen_count"], 1)
        self.assertEqual(result["dated_hint_count"], 4)
        self.assertFalse(result["safe_to_publish"])
        self.assertEqual(result["publication_authorized_count"], 0)
        self.assertEqual(
            [r["candidate_status"] for r in result["dossiers"]],
            ["PRIMARY_RECHECK_PENDING", "PRIMARY_RECHECK_PENDING",
             "PRIMARY_RECHECK_PENDING", "PRIMARY_SEEN_ONCE",
             "PRIMARY_RECHECK_PENDING"])
        for row in result["dossiers"]:
            self.assertFalse(row["publication_authorized"])
            self.assertTrue(row["editorial_review_required"])
            self.assertFalse(row["independent_date_confirmation"])
            self.assertFalse(row["organizer_identity_verified"])
            self.assertFalse(row["venue_for_edition_verified"])
            self.assertFalse(row["ticketing_verified"])
            self.assertFalse(row["lineup_verified"])
            self.assertFalse(row["coordinates_verified"])
            for forbidden in ("startDate", "endDate", "city", "region", "venue",
                              "lat", "lon", "officialSite", "sourceConfidence",
                              "lineup", "price", "showOnMap"):
                self.assertNotIn(forbidden, row)

    def test_undated_esquiriot_never_gets_public_dates(self):
        lead = LEADS[-1]
        review = build_dossiers([lead], state({lead["id"]: observed(lead)}),
                                {"festivals": []}, DAY)
        row = review["dossiers"][0]
        self.assertEqual(row["candidate_status"], "PRIMARY_SEEN_DATE_UNANNOUNCED")
        self.assertIsNone(row["start_date_hint"])
        self.assertIsNone(row["end_date_hint"])
        self.assertFalse(row["exact_dates_known_in_research_hint"])

    def test_two_days_still_are_not_independent_sources(self):
        lead = LEADS[0]
        review = build_dossiers([lead], state({lead["id"]: observed(
            lead, "2026-11-04", "2026-11-05")}), {"festivals": []}, DAY)
        row = review["dossiers"][0]
        self.assertEqual(row["candidate_status"], "PRIMARY_SEEN_ON_SEPARATE_DAYS")
        self.assertFalse(row["independent_date_confirmation"])
        self.assertFalse(row["publication_authorized"])

    def test_poisoned_observations_or_future_dates_fail_closed(self):
        lead = LEADS[0]
        good = observed(lead)
        mutations = [
            dict(good, publication_authorized=True),
            dict(good, status="VERIFIED"),
            dict(good, claim=["Wrong"]),
            dict(good, firstSeen="2026-11-06"),
            dict(good, lastSeen="2026-11-06"),
            dict(good, lastVisibleDigest="not a SHA256"),
            dict(good, firstSeen="not a date"),
            {"publication_authorized": True},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                review = build_dossiers([lead], state({lead["id"]: mutation}),
                                        {"festivals": []}, DAY)
                record = review["dossiers"][0]
                self.assertFalse(record["source_observed"])
                self.assertEqual(record["candidate_status"], "PRIMARY_RECHECK_PENDING")
                self.assertIsNone(record["primary_text_sha256"])
                self.assertFalse(record["publication_authorized"])

    def test_existing_public_edition_must_not_be_a_new_proposal(self):
        lead = LEADS[0]
        live = {"festivals": [{"slug": "some-other-slug",
                               "name": "MozHell Open Air 2027",
                               "startDate": "2027-07-23"}]}
        record = build_dossiers([lead], state({lead["id"]: observed(lead)}),
                                live, DAY)["dossiers"][0]
        self.assertTrue(record["already_in_public_catalogue"])
        self.assertEqual(record["candidate_status"], "ALREADY_IN_PUBLIC_CATALOGUE")
        self.assertFalse(record["publication_authorized"])

    def test_no_dangerous_or_extraneous_state_fields_in_output(self):
        lead = LEADS[0]
        poisoned = observed(lead)
        poisoned["publication_authorized"] = False
        poisoned["secret"] = "SHOULD_NEVER_OUTPUT"
        s = state({"https://attacker.test/": {"evil": "SHOULD_NEVER_OUTPUT"},
                   lead["id"]: poisoned})
        review = build_dossiers([lead], s, {"festivals": []}, DAY)
        self.assertNotIn("SHOULD_NEVER_OUTPUT", json.dumps(review))
        self.assertNotIn("attacker.test", json.dumps(review))
        self.assertEqual(len(review["dossiers"]), 1)

    def test_invalid_input_rejected(self):
        with self.assertRaises(ValueError):
            build_dossiers(LEADS * 2, state(), {"festivals": []}, DAY)
        with self.assertRaises(ValueError):
            build_dossiers(LEADS, {"schema": "attacker"}, {"festivals": []}, DAY)
        with self.assertRaises(ValueError):
            build_dossiers(LEADS, state(), {"festivals": "wrong"}, DAY)
        with self.assertRaises(ValueError):
            build_dossiers([LEADS[0], LEADS[0]], state(), {"festivals": []}, DAY)
        with self.assertRaises(ValueError):
            build_dossiers(LEADS, state({"bad": {}}), {"festivals": []}, "not-date")


    def test_private_candidate_rows_use_only_source_dates_and_safe_nulls(self):
        first = LEADS[0]
        second = LEADS[3]
        undated = LEADS[-1]
        dossier = build_dossiers(
            [first, second, undated],
            state({first["id"]: observed(first),
                   second["id"]: observed(second),
                   undated["id"]: observed(undated)}),
            {"festivals": []}, DAY)
        self.assertEqual(dossier["proposal_count_review_only"], 2)
        proposals = dossier["proposed_additions_review_only"]
        self.assertEqual([p["id"] for p in proposals],
                         [first["id"], second["id"]])
        self.assertEqual(dossier["publication_authorized_count"], 0)
        for proposal in proposals:
            self.assertFalse(proposal["publication_authorized"])
            self.assertFalse(proposal["safe_to_publish"])
            self.assertTrue(proposal["review_only"])
            self.assertEqual(proposal["status"], "PROPOSED_UNVERIFIED_EDITION")
            self.assertFalse(proposal["independent_confirmation"])
            self.assertIn("editorial_signoff", proposal["missing_checks"])
            fields = proposal["candidate_fields"]
            self.assertTrue(fields["startDate"].startswith("2027-"))
            self.assertTrue(fields["endDate"].startswith("2027-"))
            self.assertIsNone(fields["officialSite"])
            self.assertIsNone(fields["city"])
            self.assertIsNone(fields["department"])
            self.assertIsNone(fields["region"])
            self.assertIsNone(fields["venue"])
            self.assertIsNone(fields["styles"])
            self.assertIsNone(fields["lineup"])
            self.assertIsNone(fields["bands"])
            self.assertIsNone(fields["price"])
            self.assertIsNone(fields["lat"])
            self.assertIsNone(fields["lon"])
            self.assertIs(fields["showOnMap"], False)
            self.assertIs(fields["futureVenueConfirmed"], False)
            self.assertEqual(fields["source"], proposal["primary_source"])
        self.assertNotIn(undated["id"], [p["id"] for p in proposals])

    def test_no_proposal_from_old_unchecked_observation(self):
        first = LEADS[0]
        s = state({first["id"]: observed(first, "2026-11-05", "2026-11-05")})
        dossier = build_dossiers([first], s, {"festivals": []}, "2026-11-15")
        self.assertEqual(dossier["source_seen_count"], 0)
        self.assertEqual(dossier["proposal_count_review_only"], 0)
        self.assertEqual(dossier["dossiers"][0]["candidate_status"],
                         "PRIMARY_RECHECK_PENDING")

    def test_no_proposal_after_event_start(self):
        first = LEADS[0]
        someday = "2027-07-24"
        s = state({first["id"]: observed(first, someday, someday)})
        result = build_dossiers([first], s, {"festivals": []}, someday)
        self.assertEqual(result["source_seen_count"], 1)
        self.assertEqual(result["proposal_count_review_only"], 0)

    def test_never_propose_a_public_duplicate_even_with_valid_observation(self):
        first = LEADS[0]
        live = {"festivals": [{
            "slug": "other-id", "name": "MozHell Open Air 2027",
            "startDate": "2027-07-23",
        }]}
        result = build_dossiers([first],
                                state({first["id"]: observed(first)}),
                                live, DAY)
        self.assertEqual(result["proposal_count_review_only"], 0)
        self.assertEqual(result["dossiers"][0]["candidate_status"],
                         "ALREADY_IN_PUBLIC_CATALOGUE")

    def test_poisoned_claim_does_not_enter_private_candidate_rows(self):
        lead = LEADS[0]
        corrupt = observed(lead)
        corrupt["claim"][2] = "2027-07-26"
        result = build_dossiers([lead],
                                state({lead["id"]: corrupt}),
                                {"festivals": []}, DAY)
        self.assertEqual(result["proposal_count_review_only"], 0)
        self.assertEqual(result["dossiers"][0]["source_observed"], False)


if __name__ == "__main__":
    unittest.main()
