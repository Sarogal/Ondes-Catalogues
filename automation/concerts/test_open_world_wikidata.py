"""No-network independent directory and generic discovery integration."""
import unittest
from unittest import mock
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
                            statement("https://127.0.0.1/"),
                            statement("https://host.internal/"),
                            statement("https://unsafe.example.org:443/"),
                            statement("https://[::1]/")]}}}}


class WikidataResearchTests(unittest.TestCase):
    def test_oversized_identity_is_held_without_blocking_next_artist(self):
        reg = registry()
        reg["items"]["lead"]["candidate"]["officialArtistNames"] = ["Act A", "Act B", "Act C"]
        calls = []
        def bounded(*args):
            name = args[0]["search"]
            calls.append(name)
            if "Act A" in name:
                raise wd.mb.OversizedDirectoryResponse("private detail never retained")
            return {"search": []}
        result = wd.build(reg, DAY, request=bounded)
        self.assertEqual(result["namesChecked"], 3)
        self.assertEqual(result["reasonCounts"], {"response_too_large": 1, "not_found": 2})
        held = result["entries"]["act a"]
        self.assertEqual(held["status"], "response_too_large")
        self.assertFalse(held["identityVerified"])
        self.assertFalse(held["publicationAllowed"])
        self.assertNotIn("homepageHints", held)
        self.assertNotIn("genres", held)
        self.assertNotIn("private detail", str(result))
        self.assertIsNone(result["serviceFailureKind"])
        cached = wd.build(reg, DAY, prior=result,
                                request=lambda *a: self.fail("same-day retry"))
        self.assertEqual(cached["namesChecked"], 0)

    def test_repeated_oversized_responses_stop_at_two_and_keep_other_names_due(self):
        reg = registry()
        reg["items"]["lead"]["candidate"]["officialArtistNames"] = ["Act A", "Act B", "Act C"]
        def oversized(*args):
            raise wd.mb.OversizedDirectoryResponse("bounded")
        result = wd.build(reg, DAY, request=oversized)
        self.assertEqual(result["namesChecked"], 2)
        self.assertEqual(result["serviceFailureKind"], "oversized_response")
        self.assertEqual(set(result["entries"]), {"act a", "act b"})
        self.assertEqual(result["serviceRetryAfterKey"], "act b")
        recovered = wd.build(reg, DAY, prior=result,
                                request=lambda *a: {"search": []})
        self.assertEqual(recovered["namesChecked"], 1)
        self.assertEqual(recovered["entries"]["act c"]["status"], "not_found")
        self.assertFalse(recovered["publicationAllowed"])

    def test_maxlag_and_rate_limit_are_service_wide_stops(self):
        for kind in ("maxlag", "ratelimited", "readonly", "api_error"):
            reg = registry()
            reg["items"]["lead"]["candidate"]["officialArtistNames"] = ["Act A", "Act B"]
            def unavailable(*args):
                raise wd.mb.DirectoryServiceError(kind)
            result = wd.build(reg, DAY, request=unavailable)
            self.assertEqual(result["namesChecked"], 1)
            self.assertEqual(result["serviceFailureKind"], kind)
            self.assertEqual(result["entries"], {})
            self.assertEqual(result["serviceRetryAfterKey"], "act a")

    def test_directory_independent_of_musicbrainz_and_safe_handoff(self):
        result = wd.build(registry(), DAY, request=request)
        entry = result["entries"][NAME.casefold()]
        self.assertEqual(entry["qid"], "Q123")
        self.assertEqual(entry["homepageHints"], [URL])
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

    def test_incomplete_never_gets_homepage(self):
        def incomplete(params):
            self.assertEqual(params["action"], "wbsearchentities")
            return {"search": [{"id": "Q123", "label": NAME}],
                    "search-continue": 20}
        self.assertEqual(wd.research(NAME, incomplete),
                         {"status": "ambiguous_or_incomplete"})

    def test_explicit_nonperformer_collision_is_only_navigation_hint(self):
        for kind in ("Q11424", "Q482994", "Q7366", "Q4167410"):
            with self.subTest(kind=kind):
                def collision(params):
                    if params["action"] == "wbsearchentities":
                        return {"search": [{"id": "Q123", "label": NAME},
                                            {"id": "Q124", "label": NAME}]}
                    self.assertEqual(params["ids"], "Q123|Q124")
                    data = request({**params, "ids": "Q123"})
                    data["entities"]["Q124"] = {
                        "id": "Q124", "labels": {"en": {"value": NAME}},
                        "claims": {"P31": [statement({"id": kind})],
                                   "P856": [statement("https://unrelated.example/")]}}
                    return data
                result = wd.build(registry(), DAY, request=collision)
                entry = result["entries"][NAME.casefold()]
                self.assertEqual(entry["qid"], "Q123")
                self.assertEqual(entry["homepageHints"], [URL])
                self.assertFalse(entry["identityVerified"])
                self.assertFalse(entry["publicationAllowed"])
                self.assertEqual(result["approvalsProposed"], 0)

    def test_musical_or_unresolved_collision_stays_held(self):
        for kinds in (["Q215380"], ["Q5"], ["Q999"], [], None):
            with self.subTest(kinds=kinds):
                def collision(params):
                    if params["action"] == "wbsearchentities":
                        return {"search": [{"id": "Q123", "label": NAME},
                                            {"id": "Q124", "label": NAME}]}
                    data = request({**params, "ids": "Q123"})
                    if kinds is not None:
                        data["entities"]["Q124"] = {
                            "id": "Q124", "labels": {"en": {"value": NAME}},
                            "claims": {"P31": [statement({"id": k}) for k in kinds]}}
                    return data
                self.assertEqual(wd.research(NAME, collision),
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
            wd.build(registry(), DAY, limit=wd.MAX_NAMES + 1)


    def test_bounded_expansion_and_deferred_names_remain_due(self):
        reg = registry()
        reg["items"]["lead"]["candidate"]["officialArtistNames"] = [
            f"Act {i:02d}" for i in range(40)]
        def empty(params):
            return {"search": []}
        full = wd.build(reg, DAY, request=empty)
        self.assertEqual(full["namesChecked"], 24)
        self.assertEqual(full["reviewDeferredByTimeBudget"], 0)
        with mock.patch.object(wd.time, "monotonic", side_effect=[0, 0, 1, 2, 3, 3]):
            partial = wd.build(reg, DAY, request=empty, max_seconds=3)
        self.assertEqual(partial["namesChecked"], 3)
        self.assertEqual(partial["reviewDeferredByTimeBudget"], 21)
        self.assertEqual(len(partial["entries"]), 3)
        resumed = wd.build(reg, DAY, prior=partial, request=empty)
        self.assertEqual(resumed["dueNames"], 37)
        self.assertEqual(resumed["namesChecked"], 24)
        self.assertEqual(len(resumed["entries"]), 27)
        self.assertFalse(resumed["publicationAllowed"])
        self.assertEqual(resumed["approvalsProposed"], 0)
        for bad in (0, True, 121):
            with self.assertRaises(ValueError):
                wd.build(reg, DAY, request=empty, max_seconds=bad)


if __name__ == "__main__":
    unittest.main()
