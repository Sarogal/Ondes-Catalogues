import copy
from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from roster_candidates import roster_proposal, merge_proposals, PROOF_MODE
from structured_evidence import inspect_official_html

ORIGINAL = {
    "slug": "festival-metal-2027",
    "name": "Festival Metal 2027",
    "startDate": "2027-08-19",
    "endDate": "2027-08-22",
    "lineup": ["Peeling Flesh", "The Hu"],
    "bands": 2,
    "lastVerified": "2026-10-01",
    "officialSite": "https://festival-metal.example.org",
}
SOURCE = ORIGINAL["officialSite"]
TODAY = "2026-11-04"
PREVIOUS = {"sha256": "abc123", "lastChanged": "2026-11-03"}


def observations(performers=("New Band",), **event_updates):
    event = {
        "@type": "MusicEvent", "name": "Festival Metal 2027",
        "startDate": "2027-08-19", "endDate": "2027-08-22",
        "performer": [{"name": name} for name in performers],
    }
    event.update(event_updates)
    html = '<script type="application/ld+json">' + json.dumps(event) + "</script>"
    return inspect_official_html(html, ORIGINAL, SOURCE, TODAY)


def patch():
    return {"schema": "grossesondes.patch.v1", "safe_to_publish": False,
            "generated_at": "2026-11-03",
            "source": {"festivals": {
                "url": "https://grosses-ondes.fr/data/festivals.json",
                "generatedAt": "2026-10-25", "count": 100}},
            "additions": [{"slug": "existing-future"}], "updates": [],
            "history_additions": [], "history_updates": [], "deferred": []}


def origin():
    return {"schema": 1, "generatedAt": "2026-10-25",
            "festivals": [copy.deepcopy(ORIGINAL)] +
                         [{"slug": f"festival-{i}"} for i in range(99)]}


class RosterCandidateTests(unittest.TestCase):
    def test_proposes_three_fields_only_after_stable_day(self):
        got = roster_proposal(ORIGINAL, ORIGINAL, observations(), PREVIOUS, "abc123", TODAY)
        self.assertEqual(got["proofMode"], PROOF_MODE)
        self.assertEqual([x["field"] for x in got["changes"]],
                         ["lineup", "bands", "lastVerified"])
        self.assertEqual(got["changes"][0]["after"],
                         ["Peeling Flesh", "The Hu", "New Band"])
        self.assertEqual(got["evidence"], [SOURCE])

    def test_requires_two_distinct_days_with_same_fingerprint(self):
        self.assertIsNone(roster_proposal(
            ORIGINAL, ORIGINAL, observations(),
            {"sha256": "abc123", "lastChanged": TODAY}, "abc123", TODAY))
        self.assertIsNone(roster_proposal(
            ORIGINAL, ORIGINAL, observations(), PREVIOUS, "different", TODAY))

    def test_cannot_republish_already_present_spelling_variant(self):
        self.assertIsNone(roster_proposal(
            ORIGINAL, ORIGINAL, observations(("Peelingflesh",)), PREVIOUS, "abc123", TODAY))

    def test_rejects_sensitive_or_changed_dates(self):
        for props in [
            {"startDate": "2027-08-20"},
            {"eventStatus": "https://schema.org/EventCancelled"},
            {"endDate": "2027-08-23"},
        ]:
            self.assertIsNone(roster_proposal(
                ORIGINAL, ORIGINAL, observations(("New Band",), **props),
                PREVIOUS, "abc123", TODAY))

    def test_source_and_identity_must_match_exactly(self):
        obs = observations()
        obs[0]["source_url"] = "https://other.example.org"
        self.assertIsNone(roster_proposal(
            ORIGINAL, ORIGINAL, obs, PREVIOUS, "abc123", TODAY))
        changed = dict(ORIGINAL, lineup=["Changed Earlier"])
        self.assertIsNone(roster_proposal(
            ORIGINAL, changed, observations(), PREVIOUS, "abc123", TODAY))

    def test_not_on_generic_or_another_year(self):
        self.assertIsNone(roster_proposal(
            ORIGINAL, ORIGINAL, observations(name="Festival Metal"),
            PREVIOUS, "abc123", TODAY))
        self.assertIsNone(roster_proposal(
            ORIGINAL, ORIGINAL, observations(name="Festival Metal 2028"),
            PREVIOUS, "abc123", TODAY))

    def test_only_performer_hint_allowed(self):
        obs = observations()
        obs[0]["hints"]["offer_prices_eur"] = ["1.00"]
        self.assertIsNone(roster_proposal(
            ORIGINAL, ORIGINAL, obs, PREVIOUS, "abc123", TODAY))

    def test_merge_is_additive_and_deduplicated_by_slug(self):
        p = patch()
        original = copy.deepcopy(p)
        item = roster_proposal(ORIGINAL, ORIGINAL, observations(), PREVIOUS, "abc123", TODAY)
        self.assertEqual(merge_proposals(p, [item, item], origin(), TODAY), 1)
        self.assertEqual(p["generated_at"], TODAY)
        self.assertEqual(p["additions"], original["additions"])
        self.assertEqual(len(p["updates"]), 1)
        self.assertEqual(merge_proposals(p, [item], origin(), TODAY), 0)

    def test_existing_manual_update_not_overridden(self):
        p = patch()
        p["updates"].append({"slug": ORIGINAL["slug"], "changes": [{"field": "notes"}]})
        item = roster_proposal(ORIGINAL, ORIGINAL, observations(), PREVIOUS, "abc123", TODAY)
        self.assertEqual(merge_proposals(p, [item], origin(), TODAY), 0)
        self.assertEqual(len(p["updates"]), 1)

    def test_patch_baseline_mismatch_is_fail_closed(self):
        p = patch()
        p["source"]["festivals"]["count"] = 200
        item = roster_proposal(ORIGINAL, ORIGINAL, observations(), PREVIOUS, "abc123", TODAY)
        with self.assertRaisesRegex(ValueError, "référence"):
            merge_proposals(p, [item], origin(), TODAY)

    def test_no_auto_publication_flag_ever_introduced(self):
        p = patch()
        item = roster_proposal(ORIGINAL, ORIGINAL, observations(), PREVIOUS, "abc123", TODAY)
        merge_proposals(p, [item], origin(), TODAY)
        self.assertIs(p["safe_to_publish"], False)
        p["safe_to_publish"] = True
        with self.assertRaises(ValueError):
            merge_proposals(p, [item], origin(), TODAY)


if __name__ == "__main__":
    unittest.main()
