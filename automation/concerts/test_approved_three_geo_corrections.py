"""Strict private proofs for three historic venue location corrections."""
from __future__ import annotations
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXPECTED = {
    "le-bikini-toulouse": {
        "address": "Rue Théodore Monod, Parc Technologique du Canal",
        "postalCode": "31520", "city": "Ramonville-Saint-Agne",
        "latitude": 43.54795, "longitude": 1.48568,
        "official": "https://lebikini.com/section/infos-pratiques/infos-pratiques",
        "geo": "https://www.openstreetmap.org/node/380889428",
        "officialProof": "official-venue-address",
    },
    "rockstore-montpellier": {
        "address": "20 rue de Verdun",
        "postalCode": "34000",
        "latitude": 43.60624, "longitude": 3.88137,
        "official": "https://rockstore.fr/infos-pratiques/",
        "geo": "https://www.openstreetmap.org/node/579814541",
        "officialProof": "official-venue-address",
    },
    "the-black-lab-wasquehal": {
        "address": "8 rue des Champs, P.A. de la Pilaterie",
        "postalCode": "59290",
        "latitude": 50.652602, "longitude": 3.122069,
        "official": "https://theblacklab.fr/adresse/",
        "geo": "https://www.openstreetmap.org/node/9179662650",
        "officialProof": "official-venue-gps",
    },
}


class GeoApprovalsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        document = json.loads((ROOT / "approved.json").read_text(encoding="utf-8"))
        cls.items = document["referenceVenueCorrections"]

    def test_three_exact_private_evidence_records(self):
        self.assertEqual(len(self.items), 10)
        self.assertEqual(len({x["venueId"] for x in self.items}), 10)
        approved = {x["venueId"]: x for x in self.items}
        for venue_id, exp in EXPECTED.items():
            with self.subTest(venue_id=venue_id):
                row = approved[venue_id]
                self.assertEqual(row["reviewDecision"], "approved")
                self.assertEqual(row["reviewedBy"], "independent-official-verifier")
                self.assertEqual(row["reviewedAt"], "2026-11-03")
                for key in ("address", "postalCode", "latitude", "longitude"):
                    self.assertEqual(row["venuePatch"][key], exp[key])
                if "city" in exp:
                    self.assertEqual(row["venuePatch"]["city"], exp["city"])
                self.assertEqual(len(row["officialEvidence"]), 2)
                official, geo = row["officialEvidence"]
                self.assertEqual(official["url"], exp["official"])
                self.assertEqual(official["proofType"], exp["officialProof"])
                self.assertEqual(geo["url"], exp["geo"])
                self.assertEqual(geo["proofType"], "openstreetmap-venue-node")
                for proof in (official, geo):
                    self.assertEqual(proof["checkedAt"], "2026-11-03")
                self.assertTrue(
                    {"name", "address", "postalCode", "city"}.issubset(
                        official["checkedFields"]))
                self.assertTrue(
                    {"venueName", "coordinates"}.issubset(
                        geo["checkedFields"]))
                if venue_id == "the-black-lab-wasquehal":
                    self.assertTrue(
                        {"latitude", "longitude"}.issubset(
                            official["checkedFields"]))
                    self.assertIn("entrée publique", row["venuePatch"]["geoPrecision"])

    def test_previous_secret_place_and_rex_signed_records_preserved(self):
        records = {x["venueId"]: x for x in self.items}
        self.assertEqual(
            records["secret-place-saint-jean-de-vedas"]["venuePatch"]["latitude"],
            43.5617771)
        self.assertEqual(
            records["le-rex-toulouse"]["venuePatch"]["latitude"],
            43.611901)
        self.assertEqual(
            records["le-rex-toulouse"]["venuePatch"]["longitude"],
            1.438364)


if __name__ == "__main__":
    unittest.main()
