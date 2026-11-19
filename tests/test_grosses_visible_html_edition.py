"""Security and publisher regression tests for first-party visible HTML proof."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from grossesondes_official_html_edition import visible_official_edition
from grossesondes_structured_edition import (
    HTML_PROOF_MODE, ARCHIVED_HTML_PROOF_MODE,
    PROOF_MODE, PRIVATE_CONFIDENCE, PRIVATE_NOTES, PRIVATE_STATUS,
    validate_structured_edition, validate_archived_structured_edition,
)
from grossesondes_stage import stage
from grossesondes_cloud_sync import (
    collect_registered_edition_sources, build_candidate,
)
from test_grosses_structured_edition import (
    PARENT, ENTRY, ARCHIVE_PARENT, ARCHIVED_ENTRY, TODAY, URL,
    StructuredEditionStageTests, ArchivedStructuredEditionTests,
    event, html as jsonld_html,
)


def official_html(dates="12–13 août 2027", name="Winter Rising Fest 2027"):
    return (
        "<html><head><script>const historic = '12–13 août 2026';</script>"
        "<title>2026 archives</title></head><body><main>"
        f"<section><h1>{name}</h1><p>Édition confirmée : {dates}</p></section>"
        "</main></body></html>"
    )


def html_entry(**overrides):
    row = copy.deepcopy(ENTRY)
    row["proofMode"] = HTML_PROOF_MODE
    row.update(overrides)
    return row


def archive_entry(**overrides):
    row = copy.deepcopy(ARCHIVED_ENTRY)
    row["proofMode"] = ARCHIVED_HTML_PROOF_MODE
    row.update(overrides)
    return row


class VisibleHTMLTests(unittest.TestCase):
    def test_french_range_and_multiple_days(self):
        for dates in ("12-13 août 2027", "12 et 13 août 2027",
                      "du 12 au 13 août 2027", "12, 13 août 2027",
                      "12 | 13 | AOUT | 2027"):
            with self.subTest(dates=dates):
                self.assertIsNotNone(validate_structured_edition(
                    html_entry(), PARENT, official_html(dates), TODAY,
                    proof_mode=HTML_PROOF_MODE))
        self.assertTrue(visible_official_edition(
            "<h1>MozHell Open Air 2027</h1><p>23, 24 et 25 juillet 2027</p>",
            "MozHell Open Air 2027",
            __import__("datetime").date(2027, 7, 23),
            __import__("datetime").date(2027, 7, 25)))

    def test_official_poster_dates_before_name(self):
        from datetime import date
        self.assertTrue(visible_official_edition(
            "<section><h2>13 - 14 - 15 | AOUT | 2027</h2>"
            "<h1>Festival 666</h1><p>Bienvenue au Festival 666</p></section>",
            "Festival 666 2027", date(2027, 8, 13), date(2027, 8, 15)))

    def test_wrong_year_or_wrong_title_or_missing_date_fail_closed(self):
        for page in (
            official_html("12-13 août 2026"),
            official_html(name="Other Band Festival 2027"),
            "<h1>Winter Rising Fest 2027</h1><p>Dates prochainement</p>",
            "<h1>Winter Rising Fest 2026</h1><p>12-13 août 2026</p>",
            "<h1>Winter Rising Fest 2027</h1><p>12-13 août</p>",
            "<h1>Unrelated Festival 2027 12-13 août 2027</h1>"
            + "<p>" + "new" * 300 + "</p><h1>Winter Rising Fest 2027</h1>",
        ):
            with self.subTest(page=page[:85]):
                self.assertIsNone(validate_structured_edition(
                    html_entry(), PARENT, page, TODAY,
                    proof_mode=HTML_PROOF_MODE))

    def test_other_edition_year_near_name_never_qualifies(self):
        page = "<h1>Winter Rising Fest 2026</h1><p>12-13 août 2027</p>"
        self.assertIsNone(validate_structured_edition(
            html_entry(), PARENT, page, TODAY,
            proof_mode=HTML_PROOF_MODE))

    def test_hidden_markup_and_jsonld_cannot_certify_visible_edition(self):
        for page in (
            "<head><title>Winter Rising Fest 2027 12-13 août 2027</title></head>",
            '<script type="application/ld+json">{"name":'
            '"Winter Rising Fest 2027","startDate":"2027-08-12"}</script>',
            '<div hidden>Winter Rising Fest 2027 12-13 août 2027</div>',
            '<div aria-hidden="true">Winter Rising Fest 2027 12-13 août 2027</div>',
            '<div style="display:none">Winter Rising Fest 2027 '
            "12-13 août 2027</div>",
            '<noscript>Winter Rising Fest 2027 12-13 août 2027</noscript>',
        ):
            with self.subTest(page=page[:85]):
                self.assertIsNone(validate_structured_edition(
                    html_entry(), PARENT, page, TODAY,
                    proof_mode=HTML_PROOF_MODE))

    def test_conflicting_dates_and_cancellation_block(self):
        for page in (
            official_html() + official_html("12-14 août 2027"),
            official_html("12-14 août 2027"),
            official_html().replace("</main>", 
                "<p>Winter Rising Fest 2027 annulé — 12-13 août 2027</p></main>"),
            official_html().replace("</main>",
                "<p>Winter Rising Fest 2027 reporté — 12-13 août 2027</p></main>"),
        ):
            with self.subTest(page=page[-100:]):
                self.assertIsNone(validate_structured_edition(
                    html_entry(), PARENT, page, TODAY,
                    proof_mode=HTML_PROOF_MODE))

    def test_publisher_rejects_html_jsonld_contradictions(self):
        # The publisher independently fetches the page again. Contradictory
        # embedded same-edition data must not be silently ignored in HTML mode.
        visible = official_html()
        mismatches = (
            event(startDate="2027-08-14"),
            event(endDate="2027-08-14"),
            event(eventStatus="https://schema.org/EventCancelled"),
            event(eventStatus="https://schema.org/EventPostponed"),
        )
        for claim in mismatches:
            with self.subTest(claim=claim):
                proof = visible + jsonld_html(claim)
                self.assertIsNone(validate_structured_edition(
                    html_entry(), PARENT, proof, TODAY,
                    proof_mode=HTML_PROOF_MODE))
                self.assertIsNone(validate_archived_structured_edition(
                    archive_entry(), ARCHIVE_PARENT, proof, TODAY,
                    proof_mode=ARCHIVED_HTML_PROOF_MODE))
        # Agreement is admissible, but the structured claim alone never is.
        self.assertIsNotNone(validate_structured_edition(
            html_entry(), PARENT, visible + jsonld_html(event()), TODAY,
            proof_mode=HTML_PROOF_MODE))
        self.assertIsNotNone(validate_structured_edition(
            html_entry(), PARENT, visible + jsonld_html(event(
                name="Other Festival 2027", startDate="2027-01-01")), TODAY,
            proof_mode=HTML_PROOF_MODE))
        self.assertIsNone(validate_structured_edition(
            html_entry(), PARENT, jsonld_html(event()), TODAY,
            proof_mode=HTML_PROOF_MODE))

    def test_private_proposal_never_proves_status_geolocation_lineup_or_origin(self):
        page = official_html()
        cases = (
            {"lat": 47.1}, {"lon": 2.2}, {"venue": "Old venue"},
            {"lineup": ["Unofficial"]}, {"bands": 1}, {"showOnMap": True},
            {"dateRangeIsContinuous": True}, {"price": "19"},
            {"source": "https://other.invalid"}, {"evidence": ["https://other.invalid"]},
            {"originSlug": "wrong-parent-2026"}, {"lastVerified": "2025-01-01"},
            {"proofMode": PROOF_MODE}, {"notes": "unchecked"},
            {"verificationStatus": "Confirmed"},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                self.assertIsNone(validate_structured_edition(
                    html_entry(**changes), PARENT, page, TODAY,
                    proof_mode=HTML_PROOF_MODE))
        result = validate_structured_edition(
            html_entry(), PARENT, page, TODAY, proof_mode=HTML_PROOF_MODE)
        self.assertEqual(result["lineup"], [])
        self.assertEqual(result["bands"], 0)
        self.assertIsNone(result["lat"])
        self.assertIsNone(result["venue"])
        self.assertFalse(result["showOnMap"])
        self.assertIn("HTML visible", result["sourceConfidence"])
        self.assertNotIn("proofMode", result)

    def test_existing_jsonld_mode_does_not_start_accepting_html(self):
        self.assertIsNone(validate_structured_edition(
            ENTRY, PARENT, official_html(), TODAY))
        self.assertIsNone(validate_structured_edition(
            html_entry(), PARENT, official_html(), TODAY,
            proof_mode=PROOF_MODE))

    def test_archived_parent_revalidated_and_no_inherited_data(self):
        row = archive_entry()
        out = validate_archived_structured_edition(
            row, ARCHIVE_PARENT, official_html(), TODAY,
            proof_mode=ARCHIVED_HTML_PROOF_MODE)
        self.assertIsNotNone(out)
        self.assertEqual(out["lineup"], [])
        self.assertFalse(out["showOnMap"])
        self.assertIsNone(out["lat"])
        self.assertIsNone(out["price"])
        self.assertEqual(ARCHIVE_PARENT["lineup"], ["Prior year act"])
        for altered in (
            dict(ARCHIVE_PARENT, lastKnownYear=2025),
            dict(ARCHIVE_PARENT, slug="wrong-archive"),
            dict(ARCHIVE_PARENT, endDate="2027-08-13"),
        ):
            self.assertIsNone(validate_archived_structured_edition(
                row, altered, official_html(), TODAY,
                proof_mode=ARCHIVED_HTML_PROOF_MODE))

    def test_existing_parent_stage_and_publisher_stay_idempotent(self):
        cal, hist, patch = StructuredEditionStageTests.dataset()
        patch["additions"] = [html_entry()]
        proof = {"registered-edition:" + ENTRY["slug"]: official_html()}
        candidate, report = stage(cal, hist, patch, proof, TODAY)
        self.assertEqual(report["accepted_additions"], [ENTRY["slug"]])
        self.assertFalse(report["automatic_publication"])
        self.assertFalse(candidate["festivals"][-1]["showOnMap"])
        no_source, held = stage(cal, hist, patch, {}, TODAY)
        self.assertEqual(held["accepted_additions"], [])
        self.assertEqual(no_source["festivals"], cal["festivals"])

    def test_archive_stage_and_cumulative_publisher(self):
        cal, hist, patch = ArchivedStructuredEditionTests().archived_dataset()
        patch["additions"] = [archive_entry()]
        source = {"registered-edition:" + ENTRY["slug"]: official_html()}
        snapshot = {"festivals.json": cal, "festival-history.json": hist}
        first, report = build_candidate(
            snapshot, snapshot, patch, source, TODAY, trusted_published=True)
        self.assertTrue(report["changed"])
        self.assertEqual(len(first["festivals"]), len(cal["festivals"]) + 1)
        self.assertFalse(first["festivals"][-1]["showOnMap"])
        second, report = build_candidate(
            snapshot, {"festivals.json": first, "festival-history.json": hist},
            patch, source, TODAY, trusted_published=True)
        self.assertFalse(report["changed"])
        self.assertEqual(first["festivals"], second["festivals"])

    def test_source_collector_never_fetches_patch_url(self):
        cal, hist, patch = ArchivedStructuredEditionTests().archived_dataset()
        patch["additions"] = [archive_entry(evidence=["https://attacker.invalid"])]
        urls = []
        source = collect_registered_edition_sources(
            patch, {}, lambda url, *, registered, raw:
            urls.append((url, registered, raw)) or official_html(),
            archived={r["slug"]: r for r in hist["knownFestivals"]})
        self.assertEqual(urls, [(URL, True, True)])
        out, report = stage(cal, hist, patch, source, TODAY)
        self.assertEqual(report["accepted_additions"], [])
        self.assertEqual(out["festivals"], cal["festivals"])


if __name__ == "__main__":
    unittest.main()
