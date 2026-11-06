"""Private audit: one Dijon show signed with exact Live Nation and La Vapeur proofs."""
import json
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent
DOC=json.loads((ROOT/"approved.json").read_text(encoding="utf-8"))
ID="go-c-20270211-dijon-skip-the-use"
VENUE_ID="la-vapeur-dijon"

class DijonSignedPrivateTests(unittest.TestCase):
    def test_source_exact_and_no_inferred_guest_or_start(self):
        rows=DOC["approvals"]
        names=[r["event"]["id"] for r in rows]
        self.assertEqual(len(names),len(set(names)))
        self.assertGreaterEqual(len(rows),190)
        self.assertIn(ID,names)
        row=next(x for x in rows if x["event"]["id"]==ID)
        evt=row["event"]
        self.assertEqual((row["reviewDecision"],row["reviewedBy"],row["reviewedAt"]),
                         ("approved","independent-official-verifier","2026-11-04"))
        self.assertEqual((evt["date"],evt["title"],evt["venueId"]),
                         ("2027-02-11","Skip The Use",VENUE_ID))
        self.assertEqual(evt["artistIds"],["skip-the-use"])
        self.assertEqual(evt["genres"],["Rock"])
        self.assertIsNone(evt["time"])
        self.assertEqual(evt["sourceType"],"organisateur")
        self.assertEqual(evt["status"],"confirmed")
        self.assertEqual(row["newArtists"],[])
        self.assertEqual(evt["officialUrl"],
            "https://www.livenation.fr/event/skip-the-use-love-and-anxiety-dijon-tickets-edp1674591")
        proofs=row["officialEvidence"]
        self.assertEqual(len(proofs),2)
        self.assertEqual((proofs[0]["url"],proofs[0]["proofType"]),
                         (evt["officialUrl"],"official-organizer-or-venue"))
        self.assertEqual(proofs[0]["checkedFields"],["artists","date","venue"])
        self.assertEqual((proofs[1]["url"],proofs[1]["proofType"]),
                         ("https://www.lavapeur.com/programme/","first-party-venue-calendar"))
        self.assertEqual(proofs[1]["checkedFields"],
                         ["artists","venue","genre","dayMonth"])
        self.assertNotIn("date",proofs[1]["checkedFields"])
        self.assertTrue(all(p["checkedAt"]=="2026-11-04" for p in proofs))

    def test_geo_source_not_fabricated_from_official_address(self):
        venues=DOC["venueApprovals"]
        ids=[r["venue"]["id"] for r in venues]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertGreaterEqual(len(ids),22)
        row=next(x for x in venues if x["venue"]["id"]==VENUE_ID)
        v=row["venue"]
        self.assertEqual((v["name"],v["city"],v["department"]),
                         ("La Vapeur","Dijon","21"))
        self.assertEqual((v["address"],v["postalCode"]),
                         ("42 avenue de Stalingrad","21000"))
        self.assertEqual((v["latitude"],v["longitude"]),(47.34569,5.05964))
        self.assertIn("indicative",v["geoPrecision"])
        self.assertEqual(v["geoSource"],"https://mapcarta.com/fr/N3474725036")
        a,b=row["officialEvidence"]
        self.assertEqual((a["url"],a["proofType"]),
            ("https://www.lavapeur.com/infos-pratiques/acces","official-venue-address"))
        self.assertEqual((b["url"],b["proofType"]),
            (v["geoSource"],"openstreetmap-venue-node"))
        self.assertTrue(all(p["checkedAt"]=="2026-11-04" for p in (a,b)))

    def test_conserve_les_approbations_historiques(self):
        existing={x["event"]["id"] for x in DOC["approvals"]}
        self.assertTrue({
           "go-c-20261106-tours-les-sheriff-auxiliaire",
           "go-c-20270128-tours-cachemire-la-phaze-bobs-not-dead",
           "go-c-20270123-dijon-misanthrope-obsession-slapdown",
           "go-c-20261203-saint-ave-eiffel",
           "go-c-20270206-saint-ave-meteora-systemize",
        }.issubset(existing))
        known={x["venue"]["id"] for x in DOC["venueApprovals"]}
        self.assertTrue({"le-bateau-ivre-tours","l-echonova-saint-ave",VENUE_ID}.issubset(known))
        seen=set()
        for r in DOC["approvals"]:
            e=r["event"]
            for aid in e["artistIds"]:
                key=e["date"],e["venueId"],aid
                self.assertNotIn(key,seen)
                seen.add(key)

if __name__=="__main__":
    unittest.main()
