"""Non-regression: private funnel may diagnose, never change approval gates."""
import copy
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import registry_funnel as f


def row(candidate_id, **changes):
    candidate = {
        "candidateId": candidate_id,
        "source": "agenda_officiel_atabal_detail",
        "sourceUrl": "https://official.example/events/" + candidate_id,
        "date": "2027-03-11",
        "name": "A + B",
        "venue": "Test Hall",
        "city": "Nantes",
        "reviewBucket": "genre_tag_review",
        "officialDetailFound": True,
        "possibleExistingConcert": False,
        "publicationAllowed": False,
        "reviewRequired": True,
    }
    record_updates = changes.pop("_record", {})
    candidate.update(changes)
    return {"candidate": candidate, "status": "pending_review",
            "stableObservations": 2, "identitySignature": "signed",
            **record_updates}


def fixtures(*rows):
    return (
        {"schema": f.REGISTRY_SCHEMA, "items": {str(i): r for i, r in enumerate(rows)}},
        {"schema": f.APPROVALS_SCHEMA, "approvals": []},
        {"schemaVersion": 1, "events": []},
    )


class FunnelTests(unittest.TestCase):
    def test_future_stable_source_is_only_ready_for_recheck(self):
        r, a, c = fixtures(row("one"))
        before = copy.deepcopy((r, a, c))
        result = f.build(r, a, c, dt.date(2026, 11, 9))
        self.assertEqual(result["readyForIndependentRecheck"], 1)
        self.assertEqual(result["privateApprovedEventsTotal"], 0)
        self.assertEqual(result["publicEventsTotal"], 0)
        self.assertIs(result["publicationAllowed"], False)
        self.assertEqual((r, a, c), before)

    def test_stability_is_distinct_day_only_and_never_inferred_from_observations(self):
        unstable = row("one", _record={"stableObservations": 1, "observations": 99})
        r, a, c = fixtures(unstable)
        out = f.build(r, a, c, dt.date(2026, 11, 9))
        self.assertEqual(out["readyForIndependentRecheck"], 0)
        self.assertEqual(out["exclusiveBlockingReasons"]["awaiting_distinct_day_stability"], 1)

    def test_supported_source_is_required_for_current_auto_recheck(self):
        x = row("one", source="bbc_official_detail_review")
        r, a, c = fixtures(x)
        out = f.build(r, a, c, dt.date(2026, 11, 9))
        self.assertEqual(out["documentedOfficialGenreLeadsPendingFreshVerification"], 1)
        self.assertEqual(out["exclusiveBlockingReasons"]["verified_adapter_not_available"], 1)
        self.assertEqual(out["readyForIndependentRecheck"], 0)

    def test_molotov_rex_backstage_do_not_require_discovery_detail_flag(self):
        # Their actual recheck contracts fetch the official individual page;
        # the registry's discovery-only flag must not hide them as blockers.
        sources = (
            "agenda_officiel_molotov_genre",
            "agenda_officiel_rex_genre",
            "agenda_officiel_backstage_detail",
        )
        r, a, c = fixtures(*(row("candidate-" + str(i), source=source,
                                  officialDetailFound=False)
                              for i, source in enumerate(sources)))
        out = f.build(r, a, c, dt.date(2026, 11, 9))
        self.assertEqual(out["readyForIndependentRecheck"], 3)
        self.assertEqual(out["stableCandidatesInSupportedSourceQueue"], 3)
        self.assertEqual(out["privateApprovedEventsTotal"], 0)
        for source in sources:
            self.assertEqual(out["sourceBlockingReasons"][source],
                             {"ready_for_independent_recheck": 1})
        self.assertNotIn("missing_first_party_detail_evidence",
                         out["exclusiveBlockingReasons"])

    def test_detail_required_adapters_stay_held_without_discovery_flag(self):
        sources = sorted(f.DISCOVERY_DETAIL_FLAG_REQUIRED_SOURCES)
        r, a, c = fixtures(*(row("required-" + str(i), source=source,
                                  officialDetailFound=False)
                              for i, source in enumerate(sources)))
        out = f.build(r, a, c, dt.date(2026, 11, 9))
        self.assertEqual(out["readyForIndependentRecheck"], 0)
        self.assertEqual(
            out["exclusiveBlockingReasons"]["missing_first_party_detail_evidence"],
            len(sources))
        for source in sources:
            self.assertEqual(out["sourceBlockingReasons"][source],
                             {"missing_first_party_detail_evidence": 1})

    def test_private_source_blocker_matrix_is_exclusive_and_anonymized(self):
        r, a, c = fixtures(
            row("private-molotov-123",
                source="agenda_officiel_molotov_genre",
                officialDetailFound=False),
            row("private-rex-456",
                source="agenda_officiel_rex_genre",
                reviewBucket="genre_unknown"),
            row("private-molotov-789",
                source="agenda_officiel_molotov_genre",
                _record={"stableObservations": 1}),
        )
        out = f.build(r, a, c, dt.date(2026, 11, 9))
        matrix = out["sourceBlockingReasons"]
        self.assertEqual(sum(sum(k.values()) for k in matrix.values()), 3)
        self.assertEqual(matrix["agenda_officiel_molotov_genre"],
                         {"ready_for_independent_recheck": 1,
                          "awaiting_distinct_day_stability": 1})
        self.assertEqual(matrix["agenda_officiel_rex_genre"],
                         {"musical_genre_unconfirmed": 1})
        self.assertEqual(out["readyForIndependentRecheck"], 1)
        self.assertNotIn("private-molotov-123", str(matrix))
        self.assertNotIn("official.example", str(matrix))
        self.assertIs(out["publicationAllowed"], False)

    def test_bateau_official_recheck_is_counted_after_adapter_activation(self):
        r, a, c = fixtures(row("bateau", source="bateau_ivre_official_detail_review"))
        out = f.build(r, a, c, dt.date(2026, 11, 9))
        self.assertEqual(out["readyForIndependentRecheck"], 1)
        self.assertEqual(out["stableCandidatesInSupportedSourceQueue"], 1)
        self.assertIs(out["publicationAllowed"], False)

    def test_exact_url_date_published_or_approved_takes_precedence(self):
        r, a, c = fixtures(row("one"), row("two"), row("three"))
        a["approvals"].append({
            "reviewDecision": "approved",
            "event": {"officialUrl": "https://official.example/events/two",
                      "date": "2027-03-11"}})
        c["events"].append({
            "officialUrl": "https://official.example/events/three",
            "date": "2027-03-11"})
        out = f.build(r, a, c, dt.date(2026, 11, 9))
        self.assertEqual(out["readyForIndependentRecheck"], 1)
        self.assertEqual(out["exactApprovedUrlDateInRegistry"], 1)
        self.assertEqual(out["exactPublishedUrlDateInRegistry"], 1)
        self.assertEqual(out["exclusiveBlockingReasons"]["already_approved_exact_url_date"], 1)
        self.assertEqual(out["exclusiveBlockingReasons"]["already_published_exact_url_date"], 1)

    def test_undated_expired_unknown_and_possible_duplicate_are_separate(self):
        r, a, c = fixtures(
            row("no-date", date=None, reviewBucket="undated_lead"),
            row("old", date="2026-11-08"),
            row("no-genre", reviewBucket="genre_unknown"),
            row("possible", possibleExistingConcert=True),
        )
        out = f.build(r, a, c, dt.date(2026, 11, 9))
        counts = out["exclusiveBlockingReasons"]
        self.assertEqual(counts["undated"], 1)
        self.assertEqual(counts["expired"], 1)
        self.assertEqual(counts["musical_genre_unconfirmed"], 1)
        self.assertEqual(counts["possible_duplicate_requires_reconciliation"], 1)
        self.assertEqual(sum(counts.values()), 4)

    def test_collisions_are_diagnostic_only(self):
        r, a, c = fixtures(row("one"), row("two"))
        out = f.build(r, a, c, dt.date(2026, 11, 9))
        self.assertEqual(out["discoveredRegistryRows"], 2)
        self.assertEqual(out["diagnosticIdentityCollisionGroups"], 1)
        self.assertEqual(out["diagnosticCollisionExcessRows"], 1)
        self.assertEqual(out["readyForIndependentRecheck"], 2)

    def test_fail_closed_on_unquarantined_or_corrupt_registry(self):
        r, a, c = fixtures(row("one", publicationAllowed=True))
        with self.assertRaises(ValueError):
            f.build(r, a, c, dt.date(2026, 11, 9))
        r["items"]["0"]["candidate"]["publicationAllowed"] = False
        r["items"]["0"]["candidate"] = "bad"
        with self.assertRaises(ValueError):
            f.build(r, a, c, dt.date(2026, 11, 9))

    def test_legacy_observations_never_make_row_stable(self):
        x = row("one", _record={"observations": 100})
        x.pop("stableObservations")
        x.pop("identitySignature")
        r, a, c = fixtures(x)
        out = f.build(r, a, c, dt.date(2026, 11, 9))
        self.assertEqual(out["legacyRowsWithoutStabilityProof"], 1)
        self.assertEqual(out["readyForIndependentRecheck"], 0)

    def test_seven_day_auto_approval_and_actual_public_snapshot(self):
        r, a, c = fixtures()
        a["approvals"] = [
            {"reviewDecision": "approved",
             "reviewedBy": "automated-official-recheck",
             "reviewedAt": "2026-11-09",
             "event": {"officialUrl": "https://venue.example/e1",
                       "date": "2027-03-11"}},
            {"reviewDecision": "approved",
             "reviewedBy": "independent-official-verifier",
             "reviewedAt": "2026-11-08",
             "event": {"officialUrl": "https://venue.example/e2",
                       "date": "2027-03-12"}},
            {"reviewDecision": "approved",
             "reviewedBy": "automated-official-recheck",
             "reviewedAt": "2026-11-01",
             "event": {"officialUrl": "https://venue.example/e3",
                       "date": "2027-03-13"}},
        ]
        c["events"] = [
            {"officialUrl": "https://venue.example/e1", "date": "2027-03-11",
             "history": [{"date": "2026-11-09", "change": "Ajout"}]},
            {"officialUrl": "https://venue.example/e2", "date": "2027-03-12",
             "history": [{"date": "2026-11-02", "change": "Ajout"}]},
        ]
        out = f.build(r, a, c, dt.date(2026, 11, 9))["lastSevenDaysInclusive"]
        self.assertEqual(out["start"], "2026-11-03")
        self.assertEqual(out["automaticallyApproved"], 1)
        self.assertEqual(out["automaticallyApprovedAndObservedPublished"], 1)
        self.assertEqual(out["publicEventsFirstRecordedInHistory"], 1)



if __name__ == "__main__":
    unittest.main()
