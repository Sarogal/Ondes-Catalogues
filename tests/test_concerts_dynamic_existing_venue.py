"""Open-ended Concerts existing-venue admission, publisher and negative paths."""
import copy
import datetime as dt
import json
import unittest
from pathlib import Path
from unittest import mock

from scripts import concerts_cloud_sync as publisher
from scripts import concert_dynamic_existing_venue as dynamic
from automation.concerts import approval_preflight

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / "docs/grossesondes/concerts-reference.json").read_text())
PUBLISHED = json.loads((ROOT / "docs/grossesondes/concerts.json").read_text())
TODAY = dt.date(2026, 11, 21)
VENUE_ID = "le-bikini-toulouse"
# The immutable 2025 reference intentionally has an unverified municipal
# centroid for Le Bikini. This publisher test must use the ACTUAL published
# venue identity (with verified OSM node), never pretend the historical
# reference already possessed today's correct named geolocation.
BASE["venues"] = [
    copy.deepcopy(next(v for v in PUBLISHED["venues"] if v["id"] == VENUE_ID))
    if v["id"] == VENUE_ID else v
    for v in BASE["venues"]
]
MAIN = "https://nouveau-domaine-independant.fr/2027/03/05/metal-event/"
# Synthetic first-party host must be linked from OSM; never included in a manifest.
EVENT = "https://nouveau-domaine-independant.fr/2027/03/05/metal-event/"
WITNESS = "https://artiste-exemple.fr/tour/2027/bikini"
NAMES = [f"Groupe Libre {n}" for n in range(1, 9)]
IDS = [f"groupe-libre-{n}" for n in range(1, 9)]


def signed_approval(event_url=EVENT):
    venue = next(v for v in BASE["venues"] if v["id"] == VENUE_ID)
    return {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": TODAY.isoformat(),
        "officialEvidence": [{
            "url": event_url, "proofType": dynamic.PROFILE,
            "checkedAt": TODAY.isoformat(),
            "checkedFields": list(dynamic.CHECKED),
            "officialArtistNames": list(NAMES),
            "officialGenreLabels": ["Black Metal"],
            "namedOsmUrl": venue["geoSource"],
            "corroboratingEventUrl": WITNESS,
        }],
        "event": {
            "id": "go-c-20270305-ramonville-saint-agne-groupe-libre-1",
            "title": " + ".join(NAMES), "date": "2027-03-05",
            "time": None, "artistIds": list(IDS),
            "venueId": VENUE_ID, "genres": ["Black Metal"],
            "status": "confirmed", "officialUrl": event_url,
            "sourceType": "salle",
        },
        "newArtists": [{"id": i, "name": n} for i, n in zip(IDS, NAMES)],
    }


def page(url, *, names=NAMES, genres=True, venue_name="Le Bikini",
         postal="31520", city="Ramonville-Saint-Agne",
         date="2027-03-05", country="FR", status="", music=True,
         event_name=None):
    venue = next(v for v in BASE["venues"] if v["id"] == VENUE_ID)
    node = {
        "@context": "https://schema.org",
        "@type": "MusicEvent" if music else "Event",
        "name": event_name or " + ".join(names), "url": url,
        "startDate": date + "T20:00:00+01:00",
        "eventStatus": status,
        "performer": [{"@type": "MusicGroup", "name": n} for n in names],
        "location": {
            "@type": "Place", "name": venue_name,
            "address": {"@type": "PostalAddress", "addressCountry": country,
                        "addressLocality": city, "postalCode": postal,
                        "streetAddress": venue["address"]},
        },
    }
    if genres:
        node["genre"] = ["Black Metal"]
    return ("<html><body><main><h1>Nouvel événement</h1><script "
            "type='application/ld+json'>" + json.dumps(node)
            + "</script></main><p>Programme officiel du concert</p></body></html>")


def osm(*, name="Le Bikini", website="https://nouveau-domaine-independant.fr",
        lat="43.54795", lon="1.48568", country="FR"):
    return (f'<osm version="0.6"><node id="380889428" lat="{lat}" lon="{lon}">'
            f'<tag k="name" v="{name}"/><tag k="website" v="{website}"/>'
            f'<tag k="addr:city" v="Ramonville-Saint-Agne"/>'
            f'<tag k="addr:postcode" v="31520"/>'
            f'<tag k="addr:country" v="{country}"/></node></osm>')


def fake_fetch(modifications=None):
    modifications = modifications or {}
    venue = next(v for v in BASE["venues"] if v["id"] == VENUE_ID)
    assert venue["geoSource"].endswith("380889428")
    def fetch(url, cache):
        if url.startswith("https://api.openstreetmap.org/api/0.6/node/"):
            return modifications.get("osm", osm())
        if url == EVENT:
            return modifications.get("primary", page(EVENT))
        if url == WITNESS:
            return modifications.get("secondary",
                                     page(WITNESS, names=[NAMES[0]]))
        raise AssertionError("unexpected network URL: " + url)
    return fetch


class UnlistedExistingVenueTests(unittest.TestCase):
    def setUp(self):
        # The immutable reference still contains the ORIGINAL unlocated Bikini.
        # In this synthetic test the venue is already geo-corrected at the
        # baseline; exclude only its legacy migration patch, which production
        # continues to enforce with a persisted independent signed approval.
        original = publisher.NEW_REFERENCE_GEO_SOURCES.pop(VENUE_ID, None)
        self.assertIsNotNone(original)
        self.addCleanup(lambda: publisher.NEW_REFERENCE_GEO_SOURCES.__setitem__(
            VENUE_ID, original))

    def test_unknown_domain_and_eight_unknown_artists_publish_without_manifest(self):
        approval = signed_approval()
        calls = []
        fetch = fake_fetch()
        def visit(url, cache):
            calls.append(url)
            return fetch(url, cache)
        with mock.patch.object(dynamic, "safe_fetch", side_effect=visit):
            self.assertTrue(dynamic.validate(
                approval, {v["id"]: v for v in BASE["venues"]},
                {a["id"]: a for a in BASE["artists"]}, TODAY))
            proposed = {"schema": publisher.SCHEMA, "approvals": [approval]}
            old = {"schema": publisher.SCHEMA, "approvals": []}
            accepted = approval_preflight.check_append_only(old, proposed, TODAY)
            self.assertEqual(len(accepted), 1)
            # Never call a special-case venue verifier or edit a manifest.
            published, counts = publisher.merge(BASE, BASE, proposed, TODAY)
        self.assertEqual(counts["newEvents"], 1)
        self.assertEqual(counts["newArtists"], 8)
        self.assertEqual(counts["newVenues"], 0)
        self.assertEqual(len(published["events"]), len(BASE["events"]) + 1)
        self.assertEqual(published["venues"], BASE["venues"])
        self.assertEqual([a["id"] for a in published["artists"][-8:]], IDS)
        self.assertIn(EVENT, calls)
        self.assertIn(WITNESS, calls)
        self.assertTrue(any("api.openstreetmap.org" in x for x in calls))
        # Signed replay cannot insert another event or artist.
        with mock.patch.object(dynamic, "safe_fetch",
                               side_effect=AssertionError("old approval must not re-fetch")):
            replay, repeated = publisher.merge(BASE, published, proposed, TODAY)
        self.assertEqual(replay, published)
        self.assertEqual(repeated["newEvents"], 0)

    def test_private_national_cross_source_to_publisher_no_allowlist(self):
        from automation.concerts import dynamic_first_party_venue_proposals as proposed_source
        from automation.concerts import source_cross_domain_live_recheck as cross
        report = {
            "schema": cross.SCHEMA,
            "publicationAllowed": False,
            "sourceOwnershipVerified": False,
            "checks": [{
                "date": "2027-03-05", "leadArtist": NAMES[0],
                "city": "Ramonville-Saint-Agne", "venue": "bikini",
                "publishedAlreadyKnown": False,
                "markedPossibleDuplicate": False,
                "sourceOwnershipVerified": False,
                "publicationAllowed": False,
                "crossDomainEventVerified": True,
                "verifiedWitnesses": [
                    {"url": EVENT, "host": "nouveau-domaine-independant.fr"},
                    {"url": WITNESS, "host": "artiste-exemple.fr"},
                ],
            }],
        }
        seed = {"schema": publisher.SCHEMA, "approvals": []}
        proposals, metrics = proposed_source.build(
            report, BASE, seed, TODAY, fetch=fake_fetch())
        self.assertEqual(metrics["stateCounts"]["publisher_proposals"], 1)
        self.assertEqual(len(proposals["approvals"]), 1)
        self.assertEqual(seed["approvals"], [])
        approval = proposals["approvals"][0]
        self.assertEqual(approval["event"]["artistIds"], IDS)
        self.assertEqual(approval["newArtists"], [
            {"id": ident, "name": name}
            for ident, name in zip(IDS, NAMES)])
        with mock.patch.object(dynamic, "safe_fetch", side_effect=fake_fetch()):
            stats = approval_preflight.validate_proposal(
                seed, proposals, BASE, BASE, TODAY, publisher.merge)
        self.assertEqual(stats["newApprovals"], 1)
        self.assertTrue(stats["validatedByPublisher"])

    def test_private_cross_source_does_not_trust_failed_correlations(self):
        from automation.concerts import dynamic_first_party_venue_proposals as proposed_source
        from automation.concerts import source_cross_domain_live_recheck as cross
        base = {"schema": cross.SCHEMA, "publicationAllowed": False,
                "sourceOwnershipVerified": False,
                "checks": [{
                    "date": "2027-03-05", "leadArtist": NAMES[0],
                    "city": "Ramonville-Saint-Agne", "venue": "bikini",
                    "publishedAlreadyKnown": False,
                    "markedPossibleDuplicate": False,
                    "sourceOwnershipVerified": False, "publicationAllowed": False,
                    "crossDomainEventVerified": True,
                    "verifiedWitnesses": [
                        {"url": EVENT, "host": "nouveau-domaine-independant.fr"},
                        {"url": WITNESS, "host": "artiste-exemple.fr"},
                    ],
                }]}
        seed = {"schema": publisher.SCHEMA, "approvals": []}
        for variant in ("not_verified", "already_published", "new_venue",
                        "forged_venue", "bad_second_source", "no_osm_owner"):
            with self.subTest(variant=variant):
                report = copy.deepcopy(base)
                item = report["checks"][0]
                kwargs = {}
                if variant == "not_verified":
                    item["crossDomainEventVerified"] = False
                elif variant == "already_published":
                    item["publishedAlreadyKnown"] = True
                elif variant == "new_venue":
                    item["venue"] = "inconnu"
                elif variant == "forged_venue":
                    item["city"] = "Nantes"
                elif variant == "bad_second_source":
                    kwargs = {"secondary": page(WITNESS, names=["Faux Groupe"])}
                elif variant == "no_osm_owner":
                    kwargs = {"osm": osm(website="https://autre-site.fr")}
                out, metric = proposed_source.build(
                    report, BASE, seed, TODAY, fetch=fake_fetch(kwargs))
                self.assertEqual(out, seed)
                self.assertGreaterEqual(
                    metric["stateCounts"].get("held_needs_other_evidence", 0), 1)

    def test_source_identity_and_exact_event_contradictions_hold(self):
        for case, changed in (
            ("source-owner", {"osm": osm(website="https://unrelated.fr")}),
            ("missing-name", {"osm": osm(name="Another Venue")}),
            ("wrong-country", {"osm": osm(country="GB")}),
            ("wrong-geo", {"osm": osm(lat="44.0")}),
            ("changed-bill", {"primary": page(EVENT, names=NAMES[:-1])}),
            ("changed-date", {"primary": page(EVENT, date="2027-03-06")}),
            ("foreign-event", {"primary": page(EVENT, country="GB")}),
            ("wrong-room", {"primary": page(EVENT, venue_name="Other Place")}),
            ("nonconcert", {"primary": page(EVENT, music=False)}),
            ("festival-not-a-concert", {"primary": page(
                EVENT, event_name="Festival des métaux 2027")}),
            ("no-genre", {"primary": page(EVENT, genres=False)}),
            ("cancelled", {"primary": page(EVENT, status="EventCancelled")}),
            ("forged-witness", {"secondary": page(WITNESS, names=["Another Artist"])}),
            ("changed-witness-place", {"secondary": page(
                WITNESS, names=[NAMES[0]], city="Bordeaux")}),
        ):
            with self.subTest(case=case):
                approval = signed_approval()
                with mock.patch.object(dynamic, "safe_fetch",
                                       side_effect=fake_fetch(changed)):
                    result, counts = publisher.merge(
                        BASE, BASE,
                        {"schema": publisher.SCHEMA, "approvals": [approval]}, TODAY)
                # Publisher intentionally records invalid approvals in the
                # private held queue instead of raising from merge(). Verify
                # the rejection comes from the independent dynamic contract,
                # rather than a legacy per-venue pilot allowlist.
                self.assertEqual(result, BASE)
                self.assertEqual(counts["newEvents"], 0)
                self.assertEqual(len(counts["held"]), 1)
                if case in ("forged-witness", "changed-witness-place"):
                    # Independent second-domain event verification rejects
                    # the mismatched artist or city before dynamic.validate
                    # can add its own context prefix.
                    self.assertIn("No unique exact dated/named site and band bill",
                                  counts["held"][0]["reason"])
                else:
                    self.assertIn("Unlisted official source:",
                                  counts["held"][0]["reason"])

    def test_same_apex_witness_not_independent(self):
        row = signed_approval()
        row["officialEvidence"][0]["corroboratingEventUrl"] = (
            "https://tickets.nouveau-domaine-independant.fr/another-page")
        with mock.patch.object(dynamic, "safe_fetch", side_effect=fake_fetch()):
            with self.assertRaisesRegex(ValueError, "same source apex"):
                dynamic.validate(
                    row, {v["id"]: v for v in BASE["venues"]},
                    {a["id"]: a for a in BASE["artists"]}, TODAY)

    def test_unknown_source_refused_without_osm_website_or_secondary(self):
        record = signed_approval()
        for mod in ("without-osm", "secondary-missing", "false-attribution"):
            with self.subTest(mod=mod):
                row = copy.deepcopy(record)
                if mod == "secondary-missing":
                    row["officialEvidence"][0].pop("corroboratingEventUrl")
                elif mod == "false-attribution":
                    row["officialEvidence"][0]["namedOsmUrl"] = (
                        "https://www.openstreetmap.org/node/98765")
                otherwise = {"osm": osm(website="https://bad.example")}
                with mock.patch.object(dynamic, "safe_fetch",
                                       side_effect=fake_fetch(otherwise)):
                    with self.assertRaises((ValueError, KeyError, TypeError)):
                        dynamic.validate(
                            row, {v["id"]: v for v in BASE["venues"]},
                            {a["id"]: a for a in BASE["artists"]}, TODAY)

    def test_duplicates_stay_unpublishable(self):
        # An existing event already using the same named artist at the same
        # room/date cannot be re-created under a different generated ID.
        approval = signed_approval()
        public = copy.deepcopy(BASE)
        public["artists"].extend(
            {"id": i, "name": n, "aliases": []} for i, n in zip(IDS, NAMES))
        public["events"].append({
            "id": "go-c-20270305-ramonville-duplicate",
            "title": NAMES[0], "date": "2027-03-05",
            "artistIds": [IDS[0]], "venueId": VENUE_ID,
            "genres": ["Black Metal"], "status": "confirmed",
            "officialUrl": "https://other.example/real",
            "sourceType": "salle",
        })
        # This test checks duplicate detection without using forged prior
        # approvals for the old event.
        self.assertTrue(any(
            e["date"] == approval["event"]["date"]
            and e["venueId"] == approval["event"]["venueId"]
            and bool(set(e["artistIds"]) & set(approval["event"]["artistIds"]))
            for e in public["events"]))


if __name__ == "__main__":
    unittest.main()
