"""Le Tetris: 4 signed concerts only, exact independent-year proofs."""
import copy
import datetime as dt
import json
from pathlib import Path
import unittest
from scripts import concerts_cloud_sync as sync

TODAY = dt.date(2026, 11, 3)
V = "le-tetris-le-havre"
CAT = json.loads((Path(__file__).resolve().parents[1]/
                  "docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
# Reconstruct pre-approval artists: the live catalogue contains the six
# Tetris acts added after the signed fixture was originally written.
SIGNED_NEW = {"edging","zonbi","metro-verlaine","coffin","belek","grimskunk"}
KNOWN = {a["id"]: a for a in CAT["artists"] if a["id"] not in SIGNED_NEW}
NAMES = {name.lower().replace(".","").replace(" ","-"): name for name in ()}
NAMES.update({"edging":"Edging","zonbi":"Zonbi",
              "metro-verlaine":"Metro Verlaine","coffin":"C.O.F.F.I.N.",
              "belek":"Belek","grimskunk":"GrimSkunk"})


def venue_row():
    spec=sync.PILOT_VENUES[V]
    return {
        "reviewDecision":"approved",
        "reviewedBy":"independent-official-verifier",
        "reviewedAt":"2026-11-03",
        "venue":copy.deepcopy(spec["venue"]),
        "officialEvidence":[
            {"url":spec["officialUrl"],"proofType":"official-venue-address",
             "checkedAt":"2026-11-03",
             "checkedFields":["name","address","postalCode","city"]},
            {"url":spec["locationUrl"],"proofType":"independent-tourism-gps",
             "checkedAt":"2026-11-03",
             "checkedFields":["venueName","coordinates"]},
        ],
    }


def event_row(key):
    spec=sync.TETRIS_VERIFIED[key]
    return {
        "reviewDecision":"approved",
        "reviewedBy":"independent-official-verifier",
        "reviewedAt":"2026-11-03",
        "officialEvidence":[
            {"url":spec["officialUrl"],"proofType":"official-organizer-or-venue",
             "checkedAt":"2026-11-03",
             "checkedFields":["artists","venue","genre","dayMonth"]},
            {"url":spec["secondaryUrl"],"proofType":spec["secondaryProofType"],
             "checkedAt":"2026-11-03",
             "checkedFields":["artists","venue","fullDate"]},
        ],
        "event":{
            "id":key,"title":spec["title"],"date":spec["date"],
            "time":spec["time"],"artistIds":list(spec["artistIds"]),
            "venueId":V,"genres":list(spec["genres"]),
            "status":"confirmed","officialUrl":spec["officialUrl"],
            "sourceType":"salle","organizer":"Le Tetris",
        },
        "newArtists":[{"id":aid,"name":NAMES[aid]}
                      for aid in spec["newArtistIds"]],
    }


class TetrisCloudTests(unittest.TestCase):
    def test_only_exact_verified_venue_with_tourism_coordinates(self):
        v=sync.validate_venue_approval(venue_row(), TODAY)
        self.assertEqual((v["city"],v["department"],v["postalCode"]),
                         ("Le Havre","76","76620"))
        self.assertEqual((v["latitude"],v["longitude"]),
                         (49.5043853,0.1206928))
        self.assertIn("indicative",v["geoPrecision"])

    def test_all_four_true_concerts_pass_review_with_independent_full_year(self):
        self.assertEqual(len(sync.TETRIS_VERIFIED),4)
        total_new=[]
        for key,spec in sync.TETRIS_VERIFIED.items():
            with self.subTest(key=key):
                e,added=sync.validate_approval(
                    event_row(key),{V:sync.PILOT_VENUES[V]["venue"]},
                    KNOWN,TODAY)
                self.assertEqual((e["date"],e["artistIds"]),
                                 (spec["date"],spec["artistIds"]))
                self.assertIsNone(e["time"])
                self.assertEqual(list(added),spec["newArtistIds"])
                total_new.extend(added)
        self.assertEqual(len(total_new),6)
        self.assertEqual(len(set(total_new)),6)
        self.assertNotIn("fff",total_new)
        self.assertNotIn("the-inspector-cluzo",total_new)

    def test_gps_address_source_review_cannot_be_forged(self):
        for kind in ("lat","lon","address","geo","proof","review"):
            row=venue_row()
            if kind=="lat":
                row["venue"]["latitude"]+=0.1
            if kind=="lon":
                row["venue"]["longitude"]-=0.1
            if kind=="address":
                row["venue"]["address"]="incorrecte"
            if kind=="geo":
                row["venue"]["geoSource"]="https://bad.example"
            if kind=="proof":
                row["officialEvidence"][1]["url"]="https://bad.example"
            if kind=="review":
                row["reviewedBy"]="automated"
            with self.subTest(kind=kind),self.assertRaises((ValueError,KeyError)):
                sync.validate_venue_approval(row,TODAY)

    def test_forged_artist_year_genre_domain_and_door_hours_fail_closed(self):
        key="go-c-20261212-lehavre-the-inspector-cluzo-grimskunk"
        for kind in ("id","date","time","title","artists","venue","genre",
                     "url","secondary","secondary_type","pretend_year_first_party",
                     "artist_identity","stale","reviewer","missing_evidence"):
            row=event_row(key)
            e=row["event"]
            if kind=="id":
                e["id"]="go-c-20261212-lehavre-faux-groupe"
            if kind=="date":
                e["date"]="2027-12-12"
            if kind=="time":
                e["time"]="20:00"
            if kind=="title":
                e["title"]="The Inspector Cluzo"
            if kind=="artists":
                e["artistIds"]=["the-inspector-cluzo"]
            if kind=="venue":
                e["venueId"]="not-tetris"
            if kind=="genre":
                e["genres"]=["Jazz"]
            if kind=="url":
                e["officialUrl"]="https://fake.example/agenda/inspector-cluzo"
            if kind=="secondary":
                row["officialEvidence"][1]["url"]="https://fake.example"
            if kind=="secondary_type":
                row["officialEvidence"][1]["proofType"]="uncorroborated-date"
            if kind=="pretend_year_first_party":
                row["officialEvidence"][0]["checkedFields"].append("fullDate")
            if kind=="artist_identity":
                row["newArtists"][0]["name"]="Other artist"
            if kind=="stale":
                row["reviewedAt"]="2026-10-01"
            if kind=="reviewer":
                row["reviewedBy"]="automated"
            if kind=="missing_evidence":
                row["officialEvidence"].pop()
            with self.subTest(kind=kind),self.assertRaises((ValueError,KeyError)):
                sync.validate_approval(row,{V:sync.PILOT_VENUES[V]["venue"]},
                                       KNOWN,TODAY)


if __name__=="__main__":
    unittest.main()
