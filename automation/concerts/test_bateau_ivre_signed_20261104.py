"""Private signature review for Le Bateau Ivre (Tours, 37).

Preserve all 183 historical event approvals and 20 historical venue approvals.
Only independently reviewed named first-party cards are signable.
"""
import json
import unittest
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
DOC = json.loads((ROOT / "approved.json").read_text(encoding="utf-8"))
VENUE_ID = "le-bateau-ivre-tours"
DAY = "2026-11-04"
NAMES = {
    "go-c-20261106-tours-les-sheriff-auxiliaire":
        ("2026-11-06", "Les Sheriff + Auxiliaire",
         ["les-sheriff", "auxiliaire"], ["les-sheriff", "auxiliaire"]),
    "go-c-20261107-tours-lofofora-akiavel-gravity":
        ("2026-11-07", "Lofofora + Akiavel + Gravity",
         ["lofofora", "akiavel", "gravity"], ["lofofora", "gravity"]),
    "go-c-20261113-tours-inspector-cluzo-grant-haua":
        ("2026-11-13", "The Inspector Cluzo + Grant Haua",
         ["the-inspector-cluzo", "grant-haua"], []),
    "go-c-20261126-tours-feldup-trainfantome":
        ("2026-11-26", "Feldup & The Showerheads + Trainfantome",
         ["feldup-the-showerheads", "trainfantome"],
         ["feldup-the-showerheads", "trainfantome"]),
    "go-c-20270128-tours-cachemire-la-phaze-bobs-not-dead":
        ("2027-01-28", "Cachemire + La Phaze + Bob's Not Dead",
         ["cachemire", "la-phaze", "bobs-not-dead"], []),
}
GEO_URL = "https://www.loisirs-divertissements.com/sortir-en-france/sortir-visiter-indre-et-loire-37/jam-7880"


class BateauIvrePrivateSignedTests(unittest.TestCase):
    def test_venue_has_both_distinct_exact_geographical_proofs(self):
        venues = DOC["venueApprovals"]
        ids = [row["venue"]["id"] for row in venues]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 21)
        self.assertIn("l-echonova-saint-ave", ids)
        self.assertIn("le-jardin-moderne-rennes", ids)
        entry = next(row for row in venues if row["venue"]["id"] == VENUE_ID)
        self.assertEqual(entry["reviewedAt"], DAY)
        self.assertEqual(entry["reviewDecision"], "approved")
        self.assertEqual(entry["reviewedBy"], "independent-official-verifier")
        v = entry["venue"]
        self.assertEqual((v["name"], v["city"], v["department"]),
                         ("Le Bateau Ivre", "Tours", "37"))
        self.assertEqual((v["address"], v["postalCode"]),
                         ("146 rue Édouard Vaillant", "37000"))
        self.assertEqual((v["latitude"], v["longitude"]),
                         (47.3844669, 0.7013784))
        self.assertIn("indicatif", v["geoPrecision"])
        self.assertIn("ne représente pas l'entrée exacte", v["geoPrecision"])
        self.assertEqual(v["geoSource"], GEO_URL)
        official, geo = entry["officialEvidence"]
        self.assertEqual(official["url"], "https://www.bateauivre.coop/contact/")
        self.assertEqual(official["proofType"], "official-venue-address")
        self.assertEqual(official["checkedFields"],
                         ["name", "address", "postalCode", "city"])
        self.assertEqual(geo["url"], GEO_URL)
        self.assertEqual(geo["proofType"], "independent-tourism-event-gps")
        self.assertEqual(geo["checkedFields"], ["venueName", "coordinates"])
        self.assertTrue(all(p["checkedAt"] == DAY for p in (official, geo)))

    def test_five_exact_event_proofs_and_no_fabricated_start(self):
        rows = DOC["approvals"]
        self.assertGreaterEqual(len(rows), 188)
        ids = [row["event"]["id"] for row in rows]
        self.assertEqual(len(ids), len(set(ids)))
        mapped = {row["event"]["id"]: row for row in rows}
        self.assertTrue(set(NAMES).issubset(mapped))
        for ident, (day, title, artists, new_ids) in NAMES.items():
            with self.subTest(ident=ident):
                row = mapped[ident]
                ev = row["event"]
                self.assertEqual(row["reviewDecision"], "approved")
                self.assertEqual(row["reviewedBy"], "independent-official-verifier")
                self.assertEqual(row["reviewedAt"], DAY)
                self.assertEqual((ev["date"], ev["title"], ev["venueId"]),
                                 (day, title, VENUE_ID))
                self.assertEqual(ev["artistIds"], artists)
                self.assertEqual(ev["status"], "confirmed")
                self.assertEqual(ev["sourceType"], "salle")
                self.assertIsNone(ev["time"])
                self.assertTrue(ev["genres"])
                source = urlsplit(ev["officialUrl"])
                self.assertEqual(source.netloc, "www.bateauivre.coop")
                self.assertIn("/%C3%A9v%C3%A8nements/", source.path)
                self.assertFalse(source.query or source.fragment)
                proofs = row["officialEvidence"]
                self.assertEqual(len(proofs), 2)
                self.assertEqual(proofs[0]["url"], ev["officialUrl"])
                self.assertEqual(proofs[0]["proofType"],
                                 "official-organizer-or-venue")
                self.assertEqual(proofs[0]["checkedFields"],
                                 ["artists", "date", "venue", "genre"])
                self.assertEqual(proofs[1]["proofType"],
                                 "first-party-venue-calendar")
                self.assertTrue(proofs[1]["url"] in
                    ("https://www.bateauivre.coop/agenda-2/",
                     "https://www.bateauivre.coop/2027/?post_type=events"))
                self.assertEqual(proofs[1]["checkedFields"],
                    ["leadArtist", "dayMonth", "yearIndex", "venue"]
                    if day.startswith("2027") else ["leadArtist", "date", "venue"])
                self.assertTrue(all(p["checkedAt"] == DAY for p in proofs))
                self.assertEqual([a["id"] for a in row["newArtists"]], new_ids)

    def test_retention_and_no_same_artist_same_place_same_day(self):
        ids = {row["event"]["id"] for row in DOC["approvals"]}
        self.assertTrue({
            "go-c-20261106-limoges-7weeks",
            "go-c-20261127-limoges-gwendoline",
            "go-c-20261203-saint-ave-eiffel",
            "go-c-20270206-saint-ave-meteora-systemize",
        }.issubset(ids))
        seen = set()
        for row in DOC["approvals"]:
            event = row["event"]
            for artist in event["artistIds"]:
                key = event["date"], event["venueId"], artist
                self.assertNotIn(key, seen)
                seen.add(key)


if __name__ == "__main__":
    unittest.main()
