"""No-network adversarial tests for dynamic municipality-operated side sites."""
from datetime import date, timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from test_ptitesondes_unnumbered_official_geo_proof import directory, CITY
from test_ptitesondes_open_world_patch_bridge import (
    dossier, private_patch, readers,
)
from test_ptitesondes_open_world_release_rehearsal import (
    KEY, TODAY, official_page,
)
from test_ptitesondes_candidate_promotion import base
from ptitesondes_secondary_municipal_site_proof import (
    mint_secondary_municipal_host_proof,
    verified_secondary_municipal_host, SecondaryMunicipalHostProof,
)
from ptitesondes_open_world_patch_bridge import merge_verified_open_world

SECONDARY = "https://agenda-culturel-inconnu.example/spectacles/conte-musical"
HOST = "agenda-culturel-inconnu.example"
REFERENCE = "https://www.ville-les-bois.fr/culture/agenda-public"
LEGAL = "https://agenda-culturel-inconnu.example/mentions-legales/"


def municipal_page(destination="https://agenda-culturel-inconnu.example/"):
    return (
        "<html><main><article><h1>Ville de Ville-les-Bois</h1>"
        "<p>Le programme culturel municipal est disponible sur notre "
        "second site officiel.</p>"
        "<a href='" + destination + "'>Agenda officiel des sorties</a>"
        "</article></main></html>"
    )


def event_page():
    # Exact title and clock are still verified by the normal OA+HTML verifier.
    return (official_page() +
            "<footer><a href='/mentions-legales/'>Mentions légales</a></footer>")


def legal_page(city=CITY, host=HOST):
    return ("<html><main><h1>Mentions légales</h1>"
            "<p>Le site " + host + " est édité par la Ville de "
            + city + ".</p></main></html>")


def read_pages(url):
    if url == SECONDARY:
        return event_page()
    if url == LEGAL:
        return legal_page()
    raise AssertionError("unexpected remote source")


def mint(**changes):
    data = dict(
        city=CITY, event_url=SECONDARY, directory=directory(),
        municipal_reference_url=REFERENCE,
        municipal_reference_html=municipal_page(),
        checked_on=TODAY, reader=read_pages,
    )
    data.update(changes)
    return mint_secondary_municipal_host_proof(**data)


class SecondaryMunicipalSitesTests(unittest.TestCase):
    def test_unlisted_secondary_host_attested_without_any_host_registry(self):
        proof = mint()
        self.assertIsInstance(proof, SecondaryMunicipalHostProof)
        self.assertEqual(proof.host, HOST)
        self.assertTrue(verified_secondary_municipal_host(
            proof, CITY, SECONDARY, TODAY))
        self.assertTrue(verified_secondary_municipal_host(
            proof, CITY, "https://" + HOST + "/events/une-autre-date",
            TODAY + timedelta(days=30)))
        self.assertFalse(verified_secondary_municipal_host(
            proof, CITY, SECONDARY, TODAY + timedelta(days=31)))
        self.assertFalse(verified_secondary_municipal_host(
            proof, "Autreville", SECONDARY, TODAY))
        self.assertFalse(verified_secondary_municipal_host(
            proof, CITY, "https://sub." + HOST + "/events/test", TODAY))
        self.assertFalse(verified_secondary_municipal_host(
            {"official": True, "host": HOST}, CITY, SECONDARY, TODAY))
        with self.assertRaises(ValueError):
            SecondaryMunicipalHostProof(CITY, HOST, REFERENCE, TODAY, object())
        with self.assertRaises(AttributeError):
            proof.city = "Fausse ville"

    def test_no_municipal_reference_or_wrong_domain_mints_nothing(self):
        no_fetch = Mock(side_effect=AssertionError("no fetch without DILA"))
        for changes in (
            {"directory": {"results": []}},
            {"municipal_reference_url":
                "https://arbitrary-website.example/agenda"},
            {"municipal_reference_url":
                "https://www.ville-les-bois.fr/"},
            {"municipal_reference_html": municipal_page(
                "https://agenda-culturel-inconnu.example.evil.test/")},
            {"municipal_reference_html": (
                "<html><main><h1>Ville de Ville-les-Bois</h1>"
                "<script><a href='https://" + HOST + "/'>Agenda</a></script>"
                "</main></html>")},
            {"municipal_reference_html": (
                "<html><footer><h1>Ville de Ville-les-Bois</h1>"
                "<a href='https://" + HOST + "/'>Agenda</a></footer></html>")},
            {"municipal_reference_html": (
                "<html><main><h1>Autre Ville</h1>"
                "<a href='https://" + HOST + "/'>Agenda</a></main></html>")},
            {"event_url": "https://" + HOST + ".evil.test/spectacle"},
        ):
            with self.subTest(changes=changes):
                self.assertIsNone(mint(**changes, reader=no_fetch))
        no_fetch.assert_not_called()

    def test_self_claim_is_never_enough_without_independent_city_link(self):
        self.assertIsNone(mint(municipal_reference_html=(
            "<html><main><h1>Ville de Ville-les-Bois</h1>"
            "<p>agenda-culturel-inconnu.example</p></main></html>")))

    def test_legal_claim_must_match_real_host_and_city(self):
        for bad in (
            legal_page(city="Autreville"),
            legal_page(host=HOST + ".evil.test"),
            "<html><main><p>Ville de Ville-les-Bois, tous droits réservés.</p></main></html>",
            "<html><main><p>Ce lieu est soutenu par la Ville de Ville-les-Bois.</p></main></html>",
            "<html><script>Le site " + HOST +
            " est édité par la Ville de Ville-les-Bois.</script></html>",
        ):
            with self.subTest(legal=bad):
                self.assertIsNone(mint(reader=lambda url: (
                    event_page() if url == SECONDARY else bad)))

    def test_missing_legal_notice_link_or_external_legal_notice_blocks(self):
        self.assertIsNone(mint(reader=lambda url: (
            official_page() if url == SECONDARY else legal_page())))
        self.assertIsNone(mint(reader=lambda url: (
            official_page() + "<footer><a href='https://other.example/mentions-legales/'>"
            "Mentions légales</a></footer>" if url == SECONDARY else legal_page())))

    def test_actual_publisher_merge_after_both_authority_checks(self):
        reference = base()
        checks = readers()
        old_reader = checks["official_reader"]
        checks["official_reader"] = lambda url: (
            municipal_page() if url == REFERENCE else
            read_pages(url) if url in (SECONDARY, LEGAL) else
            old_reader(url)
        )
        item = dossier(
            official_event_url=SECONDARY,
            municipal_source_reference_url=REFERENCE,
        )
        result, report, counts = merge_verified_open_world(
            reference, reference, private_patch(reference, [item]),
            TODAY, KEY, **checks)
        self.assertEqual(report["ajoutes"], 1)
        self.assertEqual(counts["admitted_to_merge"], 1)
        self.assertEqual(counts["held"], 0)
        self.assertEqual(result["events"][-1]["source_url"], SECONDARY)
        self.assertEqual(result["events"][:100], reference["events"])
        self.assertFalse(counts["publication_complete"])

    def test_publisher_refuses_missing_independent_secondary_authority(self):
        reference = base()
        checks = readers()
        old = checks["official_reader"]
        checks["official_reader"] = lambda url: (
            municipal_page("https://unrelated.example/") if url == REFERENCE else
            read_pages(url) if url in (SECONDARY, LEGAL) else old(url))
        result, report, counts = merge_verified_open_world(
            reference, reference, private_patch(reference, [dossier(
                official_event_url=SECONDARY,
                municipal_source_reference_url=REFERENCE,
            )]), TODAY, KEY, **checks)
        self.assertEqual(report["ajoutes"], 0)
        self.assertEqual(result, reference)
        self.assertEqual(counts["held"], 1)


if __name__ == "__main__":
    unittest.main()
