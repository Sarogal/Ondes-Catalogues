"""No-network authorization tests for two Paris clubs and 3 named bills."""
import copy
import datetime as dt
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from concerts_cloud_sync import PILOT_VENUES, PARIS_CLUB_VERIFIED, merge, protect_reference

BASE=json.loads((ROOT/"docs/grossesondes/concerts-reference.json").read_text(encoding="utf8"))
DAY=dt.date(2026,11,2)
NAMES={"allt":"Allt","avralize":"Avralize","bite-down":"Bite Down",
       "we-are-magonia":"We Are Magonia","eiga":"Eiga"}

def approved_queue():
    venues=[]
    for key in ("la-maroquinerie-paris","la-boule-noire-paris"):
        src=PILOT_VENUES[key]
        venues.append({
            "reviewDecision":"approved",
            "reviewedBy":"independent-official-verifier",
            "reviewedAt":"2026-11-02",
            "venue":copy.deepcopy(src["venue"]),
            "officialEvidence":[
                {"url":src["officialUrl"],"proofType":"official-venue-address",
                 "checkedAt":"2026-11-02",
                 "checkedFields":["name","address","postalCode","city"]},
                {"url":src["locationUrl"],"proofType":"openstreetmap-venue-node",
                 "checkedAt":"2026-11-02",
                 "checkedFields":["venueName","coordinates"]},
            ],
        })
    approvals=[]
    for key,src in PARIS_CLUB_VERIFIED.items():
        proofs=[{"proofType":kind,"url":url,"checkedAt":"2026-11-02",
                 "checkedFields":list(fields)}
                for kind,url,fields in src["proofs"]]
        approvals.append({
            "reviewDecision":"approved",
            "reviewedBy":"independent-official-verifier",
            "reviewedAt":"2026-11-02",
            "officialEvidence":proofs,
            "event":{
                "id":key,"title":src["title"],"date":src["date"],
                "time":None,"artistIds":list(src["artistIds"]),
                "venueId":src["venueId"],"genres":list(src["genres"]),
                "status":"confirmed","officialUrl":src["officialUrl"],
                "sourceType":"salle","organizer":src["venueId"],
            },
            "newArtists":[{"id":a,"name":NAMES[a]}
                          for a in src["newArtistIds"]],
        })
    return {"schema":"grossesondes.concert.approvals.v1",
            "venueApprovals":venues,"approvals":approvals}

class ParisClubsWhitelistTests(unittest.TestCase):
    def test_three_named_events_two_unique_osm_points_and_existing_artists(self):
        q=approved_queue()
        result,report=merge(BASE,BASE,q,DAY)
        self.assertEqual(report["held"],[])
        self.assertEqual((report["newVenues"],report["newEvents"],report["newArtists"]),
                         (2,3,5))
        rows=result["events"][-3:]
        self.assertEqual([r["date"] for r in rows],
                         ["2026-11-10","2026-11-21","2026-11-15"])
        self.assertEqual(rows[0]["artistIds"],["allt","avralize","bite-down"])
        self.assertEqual(rows[1]["artistIds"],["horskh","we-are-magonia"])
        self.assertEqual(rows[2]["artistIds"],["ice-sealed-eyes","eiga"])
        self.assertTrue(all(e["time"] is None for e in rows))
        venues={v["id"]:v for v in result["venues"]}
        self.assertEqual((venues["la-maroquinerie-paris"]["latitude"],
                          venues["la-maroquinerie-paris"]["longitude"]),
                         (48.86853,2.39206))
        self.assertEqual((venues["la-boule-noire-paris"]["latitude"],
                          venues["la-boule-noire-paris"]["longitude"]),
                         (48.88234,2.34028))
        self.assertIn("distinct de La Cigale",
                      venues["la-boule-noire-paris"]["geoPrecision"])
        protect_reference(BASE,result)
        again,stats=merge(BASE,result,q,DAY)
        self.assertEqual(stats["newEvents"],0)
        self.assertEqual(stats["newVenues"],0)
        self.assertEqual(again,result)

    def test_missing_or_faked_support_time_genre_and_year_are_held(self):
        ids=list(PARIS_CLUB_VERIFIED)
        for variant in ("missing-bite-down","wrong-date","invented-start",
                        "wrong-domain","wrong-genre","missing-magonia",
                        "missing-calendar-proof","faked-calendar-proof",
                        "extra-artist","wrong-identity","unauthorized-concert"):
            with self.subTest(variant=variant):
                q=approved_queue()
                a=q["approvals"][1] if variant in (
                    "missing-magonia","missing-calendar-proof",
                    "faked-calendar-proof") else q["approvals"][0]
                q["approvals"]=[a]
                e=a["event"]
                if variant=="missing-bite-down":e["artistIds"].pop()
                elif variant=="wrong-date":e["date"]="2026-11-09"
                elif variant=="invented-start":e["time"]="19:30"
                elif variant=="wrong-domain":e["officialUrl"]="https://evil.test/show"
                elif variant=="wrong-genre":e["genres"]=["Jazz"]
                elif variant=="missing-magonia":e["artistIds"].pop()
                elif variant=="missing-calendar-proof":
                    a["officialEvidence"]=a["officialEvidence"][:1]
                elif variant=="faked-calendar-proof":
                    a["officialEvidence"][1]["checkedFields"]=["artists","venue"]
                elif variant=="extra-artist":
                    e["artistIds"].append("unknown-artist")
                elif variant=="wrong-identity":
                    a["newArtists"][0]["name"]="Another Band"
                elif variant=="unauthorized-concert":e["id"]="go-c-20261110-paris-mystery"
                out,report=merge(BASE,BASE,q,DAY)
                self.assertEqual(report["newEvents"],0)
                self.assertTrue(report["held"])
                self.assertEqual(out["events"],BASE["events"])

    def test_no_leak_to_third_party_venue_or_rogue_geo(self):
        for variant in ("wrong-maro-pin","wrong-boule-pin","fake-node",
                        "evil-venue-page"):
            q=approved_queue()
            if variant=="wrong-maro-pin":
                q["venueApprovals"][0]["venue"]["latitude"]+=.02
            elif variant=="wrong-boule-pin":
                q["venueApprovals"][1]["venue"]["longitude"]-=.02
            elif variant=="fake-node":
                q["venueApprovals"][1]["officialEvidence"][1]["proofType"] = "openstreetmap-venue-way"
            else:
                q["venueApprovals"][0]["officialEvidence"][0]["url"]="https://untrusted.test/"
            q["approvals"]=[]
            out,stats=merge(BASE,BASE,q,DAY)
            self.assertTrue(stats["held"])
            self.assertEqual(stats["newVenues"],1)
            self.assertEqual(out["events"],BASE["events"])
        # Even a perfect site URL is not authorization for another event.
        q=approved_queue()
        q["approvals"][0]["event"]["id"]="go-c-20261110-paris-unvetted"
        q["approvals"]=q["approvals"][:1]
        out,report=merge(BASE,BASE,q,DAY)
        self.assertEqual(report["newEvents"],0)
        self.assertTrue(report["held"])

if __name__=="__main__":
    unittest.main()
