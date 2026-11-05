"""Contrats de publication nominatifs : Le Moloco et Le SEW (février 2027)."""
import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from concerts_cloud_sync import (
    TOURNEE_DU_COEUR_MOLOCO_SEW_SIGNED_20261105 as SIGNED,
    PILOT_VENUES, validate_approval, validate_venue_approval
)
CURRENT = json.loads((ROOT / "docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
TODAY = dt.date(2026, 11, 5)
MOLOCO = "go-c-20270225-audincourt-cachemire-la-phaze-bobs-not-dead"
SEW = "go-c-20270211-morlaix-cachemire-la-phaze-bobs-not-dead"
TOUR = "https://tourneeducoeur.ragetour.com/"
GEO = "https://musitree.fr/concerts/salles/sew-la-manu-morlaix/"

def event_approval(key):
    spec = SIGNED[key]
    return {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": "2026-11-05",
        "event": copy.deepcopy(spec["event"]),
        "newArtists": [],
        "officialEvidence": [{**copy.deepcopy(p), "checkedAt": "2026-11-05"}
                             for p in spec["proofs"]],
    }

def venue_approval():
    return {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": "2026-11-05",
        "venue": copy.deepcopy(PILOT_VENUES["le-sew-morlaix"]["venue"]),
        "officialEvidence": [
            {"url": "https://sew-morlaix.com/infos",
             "proofType": "official-venue-address", "checkedAt": "2026-11-05",
             "checkedFields": ["name", "address", "postalCode", "city"]},
            {"url": GEO, "proofType": "independent-named-venue-geolocation",
             "checkedAt": "2026-11-05",
             "checkedFields": ["venueName", "coordinates"]},
        ],
    }

class TourneeCoeurMolocoSewCloudTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.venues = {v["id"]: v for v in CURRENT["venues"]}
        cls.venues["le-sew-morlaix"] = validate_venue_approval(
            venue_approval(), TODAY)
        cls.artists = {a["id"]: a for a in CURRENT["artists"]}

    def test_double_sources_deux_evenements_une_salle(self):
        self.assertEqual(set(SIGNED), {MOLOCO, SEW})
        self.assertEqual(
            (self.venues["le-sew-morlaix"]["latitude"],
             self.venues["le-sew-morlaix"]["longitude"]),
            (48.58309, -3.83484))
        self.assertEqual(self.venues["le-sew-morlaix"]["geoSource"], GEO)
        for key in (MOLOCO, SEW):
            with self.subTest(key=key):
                r = event_approval(key)
                event, new = validate_approval(r, self.venues, self.artists, TODAY)
                self.assertEqual(event, SIGNED[key]["event"])
                self.assertFalse(new)
                self.assertEqual(event["artistIds"],
                    ["cachemire", "la-phaze", "bobs-not-dead"])
                self.assertEqual(r["officialEvidence"][1]["url"], TOUR)
                public = [x for x in CURRENT["events"] if x["id"] == key]
                self.assertLessEqual(len(public), 1)
                if public:
                    for field in ("id", "title", "date", "time", "artistIds",
                                  "venueId", "genres", "officialUrl", "status"):
                        self.assertEqual(public[0].get(field), event[field])
        self.assertIsNone(SIGNED[MOLOCO]["event"]["time"])
        self.assertEqual(SIGNED[SEW]["event"]["time"], "20:00")

    def test_false_artists_times_sources_and_new_venue_rejected(self):
        for key in (MOLOCO, SEW):
            for title, mutate in [
                ("date", lambda x: x["event"].update(date="2027-02-26")),
                ("artists", lambda x: x["event"]["artistIds"].append("faux-groupe")),
                ("time", lambda x: x["event"].update(time="21:30")),
                ("venue", lambda x: x["event"].update(venueId="rockstore-montpellier")),
                ("source", lambda x: x["officialEvidence"][0].update(url="https://example.org")),
                ("tour", lambda x: x["officialEvidence"][1].update(url="https://example.org")),
                ("lineup", lambda x: x["officialEvidence"][0].update(confirmedArtists=["Autre groupe"])),
                ("review", lambda x: x.update(reviewedBy="automated-official-recheck")),
                ("old", lambda x: x.update(reviewedAt="2026-09-01")),
                ("noProof", lambda x: x["officialEvidence"].pop()),
                ("doorTime", lambda x: x["officialEvidence"][0]["checkedFields"].append("startTime")),
            ]:
                row=event_approval(key)
                mutate(row)
                with self.subTest(key=key, mutation=title), self.assertRaises(
                        (ValueError, KeyError, TypeError)):
                    validate_approval(row, self.venues, self.artists, TODAY)

    def test_geographic_forgery_and_unapproved_artist_excluded(self):
        for name, mutate in [
            ("wrongPoint", lambda x: x["venue"].update(latitude=48.7001)),
            ("wrongAddress", lambda x: x["venue"].update(address="Adresse inventée")),
            ("wrongSource", lambda x: x["officialEvidence"][1].update(url="https://example.org")),
            ("wrongReview", lambda x: x.update(reviewedBy="automatic")),
        ]:
            row = venue_approval()
            mutate(row)
            with self.subTest(name=name), self.assertRaises(
                    (ValueError, KeyError, TypeError)):
                validate_venue_approval(row, TODAY)
        row = event_approval(SEW)
        row["event"]["id"] = "go-c-20270211-morlaix-fausse-affiche"
        with self.assertRaises(ValueError):
            validate_approval(row,self.venues,self.artists,TODAY)

if __name__ == "__main__":
    unittest.main()
