"""No-network independent directory and generic discovery integration."""
import unittest
from urllib.error import HTTPError

import open_world_wikidata as wd
import open_world_frontier as frontier
import open_world_site_research as sites
from test_open_world_musicbrainz import DAY, NAME, URL, registry


def statement(value):
    return {"rank": "normal", "mainsnak": {
        "snaktype": "value", "datavalue": {"value": value}}}


def request(params):
    if params["action"] == "wbsearchentities":
        assert params["search"] == NAME
        return {"search": [{"id": "Q123", "label": NAME}]}
    assert params["ids"] == "Q123"
    return {"entities": {"Q123": {
        "id": "Q123", "labels": {"en": {"value": NAME}},
        "claims": {"P31": [statement({"id": "Q215380"})],
                   "P136": [statement({"id": "Q1"})],
                   "P856": [statement(URL), statement("http://insecure.example/"),
                            statement("https://127.0.0.1/")]}}}}


class WikidataResearchTests(unittest.TestCase):
    def test_directory_independent_of_musicbrainz_and_safe_handoff(self):
        result = wd.build(registry(), DAY, request=request)
        entry = result["entries"][NAME.casefold()]
        self.assertEqual(entry["qid"], "Q123")
        self.assertNotIn("genres", entry)
        self.assertFalse(entry["identityVerified"])
        self.assertFalse(result["publicationAllowed"])
        self.assertEqual(result["approvalsProposed"], 0)
        row = {"key": frontier.identity("artist", NAME), "name": NAME,
               "researchOnly": True}
        report = {"schema": frontier.SCHEMA, "publicationAllowed": False,
                  "artistResearch": [row], "venueResearch": []}
        seeds = sites.select_sources(report, registry(), DAY,
                                     wikidata=result)
        self.assertEqual([s["url"] for s in seeds], [URL])
        self.assertFalse(seeds[0]["claimedOfficial"])
        entry["identityVerified"] = True
        self.assertEqual(sites.select_sources(report, registry(), DAY,
                                             wikidata=result), [])

    def test_ambiguous_and_incomplete_never_get_homepage(self):
        for response in (
                {"search": [{"id": "Q123", "label": NAME},
                            {"id": "Q124", "label": NAME}]},
                {"search": [{"id": "Q123", "label": NAME}], "search-continue": 20}):
            def ambiguous(params):
                self.assertEqual(params["action"], "wbsearchentities")
                return response
            self.assertEqual(wd.research(NAME, ambiguous),
                             {"status": "ambiguous_or_incomplete"})

    def test_nonmusical_homonym_held(self):
        def wrong(params):
            data = request(params)
            if params["action"] == "wbgetentities":
                data["entities"]["Q123"]["claims"]["P31"] = [statement({"id": "Q5"})]
                data["entities"]["Q123"]["claims"].pop("P136")
            return data
        self.assertEqual(wd.research(NAME, wrong), {"status": "identity_held"})

    def test_failure_rotates_and_preserves_memory(self):
        reg = registry()
        reg["items"]["lead"]["candidate"]["officialArtistNames"] = ["Act A", "Act B"]
        def unavailable(params):
            raise HTTPError("https://example.org", 503, "unavailable", {}, None)
        first = wd.build(reg, DAY, request=unavailable)
        second = wd.build(reg, DAY, prior=first, request=unavailable)
        self.assertEqual(first["serviceRetryAfterKey"], "act a")
        self.assertEqual(second["serviceRetryAfterKey"], "act b")
        self.assertEqual(second["entries"], {})
        self.assertEqual(second["serviceFailureKind"], "http_503")
        self.assertNotIn("example.org", str(second))

    def test_success_cached_and_budget_bounded(self):
        first = wd.build(registry(), DAY, request=request)
        second = wd.build(registry(), DAY, prior=first,
                          request=lambda *a: self.fail("cached"))
        self.assertEqual(second["namesChecked"], 0)
        self.assertEqual(second["entries"], first["entries"])
        with self.assertRaises(ValueError):
            wd.build(registry(), DAY, limit=13)


if __name__ == "__main__":
    unittest.main()
