"""Verrou de cinq concerts de tournée officiellement recoupés, sans réseau."""
import copy
import datetime as dt
import sys
import unittest
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from concerts_cloud_sync import (
    TOUR_FIVE_SIGNED_20261105,
    NEW_REFERENCE_GEO_SOURCES,
    validate_approval,
)

CAT = json.loads((ROOT / "docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
VENUES = {x["id"]: x for x in CAT["venues"]}
ARTISTS = {x["id"]: x for x in CAT["artists"]}
TODAY = dt.date(2026, 11, 5)

def signed(event_id):
    spec = TOUR_FIVE_SIGNED_20261105[event_id]
    return {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": "2026-11-05",
        "officialEvidence": [
            dict(p, checkedAt="2026-11-05")
            for p in copy.deepcopy(spec["proofs"])
        ],
        "event": copy.deepcopy(spec["event"]),
        "newArtists": [],
    }


class FiveTourOfficialSignaturesTests(unittest.TestCase):
    def test_cinq_affiches_signees_sans_artistes_ajoutes(self):
        self.assertEqual(len(TOUR_FIVE_SIGNED_20261105), 5)
        for ident in TOUR_FIVE_SIGNED_20261105:
            with self.subTest(id=ident):
                row = signed(ident)
                ev, new = validate_approval(row, VENUES, ARTISTS, TODAY)
                self.assertEqual(ev["id"], ident)
                self.assertEqual(new, {})
                self.assertEqual(ev["artistIds"], row["event"]["artistIds"])
                self.assertEqual(ev["venueId"], row["event"]["venueId"])
                self.assertTrue(ev.get("time") is None or (
                    ident == "go-c-20270204-villeurbanne-revnoir-ice-sealed-eyes"
                    and ev["time"] == "20:00"))

    def test_mutations_critiques_bloquees_pour_chacune(self):
        scenarios = {
            "date": lambda a: a["event"].update(date="2027-12-31"),
            "venue": lambda a: a["event"].update(venueId="la-laiterie-strasbourg"),
            "artist": lambda a: a["event"].update(artistIds=["unknown-artist"]),
            "genre": lambda a: a["event"].update(genres=["Folk"]),
            "title": lambda a: a["event"].update(title="Guest inconnu"),
            "concert_start": lambda a: a["event"].update(time="19:30"),
            "changed_url": lambda a: a["event"].update(officialUrl="https://example.com/faux"),
            "no_second_proof": lambda a: a["officialEvidence"].pop(),
            "forged_proof": lambda a: a["officialEvidence"][0].update(url="https://example.com/faux"),
            "invented_field": lambda a: a["officialEvidence"][0]["checkedFields"].append("unverified"),
            "unapproved": lambda a: a.update(reviewDecision="pending"),
            "not_independent": lambda a: a.update(reviewedBy="automated-official-recheck"),
        }
        for ident in TOUR_FIVE_SIGNED_20261105:
            for label, change in scenarios.items():
                with self.subTest(id=ident, scenario=label):
                    row = signed(ident)
                    change(row)
                    with self.assertRaises((ValueError, KeyError)):
                        validate_approval(row, VENUES, ARTISTS, TODAY)

    def test_url_reservee_interdit_la_reaffectation(self):
        for ident in TOUR_FIVE_SIGNED_20261105:
            row = signed(ident)
            row["event"]["id"] = "go-c-20270101-concert-fictif"
            with self.subTest(id=ident):
                with self.assertRaises((ValueError, KeyError)):
                    validate_approval(row, VENUES, ARTISTS, TODAY)

    def test_exactement_trois_nouvelles_coordonnees_protegees(self):
        expected = {
            "zenith-paris-la-villette-paris": (48.89418, 2.39317),
            "le-transbordeur-villeurbanne": (45.78401, 4.86079),
            "la-belle-electrique-grenoble": (45.18718, 5.70419),
        }
        self.assertEqual(len(NEW_REFERENCE_GEO_SOURCES), 8)
        for ident, location in expected.items():
            with self.subTest(id=ident):
                spec = NEW_REFERENCE_GEO_SOURCES[ident]
                self.assertEqual(
                    (spec["patch"]["latitude"], spec["patch"]["longitude"]), location)
                self.assertEqual(spec["checkedAt"], "2026-11-05")
                self.assertEqual(spec["geoProof"], "openstreetmap-venue-way")
                self.assertEqual(spec["officialProof"], "official-venue-address")
                self.assertEqual(len(spec["expectedOriginal"]), 6)
                self.assertEqual(spec["geoFields"], ["venueName", "coordinates"])


if __name__ == "__main__":
    unittest.main()
