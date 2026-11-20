"""No-network adversarial tests for reusable Sorties/Lieux place evidence."""
import json
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ptitesondes_shared_venue_location_evidence import (
    VenueLocationProof, mint_private_location_proof, location_from_proof,
)
from ptitesondes_candidate_promotion import registry_location
from venue_registry import verified_location

DAY = date(2026, 11, 20)
GROUP = {"city": "Ville-des-Bois", "venue": "Maison des enfants"}
URL = "https://www.ville-des-bois.fr/lieux/maison-des-enfants"
POINT = (44.5, 2.25)


def directory(site="https://www.ville-des-bois.fr/"):
    return {"total_count": 1, "results": [{
        "nom": "Mairie - Ville-des-Bois", "categorie": "SL",
        "statut_de_diffusion": "true", "version_type": "Publiable",
        "copyright":
            "Direction de l'information légale et administrative (Premier ministre)",
        "url_service_public":
            "https://lannuaire.service-public.gouv.fr/occitanie/aveyron/uuid",
        "code_insee_commune": "12345",
        "pivot": '[{"type_service_local":"mairie","code_insee_commune":["12345"]}]',
        "adresse": '[{"nom_commune":"Ville-des-Bois","pays":"France"}]',
        "site_internet": json.dumps([{"libelle":"","valeur":site}]),
    }]}


def html(name="Maison des enfants", num="12"):
    node = {"@type":"Place", "name":name,
            "address":{"@type":"PostalAddress",
                       "streetAddress":num+" Rue des Chênes",
                       "postalCode":"12345",
                       "addressLocality":"Ville-des-Bois"}}
    return ("<html><script type='application/ld+json'>"
            +json.dumps(node, ensure_ascii=False)+"</script><h1>"
            +name+"</h1></html>")


def ban(lat=44.5, lng=2.25, number="12", score=0.99):
    return {"type":"FeatureCollection", "features":[{
        "type":"Feature",
        "properties":{"type":"housenumber", "score":score,
                      "city":"Ville-des-Bois", "postcode":"12345",
                      "housenumber":number,
                      "label":number+" Rue des Chênes 12345 Ville-des-Bois"},
        "geometry":{"type":"Point", "coordinates":[lng,lat]}
    }]}


def mint(**kwargs):
    base = dict(group=GROUP, directory=directory(), page_url=URL, html=html(),
                ign_fetch=lambda _:ban(), checked_on=DAY)
    base.update(kwargs)
    return mint_private_location_proof(**base)


class SharedVenueLocationTests(unittest.TestCase):
    def test_exact_venue_is_reusable_for_several_sessions_and_permanent_place(self):
        proof = mint()
        self.assertIsInstance(proof, VenueLocationProof)
        place = location_from_proof(proof, "Ville-des-Bois", "Maison des enfants",
                                    DAY, POINT)
        self.assertEqual((place["lat"],place["lng"]), POINT)
        with self.assertRaises(AttributeError):
            proof.lat = 1.0
        with self.assertRaises(AttributeError):
            del proof.city
        self.assertIsNotNone(location_from_proof(proof, GROUP["city"],
                                                 GROUP["venue"], DAY+timedelta(days=15)))
        self.assertEqual((registry_location(GROUP, proof, DAY)["lat"],
                          registry_location(GROUP, proof, DAY)["lng"]), POINT)
        ok, _ = verified_location({**GROUP, "lat":POINT[0], "lng":POINT[1]},
                                  proof, DAY)
        self.assertTrue(ok)
        # No global registry mutation or runtime injection by default.
        self.assertIsNone(registry_location(GROUP))
        self.assertFalse(verified_location(
            {**GROUP, "lat":POINT[0], "lng":POINT[1]})[0])

    def test_forbid_forged_dict_and_direct_proof_constructor(self):
        self.assertIsNone(location_from_proof({
            "city":GROUP["city"],"venue":GROUP["venue"],"lat":POINT[0],
            "lng":POINT[1], "verified":True}, *GROUP.values(), DAY))
        with self.assertRaises(ValueError):
            VenueLocationProof(GROUP["city"], GROUP["venue"], *POINT, DAY,
                               URL, object())

    def test_freshness_and_event_location_bound(self):
        proof = mint()
        for when in (DAY-timedelta(days=1), DAY+timedelta(days=31)):
            self.assertIsNone(location_from_proof(proof, GROUP["city"],
                                                  GROUP["venue"], when))
        for center in ((44.6,2.25), (float("nan"),2.25), (44.5,3.25)):
            self.assertIsNone(location_from_proof(proof, GROUP["city"],
                                                  GROUP["venue"], DAY, center))
        self.assertIsNone(location_from_proof(proof, GROUP["city"],
                                              "Maison des autres", DAY))
        self.assertIsNone(location_from_proof(proof, "Autre commune",
                                              GROUP["venue"], DAY))
        self.assertFalse(verified_location({**GROUP, "lat":44.6,"lng":2.25},
                                           proof, DAY)[0])

    def test_declared_only_or_untrusted_geocode_must_fail(self):
        self.assertIsNone(mint(directory=directory("https://wrong-city.fr/")))
        self.assertIsNone(mint(page_url="https://untrusted.example/lieu"))
        self.assertIsNone(mint(html=html(name="Autre maison")))
        self.assertIsNone(mint(html=html(num="13")))
        self.assertIsNone(mint(ign_fetch=lambda _:ban(score=0.91)))
        self.assertIsNone(mint(ign_fetch=lambda _:ban(number="13")))
        self.assertIsNone(mint(ign_fetch=lambda _:ban(lat=44.7),
                               source_center=POINT))
        self.assertIsNone(mint(source_center=(44.7,2.25)))
        self.assertIsNotNone(mint(source_center=POINT))

    def test_ambiguous_ban_or_api_errors_must_fail_closed(self):
        b = ban()
        self.assertIsNone(mint(ign_fetch=lambda _: {
            "type":"FeatureCollection","features":b["features"]*2}))
        self.assertIsNone(mint(ign_fetch=lambda _: {
            "type":"FeatureCollection","features":[]}))
        self.assertIsNone(mint(ign_fetch=lambda _: {"type":"unexpected"}))
        self.assertIsNone(mint(ign_fetch=lambda _: (_ for _ in ()).throw(
            TimeoutError("offline"))))
        self.assertIsNone(mint(source_center=(float("nan"),0)))
        self.assertIsNone(mint(checked_on="2026-11-20"))


if __name__ == "__main__":
    unittest.main()
