import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from grossesondes_structured_roster import (
    matched_roster, validate_structured_roster, PROOF_MODE,
)

ORIGINAL = {
    "slug": "festival-metal-2027",
    "name": "Festival Metal 2027",
    "startDate": "2027-08-19",
    "endDate": "2027-08-22",
    "lineup": ["Peeling Flesh", "The Hu"],
    "bands": 2,
    "lastVerified": "2026-10-01",
    "officialSite": "https://example.org/festival",
}
TODAY = "2026-11-04"


def html(*events):
    return '<script type="application/ld+json">' + json.dumps({
        "@context": "https://schema.org", "@graph": list(events)
    }, ensure_ascii=False) + "</script>"


def event(**kwargs):
    v = {
        "@type": "MusicEvent",
        "name": "Festival Metal 2027",
        "startDate": "2027-08-19",
        "endDate": "2027-08-22",
        "performer": [{"@type": "MusicGroup", "name": "Peelingflesh"},
                      {"@type": "MusicGroup", "name": "New Band"}],
    }
    v.update(kwargs)
    return v


def proposal(added=("New Band",), **kwargs):
    new = ORIGINAL["lineup"] + list(added)
    changes = [
        {"field": "lineup", "before": ORIGINAL["lineup"], "after": new},
        {"field": "bands", "before": 2, "after": len(new)},
        {"field": "lastVerified", "before": "2026-10-01", "after": TODAY},
    ]
    p = {"slug": ORIGINAL["slug"], "proofMode": PROOF_MODE,
         "changes": changes,
         "evidence": [ORIGINAL["officialSite"]], "verified_at": TODAY}
    p.update(kwargs)
    return p


class StructuredRosterTests(unittest.TestCase):
    def test_exact_2027_artist_accepted_without_mutating_baseline(self):
        baseline = copy.deepcopy(ORIGINAL)
        got = validate_structured_roster(ORIGINAL, proposal(), html(event()), TODAY)
        self.assertIsNotNone(got)
        row, fields, pending = got
        self.assertEqual(row["lineup"], ["Peeling Flesh", "The Hu", "New Band"])
        self.assertEqual(row["bands"], 3)
        self.assertEqual(fields, ["lineup", "bands", "lastVerified"])
        self.assertEqual(ORIGINAL, baseline)
        self.assertEqual(pending, [])

    def test_peelingflesh_alias_not_added_again(self):
        self.assertIsNone(validate_structured_roster(
            ORIGINAL, proposal(("Peelingflesh",)), html(event()), TODAY))

    def test_patch_cannot_change_price_or_dates(self):
        p = proposal()
        p["changes"].append({"field": "price", "before": None, "after": "22 €"})
        self.assertIsNone(validate_structured_roster(ORIGINAL, p, html(event()), TODAY))

    def test_refuses_unregistered_evidence(self):
        p = proposal()
        p["evidence"] = ["https://another-domain.example.org/festival"]
        self.assertIsNone(validate_structured_roster(ORIGINAL, p, html(event()), TODAY))

    def test_refuses_unsupported_or_missing_mode(self):
        p = proposal()
        del p["proofMode"]
        self.assertIsNone(validate_structured_roster(ORIGINAL, p, html(event()), TODAY))
        p["proofMode"] = "unknown-v2"
        self.assertIsNone(validate_structured_roster(ORIGINAL, p, html(event()), TODAY))

    def test_refuses_other_year_or_generic_festival_event(self):
        wrong = event(name="Festival Metal 2026", startDate="2026-08-19", endDate="2026-08-22")
        self.assertIsNone(validate_structured_roster(ORIGINAL, proposal(), html(wrong), TODAY))
        generic = event(name="Festival Metal")
        self.assertIsNone(validate_structured_roster(ORIGINAL, proposal(), html(generic), TODAY))

    def test_refuses_foreign_names_and_unproven_performers(self):
        wrong = event(name="Different Festival 2027")
        self.assertIsNone(validate_structured_roster(ORIGINAL, proposal(), html(wrong), TODAY))
        self.assertIsNone(validate_structured_roster(
            ORIGINAL, proposal(("Unknown Band",)), html(event()), TODAY))

    def test_refuses_date_mismatches_and_conflicting_event(self):
        wrong = event(endDate="2027-08-23")
        self.assertIsNone(validate_structured_roster(ORIGINAL, proposal(), html(wrong), TODAY))
        self.assertIsNone(validate_structured_roster(
            ORIGINAL, proposal(), html(event(), wrong), TODAY))

    def test_refuses_cancellation_and_postponement(self):
        for status in ("https://schema.org/EventCancelled", "EventPostponed", "EventRescheduled"):
            self.assertIsNone(validate_structured_roster(
                ORIGINAL, proposal(), html(event(eventStatus=status)), TODAY))

    def test_refuses_forged_before_or_late_verification(self):
        p = proposal()
        p["changes"][0]["before"] = []
        self.assertIsNone(validate_structured_roster(ORIGINAL, p, html(event()), TODAY))
        p = proposal()
        p["changes"][2]["after"] = "2027-08-19"
        p["verified_at"] = "2027-08-19"
        self.assertIsNone(validate_structured_roster(ORIGINAL, p, html(event()), TODAY))

    def test_refuses_unsupported_artist_source(self):
        source = html(event(performer=[{"name": "Peelingflesh"}]))
        self.assertIsNone(validate_structured_roster(ORIGINAL, proposal(), source, TODAY))
        self.assertIsNone(validate_structured_roster(
            ORIGINAL, proposal(), "<p>New Band official lineup</p>", TODAY))

    def test_deduplicates_artist_aliases_with_no_fuzzy_assumptions(self):
        source = html(event(performer=[{"name": "NewBand"}, {"name": "New Band XXL"}]))
        self.assertIsNotNone(validate_structured_roster(
            ORIGINAL, proposal(("New Band",)), source, TODAY))
        self.assertIsNone(validate_structured_roster(
            ORIGINAL, proposal(("New Band", "NewBand")), source, TODAY))

    def test_no_artists_or_bands_mismatch(self):
        p = proposal()
        p["changes"][1]["after"] = 400
        self.assertIsNone(validate_structured_roster(ORIGINAL, p, html(event()), TODAY))
        p = proposal()
        p["changes"][2]["after"] = "2026-09-01"
        p["verified_at"] = "2026-09-01"
        self.assertIsNone(validate_structured_roster(ORIGINAL, p, html(event()), TODAY))

    def test_stage_ignores_unverifiable_publication_candidate(self):
        from test_grosses_stage import fixtures
        from grossesondes_stage import stage
        c,h,p = fixtures()
        c["festivals"][3] = dict(ORIGINAL)
        p["updates"] = [proposal()]
        p["additions"] = []
        # Existing public data only changed if independent registered HTML given.
        out, report = stage(c, h, p, {}, TODAY)
        self.assertEqual(report["accepted_updates"], [])
        self.assertEqual(out["festivals"][3], ORIGINAL)
        out, report = stage(c, h, p,
                            {"registered-schema:" + ORIGINAL["slug"]: html(event())},
                            TODAY)
        self.assertEqual(out["festivals"][3]["lineup"][-1], "New Band")
        self.assertEqual(len(report["accepted_updates"]), 1)
        self.assertEqual(out["festivals"][3]["bands"], 3)


if __name__ == "__main__":
    unittest.main()
