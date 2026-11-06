"""Visible primary-site references remain unverified and safe."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from festival_website_discovery import visible_event_website_links
from source_qualification import (Anchors, assess_candidate, clean_url,
                                  classify, normalized, qualify, choose_checks,
                                  matches_date, with_curated_leads)

ORIGIN = "https://sortir.limoges.fr/agenda/festival-de-noel-xxxiv"
WEBSITE = "https://festival-noel-example.fr/"
LEAD = {
    "slug": "festival-de-noel-xxxiv-2026",
    "name": "Festival de Noël # XXXIV",
    "start_date": "2026-12-11", "end_date": "2026-12-14",
    "organizer": "Association Execution MGT",
    "candidate_urls": [ORIGIN],
    "allowed_to_publish": False, "official_status": "NOT_VERIFIED",
}


def visible(html, source=ORIGIN, name=LEAD["name"]):
    parser = Anchors()
    parser.feed(html)
    return visible_event_website_links(
        parser.anchors, source, name, LEAD["start_date"],
        clean_url, classify, normalized)


def html(anchor, date="11 décembre 2026"):
    return "<h1>Festival de Noël # XXXIV</h1><p>" + date + "</p>" + anchor


class PrimaryVisibleSiteLinkTests(unittest.TestCase):
    def test_same_local_block_exact_event_and_site_label(self):
        page = html('<p>Festival de Noël # XXXIV — '
                    '<a href="https://festival-noel-example.fr/?tracking=abc">Site officiel</a>'
                    '</p>')
        links = visible(page)
        self.assertEqual(links, [{
            "candidate_url": WEBSITE,
            "evidence_format": "VISIBLE_EVENT_WEBSITE",
        }])
        found = assess_candidate(LEAD, ORIGIN, "2026-11-05", html=page)
        self.assertEqual(found["status"], "REVIEW_REQUIRED")
        self.assertEqual(found["visible_festival_website_links_review_only"], links)
        self.assertFalse(found["publication_authorized"])
        self.assertFalse(found["official_site_authorized"])
        self.assertNotIn("officialSite", found)

    def test_site_and_event_both_in_anchor_text(self):
        page = html('<p><a href="https://festival-noel-example.fr/">'
                    'Site officiel du Festival de Noël # XXXIV</a></p>')
        self.assertEqual(len(visible(page)), 1)

    def test_unrelated_events_and_generic_site_link_blocked(self):
        for anchor in (
            '<p>Un autre festival <a href="https://festival-noel-example.fr/">'
            'Site officiel</a></p>',
            '<p><a href="https://festival-noel-example.fr/">Site officiel</a></p>',
            '<p>Festival de Noël # XXXIV '
            '<a href="https://festival-noel-example.fr/">Billetterie</a></p>',
            '<p><a href="https://festival-noel-example.fr/">'
            'Site officiel de Festival de Noël # XXXIV 2025</a></p>',
            '<p>Festival de Noël # XXXIV</p><p>'
            '<a href="https://festival-noel-example.fr/">Site officiel</a></p>',
        ):
            with self.subTest(anchor=anchor):
                self.assertEqual(visible(html(anchor)), [])

    def test_hidden_anchors_and_unallowed_websites_blocked(self):
        for bad in (
            '<div hidden><p>Festival de Noël # XXXIV '
            '<a href="https://festival-noel-example.fr/">Site officiel</a></p></div>',
            '<div aria-hidden="true"><p>Festival de Noël # XXXIV '
            '<a href="https://festival-noel-example.fr/">Site officiel</a></p></div>',
            '<div style="display: none"><p>Festival de Noël # XXXIV '
            '<a href="https://festival-noel-example.fr/">Site officiel</a></p></div>',
            '<noscript><p>Festival de Noël # XXXIV '
            '<a href="https://festival-noel-example.fr/">Site officiel</a></p></noscript>',
            '<p>Festival de Noël # XXXIV '
            '<a href="http://festival-noel-example.fr/">Site officiel</a></p>',
            '<p>Festival de Noël # XXXIV '
            '<a href="https://127.0.0.1/internal">Site officiel</a></p>',
            '<p>Festival de Noël # XXXIV '
            '<a href="https://www.facebook.com/festival">Site officiel</a></p>',
            '<p>Festival de Noël # XXXIV '
            '<a href="https://www.helloasso.com/associations/test">Site officiel</a></p>',
            '<p>Festival de Noël # XXXIV '
            '<a href="https://www.limoges.fr/other">Site officiel</a></p>',
        ):
            with self.subTest(bad=bad):
                self.assertEqual(visible(html(bad)), [])

    def test_name_date_required_before_storing_even_if_visible_link(self):
        page = html('<p>Festival de Noël # XXXIV '
                    '<a href="https://festival-noel-example.fr/">Site officiel</a></p>',
                    date="11 décembre 2025")
        entry = assess_candidate(LEAD, ORIGIN, "2026-11-05", html=page)
        self.assertEqual(entry["status"], "NOT_VERIFIED")
        self.assertNotIn("visible_festival_website_links_review_only", entry)

    def test_queue_persisted_but_not_fetched_or_published(self):
        page = html('<p>Festival de Noël # XXXIV '
                    '<a href="https://festival-noel-example.fr/">Site officiel</a></p>')
        report = {"schema": "grossesondes.source-watch-report.v1",
                  "date": "2026-11-05",
                  "source_reference_leads_review_only": [LEAD]}
        visited = []
        def fetch(url):
            visited.append(url)
            if url != ORIGIN:
                raise AssertionError("unapproved domain must not be visited")
            return page
        state = {}
        qualify(report, state, fetch=fetch, limit=1, disputes={})
        self.assertEqual(visited, [ORIGIN])
        self.assertEqual(report["festival_source_discovery_new_urls_review_only"], 1)
        self.assertEqual(report["festival_source_discovery_pending_urls_review_only"], 1)
        self.assertEqual(report["festival_source_discovery_review_only"][0]
                         ["evidence_format"], "VISIBLE_EVENT_WEBSITE")
        self.assertFalse(report["festival_source_discovery_review_only"][0]
                         ["publication_authorized"])
        self.assertNotIn(WEBSITE,
                         state["source_qualification_last_checked"][LEAD["slug"]])
        second = dict(report, date="2026-11-06")
        qualify(second, state, fetch=fetch, limit=1, disputes={})
        self.assertEqual(second["festival_source_discovery_new_urls_review_only"], 0)
        self.assertEqual(second["festival_source_discovery_pending_urls_review_only"], 1)

    def test_artist_tour_dates_are_explicit_and_review_only(self):
        self.assertTrue(matches_date("January 30, 2027", "2027-01-30"))
        self.assertTrue(matches_date("30 January 2027", "2027-01-30"))
        self.assertTrue(matches_date("Jan 30, 2027", "2027-01-30"))
        self.assertFalse(matches_date("January 31, 2027", "2027-01-30"))
        self.assertFalse(matches_date("January 30, 2026", "2027-01-30"))
        row = {**LEAD, "slug": "lantre-du-lion", "name": "L’Antre du Lion",
               "start_date": "2027-01-30", "end_date": "2027-01-30"}
        curated = with_curated_leads([row], {
            row["slug"]: ["https://septaria-music.com/shows/"]})[0]
        self.assertIn("https://septaria-music.com/shows/",
                      curated["candidate_urls"])
        self.assertFalse(curated["allowed_to_publish"])

    def test_six_distinct_editions_can_rotate_per_pass(self):
        rows = []
        for i in range(6):
            rows.append({
                **LEAD, "slug": f"festival-test-{i}-2026",
                "candidate_urls": [f"https://sortir.limoges.fr/agenda/festival-test-{i}"],
            })
        checked = choose_checks(rows, {}, "2026-11-05", limit=6)
        self.assertEqual(len(checked), 6)
        self.assertEqual(len({item[0]["slug"] for item in checked}), 6)
        with self.assertRaises(ValueError):
            choose_checks(rows, {}, "2026-11-05", limit=7)


if __name__ == "__main__":
    unittest.main()
