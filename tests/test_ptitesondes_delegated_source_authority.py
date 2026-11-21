"""Unknown organizer authority via a *different* DILA municipality website."""
from datetime import date, timedelta
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from test_ptitesondes_unnumbered_official_geo_proof import (
    directory, CITY, VENUE, URL as VENUE_URL,
)
from ptitesondes_delegated_source_authority import (
    DelegatedSourceHostProof, mint_delegated_venue_source_proof,
    verified_delegated_source,
)

DAY = date(2026, 11, 21)
SOURCE = "https://nouvel-organisateur.example/spectacles/conte-musical"
REF = "https://www.ville-les-bois.fr/culture/lieu"


def municipality(body=None):
    body = body or (
        "<h1>Les lieux culturels</h1><article>"
        "<h2>Place du village</h2>"
        "<p>Retrouvez le programme de cette salle sur "
        "https://nouvel-organisateur.example/spectacles</p>"
        "</article>")
    return "<html><main>" + body + "</main></html>"


def mint(source=SOURCE, **kw):
    args = dict(city=CITY, venue=VENUE, event_url=source,
                directory=directory(), municipal_reference_url=REF,
                municipal_reference_html=municipality(),
                checked_on=DAY)
    args.update(kw)
    return mint_delegated_venue_source_proof(**args)


class DelegatedFirstPartyTests(unittest.TestCase):
    def test_unknown_nonmunicipal_host_can_be_attested_and_reused(self):
        proof = mint()
        self.assertIsInstance(proof, DelegatedSourceHostProof)
        self.assertEqual(proof.host, "nouvel-organisateur.example")
        self.assertTrue(verified_delegated_source(
            proof, CITY, VENUE, SOURCE, DAY))
        self.assertTrue(verified_delegated_source(
            proof, CITY, VENUE,
            "https://nouvel-organisateur.example/autre-vraie-fiche", DAY))
        self.assertFalse(verified_delegated_source(
            proof, "Autre commune", VENUE, SOURCE, DAY))
        self.assertFalse(verified_delegated_source(
            proof, CITY, "Autre scène", SOURCE, DAY))
        self.assertFalse(verified_delegated_source(
            proof, CITY, VENUE, SOURCE, DAY+timedelta(days=31)))

    def test_never_accept_forged_boolean_or_constructor(self):
        self.assertFalse(verified_delegated_source(
            {"approved": True, "host": "nouvel-organisateur.example"},
            CITY, VENUE, SOURCE, DAY))
        with self.assertRaises(ValueError):
            DelegatedSourceHostProof(
                CITY, VENUE, "nouvel-organisateur.example", REF, DAY,
                object())
        proof = mint()
        with self.assertRaises(AttributeError):
            proof.host = "malicious.example"

    def test_untrusted_city_or_page_does_not_delegate(self):
        for patch in (
            {"directory": {"results": []}},
            {"municipal_reference_url": "https://evil.example/culture/lieu"},
            {"municipal_reference_url": "https://www.ville-les-bois.fr/"},
            {"municipal_reference_html":
                municipality("<p>Autre bâtiment et lien vers "
                             "nouvel-organisateur.example</p>")},
            {"municipal_reference_html": municipality(
                "<footer><p>Place du village "
                "nouvel-organisateur.example</p></footer>")},
            {"municipal_reference_html": municipality(
                "<script>Place du village "
                "nouvel-organisateur.example</script>")},
            {"event_url": "https://another-venue.example/spectacle"},
            {"municipal_reference_html": municipality(
                "<article><h2>Place du village</h2></article>"
                "<article><p>nouvel-organisateur.example</p></article>")},
        ):
            with self.subTest(patch=patch):
                self.assertIsNone(mint(**patch))

    def test_domain_prefix_or_child_host_never_spoofs_attestation(self):
        for site in (
            "https://nouvel-organisateur.example.evil.test/show",
            "https://sub.nouvel-organisateur.example/show",
            "https://nouvel-organisateur.example@evil.test/show",
            "http://nouvel-organisateur.example/show",
            "https://openagenda.com/agenda/show",
        ):
            with self.subTest(site=site):
                self.assertIsNone(mint(source=site))
        # Published municipality page printing a malicious suffix does not
        # attest the shorter host.
        spoof_page=municipality(
            "<article><h2>Place du village</h2>"
            "<p>https://nouvel-organisateur.example.evil.test/show</p>"
            "</article>")
        self.assertIsNone(
            mint(municipal_reference_html=spoof_page))

    def test_domain_attestation_is_not_a_session_or_gps_proof(self):
        proof = mint()
        self.assertFalse(hasattr(proof, "sessions"))
        self.assertFalse(hasattr(proof, "lat"))
        self.assertFalse(hasattr(proof, "publication_ready"))


if __name__ == "__main__":
    unittest.main()
