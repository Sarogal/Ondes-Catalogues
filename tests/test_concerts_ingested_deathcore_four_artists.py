"""Backstage: a short H1 can be expanded ONLY by a verified full promoter bill.

Synthetic markup reproduces the official Ingested 01 February 2027 page:
four named groups, Deathcore category, exact first-party date and venue.
No HTTP request, private queue, time inference, PR approval or public write.
"""
import copy
import datetime as dt
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "automation" / "concerts"))
sys.path.insert(0, str(ROOT / "scripts"))
import backstage_recheck as venue_recheck
from concerts_cloud_sync import validate_approval

TODAY = dt.date(2026, 11, 16)
URL = "https://www.backstage-btm.com/agenda/ingested/"
LINEUP = ["INGESTED", "PSYCROPTIC", "NETHERWALKER", "TRACHEOTOMY"]
IDS = ["ingested", "psycroptic", "netherwalker", "tracheotomy"]
PAGE = """<html><head><title>INGESTED | Backstage</title></head><body><main>
<h1>INGESTED</h1>
<div>Deathcore</div><div>01/02/2027</div>
<div>O’Sullivans By The Mill, 92 bis bd de Clichy - Paris</div>
<p>GARMONBOZIA présente INGESTED « 20th Anniversary Tour » + PSYCROPTIC + NETHERWALKER + TRACHEOTOMY</p>
<p>INGESTED emmènent PSYCROPTIC, NETHERWALKER et TRACHEOTOMY.</p>
</main></body></html>"""
CANDIDATE = {
    "candidateId": "backstage:2027-02-01:ingested",
    "source": "agenda_officiel_backstage_detail",
    "sourceUrl": URL,
    "name": "INGESTED",
    "date": "2027-02-01",
    "venue": "Backstage By The Mill",
    "city": "Paris",
    "classification": ["deathcore"],
    "reviewBucket": "genre_tag_review",
    "possibleExistingConcert": False,
    "reviewRequired": True,
    "publicationAllowed": False,
}


def catalogue():
    result = json.loads((ROOT / "docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
    result["events"] = []
    result["artists"] = [a for a in result["artists"] if a["id"] not in IDS]
    return result


class IngestedOfficialCompleteBillTests(unittest.TestCase):
    def test_four_named_bands_pass_exact_same_publisher_without_guessed_hour(self):
        c = catalogue()
        original = copy.deepcopy(c)
        proof = venue_recheck.verify(CANDIDATE, PAGE, c, TODAY)
        self.assertEqual(proof["event"]["title"], " + ".join(LINEUP))
        self.assertEqual(proof["event"]["artistIds"], IDS)
        self.assertEqual(proof["event"]["date"], "2027-02-01")
        self.assertEqual(proof["event"]["genres"], ["Deathcore"])
        self.assertEqual(proof["event"]["id"], "go-c-20270201-paris-ingested")
        self.assertEqual(proof["officialEvidence"][0]["officialArtistNames"],
                         LINEUP)
        self.assertEqual([a["id"] for a in proof["newArtists"]], IDS)
        event, artists = validate_approval(
            proof, {v["id"]: v for v in c["venues"]},
            {a["id"]: a for a in c["artists"]}, TODAY)
        self.assertEqual(event["artistIds"], IDS)
        self.assertEqual(set(artists), set(IDS))
        self.assertIsNone(event["time"])
        self.assertEqual(c, original)

    def test_promoter_announcement_is_exact_not_an_artist_biography_guess(self):
        for html in (
            PAGE.replace("INGESTED « 20th Anniversary Tour »",
                         "ANOTHER ACT « 20th Anniversary Tour »"),
            PAGE.replace(" + PSYCROPTIC + NETHERWALKER + TRACHEOTOMY", ""),
            PAGE.replace(" + PSYCROPTIC + NETHERWALKER + TRACHEOTOMY",
                         " + GUEST"),
            PAGE.replace(
                "GARMONBOZIA présente INGESTED",
                "<strong>GARMONBOZIA</strong> présente INGESTED"),
            PAGE.replace("Deathcore</div>", "Electronic Dance</div>"),
            PAGE.replace("01/02/2027", "01/02/2028"),
            PAGE.replace("O’Sullivans By The Mill", "Other Club"),
        ):
            with self.subTest(html=html[:250]), self.assertRaises(ValueError):
                venue_recheck.verify(CANDIDATE, html, catalogue(), TODAY)
        fake = copy.deepcopy(CANDIDATE)
        fake["sourceUrl"] = "https://third-party.example/agenda/ingested/"
        with self.assertRaises(ValueError):
            venue_recheck.verify(fake, PAGE, catalogue(), TODAY)

    def test_fourth_artist_invented_in_approval_still_fails_publisher(self):
        c = catalogue()
        proposed = venue_recheck.verify(CANDIDATE, PAGE, c, TODAY)
        venues = {v["id"]: v for v in c["venues"]}
        known = {a["id"]: a for a in c["artists"]}
        for mutation in ("event-artist", "proof-names", "time", "date"):
            forged = copy.deepcopy(proposed)
            if mutation == "event-artist":
                forged["event"]["artistIds"][-1] = "invented-band"
            elif mutation == "proof-names":
                forged["officialEvidence"][0]["officialArtistNames"][-1] = "INVENTED BAND"
            elif mutation == "time":
                forged["event"]["time"] = "19:30"
            else:
                forged["event"]["date"] = "2027-02-02"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_approval(forged, venues, known, TODAY)

    def test_alias_conflict_and_published_collision_are_fatal(self):
        c = catalogue()
        c["artists"].append({"id": "prior-alias", "name": "Prior Band",
                             "aliases": ["NETHERWALKER"]})
        with self.assertRaisesRegex(ValueError, "alias"):
            venue_recheck.verify(CANDIDATE, PAGE, c, TODAY)
        c = catalogue()
        c["events"].append({
            "id": "other", "date": "2027-02-01",
            "venueId": "backstage-by-the-mill-paris",
            "artistIds": ["psycroptic"],
        })
        with self.assertRaisesRegex(ValueError, "déjà publié"):
            venue_recheck.verify(CANDIDATE, PAGE, c, TODAY)


if __name__ == "__main__":
    unittest.main()
