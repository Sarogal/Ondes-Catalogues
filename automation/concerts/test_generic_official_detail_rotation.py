"""Regression: rotate all first-party venue links without extra requests."""
from __future__ import annotations

import datetime as dt
import unittest

import discover


class GenericVenueLinkRotationTests(unittest.TestCase):
    def test_three_slots_cover_entire_first_party_programme(self):
        day = dt.date(2026, 11, 19)
        links = [
            "https://official.example/evenement/metal-night-%02d/" % i
            for i in range(14)]
        visited = set()
        for delta in (0, 1):
            for slot in (0, 1, 2):
                selection = discover.select_generic_official_detail_links(
                    links, day + dt.timedelta(days=delta), slot)
                self.assertLessEqual(len(selection), 3)
                self.assertEqual(len(selection), len(set(selection)))
                visited.update(selection)
        self.assertEqual(visited, set(links))

    def test_never_beyond_three_per_day_and_deterministic(self):
        day = dt.date(2026, 11, 19)
        links = [str(i) for i in range(25)]
        for slot in (0, 1, 2):
            got = discover.select_generic_official_detail_links(
                links, day, slot, limit=3)
            self.assertEqual(len(got), 3)
            self.assertEqual(got, discover.select_generic_official_detail_links(
                links, day, slot, limit=3))
        short = discover.select_generic_official_detail_links(
            ["one", "two"], day, 0, limit=3)
        self.assertEqual(len(short), 2)
        self.assertEqual(set(short), {"one", "two"})

    def test_six_page_reviewed_venue_rotation_covers_forty_eight_links(self):
        # One independently trusted first-party venue with a large agenda.
        # Six distinct reads in each of three daily slots cover all 48
        # event URLs within three calendar days. No artist/date whitelist.
        day = dt.date(2026, 11, 23)
        links = [
            "https://venue.example/evenement/official-show-%02d/" % i
            for i in range(48)]
        visited = []
        for delta in range(3):
            for slot in (0, 1, 2):
                selected = discover.select_generic_official_detail_links(
                    links, day + dt.timedelta(days=delta), slot, limit=6)
                self.assertEqual(len(selected), 6)
                self.assertEqual(len(set(selected)), 6)
                visited.extend(selected)
        self.assertEqual(set(visited), set(links))

    def test_reviewed_venue_still_has_strict_bounded_budget(self):
        day = dt.date(2026, 11, 23)
        links = [str(i) for i in range(70)]
        for slot in range(3):
            selected = discover.select_generic_official_detail_links(
                links, day, slot, limit=6)
            self.assertEqual(len(selected), 6)
            self.assertEqual(selected, discover.select_generic_official_detail_links(
                links, day, slot, limit=6))
        with self.assertRaises(ValueError):
            discover.select_generic_official_detail_links(
                links, day, 0, limit=7)
        with self.assertRaises(ValueError):
            discover.select_generic_official_detail_links(
                links, day, 0, limit=True)

    def test_unpublished_urls_take_precedence_over_forty_five_published(self):
        day = dt.date(2026, 11, 23)
        links = [
            "https://official.example/evenement/band-%02d/" % i
            for i in range(48)]
        known = {("officialUrl", url) for url in links[:45]}
        original_links, original_known = list(links), set(known)
        selected = discover.select_generic_official_detail_links(
            links, day, 1, limit=6, known=known)
        self.assertEqual(len(selected), 6)
        self.assertEqual(len(set(selected)), 6)
        self.assertEqual(set(selected[:3]), set(links[45:]))
        self.assertTrue(all(("officialUrl", link) in known
                            for link in selected[3:]))
        self.assertEqual(links, original_links)
        self.assertEqual(known, original_known)

    def test_unpublished_programmes_rotate_without_published_slot_starvation(self):
        day = dt.date(2026, 11, 23)
        links = [
            "https://official.example/evenement/metal-night-%02d/" % i
            for i in range(40)]
        known = {("officialUrl", url) for url in links[:10]}
        visited = set()
        for delta in range(2):
            for slot in range(3):
                selection = discover.select_generic_official_detail_links(
                    links, day + dt.timedelta(days=delta), slot,
                    limit=6, known=known)
                self.assertLessEqual(len(selection), 6)
                self.assertEqual(len(selection), len(set(selection)))
                self.assertFalse(any(("officialUrl", url) in known
                                     for url in selection))
                visited.update(selection)
        self.assertEqual(visited, set(links[10:]))

    def test_single_unlisted_official_page_remains_eligible_next_day(self):
        day = dt.date(2026, 11, 23)
        links = ["https://official.example/evenement/show-%d/" % i
                 for i in range(48)]
        known = {("officialUrl", url) for url in links[1:]}
        for delta in (0, 1):
            selected = discover.select_generic_official_detail_links(
                links, day + dt.timedelta(days=delta), 0,
                limit=6, known=known)
            self.assertEqual(selected[0], links[0])

    def test_known_artist_tail_url_is_inspected_without_extra_quota(self):
        # The official index may have 47 unrelated entries and one distant
        # show by a catalogue artist. This only changes discovery ordering.
        day = dt.date(2026, 11, 23)
        urls = [
            "https://venue.example/evenement/synthetic-unknown-%02d/" % n
            for n in range(47)
        ] + ["https://venue.example/evenement/eisbrecher/"]
        before = list(urls)
        known = set()
        selected = discover.select_generic_official_detail_links(
            urls, day, 1, limit=6, known=known,
            artist_names=["Eisbrecher", "Unrelated Artist"])
        self.assertEqual(len(selected), 6)
        self.assertEqual(len(selected), len(set(selected)))
        self.assertEqual(selected[0], urls[-1])
        self.assertEqual(urls, before)
        self.assertFalse(any(("officialUrl", url) in known for url in selected))

    def test_known_artist_hints_never_starve_unknown_musicians(self):
        day = dt.date(2026, 11, 23)
        known_bands = [
            "https://venue.example/evenement/famous-band-%02d/" % n
            for n in range(12)
        ]
        unknown_bands = [
            "https://venue.example/evenement/new-artist-%02d/" % n
            for n in range(44)
        ]
        links = known_bands + unknown_bands
        original = list(links)
        covered_known, covered_unknown = set(), set()
        for delta in range(5):
            for slot in (0, 1, 2):
                selected = discover.select_generic_official_detail_links(
                    links, day + dt.timedelta(days=delta), slot,
                    limit=6, known=set(),
                    artist_names=["Famous Band", "Unrelated Artist"])
                self.assertEqual(len(selected), 6)
                self.assertEqual(len(set(selected)), 6)
                self.assertLessEqual(len(set(selected) & set(known_bands)), 2)
                covered_known.update(set(selected) & set(known_bands))
                covered_unknown.update(set(selected) & set(unknown_bands))
        self.assertEqual(covered_known, set(known_bands))
        self.assertEqual(covered_unknown, set(unknown_bands))
        self.assertEqual(links, original)

    def test_published_artist_url_cannot_preempt_unknown_gig(self):
        day = dt.date(2026, 11, 23)
        published = "https://venue.example/evenement/eisbrecher/"
        unknown = [
            "https://venue.example/evenement/first-show-%02d/" % n
            for n in range(12)
        ]
        selected = discover.select_generic_official_detail_links(
            [published] + unknown, day, 0, limit=6,
            known={("officialUrl", published)}, artist_names=["Eisbrecher"])
        self.assertEqual(len(selected), 6)
        self.assertNotIn(published, selected)

    def test_empty_duplicate_and_invalid_inputs(self):
        day = dt.date(2026, 11, 19)
        self.assertEqual(
            discover.select_generic_official_detail_links([], day, 0), [])
        self.assertEqual(
            len(discover.select_generic_official_detail_links(
                ["a", "a", "b"], day, 0)), 2)
        for bad_day, bad_slot, bad_limit in (
            (None, 0, 3),
            (dt.datetime(2026, 11, 19), 0, 3),
            (day, 3, 3),
            (day, -1, 3),
            (day, 0, 7),
            (day, 0, -1),
        ):
            with self.subTest(args=(bad_day, bad_slot, bad_limit)):
                with self.assertRaises(ValueError):
                    discover.select_generic_official_detail_links(
                        ["a"], bad_day, bad_slot, limit=bad_limit)

    def test_no_per_concert_allowlist_or_approval_is_generated(self):
        day = dt.date(2026, 11, 19)
        urls = ["/evenement/one/", "/evenement/two/"]
        snapshot = list(urls)
        chosen = discover.select_generic_official_detail_links(
            urls, day, 1)
        self.assertEqual(urls, snapshot)
        self.assertEqual(set(chosen), set(urls))
        self.assertTrue(all(isinstance(url, str) for url in chosen))


if __name__ == "__main__":
    unittest.main()
