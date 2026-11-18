"""Adversarial preflight: institutional OA root link is NOT event permission."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_openagenda_v2_institutional_delegation import (
    inspect_institutional_agenda_page,
    redacted_agenda_reference,
    diagnose_delegated_calendar_candidate,
)
from test_ptitesondes_openagenda_v2_joined_evidence import envelope, TODAY

HOST = "bibliotheque-test.fr"
PAGE_URL = "https://" + HOST + "/programme"
DEFAULT = envelope()
AGENDA = DEFAULT["reviewed_agenda"]
SLUG = AGENDA["agenda_slug"]
ROOT = "https://openagenda.com/" + SLUG
REVIEWED = {
    "institution_host": HOST, "exact_page_url": PAGE_URL,
    "agenda_slug": SLUG, "agenda_uid": AGENDA["agenda_uid"],
    "timezone": AGENDA["timezone"],
}


def html(anchors=None):
    if anchors is None:
        anchors = ('<a href="' + ROOT + '">Notre agenda de la médiathèque</a>')
    return "<html><body><main><h1>Programme de la ville</h1>" + anchors + "</main></body></html>"


def inspect(page=None, source=None, fetched_url=None):
    return inspect_institutional_agenda_page(
        deepcopy(REVIEWED if source is None else source),
        {"url": PAGE_URL if fetched_url is None else fetched_url,
         "html": html() if page is None else page})


def direct_case():
    c = envelope()
    del c["reviewed_agenda"]
    del c["reviewed_organizer"]
    del c["organizer_page"]
    return c


class DelegatedAgendaPreflight(unittest.TestCase):
    def test_exact_visible_root_link_is_independently_observed_not_owned(self):
        out = inspect()
        self.assertTrue(out["institutional_root_link_observed"])
        self.assertFalse(out["independently_attested_owner"])
        self.assertFalse(out["event_session_verified"])
        self.assertFalse(out["rights_reviewed"])
        self.assertFalse(out["approval_granted"])
        self.assertEqual(out["public_writes"], 0)
        self.assertNotIn(ROOT, json.dumps(redacted_agenda_reference(out)))

    def test_locale_prefixed_root_is_readable_but_not_event_url(self):
        url = "https://openagenda.com/fr/" + SLUG
        self.assertTrue(inspect(html('<a href="' + url +
            '">Agenda des animations</a>'))["institutional_root_link_observed"])
        bad = ROOT + "/events/12345678_titre"
        self.assertFalse(inspect(html('<a href="' + bad +
            '">Agenda officiel</a>'))["institutional_root_link_observed"])

    def test_query_redirect_anchor_and_lookalike_domains_fail_closed(self):
        for url in (
            ROOT + "?redirect=https://evil.example",
            ROOT + "#event",
            ROOT + "/events/12345",
            "http://openagenda.com/" + SLUG,
            "https://openagenda.com.evil.example/" + SLUG,
            "https://openagenda.com@" + HOST + "/" + SLUG,
            "https://api.openagenda.com/" + SLUG,
            "https://evil.example/" + SLUG,
        ):
            with self.subTest(url=url):
                result = inspect(html('<a href="' + url.replace("&", "&amp;") +
                    '">Agenda officiel</a>'))
                self.assertEqual(result["reason"], "no_visible_exact_root_link")

    def test_hidden_or_unlabelled_root_link_is_not_institutional_attestation(self):
        for markup in (
            '<a href="' + ROOT + '" hidden>Agenda enfants</a>',
            '<a href="' + ROOT + '" style="display:none">Agenda enfants</a>',
            '<span hidden><a href="' + ROOT + '">Notre agenda</a></span>',
            '<script><a href="' + ROOT + '">Agenda officiel</a></script>',
            '<a href="' + ROOT + '">Cliquez ici</a>',
        ):
            with self.subTest(markup=markup[:32]):
                self.assertFalse(inspect(html(markup))[
                    "institutional_root_link_observed"])

    def test_source_is_independent_not_supplied_by_candidate(self):
        candidate = direct_case()
        candidate["lead"].update({
            "institution_host": "evil.example",
            "exact_page_url": "https://evil.example/agenda",
            "agenda_slug": "evil", "approval_granted": True,
        })
        out = diagnose_delegated_calendar_candidate(
            candidate, REVIEWED, {"url": PAGE_URL, "html": html()}, TODAY)
        self.assertTrue(out["institutional_calendar_link_observed"])
        self.assertFalse(out["approval_granted"])
        self.assertFalse(out["independent_event_session_verified"])

    def test_bad_registry_or_redirect_fetch_not_accepted(self):
        for source in (
            dict(REVIEWED, institution_host="evil.example"),
            dict(REVIEWED, exact_page_url="http://" + HOST + "/programme"),
            dict(REVIEWED, agenda_slug="../autre"),
            dict(REVIEWED, agenda_uid="no"),
            dict(REVIEWED, timezone="Mars/Phobos"),
            dict(REVIEWED, untrusted=True),
        ):
            with self.subTest(source=str(source.keys())):
                self.assertFalse(inspect(source=source)[
                    "institutional_root_link_observed"])
        self.assertFalse(inspect(fetched_url="https://" + HOST + "/redir")[
            "institutional_root_link_observed"])

    def test_wrong_venue_blocks_event_even_with_institutional_link(self):
        candidate = direct_case()
        candidate["venue_page"]["url"] = "https://evil.example"
        out = diagnose_delegated_calendar_candidate(
            candidate, REVIEWED, {"url": PAGE_URL, "html": html()}, TODAY)
        self.assertEqual(out["stage"], "independent_venue_not_verified")
        self.assertFalse(out["direct_source_verified"])

    def test_wrong_agenda_identity_blocks_direct_event(self):
        reviewed = dict(REVIEWED, agenda_uid=99999999)
        out = diagnose_delegated_calendar_candidate(
            direct_case(), reviewed, {"url": PAGE_URL, "html": html()}, TODAY)
        self.assertEqual(out["stage"], "direct_openagenda_event_not_verified")

    def test_positive_structural_chain_never_verifies_session_or_ownership(self):
        result = diagnose_delegated_calendar_candidate(
            direct_case(), REVIEWED, {"url": PAGE_URL, "html": html()}, TODAY)
        self.assertEqual(result["stage"],
                         "calendar_referenced_but_event_proof_pending")
        self.assertTrue(result["venue_verified"])
        self.assertTrue(result["direct_source_verified"])
        self.assertTrue(result["institutional_calendar_link_observed"])
        self.assertFalse(result["organizer_ownership_attested"])
        self.assertFalse(result["independent_event_session_verified"])
        self.assertFalse(result["approval_granted"])
        self.assertFalse(result["publisher_connected"])
        self.assertEqual(result["public_writes"], 0)
        self.assertIn("event_session_independent_proof", result["outstanding_gates"])
        self.assertIn("rights_and_reuse", result["outstanding_gates"])

    def test_multiple_days_are_never_silently_split_into_events(self):
        c = direct_case()
        c["api_event"]["timings"].append({
            "begin": "2026-12-06T16:00:00+0100",
            "end": "2026-12-06T17:00:00+0100",
        })
        out = diagnose_delegated_calendar_candidate(
            c, REVIEWED, {"url": PAGE_URL, "html": html()}, TODAY)
        self.assertEqual(out["stage"], "multi_day_grouping_required")
        self.assertFalse(out["independent_event_session_verified"])

    def test_no_organizer_page_no_event_session_no_publication(self):
        result = diagnose_delegated_calendar_candidate(
            direct_case(), REVIEWED,
            {"url": PAGE_URL, "html": html()}, TODAY)
        for field in ("approval_granted", "publisher_connected",
                      "independent_event_session_verified",
                      "organizer_ownership_attested"):
            self.assertFalse(result[field])

    def test_visible_extra_sibling_does_not_create_forged_institution_link(self):
        extra = ('<p>Agenda de la ville</p><a href="' + ROOT +
                 '">Site externe</a>')
        self.assertFalse(inspect(html(extra))["institutional_root_link_observed"])

    def test_fail_closed_for_invalid_or_oversized_document_and_redaction(self):
        self.assertEqual(inspect(page="<html>").get("reason"),
                         "institutional_page_unavailable")
        self.assertEqual(inspect(page="x"*500001).get("reason"),
                         "institutional_page_unavailable")
        redacted = redacted_agenda_reference({"reason": "SECRET_PRIVATE_SLUG"})
        self.assertNotIn("SECRET_PRIVATE_SLUG", json.dumps(redacted))
        self.assertFalse(redacted["approval_granted"])


if __name__ == "__main__":
    unittest.main()
