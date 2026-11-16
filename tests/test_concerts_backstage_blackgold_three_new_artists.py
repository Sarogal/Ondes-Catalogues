"""Regression: real announced 3-band Backstage bill must not hit a 2-new-artist cap.

The page fragment is a static fixture transcribed from the official event
detail. No live HTTP, private approval data, publication or inferred start hour.
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

import backstage_recheck
from concerts_cloud_sync import validate_approval

TODAY = dt.date(2026, 11, 16)
URL = "https://www.backstage-btm.com/agenda/blackgold/"
NAME = "BLACKGOLD + SUMO CYCO + HYRO THE HERO"
ARTISTS = ["BLACKGOLD", "SUMO CYCO", "HYRO THE HERO"]
ARTIST_IDS = ["blackgold", "sumo-cyco", "hyro-the-hero"]
PAGE = """<html><body><main>
<h1>BLACKGOLD + SUMO CYCO + HYRO THE HERO</h1>
<div>metal</div>
<div>03/12/2026</div>
<div>O’Sullivans By The Mill, 92 bis bd de Clichy - Paris</div>
<p>BLACKGOLD: nu-metal; tournée avec SUMO CYCO et HYRO THE HERO.</p>
</main></body></html>"""
CANDIDATE = {
    "candidateId": "backstage:2026-12-03:blackgold",
    "source": "agenda_officiel_backstage_detail",
    "sourceUrl": URL,
    "name": NAME,
    "date": "2026-12-03",
    "venue": "Backstage By The Mill",
    "city": "Paris",
    "classification": ["metal"],
    "reviewBucket": "genre_tag_review",
    "possibleExistingConcert": False,
    "reviewRequired": True,
    "publicationAllowed": False,
}


def empty_concerts_with_real_venue():
    result = json.loads((ROOT / "docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
    result["events"] = []
    result["artists"] = [
        item for item in result["artists"]
        if item["id"] not in ARTIST_IDS
    ]
    return result


class BlackgoldThreeNewArtistsParityTests(unittest.TestCase):
    def test_official_three_named_artists_pass_recheck_and_exact_publisher(self):
        catalogue = empty_concerts_with_real_venue()
        before = copy.deepcopy(catalogue)
        signed = backstage_recheck.verify(CANDIDATE, PAGE, catalogue, TODAY)
        self.assertEqual(signed["reviewedBy"], "automated-official-recheck")
        self.assertEqual(signed["event"]["title"], NAME)
        self.assertEqual(signed["event"]["date"], "2026-12-03")
        self.assertEqual(signed["event"]["id"], "go-c-20261203-paris-blackgold")
        self.assertEqual(signed["event"]["genres"], ["Metal"])
        self.assertEqual(signed["event"]["artistIds"], ARTIST_IDS)
        self.assertEqual([x["id"] for x in signed["newArtists"]], ARTIST_IDS)
        self.assertEqual(signed["officialEvidence"][0]["officialArtistNames"], ARTISTS)
        event, newly_known = validate_approval(
            signed,
            {v["id"]: v for v in catalogue["venues"]},
            {a["id"]: a for a in catalogue["artists"]},
            TODAY,
        )
        self.assertEqual(event["artistIds"], ARTIST_IDS)
        self.assertEqual(set(newly_known), set(ARTIST_IDS))
        self.assertIsNone(event["time"])
        self.assertEqual(catalogue, before)

    def test_fabricated_fourth_artist_or_signed_lineup_mutation_is_rejected(self):
        catalogue = empty_concerts_with_real_venue()
        signed = backstage_recheck.verify(CANDIDATE, PAGE, catalogue, TODAY)
        venues = {v["id"]: v for v in catalogue["venues"]}
        artists = {a["id"]: a for a in catalogue["artists"]}
        variants = []
        extra = copy.deepcopy(signed)
        extra["event"]["title"] += " + INVENTED BAND"
        extra["event"]["artistIds"].append("invented-band")
        extra["newArtists"].append({"id": "invented-band", "name": "INVENTED BAND"})
        variants.append(extra)
        changed_names = copy.deepcopy(signed)
        changed_names["officialEvidence"][0]["officialArtistNames"].append("INVENTED BAND")
        variants.append(changed_names)
        forged_date = copy.deepcopy(signed)
        forged_date["event"]["date"] = "2026-12-04"
        variants.append(forged_date)
        fake_start = copy.deepcopy(signed)
        fake_start["event"]["time"] = "20:00"
        variants.append(fake_start)
        for row in variants:
            with self.subTest(row=row["event"]), self.assertRaises(ValueError):
                validate_approval(row, venues, artists, TODAY)

    def test_page_tampering_and_artist_alias_are_not_exempt(self):
        catalogue = empty_concerts_with_real_venue()
        for page in (
            PAGE.replace("03/12/2026", "04/12/2026"),
            PAGE.replace("03/12/2026", ""),
            PAGE.replace("O’Sullivans", "Fake Club"),
            PAGE.replace("metal</div>", "pop</div>"),
            PAGE.replace("<h1>"+NAME+"</h1>", "<h1>BLACKGOLD</h1>"),
        ):
            with self.subTest(page=page[:180]), self.assertRaises(ValueError):
                backstage_recheck.verify(CANDIDATE, page, catalogue, TODAY)
        catalogue["artists"].append({
            "id": "unknown-with-alias", "name": "Unknown",
            "aliases": ["SUMO CYCO"],
        })
        with self.assertRaisesRegex(ValueError, "alias"):
            backstage_recheck.verify(CANDIDATE, PAGE, catalogue, TODAY)


if __name__ == "__main__":
    unittest.main()
