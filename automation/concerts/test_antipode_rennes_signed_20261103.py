"""Private signed Antipode Rennes venue pin + three official concerts (review-only)."""
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parent
DOC=json.loads((ROOT/"approved.json").read_text(encoding="utf-8"))
GEO="antipode-rennes"
EXPECTED={
    "go-c-20261212-rennes-girls-in-hawaii-chaton-laveur": {
        "date":"2026-12-12","title":"Girls in Hawaii + Chaton Laveur",
        "artists":["girls-in-hawaii","chaton-laveur"],"new":["girls-in-hawaii","chaton-laveur"],
        "genre":["Rock"],"organizer":"Antipode","soldOut":True,
        "url":"https://antipode-rennes.fr/agenda/girls-hawaii-2026"},
    "go-c-20270127-rennes-altin-gun": {
        "date":"2027-01-27","title":"Altın Gün",
        "artists":["altin-gun"],"new":["altin-gun"],
        "genre":["Rock","Folk Rock"],"organizer":"Association Trans Musicales",
        "soldOut":False,"url":"https://antipode-rennes.fr/agenda/altin-gun-2027"},
    "go-c-20270309-rennes-the-pineapple-thief": {
        "date":"2027-03-09","title":"The Pineapple Thief",
        "artists":["the-pineapple-thief"],"new":[],
        "genre":["Rock progressif"],"organizer":"Garmonbozia",
        "soldOut":False,"url":"https://antipode-rennes.fr/agenda/pineapple-thief-2027"},
}

class AntipodeSignedPrivateTests(unittest.TestCase):
    def test_exact_geographic_signature_and_independent_official_sources(self):
        rows=DOC["referenceVenueCorrections"]
        self.assertEqual(len(rows),10)
        self.assertEqual(len({r["venueId"] for r in rows}),10)
        geo=next(r for r in rows if r["venueId"]==GEO)
        self.assertEqual((geo["reviewDecision"],geo["reviewedBy"],geo["reviewedAt"]),
                         ("approved","independent-official-verifier","2026-11-03"))
        self.assertEqual(geo["venuePatch"],{
            "address":"75 avenue Jules Maniez","postalCode":"35000",
            "latitude":48.09823,"longitude":-1.70464,
            "geoPrecision":"centre du bâtiment nommé Antipode (OpenStreetMap way 943632490), localisation indicative du bâtiment et non de l'entrée spectacles",
            "geoSource":"https://mapcarta.com/fr/W943632490"})
        a,b=geo["officialEvidence"]
        self.assertEqual(a["url"],"https://antipode-rennes.fr/informations-pratiques/acces-et-horaires")
        self.assertEqual(a["proofType"],"official-venue-address")
        self.assertEqual(b["url"],"https://mapcarta.com/fr/W943632490")
        self.assertEqual(b["proofType"],"openstreetmap-venue-way")
        self.assertTrue({"name","address","postalCode","city"}.issubset(a["checkedFields"]))
        self.assertTrue({"venueName","coordinates"}.issubset(b["checkedFields"]))
        self.assertNotEqual(a["url"],b["url"])

    def test_three_exact_named_bills_without_festival_or_imaginary_start(self):
        by={r["event"]["id"]:r for r in DOC["approvals"]}
        for ident,exp in EXPECTED.items():
            with self.subTest(ident=ident):
                r=by[ident];e=r["event"];detail,cal=r["officialEvidence"]
                self.assertEqual(r["reviewDecision"],"approved")
                self.assertEqual(r["reviewedBy"],"independent-official-verifier")
                self.assertEqual(r["reviewedAt"],"2026-11-03")
                self.assertEqual((e["title"],e["date"],e["artistIds"],e["genres"]),
                                 (exp["title"],exp["date"],exp["artists"],exp["genre"]))
                self.assertEqual(e["organizer"],exp["organizer"])
                self.assertEqual(e["venueId"],GEO)
                self.assertEqual(e["status"],"confirmed")
                self.assertEqual(e["time"],"20:30")
                self.assertEqual(e["officialUrl"],exp["url"])
                self.assertEqual([x["id"] for x in r["newArtists"]],exp["new"])
                self.assertEqual(detail["url"],e["officialUrl"])
                self.assertEqual(detail["concertStartTimeConfirmed"],"20:30")
                self.assertEqual(detail["doorTimeConfirmed"],"20:00")
                self.assertEqual(detail["soldOutOnDetailAtReview"],exp["soldOut"])
                self.assertTrue({"artists","date","venue","genre","concertStartTime",
                                 "doorTime"}.issubset(detail["checkedFields"]))
                self.assertEqual(cal["url"],"https://antipode-rennes.fr/agenda")
                self.assertEqual(cal["proofType"],"first-party-venue-calendar")
                self.assertTrue({"artists","date","venue"}.issubset(cal["checkedFields"]))
                self.assertNotIn("concertStartTime",cal["checkedFields"])

    def test_preserve_older_signatures_and_no_duplicate_venue_date_artist(self):
        self.assertGreaterEqual(len(DOC["approvals"]),138)
        rows=DOC["approvals"]
        self.assertEqual(len({r["event"]["id"] for r in rows}),len(rows))
        occupied=set()
        for r in rows:
            e=r["event"]
            for aid in e["artistIds"]:
                k=(e["venueId"],e["date"],aid)
                self.assertNotIn(k,occupied)
                occupied.add(k)
        self.assertIn("go-c-20270311-rouen-steve-n-seagulls",
                      {r["event"]["id"] for r in rows})
        self.assertGreaterEqual(len(DOC["venueApprovals"]), 19)
        self.assertEqual(len(DOC["referenceEventTimeCorrections"]),2)

if __name__=="__main__":
    unittest.main()
