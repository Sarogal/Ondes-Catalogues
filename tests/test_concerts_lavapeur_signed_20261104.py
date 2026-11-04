"""Dijon / La Vapeur: exact first-party date + distinct venue genre proof.
The official venue calendar alone cannot establish the year 2027; no guessed
guest artist, musical start, GPS or direct JSON mutation is authorized.
"""
import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from concerts_cloud_sync import (
    PILOT_VENUES, LA_VAPEUR_SKIP_SIGNED_20261104,
    validate_venue_approval, validate_approval
)
PUBLIC=json.loads((ROOT/"docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
DAY=dt.date(2026,11,4)
SPEC=LA_VAPEUR_SKIP_SIGNED_20261104
VENUE_ID="la-vapeur-dijon"


def signed_venue():
    spec=PILOT_VENUES[VENUE_ID]
    return {
        "reviewDecision":"approved",
        "reviewedBy":"independent-official-verifier",
        "reviewedAt":"2026-11-04",
        "venue":copy.deepcopy(spec["venue"]),
        "officialEvidence":[
            {"url":spec["officialUrl"],"proofType":"official-venue-address",
             "checkedAt":"2026-11-04","checkedFields":["name","address","postalCode","city"]},
            {"url":spec["locationUrl"],"proofType":"openstreetmap-venue-node",
             "checkedAt":"2026-11-04","checkedFields":["venueName","coordinates"]},
        ],
    }


def signed_event():
    return {
        "reviewDecision":"approved",
        "reviewedBy":"independent-official-verifier",
        "reviewedAt":"2026-11-04",
        "officialEvidence":[
            {"url":SPEC["officialUrl"],"proofType":"official-organizer-or-venue",
             "checkedAt":"2026-11-04","checkedFields":["artists","date","venue"]},
            {"url":SPEC["calendarUrl"],"proofType":"first-party-venue-calendar",
             "checkedAt":"2026-11-04","checkedFields":["artists","venue","genre","dayMonth"]},
        ],
        "event":{k:copy.deepcopy(SPEC[k]) for k in
                 ("id","title","date","time","artistIds","venueId","genres","officialUrl")}
                 | {"status":"confirmed","sourceType":"organisateur"},
        "newArtists":[],
    }


class LaVapeurDijonSignedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.venues={v["id"]:v for v in PUBLIC["venues"]}
        cls.venues[VENUE_ID]=PILOT_VENUES[VENUE_ID]["venue"]
        cls.artists={a["id"]:a for a in PUBLIC["artists"]}

    def test_first_party_venue_identity_and_indicative_osm_point(self):
        venue=validate_venue_approval(signed_venue(),DAY)
        self.assertEqual((venue["name"],venue["city"],venue["department"]),
                         ("La Vapeur","Dijon","21"))
        self.assertEqual((venue["address"],venue["postalCode"]),
                         ("42 avenue de Stalingrad","21000"))
        self.assertEqual((venue["latitude"],venue["longitude"]),(47.34569,5.05964))
        self.assertIn("indicative",venue["geoPrecision"])
        self.assertIn("pas son entrée",venue["geoPrecision"])
        self.assertEqual(venue["geoSource"],"https://mapcarta.com/fr/N3474725036")

    def test_exact_named_dijon_show(self):
        evt,added=validate_approval(signed_event(),self.venues,self.artists,DAY)
        self.assertEqual(evt["date"],"2027-02-11")
        self.assertEqual(evt["title"],"Skip The Use")
        self.assertEqual(evt["venueId"],VENUE_ID)
        self.assertEqual(evt["genres"],["Rock"])
        self.assertEqual(evt["artistIds"],["skip-the-use"])
        self.assertIsNone(evt["time"])
        self.assertEqual(added,{})
        exists={e["id"]:e for e in PUBLIC["events"]}
        if evt["id"] in exists:
            self.assertTrue(all(exists[evt["id"]][k]==evt[k] for k in
                                ("id","title","date","venueId","genres",
                                 "artistIds","officialUrl","status")))

    def test_forged_year_location_proofs_and_start_are_rejected(self):
        variants=[
            ("changed-date",lambda r:r["event"].update(date="2027-02-12")),
            ("wrong-venue",lambda r:r["event"].update(venueId="le-106-rouen")),
            ("invented-guest",lambda r:r["event"].update(title="Skip The Use + Guest")),
            ("false-start",lambda r:r["event"].update(time="20:00")),
            ("wrong-artist",lambda r:r["event"].update(artistIds=["mdns"])),
            ("wrong-official-url",lambda r:r["event"].update(officialUrl="https://example.org/show")),
            ("no-venue-proof",lambda r:r["officialEvidence"].pop()),
            ("pretend-venue-proves-year",lambda r:r["officialEvidence"][1]["checkedFields"].append("date")),
            ("pretend-concert-time",lambda r:r["officialEvidence"][0]["checkedFields"].append("concertStartTime")),
            ("false-venue-genre",lambda r:r["event"].update(genres=["Metal"])),
            ("not-approved",lambda r:r.update(reviewDecision="candidate")),
        ]
        for label,mutate in variants:
            with self.subTest(label=label),self.assertRaises(ValueError):
                row=signed_event()
                mutate(row)
                validate_approval(row,self.venues,self.artists,DAY)

    def test_venue_pin_and_proof_not_replacable(self):
        for label,mutate in (
            ("gps",lambda r:r["venue"].update(latitude=45.4)),
            ("host",lambda r:r["officialEvidence"][0].update(url="https://example.org")),
            ("missing-node",lambda r:r["officialEvidence"].pop()),
        ):
            with self.subTest(label=label),self.assertRaises(ValueError):
                row=signed_venue()
                mutate(row)
                validate_venue_approval(row,DAY)


if __name__=="__main__":
    unittest.main()
