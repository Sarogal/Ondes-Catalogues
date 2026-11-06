"""Two exact Echonova shows and independently located Saint-Avé room.

Protect existing 19 historic venue approvals and all prior event approvals.
No inferred guest, false start clock or direct catalogue publication.
"""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOC = json.loads((ROOT / "approved.json").read_text(encoding="utf-8"))
VENUE_ID = "l-echonova-saint-ave"
EVENTS = {
    "go-c-20261203-saint-ave-eiffel":
      ("2026-12-03", "Eiffel", "20:30", ["eiffel"]),
    "go-c-20270206-saint-ave-meteora-systemize":
      ("2027-02-06", "Meteora + Systemize", None,
       ["meteora-tribute", "systemize"]),
}


class EchonovaSignedPrivateTests(unittest.TestCase):
    def test_venue_coordinates_are_indicative_and_proof_by_source(self):
        approved = DOC["venueApprovals"]
        venues = [r["venue"]["id"] for r in approved]
        self.assertEqual(len(venues), len(set(venues)))
        # Le socle de 20 salles signées doit être conservé même si la veille
        # nationale intègre de nouveaux lieux contrôlés.
        self.assertGreaterEqual(len(venues), 20)
        self.assertIn(VENUE_ID, venues)
        row = next(r for r in approved if r["venue"]["id"] == VENUE_ID)
        self.assertEqual(row["reviewDecision"], "approved")
        self.assertEqual(row["reviewedBy"], "independent-official-verifier")
        self.assertEqual(row["reviewedAt"], "2026-11-04")
        venue = row["venue"]
        self.assertEqual((venue["name"], venue["city"], venue["department"]),
                         ("L'Echonova", "Saint-Avé", "56"))
        self.assertEqual((venue["address"], venue["postalCode"]),
                         ("1 rue Léon Griffon", "56890"))
        self.assertEqual((venue["latitude"], venue["longitude"]),
                         (47.67468, -2.74379))
        self.assertIn("indicatif", venue["geoPrecision"])
        self.assertEqual(venue["geoSource"],
                         "https://www.fandefest.com/salle/l-echonova-saint-ave")
        first, independent = row["officialEvidence"]
        self.assertEqual(first["url"], "https://lechonova.com/infos-pratiques/")
        self.assertEqual(first["proofType"], "official-venue-address")
        self.assertEqual(set(first["checkedFields"]),
                         {"name", "address", "postalCode", "city"})
        self.assertEqual(independent["url"], venue["geoSource"])
        self.assertEqual(independent["proofType"],
                         "independent-venue-coordinate-listing")
        self.assertEqual(set(independent["checkedFields"]),
                         {"venueName", "coordinates"})
        self.assertTrue(all(p["checkedAt"] == "2026-11-04"
                            for p in row["officialEvidence"]))

    def test_two_events_have_stable_identifiers_and_distinct_proofs(self):
        rows = DOC["approvals"]
        ids = [row["event"]["id"] for row in rows]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 183)
        self.assertTrue(set(EVENTS).issubset(ids))
        for ident, (date, title, time, artists) in EVENTS.items():
            with self.subTest(ident=ident):
                row = next(a for a in rows if a["event"]["id"] == ident)
                e = row["event"]
                self.assertEqual((e["date"], e["title"], e["time"],
                                  e["artistIds"], e["venueId"], e["status"],
                                  e["sourceType"]),
                                 (date,title,time,artists,VENUE_ID,
                                  "confirmed","salle"))
                self.assertEqual(row["reviewDecision"], "approved")
                self.assertEqual(row["reviewedBy"],
                                 "independent-official-verifier")
                self.assertEqual(row["reviewedAt"], "2026-11-04")
                primary, ticket = row["officialEvidence"]
                self.assertEqual(primary["url"], e["officialUrl"])
                self.assertEqual(primary["proofType"],
                                 "official-organizer-or-venue")
                self.assertEqual(ticket["url"],
                    "https://www.fnacspectacles.com/venue/lechonova-81096/")
                self.assertEqual(ticket["proofType"],
                                 "independent-ticketing-venue-list")
                self.assertEqual(ticket["checkedFields"],
                                 ["artists", "date", "venue"])
                self.assertEqual(primary["checkedFields"],
                    ["artists","date","venue","genre"] +
                    (["concertStartTime"] if time else []))
                self.assertTrue(all(p["checkedAt"] == "2026-11-04"
                                    for p in row["officialEvidence"]))
                self.assertNotIn("guest", title.lower())
                self.assertNotIn("première partie", title.lower())
                new = {a["id"] for a in row["newArtists"]}
                self.assertEqual(new,set(artists))
                self.assertNotEqual(primary["url"],ticket["url"])

    def test_history_untouched_and_no_same_artist_twice_at_same_venue_and_day(self):
        ids = {row["event"]["id"] for row in DOC["approvals"]}
        historical = {
            "go-c-20261106-limoges-7weeks",
            "go-c-20261127-limoges-gwendoline",
            "go-c-20270219-colmar-colour-haze",
            "go-c-20261211-colmar-wake-the-dead",
            "go-c-20270130-colmar-easy-cure",
        }
        self.assertTrue(historical.issubset(ids))
        observed = set()
        for row in DOC["approvals"]:
            e = row["event"]
            for aid in e["artistIds"]:
                key = (e["date"], e["venueId"], aid)
                self.assertNotIn(key,observed)
                observed.add(key)


if __name__ == "__main__":
    unittest.main()
