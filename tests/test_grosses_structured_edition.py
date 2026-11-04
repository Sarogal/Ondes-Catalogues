"""Regression tests for strict next-year festival publication from JSON-LD.

Fixtures are isolated. The private patch never becomes a sufficient proof.
No real festival JSON, public archive or network source is modified.
"""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from grossesondes_structured_edition import (
    validate_structured_edition, conflicts_with_existing, PROOF_MODE,
    PRIVATE_NOTES, PRIVATE_CONFIDENCE, PRIVATE_STATUS,
    PUBLISHED_CONFIDENCE, PUBLISHED_STATUS,
)
from grossesondes_cloud_sync import (
    collect_registered_edition_sources, build_candidate,
)
from grossesondes_stage import stage
from test_grosses_stage import fixtures

TODAY = "2026-11-04"
URL = "https://example.org/festival"
PARENT = {
    "slug": "winter-rising-fest-2026",
    "name": "Winter Rising Fest 2026",
    "startDate": "2026-08-12", "endDate": "2026-08-13",
    "officialSite": URL, "lineup": ["Old Band"], "bands": 1,
    "lat": 47.1, "lon": 2.3,
}
ENTRY = {
    "slug": "winter-rising-fest-2027",
    "name": "Winter Rising Fest 2027",
    "startDate": "2027-08-12", "endDate": "2027-08-13",
    "city": None, "department": None, "region": None, "venue": None,
    "lat": None, "lon": None, "showOnMap": False,
    "dateRangeIsContinuous": False,
    "lineup": [], "bands": 0, "price": None,
    "status": "Annoncé", "officialSite": URL, "source": URL,
    "lastVerified": TODAY, "notes": PRIVATE_NOTES,
    "verificationStatus": PRIVATE_STATUS,
    "sourceConfidence": PRIVATE_CONFIDENCE,
    "proofMode": PROOF_MODE, "originSlug": PARENT["slug"],
    "evidence": [URL], "verified_at": TODAY,
}


def event(**overrides):
    e = {
        "@type": "MusicEvent", "name": "Winter Rising Fest 2027",
        "startDate": "2027-08-12", "endDate": "2027-08-13",
        "location": {"@type": "Place", "name": "Not inherited"},
        "offers": {"@type": "Offer", "price": "99", "priceCurrency": "EUR"},
        "performer": [{"name": "Not inherited either"}],
    }
    e.update(overrides)
    return e


def html(*events):
    return '<script type="application/ld+json">' + json.dumps({
        "@context": "https://schema.org", "@graph": list(events)
    }, ensure_ascii=False) + "</script>"


def copied(**kwargs):
    v = copy.deepcopy(ENTRY)
    v.update(kwargs)
    return v


class StructuredEditionValidationTests(unittest.TestCase):
    def test_exact_next_year_accepted_with_no_inferred_fields(self):
        parent=copy.deepcopy(PARENT)
        result = validate_structured_edition(ENTRY, PARENT, html(event()), TODAY)
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "Annoncé")
        self.assertIs(result["showOnMap"], False)
        self.assertIsNone(result["lat"])
        self.assertIsNone(result["lon"])
        self.assertEqual(result["lineup"], [])
        self.assertEqual(result["bands"], 0)
        self.assertEqual(result["sourceConfidence"], PUBLISHED_CONFIDENCE)
        self.assertEqual(result["verificationStatus"], PUBLISHED_STATUS)
        self.assertNotIn("proofMode", result)
        self.assertNotIn("originSlug", result)
        self.assertEqual(parent, PARENT)

    def test_fail_closed_for_injected_identity_status_and_coords(self):
        for item in (
            copied(showOnMap=True), copied(lat=47.1),
            copied(venue="Old venue"), copied(price="99€"),
            copied(city="Old city"), copied(status="Confirmé"),
            copied(lineup=["New Band"]), copied(bands=1),
            copied(dateRangeIsContinuous=True),
            copied(notes="Different private text"), copied(unknown="yes"),
            copied(source="https://untrusted.example.org"),
            copied(evidence=["https://untrusted.example.org"]),
            copied(originSlug="different-2026"),
            copied(proofMode="other-v1"),
        ):
            with self.subTest(item=item):
                self.assertIsNone(validate_structured_edition(
                    item, PARENT, html(event()), TODAY))

    def test_fail_closed_for_dates_years_conflicts_and_event_status(self):
        for item in (
            copied(startDate="2027-08-14"),
            copied(endDate="2027-08-14"),
            copied(startDate="2027-08-13", endDate="2027-08-12"),
            copied(name="Winter Rising Fest"),
            copied(name="Winter Rising Fest 2028"),
            copied(slug="winter-rising-fest-2028"),
            copied(lastVerified="2027-08-13", verified_at="2027-08-13"),
        ):
            with self.subTest(item=item):
                self.assertIsNone(validate_structured_edition(
                    item, PARENT, html(event()), TODAY))
        for source in (
            html(event(name="Winter Rising Fest 2026")),
            html(event(name="Different Festival 2027")),
            html(event(endDate="2027-08-14")),
            html(event(eventStatus="https://schema.org/EventCancelled")),
            html(event(eventStatus="EventPostponed")),
            html(event(), event(startDate="2027-08-14")),
            html(event(endDate=None)),
            html(event(**{"@type": "GenericWebPage"})),
            '<p>Winter Rising Fest 2027 on 12-13 August</p>',
        ):
            with self.subTest(source=source[:90]):
                self.assertIsNone(validate_structured_edition(
                    ENTRY, PARENT, source, TODAY))

    def test_duplicate_semantics_even_with_other_slug_or_archives(self):
        self.assertFalse(conflicts_with_existing(
            ENTRY, [PARENT], [{"slug": "past-2024", "name": "Old Fest 2024"}]))
        self.assertTrue(conflicts_with_existing(
            ENTRY, [PARENT, copied(slug="other-edition")], []))
        self.assertTrue(conflicts_with_existing(
            ENTRY, [], [copied(slug="archived-other")]))


class StructuredEditionStageTests(unittest.TestCase):
    @staticmethod
    def dataset():
        calendar, history, patch = fixtures()
        calendar["festivals"][3] = copy.deepcopy(PARENT)
        patch["additions"] = [copy.deepcopy(ENTRY)]
        patch["updates"] = []
        return calendar, history, patch

    def test_stage_accepts_only_independent_html(self):
        calendar, history, patch = self.dataset()
        original = copy.deepcopy(calendar)
        candidate, report = stage(calendar, history, patch,
                                  {"registered-edition:" + ENTRY["slug"]: html(event())},
                                  TODAY)
        self.assertEqual(report["accepted_additions"], [ENTRY["slug"]])
        self.assertEqual(len(candidate["festivals"]), 101)
        self.assertEqual(candidate["festivals"][-1]["name"], ENTRY["name"])
        self.assertIsNone(candidate["festivals"][-1]["venue"])
        self.assertIs(candidate["festivals"][-1]["showOnMap"], False)
        self.assertEqual(calendar, original)
        self.assertFalse(report["automatic_publication"])
        no_source, held = stage(calendar, history, patch, {}, TODAY)
        self.assertEqual(no_source["festivals"], calendar["festivals"])
        self.assertEqual(held["accepted_additions"], [])

    def test_published_archive_conflict_blocks_new_addition(self):
        calendar, history, patch = self.dataset()
        candidate, report = stage(
            calendar, history, patch, {"registered-edition:" + ENTRY["slug"]: html(event())},
            TODAY, published_history={"knownFestivals": [
                {"slug": ENTRY["slug"], "name": ENTRY["name"]},
            ]})
        self.assertEqual(report["accepted_additions"], [])
        self.assertEqual(len(candidate["festivals"]), 100)
        self.assertEqual(report["held"][0]["slug"], ENTRY["slug"])

    def test_full_candidate_merge_is_idempotent_and_does_not_remove_archives(self):
        calendar, history, patch = self.dataset()
        snapshot = {"festivals.json": calendar, "festival-history.json": history}
        sources = {"registered-edition:" + ENTRY["slug"]: html(event())}
        first, report = build_candidate(snapshot, snapshot, patch, sources,
                                        TODAY, trusted_published=True)
        self.assertTrue(report["changed"])
        self.assertEqual(len(first["festivals"]), 101)
        self.assertEqual(len(history["knownFestivals"]), 170)
        second, repeat = build_candidate(
            snapshot, {"festivals.json": first, "festival-history.json": history},
            patch, sources, TODAY, trusted_published=True)
        self.assertFalse(repeat["changed"])
        self.assertEqual(second["festivals"], first["festivals"])

    def test_official_parent_fetch_not_private_evidence(self):
        for candidate in (
            copied(evidence=["https://untrusted.example.org"]),
            copied(officialSite="https://untrusted.example.org"),
        ):
            calls = []
            sources = collect_registered_edition_sources(
                {"additions": [candidate]},
                {PARENT["slug"]: PARENT},
                lambda url, *, registered, raw:
                    calls.append((url, registered, raw)) or html(event()))
            self.assertEqual(calls, [(URL, True, True)])
            calendar, history, patch = self.dataset()
            patch["additions"] = [candidate]
            stage_candidate, report = stage(calendar, history, patch, sources, TODAY)
            self.assertEqual(report["accepted_additions"], [])
            self.assertEqual(stage_candidate["festivals"], calendar["festivals"])

    def test_shared_parent_site_cached_and_unavailable_fails_closed(self):
        p = {"additions": [copied(),
                           copied(slug="another-fest-2027", originSlug="another-fest-2026")]}
        parents = {PARENT["slug"]: PARENT,
                   "another-fest-2026": dict(PARENT, slug="another-fest-2026")}
        calls = []
        proof = collect_registered_edition_sources(
            p, parents,
            lambda url, *, registered, raw:
                calls.append(url) or html(event()))
        self.assertEqual(calls, [URL])
        self.assertEqual(len(proof), 2)

        def error(*args, **kwargs):
            raise OSError("not accessible")

        unavailable = collect_registered_edition_sources(p, parents, error)
        self.assertEqual(list(unavailable.values()), ["", ""])

    def test_unknown_proof_mode_is_never_fetched(self):
        proof = collect_registered_edition_sources(
            {"additions": [copied(proofMode="unsupported")]},
            {PARENT["slug"]: PARENT},
            lambda *args, **kwargs: self.fail("unexpected network fetch"))
        self.assertEqual(proof, {})


if __name__ == "__main__":
    unittest.main()
