"""Hydrophone Lorient: Face A official GPS, ticket-proven year, no festival."""
import copy
import datetime as dt
import unittest
from scripts import concerts_cloud_sync as sync

ID="go-c-20270210-lorient-revnoir-ice-sealed-eyes"
PILOT=sync.PILOT_VENUES["hydrophone-lorient"]
SPEC=sync.HYDROPHONE_VERIFIED[ID]
DAY=dt.date(2026,11,2)
EXISTING={i:{"id":i,"name":name,"aliases":[]} for i,name in
          (("revnoir","Revnoir"),("ice-sealed-eyes","Ice Sealed Eyes"))}

def venue():
    return {"reviewDecision":"approved","reviewedBy":"independent-official-verifier",
        "reviewedAt":"2026-11-02","venue":copy.deepcopy(PILOT["venue"]),
        "officialEvidence":[
          {"url":PILOT["officialUrl"],"proofType":"official-venue-address",
            "checkedAt":"2026-11-02",
            "checkedFields":["name","address","postalCode","city"]},
          {"url":PILOT["locationUrl"],"proofType":"official-venue-gps",
            "checkedAt":"2026-11-02",
            "checkedFields":["venueName","coordinates"]}]}

def approval():
    return {"reviewDecision":"approved","reviewedBy":"independent-official-verifier",
      "reviewedAt":"2026-11-02",
      "officialEvidence":[
        {"url":SPEC["officialUrl"],"proofType":"official-organizer-or-venue",
         "checkedAt":"2026-11-02",
         "checkedFields":["artists","day","month","venue","genre","startTime"]},
        {"url":SPEC["secondaryUrl"],"proofType":SPEC["secondaryProofType"],
         "checkedAt":"2026-11-02",
         "checkedFields":["artists","date","year","venue","startTime"],
         "dateConfirmed":"2027-02-10","startTimeConfirmed":"20:00"}],
      "event":{"id":ID,"title":SPEC["title"],"date":SPEC["date"],"time":SPEC["time"],
               "artistIds":list(SPEC["artistIds"]),"venueId":"hydrophone-lorient",
               "genres":list(SPEC["genres"]),"status":"confirmed",
               "officialUrl":SPEC["officialUrl"],"sourceType":"salle",
               "organizer":"Hydrophone"},
      "newArtists":[]}

class HydrophoneApprovals(unittest.TestCase):
    def test_named_venue_coordinates_are_from_official_gps_not_studio_pin(self):
        v=sync.validate_venue_approval(venue(),DAY)
        self.assertEqual(v["address"],"11 rue Honoré d’Estiennes d’Orves")
        self.assertAlmostEqual(v["latitude"],47.7308333333)
        self.assertAlmostEqual(v["longitude"],-3.3722222222)
        self.assertEqual(v["geoSource"],"https://www.hydrophone.fr/-Pratique-.html")

    def test_full_date_from_independent_ticket_source(self):
        e,added=sync.validate_approval(approval(),{"hydrophone-lorient":PILOT["venue"]},
                                      EXISTING,DAY)
        self.assertEqual(e["date"],"2027-02-10")
        self.assertEqual(e["time"],"20:00")
        self.assertEqual(e["artistIds"],["revnoir","ice-sealed-eyes"])
        self.assertEqual(added,{})

    def test_no_modified_venue_coordinates_or_unrelated_address(self):
        for variant in ("coordinate","address","gps_proof","address_proof"):
            x=venue()
            if variant=="coordinate":x["venue"]["latitude"]+=.1
            if variant=="address":x["venue"]["address"]="studio face B"
            if variant=="gps_proof":x["officialEvidence"][1]["url"]="https://mapcarta.com/N6865891188"
            if variant=="address_proof":x["officialEvidence"][0]["url"]="https://example.org"
            with self.subTest(variant=variant),self.assertRaises(ValueError):
                sync.validate_venue_approval(x,DAY)

    def test_year_artists_festival_and_publisher_immutable(self):
        for variant in ("id","title","festival","date","time","genre","venue",
                        "missing_artist","new_artist","wrong_url","missing_year",
                        "wrong_proof_date","ticket_changed","different_hour",
                        "unauthorized_reviewer","stale","expired_ticket"):
            x=approval()
            ev=x["event"]
            if variant=="id":ev["id"]="go-c-20261106-lorient-meryl-streek"
            if variant=="title":ev["title"]="Un autre groupe"
            if variant=="festival":ev["title"]="Les Indisciplinées festival"
            if variant=="date":ev["date"]="2026-02-10"
            if variant=="time":ev["time"]="20:30"
            if variant=="genre":ev["genres"]=["Jazz"]
            if variant=="venue":ev["venueId"]="le-ferrailleur-nantes"
            if variant=="missing_artist":ev["artistIds"]=["revnoir"]
            if variant=="new_artist":x["newArtists"]=[{"id":"unknown","name":"Unknown"}]
            if variant=="wrong_url":ev["officialUrl"]="https://example.org"
            if variant=="missing_year":x["officialEvidence"][1]["checkedFields"].remove("year")
            if variant=="wrong_proof_date":x["officialEvidence"][1]["dateConfirmed"]="2026-02-10"
            if variant=="ticket_changed":x["officialEvidence"][1]["url"]="https://tickets.example"
            if variant=="different_hour":x["officialEvidence"][1]["startTimeConfirmed"]="21:00"
            if variant=="unauthorized_reviewer":x["reviewedBy"]="automated-official-recheck"
            if variant=="stale":x["reviewedAt"]="2026-10-01"
            if variant=="expired_ticket":x["officialEvidence"][1]["checkedAt"]="2026-10-01"
            with self.subTest(variant=variant),self.assertRaises(ValueError):
                sync.validate_approval(x,{"hydrophone-lorient":PILOT["venue"]},EXISTING,DAY)

if __name__=="__main__":unittest.main()
