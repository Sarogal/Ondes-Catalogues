"""La CLEF et Bel Air : signatures publiques de deux concerts, deux salles."""
import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from concerts_cloud_sync import (
    TOURNEE_DU_COEUR_CLEF_BELAIR_SIGNED_20261105 as SIGNED,
    TOURNEE_DU_COEUR_CLEF_BELAIR_VENUES_20261105 as GEO,
    PILOT_VENUES, validate_approval, validate_venue_approval
)
TODAY=dt.date(2026,11,5)
DOC=json.loads((ROOT/"docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
CLEF="go-c-20270129-saint-germain-en-laye-cachemire-la-phaze-bobs-not-dead"
BEL_AIR="go-c-20270212-saint-aubin-du-cormier-cachemire-la-phaze-bobs-not-dead"
SOURCES={
 "la-clef-saint-germain-en-laye":(
   "https://laclef.asso.fr/infos-pratiques/comment-venir/",
   "https://musitree.fr/concerts/salles/la-clef-saint-germain-en-laye-saint-germain-en-laye/",
   "independent-named-venue-geolocation",(48.89409,2.08842)),
 "espace-bel-air-saint-aubin-du-cormier":(
   "https://espacebelair.net/info-pratiques/",
   "https://mapcarta.com/fr/W117002146","openstreetmap-venue-way",
   (48.25787,-1.38968)),
}

def signed_venue(ident):
    row=GEO[ident]
    a,b,typ,coords=SOURCES[ident]
    assert row["officialUrl"]==a and row["locationUrl"]==b
    assert row["locationProofType"]==typ
    v=row["venue"]
    assert (v["latitude"],v["longitude"])==coords
    return {
        "reviewDecision":"approved","reviewedBy":"independent-official-verifier",
        "reviewedAt":"2026-11-05","venue":copy.deepcopy(v),
        "officialEvidence":[
           {"url":a,"proofType":"official-venue-address",
            "checkedAt":"2026-11-05",
            "checkedFields":["name","address","postalCode","city"]},
           {"url":b,"proofType":typ,
            "checkedAt":"2026-11-05",
            "checkedFields":["venueName","coordinates"]}]}

def signed_event(ident):
    row=SIGNED[ident]
    return {
        "reviewDecision":"approved","reviewedBy":"independent-official-verifier",
        "reviewedAt":"2026-11-05","event":copy.deepcopy(row["event"]),
        "newArtists":[],
        "officialEvidence":[{**copy.deepcopy(p),"checkedAt":"2026-11-05"}
                            for p in row["proofs"]]}

class SignedClefBelAirTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.venues={v["id"]:v for v in DOC["venues"]}
        for k in SOURCES:
            cls.venues[k]=validate_venue_approval(signed_venue(k),TODAY)
        cls.artists={a["id"]:a for a in DOC["artists"]}

    def test_positive_signature_and_catalog_integrity(self):
        self.assertEqual(set(SIGNED),{CLEF,BEL_AIR})
        self.assertEqual(set(GEO),set(SOURCES))
        for key in SOURCES:
            self.assertEqual(PILOT_VENUES[key],GEO[key])
            self.assertEqual(self.venues[key]["geoSource"],SOURCES[key][1])
        for ident in (CLEF,BEL_AIR):
            with self.subTest(event=ident):
                expected=SIGNED[ident]["event"]
                row=signed_event(ident)
                e,new=validate_approval(row,self.venues,self.artists,TODAY)
                self.assertEqual(e,expected)
                self.assertEqual(new,{})
                self.assertEqual(e["time"],"20:30")
                self.assertEqual(e["artistIds"],
                    ["cachemire","la-phaze","bobs-not-dead"])
                present=[x for x in DOC["events"] if x["id"]==ident]
                self.assertLessEqual(len(present),1)
                if present:
                    for fld in ("date","time","artistIds","venueId","title",
                                "officialUrl","genres","status"):
                        self.assertEqual(present[0][fld],e[fld])

    def test_event_forgery_fails(self):
        for ident in (CLEF,BEL_AIR):
            for name,fn in [
                ("date",lambda x:x["event"].update(date="2027-02-27")),
                ("hour",lambda x:x["event"].update(time="19:30")),
                ("venue",lambda x:x["event"].update(venueId="fake")),
                ("artists",lambda x:x["event"]["artistIds"].append("fake")),
                ("source",lambda x:x["officialEvidence"][0].update(url="https://fake.org")),
                ("support",lambda x:x["officialEvidence"][1].update(url="https://fake.org")),
                ("lineup",lambda x:x["officialEvidence"][0].update(confirmedArtists=["Fake"])),
                ("start",lambda x:x["officialEvidence"][0].update(concertStartTimeConfirmed="18:00")),
                ("old",lambda x:x.update(reviewedAt="2026-05-01")),
                ("noProof",lambda x:x["officialEvidence"].pop()),
            ]:
                row=signed_event(ident);fn(row)
                with self.subTest(event=ident,what=name),self.assertRaises(ValueError):
                    validate_approval(row,self.venues,self.artists,TODAY)

    def test_venue_forgery_fails(self):
        for ident in SOURCES:
            for name,fn in [
                ("lat",lambda x:x["venue"].update(latitude=0.0)),
                ("city",lambda x:x["venue"].update(city="Paris")),
                ("url",lambda x:x["officialEvidence"][1].update(url="https://fake.org")),
                ("reviewer",lambda x:x.update(reviewedBy="automated-official-recheck")),
            ]:
                row=signed_venue(ident);fn(row)
                with self.subTest(venue=ident,what=name),self.assertRaises(ValueError):
                    validate_venue_approval(row,TODAY)

    def test_unapproved_event_in_protected_venue_rejected(self):
        for ident in SOURCES:
            row=signed_event(CLEF)
            row["event"]["id"]="go-c-20270129-fake-lineup"
            row["event"]["venueId"]=ident
            with self.subTest(venue=ident),self.assertRaises(ValueError):
                validate_approval(row,self.venues,self.artists,TODAY)

if __name__=="__main__":
    unittest.main()
