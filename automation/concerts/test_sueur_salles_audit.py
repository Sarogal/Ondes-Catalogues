"""Safety tests for the independently verified first-party venue-source gap batch."""
import json
import unittest
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parent
SOURCE_FILE=ROOT/"sources.json"
BATCH={
    "official-gap-20261102-backstage-btm":("Backstage By The Mill","Paris","75","P1","www.backstage-btm.com"),
    "official-gap-20261102-glazart":("Glazart","Paris","75","P1","www.glazart.com"),
    "official-gap-20261102-forum-vaureal":("Le Forum de Vauréal","Vauréal","95","P1","leforum.cergypontoise.fr"),
    "official-gap-20261102-rock-n-eat":("Rock n' Eat","Lyon","69","P1","www.rockneat.com"),
    "official-gap-20261102-maison-bleue":("La Maison Bleue","Strasbourg","67","P1","www.lamaisonbleue-stbg.com"),
    "official-gap-20261102-trabendo":("Le Trabendo","Paris","75","P1","www.letrabendo.net"),
    "official-gap-20261102-maroquinerie":("La Maroquinerie","Paris","75","P2","www.lamaroquinerie.fr"),
    "official-gap-20261102-boule-noire":("La Boule Noire","Paris","75","P2","laboule-noire.fr"),
}

class OfficialCoverageSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=json.loads(SOURCE_FILE.read_text(encoding="utf8"))
        cls.venues=cls.data["venues"]

    def test_batch_exists_only_once(self):
        self.assertGreaterEqual(len(self.venues),60)
        ids=[v["id"] for v in self.venues]
        self.assertEqual(len(ids),len(set(ids)))
        keys=[(v["name"].casefold(),v["city"].casefold()) for v in self.venues]
        self.assertEqual(len(keys),len(set(keys)))
        self.assertEqual({v["id"] for v in self.venues if v["id"].startswith("official-gap-20261102-")},set(BATCH))

    def test_official_venues_never_approved_by_source_registration(self):
        lookup={v["id"]:v for v in self.venues}
        for key,(name,city,department,priority,host) in BATCH.items():
            with self.subTest(key=key):
                v=lookup[key]
                self.assertEqual((v["name"],v["city"],v["department"],v["priority"]),
                                 (name,city,department,priority))
                self.assertEqual(v["kind"],"official_venue_agenda_candidate")
                self.assertEqual(v["status"],(
                    "official_event_detail_review_only"
                    if key in ("official-gap-20261102-backstage-btm",
                               "official-gap-20261102-forum-vaureal",
                               "official-gap-20261102-glazart",
                               "official-gap-20261102-trabendo",
                               "official-gap-20261102-maroquinerie",
                               "official-gap-20261102-boule-noire")
                    else ("official_listing_review_only" if key in
                          ("official-gap-20261102-rock-n-eat",
                           "official-gap-20261102-maison-bleue")
                          else "official_agenda_verified_not_collector")))
                self.assertIs(v["publish_automatically"],False)
                self.assertEqual(v["verifiedOn"],"2026-11-02")
                self.assertEqual(v["url"],v["officialAgendaUrl"])
                self.assertTrue(v.get("exampleOfficialProgramming"))
                for field in ("url","officialIdentityUrl"):
                    parsed=urlsplit(v[field])
                    self.assertEqual(parsed.scheme,"https")
                    self.assertFalse(parsed.username or parsed.password or parsed.fragment)
                self.assertEqual(urlsplit(v["url"]).hostname,host)
                self.assertNotIn("publicationAllowed",v)
                self.assertNotIn("approval",v)
                self.assertNotIn("latitude",v)
                self.assertNotIn("longitude",v)
                self.assertNotIn("artistIds",v)
                self.assertNotIn("events",v)

    def test_competitor_is_not_a_production_data_source(self):
        for v in self.venues:
            with self.subTest(venue=v["id"]):
                parsed=urlsplit(v["url"])
                self.assertNotIn(parsed.hostname,{"sueurdemetal.com","www.sueurdemetal.com"})

if __name__=="__main__":
    unittest.main()
