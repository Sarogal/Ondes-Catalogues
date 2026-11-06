"""Rapprochement conservateur des tournées qui partagent date et salle."""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cross_artist_tour_review as cross
import artist_tour_discovery as tour
import intake_archive

CATALOG = {
    "artists": [
        {"id": "7weeks", "name": "7Weeks"},
        {"id": "the-inspector-cluzo", "name": "The Inspector Cluzo"},
    ],
    "venues": [], "events": [],
}
CONFIG = {"schema": "grossesondes.concert.artist_tour_sources.v1", "sources": []}


def candidate(cid, artist, date="2026-11-26", venue="El Mediator", city="Perpignan"):
    return {
        "candidateId": cid, "artistId": artist, "date": date,
        "city": city, "venue": venue,
        "name": artist, "leadArtist": artist,
        "sourceUrl": "https://official.example/tour", "publicationAllowed": False,
        "reviewRequired": True, "lineupToConfirm": True,
    }


class SharedTourDateTests(unittest.TestCase):
    def test_deux_artistes_meme_date_meme_lieu_signalement_sans_fusion(self):
        source = [candidate("seven", "7weeks"),
                  candidate("inspector", "the-inspector-cluzo")]
        output, groups = cross.annotate(source)
        self.assertEqual(groups, 1)
        self.assertEqual(len(output), 2)
        self.assertEqual([x["candidateId"] for x in output], ["seven", "inspector"])
        self.assertEqual(output[0]["crossArtistTourReview"]["otherArtistIds"],
                         ["the-inspector-cluzo"])
        self.assertEqual(output[1]["crossArtistTourReview"]["otherArtistIds"], ["7weeks"])
        for row in output:
            self.assertFalse(row["crossArtistTourReview"]["lineupConfirmed"])
            self.assertFalse(row["publicationAllowed"])
            self.assertTrue(row["reviewRequired"])

    def test_different_date_lieu_ou_ville_ne_regroupe_pas(self):
        base = candidate("one", "7weeks")
        other = candidate("other", "the-inspector-cluzo")
        for change in (
            {"date": "2026-11-27"}, {"venue": "Autre Salle"},
            {"city": "Montpellier"}):
            changed = dict(other, **change)
            records, groups = cross.annotate([base, changed])
            self.assertEqual(groups, 0)
            self.assertTrue(all("crossArtistTourReview" not in x for x in records))

    def test_la_meme_tournee_republiee_ne_fabrique_pas_un_second_artiste(self):
        source = [candidate("a", "7weeks"), candidate("b", "7weeks")]
        result, groups = cross.annotate(source)
        self.assertEqual(groups, 0)
        self.assertTrue(all("crossArtistTourReview" not in x for x in result))

    def test_abreviation_st_saint_et_origine_preservee(self):
        records = [
            candidate("a", "7weeks", city="St Étienne"),
            candidate("b", "the-inspector-cluzo", city="Saint-Étienne"),
        ]
        found, groups = cross.annotate(records)
        self.assertEqual(groups, 1)
        self.assertEqual(found[0]["city"], "St Étienne")

    def test_candidats_hors_quarantaine_refuses(self):
        unsafe = candidate("unsafe", "7weeks")
        unsafe["publicationAllowed"] = True
        with self.assertRaises(ValueError):
            cross.annotate([unsafe])

    def test_registre_archive_pistes_distinctes_sans_approbation(self):
        records, groups = cross.annotate([
            candidate("a", "7weeks"), candidate("b", "the-inspector-cluzo")])
        report = tour.build_report(CATALOG, CONFIG, dt.date(2026,11,5), records, [])
        archive, stats = intake_archive.merge(None, report, "2026-11-05T05:00:00Z")
        self.assertEqual(stats["added"], 2)
        self.assertEqual(archive["total"], 2)
        self.assertEqual(groups, 1)


if __name__ == "__main__":
    unittest.main()
