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
    def test_large_explicit_roster_is_not_truncated_by_network_budget(self):
        reg = registry()
        names = [f"Unknown Act {i:03d}" for i in range(65)]
        reg["items"]["lead"]["candidate"].update(
            officialArtistNames=names, leadArtist=names[0])
        tasks = mb.candidate_tasks(reg, DAY)
        self.assertEqual(len(tasks), 65)
        self.assertEqual({task[0] for task in tasks.values()}, {0})
        self.assertEqual({task[2] for task in tasks.values()}, set(names))
        calls = []
        def request(path, params):
            calls.append(params["query"])
            return {"count": 0, "artists": []}
        previous = None
        for _ in range(6):
            previous = mb.build(reg, DAY, prior=previous, request=request)
            self.assertLessEqual(previous["namesChecked"], mb.MAX_NAMES)
            self.assertFalse(previous["publicationAllowed"])
        self.assertEqual(len(calls), 65)
        self.assertEqual(len(set(calls)), 65)
        self.assertEqual(len(previous["entries"]), 65)

    def test_oversized_identity_is_held_without_blocking_next_artist(self):
        reg = registry()
        reg["items"]["lead"]["candidate"]["officialArtistNames"] = ["Act A", "Act B", "Act C"]
        calls = []
        def bounded(*args):
            name = args[1]["query"]
            calls.append(name)
            if "Act A" in name:
                raise mb.OversizedDirectoryResponse("private detail never retained")
            return {"count": 0, "artists": []}
        result = mb.build(reg, DAY, request=bounded)
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
        cached = mb.build(reg, DAY, prior=result,
                                request=lambda *a: self.fail("same-day retry"))
        self.assertEqual(cached["namesChecked"], 0)

    def test_repeated_oversized_responses_stop_at_two_and_keep_other_names_due(self):
        reg = registry()
        reg["items"]["lead"]["candidate"]["officialArtistNames"] = ["Act A", "Act B", "Act C"]
        def oversized(*args):
            raise mb.OversizedDirectoryResponse("bounded")
        result = mb.build(reg, DAY, request=oversized)
        self.assertEqual(result["namesChecked"], 2)
        self.assertEqual(result["serviceFailureKind"], "oversized_response")
        self.assertEqual(set(result["entries"]), {"act a", "act b"})
        self.assertEqual(result["serviceRetryAfterKey"], "act b")
        recovered = mb.build(reg, DAY, prior=result,
                                request=lambda *a: {"count": 0, "artists": []})
        self.assertEqual(recovered["namesChecked"], 1)
        self.assertEqual(recovered["entries"]["act c"]["status"], "not_found")
        self.assertFalse(recovered["publicationAllowed"])

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

    def test_research_priority_preserves_unknown_names_and_skips_fallback_labels(self):
        reg = registry()
        base = reg["items"]["lead"]["candidate"]
        reg["items"] = {}
        def add(key, name, date, named):
            row = {**base, "date": date, "leadArtist": name}
            row.pop("officialArtistNames", None)
            if named:
                row["officialArtistNames"] = [name]
            reg["items"][key] = {"status": "pending_review", "candidate": row}
        add("one", "1RE PARTIE", "2026-11-25", False)
        add("two", "1ère partie", "2026-11-25", False)
        add("three", "Z New Band", "2026-12-01", True)
        add("four", "A Solo Artist", "2027-01-01", True)
        add("five", "3rd Eye", "2026-11-25", False)
        add("six", "Première Partie", "2027-02-01", True)
        queried = []
        def request(path, params):
            queried.append(params["query"])
            return {"count": 0, "artists": []}
        result = mb.build(reg, DAY, limit=2, request=request)
        self.assertEqual(result["eligibleNames"], 4)
        self.assertEqual(queried, ['artist:"Z New Band"', 'artist:"A Solo Artist"'])
        result = mb.build(reg, DAY, prior=result, request=request)
        self.assertEqual(queried[2:], ['artist:"Première Partie"', 'artist:"3rd Eye"'])
        self.assertEqual(result["approvalsProposed"], 0)

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
