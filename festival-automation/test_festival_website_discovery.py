"""Festival website discovery never certifies a new primary domain."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).parent))

from festival_website_discovery import event_website_links, discovery_queue
from source_qualification import assess_candidate, classify, clean_url, normalized, qualify

ORIGIN = "https://sortir.limoges.fr/agenda/festival-de-noel-xxxiv"
TARGET = "https://festival-noel-exemple.fr/"
LEAD = {
    "slug": "festival-de-noel-xxxiv-2026", "name": "Festival de Noël # XXXIV",
    "start_date": "2026-12-11", "end_date": "2026-12-14",
    "organizer": "Association Execution MGT",
    "candidate_urls": [ORIGIN],
    "allowed_to_publish": False, "official_status": "NOT_VERIFIED",
}


def markup(name="Festival de Noël # XXXIV", start="2026-12-11", end="2026-12-14",
           target=TARGET):
    return ('<h1>Festival de Noël # XXXIV</h1>'
            '<p>11 décembre 2026 à Limoges</p>'
            '<script type="application/ld+json">'
            '{"@type":"MusicEvent","name":"' + name +
            '","startDate":"' + start + '","endDate":"' + end +
            '","url":"' + target + '","sameAs":'
            '["https://www.facebook.com/festival","https://www.helloasso.com/associations/example",'
            '"https://site-du-festival-exemple.fr/"]}'
            '</script>')


class EventSourceDiscoveryTests(unittest.TestCase):
    def extract(self, html):
        return event_website_links(
            html, ORIGIN, LEAD["name"], LEAD["start_date"], LEAD["end_date"],
            clean_url, classify, normalized)

    def test_exact_primary_event_yields_bounded_private_domains(self):
        found = self.extract(markup())
        self.assertEqual(
            [(r["candidate_url"], r["evidence_format"]) for r in found],
            [(TARGET, "SCHEMA_ORG_EVENT_URL"),
             ("https://site-du-festival-exemple.fr/", "SCHEMA_ORG_EVENT_SAMEAS")])
        result = assess_candidate(LEAD, ORIGIN, "2026-11-05", html=markup())
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertEqual(len(result["festival_event_links_review_only"]), 2)
        self.assertFalse(result["publication_authorized"])
        self.assertFalse(result["official_site_authorized"])
        self.assertNotIn("officialSite", result)

    def test_wrong_name_year_date_end_and_hidden_only_text_never_count(self):
        for bad in (
            markup(name="Autre festival"),
            markup(name="Festival de Noël # XXXIV 2025"),
            markup(start="2026-12-12"),
            markup(end="2026-12-15"),
        ):
            with self.subTest(bad=bad[:100]):
                self.assertEqual(self.extract(bad), [])
        only_script = markup().replace("<h1>Festival de Noël # XXXIV</h1>", "").replace(
            "<p>11 décembre 2026 à Limoges</p>", "<p>Accueil du site</p>")
        entry = assess_candidate(LEAD, ORIGIN, "2026-11-05", html=only_script)
        self.assertEqual(entry["status"], "NOT_VERIFIED")
        self.assertNotIn("festival_event_links_review_only", entry)

    def test_discard_self_domain_social_tickets_unsafe_and_unrelated_events(self):
        for target in (
            "http://festival-noel-exemple.fr/",
            "https://127.0.0.1/private", "https://localhost.local/",
            "https://sortir.limoges.fr/agenda/un-autre",
            "https://www.limoges.fr/festival",  # same institutional family
            "https://www.facebook.com/festival",
            "https://www.helloasso.com/associations/a",
        ):
            with self.subTest(target=target):
                self.assertEqual(self.extract(markup(target=target)),
                                 [{"candidate_url": "https://site-du-festival-exemple.fr/",
                                   "evidence_format": "SCHEMA_ORG_EVENT_SAMEAS"}])
        # Even for rejected event.url, a valid unrelated sameAs remains a *lead*.
        self.assertEqual(self.extract(markup(target="https://sortir.limoges.fr/agenda/other")),
                         [{"candidate_url": "https://site-du-festival-exemple.fr/",
                           "evidence_format": "SCHEMA_ORG_EVENT_SAMEAS"}])

    def test_unrelated_or_archived_source_cannot_enter_private_queue(self):
        record = {
            "lastChecked": "2026-11-05", "status": "REVIEW_REQUIRED",
            "role": "INSTITUTION", "fingerprint_sha256": "a" * 64,
            "festival_event_links_review_only": [{
                "candidate_url": TARGET, "evidence_format": "SCHEMA_ORG_EVENT_URL"}],
        }
        def queue(record_for=record, lead=LEAD, origin=ORIGIN, day="2026-11-05"):
            return discovery_queue([lead], {lead["slug"]: {origin: record_for}},
                                   day, clean_url, classify)
        self.assertEqual(len(queue()), 1)
        self.assertFalse(queue()[0]["publication_authorized"])
        self.assertFalse(queue()[0]["official_site_authorized"])
        self.assertEqual(queue(record_for=dict(record, status="NOT_VERIFIED")), [])
        self.assertEqual(queue(record_for=dict(record, role="TICKETING")), [])
        self.assertEqual(queue(record_for=dict(record, fingerprint_sha256="broken")), [])
        self.assertEqual(queue(record_for=dict(record, lastChecked="2026-10-01")), [])
        self.assertEqual(queue(record_for=dict(record, lastChecked="2026-11-06")), [])
        self.assertEqual(queue(lead=dict(LEAD, end_date="2026-11-04")), [])
        self.assertEqual(queue(origin="https://evil.example/agenda/event"), [])
        self.assertEqual(queue(lead=dict(LEAD, official_status="VERIFIED")), [])
        self.assertEqual(queue(lead=dict(LEAD, candidate_urls=[ORIGIN, TARGET])), [])

    def test_dedup_same_target_and_limit(self):
        record = {
            "lastChecked": "2026-11-05", "status": "REVIEW_REQUIRED",
            "role": "INSTITUTION", "fingerprint_sha256": "b" * 64,
            "festival_event_links_review_only": [
                {"candidate_url": TARGET, "evidence_format": "SCHEMA_ORG_EVENT_URL"},
                {"candidate_url": TARGET, "evidence_format": "SCHEMA_ORG_EVENT_SAMEAS"}],
        }
        found = discovery_queue([LEAD], {LEAD["slug"]: {ORIGIN: record}},
                                "2026-11-05", clean_url, classify)
        self.assertEqual(len(found), 1)

    def test_qualify_persists_and_reports_new_url_without_visiting_it(self):
        report = {
            "schema": "grossesondes.source-watch-report.v1", "date": "2026-11-05",
            "source_reference_leads_review_only": [LEAD],
        }
        state = {}
        visits = []
        def download(url):
            visits.append(url)
            self.assertEqual(url, ORIGIN)
            return markup()
        qualify(report, state, fetch=download, limit=1, disputes={})
        self.assertEqual(visits, [ORIGIN])
        self.assertEqual(len(report["festival_source_discovery_review_only"]), 2)
        self.assertEqual(report["festival_source_discovery_new_urls_review_only"], 2)
        self.assertEqual(report["festival_source_discovery_pending_urls_review_only"], 2)
        entry = report["festival_source_discovery_review_only"][0]
        self.assertEqual(entry["status"], "UNVERIFIED_DISCOVERY")
        self.assertFalse(entry["publication_authorized"])
        self.assertNotIn(TARGET, report["source_reference_leads_review_only"][0]["candidate_urls"])
        self.assertNotIn(TARGET, state["source_qualification_last_checked"][LEAD["slug"]])
        # Second pass still sees private leads, but never fetches them.
        next_report = dict(report, date="2026-11-06")
        qualify(next_report, state, fetch=download, limit=1, disputes={})
        self.assertEqual(len(next_report["festival_source_discovery_review_only"]), 2)
        self.assertEqual(next_report["festival_source_discovery_new_urls_review_only"], 0)
        self.assertEqual(next_report["festival_source_discovery_pending_urls_review_only"], 2)
        self.assertFalse(any(url == TARGET for url in visits))


if __name__ == "__main__":
    unittest.main()
