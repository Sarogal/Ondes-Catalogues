"""End-to-end no-network test: official venue + OSM, NO second website."""
import copy
import datetime as dt
import html
import unittest
from unittest import mock

from automation.concerts import dynamic_osm_official_proposals as pipeline
from scripts import concert_dynamic_existing_venue as identity
from scripts import concerts_cloud_sync as publisher
from automation.concerts import approval_preflight
import test_concerts_dynamic_existing_venue as fixture

TODAY = dt.date(2026, 11, 21)
BASE = fixture.BASE
URL = fixture.EVENT


def registry(stable=2, *, source="agenda_officiel_structuré",
             venue="Le Bikini", city="Ramonville-Saint-Agne",
             bucket="genre_tag_review", url=URL):
    return {"schema": "grossesondes.concert.intake.v1",
            "items": {"new-unique": {
                "status": "pending_review", "stableObservations": stable,
                "candidate": {
                    "candidateId": "new-unique", "source": source,
                    "sourceUrl": url, "sourcePage": url,
                    "eventDetailUrl": url,
                    "date": "2027-03-05", "name": "Groupe Libre 1",
                    "leadArtist": "Groupe Libre 1",
                    "venue": venue, "city": city, "department": "31",
                    "reviewBucket": bucket, "possibleExistingConcert": False,
                    "publicationAllowed": False, "reviewRequired": True,
                }}}
            }



def html_microdata_event():
    venue = next(v for v in BASE["venues"] if v["id"] == fixture.VENUE_ID)
    bill = "".join(
        '<div itemprop="performer" itemscope '
        'itemtype="https://schema.org/MusicGroup">'
        '<span itemprop="name">' + html.escape(name) + '</span></div>'
        for name in fixture.NAMES)
    return (
        '<html><article itemscope itemtype="https://schema.org/Event">'
        '<h1 itemprop="name">' + html.escape(" + ".join(fixture.NAMES)) + '</h1>'
        '<a itemprop="url" href="' + html.escape(URL, quote=True) + '">Concert</a>'
        '<time itemprop="startDate" datetime="2027-03-05">5 March 2027</time>'
        '<meta itemprop="genre" content="Black Metal">'
        + bill + '<div itemprop="location" itemscope '
        'itemtype="https://schema.org/Place"><span itemprop="name">Le Bikini</span>'
        '<div itemprop="address" itemscope '
        'itemtype="https://schema.org/PostalAddress">'
        '<span itemprop="streetAddress">' + html.escape(venue["address"]) + '</span>'
        '<span itemprop="postalCode">31520</span>'
        '<span itemprop="addressLocality">Ramonville-Saint-Agne</span>'
        '<meta itemprop="addressCountry" content="FR">'
        '</div></div></article></html>'
    )


class SingleOSMOfficialPublisherTests(unittest.TestCase):
    def setUp(self):
        # The reference fixture has a historical location migration, which
        # is unrelated to this new admission contract and checked elsewhere.
        old = publisher.NEW_REFERENCE_GEO_SOURCES.pop(
            fixture.VENUE_ID, None)
        self.assertIsNotNone(old)
        self.addCleanup(lambda: publisher.NEW_REFERENCE_GEO_SOURCES.__setitem__(
            fixture.VENUE_ID, old))

    def test_unknown_artists_and_domain_publish_via_real_publisher(self):
        fetch = fixture.fake_fetch()
        reads = []
        def single_source(url, cache):
            self.assertNotEqual(url, fixture.WITNESS)
            reads.append(url)
            return fetch(url, cache)
        proposals, report = pipeline.build(
            registry(), BASE,
            {"schema": publisher.SCHEMA, "approvals": []},
            TODAY, slot=0, limit=8, fetch=single_source)
        self.assertEqual(report["eligibleQueue"], 1)
        self.assertEqual(report["examined"], 1)
        self.assertEqual(report["stateCounts"],
                         {"independently_verified_proposal": 1})
        self.assertFalse(report["publicationAllowed"])
        self.assertFalse(report["privateApprovalApplied"])
        self.assertEqual(report["eligibilityRejections"], {})
        self.assertEqual(report["candidateChecks"][0]["candidateId"],
                         "new-unique")
        self.assertEqual(report["candidateChecks"][0]["state"],
                         "independently_verified_proposal")
        self.assertEqual(len(proposals["approvals"]), 1)
        app = proposals["approvals"][0]
        self.assertEqual(app["officialEvidence"][0]["proofType"],
                         identity.OSM_SINGLE_PROFILE)
        self.assertNotIn("corroboratingEventUrl", app["officialEvidence"][0])
        self.assertEqual(len(app["newArtists"]), 8)
        with mock.patch.object(identity, "safe_fetch",
                               side_effect=single_source):
            accepted = approval_preflight.check_append_only(
                {"schema": publisher.SCHEMA, "approvals": []},
                proposals, TODAY)
            self.assertEqual(len(accepted), 1)
            merged, stats = publisher.merge(BASE, BASE, proposals, TODAY)
        self.assertEqual(stats["newEvents"], 1)
        self.assertEqual(stats["newArtists"], 8)
        self.assertEqual(stats["newVenues"], 0)
        self.assertEqual(merged["events"][-1]["officialUrl"], URL)
        self.assertIn(URL, reads)
        self.assertTrue(any("api.openstreetmap.org" in x for x in reads))
        self.assertNotIn(fixture.WITNESS, reads)
        with mock.patch.object(identity, "safe_fetch",
                               side_effect=AssertionError("replay must not refetch")):
            same, again = publisher.merge(BASE, merged, proposals, TODAY)
        self.assertEqual(again["newEvents"], 0)
        self.assertEqual(same, merged)

    def test_visible_first_party_eight_band_bill_passes_real_publisher(self):
        import json
        import re
        source = fixture.page(URL)
        match = re.search(r"<script type='application/ld\+json'>(.*?)</script>", source)
        self.assertIsNotNone(match)
        event = json.loads(match.group(1))
        event["@type"] = "Event"
        event.pop("performer", None)
        event.pop("genre", None)
        visible = ("<html><main><h1>" +
                   html.escape(" + ".join(fixture.NAMES)) + "</h1>" +
                   "".join("<p><strong>" + html.escape(n) +
                           " — Black Metal | France</strong></p>"
                           for n in fixture.NAMES) +
                   "</main><script type='application/ld+json'>" +
                   json.dumps(event) + "</script></html>")
        read = fixture.fake_fetch({"primary": visible})
        result, report = pipeline.build(
            registry(), BASE,
            {"schema": publisher.SCHEMA, "approvals": []},
            TODAY, fetch=read)
        self.assertEqual(report["stateCounts"],
                         {"independently_verified_proposal": 1}, report)
        self.assertEqual(len(result["approvals"][0]["newArtists"]), 8)
        with mock.patch.object(identity, "safe_fetch", side_effect=read):
            published, stats = publisher.merge(BASE, BASE, result, TODAY)
        self.assertEqual(stats["newEvents"], 1, stats.get("held"))
        self.assertEqual(stats["newArtists"], 8)
        self.assertEqual(published["events"][-1]["officialUrl"], URL)

        incomplete = visible.replace(
            "<p><strong>" + html.escape(fixture.NAMES[-1]) +
            " — Black Metal | France</strong></p>", "")
        source = fixture.fake_fetch({"primary": incomplete})
        reads = []
        def visit(url, cache):
            reads.append(url)
            return source(url, cache)
        held, rejected = pipeline.build(
            registry(), BASE,
            {"schema": publisher.SCHEMA, "approvals": []},
            TODAY, fetch=visit)
        self.assertEqual(held["approvals"], [])
        self.assertTrue(rejected["candidateChecks"][0]["reason"].startswith(
            "official_event_content:"), rejected)
        # Source ownership must be established before an unknown host is
        # read, even when its later bill turns out to be incomplete.
        self.assertTrue(any("openstreetmap.org" in u for u in reads))

    def test_nonmetal_official_event_stays_held_after_source_verification(self):
        first_party = fixture.page(URL).replace(
            "Black Metal", "Hardcore Techno")
        base = fixture.fake_fetch({"primary": first_party})
        visited = []
        def fetch(url, cache):
            visited.append(url)
            return base(url, cache)
        withheld, report = pipeline.build(
            registry(), BASE,
            {"schema": publisher.SCHEMA, "approvals": []},
            TODAY, fetch=fetch)
        self.assertEqual(withheld["approvals"], [])
        self.assertTrue(report["candidateChecks"][0]["reason"].startswith(
            "official_event_content:"), report)
        self.assertIn(URL, visited)
        self.assertTrue(any("openstreetmap.org" in u for u in visited))
        self.assertLess(
            next(i for i,u in enumerate(visited)
                 if "openstreetmap.org" in u), visited.index(URL))

    def test_unavailable_osm_api_host_uses_second_official_api(self):
        # A failed API hostname cannot discard an authentic concert when
        # another official OSM API endpoint returns the SAME named node.
        observed = []
        normal = fixture.fake_fetch()
        def fail_first(url, cache):
            observed.append(url)
            if url.startswith("https://api.openstreetmap.org/"):
                raise ValueError("Source returned non-success HTTP status")
            if url.startswith("https://www.openstreetmap.org/api/0.6/node/"):
                return fixture.osm()
            return normal(url, cache)
        proposed, report = pipeline.build(
            registry(), BASE,
            {"schema": publisher.SCHEMA, "approvals": []},
            TODAY, fetch=fail_first)
        self.assertEqual(report["stateCounts"],
                         {"independently_verified_proposal": 1})
        with mock.patch.object(identity, "safe_fetch",
                               side_effect=fail_first):
            output, stats = publisher.merge(BASE, BASE, proposed, TODAY)
        self.assertEqual(stats["newEvents"], 1)
        self.assertIn(URL, observed)
        self.assertTrue(any(x.startswith(
            "https://www.openstreetmap.org/api/0.6/node/")
            for x in observed))
        self.assertEqual(output["events"][-1]["officialUrl"], URL)

    def test_overpass_read_only_recovers_node_without_scraping_osm_website(self):
        # Both editing-API origins may reject a public runner or robots
        # policy. A bounded node query against a dedicated read-only OSM
        # service must still prove the EXACT name, site, domain and position.
        calls = []
        original = fixture.fake_fetch()
        def network(url, cache):
            calls.append(url)
            if url.startswith("https://api.openstreetmap.org/api/0.6/node/"):
                raise ValueError("Source returned non-success HTTP status")
            if url.startswith("https://www.openstreetmap.org/api/0.6/node/"):
                raise ValueError("robots.txt forbids source")
            if url.startswith("https://overpass.private.coffee/api/interpreter?"):
                self.assertIn("node%28380889428%29", url)
                return fixture.osm()
            return original(url, cache)
        proposed, report = pipeline.build(
            registry(), BASE,
            {"schema": publisher.SCHEMA, "approvals": []},
            TODAY, fetch=network)
        self.assertEqual(report["stateCounts"],
                         {"independently_verified_proposal": 1})
        with mock.patch.object(identity, "safe_fetch", side_effect=network):
            result, stats = publisher.merge(BASE, BASE, proposed, TODAY)
        self.assertEqual(stats["newEvents"], 1)
        self.assertEqual(result["events"][-1]["officialUrl"], URL)
        self.assertTrue(any("overpass.private.coffee" in x for x in calls))

    def test_read_only_osm_fallback_refuses_forged_name_or_website(self):
        original = fixture.fake_fetch()
        for altered in (fixture.osm(name="Impostor Venue"),
                        fixture.osm(website="https://impostor.invalid"),
                        fixture.osm(lat="47.400")):
            def fetch(url, cache):
                if url.startswith(("https://api.openstreetmap.org/api/0.6/node/",
                                   "https://www.openstreetmap.org/api/0.6/node/")):
                    raise ValueError("editing API unavailable")
                if url.startswith("https://overpass.private.coffee/api/interpreter?"):
                    return altered
                return original(url, cache)
            with self.subTest(osm=altered[:110]):
                proposed, report = pipeline.build(
                    registry(), BASE,
                    {"schema": publisher.SCHEMA, "approvals": []},
                    TODAY, fetch=fetch)
                self.assertEqual(proposed["approvals"], [])
                self.assertEqual(report["stateCounts"],
                                 {"held_event_or_source_not_verified": 1})

    def test_network_failures_are_reported_by_proof_phase(self):
        original = fixture.fake_fetch()
        for phase in ("osm_identity", "official_event_fetch"):
            def fail_one(url, cache):
                if phase == "osm_identity" and (
                    "openstreetmap.org" in url or
                    "overpass.private.coffee" in url):
                    raise ValueError("Source returned non-success HTTP status")
                if phase == "official_event_fetch" and url == URL:
                    raise ValueError("Source returned non-success HTTP status")
                return original(url, cache)
            with self.subTest(phase=phase):
                result, report = pipeline.build(
                    registry(), BASE,
                    {"schema": publisher.SCHEMA, "approvals": []},
                    TODAY, fetch=fail_one)
                self.assertEqual(result["approvals"], [])
                self.assertEqual(report["examined"], 1)
                self.assertTrue(
                    report["candidateChecks"][0]["reason"].startswith(
                        phase + ":"))
                self.assertEqual(report["stateCounts"],
                    {"held_event_or_source_not_verified": 1})

    def test_osm_fallback_never_accepts_forged_node(self):
        normal = fixture.fake_fetch()
        def corrupt(url, cache):
            if url.startswith("https://api.openstreetmap.org/"):
                raise ValueError("Source returned non-success HTTP status")
            if url.startswith("https://www.openstreetmap.org/api/0.6/node/"):
                return fixture.osm(website="https://forged.invalid")
            return normal(url, cache)
        result, report = pipeline.build(
            registry(), BASE,
            {"schema": publisher.SCHEMA, "approvals": []},
            TODAY, fetch=corrupt)
        self.assertEqual(result["approvals"], [])
        self.assertEqual(report["stateCounts"],
                         {"held_event_or_source_not_verified": 1})
        self.assertTrue(report["candidateChecks"][0]["reason"].startswith(
            "osm_identity:"))


    def test_existing_non_osm_map_room_admits_official_source_by_exact_ban_osm(self):
        import json
        cat = copy.deepcopy(BASE)
        venue = next(v for v in cat["venues"] if v["id"] == fixture.VENUE_ID)
        venue["geoSource"] = "Géolocalisation indicative par commune"
        node = "380889428"
        homepage = "https://nouveau-domaine-independant.fr"
        ban = json.dumps({"features": [{
            "geometry": {"type": "Point", "coordinates": [1.48568, 43.54795]},
            "properties": {"postcode": "31520", "city": "Ramonville-Saint-Agne",
                           "street": venue["address"], "type": "street",
                           "score": 0.81,
                           "context": "31, Haute-Garonne, Occitanie"},
        }]})
        def osm(*, website=homepage, name="Le Bikini"):
            return ('<osm version="0.6"><node id="' + node +
                    '" lat="43.54795" lon="1.48568">'
                    '<tag k="name" v="' + name + '"/>'
                    '<tag k="addr:city" v="Ramonville-Saint-Agne"/>'
                    '<tag k="addr:postcode" v="31520"/>'
                    # Optional OSM addr:street is not authority when absent;
                    # BAN exact address and the same named OSM point still are.
                    '<tag k="website" v="' + website + '"/>'
                    '</node></osm>')
        def fetcher(*, ban_result=ban, map_result=None, event_html=None):
            seen = []
            def fetch(url, cache):
                seen.append(url)
                if url.startswith("https://data.geopf.fr/geocodage/search/"):
                    return ban_result
                if url.startswith("https://api.openstreetmap.org/api/0.6/map?bbox="):
                    return map_result if map_result is not None else osm()
                if url == "https://api.openstreetmap.org/api/0.6/node/" + node:
                    return map_result if map_result is not None else osm()
                if url == URL:
                    return event_html if event_html is not None else fixture.page(
                        URL, music=False)
                raise AssertionError("Unexpected independent endpoint " + url)
            return fetch, seen

        previous = {"schema": publisher.SCHEMA, "approvals": []}
        fetch, seen = fetcher()
        approved, report = pipeline.build(
            registry(), cat, previous, TODAY, fetch=fetch)
        self.assertEqual(report["stateCounts"],
                         {"independently_verified_proposal": 1})
        self.assertEqual(len(approved["approvals"]), 1)
        proof = approved["approvals"][0]["officialEvidence"][0]
        self.assertEqual(proof["proofType"], identity.OSM_ADDRESS_PROFILE)
        self.assertEqual(proof["namedOsmUrl"],
                         "https://www.openstreetmap.org/node/" + node)
        self.assertEqual(proof["publishedVenueGeoSource"], venue["geoSource"])
        self.assertEqual(proof["sourceWebsite"], homepage)
        self.assertEqual(len(approved["approvals"][0]["newArtists"]), 8)
        with mock.patch.object(identity, "safe_fetch", side_effect=fetch):
            self.assertEqual(len(approval_preflight.check_append_only(
                previous, approved, TODAY)), 1)
            published, stats = publisher.merge(cat, cat, approved, TODAY)
        self.assertEqual(stats["newEvents"], 1)
        self.assertEqual(stats["newArtists"], 8)
        self.assertEqual(stats["newVenues"], 0)
        self.assertEqual(published["events"][-1]["officialUrl"], URL)
        self.assertEqual(published["venues"], cat["venues"])
        self.assertTrue(any("data.geopf.fr" in x for x in seen))
        self.assertIn(URL, seen)

        # The first-party page, government street, and named OSM website
        # are three distinct identities. No single forged one may approve.
        bad_ban = json.dumps({"features": [{
            "geometry": {"type": "Point", "coordinates": [1.48568, 43.54795]},
            "properties": {"postcode": "31520", "city": "Ramonville-Saint-Agne",
                           "street": venue["address"], "type": "street",
                           "score": 0.70},
        }]})
        for label, kwargs in (
            ("ban_low_score", {"ban_result": bad_ban}),
            ("wrong_osm_name", {"map_result": osm(name="Wrong Hall")}),
            ("wrong_osm_site", {"map_result": osm(
                website="https://forged.invalid")}),
            ("not_music", {"event_html": fixture.page(
                URL, music=False, genres=False)}),
            ("cancelled", {"event_html": fixture.page(
                URL, status="EventCancelled")}),
        ):
            with self.subTest(label=label):
                invalid_fetch, _ = fetcher(**kwargs)
                result, diagnostic = pipeline.build(
                    registry(), cat, previous, TODAY, fetch=invalid_fetch)
                self.assertEqual(result["approvals"], [])
                self.assertEqual(diagnostic["stateCounts"],
                                 {"held_event_or_source_not_verified": 1})

    def test_generic_event_or_html_microdata_reaches_real_publisher(self):
        # Some official venue sites emit schema.org Event, or HTML microdata,
        # rather than MusicEvent. Neither may borrow a genre or bill from
        # neighboring cards; the OSM website attribution is still mandatory.
        for page in (fixture.page(URL, music=False), html_microdata_event()):
            with self.subTest(format="microdata" if "itemscope" in page else "jsonld"):
                fetch = fixture.fake_fetch({"primary": page})
                proposed, report = pipeline.build(
                    registry(), BASE,
                    {"schema": publisher.SCHEMA, "approvals": []},
                    TODAY, fetch=fetch)
                self.assertEqual(report["stateCounts"],
                                 {"independently_verified_proposal": 1})
                self.assertEqual(len(proposed["approvals"]), 1)
                with mock.patch.object(identity, "safe_fetch",
                                       side_effect=fetch):
                    result, stats = publisher.merge(
                        BASE, BASE, proposed, TODAY)
                self.assertEqual(stats["newEvents"], 1)
                self.assertEqual(result["events"][-1]["genres"],
                                 ["Black Metal"])
                self.assertEqual(result["events"][-1]["artistIds"],
                                 fixture.IDS)

    def test_generic_event_without_own_music_proof_or_fake_source_is_held(self):
        # Type Event alone is never music proof. Even a correctly typed
        # concert cannot be validated from a forged OSM website.
        cases = [
            (fixture.page(URL, music=False, genres=False), fixture.osm()),
            (fixture.page(URL, music=False), fixture.osm(
                website="https://impostor.invalid")),
            (fixture.page(URL, music=False, status="EventCancelled"),
             fixture.osm()),
            (fixture.page(URL, music=False,
                          event_name="Festival du Metal 2027"), fixture.osm()),
        ]
        for page, osm in cases:
            def fetch(url, cache):
                return osm if url.startswith(
                    "https://api.openstreetmap.org/") else page
            with self.subTest(case=page[:80], osm=osm[:90]):
                proposed, report = pipeline.build(
                    registry(), BASE,
                    {"schema": publisher.SCHEMA, "approvals": []},
                    TODAY, fetch=fetch)
                self.assertEqual(proposed["approvals"], [])
                self.assertEqual(report["stateCounts"],
                                 {"held_event_or_source_not_verified": 1})

    def test_unknown_genre_discovery_may_be_proven_by_exact_event_performer(self):
        leads = pipeline.eligible(registry(bucket="genre_unknown"), BASE, TODAY)
        self.assertEqual(len(leads), 1)
        app = pipeline.propose(leads[0], BASE, TODAY,
                               fetch=fixture.fake_fetch())
        self.assertEqual(app["event"]["genres"], ["Black Metal"])

    def test_no_stability_festival_third_party_or_unknown_venue_can_qualify(self):
        for change in (
            lambda r: r["items"]["new-unique"].update(stableObservations=1),
            lambda r: r["items"]["new-unique"]["candidate"].update(
                reviewBucket="festival_overlap_review"),
            lambda r: r["items"]["new-unique"]["candidate"].update(
                source="third_party_calendar_lead"),
            lambda r: r["items"]["new-unique"]["candidate"].update(
                venue="An Unknown Square"),
            lambda r: r["items"]["new-unique"]["candidate"].update(
                city="Paris"),
            lambda r: r["items"]["new-unique"]["candidate"].update(
                sourcePage="https://other-source.fr/calendar/"),
            lambda r: r["items"]["new-unique"]["candidate"].update(
                sourceUrl="https://unknown-source.fr/event/",
                eventDetailUrl="https://unknown-source.fr/event/",
                sourcePage="https://unknown-source.fr/event/"),
            lambda r: r["items"]["new-unique"]["candidate"].update(
                publicationAllowed=True),
        ):
            case = registry()
            change(case)
            with self.subTest(change=change):
                if "unknown-source.fr" in str(case):
                    # Valid but unverified sources may enter research, never
                    # pass attribution/Publisher on their own.
                    candidates = pipeline.eligible(case, BASE, TODAY)
                    self.assertEqual(len(candidates), 1)
                    proposals, state = pipeline.build(
                        case, BASE,
                        {"schema": publisher.SCHEMA, "approvals": []},
                        TODAY, fetch=fixture.fake_fetch())
                    self.assertEqual(len(proposals["approvals"]), 0)
                    self.assertEqual(state["examined"], 1)
                else:
                    self.assertEqual(
                        pipeline.eligible(case, BASE, TODAY), [])

    def test_forged_geometry_and_changed_artist_date_genre_fail_closed(self):
        bad_pages = [
            fixture.page(URL, date="2027-03-06"),
            fixture.page(URL, venue_name="Wrong Hall"),
            fixture.page(URL, genres=False),
            fixture.page(URL, music=False, genres=False),
            fixture.page(URL, country="BE"),
            fixture.page(URL, names=["Unrelated Artist"]),
        ]
        for altered in bad_pages:
            def tampered(url, cache):
                return (altered if url == URL else fixture.osm())
            with self.subTest(altered=altered[:80]):
                out, summary = pipeline.build(
                    registry(), BASE,
                    {"schema": publisher.SCHEMA, "approvals": []},
                    TODAY, fetch=tampered)
                self.assertEqual(len(out["approvals"]), 0)
                self.assertEqual(summary["stateCounts"],
                    {"held_event_or_source_not_verified": 1})
                self.assertEqual(len(summary["candidateChecks"]), 1)
                self.assertEqual(summary["candidateChecks"][0]["state"],
                                 "held_event_or_source_not_verified")
                self.assertTrue(summary["candidateChecks"][0]["reason"])
                self.assertEqual(sum(summary["rejectionReasons"].values()), 1)
        def fake_osm(url, cache):
            return (fixture.osm(website="https://attacker.fr")
                    if url.startswith("https://api.openstreetmap.org/")
                    else fixture.page(URL))
        result, _ = pipeline.build(
            registry(), BASE,
            {"schema": publisher.SCHEMA, "approvals": []},
            TODAY, fetch=fake_osm)
        self.assertEqual(result["approvals"], [])

    def test_private_report_explains_preselection_rejections(self):
        data = registry(stable=1)
        proposals, report = pipeline.build(
            data, BASE,
            {"schema": publisher.SCHEMA, "approvals": []},
            TODAY, fetch=fixture.fake_fetch())
        self.assertEqual(proposals["approvals"], [])
        self.assertEqual(report["eligibleQueue"], 0)
        self.assertEqual(report["examined"], 0)
        self.assertEqual(report["candidateChecks"], [])
        self.assertEqual(report["eligibilityRejections"],
                         {"insufficient_stability": 1})
        self.assertFalse(report["publicationAllowed"])

    def test_publisher_rejects_forged_profile_and_extra_fields(self):
        app = pipeline.propose(pipeline.eligible(registry(), BASE, TODAY)[0],
                               BASE, TODAY, fetch=fixture.fake_fetch())
        with mock.patch.object(identity, "safe_fetch",
                               side_effect=fixture.fake_fetch()):
            for field, value in (
                ("namedOsmUrl", "https://www.openstreetmap.org/node/9"),
                ("officialGenreLabels", ["Jazz"]),
                ("officialArtistNames", ["Fake Musician"]),
                ("corroboratingEventUrl", fixture.WITNESS),
                ("proofType", "made-up-profile"),
            ):
                changed = copy.deepcopy(app)
                changed["officialEvidence"][0][field] = value
                with self.subTest(field=field), self.assertRaises(ValueError):
                    publisher.validate_approval(
                        changed,
                        {v["id"]: v for v in BASE["venues"]},
                        {a["id"]: a for a in BASE["artists"]}, TODAY)

    def test_one_venue_cannot_monopolize_all_daily_checks(self):
        # The public registry contains many events from the same hall.
        # The scan window must include OTHER independently published venues,
        # regardless of whether their band was already known.
        cat = copy.deepcopy(BASE)
        base_venue = next(v for v in cat["venues"] if v["id"] ==
                          fixture.VENUE_ID)
        cases = registry()
        template = next(iter(cases["items"].values()))
        cases["items"] = {}
        for index in range(40):
            row = copy.deepcopy(template)
            url = f"https://long-schedule.fr/concert/{index:03d}"
            row["candidate"].update(
                candidateId=f"large-room-{index}",
                sourceUrl=url, eventDetailUrl=url, sourcePage=url)
            cases["items"][str(index)] = row
        for index in range(3):
            room = copy.deepcopy(base_venue)
            room["id"] = f"extra-physical-room-{index}"
            room["name"] = f"Extra Physical Room {index}"
            room["city"] = f"Test City {index}"
            room["department"] = str(30 + index)
            room["geoSource"] = (
                "https://www.openstreetmap.org/node/" + str(90001000 + index))
            cat["venues"].append(room)
            extra = copy.deepcopy(template)
            extra["candidate"].update(
                candidateId=f"extra-room-{index}",
                venue=room["name"], city=room["city"],
                department=room["department"],
                sourceUrl=f"https://extra-room-{index}.fr/annonce/live/",
                eventDetailUrl=f"https://extra-room-{index}.fr/annonce/live/",
                sourcePage=f"https://extra-room-{index}.fr/annonce/live/")
            cases["items"][f"extra-{index}"] = extra
        selected = pipeline.eligible(cases, cat, TODAY)
        self.assertEqual(len(selected), 43)
        self.assertEqual(
            {row[2] for row in selected[:8]},
            {fixture.VENUE_ID} |
            {f"extra-physical-room-{x}" for x in range(3)})
        # Multiple slots keep their bounded budget; distinct venue
        # candidates do not become a one-off permanently privileged cohort.
        seen = set()
        for day_offset in range(6):
            for slot in (0, 1, 2):
                day = TODAY + dt.timedelta(days=day_offset)
                rotated = pipeline.eligible(cases, cat, day)
                offset = (((day - TODAY).days * 3 + slot) * 8) % len(rotated)
                seen.update(row[0] for row in
                    (rotated[(offset+i) % len(rotated)] for i in range(8)))
        self.assertEqual(len(seen), 43)

    def test_scan_budget_rotates_across_any_number_of_candidate_events(self):
        cases = registry()
        proto = next(iter(cases["items"].values()))
        cases["items"] = {}
        for i in range(80):
            row = copy.deepcopy(proto)
            url = "https://official-unknown.fr/agenda/band-%03d/" % i
            row["candidate"]["sourceUrl"] = url
            row["candidate"]["eventDetailUrl"] = url
            row["candidate"]["sourcePage"] = url
            row["candidateId"] = str(i)
            cases["items"][str(i)] = row
        checked = set()
        for day_offset in range(4):
            for slot in (0, 1, 2):
                day = TODAY + dt.timedelta(days=day_offset)
                selected = pipeline.eligible(cases, BASE, day)
                start = (((day - TODAY).days * 3 + slot) * 8) % len(selected)
                sample = [selected[(start + x) % len(selected)]
                          for x in range(8)]
                checked.update(url for url, date, vid, c in sample)
        self.assertEqual(len(checked), 80)


if __name__ == "__main__":
    unittest.main()
