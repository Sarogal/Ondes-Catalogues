"""Offline adversarial RSS/Atom official feed nominations, no HTTP/approval."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_openagenda_v2_official_feeds import (
    nominate_from_reviewed_feed, verify_nominated_feed_page,
    redacted_feed_stage,
)
from ptitesondes_openagenda_v2_joined_evidence import diagnose_feed_candidate
from test_ptitesondes_openagenda_v2_joined_evidence import (
    envelope, html as official_event_html, TODAY,
)

HOST = "www.bibliotheque-test.fr"
FEED_URL = "https://" + HOST + "/agenda/feed/"
EVENT_URL = "https://" + HOST + "/programmation/lecture"
LEAD = {
    "title": "Lecture pour enfants",
    "city": "Rouen", "venue": "Médiathèque des Familles",
    "source_url": "https://openagenda.com/commune-test/events/12345678_lecture",
}
PIN = {"approved_host": HOST, "exact_feed_url": FEED_URL, "feed_format": "rss"}


def rss(items=None):
    if items is None:
        items = [("<title>Lecture pour enfants</title>"
                  "<link>" + EVENT_URL + "</link>"
                  "<pubDate>Wed, 18 Nov 2026 10:00:00 +0100</pubDate>")]
    return ('<?xml version="1.0"?><rss version="2.0"><channel>'
            '<title>Agenda de la bibliothèque</title>'
            + "".join("<item>" + x + "</item>" for x in items)
            + "</channel></rss>")


def atom(items=None):
    if items is None:
        items = ['<entry><title>Lecture pour enfants</title>'
                 '<link rel="alternate" type="text/html" href="'
                 + EVENT_URL + '"/></entry>']
    return ('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
            '<title>Agenda</title>' + "".join(items) + '</feed>')


def nominate(content=None, *, lead=None, pin=None, fetched_url=None, mime=None):
    registry = deepcopy(PIN if pin is None else pin)
    return nominate_from_reviewed_feed(
        deepcopy(LEAD if lead is None else lead),
        registry,
        {"url": FEED_URL if fetched_url is None else fetched_url,
         "content": rss() if content is None else content,
         "content_type": "application/rss+xml" if mime is None else mime})


def feed_case():
    case = envelope()
    del case["reviewed_organizer"]
    del case["organizer_page"]
    case["organizer_event_page"] = {
        "url": EVENT_URL, "html": official_event_html()}
    return case


class FirstPartyFeedContract(unittest.TestCase):
    def test_rss_first_party_nomination_only_not_event_proof(self):
        result = nominate()
        self.assertTrue(result["first_party_event_link_nominated"])
        self.assertEqual(result["reviewed_organizer"], {
            "approved_host": HOST, "exact_url": EVENT_URL})
        self.assertFalse(result["organizer_ownership_attested"])
        self.assertFalse(result["approval_granted"])
        self.assertFalse(result["publisher_connected"])
        self.assertEqual(result["public_writes"], 0)
        self.assertNotIn(EVENT_URL, json.dumps(redacted_feed_stage(result)))

    def test_atom_namespace_alternate_link_and_mime(self):
        pin = dict(PIN, feed_format="atom")
        out = nominate(atom(), pin=pin, mime="application/atom+xml; charset=utf-8")
        self.assertTrue(out["first_party_event_link_nominated"])
        self.assertEqual(out["reviewed_organizer"]["exact_url"], EVENT_URL)

    def test_feed_pubdate_cannot_prove_event_date(self):
        # A pubDate in 2026 is only when the item was published.
        out = nominate(rss(["<title>Lecture pour enfants</title><link>" +
                            EVENT_URL + "</link><pubDate>Tue, 10 Oct 2023 "
                            "00:00:00 GMT</pubDate>"]))
        self.assertTrue(out["first_party_event_link_nominated"])
        self.assertNotIn("event_date", out)

    def test_suspicious_urls_never_nominated(self):
        urls = (
            "http://" + HOST + "/programmation/lecture",
            "https://fake.example/event",
            "//fake.example/event",
            "javascript:alert(1)",
            "https://" + HOST + "@fake.example/evil",
            "https://" + HOST + "/event?redirect=https://fake.example",
            "https://" + HOST + "/event#hidden",
            "https://127.0.0.1/secret",
        )
        for target in urls:
            with self.subTest(target=target):
                item = "<title>Lecture pour enfants</title><link>" + target.replace(
                    "&", "&amp;") + "</link>"
                result = nominate(rss([item]))
                self.assertFalse(result["first_party_event_link_nominated"])

    def test_cross_origin_or_forged_reviewed_index_refused(self):
        for pin in (
            dict(PIN, approved_host="fake.example"),
            dict(PIN, exact_feed_url="http://" + HOST + "/agenda/feed/"),
            dict(PIN, exact_feed_url="https://fake.example/feed"),
            dict(PIN, feed_format="json"),
            {},
        ):
            with self.subTest(pin=pin):
                self.assertFalse(nominate(pin=pin)["first_party_event_link_nominated"])
        self.assertFalse(nominate(fetched_url="https://fake.example/feed")[
            "first_party_event_link_nominated"])

    def test_dtd_entity_expansion_and_malformed_feed_rejected(self):
        cases = (
            "<!DOCTYPE rss [<!ENTITY payload 'fake'>]>" + rss(),
            "<!ENTITY payload 'fake'>" + rss(),
            "<rss><channel><item>",
            "<html><body><h1>RSS</h1></body></html>",
            rss().replace("<channel>", "<feed>").replace("</channel>", "</feed>"),
        )
        for data in cases:
            with self.subTest(data=data[:50]):
                self.assertFalse(nominate(data)["first_party_event_link_nominated"])

    def test_html_disguised_as_rss_and_unbounded_xml_rejected(self):
        self.assertEqual(nominate(mime="text/html")["reason"],
                         "official_feed_unavailable")
        self.assertFalse(nominate("a" * 450001)["first_party_event_link_nominated"])
        self.assertFalse(nominate(rss(["<title>x</title><link>" + EVENT_URL +
                         "</link>"] * 601))["first_party_event_link_nominated"])

    def test_feed_with_multiple_matching_permalinks_not_selected(self):
        alt = "https://" + HOST + "/programmation/lecture-2"
        first = "<title>Lecture pour enfants</title><link>" + EVENT_URL + "</link>"
        second = "<title>Lecture pour enfants</title><link>" + alt + "</link>"
        self.assertEqual(nominate(rss([first, second]))["reason"],
                         "ambiguous_first_party_event_links")
        atom_pin = dict(PIN, feed_format="atom")
        same = ('<entry><title>Lecture pour enfants</title><link href="' + EVENT_URL +
                '"/><link href="' + alt + '"/></entry>')
        self.assertFalse(nominate(atom([same]), pin=atom_pin,
                                  mime="application/atom+xml")[
                                      "first_party_event_link_nominated"])

    def test_duplicate_same_permalink_not_ambiguous(self):
        item = "<title>Lecture pour enfants</title><link>" + EVENT_URL + "</link>"
        self.assertTrue(nominate(rss([item, item]))["first_party_event_link_nominated"])

    def test_nonmatching_title_does_not_fuzzy_match(self):
        out = nominate(lead=dict(LEAD, title="Lecture pour les adolescents"))
        self.assertEqual(out["reason"], "no_exact_first_party_event_link")

    def test_bogus_candidate_claim_cannot_change_feed_or_domain(self):
        lead = dict(LEAD, approved_host="evil.example",
                    exact_feed_url="https://evil.example",
                    url="https://evil.example", approved=True)
        out = nominate(lead=lead)
        self.assertTrue(out["first_party_event_link_nominated"])
        self.assertEqual(out["reviewed_organizer"]["exact_url"], EVENT_URL)

    def test_exact_html_page_fetch_required(self):
        pin = nominate()
        self.assertTrue(verify_nominated_feed_page(
            pin, {"url": EVENT_URL, "html": official_event_html()}))
        self.assertFalse(verify_nominated_feed_page(
            pin, {"url": EVENT_URL+"/", "html": official_event_html()}))
        self.assertFalse(verify_nominated_feed_page(
            pin, {"url": EVENT_URL, "html": "short"}))

    def test_feeds_joined_to_full_diagnostic_but_never_published(self):
        c = feed_case()
        good = diagnose_feed_candidate(
            c, PIN, {"url": FEED_URL, "content": rss(),
                     "content_type": "application/rss+xml"}, TODAY)
        self.assertEqual(good["stage"],
                         "structural_evidence_complete_other_gates_pending")
        self.assertFalse(good["approval_granted"])
        self.assertFalse(good["publisher_connected"])
        self.assertEqual(good["public_writes"], 0)
        c["organizer_event_page"]["url"] = "https://evil.example/event"
        denied = diagnose_feed_candidate(
            c, PIN, {"url": FEED_URL, "content": rss(),
                     "content_type": "application/rss+xml"}, TODAY)
        self.assertEqual(denied["stage"], "organizer_event_page_not_exact")

    def test_redaction_excludes_untrusted_error_messages(self):
        result = redacted_feed_stage({"reason": "SECRET-UID-123456"})
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertFalse(result["approval_granted"])
        self.assertFalse(result["contains_event_url_or_identifiers"])


if __name__ == "__main__":
    unittest.main()
