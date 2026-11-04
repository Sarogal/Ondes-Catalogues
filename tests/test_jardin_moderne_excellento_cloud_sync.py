"""Le Jardin Moderne Rennes: independently approved exact artist bill only."""
import copy
import datetime as dt
import json
from pathlib import Path
import unittest
from scripts import concerts_cloud_sync as sync

ROOT=Path(__file__).resolve().parents[1]
ID="go-c-20261107-rennes-excellento"
VENUE="le-jardin-moderne-rennes"
URL="https://www.jardinmoderne.org/agenda/excellento-joey-gluten-batarde/"
GEO="https://mapcarta.com/fr/W80301709"
DAY=dt.date(2026,11,4)
ARTISTS=["excellento","joey-gluten","batarde"]
NAMES=["Excellento","Joey Glüten","Bâtarde"]

def signed_venue():
    return {
        "reviewDecision":"approved","reviewedBy":"independent-official-verifier",
        "reviewedAt":"2026-11-03",
        "officialEvidence":[
            {"url":"https://www.jardinmoderne.org/acces-2/",
             "proofType":"official-venue-address","checkedAt":"2026-11-03",
             "checkedFields":["name","address","postalCode","city"]},
            {"url":GEO,"proofType":"openstreetmap-venue-way",
             "checkedAt":"2026-11-03",
             "checkedFields":["venueName","coordinates"]}
        ],
        "venue":copy.deepcopy(sync.PILOT_VENUES[VENUE]["venue"])
    }

def signed_event():
    return {
        "reviewDecision":"approved","reviewedBy":"independent-official-verifier",
        "reviewedAt":"2026-11-03",
        "officialEvidence":[
            {"url":URL,"proofType":"official-organizer-or-venue",
             "checkedAt":"2026-11-03",
             "checkedFields":["artists","date","venue","genre"]},
            {"url":"https://www.jardinmoderne.org/agenda/",
             "proofType":"first-party-venue-calendar","checkedAt":"2026-11-03",
             "checkedFields":["artists","date","venue"]}
        ],
        "event":{"id":ID,"title":"Excellento + Joey Glüten + Bâtarde",
                 "date":"2026-11-07","time":None,
                 "artistIds":ARTISTS[:],"venueId":VENUE,
                 "genres":["Rock"],"status":"confirmed",
                 "officialUrl":URL,"sourceType":"salle"},
        "newArtists":[{"id":i,"name":n} for i,n in zip(ARTISTS,NAMES)]
    }

class JardinModerneCloudTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat=json.loads((ROOT/"docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
        cls.venues={v["id"]:v for v in cls.cat["venues"]}
        cls.venues[VENUE]=sync.PILOT_VENUES[VENUE]["venue"]
        cls.artists={a["id"]:a for a in cls.cat["artists"] if a["id"] not in ARTISTS}

    def test_venue_geo_signed_by_two_distinct_providers(self):
        v=sync.validate_venue_approval(signed_venue(),DAY)
        self.assertEqual(v["name"],"Le Jardin Moderne")
        self.assertEqual(v["address"],"11 rue du Manoir de Servigné")
        self.assertEqual(v["city"],"Rennes")
        self.assertEqual((v["latitude"],v["longitude"]),(48.10164,-1.72557))
        self.assertEqual(v["geoSource"],GEO)
        self.assertIn("non assimilé",v["geoPrecision"])
        for index,key,value in (
            (0,"url","https://example.org/acces/"),
            (1,"url","https://example.org/map"),
            (1,"proofType","unverified"),
            (1,"checkedFields",[]),
            (0,"checkedAt","2026-11-05"),
        ):
            wrong=signed_venue()
            wrong["officialEvidence"][index][key]=value
            with self.subTest(index=index,key=key):
                with self.assertRaises((ValueError,KeyError)):
                    sync.validate_venue_approval(wrong,DAY)

    def test_exact_rock_lineup_and_unverified_start(self):
        self.assertIsNone(sync.JARDIN_MODERNE_VERIFIED[ID]["time"])
        row,added=sync.validate_approval(signed_event(),
                                          self.venues,self.artists,DAY)
        self.assertEqual(row["date"],"2026-11-07")
        self.assertIsNone(row["time"])
        self.assertEqual(row["artistIds"],ARTISTS)
        self.assertEqual(row["genres"],["Rock"])
        self.assertEqual(row["venueId"],VENUE)
        self.assertEqual([added[a]["name"] for a in ARTISTS],NAMES)

    def test_forged_dates_bands_rooms_or_start_clocks_never_publish(self):
        for key,value in (
            ("id","go-c-20261107-rennes-fake"),
            ("title","Excellento + Invented"),
            ("date","2027-11-07"),
            ("time","20:00"),
            ("artistIds",["excellento"]),
            ("artistIds",["excellento","joey-gluten","fake"]),
            ("venueId","antipode-rennes"),
            ("genres",["Rap"]),("status","cancelled"),
            ("officialUrl","https://www.jardinmoderne.org/agenda/"),
        ):
            wrong=signed_event()
            wrong["event"][key]=value
            with self.subTest(key=key,value=str(value)):
                with self.assertRaises((ValueError,KeyError)):
                    sync.validate_approval(wrong,self.venues,self.artists,DAY)
        for mutation in ("wrong_name","additional","bad_geo_proof",
                         "unverified_time","unofficial_calendar","old"):
            wrong=signed_event()
            if mutation=="wrong_name":
                wrong["newArtists"][0]["name"]="Fake"
            elif mutation=="additional":
                wrong["newArtists"].append({"id":"other","name":"Other"})
            elif mutation=="bad_geo_proof":
                wrong["officialEvidence"][0]["url"]="https://example.org/event"
            elif mutation=="unverified_time":
                wrong["officialEvidence"][0]["checkedFields"].append("concertStartTime")
            elif mutation=="unofficial_calendar":
                wrong["officialEvidence"][1]["url"]="https://example.org/agenda"
            elif mutation=="old":
                wrong["reviewedAt"]="2026-10-01"
            with self.subTest(mutation=mutation):
                with self.assertRaises((ValueError,KeyError)):
                    sync.validate_approval(wrong,self.venues,self.artists,DAY)

    def test_existing_264_public_events_stay_unique(self):
        ids=[e["id"] for e in self.cat["events"]]
        self.assertGreaterEqual(len(ids),264)
        self.assertEqual(len(ids),len(set(ids)))
        self.assertIn("go-c-20270130-saint-brieuc-sbrbs",ids)
        self.assertIn("go-c-20261202-saint-brieuc-magma",ids)
        self.assertIn("go-c-20261216-rennes-hanry",ids)

if __name__=="__main__":
    unittest.main()
