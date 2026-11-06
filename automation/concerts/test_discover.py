"""Tests sans réseau de la veille Concerts."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discover as d


class DiscoveryTests(unittest.TestCase):
    def test_cloud_catalogue_falls_back_to_github_raw(self):
        from unittest import mock
        import urllib.error
        calls = []
        def response(url, *args, **kwargs):
            calls.append(url)
            if url == d.CATALOG:
                raise urllib.error.HTTPError(url, 503, "temporarily unavailable", {}, None)
            if url == d.CATALOG_RAW:
                return '{"schemaVersion": 1, "events": []}', url
            raise AssertionError("Unexpected URL " + url)
        with mock.patch.object(d, "download", side_effect=response):
            data = d.json_url(d.CATALOG)
        self.assertEqual(data["schemaVersion"], 1)
        self.assertEqual(calls, [d.CATALOG, d.CATALOG_RAW])

    def test_reference_unavailable_fails_closed(self):
        from unittest import mock
        import urllib.error
        with mock.patch.object(d, "download", side_effect=urllib.error.URLError("unavailable")):
            with self.assertRaisesRegex(RuntimeError, "Neither GitHub Pages"):
                d.json_url(d.CATALOG)

    def test_discovery_reference_is_cloud_catalogue(self):
        self.assertEqual(d.CATALOG, "https://sarogal.github.io/Ondes-Catalogues/grossesondes/concerts.json")

    def test_normalisation_accents(self):
        self.assertEqual(d.norm("Saint-Jean-de-Védas"), "saintjeandevedas")

    def test_titre_et_date_futur(self):
        self.assertEqual(d.iso_day("2027-11-05T20:00:00+01:00"), "2027-11-05")
        self.assertIsNone(d.iso_day("2027-19-80"))

    def test_ticketmaster_confirme_candidat_seulement(self):
        raw = {
            "id": "abc123", "name": "Test Metal Live",
            "url": "https://www.ticketmaster.fr/event/test",
            "dates": {"start": {"localDate": "2027-05-01", "localTime": "20:00"},
                      "status": {"code": "onsale"}},
            "_embedded": {
                "venues": [{"name": "Salle test", "city": {"name": "Paris"},
                            "country": {"countryCode": "FR"}}],
                "attractions": [{"name": "Groupe Test"}]
            },
            "classifications": [{"genre": {"name": "Metal"}}],
        }
        c = d.ticketmaster_candidate(raw, {("2027-05-01", "paris", "groupetest")}, "2026-11-01")
        self.assertTrue(c["possibleExistingConcert"])
        self.assertFalse(c["publicationAllowed"])
        self.assertTrue(c["reviewRequired"])
        self.assertEqual(c["venue"], "Salle test")

    def test_ticketmaster_absence_de_cle_ne_bloque_pas_la_veille(self):
        rapport = []
        candidats = d.scan_ticketmaster("", set(), d.today_fr(), rapport)
        self.assertEqual(candidats, [])
        self.assertEqual(rapport[0]["status"], "not_configured")

    def test_ticketmaster_429_stops_all_remaining_queries(self):
        from unittest import mock
        import datetime as dt
        import urllib.error
        urls=[]
        def throttled(url,*a,**kw):
            urls.append(url)
            raise urllib.error.HTTPError(url,429,"rate limit",{},None)
        report=[]
        with mock.patch.object(d,"download",side_effect=throttled), \
             mock.patch.object(d.time,"sleep"):
            rows=d.scan_ticketmaster("NOT_A_REAL_SECRET",set(),dt.date(2026,11,2),report)
        self.assertEqual(rows,[])
        self.assertEqual(len(urls),1)
        self.assertEqual(report[0]["error"],"HTTP 429")
        self.assertNotIn("NOT_A_REAL_SECRET",str(report))

    def test_ticketmaster_unfiltered_fr_requires_explicit_genre_and_future_date(self):
        from unittest import mock
        import datetime as dt
        import urllib.parse
        def event(genre,date,ident):
            return {"id":ident,"name":"Metal in France",
                    "url":"https://www.ticketmaster.fr/event/"+ident,
                    "dates":{"start":{"localDate":date,"localTime":"20:00"},
                             "status":{"code":"onsale"}},
                    "_embedded":{"venues":[{"name":"Le Rex",
                                             "city":{"name":"Toulouse"},
                                             "country":{"countryCode":"FR"}}],
                                 "attractions":[{"name":"Test Act"}]},
                    "classifications":[{"genre":{"name":genre}}]}
        seen=[]
        def response(url,*a,**kw):
            args=urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            seen.append(args)
            if "keyword" in args or "classificationName" in args:
                events=[]
            else:
                events=[event("Metal","2027-02-03","metal-future"),
                        event("Pop","2027-02-04","pop-future"),
                        event("Metal","2026-10-02","metal-past")]
            return json.dumps({"_embedded":{"events":events},
                               "page":{"totalElements":len(events)}}),url
        report=[]
        with mock.patch.object(d,"download",side_effect=response), \
             mock.patch.object(d.time,"sleep"):
            rows=d.scan_ticketmaster("NOT_A_REAL_SECRET",set(),dt.date(2026,11,2),report)
        self.assertEqual([x["candidateId"] for x in rows],["ticketmaster:metal-future"])
        self.assertEqual(len(seen),3)
        self.assertEqual(sum("startDateTime" not in args for args in seen),1)
        self.assertTrue(all(x["publicationAllowed"] is False for x in rows))
        self.assertNotIn("NOT_A_REAL_SECRET",str(report))

    def test_ticketmaster_annulation_non_retenue(self):
        raw = {
            "id": "evt", "name": "Concert", "url": "https://ticketmaster.fr/test",
            "dates": {"start": {"localDate": "2027-05-01"}, "status": {"code": "cancelled"}},
            "_embedded": {"venues": [{"name": "Salle", "city": {"name": "Lyon"},
                                      "country": {"countryCode": "FR"}}]},
        }
        self.assertIsNone(d.ticketmaster_candidate(raw, set(), "2026-11-01"))

    def test_jsonld_officiel(self):
        payload = {
            "@context": "https://schema.org", "@graph": [{
                "@type": "MusicEvent", "name": "Concert de doom métal",
                "startDate": "2027-02-15T20:00:00+01:00",
                "performer": {"@type": "MusicGroup", "name": "Groupe Essai"},
                "location": {"@type": "MusicVenue", "name": "La Salle",
                             "address": {"addressLocality": "Nîmes"}}
            }]
        }
        html = "<html><script type='application/ld+json'>" + json.dumps(payload) + "</script></html>"
        events = list(d.read_ld(html))
        self.assertEqual(len(events), 1)
        source = {"name": "La Salle", "city": "Nîmes", "department": "30"}
        c = d.venue_candidate(events[0], source, "https://exemple.fr/concert", set(), "2026-11-01")
        self.assertEqual(c["leadArtist"], "Groupe Essai")
        self.assertEqual(c["date"], "2027-02-15")
        self.assertFalse(c["publicationAllowed"])

    def test_absence_date_pas_de_candidate(self):
        source = {"name": "Salle", "city": "Paris", "department": "75"}
        self.assertIsNone(d.venue_candidate({"@type": "MusicEvent", "name": "Un concert"},
                                            source, "https://exemple.fr/", set(), "2026-11-01"))

    def test_annulations_reunions_et_festivals_exclus(self):
        self.assertTrue(d.reject_listing("HEAVY LUNGS &#8211; ANNULÉ"))
        self.assertTrue(d.reject_listing("Réunion d'information autour des musiques actuelles"))
        self.assertTrue(d.reject_listing("ONE WAY OUT FEST IV"))
        self.assertFalse(d.reject_listing("CONVERGE + NOUN"))

    def test_tri_rss_sans_date(self):
        records = [
            {"date": None, "city": "Paris", "name": "Annonce RSS"},
            {"date": "2027-01-04", "city": "Nantes", "name": "Concert date"},
        ]
        ordered = sorted(records, key=d.candidate_sort_key)
        self.assertEqual(ordered[0]["name"], "Concert date")
        self.assertIsNone(ordered[1]["date"])

    def test_catalogue_match(self):
        catalog = {
            "venues": [{"id": "v", "city": "Saint-Jean-de-Védas"}],
            "artists": [{"id": "a", "name": "Groupe Metal"}],
            "events": [{"date": "2027-04-10", "venueId": "v", "artistIds": ["a"]}],
        }
        self.assertIn(("2027-04-10", "saintjeandevedas", "groupemetal"), d.make_known_keys(catalog))

    def test_agenda_salle_ne_republie_pas_concert_autre_lieu(self):
        source = {"name": "La Tannerie", "city": "Bourg-en-Bresse",
                  "department": "01"}
        raw = {
            "name": "Concert à Radio B",
            "startDate": "2026-11-13T20:00:00+01:00",
            "location": {"name": "Radio B",
                         "address": {"addressLocality": "Bourg-en-Bresse"}},
            "performer": {"name": "Band"}
        }
        self.assertIsNone(d.venue_candidate(
            raw, source, "https://www.la-tannerie.com/agenda/", set(), "2026-11-01"))
        raw["location"]["name"] = "La Tannerie"
        self.assertIsNotNone(d.venue_candidate(
            raw, source, "https://www.la-tannerie.com/agenda/", set(), "2026-11-01"))

    def test_non_fr_exclu(self):
        raw = {"id": "abc123", "name": "Test Metal",
               "url": "https://www.ticketmaster.fr/event/test",
               "dates": {"start": {"localDate": "2027-05-01"}},
               "_embedded": {"venues": [{"name": "Salle", "city": {"name": "Bruxelles"},
                                         "country": {"countryCode": "BE"}}]}}
        self.assertIsNone(d.ticketmaster_candidate(raw, set(), "2026-11-01"))


if __name__ == "__main__":
    unittest.main()
