"""Named multi-artist La Laiterie regression tests against the REAL publisher."""
import copy
import datetime as dt
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "automation" / "concerts"))

import concerts_cloud_sync as publisher
import laiterie_adapter as adapter
import laiterie_official_recheck as verifier
import official_recheck as engine
from test_laiterie_official_recheck import PAGE, URL, SOURCE, TODAY, catalogue

# Both names appear in the actual event header and the individual Artistes
# section. Recommendation headings below the section are intentionally ignored.
TWO = PAGE.replace(
    "<h1>PETER HOOK & THE LIGHT</h1>",
    "<h1>PETER HOOK & THE LIGHT</h1><h2>+ 7WEEKS</h2>",
).replace(
    "<h2>On vous recommande</h2>",
    "<h2>7WEEKS</h2><h2>On vous recommande</h2>",
)


def two_catalogue():
    result = catalogue()
    result["artists"].append({"id": "7weeks", "name": "7Weeks", "aliases": []})
    return result


def candidate(page=TWO):
    row = adapter.details(page, URL, SOURCE, TODAY.isoformat())
    row.update({"reviewBucket": "genre_tag_review",
                "possibleExistingConcert": False})
    return row


def signed():
    return verifier.verify(candidate(), TWO, two_catalogue(), TODAY)


def publisher_check(row):
    c = two_catalogue()
    venues = {v["id"]: v for v in c["venues"]}
    artists = {a["id"]: a for a in c["artists"]}
    return publisher.validate_approval(row, venues, artists, TODAY)


class LaiterieMultiTests(unittest.TestCase):
    def test_two_exactly_named_existing_artists_pass_independent_publisher(self):
        row = signed()
        self.assertEqual(row["event"]["artistIds"],
                         ["peter-hook-and-the-light", "7weeks"])
        self.assertEqual(row["event"]["title"],
                         "Peter Hook and The Light + 7Weeks")
        self.assertIsNone(row["event"]["time"])
        proof = row["officialEvidence"][0]
        self.assertEqual(proof["officialArtistNames"],
                         ["Peter Hook and The Light", "7Weeks"])
        self.assertEqual(proof["sourceStructure"], verifier.MULTI_STRUCTURE)
        self.assertEqual(row["newArtists"], [])
        event, new = publisher_check(row)
        self.assertEqual(event, row["event"])
        self.assertEqual(new, {})

    def test_unidentified_unsupported_and_contradictory_bills_are_held(self):
        variants = [
            TWO.replace("+ 7WEEKS", "+ Guest").replace("<h2>7WEEKS</h2>",
                                                           "<h2>Guest</h2>"),
            TWO.replace("+ 7WEEKS", "+ 1ère partie").replace("<h2>7WEEKS</h2>",
                                                              "<h2>1ère partie</h2>"),
            TWO.replace("<h2>7WEEKS</h2><h2>On vous recommande",
                        "<h2>Other Artist</h2><h2>On vous recommande"),
            TWO.replace("<h2>7WEEKS</h2><h2>On vous recommande",
                        "<h2>7WEEKS</h2><h2>HIDDEN SUPPORT</h2><h2>On vous recommande"),
            TWO.replace("<h2>7WEEKS</h2><h2>On vous recommande",
                        "<h2>On vous recommande"),
            TWO.replace("Vendredi 2 avril 2027", "Samedi 3 avril 2027"),
            TWO.replace("#Rock New wave Post-Punk", "#Chanson Electro"),
            TWO.replace("Laiterie, Grande Salle", "Autre salle"),
            TWO.replace("Artefact PRL", "Concert reporté"),
        ]
        for page in variants:
            with self.subTest(page=page[:100]), self.assertRaises(ValueError):
                verifier.verify(candidate(), page, two_catalogue(), TODAY)

    def test_unknown_artist_and_existing_event_are_not_silently_added(self):
        c = two_catalogue()
        c["artists"] = c["artists"][:1]
        with self.assertRaisesRegex(ValueError, "canonique"):
            verifier.verify(candidate(), TWO, c, TODAY)
        c = two_catalogue()
        c["events"] = [{
            "id": "prior", "date": "2027-04-02",
            "venueId": "la-laiterie-strasbourg",
            "artistIds": ["7weeks"],
        }]
        with self.assertRaisesRegex(ValueError, "déjà connu"):
            verifier.verify(candidate(), TWO, c, TODAY)

    def test_real_publisher_rejects_multi_proof_spoofing(self):
        for path, value in [
            (("officialEvidence", 0, "sourceStructure"), verifier.STRUCTURE),
            (("officialEvidence", 0, "officialArtistNames"),
             ["Peter Hook and The Light", "Guest"]),
            (("event", "title"), "Peter Hook and The Light"),
            (("event", "time"), "19:30"),
            (("event", "artistIds"), ["peter-hook-and-the-light", "unlisted"]),
            (("event", "venueId"), "other-venue"),
        ]:
            row = copy.deepcopy(signed())
            if len(path) == 3:
                row[path[0]][path[1]][path[2]] = value
            else:
                row[path[0]][path[1]] = value
            with self.subTest(path=path), self.assertRaises((ValueError, KeyError)):
                publisher_check(row)

    def test_stability_and_idempotence_enforced_by_existing_engine(self):
        c = two_catalogue()
        approvals = {"schema": "grossesondes.concert.approvals.v1",
                     "approvals": []}
        registry = {"items": {"multi": {
            "candidate": candidate(), "status": "pending_review",
            "stableObservations": 1,
        }}}
        def no_fetch(*args):
            raise AssertionError("Not stable on distinct days")
        _, report = engine.process(registry, c, approvals, TODAY, fetch=no_fetch)
        self.assertEqual(report["evaluated"], 0)
        registry["items"]["multi"]["stableObservations"] = 2
        result, report = engine.process(
            registry, c, approvals, TODAY, fetch=lambda url, cache: TWO)
        self.assertEqual(len(report["newApprovals"]), 1)
        again, report = engine.process(registry, c, result, TODAY, fetch=no_fetch)
        self.assertEqual(report["alreadyApprovedSkipped"], 1)
        self.assertEqual(again, result)


if __name__ == "__main__":
    unittest.main()
