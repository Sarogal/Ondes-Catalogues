"""Pure/adversarial tests: official HTML links are suggestions, never proof."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_official_html_index_discovery import (
    discover_html_event_pages, discover_live_html_event_pages,
    redacted_html_index_counts,
)

PIN = {"approved_host": "mpt.montpellier.fr",
       "exact_index_url": "https://mpt.montpellier.fr/evenements"}


def document(markup):
    return {"url": PIN["exact_index_url"],
            "html": "<html><head><title>Agenda</title></head><body>"
                    + markup + "</body></html>"}


def link(path, label="En savoir plus"):
    return '<a href="' + path + '">' + label + '</a>'


class MockHttp:
    def __init__(self, html, *, status=200, redirect=False, mime="text/html"):
        self.body = html
        self.status = status
        self.redirect = redirect
        self.mime = mime
        self.request = None

    def __call__(self, request, timeout):
        self.request = request
        self.url = request.full_url
        self.timeout = timeout
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def geturl(self):
        return self.url + "/redirect" if self.redirect else self.url

    @property
    def headers(self):
        return {"Content-Type": self.mime}

    def read(self, limit):
        return self.body.encode("utf-8")


class OfficialHtmlIndexTests(unittest.TestCase):
    def test_municipal_first_party_index_nominates_multiple_pages_without_admission(self):
        markup = ("<header>" + link("/evil-nav", "Programme") + "</header>"
                  "<main><h1>Événements</h1>"
                  + link("/evenement/cocon-paisible-0")
                  + link("/evenement/le-corps-le-jeu", "Le corps, le jeu !")
                  + "</main><footer>" + link("/footer", "Programme") + "</footer>")
        out = discover_html_event_pages(PIN, document(markup))
        self.assertEqual(out["stage"], "routing_suggestions_only")
        self.assertEqual(out["counts"]["same_host_child_pages"], 2)
        self.assertEqual(len(out["private_routing_proposals"]), 2)
        self.assertFalse(out["independent_event_session_verified"])
        self.assertFalse(out["rights_reviewed"])
        self.assertFalse(out["approval_granted"])
        self.assertFalse(out["publisher_connected"])
        self.assertEqual(out["public_writes"], 0)

    def test_repeated_title_different_urls_kept_not_merged_as_one_session(self):
        body = ("<main>" + link("/evenement/atelier-0", "Atelier enfants")
                + link("/evenement/atelier-1", "Atelier enfants") + "</main>")
        out = discover_html_event_pages(PIN, document(body))
        self.assertEqual(out["counts"]["same_host_child_pages"], 2)
        self.assertEqual(len({p["url"] for p in out["private_routing_proposals"]}), 2)
        self.assertTrue(all(p["approved"] is False
                            for p in out["private_routing_proposals"]))

    def test_duplicate_event_link_is_collapsed_by_url(self):
        body = "<main>" + link("/evenement/atelier") * 3 + "</main>"
        out = discover_html_event_pages(PIN, document(body))
        self.assertEqual(out["counts"]["same_host_child_pages"], 1)
        self.assertEqual(out["counts"]["duplicate_child_links"], 2)

    def test_navigation_in_main_and_hidden_elements_do_not_vote(self):
        body = ("<main><nav>" + link("/evenement/menu")
                + "</nav><footer>" + link("/evenement/footer")
                + "</footer><div hidden>" + link("/evenement/hidden")
                + "</div><div aria-hidden='true'>" + link("/evenement/aria")
                + "</div><div style='display:none'>" + link("/evenement/css")
                + "</div><script>" + link("/evenement/js")
                + "</script>" + link("/evenement/visible")
                + "</main>")
        out = discover_html_event_pages(PIN, document(body))
        self.assertEqual(out["counts"]["same_host_child_pages"], 1)

    def test_cross_host_fake_domains_and_unsafe_protocols_blocked(self):
        targets = (
            "https://mpt.montpellier.fr.evil.example/event",
            "https://evil.example/event",
            "//mpt.montpellier.fr/event",
            "javascript:alert(1)",
            "mailto:contact@exemple.fr",
            "/evenement/ok?tracking=1",
            "/evenement/ok#fragment",
            "#evenement",
            "?page=2",
            "http://mpt.montpellier.fr/unsafe",
        )
        body = "<main>" + "".join(link(path) for path in targets) + "</main>"
        out = discover_html_event_pages(PIN, document(body))
        self.assertEqual(out["counts"]["same_host_child_pages"], 0)
        self.assertEqual(out["counts"]["out_of_scope_links"], len(targets))

    def test_relative_and_absolute_exact_same_host_permitted(self):
        body = ("<main>" + link("./evenement/atelier", "Atelier jeunesse")
                + link("https://mpt.montpellier.fr/evenement/autre")
                + "</main>")
        out = discover_html_event_pages(PIN, document(body))
        self.assertEqual(out["counts"]["same_host_child_pages"], 2)

    def test_no_main_no_implicit_first_party_verification(self):
        out = discover_html_event_pages(PIN, document(link("/evenement/atelier")))
        self.assertEqual(out["counts"]["same_host_child_pages"], 0)
        self.assertEqual(out["private_routing_proposals"], [])

    def test_index_host_and_exact_page_must_come_from_external_pin(self):
        body = "<main>" + link("/evenement/atelier") + "</main>"
        rogue = dict(PIN, approved_host="evil.example")
        self.assertEqual(discover_html_event_pages(
            rogue, document(body))["stage"], "invalid_or_unreviewed_index")
        wrong_page = dict(document(body), url="https://mpt.montpellier.fr/other")
        self.assertEqual(discover_html_event_pages(
            PIN, wrong_page)["counts"]["same_host_child_pages"], 0)

    def test_gigantic_index_and_too_many_links_rejected_not_truncated(self):
        out = discover_html_event_pages(
            PIN, document("<main>" + "x" * 400001 + "</main>"))
        self.assertEqual(out["stage"], "index_html_unavailable")
        body = "<main>" + "".join(link("/evenement/test-" + str(i))
                                  for i in range(210)) + "</main>"
        out = discover_html_event_pages(PIN, document(body))
        self.assertEqual(out["stage"], "too_many_index_candidates")
        self.assertEqual(out["private_routing_proposals"], [])

    def test_genuine_http_reader_gets_pinned_url_only(self):
        markup = document("<main>" + link("/evenement/cocon") + "</main>")["html"]
        net = MockHttp(markup)
        out = discover_live_html_event_pages(PIN, opener=net)
        self.assertEqual(out["counts"]["same_host_child_pages"], 1)
        self.assertEqual(net.url, PIN["exact_index_url"])
        self.assertEqual(net.request.get_method(), "GET")
        self.assertEqual(net.timeout, 12)
        self.assertIsNone(net.request.get_header("Key"))

    def test_redirect_wrong_status_or_type_are_refused(self):
        markup = document("<main>" + link("/evenement/cocon") + "</main>")["html"]
        for arguments in (
            {"redirect": True}, {"status": 302}, {"mime": "application/json"}
        ):
            with self.subTest(arguments=arguments):
                out = discover_live_html_event_pages(
                    PIN, opener=MockHttp(markup, **arguments))
                self.assertEqual(out["stage"], "index_html_unavailable")
                self.assertEqual(out["private_routing_proposals"], [])

    def test_redacted_public_report_cannot_contain_private_urls_or_titles(self):
        body = "<main>" + link("/evenement/bambins-musiciens", "Bambins musiciens") + "</main>"
        report = discover_html_event_pages(PIN, document(body))
        public = redacted_html_index_counts(report)
        serialized = json.dumps(public)
        for secret in ("mpt.montpellier.fr", "/evenement/bambins-musiciens",
                       "Bambins musiciens", "https://"):
            self.assertNotIn(secret, serialized)
        self.assertFalse(public["approval_granted"])
        self.assertFalse(public["contains_private_identifiers"])
        forged = redacted_html_index_counts({
            "schema": report["schema"],
            "counts": {"same_host_child_pages": True,
                       "visible_index_anchors": -1,
                       "out_of_scope_links": "private",
                       "duplicate_child_links": 20000},
            "private_routing_proposals": [{"secret": "leak"}],
        })
        self.assertTrue(all(v == 0 for v in forged["counts"].values()))
        self.assertNotIn("leak", json.dumps(forged))


if __name__ == "__main__":
    unittest.main()
