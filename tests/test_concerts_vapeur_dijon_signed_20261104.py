"""Strict La Vapeur Dijon signer: first-party poster + authorized organizer booking.

The 19:30–23:00 Weezevent period does not establish music start.
All data modifications must flow via the approved cloud sync.
"""
import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from concerts_cloud_sync import (
    PILOT_VENUES,VAPEUR_DIJON_SIGNED_20261104,
    validate_approval,validate_venue_approval,
)

DOC=json.loads((ROOT/"docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
DAY=dt.date(2026,11,4)
VENUE="la-vapeur-dijon"
ID="go-c-20270123-dijon-misanthrope-obsession-slapdown"
SPEC=VAPEUR_DIJON_SIGNED_20261104[ID]
GEO=PILOT_VENUES[VENUE]


def venue_approval():
    return {
      "reviewDecision":"approved",
      "reviewedBy":"independent-official-verifier",
      "reviewedAt":"2026-11-04",
      "venue":copy.deepcopy(GEO["venue"]),
      "officialEvidence":[
        {"url":GEO["officialUrl"],"proofType":"official-venue-address",
         "checkedAt":"2026-11-04",
         "checkedFields":["name","address","postalCode","city"]},
        {"url":GEO["locationUrl"],"proofType":"openstreetmap-venue-node",
         "checkedAt":"2026-11-04",
         "checkedFields":["venueName","coordinates"]},
      ],
    }


def approval():
    return {
      "reviewDecision":"approved",
      "reviewedBy":"independent-official-verifier",
      "reviewedAt":"2026-11-04",
      "officialEvidence":[
        {"url":SPEC["officialUrl"],"proofType":"official-organizer-or-venue",
         "checkedAt":"2026-11-04",
         "checkedFields":["artists","date","venue","genre"],
         "officialOrganizer":"Association Phoenix Rising"},
        {"url":SPEC["calendarUrl"],"proofType":"first-party-venue-calendar",
         "checkedAt":"2026-11-04",
         "checkedFields":["artists","dayMonth","venue","genre"],
         "linkedBookingUrl":SPEC["officialUrl"]},
      ],
      "event":{
        "id":ID,"title":SPEC["title"],"date":SPEC["date"],
        "time":None,"artistIds":SPEC["artistIds"],"venueId":VENUE,
        "genres":SPEC["genres"],"status":"confirmed",
        "officialUrl":SPEC["officialUrl"],"sourceType":"organisateur",
      },
      "newArtists":[{"id":aid,"name":SPEC["artistNames"][i]}
                    for i,aid in enumerate(SPEC["artistIds"])
                    if aid in SPEC["newArtistIds"]],
    }


class VapeurSignedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.venues={x["id"]:x for x in DOC["venues"]}
        cls.venues[VENUE]=GEO["venue"]
        new_ids=set(SPEC["newArtistIds"])
        cls.artists={x["id"]:x for x in DOC["artists"] if x["id"] not in new_ids}

    def test_geolocation_is_nominative_and_indicative(self):
        result=validate_venue_approval(venue_approval(),DAY)
        self.assertEqual((result["latitude"],result["longitude"]),
                         (47.34569,5.05964))
        self.assertEqual((result["city"],result["department"]),("Dijon","21"))
        self.assertIn("indicative",result["geoPrecision"])
        self.assertIn("pas son entrée",result["geoPrecision"])
        self.assertEqual(result["geoSource"],"https://mapcarta.com/fr/N3474725036")

    def test_one_event_two_sources_and_no_inferred_time(self):
        self.assertEqual(len(VAPEUR_DIJON_SIGNED_20261104),1)
        event,added=validate_approval(approval(),self.venues,self.artists,DAY)
        self.assertEqual(event["date"],"2027-01-23")
        self.assertEqual(event["title"],"Misanthrope + Obsession + Slapdown")
        self.assertEqual(event["artistIds"],["misanthrope","obsession","slapdown"])
        self.assertEqual(set(added),{"obsession","slapdown"})
        self.assertIsNone(event["time"])
        for previous in DOC["events"]:
            if (previous["id"] != event["id"] and
                    previous["date"] == event["date"] and
                    previous["venueId"] == VENUE):
                self.assertFalse(set(previous["artistIds"]) & set(event["artistIds"]))

    def test_refuses_fake_venue_location_and_unverified_event(self):
        for label,fix in (
            ("wrong-pin", lambda r:r["venue"].update(longitude=5.2)),
            ("wrong-address",lambda r:r["venue"].update(address="42 fausse adresse")),
            ("missing-evidence",lambda r:r["officialEvidence"].pop()),
            ("new-source",lambda r:r["officialEvidence"][1].update(url="https://example.org")),
        ):
            row=venue_approval();fix(row)
            with self.subTest(label=label),self.assertRaises(ValueError):
                validate_venue_approval(row,DAY)
        for label,fix in (
            ("fake-date",lambda r:r["event"].update(date="2027-01-24")),
            ("fake-start",lambda r:r["event"].update(time="19:30")),
            ("wrong-bill",lambda r:r["event"].update(title="Artistes inventés")),
            ("wrong-venue",lambda r:r["event"].update(venueId="rockstore-montpellier")),
            ("wrong-artist",lambda r:r["newArtists"][0].update(name="Fake")),
            ("changed-organizer",lambda r:r["officialEvidence"][0].update(officialOrganizer="Other")),
            ("not-first-party",lambda r:r["officialEvidence"][1].update(url="https://example.org")),
            ("no-booking-link",lambda r:r["officialEvidence"][1].pop("linkedBookingUrl")),
            ("year-from-calendar",lambda r:r["officialEvidence"][1]["checkedFields"].append("date")),
            ("missing-ticket",lambda r:r["officialEvidence"].pop(0)),
            ("fake-event-id",lambda r:r["event"].update(id="go-c-20270123-dijon-fake")),
        ):
            row=approval();fix(row)
            with self.subTest(label=label),self.assertRaises(ValueError):
                validate_approval(row,self.venues,self.artists,DAY)


if __name__=="__main__":
    unittest.main()
