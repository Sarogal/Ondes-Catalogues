"""Public-side fail-closed gate for the single first-party Atabal pilot."""
import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from concerts_cloud_sync import validate_approval

URL=("https://www.atabal-biarritz.fr/agenda/concerts/"
     "peter-hook-the-light-a-joy-division-celebration-jeudi-08-avril-2027/")
DAY=dt.date(2026,11,6)


def row():
    return {
        "reviewDecision":"approved","reviewedBy":"automated-official-recheck",
        "reviewedAt":"2026-11-06",
        "officialEvidence":[{
            "url":URL,
            "proofType":"official-organizer-or-venue",
            "checkedAt":"2026-11-06",
            "checkedFields":["artists","date","venue","genre"],
            "officialArtistNames":["PETER HOOK & THE LIGHT"]
        }],
        "event":{
            "id":"go-c-20270408-biarritz-peter-hook-and-the-light",
            "title":"PETER HOOK & THE LIGHT","date":"2027-04-08",
            "time":None,"artistIds":["peter-hook-and-the-light"],
            "venueId":"atabal-biarritz","genres":["Post Punk"],
            "status":"confirmed","officialUrl":URL,
            "sourceType":"salle","organizer":"Atabal"
        },
        "newArtists":[]
    }


class AtabalPublicGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data=json.loads((ROOT/"docs/grossesondes/concerts.json")
                        .read_text(encoding="utf-8"))
        cls.venues={x["id"]:x for x in data["venues"]}
        cls.artists={x["id"]:x for x in data["artists"]}

    def test_precise_official_approval_only(self):
        event,created=validate_approval(row(),self.venues,self.artists,DAY)
        self.assertEqual(event["id"],row()["event"]["id"])
        self.assertEqual(event["artistIds"],["peter-hook-and-the-light"])
        self.assertIsNone(event["time"])
        self.assertEqual(created,[])

    def test_narrow_review_rejects_mutations(self):
        for mutant in (
            "url-domain","url-query","url-agenda","event-id","other-title",
            "date","start-time","support","new-artist","genre","venue",
            "organizer","status","source","evidence-url","evidence-fields",
            "evidence-names","second-proof","stale","wrong-reviewer",
            "different-artist"
        ):
            approval=copy.deepcopy(row())
            event=approval["event"]; proof=approval["officialEvidence"][0]
            if mutant=="url-domain":
                event["officialUrl"]=event["officialUrl"].replace(
                    "www.atabal-biarritz.fr","fake-atabal.example")
                proof["url"]=event["officialUrl"]
            elif mutant=="url-query":
                event["officialUrl"]+="?event=other"
                proof["url"]=event["officialUrl"]
            elif mutant=="url-agenda":
                event["officialUrl"]="https://www.atabal-biarritz.fr/agenda/concerts/"
                proof["url"]=event["officialUrl"]
            elif mutant=="event-id":
                event["id"]="go-c-20270408-biarritz-other"
            elif mutant=="other-title":
                event["title"]="PETER HOOK & THE LIGHT + GUEST"
            elif mutant=="date":
                event["date"]="2027-04-09"
            elif mutant=="start-time":
                event["time"]="19:30"
            elif mutant=="support":
                event["artistIds"].append("new-artist")
            elif mutant=="new-artist":
                approval["newArtists"].append({"id":"new-artist","name":"New Artist"})
            elif mutant=="genre":
                event["genres"]=["Reggae"]
            elif mutant=="venue":
                event["venueId"]="le-molotov-marseille"
            elif mutant=="organizer":
                event["organizer"]="Unknown"
            elif mutant=="status":
                event["status"]="cancelled"
            elif mutant=="source":
                event["sourceType"]="aggregator"
            elif mutant=="evidence-url":
                proof["url"]="https://example.org/"
            elif mutant=="evidence-fields":
                proof["checkedFields"]=["artists","date","venue"]
            elif mutant=="evidence-names":
                proof["officialArtistNames"]=["Unrelated Act"]
            elif mutant=="second-proof":
                approval["officialEvidence"].append(copy.deepcopy(proof))
            elif mutant=="stale":
                approval["reviewedAt"]="2026-10-01"
                proof["checkedAt"]="2026-10-01"
            elif mutant=="wrong-reviewer":
                approval["reviewedBy"]="human"
            elif mutant=="different-artist":
                event["artistIds"]=["other"]
            with self.subTest(mutant=mutant),self.assertRaises(
                    (ValueError,KeyError)):
                validate_approval(approval,self.venues,self.artists,DAY)

    def test_known_artist_must_not_be_replaced(self):
        fake=dict(self.artists)
        fake["peter-hook-and-the-light"]={
            "id":"peter-hook-and-the-light","name":"A different group"}
        with self.assertRaisesRegex(ValueError,"identité"):
            validate_approval(row(),self.venues,fake,DAY)

    def test_only_named_atabal_venue_can_be_auto_reviewed(self):
        item=copy.deepcopy(row())
        item["event"]["venueId"]="atabal-biarritz-other"
        with self.assertRaises(ValueError):
            validate_approval(item,self.venues,self.artists,DAY)


if __name__=="__main__":
    unittest.main()
