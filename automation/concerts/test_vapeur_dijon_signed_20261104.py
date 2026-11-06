"""Private signed venue and exact January 2027 metal bill at La Vapeur Dijon."""
import json
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent
DOC=json.loads((ROOT/"approved.json").read_text(encoding="utf-8"))
ID="go-c-20270123-dijon-misanthrope-obsession-slapdown"
VENUE="la-vapeur-dijon"
DAY="2026-11-04"


class VapeurSignedPrivateTests(unittest.TestCase):
    def test_preserves_tours_and_other_historic_approvals(self):
        ids=[row["event"]["id"] for row in DOC["approvals"]]
        venues=[row["venue"]["id"] for row in DOC["venueApprovals"]]
        self.assertGreaterEqual(len(ids),189)
        self.assertGreaterEqual(len(venues),22)
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(len(venues),len(set(venues)))
        self.assertTrue({
            "go-c-20261106-tours-les-sheriff-auxiliaire",
            "go-c-20270128-tours-cachemire-la-phaze-bobs-not-dead",
            "go-c-20261203-saint-ave-eiffel",
        }.issubset(set(ids)))
        self.assertTrue({"le-bateau-ivre-tours","l-echonova-saint-ave",
                         "le-jardin-moderne-rennes"}.issubset(set(venues)))

    def test_venue_official_address_and_osm_node(self):
        row=next(x for x in DOC["venueApprovals"] if x["venue"]["id"]==VENUE)
        v=row["venue"]
        self.assertEqual((row["reviewDecision"],row["reviewedBy"],row["reviewedAt"]),
                         ("approved","independent-official-verifier",DAY))
        self.assertEqual((v["name"],v["city"],v["department"]),
                         ("La Vapeur","Dijon","21"))
        self.assertEqual((v["latitude"],v["longitude"]),(47.34569,5.05964))
        self.assertIn("indicative",v["geoPrecision"])
        self.assertEqual(v["geoSource"],"https://mapcarta.com/fr/N3474725036")
        official,geo=row["officialEvidence"]
        self.assertEqual(official["url"],"https://www.lavapeur.com/infos-pratiques/acces")
        self.assertEqual(official["proofType"],"official-venue-address")
        self.assertEqual(geo["proofType"],"openstreetmap-venue-node")
        self.assertEqual(geo["checkedFields"],["venueName","coordinates"])

    def test_exact_organizer_bill_with_official_program_and_no_fake_start(self):
        row=next(x for x in DOC["approvals"] if x["event"]["id"]==ID)
        e=row["event"]
        self.assertEqual((row["reviewDecision"],row["reviewedBy"],row["reviewedAt"]),
                         ("approved","independent-official-verifier",DAY))
        self.assertEqual((e["date"],e["title"],e["venueId"]),
                         ("2027-01-23","Misanthrope + Obsession + Slapdown",VENUE))
        self.assertEqual(e["artistIds"],["misanthrope","obsession","slapdown"])
        self.assertEqual([x["id"] for x in row["newArtists"]],
                         ["obsession","slapdown"])
        self.assertEqual((e["genres"],e["status"],e["sourceType"]),
                         (["Metal"],"confirmed","organisateur"))
        self.assertIsNone(e["time"])
        ticket,calendar=row["officialEvidence"]
        self.assertEqual(ticket["url"],e["officialUrl"])
        self.assertEqual(ticket["officialOrganizer"],"Association Phoenix Rising")
        self.assertEqual(ticket["checkedFields"],["artists","date","venue","genre"])
        self.assertEqual(calendar["proofType"],"first-party-venue-calendar")
        self.assertEqual(calendar["url"],"https://www.lavapeur.com/programme/")
        self.assertEqual(calendar["linkedBookingUrl"],ticket["url"])
        self.assertEqual(calendar["checkedFields"],["artists","dayMonth","venue","genre"])
        self.assertTrue(all(p["checkedAt"]==DAY for p in row["officialEvidence"]))

    def test_no_duplicate_artist_at_same_venue_and_date(self):
        seen=set()
        for row in DOC["approvals"]:
            e=row["event"]
            for a in e["artistIds"]:
                key=(e["date"],e["venueId"],a)
                self.assertNotIn(key,seen)
                seen.add(key)


if __name__=="__main__":
    unittest.main()
