"""Real Publisher regression: one official OpenAgenda event + a NEW named site.

The discovery cannot self-approve. Every event/agenda UID is freshly fetched;
the location comes from independent French BAN plus a named OSM feature.
This test must make both the private preflight and production merge pass.
"""
import copy
import datetime as dt
import json
import unittest
from unittest import mock

from automation.concerts import approval_preflight
from automation.concerts import openagenda_new_site_proposals as producer
from automation.concerts import openagenda_official_concert as oa
from scripts import concert_dynamic_new_site_source as signer
from scripts import concerts_cloud_sync as publisher
import test_concerts_dynamic_new_site_source as fixture
import test_concerts_self_attributed_unknown_venue as geo_fixture
import test_concerts_dynamic_existing_venue as existing

TODAY = dt.date(2026, 11, 22)
DAY = fixture.DAY
URL = "https://openagenda.com/shotgun/events/eight-unknown-metal-bands"
AGENDA_UID, EVENT_UID = "9969608", "87654321"
OFFICIAL_EXPORT = oa.official_export_url(AGENDA_UID, EVENT_UID)


def observation(**changes):
    item = {
        "candidateId": "oa:synthetic-new-venue",
        "source": "agenda_officiel_openagenda",
        "sourceUrl": URL, "sourcePage": URL,
        "eventDetailUrl": URL,
        "openAgendaUid": AGENDA_UID, "openAgendaEventUid": EVENT_UID,
        "date": DAY, "name": " + ".join(fixture.BANDS),
        "leadArtist": fixture.BANDS[0],
        "venue": "Place Libre", "city": "Tours",
        "reviewBucket": "genre_tag_review",
        "publicationAllowed": False, "reviewRequired": True,
        "possibleExistingConcert": False,
    }
    item.update(changes)
    return {
        "schema": "grossesondes.concert.intake.v1",
        "items": {"new": {
            "status": "pending_review", "stableObservations": 1,
            "candidate": item,
        }},
    }


def official(**changes):
    record = {
        "uid": 87654321, "slug": "eight-unknown-metal-bands",
        "origin": {"uid": 9969608, "slug": "shotgun"},
        "status": 1, "firstDate": DAY, "lastDate": DAY,
        "title": {"fr": " + ".join(fixture.BANDS)},
        "keywords": {"fr": ["Death Metal", "punk"]},
        "location": {
            "name": "Place Libre", "city": "Tours",
            "address": "Place Libre, 37000 Tours, France",
            "postalCode": "37000", "countryCode": "fr",
            "latitude": 47.395, "longitude": 0.688,
        },
    }
    record.update(changes)
    return json.dumps({"total": 1, "events": [record]}, ensure_ascii=False)


def official_get(*, changes=None, gov=None, osm=None):
    geo_get, geo_seen = geo_fixture.fetch_for(government=gov, osm=osm)
    body = official(**(changes or {}))
    reads = []
    def fetch(url, cache):
        reads.append(url)
        if url == OFFICIAL_EXPORT:
            return body
        return geo_get(url, cache)
    return fetch, reads


class OpenAgendaNewNamedSitePublisherTests(unittest.TestCase):
    def setUp(self):
        original = publisher.NEW_REFERENCE_GEO_SOURCES.pop(
            existing.VENUE_ID, None)
        self.assertIsNotNone(original)
        self.addCleanup(lambda: publisher.NEW_REFERENCE_GEO_SOURCES.__setitem__(
            existing.VENUE_ID, original))

    def test_new_room_and_eight_unknown_artists_publish_atomically(self):
        base = geo_fixture.test_catalogue()
        previous = geo_fixture.before()
        fetch, reads = official_get()
        proposed, report = producer.build(
            observation(), base, previous, TODAY, fetch=fetch)
        self.assertEqual(report["eligibleUnknownSites"], 1)
        self.assertEqual(report["stateCounts"],
                         {"publisher_bound_openagenda_event_site_pair": 1},
                         report)
        self.assertEqual(len(proposed["approvals"]), 1)
        self.assertEqual(len(proposed["venueApprovals"]), 1)
        event = proposed["approvals"][0]
        site = proposed["venueApprovals"][0]
        self.assertEqual(event["officialEvidence"][1]["proofType"],
                         signer.OPENAGENDA_NEW_PROFILE)
        self.assertEqual(len(event["newArtists"]), 8)
        self.assertEqual(site["venue"]["name"], "Place Libre")
        self.assertEqual(site["venue"]["geoSource"], fixture.SITE_OSM)
        self.assertEqual(site["venue"]["geoPrecision"], "named-site-point")
        self.assertEqual(site["venue"]["latitude"], 47.395)
        self.assertEqual(site["eventBinding"]["authoritySourceUrl"], URL)
        self.assertGreaterEqual(reads.count(OFFICIAL_EXPORT), 3)
        self.assertNotIn(URL, reads, "no second event website or HTML required")
        self.assertTrue(any(url.startswith("https://data.geopf.fr")
                            for url in reads))
        self.assertTrue(any("openstreetmap.org" in url for url in reads))
        self.assertEqual(previous, geo_fixture.before())

        with mock.patch.object(signer.probe, "safe_fetch", side_effect=fetch):
            self.assertEqual(len(approval_preflight.check_append_only(
                previous, proposed, TODAY)), 1)
            published, stats = publisher.merge(base, base, proposed, TODAY)
        self.assertEqual(stats["newEvents"], 1, stats.get("held"))
        self.assertEqual(stats["newVenues"], 1)
        self.assertEqual(stats["newArtists"], 8)
        self.assertEqual(published["events"][-1]["officialUrl"], URL)
        self.assertEqual(published["events"][-1]["venueId"],
                         published["venues"][-1]["id"])

    def test_generic_metal_headline_uses_corroborated_named_bill(self):
        base = geo_fixture.test_catalogue()
        previous = geo_fixture.before()
        title = "SOIRÉE MÉTAL"
        registry = observation(name=title, leadArtist=title)
        names = ["Harsh", "Witchorious", "Wake The Dead"]
        desc = " - ".join(names)
        long = "\n\n".join("### " + n + "\n\nPrésentation du groupe." for n in names)
        changes = {"title": {"fr": title}, "description": {"fr": desc},
                   "longDescription": {"fr": long}, "keywords": {"fr": ["metal"]}}
        fetch, _ = official_get(changes=changes)
        proposed, report = producer.build(registry, base, previous, TODAY, fetch=fetch)
        self.assertEqual(len(proposed["approvals"]), 1, report)
        event = proposed["approvals"][0]
        self.assertEqual(event["officialEvidence"][1]["officialArtistNames"], names)
        self.assertEqual(event["event"]["title"], " + ".join(names))
        with mock.patch.object(signer.probe, "safe_fetch", side_effect=fetch):
            self.assertEqual(len(approval_preflight.check_append_only(
                previous, proposed, TODAY)), 1)
            published, stats = publisher.merge(base, base, proposed, TODAY)
        self.assertEqual(stats["newEvents"], 1, stats)
        self.assertEqual(stats["newVenues"], 1, stats)
        self.assertEqual(published["events"][-1]["title"], " + ".join(names))
        for invalid in ("", "### Harsh", "### Harsh\n### Other\n### Wake The Dead",
                        "```\n" + long + "\n```", "<div hidden>" + long + "</div>"):
            with self.subTest(invalid=invalid):
                bad, _ = official_get(changes={**changes, "longDescription": {"fr": invalid}})
                held, report = producer.build(registry, base, previous, TODAY, fetch=bad)
                self.assertEqual(held, previous, report)
        wrong = observation(name="Concert punk", leadArtist="Concert punk")
        held, report = producer.build(wrong, base, previous, TODAY, fetch=fetch)
        self.assertEqual(held, previous, report)

    def test_city_suffix_is_not_a_new_artist_at_new_venue(self):
        reference = geo_fixture.test_catalogue()
        base = copy.deepcopy(reference)
        base["artists"].append({"id": "ultra-vomit", "name": "Ultra Vomit", "aliases": []})
        previous = geo_fixture.before()
        title = "ULTRA VOMIT - TOURS"
        registry = observation(name=title, leadArtist=title)
        fetch, _ = official_get(changes={
            "title": {"fr": title},
            "keywords": {"fr": ["metal"]},
            "longDescription": {"fr": "Ultra Vomit est un groupe de metal hors du commun."},
        })
        proposed, report = producer.build(registry, base, previous, TODAY, fetch=fetch)
        self.assertEqual(len(proposed["approvals"]), 1, report)
        event = proposed["approvals"][0]
        self.assertEqual(event["event"]["artistIds"], ["ultra-vomit"])
        self.assertEqual(event["newArtists"], [])
        self.assertEqual(event["event"]["title"].casefold(), "ultra vomit")
        with mock.patch.object(signer.probe, "safe_fetch", side_effect=fetch):
            self.assertEqual(len(approval_preflight.check_append_only(
                previous, proposed, TODAY)), 1)
            published, stats = publisher.merge(reference, base, proposed, TODAY)
        self.assertEqual(stats["newEvents"], 1, stats)
        self.assertEqual(stats["newVenues"], 1, stats)
        self.assertEqual(stats["newArtists"], 0, stats)
        self.assertEqual(published["events"][-1]["artistIds"], ["ultra-vomit"])
        for desc in (title, "Un autre groupe joue du metal.",
                     "<script>Ultra Vomit est un groupe de metal.</script>"):
            with self.subTest(desc=desc):
                bad, _ = official_get(changes={"title": {"fr": title},
                                               "longDescription": {"fr": desc}})
                held, report = producer.build(registry, base, previous, TODAY, fetch=bad)
                self.assertEqual(held, previous, report)

    def test_syndicated_event_at_unknown_room_uses_authenticated_origin(self):
        base = geo_fixture.test_catalogue()
        previous = geo_fixture.before()
        alias = "https://openagenda.com/city-agenda/events/eight-unknown-metal-bands"
        original_url = "https://openagenda.com/shotgun/events/87654321_eight-unknown-metal-bands"
        permalink = "https://openagenda.com/agendas/9969608/events/87654321"
        registry = observation(sourceUrl=alias, sourcePage=alias, eventDetailUrl=alias)
        fetch, reads = official_get(changes={"permalink": permalink})
        proposed, report = producer.build(registry, base, previous, TODAY, fetch=fetch)
        self.assertEqual(len(proposed["approvals"]), 1, report)
        self.assertEqual(len(proposed["venueApprovals"]), 1, report)
        event = proposed["approvals"][0]
        site = proposed["venueApprovals"][0]
        self.assertEqual(event["event"]["officialUrl"], original_url)
        self.assertEqual(site["eventBinding"]["eventOfficialUrl"], original_url)
        self.assertEqual(site["eventBinding"]["authoritySourceUrl"], original_url)
        self.assertTrue(all(proof["url"] == original_url
                            for proof in event["officialEvidence"]))
        self.assertNotIn(alias, reads)
        with mock.patch.object(signer.probe, "safe_fetch", side_effect=fetch):
            self.assertEqual(len(approval_preflight.check_append_only(
                previous, proposed, TODAY)), 1)
            published, stats = publisher.merge(base, base, proposed, TODAY)
        self.assertEqual(stats["newEvents"], 1, stats)
        self.assertEqual(stats["newVenues"], 1, stats)
        self.assertEqual(published["events"][-1]["officialUrl"], original_url)

        for changes in ({}, {"permalink": permalink + "9"},
                        {"permalink": permalink, "slug": "different-event"},
                        {"permalink": permalink, "origin": {"uid": 123456, "slug": "shotgun"}},
                        {"permalink": permalink, "status": 2}):
            with self.subTest(changes=changes):
                denied_fetch, _ = official_get(changes=changes)
                denied, reason = producer.build(
                    registry, base, previous, TODAY, fetch=denied_fetch)
                self.assertEqual(denied, previous, reason)

    def test_composite_discovery_title_resolves_two_separately_named_acts(self):
        base = geo_fixture.test_catalogue()
        previous = geo_fixture.before()
        title = "GAGNER DE L'ARGENT | WTAZZZ"
        fetch, _ = official_get(changes={
            "title": {"fr": title},
            "keywords": {"fr": ["punk"]},
            "longDescription": {"fr": "<h2>GAGNER DE L'ARGENT</h2><p>Collectif punk.</p><h2>WTAZZZ</h2><p>Un autre groupe.</p>"},
        })
        proposed, report = producer.build(
            observation(name=title, leadArtist=title), base, previous, TODAY, fetch=fetch)
        self.assertEqual(len(proposed["approvals"]), 1, report)
        event = proposed["approvals"][0]
        self.assertEqual(event["officialEvidence"][1]["officialArtistNames"],
                         ["GAGNER DE L'ARGENT", "WTAZZZ"])
        with mock.patch.object(signer.probe, "safe_fetch", side_effect=fetch):
            self.assertEqual(len(approval_preflight.check_append_only(
                previous, proposed, TODAY)), 1)
            published, stats = publisher.merge(base, base, proposed, TODAY)
        self.assertEqual(stats["newEvents"], 1, stats)
        self.assertEqual(len(published["events"][-1]["artistIds"]), 2)
        self.assertEqual(published["events"][-1]["artistIds"], event["event"]["artistIds"])

    def test_named_osm_site_without_optional_address_tags_reaches_publisher(self):
        # BAN independently proves the street and town. A unique, precisely
        # located, identically named OSM room is still a real place even if the
        # OSM mapper did not fill in addr:city and addr:postcode.
        osm = geo_fixture.osm_xml()
        no_tags = osm.replace('<tag k="addr:city" v="Tours"/>', '').replace(
            '<tag k="addr:postcode" v="37000"/>', '')
        self.assertNotEqual(no_tags, osm)
        base = geo_fixture.test_catalogue()
        before = geo_fixture.before()
        fetch, _ = official_get(osm=no_tags)
        proposed, report = producer.build(
            observation(), base, before, TODAY, fetch=fetch)
        self.assertEqual(report["stateCounts"], {
            "publisher_bound_openagenda_event_site_pair": 1}, report)
        self.assertEqual(len(proposed["venueApprovals"]), 1)
        self.assertEqual(proposed["venueApprovals"][0]["venue"]["geoPrecision"],
                         "named-site-point")
        with mock.patch.object(signer.probe, "safe_fetch", side_effect=fetch):
            self.assertEqual(len(approval_preflight.check_append_only(
                before, proposed, TODAY)), 1)
            published, stats = publisher.merge(base, base, proposed, TODAY)
        self.assertEqual(stats["newEvents"], 1)
        self.assertEqual(stats["newVenues"], 1)
        self.assertEqual(published["venues"][-1]["name"], "Place Libre")

        # Absence of a tag is not the same as a conflicting assertion.
        for bad_tag in ('<tag k="addr:city" v="Paris"/>',
                        '<tag k="addr:postcode" v="75001"/>'):
            with self.subTest(bad_tag=bad_tag):
                wrong_osm = no_tags.replace("</node>", bad_tag + "</node>")
                denied_fetch, _ = official_get(osm=wrong_osm)
                denied, reason = producer.build(
                    observation(), base, before, TODAY, fetch=denied_fetch)
                self.assertEqual(denied, before, reason)
                self.assertEqual(reason["stateCounts"], {
                    "held_original_or_named_site_unverified": 1}, reason)

    def test_geo_report_distinguishes_ban_rejections_without_admission(self):
        base = geo_fixture.test_catalogue()
        previous = geo_fixture.before()
        duplicate = json.loads(geo_fixture.ban())
        duplicate["features"].append(copy.deepcopy(duplicate["features"][0]))
        cases = (
            ('{"features":[]}', "ban_no_valid_point"),
            (geo_fixture.ban(city="Paris"), "ban_postal_identity_mismatch"),
            (geo_fixture.ban(street="Place Autre"), "ban_street_name_mismatch"),
            (geo_fixture.ban(score=0.7), "ban_score_insufficient"),
            (json.dumps(duplicate), "ban_multiple_exact_addresses"),
        )
        for government, code in cases:
            with self.subTest(code=code):
                fetch, reads = official_get(gov=government)
                proposed, report = producer.build(
                    observation(), base, previous, TODAY, fetch=fetch)
                self.assertEqual(proposed, previous, report)
                self.assertEqual(report["geoDiagnostics"], {code: 1}, report)
                self.assertEqual(report["candidateChecks"][0]["geoDiagnostic"], code)
                self.assertFalse(any("openstreetmap.org" in url for url in reads))
                self.assertFalse(report["publicationAllowed"])

    def test_openagenda_new_venue_fails_closed_on_false_identity_or_geography(self):
        base = geo_fixture.test_catalogue()
        reference = official()
        item = json.loads(reference)["events"][0]
        cases = (
            ("cancelled", {"status": 2}, None, None),
            ("wrong_uid", {"uid": 87654322}, None, None),
            ("wrong_agenda", {"origin": {"uid": 123456, "slug": "shotgun"}},
             None, None),
            ("wrong_agenda_slug", {"origin": {"uid": 9969608, "slug": "forged"}},
             None, None),
            ("wrong_date", {"firstDate": "2027-05-12"}, None, None),
            ("wrong_genre", {"keywords": {"fr": ["hardcore techno"]}},
             None, None),
            ("wrong_city", {"location": dict(item["location"], city="Paris")},
             None, None),
            ("wrong_country", {"location": dict(item["location"],
                                                countryCode="de")},
             None, None),
            ("wrong_gps", {"location": dict(item["location"],
                                           latitude=45.0)},
             None, None),
            ("wrong_government", {}, geo_fixture.ban(city="Paris"), None),
            ("wrong_named_site", {}, None, geo_fixture.osm_xml(
                name="Another venue")),
        )
        for name, changed, government, osm in cases:
            with self.subTest(name=name):
                fetch, _ = official_get(
                    changes=changed, gov=government, osm=osm)
                proposed, report = producer.build(
                    observation(), base, geo_fixture.before(), TODAY,
                    fetch=fetch)
                self.assertEqual(proposed, geo_fixture.before(), report)
                self.assertEqual(report["stateCounts"],
                                 {"held_original_or_named_site_unverified": 1},
                                 report)

    def test_electronic_hardcore_is_not_punk_hardcore(self):
        """Actual Hysta-style hardstyle/gabber labels do not sign a metal concert."""
        case = json.loads(official())["events"][0]
        original_url = URL
        venue = case["location"]
        electric = ("<p>Hysta est une figure de la musique électronique "
                    "et du hardcore. Soirée hardstyle, gabber et uptempo.</p>")
        electronic_cases = (
            ({"fr": ["hardcore", "hardstyle", "gabber", "uptempo"]},
             {"fr": electric}),
            ({"fr": []}, {"fr": electric}),
            ({"fr": ["hardcore"]}, {"fr": electric}),
        )
        for keywords, description in electronic_cases:
            with self.subTest(keywords=keywords):
                payload = official(keywords=keywords, description=description)
                with self.assertRaisesRegex(
                        ValueError, "original metal/punk genre evidence missing"):
                    oa.verified_export(
                        payload, original_url, DAY, venue,
                        agenda_uid=AGENDA_UID, event_uid=EVENT_UID)
        for keywords, description in (
            ({"fr": ["hardcore"]},
             {"fr": "<p>Hardcore punk avec riffs de guitare.</p>"}),
            ({"fr": ["hardcore", "punk", "hardstyle"]},
             {"fr": "<p>Hardcore punk et hardstyle sur le même plateau.</p>"}),
        ):
            with self.subTest(accepted=keywords):
                names, genres = oa.verified_export(
                    official(keywords=keywords, description=description),
                    original_url, DAY, venue,
                    agenda_uid=AGENDA_UID, event_uid=EVENT_UID)
                self.assertTrue(names)
                self.assertTrue(genres)

    def test_french_overseas_places_are_eligible_without_city_allowlist(self):
        for code, postcode, department in (
            ("gp", "97110", "971"), ("mq", "97200", "972"),
            ("gf", "97300", "973"), ("re", "97400", "974"),
            ("yt", "97600", "976"), ("nc", "98800", "988"),
            ("pf", "98713", "987"), ("wf", "98600", "986"),
            ("pm", "97500", "975"),
        ):
            with self.subTest(country=code):
                place = producer._unpublished_location({
                    "location": {
                        "name": "Salle Libre", "city": "Ville Libre",
                        "postalCode": postcode,
                        "address": "15 rue Exemple, France",
                        "countryCode": code,
                    },
                })
                self.assertEqual(place["department"], department)
                self.assertEqual(place["name"], "Salle Libre")
                self.assertNotIn("latitude", place)
                self.assertNotIn("longitude", place)

    def test_same_slot_repeated_runs_advance_new_site_review_memory(self):
        from automation.concerts import dynamic_self_attributed_new_site_proposals as own
        leads = [(DAY, "https://example.org/events/" + str(i),
                  {"candidateId": "lead-" + str(i),
                   "reviewBucket": "genre_tag_review" if i < 9 else "genre_unknown"})
                 for i in range(12)]
        for module in (producer, own):
            with self.subTest(module=module.__name__), \
                 mock.patch.object(module, "eligible", return_value=leads), \
                 mock.patch.object(module, "propose", side_effect=ValueError("test only")):
                prior = None
                seen = set()
                for _ in range(3):
                    result, report = module.build(
                        observation(), geo_fixture.test_catalogue(),
                        geo_fixture.before(), TODAY, slot=1, limit=4, prior=prior)
                    ids = {row["candidateId"] for row in report["candidateChecks"]}
                    self.assertEqual(len(ids), 4)
                    self.assertFalse(ids & seen)
                    self.assertEqual(report["firstReviewInMemory"], 4)
                    self.assertEqual(result, geo_fixture.before())
                    self.assertFalse(report["publicationAllowed"])
                    seen.update(ids)
                    prior = report
                self.assertEqual(len(seen), 12)
                self.assertEqual(len(prior["reviewMemory"]), 12)
                self.assertTrue(all(len(k) == 64 for k in prior["reviewMemory"]))
                _, report = module.build(
                    observation(), geo_fixture.test_catalogue(), geo_fixture.before(),
                    TODAY, slot=1, limit=4, prior=prior)
                self.assertEqual(report["examined"], 4)
                self.assertEqual(report["firstReviewInMemory"], 0)

    def test_one_previous_pair_retry_preserves_cohort_and_budget(self):
        from automation.concerts import dynamic_new_site_approval_proposals as geo
        leads = [
            (DAY, "https://example.org/events/" + str(i),
             {"candidateId": "lead-" + str(i),
              "reviewBucket": "genre_tag_review" if i < 6 else "genre_unknown"})
            for i in range(8)
        ]
        chosen = [leads[0], leads[1], leads[2], leads[6]]
        row = leads[5]
        check = {"candidateId": row[2]["candidateId"], "date": DAY,
                 "state": "publisher_bound_openagenda_event_site_pair",
                 "reviewKey": geo.site_review_key(row),
                 "proposedEventId": "test-event"}
        prior = {"schema": producer.SCHEMA, "publicationAllowed": False,
                 "privateApprovalApplied": False, "candidateChecks": [check]}
        result, retried = producer._prioritize_previous_pair(
            chosen, leads, prior, set(), 4)
        self.assertEqual(result, [leads[0], leads[1], row, leads[6]])
        self.assertEqual(retried, {geo.site_review_key(row)})
        self.assertEqual(len(result), len(chosen))
        for invalid, signed, limit in (
                ({**check, "immediatePairRetry": True}, set(), 4),
                (check, {"test-event"}, 4),
                ({**check, "reviewKey": "wrong"}, set(), 4),
                (check, set(), 1)):
            unchanged, retries = producer._prioritize_previous_pair(
                chosen, leads, {**prior, "candidateChecks": [invalid]}, signed, limit)
            self.assertEqual(unchanged, chosen)
            self.assertEqual(retries, set())
        legacy = {k: v for k, v in check.items()
                  if k not in ("reviewKey", "proposedEventId")}
        duplicate = (DAY, "https://other.example.org/event", row[2])
        self.assertEqual(producer._prioritize_previous_pair(
            chosen, leads + [duplicate], {**prior, "candidateChecks": [legacy]},
            set(), 4), (chosen, set()))

    def test_replayed_pair_is_freshly_verified_and_failure_stays_private(self):
        base, previous = geo_fixture.test_catalogue(), geo_fixture.before()
        fetch, _ = official_get()
        proposed, first = producer.build(
            observation(), base, previous, TODAY, fetch=fetch, limit=4)
        self.assertEqual(len(proposed["approvals"]), 1)
        bad, reads = official_get(changes={"status": 2})
        result, second = producer.build(
            observation(), base, previous, TODAY, fetch=bad, limit=4, prior=first)
        self.assertEqual(second["immediatePairRetries"], 1)
        self.assertIn(OFFICIAL_EXPORT, reads)
        self.assertEqual(result, previous)
        self.assertFalse(second["publicationAllowed"])
        self.assertEqual(second["examined"], 1)
        self.assertTrue(second["candidateChecks"][0]["immediatePairRetry"])

    def test_pair_retry_rebuilds_changed_named_bill_without_stale_signature(self):
        base, previous = geo_fixture.test_catalogue(), geo_fixture.before()
        first_names = ["Example Headliner"]
        first_fetch, _ = official_get(changes={
            "title": {"fr": first_names[0]}, "keywords": {"fr": ["metal"]}})
        registry = observation(name=first_names[0], leadArtist=first_names[0])
        proposed, first = producer.build(
            registry, base, previous, TODAY, fetch=first_fetch, limit=4)
        self.assertEqual(len(proposed["approvals"]), 1, first)
        self.assertEqual(proposed["approvals"][0]["officialEvidence"][1]
                         ["officialArtistNames"], first_names)
        names = first_names + ["Example Support A", "Example Support B"]
        fresh_fetch, reads = official_get(changes={
            "title": {"fr": " + ".join(names)},
            "keywords": {"fr": ["metal", "punk"]}})
        rebuilt, second = producer.build(
            registry, base, previous, TODAY, fetch=fresh_fetch, limit=4, prior=first)
        self.assertEqual(second["immediatePairRetries"], 1)
        self.assertIn(OFFICIAL_EXPORT, reads)
        self.assertEqual(len(rebuilt["approvals"]), 1, second)
        self.assertEqual(rebuilt["approvals"][0]["officialEvidence"][1]
                         ["officialArtistNames"], names)
        self.assertEqual(len(rebuilt["approvals"][0]["event"]["artistIds"]), 3)
        self.assertEqual(len(rebuilt["venueApprovals"]), 1)
        self.assertEqual(proposed["approvals"][0]["officialEvidence"][1]
                         ["officialArtistNames"], first_names)
        self.assertEqual(previous, geo_fixture.before())
        with mock.patch.object(signer.probe, "safe_fetch", side_effect=fresh_fetch):
            stats = approval_preflight.validate_proposal(
                previous, rebuilt, base, base, TODAY, publisher.merge)
        self.assertTrue(stats["validatedByPublisher"])

    def test_priority_and_unknown_genres_both_rotate_without_starvation(self):
        leads = []
        for bucket in ("genre_tag_review", "genre_unknown"):
            for index in range(6):
                leads.append((
                    DAY,
                    "https://openagenda.com/shotgun/events/" +
                    bucket + "-" + str(index),
                    {"candidateId": bucket + "-" + str(index),
                     "reviewBucket": bucket},
                ))
        all_seen = set()
        with mock.patch.object(producer, "eligible", return_value=leads), \
             mock.patch.object(producer, "propose", side_effect=ValueError(
                 "test only, do not publish")):
            for day in (TODAY, TODAY + dt.timedelta(days=1)):
                for slot in (0, 1, 2):
                    returned, report = producer.build(
                        observation(), geo_fixture.test_catalogue(),
                        geo_fixture.before(), day, slot=slot, limit=4)
                    self.assertEqual(returned, geo_fixture.before())
                    self.assertEqual(report["examined"], 4)
                    ids = [item["candidateId"] for item in
                           report["candidateChecks"]]
                    self.assertEqual(len([i for i in ids
                                          if i.startswith("genre_tag_review")]), 3)
                    self.assertEqual(len([i for i in ids
                                          if i.startswith("genre_unknown")]), 1)
                    all_seen.update(ids)
        # Every unknown lead is eventually visited, even with 75% priority.
        self.assertEqual(len(all_seen), 12)

    def test_single_check_budget_still_visits_unknown_genres(self):
        leads = [(DAY, "https://openagenda.com/shotgun/events/" + bucket,
                  {"candidateId": bucket, "reviewBucket": bucket})
                 for bucket in ("genre_tag_review", "genre_unknown")]
        visited = set()
        with mock.patch.object(producer, "eligible", return_value=leads), \
             mock.patch.object(producer, "propose",
                               side_effect=ValueError("test only")):
            for delta in range(8):
                _, report = producer.build(
                    observation(), geo_fixture.test_catalogue(),
                    geo_fixture.before(), TODAY + dt.timedelta(days=delta),
                    slot=0, limit=1)
                self.assertEqual(report["examined"], 1)
                visited.add(report["candidateChecks"][0]["candidateId"])
        self.assertEqual(visited, {"genre_tag_review", "genre_unknown"})

    def test_discovery_never_authorizes_known_venue_or_old_date(self):
        base = geo_fixture.test_catalogue()
        fetch = lambda *_: self.fail("untrusted lead must not reach network")
        invalid = observation(date="2020-01-01")
        result, report = producer.build(
            invalid, base, geo_fixture.before(), TODAY, fetch=fetch)
        self.assertEqual(result, geo_fixture.before())
        self.assertEqual(report["eligibleUnknownSites"], 0)
        # A venue already present on the public map goes to existing-site
        # admission, never a parallel duplicate newly-created location.
        known = copy.deepcopy(base)
        known["venues"].append({
            "id": "already-signed-site", "name": "Place Libre",
            "city": "Tours",
        })
        result, report = producer.build(
            observation(), known, geo_fixture.before(), TODAY,
            fetch=fetch)
        self.assertEqual(result, geo_fixture.before())
        self.assertEqual(report["eligibleUnknownSites"], 0)


if __name__ == "__main__":
    unittest.main()
