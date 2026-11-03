"""Antipode Rennes: 3 official first-party bills, exact doors/start and independent GPS proof."""
import copy
import datetime as dt
import json
from pathlib import Path
import unittest
from scripts import concerts_cloud_sync as sync

ROOT=Path(__file__).resolve().parents[1]
DAY=dt.date(2026,11,3)
IDS=tuple(sync.ANTIPODE_RENNES_VERIFIED)

def event_row(ident):
    s=sync.ANTIPODE_RENNES_VERIFIED[ident]
    return {
        "reviewDecision":"approved","reviewedBy":"independent-official-verifier",
        "reviewedAt":"2026-11-03",
        "officialEvidence":[
            {"url":s["officialUrl"],"proofType":"official-organizer-or-venue",
             "checkedAt":"2026-11-03","checkedFields":[
                "artists","date","venue","genre","concertStartTime","doorTime"],
             "concertStartTimeConfirmed":"20:30","doorTimeConfirmed":"20:00",
             "soldOutOnDetailAtReview":s["soldOut"]},
            {"url":s["calendarUrl"],"proofType":"first-party-venue-calendar",
             "checkedAt":"2026-11-03","checkedFields":["artists","date","venue"]},
        ],
        "event":{key:copy.deepcopy(s[key]) for key in (
            "title","date","time","venueId","artistIds","genres","status",
            "organizer","officialUrl")},
        "newArtists":[
            {"id":aid,"name":s["artistNames"][i]}
            for i,aid in enumerate(s["artistIds"]) if aid in s["newArtistIds"]]
    } | {"event":{**{key:copy.deepcopy(s[key]) for key in (
            "title","date","time","venueId","artistIds","genres","status",
            "organizer","officialUrl")},
            "id":ident,"sourceType":"salle"}}

class AntipodeRennesOfficialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat=json.loads((ROOT/"docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
        cls.ref=json.loads((ROOT/"docs/grossesondes/concerts-reference.json").read_text(encoding="utf-8"))
        cls.venues={v["id"]:v for v in cls.cat["venues"]}
        new={aid for spec in sync.ANTIPODE_RENNES_VERIFIED.values()
             for aid in spec["newArtistIds"]}
        cls.artists={a["id"]:a for a in cls.cat["artists"] if a["id"] not in new}

    def test_three_exact_first_party_shows_with_explicit_start_and_door(self):
        self.assertEqual(len(IDS),4)
        discovered=set()
        for ident in IDS:
            with self.subTest(ident=ident):
                spec=sync.ANTIPODE_RENNES_VERIFIED[ident]
                event,new=sync.validate_approval(
                    event_row(ident),self.venues,self.artists,DAY)
                self.assertEqual(event["time"],"20:30")
                self.assertEqual(event["venueId"],"antipode-rennes")
                self.assertEqual(event["status"],"confirmed")
                self.assertEqual(list(new),spec["newArtistIds"])
                discovered.update(new)
                prior=[e for e in self.cat["events"] if e["id"]==ident]
                self.assertLessEqual(len(prior),1)
        self.assertEqual(discovered,
            {"girls-in-hawaii","chaton-laveur","altin-gun","diiv"})
        self.assertEqual(sync.ANTIPODE_RENNES_VERIFIED[
            "go-c-20261212-rennes-girls-in-hawaii-chaton-laveur"]["soldOut"],True)

    def test_rejects_changes_to_show_genre_venue_lineup_organizer_and_clock(self):
        for ident in IDS:
            for field,value in (
                ("id","go-c-20270909-rennes-unknown"),
                ("title","Invented Band"),("date","2027-05-01"),
                ("time","20:00"),("venueId","l-etage-rennes"),
                ("artistIds",["bogus"]),("genres",["Techno"]),
                ("organizer","Unknown Organizer"),("status","cancelled"),
                ("officialUrl","https://antipode-rennes.fr/agenda/false-concert")
            ):
                with self.subTest(ident=ident,field=field):
                    row=event_row(ident);row["event"][field]=value
                    with self.assertRaises((ValueError,KeyError)):
                        sync.validate_approval(row,self.venues,self.artists,DAY)
            for mutation in ("doors","start","soldout","calendar","calendarClock",
                             "reviewer","newArtist","wrongProofDate"):
                with self.subTest(ident=ident,mutation=mutation):
                    row=event_row(ident)
                    if mutation=="doors":
                        row["officialEvidence"][0]["doorTimeConfirmed"]="20:30"
                    elif mutation=="start":
                        row["officialEvidence"][0]["concertStartTimeConfirmed"]="20:00"
                    elif mutation=="soldout":
                        row["officialEvidence"][0]["soldOutOnDetailAtReview"]=not (
                            row["officialEvidence"][0]["soldOutOnDetailAtReview"])
                    elif mutation=="calendar":
                        row["officialEvidence"][1]["url"]="https://example.net/agenda"
                    elif mutation=="calendarClock":
                        row["officialEvidence"][1]["checkedFields"].append("startTime")
                    elif mutation=="reviewer":
                        row["reviewedBy"]="automated-official-recheck"
                    elif mutation=="newArtist":
                        row["newArtists"].append({"id":"impostor","name":"Impostor"})
                    elif mutation=="wrongProofDate":
                        row["officialEvidence"][0]["checkedAt"]="2026-11-02"
                    with self.assertRaises((ValueError,KeyError)):
                        sync.validate_approval(row,self.venues,self.artists,DAY)

    def test_antipode_geo_correction_is_exact_and_does_not_shift_other_venues(self):
        spec=sync.NEW_REFERENCE_GEO_SOURCES["antipode-rennes"]
        self.assertEqual(spec["patch"]["latitude"],48.09823)
        self.assertEqual(spec["patch"]["longitude"],-1.70464)
        self.assertEqual(spec["patch"]["address"],"75 avenue Jules Maniez")
        before=self.ref["venues"]
        after=sync.corrected_reference_venues(self.ref,extra_venues=("antipode-rennes",))
        changed=[(a,b) for a,b in zip(before,after) if a!=b]
        # The immutable Ferrailleur baseline pin is independently fixed by existing rules.
        self.assertEqual({b["id"] for a,b in changed},
                         {"antipode-rennes","le-ferrailleur-nantes"})
        base=next(v for v in before if v["id"]=="antipode-rennes")
        fixed=next(v for v in after if v["id"]=="antipode-rennes")
        self.assertEqual(base["address"],"Adresse exacte à vérifier")
        self.assertEqual(fixed["geoSource"],"https://mapcarta.com/fr/W943632490")
        for k,val in spec["patch"].items():
            self.assertEqual(fixed[k],val)
        forged=copy.deepcopy(after)
        next(v for v in forged if v["id"]=="antipode-rennes")["latitude"]+=1
        cand=copy.deepcopy(self.ref);cand["venues"]=forged
        with self.assertRaises(ValueError):
            sync.protect_reference(self.ref,cand)

if __name__=="__main__":
    unittest.main()
