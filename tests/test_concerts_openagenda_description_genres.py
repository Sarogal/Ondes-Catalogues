"""Original OpenAgenda description: first-party genre evidence without tags.

Synthetic source data only. This does not assume a second concert website,
invent individual band genres or bypass the Publisher's independent replay.
"""
import json
import unittest
from unittest import mock

from automation.concerts import openagenda_official_concert as oa
from automation.concerts import approval_preflight
from scripts import concerts_cloud_sync as publisher
import test_concerts_openagenda_new_site_publisher as fixture
import test_concerts_dynamic_existing_venue as existing


def official_record(*, description, keywords=None, **changes):
    row = json.loads(fixture.official())["events"][0]
    row["keywords"] = keywords
    row["description"] = {"fr": description}
    row.update(changes)
    return json.dumps({"total": 1, "events": [row]}, ensure_ascii=False)


def check(raw):
    location = fixture.producer._unpublished_location(
        json.loads(raw)["events"][0])
    return oa.verified_export(
        raw, fixture.URL, fixture.DAY, location,
        agenda_uid=fixture.AGENDA_UID, event_uid=fixture.EVENT_UID)


class OpenAgendaDescriptionGenreTests(unittest.TestCase):

    def test_named_guest_label_is_not_part_of_artist_identity(self):
        names, genres = check(official_record(
            description="Black metal et death metal.",
            keywords={"fr": ["black metal", "death metal"]},
            title={"fr": "PANZERFAUST + guests : NEXION"}))
        self.assertEqual(names, ["PANZERFAUST", "NEXION"])
        self.assertEqual(oa._bill({"@type": "MusicEvent",
            "name": "Example Band + Guest House"}), ["Example Band", "Guest House"])

    def test_pipe_title_requires_separate_visible_artist_evidence(self):
        raw = official_record(description="Concert punk.",
            keywords={"fr": ["punk"]},
            title={"fr": "GAGNER DE L'ARGENT | WTAZZZ"},
            longDescription={"fr": "<h2>GAGNER DE L'ARGENT</h2><p>Collectif punk.</p><h2>WTAZZZ</h2><p>Un autre groupe.</p>"})
        self.assertEqual(check(raw)[0], ["GAGNER DE L'ARGENT", "WTAZZZ"])
        for body in ("<p>GAGNER DE L'ARGENT | WTAZZZ</p>",
                     "<p>GAGNER DE L'ARGENT</p><span hidden>WTAZZZ</span>"):
            raw = official_record(description="Concert punk.",
                keywords={"fr": ["punk"]},
                title={"fr": "GAGNER DE L'ARGENT | WTAZZZ"},
                longDescription={"fr": body})
            self.assertEqual(check(raw)[0], ["GAGNER DE L'ARGENT | WTAZZZ"])

    def test_original_visible_description_accepts_punk_and_metalcore_without_keywords(self):
        names, genres = check(official_record(
            description="<p>Deux groupes de metalcore et punk sur scène.</p>",
            keywords={}))
        self.assertEqual(names[0], fixture.fixture.BANDS[0])
        self.assertIn("metalcore", genres)
        self.assertIn("punk", genres)
        self.assertLessEqual(len(genres), 8)

    def test_publisher_replays_original_description_without_second_domain(self):
        previous_geo = publisher.NEW_REFERENCE_GEO_SOURCES.pop(
            existing.VENUE_ID, None)
        self.assertIsNotNone(previous_geo)
        self.addCleanup(lambda: publisher.NEW_REFERENCE_GEO_SOURCES.__setitem__(
            existing.VENUE_ID, previous_geo))
        base = fixture.geo_fixture.test_catalogue()
        previous = fixture.geo_fixture.before()
        raw = official_record(
            description="<p>Concert de Death Metal et punk.</p>",
            keywords={})
        geo_fetch, calls = fixture.geo_fixture.fetch_for()

        def fetch(url, cache):
            calls.append(url)
            if url == fixture.OFFICIAL_EXPORT:
                return raw
            return geo_fetch(url, cache)

        proposed, report = fixture.producer.build(
            fixture.observation(), base, previous, fixture.TODAY, fetch=fetch)
        self.assertEqual(report["stateCounts"], {
            "publisher_bound_openagenda_event_site_pair": 1}, report)
        self.assertEqual(len(proposed["approvals"]), 1)
        self.assertEqual(len(proposed["venueApprovals"]), 1)
        with mock.patch.object(fixture.signer.probe, "safe_fetch",
                               side_effect=fetch):
            self.assertEqual(len(approval_preflight.check_append_only(
                previous, proposed, fixture.TODAY)), 1)
            published, stats = publisher.merge(
                base, base, proposed, fixture.TODAY)
        self.assertEqual(stats["newEvents"], 1, stats)
        self.assertEqual(stats["newVenues"], 1, stats)
        self.assertEqual(published["events"][-1]["genres"],
                         proposed["approvals"][0]["event"]["genres"])
        self.assertIn(fixture.OFFICIAL_EXPORT, calls)
        self.assertNotIn(fixture.URL, calls,
                         "second concert-page lookup is not required")

    def test_hidden_or_nonmusical_description_is_never_genre_evidence(self):
        for raw in (
            "<script>Death Metal</script><p>Soirée techno.</p>",
            "<p>Hardcore techno, hardtek, gabber et frenchcore.</p>",
            "<p>Concert instrumental de musique classique.</p>",
            "<p>Rock généraliste.</p>",
            "<template>Punk</template><p>DJ techno.</p>",
        ):
            with self.subTest(description=raw):
                with self.assertRaisesRegex(
                        ValueError, "genre evidence missing"):
                    check(official_record(description=raw, keywords=None))

    def test_wrong_uid_cancelled_wrong_date_and_wrong_agenda_remain_blocked(self):
        raw = official_record(
            description="<p>Concert punk et metalcore</p>", keywords={})
        record = json.loads(raw)["events"][0]
        for changes in (
            {"uid": 123456789},
            {"origin": {"uid": 321123, "slug": "shotgun"}},
            {"status": 2},
            {"firstDate": "2027-12-01"},
        ):
            with self.subTest(changes=changes):
                changed = dict(record, **changes)
                with self.assertRaises(ValueError):
                    check(json.dumps({"total": 1, "events": [changed]}))

    def test_venue_name_is_not_genre_evidence(self):
        for name, description in (
            ("Punk Paradise", "Soirée chaâbi au Punk Paradise."),
            ("Metal Hall", "Concert de jazz au METAL HALL."),
            ("Rock Club", "Soirée raï au Rock Club."),
        ):
            with self.subTest(name=name):
                raw = official_record(description=description,
                                      keywords={"fr": ["chaâbi", "raï"]})
                record = json.loads(raw)["events"][0]
                record["location"]["name"] = name
                with self.assertRaisesRegex(ValueError, "genre evidence missing"):
                    check(json.dumps({"total": 1, "events": [record]}))

    def test_separate_musical_genre_at_genre_named_venue_remains_valid(self):
        raw = official_record(
            description="Concert de punk rock au Punk Paradise.", keywords={})
        record = json.loads(raw)["events"][0]
        record["location"]["name"] = "Punk Paradise"
        _, genres = check(json.dumps({"total": 1, "events": [record]}))
        self.assertTrue(any("punk" in g for g in genres))

    def test_hidden_inline_description_is_not_genre_evidence(self):
        for fragment in ('<span hidden>Punk</span>',
                         '<span aria-hidden="true">Metalcore</span>',
                         '<span style="display:none">Death metal</span>'):
            with self.subTest(fragment=fragment):
                with self.assertRaisesRegex(ValueError, "genre evidence missing"):
                    check(official_record(description=fragment + "<p>Soirée jazz.</p>"))


    def test_non_nominative_support_never_becomes_an_artist(self):
        for label in ("GUESTS", "Special Guest", "TBA",
                      "Première partie à confirmer", "Invité surprise",
                      "Spezialgast", "Invitados"):
            with self.subTest(label=label):
                raw = official_record(description="Concert post punk.",
                    keywords={"fr": ["post punk"]},
                    title={"fr": "Example Band + " + label})
                names, genres = check(raw)
                self.assertEqual(names, ["Example Band"])
                self.assertEqual(genres, ["post punk"])

    def test_named_performers_and_order_preserved(self):
        names = oa._bill({"@type": "MusicEvent",
            "name": "Example Band + GUESTS + Guest House + Other Band",
            "performer": [{"@type": "MusicGroup", "name": "Example Band"},
                          {"@type": "MusicGroup", "name": "GUESTS"},
                          {"@type": "MusicGroup", "name": "Guest House"}]})
        self.assertEqual(names, ["Example Band", "Guest House", "Other Band"])

    def test_placeholder_only_and_contradictory_named_bill_rejected(self):
        for title, performers in (
            ("GUESTS + TBA", []),
            ("GUESTS", []),
            ("Example Band + GUESTS",
             [{"@type": "MusicGroup", "name": "Different Band"}]),
        ):
            with self.subTest(title=title):
                with self.assertRaises(ValueError):
                    oa._bill({"@type": "MusicEvent", "name": title,
                              "performer": performers})

    def test_keyword_genre_still_takes_precedence_over_description(self):
        _, genres = check(official_record(
            description="<p>Simple rencontre publique.</p>",
            keywords={"fr": ["Black Metal"]}))
        self.assertEqual(genres, ["Black Metal"])


if __name__ == "__main__":
    unittest.main()
