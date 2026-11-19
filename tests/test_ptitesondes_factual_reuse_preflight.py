"""Adversarial, offline checks: fact-only private drafts and OA rights metadata."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_factual_reuse_preflight import (
    prepare_private_html_factual_draft, triage_openagenda_licence_metadata,
)
from ptitesondes_openagenda_v2_direct_evidence import SCHEMA as OA_SCHEMA

URL = "https://mpt.montpellier.fr/evenement/atelier-decouverte"
PIN = {
    "approved_host": "mpt.montpellier.fr",
    "exact_index_url": "https://mpt.montpellier.fr/evenements",
}
LEAD = {
    "title": "Atelier découverte", "city": "Montpellier",
    "venue": "Maison pour tous Albert Camus",
    "date_start": "2026-11-21", "start_local": "09:15",
    "source_url": URL, "category": "atelier-creatif",
    "price_evidence": "explicit_free",
    "registration_evidence": "explicit_required",
}
PAGE = """<html><body><main>
<h1>Atelier découverte</h1>
<p>Maison pour tous Albert Camus, Montpellier</p>
<ul><li>21 novembre 2026 - 09:15 > 10:15</li></ul>
{audience}
<p>Sur inscription | Gratuit</p>
<p>Récit protégé original de l'organisateur. Un tigre bleu danse sur la lune.</p>
<h2>Autres événements</h2><p>Adultes uniquement, 10 €</p>
</main></body></html>"""
DIRECT = {
    "schema": OA_SCHEMA, "source_evidence_structurally_valid": True,
    "approval_granted": False, "public_writes": 0,
}
OA_EVENT = {
    "uid": 12345,
    "updatedAt": "2026-11-19T14:38:00+01:00",
    "rights": {
        "license": {
            "id": "etalab-2.0", "name": "Licence Ouverte 2.0",
            "url": "https://www.data.gouv.fr/pages/legal/licences/etalab-2.0/",
        },
        "licensor": {"name": "Institution fictive", "agendaUid": 1024},
        "publisher": {"name": "Autre agrégateur fictif", "agendaUid": 5678},
    },
}
_SENTINEL = object()


def html_draft(audience="<p>Public : familles</p>", *, lead=None, html=None, pin=PIN):
    page = PAGE.replace("{audience}", audience) if html is None else html
    return prepare_private_html_factual_draft(
        LEAD if lead is None else lead,
        {"url": URL, "html": page}, pin, "/evenement/")


class HTMLFactualDraftTests(unittest.TestCase):
    def assert_nonpublish(self, result):
        self.assertIs(result["approval_granted"], False)
        self.assertIs(result["publication_ready"], False)
        self.assertIs(result["rights_reviewed"], False)
        self.assertIs(result["publisher_connected"], False)
        self.assertEqual(result["public_writes"], 0)
        self.assertIs(result["source_licence_assumed"], False)
        self.assertIs(result["copyrighted_description_reused"], False)
        self.assertIs(result["third_party_image_reused"], False)

    def test_fact_only_proposal_uses_original_neutral_template(self):
        out = html_draft()
        self.assertEqual(out["status"], "private_draft_for_rights_review")
        self.assert_nonpublish(out)
        d = out["draft"]
        self.assertEqual(d["schema"], "ptitesondes.private_original_facts_draft.v1")
        self.assertEqual(d["title"], "Atelier créatif — Montpellier")
        self.assertEqual(d["source_title_identity_only"], LEAD["title"])
        self.assertEqual(d["date_start"], LEAD["date_start"])
        self.assertEqual(d["start_local"], LEAD["start_local"])
        self.assertEqual(d["source_url"], URL)
        self.assertIn("21/11/2026 à 09:15", d["original_factual_summary"])
        self.assertIn("Âge non précisé", d["original_factual_summary"])
        self.assertNotIn("Un tigre bleu", d["original_factual_summary"])
        self.assertNotIn("Récit protégé", d["original_factual_summary"])
        self.assertNotIn(LEAD["title"], d["original_factual_summary"])
        self.assertIsNone(d["source_description"])
        self.assertIsNone(d["image_url"])
        self.assertIs(d["safe_to_publish"], False)

    def test_explicit_age_range_is_precisely_reported(self):
        out = html_draft("<p>Pour les enfants de 3 à 6 ans</p>")
        self.assertEqual(out["status"], "private_draft_for_rights_review")
        self.assertEqual((out["draft"]["age_min"], out["draft"]["age_max"]), (3, 6))
        self.assertIn("de 3 à 6 ans", out["draft"]["original_factual_summary"])
        self.assert_nonpublish(out)

    def test_mixed_family_access_allowed_with_no_invented_age(self):
        out = html_draft("<p>Atelier parents enfants</p>")
        self.assertEqual(out["status"], "private_draft_for_rights_review")
        self.assertEqual(out["draft"]["audience_source_claim"], "explicit_mixed")
        self.assertIsNone(out["draft"]["age_min"])
        self.assertIsNone(out["draft"]["age_max"])

    def test_membership_cost_is_not_turned_into_event_fee(self):
        page = PAGE.replace("{audience}", "<p>Familles</p>")
        page = page.replace("<p>Sur inscription | Gratuit</p>",
            "<p>Sur inscription | Gratuit</p><p>Carte MPT obligatoire - tarif carte 10 €</p>")
        lead = dict(LEAD, price_evidence="ambiguous")
        out = html_draft(lead=lead, html=page)
        self.assertEqual(out["status"], "private_draft_for_rights_review")
        self.assertEqual(out["draft"]["price_source_claim"], "free_with_mandatory_membership")
        self.assertIn("coût de la carte non vérifié", out["draft"]["original_factual_summary"])
        self.assert_nonpublish(out)

    def test_not_stated_is_neither_free_nor_no_registration(self):
        page = PAGE.replace("{audience}", "<p>Familles</p>").replace(
            "<p>Sur inscription | Gratuit</p>", "<p>Informations pratiques</p>")
        lead = dict(LEAD, price_evidence="not_stated", registration_evidence="not_stated")
        out = html_draft(lead=lead, html=page)
        self.assertEqual(out["status"], "private_draft_for_rights_review")
        self.assertEqual(out["draft"]["price_source_claim"], "unknown")
        self.assertEqual(out["draft"]["registration_source_claim"], "unknown")
        self.assertIn("Tarif non précisé", out["draft"]["original_factual_summary"])
        self.assertIn("Modalités d'inscription non précisées", out["draft"]["original_factual_summary"])

    def test_claiming_license_in_html_footer_does_not_grant_reuse(self):
        page = PAGE.replace("{audience}", "<p>Familles</p>").replace(
            "</main>", '<footer>Licence Ouverte 2.0, réutilisation autorisée</footer></main>')
        out = html_draft(html=page)
        self.assertEqual(out["status"], "private_draft_for_rights_review")
        self.assert_nonpublish(out)
        self.assertEqual(out["draft"]["source_rights_status"], "source_policy_review_pending")

    def test_adult_only_and_forged_family_cues_are_held(self):
        pages = (
            PAGE.replace("{audience}", "<p>Familles</p><p>Adultes uniquement</p>"),
            PAGE.replace("{audience}", "<p>Parents uniquement</p>"),
            PAGE.replace("{audience}", "<p>Un livre sur les enfants</p>"),
            PAGE.replace("{audience}", "<p hidden>Familles</p>"),
        )
        for html in pages:
            with self.subTest(html=html[-100:]):
                out = html_draft(html=html)
                self.assertIsNone(out["draft"])
                self.assert_nonpublish(out)

    def test_conflicting_price_and_registration_hold_without_draft(self):
        for replacement in (
            "<p>Gratuit | Tarif 8 euros | Sur inscription</p>",
            "<p>Gratuit | Sur inscription | Sans inscription</p>",
        ):
            with self.subTest(replacement=replacement):
                page = PAGE.replace("{audience}", "<p>Familles</p>").replace(
                    "<p>Sur inscription | Gratuit</p>", replacement)
                out = html_draft(html=page)
                self.assertEqual(out["reason"], "source_access_terms_conflicting")
                self.assertIsNone(out["draft"])

    def test_wrong_host_time_and_venue_cannot_create_a_draft(self):
        changes = (
            dict(LEAD, source_url="https://evil.example/evenement/evenement"),
            dict(LEAD, start_local="16:15"),
            dict(LEAD, venue="Maison fictive"),
            dict(LEAD, city="Nîmes"),
        )
        for lead in changes:
            with self.subTest(changed=lead):
                out = html_draft(lead=lead)
                self.assertEqual(out["reason"], "exact_official_session_not_corroborated")
                self.assertIsNone(out["draft"])
                self.assert_nonpublish(out)

    def test_unclassified_or_musical_event_cannot_use_this_route(self):
        for code in ("concert", "unknown-thing", None):
            out = html_draft(lead=dict(LEAD, category=code))
            self.assertEqual(out["reason"], "missing_or_invalid_factual_fields")
            self.assertIsNone(out["draft"])

    def test_private_draft_does_not_leak_to_public_aggregate_shape(self):
        out = html_draft()
        safe = dict(out, draft=None)
        dumped = json.dumps(safe)
        self.assertNotIn("Montpellier", dumped)
        self.assertNotIn("09:15", dumped)
        self.assertNotIn(URL, dumped)
        self.assertNotIn("Récit protégé", dumped)

    def test_html_markup_in_source_fields_is_rejected(self):
        lead = dict(LEAD, title="<script>alert(1)</script>")
        out = html_draft(lead=lead)
        self.assertIsNone(out["draft"])
        self.assert_nonpublish(out)

    def test_missing_exact_session_never_yields_draft(self):
        out = html_draft(html=PAGE.replace("09:15", "17:30").replace(
            "{audience}", "<p>Familles</p>"))
        self.assertEqual(out["status"], "held")
        self.assertIsNone(out["draft"])


class OALicenceTests(unittest.TestCase):
    def test_event_et alab_license_with_attribution_is_only_reviewable(self):
        out = triage_openagenda_licence_metadata(OA_EVENT, DIRECT)
        self.assertEqual(out["route"], "open_licence_claim_ready_for_independent_rights_review")
        self.assertTrue(out["recognized_open_licence_claim"])
        self.assertTrue(out["attribution_metadata_complete"])
        self.assertFalse(out["rights_reviewed"])
        self.assertFalse(out["publication_ready"])
        self.assertEqual(out["public_writes"], 0)
        serialized = json.dumps(out)
        self.assertNotIn("Institution fictive", serialized)

    def test_missing_updated_at_must_not_create_complete_attribution(self):
        event = deepcopy(OA_EVENT)
        event.pop("updatedAt")
        out = triage_openagenda_licence_metadata(event, DIRECT)
        self.assertEqual(out["route"], "open_licence_claim_attribution_incomplete")
        self.assertFalse(out["attribution_metadata_complete"])

    def test_invalid_updated_at_never_counts_as_verified(self):
        for invalid in ("2026-11-19", "2026-13-99T14:00:00+01:00",
                        "2026-11-19T14:00:00", "tomorrow", 12):
            with self.subTest(invalid=invalid):
                event = dict(OA_EVENT, updatedAt=invalid)
                out = triage_openagenda_licence_metadata(event, DIRECT)
                self.assertFalse(out["source_update_timestamp_claimed"])

    def test_licensor_and_publisher_are_not_interchangeable(self):
        event = deepcopy(OA_EVENT)
        event["rights"]["licensor"] = {}
        out = triage_openagenda_licence_metadata(event, DIRECT)
        self.assertFalse(out["licensor_name_claimed"])
        self.assertFalse(out["attribution_metadata_complete"])

    def test_wrong_or_spoofed_license_is_not_assumed_open(self):
        for mutation in (
            {"id": "CC-BY-4.0"},
            {"url": "https://evil.example/license"},
            {"name": "Tous droits réservés"},
        ):
            event = deepcopy(OA_EVENT)
            event["rights"]["license"].update(mutation)
            out = triage_openagenda_licence_metadata(event, DIRECT)
            self.assertEqual(out["route"], "other_or_unknown_licence_requires_review")
            self.assertFalse(out["recognized_open_licence_claim"])

    def test_agenda_level_license_claim_without_event_rights_is_held(self):
        event = deepcopy(OA_EVENT)
        event.pop("rights")
        out = triage_openagenda_licence_metadata(event, DIRECT)
        self.assertEqual(out["route"], "missing_event_rights")
        self.assertFalse(out["attribution_metadata_complete"])

    def test_forged_evidence_or_unreviewed_source_is_rejected(self):
        for proof in (
            {}, None, dict(DIRECT, source_evidence_structurally_valid=False),
            dict(DIRECT, approval_granted=True),
            dict(DIRECT, public_writes=1),
            dict(DIRECT, schema="fake"),
        ):
            with self.subTest(proof=proof):
                out = triage_openagenda_licence_metadata(OA_EVENT, proof)
                self.assertEqual(out["route"], "source_evidence_unverified")
                self.assertFalse(out["recognized_open_licence_claim"])

    def test_licence_claim_cannot_grant_media_rights(self):
        out = triage_openagenda_licence_metadata(OA_EVENT, DIRECT)
        self.assertTrue(out["images_and_third_party_content_not_cleared"])
        self.assertFalse(out["rights_reviewed"])
        self.assertFalse(out["approval_granted"])


if __name__ == "__main__":
    unittest.main()
