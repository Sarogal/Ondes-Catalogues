"""Adversarial read-only coverage: only trusted live reads bind OA2 identity."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_oa2_live_pinned_bridge import diagnose_live_pinned_agenda
from test_ptitesondes_openagenda_v2_institutional_delegation import (
    direct_case, REVIEWED, ROOT, html,
)

PUBLIC_KEY = "oa_pk_" + "x" * 30


class MockFetch:
    def __init__(self, payload, content_type, status=200, redirect=False):
        self.payload = payload
        self.content_type = content_type
        self.status = status
        self.redirect = redirect
        self.request = None

    def __call__(self, request, timeout):
        self.request = request
        self.timeout = timeout
        self.url = request.full_url
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def geturl(self):
        return self.url + "/redirect" if self.redirect else self.url

    @property
    def headers(self):
        return {"Content-Type": self.content_type}

    def read(self, size):
        self.read_size = size
        if isinstance(self.payload, str):
            return self.payload.encode("utf-8")
        return json.dumps(self.payload).encode("utf-8")


def sources():
    return [deepcopy(REVIEWED)]


def readers(event=None, institution_html=None, status=200, redirect=False):
    c = direct_case()
    p = (deepcopy(c["api_event"]) if event is None else event)
    official = MockFetch(
        html() if institution_html is None else institution_html, "text/html")
    api = MockFetch(p, "application/json", status=status, redirect=redirect)
    return official, api


def verify(lead=None, pins=None, key=PUBLIC_KEY, official=None, api=None):
    if lead is None:
        lead = direct_case()["lead"]
    if pins is None:
        pins = sources()
    if official is None or api is None:
        default_official, default_api = readers()
        official = official or default_official
        api = api or default_api
    return diagnose_live_pinned_agenda(
        lead, pins, key, institution_opener=official, api_opener=api)


class LivePinnedBridgeTests(unittest.TestCase):
    def test_exact_http_get_from_reviewed_agenda_uid_never_approves(self):
        official, api = readers()
        c = direct_case()
        out = verify(official=official, api=api)
        self.assertEqual(out["stage"], "strict_api_identity_bound_other_gates_pending")
        self.assertTrue(out["institutional_root_link_observed"])
        self.assertTrue(out["api_identity_bound_for_review"])
        self.assertFalse(out["institution_owner_attested"])
        self.assertFalse(out["independent_event_session_verified"])
        self.assertFalse(out["approval_granted"])
        self.assertEqual(out["public_writes"], 0)
        self.assertEqual(official.url, REVIEWED["exact_page_url"])
        self.assertEqual(
            api.url, "https://api.openagenda.com/v2/agendas/"
            + str(REVIEWED["agenda_uid"]) + "/events/"
            + c["lead"]["external_id"])
        self.assertEqual(api.request.get_method(), "GET")
        self.assertEqual(api.request.get_header("Key"), PUBLIC_KEY)
        self.assertEqual(api.timeout, 18)
        self.assertNotIn(PUBLIC_KEY, api.url)

    def test_historical_ods_slug_is_bridgeable_but_never_canonicalized(self):
        c = direct_case()
        lead = dict(c["lead"], collector="opendatasoft-index",
                    source_url=ROOT + "/events/lecture-pour-enfants")
        official, api = readers()
        out = verify(lead=lead, official=official, api=api)
        self.assertEqual(out["stage"], "legacy_api_identity_bound_other_gates_pending")
        self.assertTrue(out["api_identity_bound_for_review"])
        self.assertFalse(out["independent_event_session_verified"])
        self.assertFalse(out["rights_reviewed"])
        self.assertFalse(out["approval_granted"])
        self.assertNotIn(lead["source_url"], json.dumps(out))

    def test_empty_or_ambiguous_registry_performs_no_network_read(self):
        official, api = readers()
        out = verify(pins=[], official=official, api=api)
        self.assertEqual(out["stage"], "no_independently_curated_institution")
        self.assertIsNone(official.request)
        self.assertIsNone(api.request)
        other = dict(REVIEWED, institution_host="autre-ville.fr",
                     exact_page_url="https://autre-ville.fr/agenda")
        out = verify(pins=[REVIEWED, other], official=official, api=api)
        self.assertEqual(out["stage"], "ambiguous_independently_curated_institution")
        self.assertIsNone(api.request)
        self.assertFalse(out["approval_granted"])

    def test_candidate_cannot_choose_source_or_page(self):
        lead = dict(direct_case()["lead"], institution_host="evil.example",
                    exact_page_url="https://evil.example/forged",
                    agenda_uid=9999, official=True)
        official, api = readers()
        out = verify(lead=lead, official=official, api=api)
        self.assertTrue(out["api_identity_bound_for_review"])
        self.assertEqual(official.url, REVIEWED["exact_page_url"])
        self.assertFalse(out["institution_owner_attested"])

    def test_unreviewed_root_link_and_hidden_link_block_api_read(self):
        for markup in (
            '<a href="' + ROOT + '">Cliquez ici</a>',
            '<a href="' + ROOT + '" hidden>Agenda enfants</a>',
            '<a href="https://openagenda.com.evil.example/slug">Agenda</a>',
        ):
            official, api = readers(institution_html=html(markup))
            out = verify(official=official, api=api)
            self.assertEqual(out["stage"], "institutional_root_link_not_confirmed")
            self.assertIsNone(api.request)

    def test_official_page_redirect_rejected_before_api(self):
        official, api = readers()
        official.redirect = True
        out = verify(official=official, api=api)
        self.assertEqual(out["stage"], "independent_institutional_page_unavailable")
        self.assertIsNone(api.request)

    def test_http_redirect_or_failure_and_secret_key_fail_closed(self):
        for status, redirect in ((401, False), (200, True)):
            official, api = readers(status=status, redirect=redirect)
            out = verify(official=official, api=api)
            self.assertEqual(out["stage"], "trusted_api_direct_read_unavailable")
            self.assertFalse(out["api_identity_bound_for_review"])
        official, api = readers()
        out = verify(key="oa_sk_" + "x" * 30, official=official, api=api)
        self.assertEqual(out["stage"], "trusted_api_direct_read_unavailable")
        self.assertIsNone(api.request)

    def test_uid_title_or_place_mismatch_refused(self):
        base = direct_case()["api_event"]
        variants = [
            (dict(base, uid=123456789), "direct_event_uid_mismatch"),
            (dict(base, title={"fr": "Titre sans rapport"}), "direct_event_identity_not_concordant"),
            (dict(base, location=dict(base["location"], name="Autre lieu")),
             "direct_event_identity_not_concordant"),
        ]
        for event, stage in variants:
            with self.subTest(stage=stage):
                official, api = readers(event=event)
                out = verify(official=official, api=api)
                self.assertEqual(out["stage"], stage)
                self.assertFalse(out["api_identity_bound_for_review"])

    def test_invalid_candidate_and_legacy_collector_refuse_io(self):
        candidate = dict(direct_case()["lead"], source_url=ROOT
                         + "/events/lecture-pour-enfants", collector="forged")
        official, api = readers()
        out = verify(lead=candidate, official=official, api=api)
        self.assertEqual(out["stage"], "invalid_candidate_or_registry")
        self.assertIsNone(official.request)
        self.assertIsNone(api.request)
        c = direct_case()["lead"]
        bad_uid = dict(c, external_id="987654321012")
        out = verify(lead=bad_uid, official=official, api=api)
        self.assertEqual(out["stage"], "invalid_candidate_or_registry")

    def test_report_redacts_all_private_details(self):
        c = direct_case()
        out = verify()
        report = json.dumps(out, ensure_ascii=False)
        for secret in (
            PUBLIC_KEY, c["lead"]["title"], c["lead"]["source_url"],
            c["lead"]["external_id"], REVIEWED["institution_host"],
            REVIEWED["exact_page_url"], ROOT,
        ):
            self.assertNotIn(str(secret), report)
        self.assertFalse(out["contains_private_identifiers"])


if __name__ == "__main__":
    unittest.main()
