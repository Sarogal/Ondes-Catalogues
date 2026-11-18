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
    select_pinned_agenda_for_lead, census_institution_pins_on_private_backlog,
    diagnose_legacy_ods_authenticated_mapping,
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

TRUSTED = {
    "agenda_uid": AGENDA["agenda_uid"],
    "event_uid": DEFAULT["lead"]["external_id"],
    "response_url": (
        "https://api.openagenda.com/v2/agendas/"
        + str(AGENDA["agenda_uid"]) + "/events/"
        + str(DEFAULT["lead"]["external_id"])),
    "method": "GET", "status": 200, "key_kind": "public_read_only",
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
            candidate, REVIEWED, {"url": PAGE_URL, "html": html()}, TODAY, TRUSTED)
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
            candidate, REVIEWED, {"url": PAGE_URL, "html": html()}, TODAY, TRUSTED)
        self.assertEqual(out["stage"], "independent_venue_not_verified")
        self.assertFalse(out["direct_source_verified"])


    def test_trusted_api_request_required_and_cannot_be_replaced_by_lead_claim(self):
        c = direct_case()
        unbound = diagnose_delegated_calendar_candidate(
            c, REVIEWED, {"url": PAGE_URL, "html": html()}, TODAY)
        self.assertEqual(unbound["stage"],
                         "direct_api_request_not_independently_bound")
        c["lead"]["api_request_verified"] = True
        c["lead"]["api_response_url"] = TRUSTED["response_url"]
        unbound = diagnose_delegated_calendar_candidate(
            c, REVIEWED, {"url": PAGE_URL, "html": html()}, TODAY)
        self.assertEqual(unbound["stage"],
                         "direct_api_request_not_independently_bound")
        for modification in (
            {"status": True},
            {"status": 302},
            {"method": "POST"},
            {"key_kind": "owner_secret"},
            {"agenda_uid": 99999999},
            {"event_uid": "98765432"},
            {"response_url": TRUSTED["response_url"] + "?key=leak"},
        ):
            with self.subTest(modification=modification):
                bad = dict(TRUSTED, **modification)
                result = diagnose_delegated_calendar_candidate(
                    c, REVIEWED, {"url": PAGE_URL, "html": html()},
                    TODAY, bad)
                self.assertEqual(result["stage"],
                                 "direct_api_request_not_independently_bound")
                self.assertEqual(result["public_writes"], 0)

    def test_wrong_agenda_identity_blocks_before_accepting_api_response(self):
        reviewed = dict(REVIEWED, agenda_uid=99999999)
        out = diagnose_delegated_calendar_candidate(
            direct_case(), reviewed, {"url": PAGE_URL, "html": html()}, TODAY, TRUSTED)
        self.assertEqual(out["stage"], "direct_api_request_not_independently_bound")

    def test_positive_structural_chain_never_verifies_session_or_ownership(self):
        result = diagnose_delegated_calendar_candidate(
            direct_case(), REVIEWED, {"url": PAGE_URL, "html": html()}, TODAY, TRUSTED)
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
            c, REVIEWED, {"url": PAGE_URL, "html": html()}, TODAY, TRUSTED)
        self.assertEqual(out["stage"], "multi_day_grouping_required")
        self.assertFalse(out["independent_event_session_verified"])

    def test_no_organizer_page_no_event_session_no_publication(self):
        result = diagnose_delegated_calendar_candidate(
            direct_case(), REVIEWED,
            {"url": PAGE_URL, "html": html()}, TODAY, TRUSTED)
        for field in ("approval_granted", "publisher_connected",
                      "independent_event_session_verified",
                      "organizer_ownership_attested"):
            self.assertFalse(result[field])

    def test_visible_extra_sibling_does_not_create_forged_institution_link(self):
        extra = ('<p>Agenda de la ville</p><a href="' + ROOT +
                 '">Site externe</a>')
        self.assertFalse(inspect(html(extra))["institutional_root_link_observed"])


    def test_curated_agenda_pin_ignores_claimed_organizer_and_duplicate_registry(self):
        c = direct_case()["lead"]
        c["official_url"] = "https://evil.example/owned"
        reason, pin = select_pinned_agenda_for_lead(c, [REVIEWED])
        self.assertEqual(reason, "institution_pin_selected_for_verification_only")
        self.assertEqual(pin, REVIEWED)
        self.assertEqual(
            select_pinned_agenda_for_lead(c, [])[0],
            "no_independently_curated_institution")
        duplicate = dict(REVIEWED,
                         institution_host="second-library.example",
                         exact_page_url="https://second-library.example/agenda")
        reason, pin = select_pinned_agenda_for_lead(
            c, [REVIEWED, duplicate])
        self.assertEqual(reason, "institution_registry_ambiguous")
        self.assertIsNone(pin)

    def test_untrusted_event_url_or_uid_cannot_select_source(self):
        c = direct_case()["lead"]
        for untrusted in (
            dict(c, external_id="8888888"),
            dict(c, source_url="https://openagenda.com.evil.example/agenda/events/123"),
            dict(c, source_url="http://openagenda.com/" + SLUG),
        ):
            self.assertEqual(
                select_pinned_agenda_for_lead(untrusted, [REVIEWED])[0],
                "lead_identity_invalid")

    def test_registry_rejects_unreviewed_source_and_excessive_size(self):
        for records in (
            [dict(REVIEWED, institution_host="openagenda.com",
                  exact_page_url=ROOT)],
            [dict(REVIEWED, timezone="Mars/Phobos")],
            [dict(REVIEWED, extra="unreviewed")],
            [REVIEWED] * 501,
        ):
            with self.assertRaises(ValueError):
                select_pinned_agenda_for_lead(
                    direct_case()["lead"], records)

    def test_real_backlog_census_shape_is_private_and_not_approval(self):
        c = direct_case()["lead"]
        leads = [
            dict(c), dict(c), dict(c, date_start="2026-01-01"),
            dict(c, date_start="bad"), dict(c, external_id="invalid"),
        ]
        r = census_institution_pins_on_private_backlog(
            leads, [REVIEWED], TODAY)
        self.assertEqual(r["counts"].get("future_in_window_rows"), 3)
        self.assertEqual(
            r["counts"].get("institution_pin_selected_for_verification_only"), 2)
        self.assertEqual(r["counts"].get("lead_identity_invalid"), 1)
        self.assertEqual(r["counts"].get("expired_rows"), 1)
        self.assertEqual(r["counts"].get("invalid_or_missing_date"), 1)
        self.assertFalse(r["approval_granted"])
        self.assertFalse(r["institutional_ownership_attested"])
        self.assertEqual(r["public_writes"], 0)
        for secret in (PAGE_URL, HOST, SLUG, c["title"], c["source_url"]):
            self.assertNotIn(secret, json.dumps(r))


    def test_legacy_ods_mirror_routed_to_api_not_accepted_as_direct_proof(self):
        c = dict(direct_case()["lead"], collector="opendatasoft-index",
                 source_url="https://openagenda.com/" + SLUG
                 + "/events/lecture-pour-enfants")
        status, pin = select_pinned_agenda_for_lead(c, [REVIEWED])
        self.assertEqual(status, "legacy_ods_mirror_needs_authenticated_api_bridge")
        self.assertIsNone(pin)
        out = diagnose_legacy_ods_authenticated_mapping(
            c, REVIEWED, direct_case()["api_event"], TRUSTED)
        self.assertEqual(out["stage"],
                         "legacy_identity_api_bound_other_gates_pending")
        self.assertTrue(out["api_event_identity_bound_for_review"])
        self.assertFalse(out["canonical_source_url_verified"])
        self.assertFalse(out["independent_event_sessions_verified"])
        self.assertFalse(out["approval_granted"])
        self.assertEqual(out["public_writes"], 0)
        raw = json.dumps(out)
        for private in (PAGE_URL, HOST, SLUG, c["title"], c["source_url"]):
            self.assertNotIn(private, raw)

    def test_legacy_bridge_requires_private_direct_get_and_true_identity(self):
        c = dict(direct_case()["lead"], collector="opendatasoft-index",
                 source_url="https://openagenda.com/" + SLUG
                 + "/events/lecture-pour-enfants")
        evt = direct_case()["api_event"]
        for ctx in (
            None, dict(TRUSTED, method="POST"),
            dict(TRUSTED, status=301),
            dict(TRUSTED, key_kind="owner_secret"),
            dict(TRUSTED, agenda_uid="9999999"),
            dict(TRUSTED, event_uid="77777777"),
            dict(TRUSTED, response_url=TRUSTED["response_url"]+"?key=secret"),
        ):
            with self.subTest(context=bool(ctx)):
                result = diagnose_legacy_ods_authenticated_mapping(
                    c, REVIEWED, evt, ctx)
                self.assertEqual(result["stage"],
                                 "api_event_request_not_independently_bound")
                self.assertFalse(result["api_event_identity_bound_for_review"])
        for payload, stage in (
            (dict(evt, uid=98765432), "api_event_uid_not_concordant"),
            (dict(evt, title={"fr": "Spectacle adultes"}),
             "api_event_title_not_concordant"),
            (dict(evt, location=dict(evt["location"], name="Lieu différent")),
             "api_event_place_identity_not_concordant"),
        ):
            result = diagnose_legacy_ods_authenticated_mapping(
                c, REVIEWED, payload, TRUSTED)
            self.assertEqual(result["stage"], stage)
            self.assertFalse(result["approval_granted"])

    def test_fake_legacy_domain_or_uid_in_url_is_never_accepted(self):
        c = dict(direct_case()["lead"], collector="opendatasoft-index")
        for url in (
            "https://openagenda.com.evil.example/" + SLUG + "/events/titre",
            "https://openagenda.com/" + SLUG + "/events/12345678_titre",
            "https://openagenda.com/" + SLUG + "/events/titre?redirect=evil",
            "https://openagenda.com/" + SLUG + "/events/titre#fake",
            "http://openagenda.com/" + SLUG + "/events/titre",
        ):
            with self.subTest(url=url):
                out = diagnose_legacy_ods_authenticated_mapping(
                    dict(c, source_url=url), REVIEWED,
                    direct_case()["api_event"], TRUSTED)
                self.assertEqual(out["stage"],
                                 "invalid_or_unreviewed_legacy_pointer")

    def test_legacy_mirrors_counted_separately_from_strict_url_uid(self):
        c = dict(direct_case()["lead"], collector="opendatasoft-index")
        mirror = dict(c, source_url="https://openagenda.com/" + SLUG
                      + "/events/lecture-pour-enfants")
        report = census_institution_pins_on_private_backlog(
            [c, mirror], [REVIEWED], TODAY)
        self.assertEqual(
            report["counts"].get("institution_pin_selected_for_verification_only"), 1)
        self.assertEqual(
            report["counts"].get("legacy_ods_mirror_needs_authenticated_api_bridge"), 1)
        self.assertFalse(report["approval_granted"])

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
