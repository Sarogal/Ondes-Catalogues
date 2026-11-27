"""No-network tests: unknown performers remain research, never publisher proof."""
import copy
import datetime as dt
import json
import unittest

import open_world_artist_genre as research

DAY = dt.date(2026, 11, 24)
URL = "https://newact.example.org/music"
NAME = "New Act"
PROFILE = ('<script type="application/ld+json">'
           + json.dumps({"@type": "MusicGroup", "name": NAME,
                         "genre": ["Death Metal", "Hardcore Techno"]})
           + '</script>')


def registry(hints=None, *, source="open_world_visible_card_research"):
    candidate = {
        "candidateId": "PRIVATE-LEAD", "date": "2027-02-10",
        "source": source, "sourceUrl": "https://official-venue.example.org/event",
        "officialArtistNames": [NAME],
        "leadArtist": NAME,
        "artistWebsiteHints": hints if hints is not None
                              else [{"name": NAME, "url": URL}],
        "publicationAllowed": False, "reviewRequired": True,
    }
    return {"schema": "grossesondes.concert.intake.v1",
            "items": {"key": {"status": "pending_review",
                              "candidate": candidate}}}


class OpenWorldArtistGenreTests(unittest.TestCase):
    def test_last_artist_in_large_named_bill_has_own_profile_research(self):
        names = [f"Unknown Act {i:03d}" for i in range(65)]
        reg = registry([{"name": names[-1], "url": URL}])
        reg["items"]["key"]["candidate"].update(
            officialArtistNames=names, leadArtist=names[0])
        sources, ambiguous = research.candidate_sources(reg, DAY)
        self.assertEqual(ambiguous, 0)
        self.assertEqual([s["name"] for s in sources], [names[-1]])
        profile = PROFILE.replace(NAME, names[-1])
        out = research.build(reg, DAY, fetch=lambda u, cache: profile)
        self.assertEqual(out["profilesRefreshed"], 1)
        fact = next(iter(out["facts"].values()))
        self.assertEqual(fact["artistName"], names[-1])
        self.assertFalse(fact["officialDomainVerified"])
        self.assertFalse(out["publicationAllowed"])

    def test_same_slot_with_memory_reaches_all_new_profiles_before_repeating(self):
        rows = {}
        for i in range(25):
            name = f"Act {i:03d}"
            url = f"https://artist{i}.example.org/"
            item = registry([{"name": name, "url": url}])["items"]["key"]
            item["candidate"].update(leadArtist=name, officialArtistNames=[name])
            rows[str(i)] = item
        batch = {"schema": "grossesondes.concert.intake.v1", "items": rows}
        calls = []
        def fetch(url, cache):
            calls.append(url)
            return PROFILE  # Exact identity fails; no musical fact is promoted.
        previous = None
        for expected in (10, 10, 5, 0):
            previous = research.build(batch, DAY, prior=previous, slot=0,
                                      limit=10, fetch=fetch)
            self.assertEqual(previous["sourcesChecked"], expected)
            self.assertFalse(previous["publicationAllowed"])
        self.assertEqual(len(calls), 25)
        self.assertEqual(len(set(calls)), 25)
        self.assertEqual(previous["profileSourcesInCooldown"], 25)
        self.assertEqual(previous["memoryFactCount"], 0)
        later = research.build(batch, DAY + dt.timedelta(days=1), prior=previous,
                               slot=0, limit=10, fetch=fetch)
        self.assertEqual(later["sourcesChecked"], 10)

    def test_fresh_profile_is_reused_and_new_artist_is_not_delayed(self):
        first = research.build(registry(), DAY, fetch=lambda *a: PROFILE)
        self.assertEqual(first["profilesRefreshed"], 1)
        batch = registry()
        added = registry([{"name": "New Solo", "url": "https://newsolo.example.org/"}])
        item = added["items"]["key"]
        item["candidate"].update(leadArtist="New Solo", officialArtistNames=["New Solo"])
        batch["items"]["new"] = item
        calls = []
        def fetch(url, cache):
            calls.append(url)
            return PROFILE.replace(NAME, "New Solo")
        next_day = research.build(batch, DAY + dt.timedelta(days=1), prior=first, fetch=fetch)
        self.assertEqual(calls, ["https://newsolo.example.org/"])
        self.assertEqual(next_day["memoryFactCount"], 2)
        self.assertEqual(next_day["profilesRefreshed"], 1)
        self.assertEqual(next_day["profileSourcesInCooldown"], 1)
        self.assertEqual(next_day["officialDomainsAuthenticated"], 0)
        due = research.build(registry(), DAY + dt.timedelta(days=14),
                             prior=next_day, fetch=lambda *a: PROFILE)
        self.assertEqual(due["sourcesChecked"], 1)
        self.assertEqual(due["profilesRefreshed"], 1)
        self.assertFalse(due["publicationAllowed"])

    def test_legacy_fact_seeds_cooldown_without_granting_trust(self):
        first = research.build(registry(), DAY, fetch=lambda *a: PROFILE)
        first.pop("profileAttempts")
        next_day = research.build(registry(), DAY + dt.timedelta(days=1),
                                  prior=first, fetch=lambda *a: self.fail("cached"))
        self.assertEqual(next_day["sourcesChecked"], 0)
        self.assertEqual(next_day["facts"], first["facts"])
        self.assertEqual(next_day["officialDomainsAuthenticated"], 0)
        self.assertEqual(next_day["approvalsProposed"], 0)

    def test_future_or_invalid_attempt_cannot_suppress_research(self):
        first = research.build(registry(), DAY, fetch=lambda *a: PROFILE)
        key = next(iter(first["profileAttempts"]))
        for invalid in (
                {"status": "read", "checkedAt": (DAY + dt.timedelta(days=10)).isoformat()},
                {"status": "invented", "checkedAt": DAY.isoformat()},
                {"status": "read", "checkedAt": []},
        ):
            with self.subTest(invalid=invalid):
                prior = {**first, "profileAttempts": {key: invalid}}
                out = research.build(registry(), DAY, prior=prior, fetch=lambda *a: PROFILE)
                self.assertEqual(out["sourcesChecked"], 1)
                self.assertFalse(out["publicationAllowed"])

    def test_unknown_artist_self_declared_musicgroup_is_retained_without_trust(self):
        seen = []
        original = registry()
        saved = copy.deepcopy(original)
        def fetch(url, cache):
            seen.append(url)
            return PROFILE
        result = research.build(original, DAY, fetch=fetch)
        self.assertEqual(seen, [URL])
        self.assertEqual(result["profilesRefreshed"], 1)
        self.assertEqual(result["memoryFactCount"], 1)
        item = next(iter(result["facts"].values()))
        self.assertEqual(item["artistName"], NAME)
        self.assertEqual(item["genres"], ["Death Metal"])
        self.assertFalse(item["officialDomainVerified"])
        self.assertFalse(item["eventDateLocationAndLineupProved"])
        self.assertFalse(result["publicationAllowed"])
        self.assertEqual(result["approvalsProposed"], 0)
        self.assertEqual(result["officialDomainsAuthenticated"], 0)
        self.assertEqual(original, saved)

    def test_never_inherit_other_artist_or_concert_genre(self):
        for html in (
            '<h1>New Act</h1><p>Death Metal concert</p>',
            PROFILE.replace('"name": "New Act"', '"name": "Other Act"'),
            PROFILE.replace('"Death Metal"', '"Jazz"'),
            PROFILE + PROFILE.replace('"Death Metal"', '"Thrash Metal"'),
        ):
            out = research.build(registry(), DAY, fetch=lambda u, cache: html)
            self.assertEqual(out["memoryFactCount"], 0)
            self.assertEqual(out["reasonCounts"], {"profileHeld": 1})

    def test_unknown_artist_linked_bio_is_research_only(self):
        tour = ('<html><title>New Act tour</title>'
                '<a href="/bio">Bio</a></html>')
        biog = ('<html><title>Bio New Act</title><main><p>'
                'New Act are a band with their heavy rock sound.'
                '</p></main></html>')
        calls = []
        def fetch(url, cache):
            calls.append(url)
            return tour if url == URL else biog
        out = research.build(registry(), DAY, fetch=fetch)
        fact = next(iter(out["facts"].values()))
        self.assertEqual(calls, [URL, "https://newact.example.org/bio"])
        self.assertEqual(fact["genres"], ["Heavy Rock"])
        self.assertEqual(fact["genreEvidenceUrl"],
                         "https://newact.example.org/bio")
        self.assertEqual(fact["evidenceKind"],
                         "unverified-origin-artist-visible-linked-bio")
        self.assertFalse(fact["officialDomainVerified"])
        next_day = research.build(
            {"schema": "grossesondes.concert.intake.v1", "items": {}},
            DAY + dt.timedelta(days=1), prior=out)
        self.assertEqual(next_day["memoryFactCount"], 1)

    def test_direct_named_artist_description_without_directory_or_bio_link(self):
        for sentence, genre in (
            ("New Act is a death metal band from France.", "Death Metal"),
            ("New Act est un groupe de punk basé à Lyon.", "Punk"),
        ):
            html = f"<title>New Act | Official website</title><main><p>{sentence}</p></main>"
            calls = []
            def fetch(url, cache):
                calls.append(url)
                return html
            out = research.build(registry(), DAY, fetch=fetch)
            self.assertEqual(calls, [URL])
            self.assertEqual(out["profilesRefreshed"], 1)
            fact = next(iter(out["facts"].values()))
            self.assertEqual(fact["genres"], [genre])
            self.assertEqual(fact["genreEvidenceUrl"], URL)
            self.assertEqual(fact["evidenceKind"],
                             "unverified-origin-artist-visible-direct-description")
            self.assertFalse(fact["officialDomainVerified"])
            self.assertFalse(fact["publicationAllowed"])
            self.assertEqual(out["approvalsProposed"], 0)
            empty = {"schema": "grossesondes.concert.intake.v1", "items": {}}
            retained = research.build(empty, DAY, prior=out)
            self.assertEqual(retained["facts"], out["facts"])

    def test_direct_description_rejects_event_influences_negation_other_identity(self):
        for page in (
            "<title>New Act</title><p>New Act plays with a death metal band.</p>",
            "<title>New Act</title><p>New Act is not a death metal band.</p>",
            "<title>New Act</title><p>Other Act is a death metal band.</p>",
            "<title>Other Act</title><p>New Act is a death metal band.</p>",
            "<title>New Act</title><footer><p>New Act is a death metal band.</p></footer>",
            "<title>New Act</title><p>New Act is a hardcore techno group.</p>",
            "<title>New Act</title><p>New Act is a metal band tribute act.</p>",
            "<title>New Act</title><p>New Act est un groupe de metal symphonique électronique.</p>",
            PROFILE.replace('"Death Metal"', '"Jazz"') +
                "<title>New Act</title><p>New Act is a death metal band.</p>",
        ):
            with self.subTest(page=page):
                result = research.build(registry(), DAY, fetch=lambda *a: page)
                self.assertEqual(result["memoryFactCount"], 0)
                self.assertEqual(result["approvalsProposed"], 0)

    def test_linked_bio_cross_domain_does_not_leak_or_qualify(self):
        page = '<a href="https://another.example.org/bio">Bio</a>'
        result = research.build(registry(), DAY,
                                fetch=lambda u, cache: page)
        self.assertEqual(result["memoryFactCount"], 0)
        self.assertEqual(result["reasonCounts"], {"profileHeld": 1})

    def test_unsafe_and_unattached_performer_urls_never_fetched(self):
        for hints in (
            [{"name": NAME, "url": "https://127.0.0.1/admin"}],
            [{"name": "Different Performer", "url": URL}],
            [{"name": NAME, "url": "http://newact.example.org/music"}],
        ):
            out = research.build(registry(hints), DAY,
                                 fetch=lambda *a: self.fail("network"))
            self.assertEqual(out["candidateArtistSources"], 0)
        # Two unrelated sites claiming the same artist are not coalesced.
        both = registry([{"name": NAME, "url": URL},
                         {"name": NAME, "url": "https://clone.example.org/"}])
        out = research.build(both, DAY,
                             fetch=lambda *a: self.fail("ambiguous"))
        self.assertEqual(out["ambiguousArtistSourcesHeld"], 1)

    def test_explicit_same_origin_homepage_resolves_navigation_not_identity(self):
        home = "https://newact.example.org/"
        hints = [{"name": NAME, "url": URL}, {"name": NAME, "url": home},
                 {"name": NAME, "url": home + "tour"}]
        seen = []
        def fetch(url, cache):
            seen.append(url)
            return PROFILE
        result = research.build(registry(hints), DAY, fetch=fetch)
        self.assertEqual(seen, [home])
        self.assertEqual(result["ambiguousArtistSourcesHeld"], 0)
        self.assertEqual(result["profilesRefreshed"], 1)
        self.assertEqual(result["officialDomainsAuthenticated"], 0)
        self.assertFalse(result["publicationAllowed"])
        for competing in (
            hints + [{"name": NAME, "url": "https://clone.example.org/"}],
            [hints[0], hints[2]],
            hints + [{"name": NAME, "url": "https://other.newact.example.org/"}],
        ):
            out = research.build(registry(competing), DAY,
                                 fetch=lambda *a: self.fail("ambiguous"))
            self.assertEqual(out["ambiguousArtistSourcesHeld"], 1)

    def test_memory_survives_missing_next_day_without_converting_to_authority(self):
        first = research.build(registry(), DAY,
                               fetch=lambda u, cache: PROFILE)
        empty = {"schema": "grossesondes.concert.intake.v1", "items": {}}
        second = research.build(empty, DAY + dt.timedelta(days=1),
                                prior=first, fetch=lambda *a: self.fail("network"))
        self.assertEqual(second["sourcesChecked"], 0)
        self.assertEqual(second["facts"], first["facts"])
        self.assertEqual(second["memoryFactCount"], 1)
        self.assertFalse(second["publicationAllowed"])
        bad = copy.deepcopy(first)
        bad["publicationAllowed"] = True
        with self.assertRaises(ValueError):
            research.build(empty, DAY, prior=bad)

    def test_artist_official_tour_is_hint_not_verified_source(self):
        row = registry([], source="artist_official_tour")
        row["items"]["key"]["candidate"]["sourceUrl"] = URL
        out = research.build(row, DAY, fetch=lambda u, cache: PROFILE)
        self.assertEqual(out["profilesRefreshed"], 1)
        self.assertFalse(next(iter(out["facts"].values()))["officialDomainVerified"])

    def test_rotation_and_bounded_budget(self):
        rows = {}
        for i in range(25):
            lead = registry([{"name": NAME, "url": f"https://artist{i}.example.org/"}])
            lead["items"]["key"]["candidate"]["leadArtist"] = "Act " + str(i)
            lead["items"]["key"]["candidate"]["officialArtistNames"] = ["Act " + str(i)]
            lead["items"]["key"]["candidate"]["artistWebsiteHints"][0]["name"] = "Act " + str(i)
            rows[str(i)] = lead["items"]["key"]
        batch = {"schema": "grossesondes.concert.intake.v1", "items": rows}
        a = research.build(batch, DAY, limit=10, slot=0,
                           fetch=lambda u, cache: PROFILE)
        b = research.build(batch, DAY, limit=10, slot=1,
                           fetch=lambda u, cache: PROFILE)
        self.assertEqual(a["sourcesChecked"], 10)
        self.assertEqual(b["sourcesChecked"], 10)
        self.assertEqual(a["profilesRefreshed"], 0)  # Names do not match profile
        self.assertEqual(b["profilesRefreshed"], 0)
        with self.assertRaises(ValueError):
            research.build(batch, DAY, limit=25)

class DirectoryArtistResearchTests(unittest.TestCase):
    def directory(self, *, wiki=False, **changes):
        item = {"status": "hypothesis", "artistName": NAME,
                "checkedAt": DAY.isoformat(), "publicationAllowed": False,
                "identityVerified": False, "homepageHints": [URL],
                "genres": ["Black Metal"]}
        item.update({"qid": "Q123"} if wiki else
                    {"mbid": "12345678-1234-1234-1234-123456789abc"})
        item.update(changes)
        return {"schema": research.wd.SCHEMA if wiki else research.mb.SCHEMA,
                "publicationAllowed": False, "approvalsProposed": 0,
                "entries": {research.mb.exact(NAME): item}}

    def test_directory_lead_is_researched_without_importing_directory_genres(self):
        for wiki in (False, True):
            with self.subTest(wiki=wiki):
                kwargs = {"wikidata" if wiki else "musicbrainz": self.directory(wiki=wiki)}
                calls = []
                def fetch(url, cache):
                    calls.append(url)
                    return PROFILE
                result = research.build(registry([]), DAY, fetch=fetch, **kwargs)
                self.assertEqual(calls, [URL])
                self.assertEqual(result["directoryHintSources"], 1)
                self.assertEqual(result["directoryHintSourcesChecked"], 1)
                fact = next(iter(result["facts"].values()))
                self.assertEqual(fact["genres"], ["Death Metal"])
                self.assertFalse(fact["officialDomainVerified"])
                self.assertEqual(result["approvalsProposed"], 0)

    def test_stale_future_forged_mismatched_and_unsafe_directory_rows_ignored(self):
        for changes in (
            {"checkedAt": "2026-10-01"}, {"checkedAt": "2026-11-25"},
            {"identityVerified": True}, {"publicationAllowed": True},
            {"artistName": "Different Act"}, {"mbid": "bad"},
            {"homepageHints": ["https://127.0.0.1/"]},
        ):
            with self.subTest(changes=changes):
                result = research.build(registry([]), DAY,
                    musicbrainz=self.directory(**changes),
                    fetch=lambda *a: self.fail("unsafe or stale hint"))
                self.assertEqual(result["candidateArtistSources"], 0)

    def test_competing_directory_urls_held_but_direct_event_hint_kept(self):
        other = self.directory(wiki=True, homepageHints=["https://clone.example.org/"])
        args = {"musicbrainz": self.directory(), "wikidata": other}
        result = research.build(registry([]), DAY, **args,
                               fetch=lambda *a: self.fail("ambiguous"))
        self.assertEqual(result["ambiguousArtistSourcesHeld"], 1)
        result = research.build(registry(), DAY, **args, fetch=lambda *a: PROFILE)
        self.assertEqual(result["profilesRefreshed"], 1)
        self.assertEqual(result["directoryHintSources"], 0)

    def test_directory_homepage_resolves_same_origin_direct_paths_only(self):
        home = "https://newact.example.org/"
        hints = [{"name": NAME, "url": URL},
                 {"name": NAME, "url": home + "tour"}]
        other = self.directory(wiki=True, homepageHints=["https://clone.example.org/"])
        calls = []
        def fetch(url, cache):
            calls.append(url)
            return PROFILE
        result = research.build(registry(hints), DAY, fetch=fetch,
                                musicbrainz=self.directory(homepageHints=[home]),
                                wikidata=other)
        self.assertEqual(calls, [home])
        self.assertEqual(result["ambiguousArtistSourcesHeld"], 0)
        self.assertEqual(result["profilesRefreshed"], 1)
        self.assertEqual(result["officialDomainsAuthenticated"], 0)
        self.assertEqual(result["approvalsProposed"], 0)
        self.assertFalse(result["publicationAllowed"])
        self.assertFalse(next(iter(result["facts"].values()))["officialDomainVerified"])
        for urls in (["https://clone.example.org/"], [home + "bio"],
                     [home + "?other=1"]):
            out = research.build(registry(hints), DAY,
                musicbrainz=self.directory(homepageHints=urls),
                fetch=lambda *a: self.fail("ambiguous"))
            self.assertEqual(out["ambiguousArtistSourcesHeld"], 1)
        competing = hints + [{"name": NAME, "url": "https://clone.example.org/tour"}]
        out = research.build(registry(competing), DAY,
            musicbrainz=self.directory(homepageHints=[home]),
            fetch=lambda *a: self.fail("competing origins"))
        self.assertEqual(out["ambiguousArtistSourcesHeld"], 1)
        calls.clear()
        research.build(registry(), DAY, fetch=fetch,
                       musicbrainz=self.directory(homepageHints=[home]))
        self.assertEqual(calls, [URL])

    def test_contradictory_structured_profile_cannot_be_hidden_by_biography(self):
        html = PROFILE + PROFILE.replace('"Death Metal"', '"Thrash Metal"') + '<a href="/bio">Bio</a>'
        def fetch(url, cache):
            self.assertEqual(url, URL)
            return html
        result = research.build(registry(), DAY, fetch=fetch)
        self.assertEqual(result["memoryFactCount"], 0)

if __name__ == "__main__":
    unittest.main()
