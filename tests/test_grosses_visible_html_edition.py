"""Security and publisher regression tests for first-party visible HTML proof."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from grossesondes_official_html_edition import visible_official_edition, explicit_ranges, fold
from grossesondes_structured_edition import (
    HTML_PROOF_MODE, ARCHIVED_HTML_PROOF_MODE, ARCHIVED_BROWSER_PROOF_MODE,
    PROOF_MODE, PRIVATE_CONFIDENCE, PRIVATE_NOTES, PRIVATE_STATUS,
    validate_structured_edition, validate_archived_structured_edition,
)
from grossesondes_stage import stage
from grossesondes_cloud_sync import (
    collect_registered_edition_sources, build_candidate,
    browser_needed_for_pending_patch,
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
                      "12 & 13 août 2027", "12 &amp; 13 août 2027",
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

    def test_ampersand_range_does_not_truncate_first_day(self):
        from datetime import date
        expected = [(date(2027, 6, 25), date(2027, 6, 26))]
        self.assertEqual([(a, b) for _, _, a, b in explicit_ranges(
            "25 & 26 Juin 2027", 2027)], expected)
        self.assertEqual([(a, b) for _, _, a, b in explicit_ranges(
            "25 & 27 Juin 2027", 2027)], [])
        self.assertTrue(visible_official_edition(
            "<main><h1>Festibarock'in 2027</h1>"
            "<p>25 &amp; 26 Juin 2027</p></main>",
            "Festibarock'in 2027", *expected[0]))
        self.assertFalse(visible_official_edition(
            "<main><h1>Festibarock'in 2027</h1>"
            "<p>25 &amp; 27 Juin 2027</p></main>",
            "Festibarock'in 2027", date(2027, 6, 27), date(2027, 6, 27)))

    def test_dotted_adjacent_days_are_exact_and_nonadjacent_dates_not_guessed(self):
        from datetime import date
        exact = (date(2027, 8, 13), date(2027, 8, 14))
        for value in ("13.14 août 2027", "13. 14 août 2027",
                      "13 . 14 AOUT 2027"):
            with self.subTest(value=value):
                self.assertEqual([(a, b) for _, _, a, b in
                                  explicit_ranges(fold(value), 2027)], [exact])
                self.assertTrue(visible_official_edition(
                    "<main><h1>Colomb'in Rock Festival 2027</h1>"
                    f"<p>Rendez-vous les {value} !</p></main>",
                    "Colomb'in Rock Festival 2027", *exact))
        for value in ("13.15 août 2027", "13. 16 août 2027",
                      "13.14 août", "13.14 août 2026"):
            with self.subTest(value=value):
                self.assertEqual([(a, b) for _, _, a, b in
                                  explicit_ranges(fold(value), 2027)], [])

    def test_visible_partial_day_mentions_are_not_false_conflicts(self):
        from datetime import date
        html = ("<main><h1>Festival Roche Libre 2027</h1>"
                "<p>Les 13 et 14 août 2027, deux soirées rock.</p>"
                "<p>Samedi 14 août 2027 : programmation à venir.</p></main>")
        self.assertTrue(visible_official_edition(
            html, "Festival Roche Libre 2027",
            date(2027, 8, 13), date(2027, 8, 14)))
        from grossesondes_institutional_edition import institutional_date
        self.assertEqual(institutional_date(
            html, "Festival Roche Libre 2027", 2027),
            (date(2027, 8, 13), date(2027, 8, 14)))
        for appended in (
                "<p>Autre festival les 16 et 17 août 2027</p>",
                "<p>Le festival aura lieu les 14 et 15 août 2027</p>",
                "<p>Dates modifiées : 13 au 15 août 2027</p>",
        ):
            with self.subTest(appended=appended):
                self.assertIsNone(institutional_date(
                    html.replace("</main>", appended + "</main>"),
                    "Festival Roche Libre 2027", 2027))

    def test_independent_ticket_sale_day_not_an_extra_festival_date(self):
        from datetime import date
        from grossesondes_institutional_edition import institutional_date
        from grossesondes_official_html_edition import administrative_calendar_dates
        festival = (
            "<main><p>Festival des Roches Libres 2027 : "
            "rendez-vous les 13 et 14 août 2027 pour deux jours de métal.</p>"
        )
        administrative = "<p>Ouverture de la billetterie le 26 mars 2027.</p>"
        html = festival + administrative + "</main>"
        start, end = date(2027, 8, 13), date(2027, 8, 14)
        self.assertEqual(administrative_calendar_dates(
            html, "Festival des Roches Libres 2027", 2027),
            {(date(2027, 3, 26), date(2027, 3, 26))})
        self.assertTrue(visible_official_edition(
            html, "Festival des Roches Libres 2027", start, end))
        self.assertEqual(institutional_date(
            html, "Festival des Roches Libres 2027", 2027), (start, end))

    def test_conflicting_festival_dates_still_fail_despite_ticket_milestone(self):
        from datetime import date
        from grossesondes_institutional_edition import institutional_date
        title = "Festival des Roches Libres 2027"
        intro = "<main><p>Festival des Roches Libres 2027 : 13 et 14 août 2027.</p>"
        outro = "</main>"
        cases = (
            "<p>Le Festival des Roches Libres 2027 se tiendra le 26 mars 2027.</p>",
            "<p>Autre festival : 26 mars 2027.</p>",
            "<p>Ouverture de la billetterie du Festival des Roches Libres "
            "le 26 mars 2027.</p>",
            "<p>Ouverture de la billetterie les 26 et 27 mars 2027.</p>",
            "<p>Ouverture de la billetterie le 26 mars 2027, "
            "mais festival les 11 et 12 août 2027.</p>",
            "<p>Le Festival des Roches Libres 2027 est annulé.</p>",
            '<p hidden>Ouverture de la billetterie le 26 mars 2027</p>'
            "<p>Autre festival : 26 mars 2027.</p>",
        )
        for extra in cases:
            with self.subTest(extra=extra):
                page = intro + extra + outro
                self.assertIsNone(institutional_date(page, title, 2027))
                self.assertFalse(visible_official_edition(
                    page, title, date(2027, 8, 13), date(2027, 8, 14)))

    def test_unspecific_dates_or_scripts_never_create_an_administrative_exception(self):
        from datetime import date
        from grossesondes_official_html_edition import administrative_calendar_dates
        title = "Festival des Roches Libres 2027"
        cases = (
            "<p>Billetterie : 26 mars 2027.</p>",
            "<p>Mars 2027 : ouverture bientôt.</p>",
            "<p>Ouverture de la billetterie le 26 mars.</p>",
            "<p>Ouverture de la billetterie 26 et 27 mars 2027.</p>",
            '<script>Ouverture de la billetterie le 26 mars 2027</script>',
            '<div hidden><p>Ouverture de la billetterie le 26 mars 2027</p></div>',
            "<p>Festival des Roches Libres 2027 : ouverture "
            "de la billetterie le 26 mars 2027.</p>",
        )
        for html in cases:
            with self.subTest(html=html):
                self.assertEqual(administrative_calendar_dates(
                    html, title, 2027), set())

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

    def test_current_edition_paragraph_is_not_vetoed_by_separate_archive_title(self):
        from datetime import date
        from grossesondes_institutional_edition import institutional_date
        start, end = date(2027, 4, 23), date(2027, 4, 24)
        html = ("<main><p>Rendez-vous les 23 et 24 avril 2027 "
                "pour la deuxième édition du Festival Spirale Rock !</p>"
                "<p>Le Festival Spirale Rock 2026, c'était ça !</p>"
                "<section><h2>Photos et souvenirs de 2026</h2></section></main>")
        self.assertTrue(visible_official_edition(
            html, "Festival Spirale Rock 2027", start, end))
        self.assertEqual(institutional_date(
            html, "Festival Spirale Rock 2027", 2027), (start, end))
        wrong = (
            "<h1>Festival Spirale Rock 2026</h1>"
            "<p>Rendez-vous les 23 et 24 avril 2027.</p>"
            "<footer>Festival Spirale Rock</footer>")
        self.assertFalse(visible_official_edition(
            wrong, "Festival Spirale Rock 2027", start, end))
        self.assertIsNone(institutional_date(
            wrong, "Festival Spirale Rock 2027", 2027))
        # Even in one paragraph, 2026 cannot be read as a 2027 identity.
        same_block = ("<p>Festival Spirale Rock 2026 et 2027 : "
                      "23 et 24 avril 2027</p>")
        self.assertFalse(visible_official_edition(
            same_block, "Festival Spirale Rock 2027", start, end))
        # Hidden current claims cannot neutralize a visible old-year title.
        hidden = (
            "<h1>Festival Spirale Rock 2026</h1>"
            '<p hidden>Festival Spirale Rock les 23 et 24 avril 2027</p>'
            "<p>23 et 24 avril 2027</p>")
        self.assertFalse(visible_official_edition(
            hidden, "Festival Spirale Rock 2027", start, end))

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

    def test_browser_mode_cannot_reach_publisher_without_independent_render(self):
        cal, hist, patch = ArchivedStructuredEditionTests().archived_dataset()
        proposal = archive_entry(proofMode=ARCHIVED_BROWSER_PROOF_MODE)
        patch["additions"] = [proposal]
        snapshot = {"festivals.json": cal, "festival-history.json": hist}
        proof = official_html()
        key = "registered-edition:" + proposal["slug"]
        missing, held = build_candidate(
            snapshot, snapshot, patch, {key: proof}, TODAY,
            trusted_published=True)
        self.assertEqual(held["accepted_additions"], [])
        self.assertEqual(len(missing["festivals"]), len(cal["festivals"]))
        # Neither a patch-supplied HTML value nor an ordinary HTML proof
        # can mark a browser independently revalidated.
        sources = {key: proof,
                   "registered-edition-browser-verified:" + proposal["slug"]: False}
        missing, held = build_candidate(
            snapshot, snapshot, patch, sources, TODAY,
            trusted_published=True)
        self.assertEqual(held["accepted_additions"], [])

    def test_browser_publisher_fetches_only_frozen_parent_and_detects_conflicts(self):
        cal, hist, patch = ArchivedStructuredEditionTests().archived_dataset()
        proposal = archive_entry(proofMode=ARCHIVED_BROWSER_PROOF_MODE)
        patch["additions"] = [proposal]
        raw = ("<html><head><script>const nextYear=2027;</script></head>"
               "<body><h1>Winter Rising Fest</h1>"
               "<p>Dates à annoncer</p></body></html>")
        calls = []
        def fetch(url, *, registered, raw):
            calls.append(("raw", url, registered, raw))
            return raw_page[0]
        def render(url):
            calls.append(("browser", url))
            return official_html()
        raw_page = [raw]
        sources = collect_registered_edition_sources(
            patch, {}, fetcher=fetch,
            archived={ARCHIVE_PARENT["slug"]: ARCHIVE_PARENT},
            browser_fetcher=render)
        self.assertEqual([call[1] for call in calls], [URL, URL])
        self.assertTrue(sources.get(
            "registered-edition-browser-verified:" + proposal["slug"]))
        snapshot = {"festivals.json": cal, "festival-history.json": hist}
        accepted, report = build_candidate(
            snapshot, snapshot, patch, sources, TODAY,
            trusted_published=True)
        self.assertIn(proposal["slug"], report["accepted_additions"])
        row = accepted["festivals"][-1]
        self.assertFalse(row["showOnMap"])
        self.assertIsNone(row["venue"])
        self.assertIsNone(row["lat"])
        self.assertEqual(row["lineup"], [])
        # If original raw page contradicts the browser, the publisher
        # MUST veto the candidate before staging any edition.
        raw_page[0] = official_html("12–14 août 2027")
        denied = collect_registered_edition_sources(
            patch, {}, fetcher=fetch,
            archived={ARCHIVE_PARENT["slug"]: ARCHIVE_PARENT},
            browser_fetcher=render)
        self.assertFalse(denied.get(
            "registered-edition-browser-verified:" + proposal["slug"]))
        refused, report = build_candidate(
            snapshot, snapshot, patch, denied, TODAY,
            trusted_published=True)
        self.assertEqual(report["accepted_additions"], [])
        self.assertEqual(refused["festivals"], cal["festivals"])

    def test_browser_install_gate_skips_already_published_proposals(self):
        browser_row = archive_entry(proofMode=ARCHIVED_BROWSER_PROOF_MODE)
        raw_row = archive_entry(proofMode=ARCHIVED_HTML_PROOF_MODE,
                                slug="another-archived-2027")
        patch = {"additions": [raw_row, browser_row]}
        self.assertTrue(browser_needed_for_pending_patch(patch, set()))
        self.assertFalse(browser_needed_for_pending_patch(
            patch, {browser_row["slug"]}))
        self.assertFalse(browser_needed_for_pending_patch(
            {"additions": [raw_row]}, set()))
        self.assertFalse(browser_needed_for_pending_patch(
            {"additions": []}, set()))

    def test_browser_proof_rejects_forged_fields_and_missing_browser(self):
        parent = ARCHIVE_PARENT
        proposal = archive_entry(proofMode=ARCHIVED_BROWSER_PROOF_MODE)
        self.assertIsNotNone(validate_archived_structured_edition(
            proposal, parent, official_html(), TODAY,
            proof_mode=ARCHIVED_BROWSER_PROOF_MODE))
        for altered in (
                dict(proposal, showOnMap=True),
                dict(proposal, venue="Old venue"),
                dict(proposal, lat=48.1),
                dict(proposal, lineup=["Old Band"], bands=1),
                dict(proposal, evidence=["https://evil.example"])):
            self.assertIsNone(validate_archived_structured_edition(
                altered, parent, official_html(), TODAY,
                proof_mode=ARCHIVED_BROWSER_PROOF_MODE))
        sources = collect_registered_edition_sources(
            {"additions": [proposal]}, {},
            fetcher=lambda url, *, registered, raw: official_html(),
            archived={parent["slug"]: parent},
            browser_fetcher=lambda url: (_ for _ in ()).throw(OSError("down")))
        self.assertFalse(sources.get(
            "registered-edition-browser-verified:" + proposal["slug"]))

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
