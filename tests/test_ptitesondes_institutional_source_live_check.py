"""Read-only source authority smoke: network mocked; outputs only counts."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_institutional_source_policy import MANIFEST_PATH
from ptitesondes_institutional_source_live_check import (
    run_source_authority_check,
)

ENTRY = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["entries"][0]
AUTHORITY_HTML = (
    "<html><body><main><h1>Équipements municipaux</h1>"
    '<a href="https://mpt.montpellier.fr/maisons/albert-camus">'
    "Maison pour tous</a></main></body></html>"
)
NOTICE_HTML = (
    "<html><body><main><h1>Mentions légales</h1><p>"
    "Ville et Métropole de Montpellier - Identité de l'éditeur</p>"
    "</main></body></html>"
)


def reader(pin):
    if pin["exact_url"] == ENTRY["external_authority_url"]:
        return {"url": pin["exact_url"], "html": AUTHORITY_HTML}
    if pin["exact_url"] == ENTRY["publisher_notice_url"]:
        return {"url": pin["exact_url"], "html": NOTICE_HTML}
    raise ValueError("unexpected_source")


class InstitutionalSourceLiveCheckTests(unittest.TestCase):
    def assert_nonpublishable(self, out):
        self.assertFalse(out["publisher_licence_attested"])
        self.assertFalse(out["licence_or_reuse_rights_inferred_from_site"])
        self.assertFalse(out["organizer_event_attested"])
        self.assertFalse(out["publisher_connected"])
        self.assertFalse(out["publication_ready"])
        self.assertFalse(out["approval_granted"])
        self.assertFalse(out["contains_source_names_or_urls"])
        self.assertEqual(out["public_writes"], 0)
        s = json.dumps(out)
        for value in ("Montpellier", "mpt.montpellier.fr", "Albert Camus"):
            self.assertNotIn(value, s)

    def test_independent_city_link_and_legal_notice_do_not_grant_rights(self):
        seen = []
        def observed(pin):
            seen.append(pin["exact_url"])
            return reader(pin)
        out = run_source_authority_check(observed)
        self.assertEqual(out["stage"], "bounded_source_reference_check_completed")
        self.assertEqual(out["counts"]["registered"], 1)
        self.assertEqual(out["counts"]["institutional_host_link_confirmed"], 1)
        self.assertEqual(out["counts"]["publisher_notice_page_reachable"], 1)
        self.assertEqual(out["counts"]["source_policy_reuse_pending"], 1)
        self.assertEqual(set(seen), {
            ENTRY["external_authority_url"],
            ENTRY["publisher_notice_url"],
        })
        self.assert_nonpublishable(out)

    def test_network_failure_holds_without_raw_errors(self):
        def failed(_):
            raise OSError("private / forbidden client metadata")
        out = run_source_authority_check(failed)
        self.assertEqual(out["counts"]["authority_link_unconfirmed"], 1)
        self.assertEqual(out["counts"]["publisher_notice_page_unconfirmed"], 1)
        self.assert_nonpublishable(out)

    def test_lookalike_city_link_is_not_institutional_proof(self):
        def fake(pin):
            page = reader(pin)
            if pin["exact_url"] == ENTRY["external_authority_url"]:
                page["html"] = AUTHORITY_HTML.replace(
                    "mpt.montpellier.fr", "mpt.montpellier.fr.evil.example")
            return page
        out = run_source_authority_check(fake)
        self.assertEqual(out["counts"]["institutional_host_link_confirmed"], 0)
        self.assertEqual(out["counts"]["authority_link_unconfirmed"], 1)
        self.assert_nonpublishable(out)

    def test_mismatching_source_url_or_redirect_is_not_accepted(self):
        def redirect(pin):
            page = reader(pin)
            return dict(page, url=pin["exact_url"] + "/redirect")
        out = run_source_authority_check(redirect)
        self.assertEqual(out["counts"]["authority_link_unconfirmed"], 1)
        self.assertEqual(out["counts"]["publisher_notice_page_unconfirmed"], 1)
        self.assert_nonpublishable(out)

    def test_collector_input_not_accepted_as_trusted_authority(self):
        # The public entrypoint only accepts an injected reader for tests.
        # There is no event argument or candidate-supplied registry path.
        out = run_source_authority_check(reader)
        self.assertEqual(sum(1 for k in out if k.startswith("source_url")), 0)
        self.assert_nonpublishable(out)


if __name__ == "__main__":
    unittest.main()
