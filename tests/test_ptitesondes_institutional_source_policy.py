"""Adversarial source-registry tests; all pages and reviewed records synthetic."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_institutional_source_policy import (
    SCHEMA, MANIFEST_PATH, assess_source_policy, committed_source_policy,
    corroborate_independent_authority_link,
)

NOW = date(2026, 11, 20)
PIN = {
    "approved_host": "mpt.montpellier.fr",
    "exact_index_url": "https://mpt.montpellier.fr/evenements",
}
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
ENTRY = MANIFEST["entries"][0]
DEFAULT = object()
AUTHORITY = {
    "url": ENTRY["external_authority_url"],
    "html": (
        "<html><body><main><h1>Sites de la Ville de Montpellier</h1>"
        '<a href="https://mpt.montpellier.fr/maisons/albert-camus">'
        "Maison pour tous Albert Camus</a></main></body></html>"
    ),
}


def review(manifest=DEFAULT, pin=None, prefix="/evenement/", today=NOW):
    return assess_source_policy(
        deepcopy(MANIFEST if manifest is DEFAULT else manifest),
        deepcopy(PIN if pin is None else pin), prefix, today,
    )


def reviewed_manifest():
    value = deepcopy(MANIFEST)
    item = value["entries"][0]
    item["reuse_policy_state"] = "fact_only_source_review_recorded"
    item["facts_only_review_evidence_url"] = (
        "https://www.montpellier.fr/territoire/les-equipements/"
        "loisirs-equipements-et-lieux")
    item["reuse_reviewed_on"] = "2026-11-19"
    item["reuse_expires_on"] = "2027-02-19"
    return value


class InstitutionalPolicyTest(unittest.TestCase):
    def check_safe(self, record):
        self.assertEqual(record["schema"], SCHEMA)
        self.assertIs(record["publisher_rights_assumed"], False)
        self.assertIs(record["database_extraction_allowed_assumed"], False)
        self.assertIs(record["media_reuse_allowed"], False)
        self.assertIs(record["event_rights_reviewed"], False)
        self.assertIs(record["event_organizer_attested"], False)
        self.assertIs(record["event_geometry_verified"], False)
        self.assertIs(record["event_access_fully_verified"], False)
        self.assertIs(record["publication_ready"], False)
        self.assertIs(record["approval_granted"], False)
        self.assertIs(record["publisher_connected"], False)
        self.assertEqual(record["public_writes"], 0)
        self.assertIs(record["source_or_event_identifiers_present"], False)
        for private in ("Montpellier", "mpt.montpellier.fr", "/evenements",
                        "/maisons/", "source_id"):
            self.assertNotIn(private, json.dumps(record))

    def test_current_committed_registry_is_pending_legal_review(self):
        result = committed_source_policy(PIN, "/evenement/", NOW)
        self.assertEqual(result["status"], "source_reuse_policy_pending")
        self.assertTrue(result["owner_host_reference_documented"])
        self.assertFalse(result["ownership_rechecked_live"])
        self.check_safe(result)

    def test_one_source_policy_is_shared_across_all_events(self):
        first = review()
        second = review()
        self.assertEqual(first, second)
        self.assertEqual(len(MANIFEST["entries"]), 1)
        self.assertNotIn("event", ENTRY)
        self.check_safe(first)

    def test_unlisted_and_lookalike_hosts_stay_unregistered(self):
        for pin in (
            dict(PIN, approved_host="mpt.montpellier.fr.evil.example",
                 exact_index_url="https://mpt.montpellier.fr.evil.example/evenements"),
            dict(PIN, approved_host="www.montpellier.fr",
                 exact_index_url="https://www.montpellier.fr/evenements"),
            dict(PIN, exact_index_url="https://mpt.montpellier.fr/autre-agenda"),
        ):
            with self.subTest(pin=pin):
                result = review(pin=pin)
                self.assertEqual(result["status"], "source_not_registered")
                self.check_safe(result)

    def test_not_allowed_url_components_and_wrong_child_prefix(self):
        for pin, prefix in (
            (dict(PIN, exact_index_url="http://mpt.montpellier.fr/evenements"),
             "/evenement/"),
            (dict(PIN, exact_index_url="https://mpt.montpellier.fr/evenements?x=1"),
             "/evenement/"),
            (dict(PIN, exact_index_url="https://mpt.montpellier.fr/evenements#x"),
             "/evenement/"),
            (dict(PIN, exact_index_url="https://user@mpt.montpellier.fr/evenements"),
             "/evenement/"),
            (PIN, "//evenement/"),
            (PIN, "/other/"),
        ):
            with self.subTest(pin=pin, prefix=prefix):
                result = review(pin=pin, prefix=prefix)
                self.assertIn(result["status"], (
                    "source_not_registered", "source_registry_invalid"))
                self.check_safe(result)

    def test_no_review_boolean_or_fake_licence_can_overwrite_policy(self):
        for patch in (
            {"verified": True},
            {"rights_reviewed": True},
            {"reuse_policy_state": "fact_only_source_review_recorded"},
            {"license": "open"},
        ):
            with self.subTest(patch=patch):
                manifest = deepcopy(MANIFEST)
                manifest["entries"][0].update(patch)
                result = review(manifest=manifest)
                self.assertEqual(result["status"], "source_registry_invalid")
                self.check_safe(result)

    def test_synthetic_source_level_fact_only_review_remains_non_publishable(self):
        result = review(manifest=reviewed_manifest())
        self.assertEqual(result["status"],
            "source_fact_only_review_recorded_requires_independent_checks")
        self.assertTrue(result["source_level_fact_only_review_recorded"])
        self.check_safe(result)

    def test_future_expired_and_invalid_review_dates_fail_closed(self):
        for today in (date(2026, 11, 18), date(2027, 2, 20)):
            with self.subTest(today=today):
                result = review(manifest=reviewed_manifest(), today=today)
                self.assertEqual(result["status"], "source_reuse_review_stale_or_incomplete")
                self.check_safe(result)
        for expiry in ("2028-11-19", "2026-11-18", "bad"):
            manifest = reviewed_manifest()
            manifest["entries"][0]["reuse_expires_on"] = expiry
            self.assertEqual(review(manifest=manifest)["status"],
                             "source_registry_invalid")

    def test_restricted_source_is_not_silently_promoted(self):
        manifest = deepcopy(MANIFEST)
        manifest["entries"][0]["reuse_policy_state"] = "restricted_do_not_reuse"
        result = review(manifest=manifest)
        self.assertEqual(result["status"], "source_reuse_restricted")
        self.check_safe(result)

    def test_missing_source_cannot_be_self_registered_by_candidate(self):
        # Registered source may only be changed by a review of the fixed file.
        manifest = deepcopy(MANIFEST)
        manifest["entries"] = []
        out = review(manifest=manifest)
        self.assertEqual(out["status"], "source_not_registered")
        self.check_safe(out)

    def test_duplicated_ids_domains_and_indexes_refuse_all(self):
        for patch in (
            dict(MANIFEST["entries"][0]),
            dict(MANIFEST["entries"][0], source_id="another-id"),
            dict(MANIFEST["entries"][0], index_url=
                "https://mpt.montpellier.fr/another-index",
                source_id="another-id"),
        ):
            manifest = deepcopy(MANIFEST)
            manifest["entries"].append(patch)
            result = review(manifest=manifest)
            self.assertEqual(result["status"], "source_registry_invalid")
            self.check_safe(result)

    def test_invalid_manifest_fails_closed(self):
        for manifest in (
            None, {}, [], {"schema": "unknown", "entries": []},
            {"schema": MANIFEST["schema"], "entries": {}},
            dict(MANIFEST, injected="arbitrary"),
        ):
            with self.subTest(manifest=manifest):
                out = review(manifest=manifest)
                self.assertEqual(out["status"], "source_registry_invalid")
                self.check_safe(out)

    def test_invalid_entry_host_or_authority_not_accepted(self):
        for patch in (
            {"approved_host": "evil.example"},
            {"index_url": "https://evil.example/evenements"},
            {"publisher_notice_url": "https://evil.example/mentions"},
            {"external_authority_url": "https://mpt.montpellier.fr/mentions"},
            {"no_third_party_description_or_images": False},
            {"access_terms_require_per_session_review": False},
        ):
            with self.subTest(patch=patch):
                doc = deepcopy(MANIFEST)
                doc["entries"][0].update(patch)
                self.assertEqual(review(manifest=doc)["status"],
                                 "source_registry_invalid")

    def test_live_independent_authority_link_is_corroboration_only(self):
        self.assertTrue(corroborate_independent_authority_link(
            ENTRY, AUTHORITY, primary_source_host=PIN["approved_host"]))
        self.assertFalse(review()["ownership_rechecked_live"])
        self.check_safe(review())

    def test_hidden_spoof_or_unrelated_authority_links_never_count(self):
        cases = (
            '<nav><a href="https://mpt.montpellier.fr/maisons/a">Menu</a></nav>',
            '<main><a href="https://mpt.montpellier.fr.evil.example/maisons/a">Fake</a></main>',
            '<main><a href="https://evil.example/maisons/a">Other</a></main>',
            '<main><a href="https://mpt.montpellier.fr/evenement/a">Wrong path</a></main>',
            '<main><a href="http://mpt.montpellier.fr/maisons/a">HTTP</a></main>',
            '<main><div hidden><a href="https://mpt.montpellier.fr/maisons/a">Hidden</a></div></main>',
            '<main><div aria-hidden="true"><a href="https://mpt.montpellier.fr/maisons/a">Hidden</a></div></main>',
            '<main><div style="display:none"><a href="https://mpt.montpellier.fr/maisons/a">Hidden</a></div></main>',
        )
        for body in cases:
            with self.subTest(body=body):
                html = "<html><body>" + body + (" " * 200) + "</body></html>"
                page = dict(AUTHORITY, html=html)
                self.assertFalse(corroborate_independent_authority_link(ENTRY, page))

    def test_wrong_identity_redirect_or_oversized_authority_page_refused(self):
        for page in (
            dict(AUTHORITY, url="https://evil.example/authority"),
            dict(AUTHORITY, html=""),
            dict(AUTHORITY, html=AUTHORITY["html"] * 5000),
        ):
            with self.subTest(page=page["url"]):
                self.assertFalse(corroborate_independent_authority_link(
                    ENTRY, page))

    def test_authority_reference_does_not_grant_rights_or_media(self):
        self.assertTrue(corroborate_independent_authority_link(ENTRY, AUTHORITY))
        result = committed_source_policy(PIN, "/evenement/", NOW)
        self.check_safe(result)


if __name__ == "__main__":
    unittest.main()
