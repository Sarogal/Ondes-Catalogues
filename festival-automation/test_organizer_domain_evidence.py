"""Non-regression: repeated and independent *links* never authenticate a domain."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from organizer_domain_evidence import organizer_domain_dossiers
from source_qualification import clean_url, classify, qualify


SLUG = "festival-de-noel-xxxiv-2026"
TARGET = "https://execution-mgt.fr/"
MUNICIPAL = "https://sortir.limoges.fr/agenda/festival-de-noel-xxxiv"
VENUE = "https://zinor.fr/concerts/festival-de-noel-xxxiv"


def lead(end="2026-12-14"):
    return {
        "slug": SLUG, "name": "Festival de Noël # XXXIV",
        "start_date": "2026-12-11", "end_date": end,
        "organizer": "Association EXECUTION Mgt",
        "candidate_urls": [MUNICIPAL, VENUE],
        "official_status": "NOT_VERIFIED", "allowed_to_publish": False
    }


def record(role, day="2026-11-05", links=None):
    return {
        "status": "REVIEW_REQUIRED", "role": role,
        "lastChecked": day, "fingerprint_sha256": "a" * 64,
        "organizer_links_review_only": [TARGET] if links is None else links
    }


def dossiers(leads=None, history=None, today="2026-11-05"):
    return organizer_domain_dossiers(
        [lead()] if leads is None else leads,
        {SLUG: {MUNICIPAL: record("INSTITUTION"),
                VENUE: record("VENUE", "2026-11-04")}} if history is None else history,
        today, clean_url, classify)


class DomainEvidenceTests(unittest.TestCase):
    def test_two_independent_sources_consolidated_without_verification(self):
        rows = dossiers()
        self.assertEqual(len(rows), 1)
        item = rows[0]
        self.assertEqual(item["candidate_domain"], "execution-mgt.fr")
        self.assertEqual(item["source_count"], 2)
        self.assertEqual(item["corroboration_level"], "MULTI_SOURCE_LINK_ONLY")
        self.assertEqual({r["source_role"] for r in item["references"]},
                         {"INSTITUTION", "VENUE"})
        for flag in ("publication_authorized", "official_site_authorized",
                     "ownership_proven"):
            self.assertIs(item[flag], False)
        self.assertIs(item["link_only"], True)
        self.assertNotIn("officialSite", item)

    def test_related_municipal_subdomains_count_as_single_source_family(self):
        tourism = "https://www.sortir.limoges.fr/agenda/noel-2026"
        h = {SLUG: {MUNICIPAL: record("INSTITUTION"),
                    tourism: record("INSTITUTION")}}
        new_lead = lead()
        new_lead["candidate_urls"].append(tourism)
        self.assertEqual(classify(tourism), "INSTITUTION")
        rows = dossiers([new_lead], h)
        self.assertEqual(rows[0]["source_count"], 1)
        self.assertEqual(rows[0]["corroboration_level"], "SINGLE_SOURCE_LINK_ONLY")
        self.assertEqual(rows[0]["source_families"], ["limoges.fr"])

    def test_ticketing_or_non_matching_source_does_not_corroborate(self):
        ticket = "https://www.helloasso.com/associations/execution-mgt/evenements/noel"
        new_lead = lead()
        new_lead["candidate_urls"].append(ticket)
        h = {SLUG: {MUNICIPAL: record("INSTITUTION"),
                    ticket: record("TICKETING")}}
        self.assertEqual(dossiers([new_lead], h)[0]["source_count"], 1)
        bad = record("INSTITUTION")
        bad["status"] = "NOT_VERIFIED"
        h[SLUG][MUNICIPAL] = bad
        self.assertEqual(dossiers([new_lead], h), [])

    def test_stale_future_and_invalid_fingerprints_do_not_count(self):
        for day, digest in (
            ("2026-10-13", "a" * 64), ("2026-11-06", "a" * 64),
            ("2026-11-05", "invalid")):
            h = {SLUG: {MUNICIPAL: record("INSTITUTION", day)}}
            h[SLUG][MUNICIPAL]["fingerprint_sha256"] = digest
            self.assertEqual(dossiers(history=h), [])
        self.assertEqual(dossiers(leads=[lead(end="2026-11-04")]), [])
        already_approved = lead()
        already_approved["official_status"] = "VERIFIED"
        self.assertEqual(dossiers(leads=[already_approved]), [])

    def test_unlisted_history_and_unsafe_or_self_links_are_dropped(self):
        rogue = "https://other.fr/agenda/same-name"
        h = {SLUG: {rogue: record("VENUE")}}
        self.assertEqual(dossiers(history=h), [])
        h = {SLUG: {MUNICIPAL: record("INSTITUTION", links=[
            "http://execution-mgt.fr/", "https://127.0.0.1/internal",
            "https://sortir.limoges.fr/own", "https://www.facebook.com/exec",
            "https://www.helloasso.com/associations/exec",
        ])}}
        self.assertEqual(dossiers(history=h), [])

    def test_same_target_domain_multiple_paths_still_one_dossier(self):
        h = {SLUG: {
            MUNICIPAL: record("INSTITUTION", links=[
                "https://execution-mgt.fr/", "https://execution-mgt.fr/contact"]),
            VENUE: record("VENUE", links=["https://execution-mgt.fr/"]),
        }}
        rows = dossiers(history=h)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_count"], 2)
        self.assertEqual(len(rows[0]["candidate_urls"]), 2)

    def test_live_qualify_aggregates_previous_day_without_extra_fetch(self):
        row = lead()
        html = lambda url: (
            "<h1>Festival de Noël # XXXIV</h1>"
            "<p>11 décembre 2026, concert à Limoges.</p>"
            "<a href='https://execution-mgt.fr/'>Proposé par Execution MGT</a>")
        state = {}
        report1 = {"schema": "grossesondes.source-watch-report.v1",
                   "date": "2026-11-04",
                   "source_reference_leads_review_only": [row]}
        qualify(report1, state, fetch=html, limit=1)
        self.assertEqual(len(report1["organizer_domain_evidence_review_only"]), 1)
        self.assertEqual(report1["organizer_domain_evidence_review_only"][0]["source_count"], 1)
        report2 = dict(report1, date="2026-11-05")
        qualify(report2, state, fetch=html, limit=1)
        summary = report2["organizer_domain_evidence_review_only"][0]
        self.assertEqual(summary["source_count"], 2)
        self.assertEqual(summary["corroboration_level"], "MULTI_SOURCE_LINK_ONLY")
        self.assertFalse(summary["publication_authorized"])
        self.assertEqual(len(report2["source_qualification_review_only"]), 1)


if __name__ == "__main__":
    unittest.main()
