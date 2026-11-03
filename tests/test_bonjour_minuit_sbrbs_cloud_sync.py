"""The 2027 SBRBS rock evening has four named first-party acts, no start guess."""
import datetime as dt
import json
from pathlib import Path
import unittest

from scripts import concerts_cloud_sync as sync

ROOT=Path(__file__).resolve().parents[1]
IDENT="go-c-20270130-saint-brieuc-sbrbs"
URL="https://bonjour-minuit.fr/evenement/sbrbs-30janv27/"
ARTISTS=["sbrbs","atoem","sarakiniko","dj-cup-of-tea"]
NAMES=["SBRBS","Atoem","Sarakiniko","DJ Cup of Tea"]
DAY=dt.date(2026,11,3)

def approved():
    return {
        "reviewDecision":"approved",
        "reviewedBy":"independent-official-verifier",
        "reviewedAt":"2026-11-03",
        "officialEvidence":[
            {"url":URL,"proofType":"official-organizer-or-venue",
             "checkedAt":"2026-11-03",
             "checkedFields":["artists","date","venue","genre"]},
            {"url":"https://bonjour-minuit.fr/agenda/",
             "proofType":"first-party-venue-calendar",
             "checkedAt":"2026-11-03",
             "checkedFields":["artists","date","venue"]},
        ],
        "event":{
            "id":IDENT,
            "title":"SBRBS + Atoem + Sarakiniko + DJ Cup of Tea",
            "date":"2027-01-30","time":None,"artistIds":list(ARTISTS),
            "venueId":"bonjour-minuit-saint-brieuc",
            "genres":["Rock indépendant"],"status":"confirmed",
            "officialUrl":URL,"sourceType":"salle",
        },
        "newArtists":[{"id":a,"name":n} for a,n in zip(ARTISTS,NAMES)]
    }

class SbrbsCloudApprovalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat=json.loads((ROOT/"docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
        cls.venues={v["id"]:v for v in cls.cat["venues"]}
        cls.artists={a["id"]:a for a in cls.cat["artists"]
                     if a["id"] not in ARTISTS}

    def test_strict_four_named_official_artists_and_no_music_start(self):
        spec=sync.BONJOUR_MINUIT_VERIFIED[IDENT]
        self.assertEqual(spec["artistIds"],ARTISTS)
        self.assertEqual(spec["artistNames"],NAMES)
        self.assertEqual(spec["newArtistIds"],ARTISTS)
        self.assertIsNone(spec["time"])
        event,new=sync.validate_approval(approved(),self.venues,self.artists,DAY)
        self.assertEqual(event["date"],"2027-01-30")
        self.assertIsNone(event["time"])
        self.assertEqual(event["artistIds"],ARTISTS)
        self.assertEqual(event["title"],"SBRBS + Atoem + Sarakiniko + DJ Cup of Tea")
        self.assertEqual(event["genres"],["Rock indépendant"])
        self.assertEqual([new[x]["name"] for x in ARTISTS],NAMES)
        self.assertEqual(len({e["id"] for e in self.cat["events"]}),
                         len(self.cat["events"]))

    def test_forged_date_ticket_or_support_acts_are_never_approved(self):
        for field,value in (
            ("id","go-c-20270130-saint-brieuc-invented"),
            ("date","2026-01-30"),("time","20:30"),
            ("artistIds",["sbrbs","atoem"]),
            ("title","SBRBS + Unknown Opening Act"),
            ("genres",["Electro"]),("venueId","antipode-rennes"),
            ("officialUrl","https://bonjour-minuit.fr/agenda/"),
            ("status","cancelled"),
        ):
            with self.subTest(field=field):
                wrong=approved();wrong["event"][field]=value
                with self.assertRaises((ValueError,KeyError)):
                    sync.validate_approval(wrong,self.venues,self.artists,DAY)
        for mutation in ("wrong_artist","wrong_id","extra_artist",
                         "wrong_date_proof","wrong_calendar","guessed_time"):
            wrong=approved()
            if mutation=="wrong_artist":
                wrong["newArtists"][1]["name"]="Fake Band"
            elif mutation=="wrong_id":
                wrong["newArtists"][1]["id"]="atoem-duplicate"
            elif mutation=="extra_artist":
                wrong["newArtists"].append({"id":"unlisted","name":"Unlisted"})
            elif mutation=="wrong_date_proof":
                wrong["officialEvidence"][0]["checkedAt"]="2026-11-02"
            elif mutation=="wrong_calendar":
                wrong["officialEvidence"][1]["url"]="https://example.org/calendar"
            elif mutation=="guessed_time":
                wrong["officialEvidence"][0]["checkedFields"].append(
                    "concertStartTime")
            with self.subTest(mutation=mutation):
                with self.assertRaises((ValueError,KeyError)):
                    sync.validate_approval(wrong,self.venues,self.artists,DAY)

    def test_prior_magma_hanry_still_preserved_without_rewriting(self):
        ids=[event["id"] for event in self.cat["events"]]
        self.assertIn("go-c-20261202-saint-brieuc-magma",ids)
        self.assertIn("go-c-20261216-rennes-hanry",ids)
        self.assertGreaterEqual(len(ids),263)
        self.assertEqual(len(ids),len(set(ids)))

if __name__=="__main__":
    unittest.main()
