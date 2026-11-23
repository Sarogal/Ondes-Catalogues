"""One actual OpenAgenda-owned JSON export can publish an existing-venue gig.

No JSON-LD, OSM witness, artist allowlist or second event page is needed.
The publisher independently re-fetches the same first-party export.
"""
import copy
import datetime as dt
import json
import unittest
from unittest import mock

from automation.concerts import dynamic_osm_official_proposals as producer
from automation.concerts import openagenda_official_concert as oa
from automation.concerts import approval_preflight
from scripts import concert_dynamic_existing_venue as identity
from scripts import concerts_cloud_sync as publisher
import test_concerts_dynamic_existing_venue as fixture

TODAY = dt.date(2026, 11, 22)
DAY = "2027-03-05"
URL = "https://openagenda.com/fr/shotgun/events/87654321_eight-unknown-metal-bands"
EXPORT = ("https://openagenda.com/agendas/9969608/events.json?"
          "oaq%5Buids%5D%5B%5D=87654321&limit=1")


def registry():
    return {"schema": "grossesondes.concert.intake.v1",
            "items": {"from-openagenda": {
                "status": "pending_review", "stableObservations": 1,
                "candidate": {
                    "candidateId": "from-openagenda",
                    "source": "agenda_officiel_openagenda",
                    "sourceUrl": URL, "sourcePage": URL,
                    "eventDetailUrl": URL,
                    "openAgendaUid": "9969608",
                    "openAgendaEventUid": "87654321",
                    "date": DAY, "name": " + ".join(fixture.NAMES),
                    "leadArtist": fixture.NAMES[0],
                    "venue": "Le Bikini", "city": "Ramonville-Saint-Agne",
                    "department": "31", "reviewBucket": "genre_tag_review",
                    "possibleExistingConcert": False,
                    "publicationAllowed": False, "reviewRequired": True,
                }}}}


def official_export(**changes):
    venue = next(v for v in fixture.BASE["venues"]
                 if v["id"] == fixture.VENUE_ID)
    record = {
        "uid": 87654321, "slug": "eight-unknown-metal-bands",
        "status": 1, "firstDate": DAY, "lastDate": DAY,
        "origin": {"uid": 9969608, "slug": "shotgun"},
        "canonicalUrl": ("https://openagenda.com/shotgun/events/"
                         "87654321_eight-unknown-metal-bands"),
        "title": {"fr": " + ".join(fixture.NAMES)},
        "keywords": {"fr": ["Black Metal", "punk"]},
        "location": {
            "name": "Le Bikini", "city": "Ramonville-Saint-Agne",
            "postalCode": "31520", "countryCode": "fr",
            "address": venue["address"] + ", 31520 Ramonville-Saint-Agne, France",
        },
    }
    record.update(changes)
    return json.dumps({"total": 1, "events": [record]}, ensure_ascii=False)


class OpenAgendaFirstPartyExportContract(unittest.TestCase):
    def setUp(self):
        self.catalogue = copy.deepcopy(fixture.BASE)
        old = publisher.NEW_REFERENCE_GEO_SOURCES.pop(fixture.VENUE_ID, None)
        if old is not None:
            self.addCleanup(lambda: publisher.NEW_REFERENCE_GEO_SOURCES.__setitem__(
                fixture.VENUE_ID, old))

    def test_publisher_accepts_official_export_without_json_ld(self):
        observed = []
        def get(url, cache):
            observed.append(url)
            self.assertEqual(url, EXPORT, "only the original OpenAgenda export")
            return official_export()
        self.assertEqual(oa.official_export_url("9969608", "87654321"), EXPORT)
        with mock.patch.object(identity, "safe_fetch", side_effect=get):
            before = {"schema": publisher.SCHEMA, "approvals": []}
            proposals, report = producer.build(
                registry(), self.catalogue, before, TODAY, fetch=get)
            self.assertEqual(report["stateCounts"],
                             {"independently_verified_proposal": 1}, report)
            signed = proposals["approvals"][0]
            proof = signed["officialEvidence"][0]
            self.assertEqual(proof["proofType"], identity.OPENAGENDA_PROFILE)
            self.assertEqual(proof["officialOpenAgendaUid"], "9969608")
            self.assertEqual(proof["officialOpenAgendaEventUid"], "87654321")
            self.assertEqual(len(signed["newArtists"]), 8)
            self.assertEqual(len(approval_preflight.check_append_only(
                before, proposals, TODAY)), 1)
            published, stats = publisher.merge(
                self.catalogue, self.catalogue, proposals, TODAY)
            self.assertEqual(stats["newEvents"], 1, stats["held"])
            self.assertEqual(stats["newArtists"], 8)
            self.assertEqual(published["events"][-1]["officialUrl"], URL)
        self.assertGreaterEqual(len(observed), 3)
        self.assertEqual(set(observed), {EXPORT})

    def test_unknown_historical_postcode_and_address_do_not_block_official_oa(self):
        # Historical public map placeholders are not known physical data.
        # The official original OA export still binds UID + slug, venue,
        # municipality, programme date, named artists and relevant genre.
        venue = next(v for v in self.catalogue["venues"]
                     if v["id"] == fixture.VENUE_ID)
        venue["postalCode"] = "À vérifier"
        venue["address"] = "Adresse exacte à vérifier"
        calls = []
        def get(url, cache):
            self.assertEqual(url, EXPORT)
            calls.append(url)
            return official_export()
        before = {"schema": publisher.SCHEMA, "approvals": []}
        with mock.patch.object(identity, "safe_fetch", side_effect=get):
            proposed, report = producer.build(
                registry(), self.catalogue, before, TODAY, fetch=get)
            self.assertEqual(len(proposed["approvals"]), 1, report)
            self.assertEqual(
                proposed["approvals"][0]["event"]["officialUrl"], URL)
            self.assertEqual(len(approval_preflight.check_append_only(
                before, proposed, TODAY)), 1)
            merged, stats = publisher.merge(
                self.catalogue, self.catalogue, proposed, TODAY)
            self.assertEqual(stats["newEvents"], 1, stats["held"])
            self.assertEqual(merged["events"][-1]["officialUrl"], URL)
        self.assertGreaterEqual(len(calls), 3)

    def test_placeholder_never_overrides_actual_venue_identity_or_real_address(self):
        venue = next(v for v in self.catalogue["venues"]
                     if v["id"] == fixture.VENUE_ID)
        placeholder = copy.deepcopy(venue)
        placeholder["postalCode"] = "À vérifier"
        placeholder["address"] = "Adresse exacte à vérifier"
        # Unknown catalogue fields are not a licence to change the
        # venue/city, cancellation state or original first-party source.
        altered = json.loads(official_export())["events"][0]
        for name, city in (("Other Venue", venue["city"]),
                           (venue["name"], "Paris")):
            bad = copy.deepcopy(altered)
            bad["location"]["name"] = name
            bad["location"]["city"] = city
            with self.subTest(name=name, city=city), self.assertRaises(ValueError):
                oa.verified_export(
                    json.dumps({"total": 1, "events": [bad]}),
                    URL, DAY, placeholder, agenda_uid=9969608,
                    event_uid=87654321)

        # Once a real postcode is known, disagreement is a fatal conflict.
        known_postcode = copy.deepcopy(venue)
        known_postcode["postalCode"] = "31520"
        wrong_postcode = copy.deepcopy(altered)
        wrong_postcode["location"]["postalCode"] = "75001"
        with self.assertRaisesRegex(ValueError, "postal code mismatch"):
            oa.verified_export(
                json.dumps({"total": 1, "events": [wrong_postcode]}),
                URL, DAY, known_postcode, agenda_uid=9969608,
                event_uid=87654321)
        # Real stored street details retain strict existing reconciliation.
        wrong_street = copy.deepcopy(altered)
        wrong_street["location"]["address"] = "99 rue imaginaire"
        with self.assertRaisesRegex(ValueError, "street location mismatch"):
            oa.verified_export(
                json.dumps({"total": 1, "events": [wrong_street]}),
                URL, DAY, venue, agenda_uid=9969608,
                event_uid=87654321)

    def test_fresh_official_openagenda_is_not_starved_by_old_queue(self):
        huge = registry()
        for i in range(32):
            entry = copy.deepcopy(huge["items"]["from-openagenda"])
            candidate = entry["candidate"]
            ident = "older-recheck-%02d" % i
            candidate["candidateId"] = ident
            link = ("https://openagenda.com/fr/shotgun/events/"
                    "older-metal-concert-%02d" % i)
            candidate["sourceUrl"] = link
            candidate["sourcePage"] = link
            candidate["eventDetailUrl"] = link
            candidate.pop("openAgendaUid")
            candidate.pop("openAgendaEventUid")
            huge["items"][ident] = entry
        def only_verified_export(link, cache):
            self.assertEqual(link, EXPORT)
            return official_export()
        # The normal moving window would revisit only one old venue URL at
        # slot=2, leaving the newly discovered OA record waiting for days.
        result, report = producer.build(
            huge, self.catalogue,
            {"schema": publisher.SCHEMA, "approvals": []},
            TODAY, slot=2, limit=1, fetch=only_verified_export)
        self.assertEqual(report["eligibleQueue"], 33)
        self.assertEqual(report["examined"], 1)
        self.assertEqual(report["candidateChecks"][0]["candidateId"],
                         "from-openagenda")
        self.assertEqual(len(result["approvals"]), 1)

    def test_historical_pilot_venue_cannot_blacklist_new_official_oa_bill(self):
        # A protected *event URL/ID* remains immutable. The same once-pilot
        # venue ID must nonetheless be reusable for a different OA concert
        # independently checked by the production publisher.
        def original_record(url, cache):
            self.assertEqual(url, EXPORT)
            return official_export()
        approvals, report = producer.build(
            registry(), self.catalogue,
            {"schema": publisher.SCHEMA, "approvals": []},
            TODAY, fetch=original_record)
        self.assertEqual(len(approvals["approvals"]), 1, report)
        new_event = copy.deepcopy(approvals["approvals"][0])
        old_venue = next(v for v in self.catalogue["venues"]
                         if v["id"] == fixture.VENUE_ID)
        # The synthetic venue ID intentionally models a *historically
        # protected* pilot: no new concert should be denied only because
        # the venue happens to be in such a legacy pilot.
        sentinel = dict(old_venue, id="le-sew-morlaix")
        new_event["event"]["venueId"] = sentinel["id"]
        all_venues = {v["id"]: v for v in self.catalogue["venues"]}
        all_venues[sentinel["id"]] = sentinel
        artists = {a["id"]: a for a in self.catalogue["artists"]}
        with mock.patch.object(identity, "safe_fetch",
                               side_effect=original_record):
            publisher.validate_approval(new_event, all_venues, artists, TODAY)

    def test_forged_ambiguous_or_wrong_style_export_never_approves(self):
        failures = (
            {"status": 2},
            {"eventStatus": "https://schema.org/EventCancelled"},
            {"eventStatus": "EventPostponed"},
            {"firstDate": "2027-03-06"},
            {"origin": {"uid": 987654, "slug": "shotgun"}},
            {"origin": {"uid": 9969608, "slug": "forged"}},
            {"originAgenda": {"uid": 9969608, "slug": "forged"}},
            {"origin": None},
            {"uid": 87654322},
            {"slug": "another-event"},
            {"title": {"fr": "Festival des arts métal"}},
            {"keywords": {"fr": ["Hardcore Techno"]}},
            {"location": {"name": "Another Venue", "city": "Paris",
                           "countryCode": "fr"}},
        )
        for corrupt in failures:
            with self.subTest(corrupt=corrupt):
                def get(url, cache):
                    self.assertEqual(url, EXPORT)
                    return official_export(**corrupt)
                proposals, result = producer.build(
                    registry(), self.catalogue,
                    {"schema": publisher.SCHEMA, "approvals": []},
                    TODAY, fetch=get)
                self.assertEqual(proposals["approvals"], [])
                self.assertEqual(result["stateCounts"],
                    {"held_event_or_source_not_verified": 1})

    def test_real_export_supports_prefixed_or_plain_public_event_slug(self):
        # Actual OpenAgenda JSON uses origin, and its canonical URL may have
        # an immutable UID prefix while the indexed link omits that prefix.
        venue = next(v for v in fixture.BASE["venues"]
                     if v["id"] == fixture.VENUE_ID)
        for page in (URL, "https://openagenda.com/shotgun/events/"
                     "87654321_eight-unknown-metal-bands"):
            names, genres = oa.verified_export(
                official_export(), page, DAY, venue,
                agenda_uid="9969608", event_uid="87654321")
            self.assertEqual(names, fixture.NAMES)
            self.assertIn("punk", genres)

    def test_syndicated_openagenda_public_url_reconciles_to_true_origin(self):
        # A municipal agenda can republish a venue-origin event. Only the
        # original OpenAgenda event UID+agenda UID+slug+canonical permalink
        # may supply publisher authority; the index alias is never signed.
        syndicated = ("https://openagenda.com/ville-de-bordeaux/events/"
                      "87654321_eight-unknown-metal-bands")
        original = ("https://openagenda.com/shotgun/events/"
                    "87654321_eight-unknown-metal-bands")
        permalink = "https://openagenda.com/agendas/9969608/events/87654321"
        payload = official_export(permalink=permalink)
        self.assertEqual(
            oa.original_event_url_from_export(
                payload, syndicated, agenda_uid=9969608,
                event_uid=87654321), original)
        self.assertEqual(
            oa.original_event_url_from_export(
                payload, URL, agenda_uid=9969608,
                event_uid=87654321), URL)
        reg = registry()
        candidate = reg["items"]["from-openagenda"]["candidate"]
        for field in ("sourceUrl", "sourcePage", "eventDetailUrl"):
            candidate[field] = syndicated
        requests = []
        def get(url, cache):
            requests.append(url)
            self.assertEqual(url, EXPORT)
            return payload
        initial = {"schema": publisher.SCHEMA, "approvals": []}
        with mock.patch.object(identity, "safe_fetch", side_effect=get):
            proposals, report = producer.build(
                reg, self.catalogue, initial, TODAY, fetch=get)
            self.assertEqual(report["stateCounts"],
                             {"independently_verified_proposal": 1}, report)
            signed = proposals["approvals"][0]
            self.assertEqual(signed["event"]["officialUrl"], original)
            self.assertEqual(
                signed["officialEvidence"][0]["officialOpenAgendaEventUrl"],
                original)
            self.assertEqual(len(approval_preflight.check_append_only(
                initial, proposals, TODAY)), 1)
            merged, stats = publisher.merge(
                self.catalogue, self.catalogue, proposals, TODAY)
            self.assertEqual(stats["newEvents"], 1, stats["held"])
            self.assertEqual(merged["events"][-1]["officialUrl"], original)
        self.assertGreaterEqual(len(requests), 3)
        self.assertEqual(set(requests), {EXPORT})

    def test_syndicated_origin_is_not_trusted_from_discovery_alone(self):
        syndicated = ("https://openagenda.com/ville-de-bordeaux/events/"
                      "87654321_eight-unknown-metal-bands")
        permalink = "https://openagenda.com/agendas/9969608/events/87654321"
        cases = (
            ({"permalink": None}, syndicated),
            ({"permalink": "https://evil.example/copy"}, syndicated),
            ({"permalink": "https://openagenda.com/agendas/999/events/87654321"},
             syndicated),
            ({"permalink": permalink, "uid": 87654322}, syndicated),
            ({"permalink": permalink, "slug": "different-concert"}, syndicated),
            ({"permalink": permalink,
              "origin": {"uid": 9969609, "slug": "shotgun"}}, syndicated),
            ({"permalink": permalink,
              "originAgenda": {"uid": 9969608, "slug": "forged"}}, syndicated),
            ({"permalink": permalink},
             "https://untrusted.example/ville-de-bordeaux/events/"
             "87654321_eight-unknown-metal-bands"),
            ({"permalink": permalink},
             "https://openagenda.com/ville-de-bordeaux/events/other-event"),
        )
        for changes, candidate_url in cases:
            with self.subTest(changes=changes, url=candidate_url):
                with self.assertRaises(ValueError):
                    oa.original_event_url_from_export(
                        official_export(**changes), candidate_url,
                        agenda_uid=9969608, event_uid=87654321)

    def test_named_lineup_does_not_contain_the_venue_suffix(self):
        venue = next(v for v in fixture.BASE["venues"]
                     if v["id"] == fixture.VENUE_ID)
        names, genres = oa.verified_export(
            official_export(title={"fr": "LocoMuerte + DoorShan - Le Bikini"}),
            URL, DAY, venue, agenda_uid="9969608", event_uid="87654321")
        self.assertEqual(names, ["LocoMuerte", "DoorShan"])
        self.assertIn("punk", genres)
        # Unknown suffixes must not be stripped as if they were this venue.
        wrong, _ = oa.verified_export(
            official_export(title={"fr": "LocoMuerte + DoorShan - Another Room"}),
            URL, DAY, venue, agenda_uid="9969608", event_uid="87654321")
        self.assertEqual(wrong, ["LocoMuerte", "DoorShan - Another Room"])

    def test_numbered_official_street_matches_named_unnumbered_published_pin(self):
        # Historical Ferrailleur map: "Quai des Antilles"; OpenAgenda's
        # exact street adds "21". They are the SAME named point, not a new
        # candidate venue, and the official GPS remains near the map pin.
        site = copy.deepcopy(next(v for v in fixture.BASE["venues"]
                                  if v["id"] == "le-ferrailleur-nantes"))
        site.update(name="Le Ferrailleur", city="Nantes",
                    address="Quai des Antilles", postalCode="44200",
                    latitude=47.20058, longitude=-1.57365,
                    geoPrecision="point du lieu (OpenStreetMap node 373218467)")
        place = {
            "name": "Le Ferrailleur", "city": "Nantes",
            "address": "21 quai des Antilles, 44200 Nantes, France",
            "postalCode": "44200", "countryCode": "fr",
            "latitude": 47.200163, "longitude": -1.573912,
        }
        names, genres = oa.verified_export(
            official_export(location=place, title={"fr": "Sunami + Desolated"}),
            URL, DAY, site, agenda_uid="9969608", event_uid="87654321")
        self.assertEqual(names, ["Sunami", "Desolated"])
        self.assertIn("punk", genres)

        # A different street, remote point, uncertain map, wrong postcode,
        # or contradicting published house number must still be refused.
        cases = (
            ({"address": "21 quai du Port, 44200 Nantes"}, {}, "street"),
            ({"latitude": 47.205, "longitude": -1.573912}, {}, "street"),
            ({"longitude": None}, {}, "street"),
            ({}, {"geoPrecision": "centre de commune"}, "street"),
            ({}, {"address": "20 quai des Antilles"}, "street"),
            ({"postalCode": "44100"}, {}, "postal"),
        )
        for place_change, site_change, reason in cases:
            with self.subTest(place=place_change, site=site_change):
                p = dict(place, **place_change)
                v = dict(site, **site_change)
                with self.assertRaisesRegex(ValueError, reason):
                    oa.verified_export(
                        official_export(location=p, title={"fr": "Sunami + Desolated"}),
                        URL, DAY, v, agenda_uid="9969608",
                        event_uid="87654321")

    def test_same_day_venue_headliner_from_another_url_remains_a_duplicate(self):
        cat = copy.deepcopy(self.catalogue)
        venue = next(v for v in cat["venues"] if v["id"] == "le-ferrailleur-nantes")
        venue.update(name="Le Ferrailleur", city="Nantes",
                     address="Quai des Antilles", postalCode="44200",
                     latitude=47.20058, longitude=-1.57365,
                     geoPrecision="point du lieu (OpenStreetMap node 373218467)")
        if not any(a["id"] == "sunami" for a in cat["artists"]):
            cat["artists"].append({"id": "sunami", "name": "Sunami", "aliases": []})
        cat["events"].append({
            "id": "go-c-signed-existing-sunami", "title": "Sunami + Desolated",
            "date": DAY, "artistIds": ["sunami"],
            "venueId": "le-ferrailleur-nantes",
            "officialUrl": "https://www.leferrailleur.fr/agenda",
        })
        lead = registry()
        candidate = lead["items"]["from-openagenda"]["candidate"]
        candidate.update(name="Sunami + Desolated", leadArtist="Sunami",
                         venue="Le Ferrailleur", city="Nantes",
                         department=None)
        place = {
            "name": "Le Ferrailleur", "city": "Nantes",
            "address": "21 quai des Antilles, 44200 Nantes, France",
            "postalCode": "44200", "countryCode": "fr",
            "latitude": 47.200163, "longitude": -1.573912,
        }
        def official(link, cache):
            self.assertEqual(link, EXPORT)
            return official_export(location=place,
                                   title={"fr": "Sunami + Desolated"})
        proposed, report = producer.build(
            lead, cat, {"schema": publisher.SCHEMA, "approvals": []},
            TODAY, fetch=official)
        self.assertEqual(report["examined"], 1)
        self.assertEqual(proposed["approvals"], [])
        self.assertTrue(any("already published or overlapping concert" in key
                            for key in report["rejectionReasons"]))

    def test_named_lineup_removes_only_exact_venue_and_city_suffix(self):
        # Real official titles may append BOTH the venue and city.
        # Neither part belongs to the support act's artist identity.
        venue = copy.deepcopy(next(v for v in fixture.BASE["venues"]
                                  if v["id"] == fixture.VENUE_ID))
        venue.update(name="Fury Défendu", city="Rouen",
                     postalCode="76000", address="2 Quai Pierre Corneille")
        location = {
            "name": "Fury Défendu", "city": "Rouen",
            "postalCode": "76000", "countryCode": "fr",
            "address": "2 Quai Pierre Corneille, 76000 Rouen, France",
        }
        for title, expected in (
            ("Wake the dead + devotion - Fury defendu - Rouen",
             ["Wake the dead", "devotion"]),
            ("Wake the dead - Fury defendu - Rouen", ["Wake the dead"]),
            ("Wake the dead + devotion - Another Room - Rouen",
             ["Wake the dead", "devotion - Another Room - Rouen"]),
            ("Wake the dead + devotion - Fury defendu - Paris",
             ["Wake the dead", "devotion - Fury defendu - Paris"]),
        ):
            with self.subTest(title=title):
                names, genres = oa.verified_export(
                    official_export(location=location, title={"fr": title}),
                    URL, DAY, venue, agenda_uid="9969608",
                    event_uid="87654321")
                self.assertEqual(names, expected)
                self.assertIn("punk", genres)

    def test_untrusted_ids_cannot_change_first_party_origin(self):
        for ids in ((-1, 87654321), ("9969608/evil", "87654321"),
                    (9969608, "1?x=2"), (False, 87654321)):
            with self.subTest(ids=ids):
                with self.assertRaises(ValueError):
                    oa.official_export_url(*ids)


if __name__ == "__main__":
    unittest.main()
