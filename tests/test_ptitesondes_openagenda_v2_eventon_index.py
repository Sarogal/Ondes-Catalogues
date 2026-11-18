"""Adversarial EventON/evcal index fixtures; no network or event approval."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_openagenda_v2_eventon_index import (
    nominate_eventon_page, verify_eventon_page, redacted_eventon_stage,
)
from ptitesondes_openagenda_v2_joined_evidence import (
    diagnose_eventon_candidate,
)
from test_ptitesondes_openagenda_v2_joined_evidence import (
    envelope, html as organizer_html, TODAY,
)

HOST = "www.bibliotheque-test.fr"
INDEX_URL = "https://" + HOST + "/agenda/rss-2/"
EVENT_URL = "https://" + HOST + "/programmation/lecture"
REVIEWED = {"approved_host": HOST, "exact_index_url": INDEX_URL}


def stamp(day=5, month=12, year=2026, hour=14, minute=30):
    return str(int(datetime(year, month, day, hour, minute,
                            tzinfo=timezone.utc).timestamp()))


def anchor(day=5, href="/programmation/lecture", title="Lecture pour enfants",
           classes="desc_trig evcal_list_a sin_val evo_jeune-public",
           anchor_id=None, hidden=""):
    evc = anchor_id or ("evc_" + stamp(day=day) + "22790")
    return ('<a id="' + evc + '" class="' + classes + '" ' + hidden +
            'href="' + href + '">' + title + '</a>')


def html(anchors=None):
    anchors = [anchor()] if anchors is None else anchors
    return ("<html><body><main><h1>Agenda</h1><div "
            'class="ajde_evcal_calendar">' +
            "".join("<section>" + part + "</section>" for part in anchors) +
            "</div></main></body></html>")


def lead():
    return deepcopy(envelope()["lead"])


def nomination(*, links=None, item=None, registry=None, final=None):
    return nominate_eventon_page(
        lead() if item is None else item,
        REVIEWED if registry is None else registry,
        {"url": INDEX_URL if final is None else final,
         "html": html(links)})


class EventONFirstPartyIndex(unittest.TestCase):
    def test_plugin_anchor_with_exact_title_and_date_routes_only(self):
        x = nomination()
        self.assertTrue(x["first_party_event_page_nominated"])
        self.assertEqual(x["reviewed_organizer"], {
            "approved_host": HOST, "exact_url": EVENT_URL,
        })
        self.assertFalse(x["verified_event_time"])
        self.assertFalse(x["organizer_ownership_attested"])
        self.assertFalse(x["approval_granted"])
        self.assertEqual(x["public_writes"], 0)
        self.assertNotIn(EVENT_URL, json.dumps(redacted_eventon_stage(x)))

    def test_real_observed_eventon_identifier_shape_is_accepted_as_hint(self):
        x = nomination(item={"title": "Bouquins câlins",
                             "date_start": "2026-11-25"},
                       links=[anchor(
                           anchor_id="evc_179559900022790",
                           title="Bouquins câlins",
                           href="/agenda/event/bouquins-calins-public/")])
        self.assertTrue(x["first_party_event_page_nominated"], x["reason"])
        self.assertIn("/agenda/event/", x["reviewed_organizer"]["exact_url"])

    def test_repeated_same_title_selects_single_matching_calendar_day(self):
        links = [
            anchor(day=5, href="/programmation/lecture"),
            anchor(day=15, href="/programmation/lecture-15"),
            anchor(day=25, href="/programmation/lecture-25"),
        ]
        x = nomination(links=links)
        self.assertTrue(x["first_party_event_page_nominated"])
        self.assertEqual(x["reviewed_organizer"]["exact_url"], EVENT_URL)

    def test_multiple_same_day_competing_pages_fail_closed(self):
        links = [
            anchor(href="/programmation/lecture"),
            anchor(href="/programmation/autre"),
        ]
        x = nomination(links=links)
        self.assertEqual(x["reason"], "ambiguous_eventon_occurrence_or_link")
        self.assertNotIn("reviewed_organizer", x)

    def test_exact_duplicate_same_page_does_not_create_fake_ambiguity(self):
        x = nomination(links=[anchor(), anchor()])
        self.assertTrue(x["first_party_event_page_nominated"])

    def test_hidden_or_non_plugin_anchor_never_nominate(self):
        cases = [
            anchor(hidden="hidden "),
            anchor(hidden='aria-hidden="true" '),
            '<div style="display:none">' + anchor() + "</div>",
            anchor(classes="evcal_list_a"),
            anchor(classes="desc_trig"),
            anchor(classes="evo_jeune-public"),
            '<script>' + anchor() + "</script>",
        ]
        for c in cases:
            with self.subTest(c=c[:42]):
                self.assertEqual(nomination(links=[c])["reason"],
                                 "no_exact_eventon_occurrence")

    def test_forged_other_host_and_redirect_queries_refused(self):
        urls = (
            "https://evil.example/event",
            "https://" + HOST + "@evil.example/event",
            "//evil.example/event", "javascript:alert(1)",
            "http://" + HOST + "/event",
            "https://" + HOST + "/event?url=https://evil.example",
            "https://" + HOST + "/event#frag",
        )
        for url in urls:
            with self.subTest(url=url):
                c = anchor(href=url.replace("&", "&amp;"))
                self.assertFalse(nomination(links=[c])[
                    "first_party_event_page_nominated"])

    def test_bad_plugin_id_and_distant_dates_blocked(self):
        for bad in (
            "evc_foo", "evc_000000000022790",
            "evc_1795599000", "evc_179559900022790_fake",
            "evt_179559900022790",
        ):
            self.assertFalse(nomination(links=[anchor(anchor_id=bad)])[
                "first_party_event_page_nominated"])
        self.assertFalse(nomination(links=[anchor(day=20)])[
            "first_party_event_page_nominated"])

    def test_independent_registry_url_cannot_come_from_lead(self):
        evil = dict(lead(), approved_host="evil.example",
                    exact_index_url="https://evil.example/events",
                    approved=True)
        self.assertTrue(nomination(item=evil)["first_party_event_page_nominated"])
        self.assertFalse(nomination(registry=dict(
            REVIEWED, approved_host="evil.example"))[
                "first_party_event_page_nominated"])
        self.assertFalse(nomination(final="https://evil.example/events")[
            "first_party_event_page_nominated"])

    def test_invalid_date_or_title_fails_before_html_analysis(self):
        for date_token in ("2026-12-32", "2026/12/05", None, "2026-12-5"):
            with self.subTest(day=date_token):
                r = nomination(item=dict(lead(), date_start=date_token))
                self.assertEqual(r["reason"], "candidate_title_or_day_invalid")
        self.assertEqual(
            nomination(item=dict(lead(), title=""))["reason"],
            "candidate_title_or_day_invalid")

    def test_page_fetch_exact_url_and_bounds_required(self):
        pin = nomination()
        self.assertTrue(verify_eventon_page(
            pin, {"url": EVENT_URL, "html": organizer_html()}))
        self.assertFalse(verify_eventon_page(
            pin, {"url": EVENT_URL + "/", "html": organizer_html()}))
        self.assertFalse(verify_eventon_page(
            pin, {"url": EVENT_URL, "html": "oops"}))

    def test_joined_candidate_requires_official_session_and_other_gates(self):
        case = envelope()
        case.pop("reviewed_organizer")
        case.pop("organizer_page")
        case["organizer_event_page"] = {
            "url": EVENT_URL, "html": organizer_html()}
        result = diagnose_eventon_candidate(
            case, REVIEWED, {"url": INDEX_URL, "html": html()}, TODAY)
        self.assertEqual(result["stage"],
                         "structural_evidence_complete_other_gates_pending")
        self.assertFalse(result["approval_granted"])
        self.assertFalse(result["publisher_connected"])
        self.assertIn("historic_deduplication", result["outstanding_gates"])
        case["organizer_event_page"]["html"] = organizer_html().replace(
            "5 décembre 2026", "6 décembre 2026")
        held = diagnose_eventon_candidate(
            case, REVIEWED, {"url": INDEX_URL, "html": html()}, TODAY)
        self.assertEqual(held["stage"], "organizer_session_not_confirmed")

    def test_index_or_event_url_mismatch_fails_joined(self):
        case = envelope()
        case.pop("reviewed_organizer")
        case.pop("organizer_page")
        case["organizer_event_page"] = {
            "url": EVENT_URL + "/",
            "html": organizer_html(),
        }
        x = diagnose_eventon_candidate(
            case, REVIEWED, {"url": INDEX_URL, "html": html()}, TODAY)
        self.assertEqual(x["stage"], "organizer_event_page_not_exact")
        x = diagnose_eventon_candidate(
            case, REVIEWED,
            {"url": INDEX_URL, "html": html([anchor(day=20)])}, TODAY)
        self.assertEqual(x["stage"], "eventon_index_not_confirmed")

    def test_anonymous_reason_only_and_bad_inputs(self):
        x = redacted_eventon_stage({"reason": "PRIVATE_USER_FAKE"})
        self.assertNotIn("PRIVATE_USER_FAKE", json.dumps(x))
        self.assertFalse(x["approval_granted"])
        self.assertFalse(x["contains_event_url_or_id"])
        self.assertEqual(nomination(links=[anchor()] * 2401)["reason"],
                         "index_unavailable")
        self.assertFalse(nomination(
            links=['<' + 'x' * 2000100 + '>'])[
                "first_party_event_page_nominated"])


if __name__ == "__main__":
    unittest.main()
