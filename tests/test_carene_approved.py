"""La Carène: named OSM way, official site address, two exact punk bills."""
import copy
import datetime as dt
import unittest
from scripts import concerts_cloud_sync as sync

TODAY=dt.date(2026,11,2)
VENUE_ID="la-carene-brest"
PILOT=sync.PILOT_VENUES[VENUE_ID]
ARTISTS={"dame-area":"Dame Area","tact":"Tact",
         "mary-bell":"Mary Bell","prisonnier-du-temps":"Prisonnier du temps"}

def venue_approval():
    return {"reviewDecision":"approved","reviewedBy":"independent-official-verifier",
        "reviewedAt":"2026-11-02","venue":copy.deepcopy(PILOT["venue"]),
        "officialEvidence":[
            {"url":PILOT["officialUrl"],"proofType":"official-venue-address",
             "checkedAt":"2026-11-02",
             "checkedFields":["name","address","postalCode","city"]},
            {"url":PILOT["locationUrl"],"proofType":"openstreetmap-venue-way",
             "checkedAt":"2026-11-02","checkedFields":["venueName","coordinates"]}]}

def approval(event_id):
    spec=sync.CARENE_VERIFIED[event_id]
    return {"reviewDecision":"approved","reviewedBy":"independent-official-verifier",
        "reviewedAt":"2026-11-02","officialEvidence":[
            {"url":spec["officialUrl"],"proofType":"official-organizer-or-venue",
             "checkedAt":"2026-11-02",
             "checkedFields":["artists","date","venue","genre","startTime"]},
            {"url":"https://www.lacarene.fr/-agenda-.html",
             "proofType":"first-party-venue-calendar","checkedAt":"2026-11-02",
             "checkedFields":["artists","date","venue"]}],
        "event":{"id":event_id,"title":spec["title"],"date":spec["date"],
                 "artistIds":list(spec["artistIds"]),"time":spec["time"],
                 "genres":list(spec["genres"]),"venueId":VENUE_ID,
                 "status":"confirmed","officialUrl":spec["officialUrl"],
                 "sourceType":"salle","organizer":"La Carène"},
        "newArtists":[{"id":i,"name":ARTISTS[i]} for i in spec["artistIds"]]}

class CareneApprovedTests(unittest.TestCase):
    def test_verified_precise_venue_on_named_osm_feature(self):
        v=sync.validate_venue_approval(venue_approval(),TODAY)
        self.assertEqual(v["city"],"Brest")
        self.assertEqual(v["postalCode"],"29200")
        self.assertAlmostEqual(v["latitude"],48.38479)
        self.assertAlmostEqual(v["longitude"],-4.48195)

    def test_both_bills_approved_with_explicit_start_and_all_artists(self):
        self.assertEqual(len(sync.CARENE_VERIFIED),2)
        for event_id in sync.CARENE_VERIFIED:
            with self.subTest(event_id=event_id):
                event,added=sync.validate_approval(
                    approval(event_id),{VENUE_ID:PILOT["venue"]},{},TODAY)
                self.assertEqual(event["time"],"21:00")
                self.assertEqual(set(added),set(event["artistIds"]))

    def test_no_forged_venue_or_coordinate(self):
        for mutation in ("coords","address","evidence","reviewer"):
            a=venue_approval()
            if mutation=="coords":a["venue"]["latitude"]+=0.4
            if mutation=="address":a["venue"]["address"]="Ailleurs"
            if mutation=="evidence":a["officialEvidence"][1]["url"]="https://example.org/map"
            if mutation=="reviewer":a["reviewedBy"]="automated-official-recheck"
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                sync.validate_venue_approval(a,TODAY)

    def test_bill_mutations_not_publishable(self):
        event_id="go-c-20261128-brest-mary-bell-prisonnier-du-temps"
        for mutation in ("title","date","time","genre","artists","url","venue",
                         "provenance","proof","agenda","reviewer","stale"):
            a=approval(event_id)
            if mutation=="title":a["event"]["title"]="Metalearth Festival"
            if mutation=="date":a["event"]["date"]="2026-11-29"
            if mutation=="time":a["event"]["time"]="20:30"
            if mutation=="genre":a["event"]["genres"]=["Jazz"]
            if mutation=="artists":a["newArtists"][0]["name"]="Imaginary Band"
            if mutation=="url":a["event"]["officialUrl"]="https://tickets.example/test"
            if mutation=="venue":a["event"]["venueId"]="a-random-venue"
            if mutation=="provenance":a["event"]["sourceType"]="aggregator"
            if mutation=="proof":a["officialEvidence"][0]["checkedFields"].remove("genre")
            if mutation=="agenda":a["officialEvidence"][1]["url"]="https://example.org/agenda"
            if mutation=="reviewer":a["reviewedBy"]="automated-official-recheck"
            if mutation=="stale":a["reviewedAt"]="2026-10-10"
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                sync.validate_approval(a,{VENUE_ID:PILOT["venue"]},{},TODAY)

    def test_no_other_carene_or_festival_accepted(self):
        a=approval("go-c-20261107-brest-dame-area-tact")
        a["event"]["id"]="go-c-20261113-brest-metalearth-festival"
        with self.assertRaises(ValueError):
            sync.validate_approval(a,{VENUE_ID:PILOT["venue"]},{},TODAY)

if __name__=="__main__":unittest.main()
