"""Official venue/institution schema.org organizer URLs are PRIVATE research leads."""
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).parent))

from organizer_structured_links import structured_organizer_links
from source_qualification import (assess_candidate, classify, clean_url,
                                  normalized, organizer_aliases, qualify)
from organizer_domain_evidence import organizer_domain_dossiers

SOURCE = "https://www.phalempin.fr/agenda/dawn"
TARGET = "https://refuge59.fr/"
TITLE = "Dawn Metal Festival"
ORG = "Association Le Refuge (Le Refuge 59)"
SLUG = "dawn-metal-festival-2026"


def lead():
    return {
        "slug": SLUG, "name": TITLE, "organizer": ORG,
        "start_date": "2026-11-14", "end_date": "2026-11-14",
        "candidate_urls": [SOURCE],
        "official_status": "NOT_VERIFIED", "allowed_to_publish": False
    }


def event(**changes):
    record = {"@type": "MusicEvent", "name": TITLE,
              "startDate": "2026-11-14", "endDate": "2026-11-14",
              "organizer": {"@type": "Organization", "name": "Le Refuge 59",
                            "url": TARGET}}
    record.update(changes)
    return record


def html(data, visible=True):
    contents = json.dumps(data, ensure_ascii=False)
    top = "<h1>Dawn Metal Festival</h1><p>14 novembre 2026</p>" if visible else ""
    return top + '<script type="application/ld+json">' + contents + "</script>"


def links(data, source=SOURCE):
    return structured_organizer_links(
        html(data), source, TITLE, "2026-11-14", "2026-11-14",
        organizer_aliases(ORG), clean_url, classify, normalized)


class OrganizerStructuredLinksTests(unittest.TestCase):
    def test_exact_event_organizer_url_is_only_a_private_hint(self):
        row = lead()
        result = assess_candidate(row, SOURCE, "2026-11-05", html=html(event()))
        self.assertEqual(result["role"], "INSTITUTION")
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertEqual(result["organizer_links_review_only"], [])
        self.assertEqual(result["structured_organizer_links_review_only"], [TARGET])
        self.assertFalse(result["publication_authorized"])
        self.assertFalse(result["official_site_authorized"])
        self.assertNotIn("officialSite", result)
        self.assertNotIn("ticketAvailability", result)

    def test_structured_event_accepts_primary_name_before_parenthesis(self):
        datum = event(organizer={
            "@type": "Organization", "name": "Le Refuge", "url": TARGET})
        self.assertEqual(links(datum), [TARGET])
        # Exact labels only. A similar but distinct association must not match.
        changed = event(organizer={
            "@type": "Organization", "name": "Le Refuge International",
            "url": TARGET})
        self.assertEqual(links(changed), [])

    def test_event_can_be_in_graph_and_year_suffix_only(self):
        data = {"@context": "https://schema.org", "@graph": [
            {"@type": "Organization", "name": "Le Refuge 59", "url": "https://wrong.fr"},
            event(name="Dawn Metal Festival 2026"),
        ]}
        self.assertEqual(links(data), [TARGET])

    def test_wrong_name_dates_and_organization_cannot_link(self):
        originals = [
            event(name="Dawn Metal Festival 2027"),
            event(name="Dawn Metal Festival extra"),
            event(startDate="2026-11-15"),
            event(endDate="2026-11-15"),
            event(organizer={"name": "Autre Association", "url": TARGET}),
            event(organizer={"@type": "Person", "name": "Le Refuge 59",
                             "url": TARGET}),
            {"@type": "Organization", "name": "Le Refuge 59", "url": TARGET},
        ]
        for sample in originals:
            with self.subTest(sample=sample):
                self.assertEqual(links(sample), [])

    def test_ticket_social_unsafe_and_source_domains_filtered(self):
        for target in (
            "https://www.helloasso.com/associations/le-refuge-59",
            "https://www.facebook.com/LeRefuge59",
            "https://www.instagram.com/refuge59",
            "http://refuge59.fr/",
            "https://127.0.0.1/private",
            "https://valid.fr@evil.example/private",
            "https://www.phalempin.fr/agenda/false",
            "https://sub.phalempin.fr/agenda/false",
        ):
            with self.subTest(target=target):
                body = event(organizer={"name": "Le Refuge 59", "url": target})
                self.assertEqual(links(body), [])

    def test_fake_organizer_in_unrelated_event_is_not_extracted(self):
        data = {"@graph": [
            event(name="Completely Different Festival"),
            {"@type": "Organization", "name": "Le Refuge 59",
             "url": TARGET}
        ]}
        self.assertEqual(links(data), [])

    def test_no_organizer_link_when_visible_page_does_not_match_edition(self):
        wrong_visible = html(event(), visible=False) + "<p>Festival inconnu</p>"
        result = assess_candidate(lead(), SOURCE, "2026-11-05", html=wrong_visible)
        self.assertEqual(result["status"], "NOT_VERIFIED")
        self.assertNotIn("structured_organizer_links_review_only", result)

    def test_too_big_bad_json_and_third_party_page_fail_closed(self):
        self.assertEqual(links({"@graph": [{"@type": "Organization",
                                           "name": "Le Refuge 59", "url": TARGET}]}), [])
        self.assertEqual(structured_organizer_links(
            "x" * 650001, SOURCE, TITLE, "2026-11-14", "2026-11-14",
            organizer_aliases(ORG), clean_url, classify, normalized), [])
        self.assertEqual(structured_organizer_links(
            "<script type='application/ld+json'>bad</script>",
            SOURCE, TITLE, "2026-11-14", "2026-11-14",
            organizer_aliases(ORG), clean_url, classify, normalized), [])
        self.assertEqual(links(event(), "https://www.helloasso.com/associations/le-refuge-59"), [])

    def test_both_html_link_and_structured_metadata_count_once(self):
        row = lead()
        both = (html(event()) +
                "<p>Organisateur : "
                "<a href='https://refuge59.fr/'>Le Refuge 59</a></p>")
        history = {}
        report = {"schema": "grossesondes.source-watch-report.v1",
                  "date": "2026-11-05",
                  "source_reference_leads_review_only": [row]}
        qualify(report, history, fetch=lambda _: both, limit=1)
        self.assertEqual(len(report["organizer_domain_leads_review_only"]), 2)
        self.assertEqual({r["evidence_format"] for r in
                          report["organizer_domain_leads_review_only"]},
                         {"VISIBLE_ANCHOR", "SCHEMA_ORG"})
        for r in report["organizer_domain_leads_review_only"]:
            self.assertFalse(r["publication_authorized"])
            self.assertTrue(r["link_only"])
        records = history["source_qualification_last_checked"][SLUG][SOURCE]
        self.assertEqual(records["organizer_links_review_only"], [TARGET])
        self.assertEqual(records["structured_organizer_links_review_only"], [TARGET])
        dossiers = organizer_domain_dossiers(
            [row], history["source_qualification_last_checked"], "2026-11-05",
            clean_url, classify)
        self.assertEqual(len(dossiers), 1)
        self.assertEqual(dossiers[0]["source_count"], 1)
        self.assertEqual(dossiers[0]["evidence_formats"],
                         ["SCHEMA_ORG", "VISIBLE_ANCHOR"])
        self.assertEqual(dossiers[0]["corroboration_level"],
                         "SINGLE_SOURCE_LINK_ONLY")
        self.assertFalse(dossiers[0]["official_site_authorized"])

    def test_no_domain_from_dawn_municipal_page_when_only_facebook_given(self):
        row = lead()
        social = event(organizer={"@type": "Organization",
                    "name": "Le Refuge 59", "url": "https://www.facebook.com/refuge59"})
        result = assess_candidate(row, SOURCE, "2026-11-05", html=html(social))
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertEqual(result["structured_organizer_links_review_only"], [])
        self.assertFalse(result["publication_authorized"])


if __name__ == "__main__":
    unittest.main()
