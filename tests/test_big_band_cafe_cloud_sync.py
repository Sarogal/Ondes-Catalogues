"""Big Band Café, Hérouville: two source-pinned dates, not concert-start times."""
import copy
import datetime as dt
import json
from pathlib import Path
import unittest
from scripts import concerts_cloud_sync as sync

ROOT=Path(__file__).resolve().parents[1]
TODAY=dt.date(2026,11,3)
IDS=tuple(sync.BBC_NORMANDY_VERIFIED)


def make_row(event_id):
    spec=sync.BBC_NORMANDY_VERIFIED[event_id]
    return {
        "reviewDecision":"approved",
        "reviewedBy":"independent-official-verifier",
        "reviewedAt":"2026-11-03",
        "officialEvidence":[
            {"url":spec["officialUrl"],"proofType":"official-organizer-or-venue",
             "checkedAt":"2026-11-03",
             "checkedFields":["artists","date","venue","genre"]},
            {"url":spec["ticketUrl"],
             "proofType":"authorized-ticket-distributor-full-date",
             "checkedAt":"2026-11-03",
             "checkedFields":["artists","date","venue"]}
        ],
        "event":{
            "id":event_id,"title":spec["title"],"date":spec["date"],
            "time":None,"artistIds":list(spec["artistIds"]),
            "venueId":spec["venueId"],"genres":list(spec["genres"]),
            "status":"confirmed","officialUrl":spec["officialUrl"],
            "sourceType":"salle","organizer":"Big Band Café"
        },
        "newArtists":[
            {"id":aid,"name":spec["artistNames"][i]}
            for i, aid in enumerate(spec["artistIds"])
            if aid in spec["newArtistIds"]
        ],
    }


class BBCSignedAllowlistTests(unittest.TestCase):
    def setup_catalogue(self):
        cat=json.loads((ROOT/"docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
        venues={v["id"]:v for v in cat["venues"]}
        artists={a["id"]:a for a in cat["artists"] if a["id"]!="madam"}
        return cat,venues,artists

    def test_two_documented_official_dates_without_made_up_start(self):
        cat,venues,artists=self.setup_catalogue()
        for ident in IDS:
            with self.subTest(id=ident):
                s=sync.BBC_NORMANDY_VERIFIED[ident]
                event,new=sync.validate_approval(make_row(ident),venues,artists,TODAY)
                self.assertEqual(event["date"],s["date"])
                self.assertEqual(event["venueId"],"big-band-cafe-herouville")
                self.assertEqual(event["artistIds"],s["artistIds"])
                self.assertIsNone(event["time"])
                self.assertEqual(list(new),s["newArtistIds"])
        self.assertIn("ugly-kid-joe",artists)

    def test_no_forged_artist_date_id_or_door_time(self):
        _,venues,artists=self.setup_catalogue()
        for ident in IDS:
            for field,value in [
                ("id","go-c-20270205-herouville-faux"),
                ("title","Un autre groupe"),
                ("date","2027-02-06"),
                ("time","20:00"),
                ("artistIds",["fake-group"]),
                ("venueId","le-106-rouen"),
                ("genres",["Rap"]),
                ("officialUrl","https://bigbandcafe.com/concerts/"),
                ("sourceType","organisateur"),
            ]:
                row=make_row(ident)
                row["event"][field]=value
                with self.subTest(id=ident,field=field),self.assertRaises(
                        (ValueError,KeyError)):
                    sync.validate_approval(row,venues,artists,TODAY)
            for idx in (0,1):
                for field,value in [
                    ("url","https://example.com/faux"),
                    ("checkedAt","2026-10-01"),
                    ("checkedFields",["date","artists"]),
                    ("proofType","other-proof"),
                ]:
                    row=make_row(ident)
                    row["officialEvidence"][idx][field]=value
                    with self.subTest(id=ident,idx=idx,field=field),self.assertRaises(
                            (ValueError,KeyError)):
                        sync.validate_approval(row,venues,artists,TODAY)
            row=make_row(ident)
            row["officialEvidence"][0]["checkedFields"].append("startTime")
            with self.assertRaises(ValueError):
                sync.validate_approval(row,venues,artists,TODAY)

    def test_new_artist_identity_cannot_be_renamed(self):
        _,venues,artists=self.setup_catalogue()
        row=make_row("go-c-20270402-herouville-madam")
        row["newArtists"][0]["name"]="Other artist"
        with self.assertRaises(ValueError):
            sync.validate_approval(row,venues,artists,TODAY)

    def test_public_catalogue_has_at_most_one_of_each(self):
        cat,_,_=self.setup_catalogue()
        for ident in IDS:
            rows=[e for e in cat["events"] if e["id"]==ident]
            self.assertLessEqual(len(rows),1)
            if rows:
                s=sync.BBC_NORMANDY_VERIFIED[ident]
                for field in ("title","date","time","venueId","artistIds",
                              "genres","officialUrl"):
                    self.assertEqual(rows[0][field],s[field])
        self.assertEqual(len(cat["events"]),
                         len({e["id"] for e in cat["events"]}))


if __name__=="__main__":
    unittest.main()
