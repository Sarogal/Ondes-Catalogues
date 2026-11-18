"""Adversarial offline verification: trusted organizer INDEX, never lead URL."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_openagenda_v2_organizer_index import (
    discover_from_reviewed_index, check_indexed_event_fetch,
    redacted_index_stage, _VisibleAnchors,
)
from ptitesondes_openagenda_v2_joined_evidence import diagnose_candidate
from test_ptitesondes_openagenda_v2_joined_evidence import (
    envelope, html as official_event_html, TODAY,
)

INDEX = {
    "approved_host": "www.bibliotheque-test.fr",
    "exact_index_url": "https://www.bibliotheque-test.fr/agenda",
}
EVENT_URL = "https://www.bibliotheque-test.fr/programmation/lecture"
LEAD = {"title": "Lecture pour enfants", "city": "Rouen",
        "venue": "Médiathèque des Familles",
        "source_url": "https://openagenda.com/commune-test/events/12345678_lecture"}


def document(anchor=None, before="", after=""):
    if anchor is None:
        anchor = '<a href="/programmation/lecture">Lecture pour enfants</a>'
    return ("<html><body><main><h1>Agenda officiel</h1>" + before +
            "<nav>" + anchor + "</nav>" + after + "</main></body></html>")


def discover(*, lead=None, registry=None, index_html=None, page_url=None):
    registry = deepcopy(INDEX if registry is None else registry)
    return discover_from_reviewed_index(
        deepcopy(LEAD if lead is None else lead), registry,
        {"url": INDEX["exact_index_url"] if page_url is None else page_url,
         "html": document() if index_html is None else index_html})


class InstitutionalIndexContract(unittest.TestCase):
    def test_exact_visible_same_origin_link_is_private_nomination_only(self):
        result = discover()
        self.assertTrue(result["indexed_event_link_confirmed"])
        self.assertEqual(result["reviewed_organizer"],
                         {"approved_host": INDEX["approved_host"],
                          "exact_url": EVENT_URL})
        self.assertFalse(result["owner_attested"])
        self.assertFalse(result["approval_granted"])
        self.assertFalse(result["publisher_connected"])
        self.assertEqual(result["public_writes"], 0)
        self.assertNotIn(EVENT_URL, json.dumps(redacted_index_stage(result)))

    def test_collector_cannot_choose_different_host_or_href(self):
        payload = dict(LEAD,
                       exact_url="https://fake.example/takeover",
                       official_url="https://fake.example/takeover",
                       approved_host="fake.example",
                       organizer_approved=True)
        r = discover(lead=payload)
        self.assertTrue(r["indexed_event_link_confirmed"])
        self.assertEqual(r["reviewed_organizer"]["exact_url"], EVENT_URL)

    def test_disallow_external_cross_host_and_untrusted_schemes(self):
        for href in ("https://fake.example/lecture",
                     "//fake.example/lecture", "http://www.bibliotheque-test.fr/lecture",
                     "javascript:alert(1)", "https://127.0.0.1/lecture",
                     "https://www.bibliotheque-test.fr@fake.example/lecture",
                     "/agenda/lecture?redirect=https://fake.example/",
                     "/agenda/lecture#section"):
            with self.subTest(href=href):
                raw = document('<a href="' + href + '">Lecture pour enfants</a>')
                self.assertFalse(discover(index_html=raw)["indexed_event_link_confirmed"])

    def test_hidden_or_unrelated_links_must_not_choose(self):
        for element in (
            '<a style="display:none" href="/programmation/lecture">Lecture pour enfants</a>',
            '<a hidden href="/programmation/lecture">Lecture pour enfants</a>',
            '<a aria-hidden="true" href="/programmation/lecture">Lecture pour enfants</a>',
            '<div hidden><a href="/programmation/lecture">Lecture pour enfants</a></div>',
            '<script><a href="/programmation/lecture">Lecture pour enfants</a></script>',
            '<a href="/programmation/lecture">Atelier pour adultes</a>',
        ):
            with self.subTest(tag=element[:28]):
                self.assertEqual(discover(index_html=document(element))["reason"],
                                 "no_independently_indexed_event_link")

    def test_multiple_matching_event_urls_cannot_autoselect(self):
        doc = document(
            '<a href="/programmation/lecture">Lecture pour enfants</a>' +
            '<a href="/programmation/autre">Lecture pour enfants</a>')
        result = discover(index_html=doc)
        self.assertEqual(result["reason"], "ambiguous_official_event_links")
        self.assertNotIn("reviewed_organizer", result)

    def test_same_url_repeated_once_is_not_ambiguous(self):
        doc = document(
            '<a href="/programmation/lecture">Lecture pour enfants</a>' +
            '<a href="/programmation/lecture">Lecture pour enfants</a>')
        self.assertTrue(discover(index_html=doc)["indexed_event_link_confirmed"])

    def test_index_and_page_must_match_exact_pinned_urls(self):
        self.assertFalse(discover(registry=dict(INDEX,
            approved_host="fake.example"))["indexed_event_link_confirmed"])
        self.assertFalse(discover(page_url="https://fake.example/agenda")[
            "indexed_event_link_confirmed"])
        result = discover()
        good = {"url": EVENT_URL, "html": official_event_html()}
        self.assertTrue(check_indexed_event_fetch(result, good))
        self.assertFalse(check_indexed_event_fetch(result, dict(good, url=EVENT_URL+"/")))
        self.assertFalse(check_indexed_event_fetch(
            result, dict(good, html="<p>x</p>")))

    def test_malformed_input_and_oversized_index_fail_closed(self):
        for bad in (None, {}, {"title": None}, {"title": "Lecture pour enfants" * 1000}):
            with self.subTest(bad=str(type(bad))):
                self.assertFalse(discover(lead=bad)["indexed_event_link_confirmed"])
        self.assertFalse(discover(index_html="z"*350001)["indexed_event_link_confirmed"])
        self.assertEqual(len(redacted_index_stage({"reason": "PRIVATE secret"})), 5)

    def test_link_text_normalization_not_similarity_guessing(self):
        label = '<a href="/programmation/lecture">Lecture pour enfants</a>'
        self.assertTrue(discover(index_html=document(label),
                    lead=dict(LEAD, title="Lecture pour enfants"))[
                        "indexed_event_link_confirmed"])
        self.assertFalse(discover(index_html=document(label),
                    lead=dict(LEAD, title="Lecture pour adolescents"))[
                        "indexed_event_link_confirmed"])

    def test_index_nomination_then_joined_proof_still_not_approval(self):
        case = envelope()
        r = discover()
        self.assertTrue(r["indexed_event_link_confirmed"])
        case["reviewed_organizer"] = r["reviewed_organizer"]
        case["organizer_page"] = {
            "url": EVENT_URL, "html": official_event_html()}
        self.assertTrue(check_indexed_event_fetch(r, case["organizer_page"]))
        joined = diagnose_candidate(case, TODAY)
        self.assertEqual(joined["stage"],
                         "structural_evidence_complete_other_gates_pending")
        self.assertFalse(joined["approval_granted"])
        self.assertFalse(joined["publisher_connected"])
        self.assertIn("reuse_rights", joined["outstanding_gates"])


if __name__ == "__main__":
    unittest.main()
