"""Tests hors réseau du moteur Artistes → Tournées."""
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import artist_tour_discovery as tour
import intake_archive

DAY = dt.date(2026, 11, 4)
SOURCE = {
    "artistId": "resolve", "sourceRole": "artist_official",
    "url": "https://resolveofficial.co/", "enabled": True,
}
CATALOG = {
    "schemaVersion": 1, "artists": [
        {"id": "resolve", "name": "Resolve"}, {"id": "skip-the-use", "name": "Skip The Use"}],
    "venues": [{"id": "rockstore-montpellier", "name": "Rockstore", "city": "Montpellier"}],
    "events": [
        {"id": "known", "date": "2027-01-23", "venueId": "rockstore-montpellier",
         "artistIds": ["resolve"]},
        {"id": "known2", "date": "2027-01-27", "venueId": "rockstore-montpellier",
         "artistIds": ["resolve"]},
    ],
}
RAW = {
    "@type": "MusicEvent", "name": "Resolve + invité non précisé",
    "startDate": "2027-02-01T20:00:00+01:00",
    "performer": [{"@type": "MusicGroup", "name": "Resolve"}],
    "location": {"@type": "MusicVenue", "name": "L'Atelier Nouveau",
                 "address": {"addressLocality": "Brest", "addressCountry": "FR"}},
}
CONFIG = {"schema": "grossesondes.concert.artist_tour_sources.v1",
          "sources": [SOURCE]}


class TourDiscoveryTests(unittest.TestCase):
    def test_priorites_sur_vraies_dates_distinctes(self):
        rows = tour.artist_ranking(CATALOG)
        self.assertEqual(rows[0]["artist"], "Resolve")
        self.assertEqual(rows[0]["recordedDateCount"], 2)
        self.assertEqual(rows[1]["recordedDateCount"], 0)

    def test_source_officielle_uniquement(self):
        self.assertEqual(len(tour.source_selection(CONFIG, tour.artist_ranking(CATALOG), DAY, 3)), 1)
        bad = {"schema": CONFIG["schema"],
               "sources": [dict(SOURCE, url="http://url-insecure.fr")]}
        with self.assertRaises(ValueError):
            tour.source_selection(bad, tour.artist_ranking(CATALOG), DAY, 3)
        bad = {"schema": CONFIG["schema"],
               "sources": [dict(SOURCE, artistId="unknown")]}
        with self.assertRaises(ValueError):
            tour.source_selection(bad, tour.artist_ranking(CATALOG), DAY, 3)
        bad = {"schema": CONFIG["schema"],
               "sources": [dict(SOURCE, sourceRole="aggregator")]}
        with self.assertRaises(ValueError):
            tour.source_selection(bad, tour.artist_ranking(CATALOG), DAY, 3)

    def test_piste_officielle_nest_jamais_approuvee(self):
        candidate = tour.event_candidate(RAW, SOURCE, "Resolve", CATALOG, DAY)
        self.assertEqual(candidate["date"], "2027-02-01")
        self.assertEqual(candidate["city"], "Brest")
        self.assertTrue(candidate["newVenueToReview"])
        self.assertTrue(candidate["coordinatesToVerify"])
        self.assertFalse(candidate["publicationAllowed"])
        self.assertTrue(candidate["reviewRequired"])
        self.assertNotIn("latitude", candidate)
        self.assertNotIn("time", candidate)
        self.assertTrue(candidate["candidateId"].startswith("artist-tour:"))

    def test_annee_pays_ville_et_salle_obligatoires(self):
        for change in [
            {"startDate": "février 2027"},
            {"startDate": "02-01"},
            {"location": {"name": "Salle", "address": {"addressLocality": "Brest"}}},
            {"location": {"name": "Salle", "address": {
                "addressLocality": "Bruxelles", "addressCountry": "BE"}}},
            {"location": {"name": "Salle", "address": {
                "addressCountry": "FR"}}},
            {"location": {"address": {
                "addressLocality": "Brest", "addressCountry": "FR"}}},
        ]:
            raw = dict(RAW, **change)
            self.assertIsNone(tour.event_candidate(raw, SOURCE, "Resolve", CATALOG, DAY))

    def test_refus_de_concert_autre_artiste(self):
        raw = dict(RAW, performer={"name": "Un autre groupe"})
        self.assertIsNone(tour.event_candidate(raw, SOURCE, "Resolve", CATALOG, DAY))

    def test_nom_seul_doit_contenir_lartiste_entier(self):
        raw = dict(RAW)
        raw.pop("performer")
        self.assertTrue(tour.same_artist(raw, "Resolve"))
        raw["name"] = "Unresolvable Band"
        self.assertFalse(tour.same_artist(raw, "Resolve"))

    def test_venue_existante_est_identifiee(self):
        raw = dict(RAW, location={"name": "Rockstore", "address": {
            "addressLocality": "Montpellier", "addressCountry": "FR"}})
        c = tour.event_candidate(raw, SOURCE, "Resolve", CATALOG, DAY)
        self.assertFalse(c["newVenueToReview"])
        self.assertEqual(c["venueIdIfKnown"], "rockstore-montpellier")

    def test_annulation_reste_une_alerte(self):
        raw = dict(RAW, eventStatus="https://schema.org/EventCancelled")
        c = tour.event_candidate(raw, SOURCE, "Resolve", CATALOG, DAY)
        self.assertTrue(c["cancellationNotice"])
        report = tour.build_report(CATALOG, CONFIG, DAY, [c], [])
        self.assertEqual(report["candidates"][0]["reviewBucket"], "cancellation_watch")
        self.assertFalse(report["candidates"][0]["publicationAllowed"])

    def test_scan_jsonld_sans_reseau_et_archive_compatible(self):
        page = "<script type='application/ld+json'>" + json.dumps(
            {"@context": "https://schema.org", "@graph": [RAW]}) + "</script>"
        def fetch(url, **kwargs):
            self.assertEqual(url, SOURCE["url"])
            return page, url
        candidates, checks = tour.scan(CATALOG, CONFIG, DAY, fetch=fetch,
                                       robots=lambda url, cache: True)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(checks[0]["structuredEvents"], 1)
        report = tour.build_report(CATALOG, CONFIG, DAY, candidates, checks)
        self.assertEqual(sum(report["triageCounts"].values()), len(report["candidates"]))
        archived, summary = intake_archive.merge(None, report, "2026-11-04T12:00:00Z")
        self.assertEqual(summary["added"], 1)
        self.assertEqual(archived["total"], 1)

    def test_source_non_structuree_reste_sans_piste(self):
        candidates, checks = tour.scan(
            CATALOG, CONFIG, DAY, fetch=lambda url, **kw: ("<html>concert 2027</html>", url),
            robots=lambda url, cache: True)
        self.assertEqual(candidates, [])
        self.assertEqual(checks[0]["status"], "source_read_no_structured_event")

    def test_robots_blocage_pas_de_requete(self):
        with mock.patch.object(tour.discover, "download", side_effect=AssertionError("appel interdit")):
            candidates, checks = tour.scan(
                CATALOG, CONFIG, DAY, fetch=tour.discover.download,
                robots=lambda url, cache: False)
        self.assertEqual(candidates, [])
        self.assertEqual(checks[0]["status"], "held_source_unavailable")

    def test_repetition_stable_meme_concert(self):
        first = tour.event_candidate(RAW, SOURCE, "Resolve", CATALOG, DAY)
        again = tour.event_candidate(RAW, dict(SOURCE, url="https://example.com/tour"),
                                     "Resolve", CATALOG, DAY)
        self.assertEqual(first["candidateId"], again["candidateId"])

    def test_source_file_a_vrais_identifiants(self):
        source = json.loads(tour.SOURCES.read_text(encoding="utf-8"))
        valid = {a["artistId"] for a in tour.artist_ranking(CATALOG)}
        self.assertIn("resolve", valid)
        self.assertIn("resolve", {s["artistId"] for s in source["sources"]})
        self.assertEqual(source["schema"], CONFIG["schema"])


if __name__ == "__main__":
    unittest.main()
