"""No-network tests for directory research and downstream tour navigation."""
import datetime as dt
import unittest
from urllib.error import HTTPError, URLError

import open_world_musicbrainz as mb
import open_world_site_research as sites
import open_world_frontier as frontier

DAY = dt.date(2026, 11, 24)
NAME = "Unknown Act"
ID = "b943bd49-21fd-4d32-bf2a-fc19d3a6d6a1"
URL = "https://unknown-act.example.org/"


def registry():
    return {"schema": "grossesondes.concert.intake.v1", "items": {
        "lead": {"status": "pending_review", "candidate": {
            "officialArtistNames": [NAME], "date": "2027-02-10",
            "publicationAllowed": False, "reviewRequired": True,
            "source": "open_world_visible_card_research",
        }}}}


def lookup(path, params):
    if not path:
        return {"count": 1, "artists": [{"name": NAME, "id": ID}]}
    assert path == ID
    return {"name": NAME, "id": ID, "type": "Group",
            "genres": [{"name": "death metal", "count": 3},
                       {"name": "jazz", "count": 1}],
            "relations": [{"type": "official homepage", "target-type": "url",
                           "ended": False, "url": {"resource": URL}},
                          {"type": "social network", "target-type": "url",
                           "url": {"resource": "https://social.example.org/"}}]}


class MusicBrainzResearchTests(unittest.TestCase):
    def test_unknown_name_without_website(self):
        result = mb.build(registry(), DAY, request=lookup)
        entry = result["entries"][mb.exact(NAME)]
        self.assertEqual(result["namesChecked"], 1)
        self.assertEqual(result["approvalsProposed"], 0)
        self.assertEqual(entry["mbid"], ID)
        self.assertIn("death metal", [x.casefold() for x in entry["genres"]])
        self.assertEqual(entry["homepageHints"], [URL])
        self.assertFalse(entry["identityVerified"])
        self.assertFalse(entry["publicationAllowed"])

    def test_ambiguous_and_truncated_search_never_lookup(self):
        for rows, count in [
            ([{"name": NAME, "id": ID}, {"name": NAME, "id": ID}], 2),
            ([{"name": NAME, "id": ID}], 21),
        ]:
            def request(path, params):
                self.assertEqual(path, "")
                return {"artists": rows, "count": count}
            result = mb.build(registry(), DAY, request=request)
            entry = result["entries"][mb.exact(NAME)]
            self.assertEqual(entry["status"], "ambiguous_or_incomplete")
            self.assertNotIn("homepageHints", entry)

    def test_memory_and_service_failure(self):
        result = mb.build(registry(), DAY, request=lookup)
        def unavailable(*args):
            raise OSError("service unavailable")
        next_day = mb.build(registry(), DAY + dt.timedelta(days=1),
                            prior=result, request=lambda *a: self.fail("cached"))
        self.assertEqual(next_day["namesChecked"], 0)
        later = mb.build(registry(), DAY + dt.timedelta(days=31),
                         prior=result, request=unavailable)
        self.assertEqual(later["entries"], result["entries"])
        self.assertEqual(later["reasonCounts"], {"serviceHeld": 1})

    def test_service_failure_rotates_without_losing_unresolved_name(self):
        reg = registry()
        reg["items"]["lead"]["candidate"]["officialArtistNames"] = [
            "Act A", "Act B", "Act C"]
        attempted = []
        def unavailable(path, params):
            attempted.append(params["query"])
            raise HTTPError("https://example.org/private", 503,
                            "unavailable", {}, None)
        first = mb.build(reg, DAY, request=unavailable)
        self.assertEqual(first["namesChecked"], 1)
        self.assertEqual(first["entries"], {})
        self.assertEqual(first["serviceFailureKind"], "http_503")
        self.assertEqual(first["serviceRetryAfterKey"], "act a")
        second = mb.build(reg, DAY, prior=first, request=unavailable)
        self.assertEqual(second["serviceRetryAfterKey"], "act b")
        third = mb.build(reg, DAY, prior=second, request=unavailable)
        fourth = mb.build(reg, DAY, prior=third, request=unavailable)
        self.assertEqual(attempted, ['artist:"Act A"', 'artist:"Act B"',
                                     'artist:"Act C"', 'artist:"Act A"'])
        self.assertEqual(fourth["dueNames"], 3)
        self.assertEqual(fourth["entries"], {})
        self.assertNotIn("example.org", str(fourth))

    def test_recovery_after_failure_keeps_budget_and_reviews_all(self):
        reg = registry()
        reg["items"]["lead"]["candidate"]["officialArtistNames"] = [
            "Act A", "Act B", "Act C"]
        def unavailable(*args):
            raise URLError(TimeoutError())
        first = mb.build(reg, DAY, request=unavailable)
        self.assertEqual(first["serviceFailureKind"], "timeout")
        result = mb.build(reg, DAY, prior=first, limit=2,
                          request=lambda *a: {"count": 0, "artists": []})
        self.assertEqual(set(result["entries"]), {"act b", "act c"})
        self.assertIsNone(result["serviceFailureKind"])
        self.assertIsNone(result["serviceRetryAfterKey"])
        final = mb.build(reg, DAY, prior=result,
                         request=lambda *a: {"count": 0, "artists": []})
        self.assertEqual(set(final["entries"]), {"act a", "act b", "act c"})

    def test_no_event_data_sent_and_query_escaped(self):
        name = 'Act "OR" \\ Other'
        def request(path, params):
            self.assertFalse(path)
            self.assertEqual(set(params), {"query", "limit"})
            self.assertEqual(params["query"], 'artist:"Act \\"OR\\" \\\\ Other"')
            return {"count": 0, "artists": []}
        self.assertEqual(mb.research(name, request)["status"], "not_found")

    def test_homepage_handoff_is_quarantined_and_safe(self):
        result = mb.build(registry(), DAY, request=lookup)
        entry = result["entries"][mb.exact(NAME)]
        entry["homepageHints"].append("https://127.0.0.1/")
        row = {"key": frontier.identity("artist", NAME), "name": NAME,
               "researchOnly": True}
        report = {"schema": frontier.SCHEMA, "publicationAllowed": False,
                  "artistResearch": [row], "venueResearch": []}
        seeds = sites.select_sources(report, registry(), DAY,
                                     musicbrainz=result)
        self.assertEqual(len(seeds), 1)
        self.assertEqual(seeds[0]["url"], URL)
        self.assertFalse(seeds[0]["claimedOfficial"])
        entry["identityVerified"] = True
        self.assertEqual(sites.select_sources(report, registry(), DAY,
                         musicbrainz=result), [])

    def test_detail_identity_mismatch(self):
        def request(path, params):
            result = lookup(path, params)
            if path:
                result["name"] = "Different Act"
            return result
        result = mb.build(registry(), DAY, request=request)
        self.assertEqual(result["entries"][mb.exact(NAME)]["status"],
                         "identity_held")


if __name__ == "__main__":
    unittest.main()
