"""Atabal Biarritz hardcoded venue and first-party bill regression suite."""
import copy
import datetime as dt
import unittest
from scripts import concerts_cloud_sync as sync

TODAY=dt.date(2026,11,2)
VID="atabal-biarritz"
VENUE=sync.PILOT_VENUES[VID]
NEW={"mafia-sofa":"Mafia Sofa","anestesia":"Anestesia","horzdun":"Horzdun",
     "burning-heads":"Burning Heads","not-scientists":"Not Scientists",
     "the-dead-krazukies":"The Dead Krazukies"}
EXISTING={
    "frankie-and-the-witch-fingers":{"id":"frankie-and-the-witch-fingers",
                                  "name":"Frankie and the Witch Fingers"},
    "iguana-death-cult":{"id":"iguana-death-cult","name":"Iguana Death Cult"},
}

def location():
    return {"reviewDecision":"approved","reviewedBy":"independent-official-verifier",
       "reviewedAt":"2026-11-02","venue":copy.deepcopy(VENUE["venue"]),
       "officialEvidence":[
          {"url":VENUE["officialUrl"],"proofType":"official-venue-address",
           "checkedAt":"2026-11-02",
           "checkedFields":["name","address","postalCode","city"]},
          {"url":VENUE["locationUrl"],"proofType":"official-tourism-geo",
           "checkedAt":"2026-11-02",
           "checkedFields":["venueName","coordinates"]}]}

def bill(event_id):
    spec=sync.ATABAL_VERIFIED[event_id]
    return {"reviewDecision":"approved",
       "reviewedBy":"independent-official-verifier","reviewedAt":"2026-11-02",
       "officialEvidence":[
           {"url":spec["officialUrl"],"proofType":"official-organizer-or-venue",
            "checkedAt":"2026-11-02",
            "checkedFields":["artists","date","venue","genre"]},
           {"url":"https://www.atabal-biarritz.fr/agenda/concerts/",
            "proofType":"first-party-venue-calendar","checkedAt":"2026-11-02",
            "checkedFields":["artists","date","venue"]}],
       "event":{"id":event_id,"title":spec["title"],"date":spec["date"],
                "time":spec["time"],"venueId":VID,"artistIds":spec["artistIds"],
                "genres":spec["genres"],"status":"confirmed",
                "officialUrl":spec["officialUrl"],"sourceType":"salle",
                "organizer":"Atabal Biarritz"},
       "newArtists":[{"id":i,"name":NEW[i]} for i in spec["newArtistIds"]]}

class AtabalWhitelistTests(unittest.TestCase):
    def test_venue_is_grounded_in_independent_tourism_gps(self):
        result=sync.validate_venue_approval(location(),TODAY)
        self.assertEqual(result["address"],"37 allée du Moura")
        self.assertEqual((result["latitude"],result["longitude"]),(43.4604,-1.53984))
        self.assertIn("tourisme64.com",result["geoSource"])

    def test_all_three_approved_with_no_start_time(self):
        self.assertEqual(len(sync.ATABAL_VERIFIED),3)
        for key in sync.ATABAL_VERIFIED:
            with self.subTest(key=key):
                event,artists=sync.validate_approval(
                    bill(key),{VID:VENUE["venue"]},EXISTING,TODAY)
                self.assertIsNone(event["time"])
                self.assertEqual(set(artists),set(sync.ATABAL_VERIFIED[key]["newArtistIds"]))
                self.assertTrue(event["genres"])

    def test_forged_tourism_coordinates_or_address_rejected(self):
        for bad in ("lat","lon","addr","geo_url","proof_type","date","reviewer"):
            row=location()
            if bad=="lat":row["venue"]["latitude"]+=.4
            if bad=="lon":row["venue"]["longitude"]+=.7
            if bad=="addr":row["venue"]["address"]="Autre salle"
            if bad=="geo_url":row["officialEvidence"][1]["url"]="https://example.net"
            if bad=="proof_type":row["officialEvidence"][1]["proofType"]="aggregator"
            if bad=="date":row["officialEvidence"][1]["checkedAt"]="2026-10-05"
            if bad=="reviewer":row["reviewedBy"]="automated-official-recheck"
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                sync.validate_venue_approval(row,TODAY)

    def test_forged_dates_lineup_and_time_rejected(self):
        key="go-c-20261211-biarritz-anestesia-horzdun"
        for bad in ("date","title","time","artists","genre","url","source",
                    "proof","calendar","age","reviewer"):
            row=bill(key)
            if bad=="date":row["event"]["date"]="2026-10-24"
            if bad=="title":row["event"]["title"]="Anestesia + Invented"
            if bad=="time":row["event"]["time"]="20:30"
            if bad=="artists":row["newArtists"][0]["name"]="Wrong"
            if bad=="genre":row["event"]["genres"]=["Rap"]
            if bad=="url":row["event"]["officialUrl"]="https://example.org"
            if bad=="source":row["event"]["sourceType"]="aggregator"
            if bad=="proof":row["officialEvidence"][0]["checkedFields"].remove("genre")
            if bad=="calendar":row["officialEvidence"][1]["url"]="https://example.org/agenda"
            if bad=="age":row["reviewedAt"]="2026-10-05"
            if bad=="reviewer":row["reviewedBy"]="automated-official-recheck"
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                sync.validate_approval(row,{VID:VENUE["venue"]},EXISTING,TODAY)

    def test_unlisted_atabal_events_not_publishable(self):
        row=bill("go-c-20270514-biarritz-burning-heads")
        row["event"]["id"]="go-c-20270115-biarritz-svinkels"
        with self.assertRaises(ValueError):
            sync.validate_approval(row,{VID:VENUE["venue"]},EXISTING,TODAY)

if __name__=="__main__":
    unittest.main()
