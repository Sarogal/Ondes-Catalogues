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
    ARCHIVED_PROOF_MODE, validate_archived_structured_edition,
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

    def test_yearless_parent_is_revalidated_from_pinned_official_dates(self):
        parent = dict(PARENT, slug="cernunnos-pagan-fest",
                      name="Cernunnos Pagan Fest", startDate="2027-02-12",
                      endDate="2027-02-14")
        proposed = copied(slug="cernunnos-pagan-fest-2028",
                          name="Cernunnos Pagan Fest 2028",
                          originSlug="cernunnos-pagan-fest",
                          startDate="2028-02-11", endDate="2028-02-13")
        proof = html(event(name="Cernunnos Pagan Fest 2028",
                           startDate="2028-02-11", endDate="2028-02-13"))
        verified = validate_structured_edition(proposed, parent, proof, TODAY)
        self.assertIsNotNone(verified)
        self.assertEqual(verified["slug"], "cernunnos-pagan-fest-2028")
        self.assertIs(verified["showOnMap"], False)
        self.assertEqual(verified["lineup"], [])
        self.assertIsNone(verified["price"])
        self.assertIsNone(verified["lat"])
        self.assertNotIn("proofMode", verified)
        self.assertIsNone(validate_structured_edition(
            proposed, dict(parent, startDate=None), proof, TODAY))
        self.assertIsNone(validate_structured_edition(
            proposed, dict(parent, startDate="2026-02-12"), proof, TODAY))
        self.assertIsNone(validate_structured_edition(
            proposed, dict(parent, name="Cernunnos Pagan Fest 2026"), proof, TODAY))
        self.assertIsNone(validate_structured_edition(
            copied(**{**proposed, "slug": "cernunnos-pagan-fest-2027"}),
            parent, proof, TODAY))

    def test_middle_year_multi_city_slug_does_not_allow_silent_rollover(self):
        parent = dict(PARENT, slug="shred-fest-2027-montpellier",
                      name="Shred Fest 2027 — Montpellier",
                      startDate="2027-02-04", endDate="2027-02-04")
        proposed = copied(slug="shred-fest-2027-montpellier-2028",
                          name="Shred Fest 2028 — Montpellier",
                          originSlug=parent["slug"],
                          startDate="2028-02-04", endDate="2028-02-04")
        proof = html(event(name="Shred Fest 2028 — Montpellier",
                           startDate="2028-02-04", endDate="2028-02-04"))
        self.assertIsNone(validate_structured_edition(proposed, parent, proof, TODAY))

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

    def test_yearless_parent_reaches_stage_only_with_independent_html(self):
        c, history, patch = self.dataset()
        c["festivals"][3] = dict(PARENT, slug="cernunnos-pagan-fest",
                                 name="Cernunnos Pagan Fest",
                                 startDate="2027-02-12", endDate="2027-02-14")
        new = copied(slug="cernunnos-pagan-fest-2028",
                     name="Cernunnos Pagan Fest 2028",
                     originSlug="cernunnos-pagan-fest",
                     startDate="2028-02-11", endDate="2028-02-13")
        patch["additions"] = [new]
        proof = html(event(name="Cernunnos Pagan Fest 2028",
                           startDate="2028-02-11", endDate="2028-02-13"))
        sources = collect_registered_edition_sources(
            patch, {c["festivals"][3]["slug"]: c["festivals"][3]},
            lambda url, *, registered, raw: proof)
        output, result = stage(c, history, patch, sources, TODAY)
        self.assertEqual(result["accepted_additions"], ["cernunnos-pagan-fest-2028"])
        self.assertIs(output["festivals"][-1]["showOnMap"], False)
        output, result = stage(c, history, patch, {}, TODAY)
        self.assertEqual(result["accepted_additions"], [])
        self.assertEqual(len(output["festivals"]), len(c["festivals"]))

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



# An archive-only organizer is *not* a published current-edition parent.
# These fixtures never contain authentic festival claims or live network data.
ARCHIVE_PARENT = {
    "slug": "winter-rising-fest",
    "name": "Winter Rising Fest",
    "startDate": "2026-08-12", "endDate": "2026-08-13",
    "lastKnownYear": 2026, "officialSite": URL,
    "venue": "Old Town Hall", "lat": 48.1, "lon": 2.5,
    "lineup": ["Prior year act"], "price": "old price",
}
ARCHIVED_ENTRY = {
    **ENTRY, "proofMode": ARCHIVED_PROOF_MODE,
    "originSlug": ARCHIVE_PARENT["slug"],
}


class ArchivedStructuredEditionTests(unittest.TestCase):
    def test_new_year_can_use_frozen_archived_organizer_only_for_identity(self):
        verified = validate_archived_structured_edition(
            ARCHIVED_ENTRY, ARCHIVE_PARENT, html(event()), TODAY)
        self.assertIsNotNone(verified)
        self.assertEqual(verified["slug"], "winter-rising-fest-2027")
        self.assertFalse(verified["showOnMap"])
        self.assertIsNone(verified["venue"])
        self.assertIsNone(verified["lat"])
        self.assertIsNone(verified["lon"])
        self.assertIsNone(verified["price"])
        self.assertEqual(verified["lineup"], [])
        self.assertEqual(verified["bands"], 0)
        self.assertNotIn("proofMode", verified)
        self.assertIn("archive", verified["verificationStatus"])
        self.assertEqual(ARCHIVE_PARENT["lineup"], ["Prior year act"])

    def test_untrusted_archive_or_proposal_never_certifies_the_new_edition(self):
        altered_parents = [
            dict(ARCHIVE_PARENT, lastKnownYear=2025),
            dict(ARCHIVE_PARENT, lastKnownYear=True),
            dict(ARCHIVE_PARENT, endDate="2027-08-13"),
            dict(ARCHIVE_PARENT, startDate="2025-08-12"),
            dict(ARCHIVE_PARENT, officialSite="https://untrusted.invalid"),
            dict(ARCHIVE_PARENT, slug="different-fest"),
            dict(ARCHIVE_PARENT, name="Different Festival"),
        ]
        for altered in altered_parents:
            with self.subTest(parent=altered):
                self.assertIsNone(validate_archived_structured_edition(
                    ARCHIVED_ENTRY, altered, html(event()), TODAY))
        for altered in [
            dict(ARCHIVED_ENTRY, originSlug="different"),
            dict(ARCHIVED_ENTRY, officialSite="https://attacker.invalid"),
            dict(ARCHIVED_ENTRY, evidence=["https://attacker.invalid"]),
            dict(ARCHIVED_ENTRY, lat=48.1),
            dict(ARCHIVED_ENTRY, venue="Old Town Hall"),
            dict(ARCHIVED_ENTRY, lineup=["Prior year act"], bands=1),
            dict(ARCHIVED_ENTRY, showOnMap=True),
            dict(ARCHIVED_ENTRY, proofMode=PROOF_MODE),
            dict(ARCHIVED_ENTRY, startDate="2027-08-14"),
        ]:
            with self.subTest(proposal=altered):
                self.assertIsNone(validate_archived_structured_edition(
                    altered, ARCHIVE_PARENT, html(event()), TODAY))

    def test_official_page_must_prove_the_2027_edition_again(self):
        for source in (
            "",
            html(event(name="Winter Rising Fest 2026")),
            html(event(startDate="2027-08-11")),
            html(event(eventStatus="https://schema.org/EventCancelled")),
            "<h1>Winter Rising Fest 2027</h1><p>12–13 août 2027</p>",
        ):
            with self.subTest(source=source):
                self.assertIsNone(validate_archived_structured_edition(
                    ARCHIVED_ENTRY, ARCHIVE_PARENT, source, TODAY))

    def archived_dataset(self):
        calendar, history, patch = fixtures()
        history["knownFestivals"][3] = copy.deepcopy(ARCHIVE_PARENT)
        patch["additions"] = [copy.deepcopy(ARCHIVED_ENTRY)]
        patch["updates"] = []
        return calendar, history, patch

    def test_archive_edition_enters_stage_only_with_independent_current_html(self):
        calendar, history, patch = self.archived_dataset()
        original = copy.deepcopy(calendar)
        parents = {r["slug"]: r for r in history["knownFestivals"]}
        urls = []
        proofs = collect_registered_edition_sources(
            patch, {}, lambda url, *, registered, raw:
            urls.append((url, registered, raw)) or html(event()),
            archived=parents)
        self.assertEqual(urls, [(URL, True, True)])
        self.assertEqual(list(proofs), ["registered-edition:" + ARCHIVED_ENTRY["slug"]])
        candidate, report = stage(calendar, history, patch, proofs, TODAY)
        self.assertEqual(report["accepted_additions"], [ARCHIVED_ENTRY["slug"]])
        self.assertEqual(len(candidate["festivals"]), len(calendar["festivals"]) + 1)
        self.assertFalse(candidate["festivals"][-1]["showOnMap"])
        self.assertEqual(calendar, original)
        empty, held = stage(calendar, history, patch, {}, TODAY)
        self.assertEqual(held["accepted_additions"], [])
        self.assertEqual(empty["festivals"], calendar["festivals"])

    def test_archived_origin_does_not_accept_malicious_private_url(self):
        calendar, history, patch = self.archived_dataset()
        patch["additions"][0]["evidence"] = ["https://attacker.invalid/payload"]
        parents = {r["slug"]: r for r in history["knownFestivals"]}
        visited = []
        proofs = collect_registered_edition_sources(
            patch, {}, lambda url, *, registered, raw:
            visited.append(url) or html(event()),
            archived=parents)
        self.assertEqual(visited, [URL])
        candidate, result = stage(calendar, history, patch, proofs, TODAY)
        self.assertEqual(result["accepted_additions"], [])
        self.assertEqual(candidate["festivals"], calendar["festivals"])

    def test_unknown_archive_origin_and_duplicates_stay_blocked(self):
        calendar, history, patch = self.archived_dataset()
        patch["additions"][0]["originSlug"] = "fake-archive"
        visited = []
        evidence = collect_registered_edition_sources(
            patch, {}, lambda *args, **kwargs: visited.append("fetched"),
            archived={r["slug"]: r for r in history["knownFestivals"]})
        self.assertEqual(visited, [])
        self.assertEqual(evidence, {})
        candidate, report = stage(calendar, history, patch, {}, TODAY)
        self.assertEqual(report["accepted_additions"], [])
        self.assertEqual(candidate["festivals"], calendar["festivals"])
        calendar, history, patch = self.archived_dataset()
        calendar["festivals"][0] = dict(
            ARCHIVED_ENTRY, proofMode=None, originSlug=None)
        candidate, report = stage(calendar, history, patch,
                                  {"registered-edition:" + ARCHIVED_ENTRY["slug"]:
                                   html(event())}, TODAY)
        self.assertEqual(report["accepted_additions"], [])
        self.assertIn("doublon", report["held"][0]["reason"])

    def test_cumulative_publisher_merge_is_idempotent_from_archives(self):
        calendar, history, patch = self.archived_dataset()
        snapshot = {"festivals.json": calendar, "festival-history.json": history}
        sources = {"registered-edition:" + ARCHIVED_ENTRY["slug"]: html(event())}
        first, first_report = build_candidate(
            snapshot, snapshot, patch, sources, TODAY, trusted_published=True)
        self.assertTrue(first_report["changed"])
        self.assertEqual(len(first["festivals"]), len(calendar["festivals"]) + 1)
        second, second_report = build_candidate(
            snapshot, {"festivals.json": first, "festival-history.json": history},
            patch, sources, TODAY, trusted_published=True)
        self.assertFalse(second_report["changed"])
        self.assertEqual(second["festivals"], first["festivals"])


if __name__ == "__main__":
    unittest.main()
