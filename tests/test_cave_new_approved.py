"""First-party two-document GROSSes ONDES Joobieseaz approval tests."""
import copy
import datetime as dt
import unittest
from scripts import concerts_cloud_sync as sync

EVENT_ID="go-c-20261216-roubaix-joobieseaz-belljars"
SPEC=sync.CAVE_POETES_VERIFIED[EVENT_ID]
TODAY=dt.date(2026,11,2)
VENUES={"la-cave-aux-poetes-roubaix":{"id":"la-cave-aux-poetes-roubaix",
                                        "city":"Roubaix","name":"La Cave aux Poètes"}}

def approval():
    return {"reviewDecision":"approved","reviewedBy":"independent-official-verifier",
        "reviewedAt":"2026-11-02",
        "officialEvidence":[
            {"url":SPEC["officialUrl"],"proofType":"official-organizer-or-venue",
             "checkedAt":"2026-11-02",
             "checkedFields":["artists","date","venue","genre","startTime"],
             "notes":"First-party detail page, post-punk in Joobieseaz biography, start time 19h."},
            {"url":SPEC["organizerCalendar"],
             "proofType":"first-party-venue-calendar","checkedAt":"2026-11-02",
             "checkedFields":["artists","date","venue"],
             "notes":"Independent fetch of venue's dated agenda card in same primary venue."}],
        "event":{"id":EVENT_ID,"title":SPEC["title"],"date":SPEC["date"],
            "time":SPEC["time"],"artistIds":SPEC["artistIds"],
            "venueId":"la-cave-aux-poetes-roubaix","genres":SPEC["genres"],
            "status":"confirmed","officialUrl":SPEC["officialUrl"],
            "sourceType":"salle","organizer":"La Cave aux Poètes"},
        "newArtists":[{"id":"joobieseaz","name":"Joobieseaz"},
                      {"id":"belljars","name":"Belljars"}]}

class CaveNewApprovalTests(unittest.TestCase):
    def test_single_named_first_party_case_is_valid(self):
        event,artists=sync.validate_approval(approval(),VENUES,{},TODAY)
        self.assertEqual(event["time"],"19:00")
        self.assertEqual(set(artists),{"joobieseaz","belljars"})

    def test_exact_sources_genre_artists_date_and_time_required(self):
        for mutated in ("date","venue","time","genre","url","name","proof","calendar","reviewer"):
            a=approval()
            if mutated=="date":a["event"]["date"]="2026-12-15"
            if mutated=="venue":a["event"]["venueId"]="nonexistent"
            if mutated=="time":a["event"]["time"]="18:30"
            if mutated=="genre":a["event"]["genres"]=["Rock"]
            if mutated=="url":a["event"]["officialUrl"]="https://tickets.example/joobieseaz"
            if mutated=="name":a["newArtists"][0]["name"]="Another Act"
            if mutated=="proof":a["officialEvidence"][0]["checkedFields"].remove("genre")
            if mutated=="calendar":a["officialEvidence"][1]["proofType"]="independent-aggregator"
            if mutated=="reviewer":a["reviewedBy"]="automated-official-recheck"
            with self.subTest(mutated=mutated),self.assertRaises(ValueError):
                sync.validate_approval(a,VENUES,{},TODAY)

    def test_no_open_ended_permission_for_other_bills(self):
        a=approval()
        a["event"]["id"]="go-c-20261217-roubaix-another-group"
        with self.assertRaises(ValueError):
            sync.validate_approval(a,VENUES,{},TODAY)
        self.assertIn("go-c-20261108-roubaix-babe-haven-latter-muddle",
                      sync.CAVE_POETES_VERIFIED)

if __name__=="__main__":unittest.main()
