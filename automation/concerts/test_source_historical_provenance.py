"""Prior signed and published history may corroborate, never auto-authorize."""
import copy
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import source_historical_provenance as provenance
import source_admission_intake as intake

DAY = dt.date(2026, 11, 21)
HOST = "metal-farm.fr"
VENUE = {"id": "new-venue-875", "name": "La Ferme Metal",
         "city": "Petite Ville", "department": "25"}


def queue(host=HOST, *, venue="La Ferme Metal", city="Petite Ville"):
    return {
        "schema": intake.SCHEMA,
        "automaticTrustGranted": False, "publicationAllowed": False,
        "reviewQueue": [{
            "host": host, "alreadyReviewedAuthority": False,
            "stableOnDistinctDays": 3, "eventLeads": 2,
            "venues": [venue], "cities": [city], "examples": [],
        }],
    }


def record(i, host=HOST, venue_id=VENUE["id"]):
    url = f"https://{host}/agenda/unknown-{i}/"
    return {
        "id": f"go-c-2027030{i}-petite-ville-unknown-metal-{i}",
        "date": f"2027-03-0{i}",
        "officialUrl": url, "venueId": venue_id,
        "genres": ["Death Metal"], "artistIds": [f"new-unknown-{i}"],
        "status": "confirmed",
    }


def approved(event, *, reviewed_by="independent-official-verifier"):
    return {
        "reviewDecision": "approved", "reviewedBy": reviewed_by,
        "reviewedAt": "2026-11-19",
        "event": copy.deepcopy(event),
        "officialEvidence": [{
            "url": event["officialUrl"],
            "checkedAt": "2026-11-19",
            "proofType": "official-organizer-or-venue",
            "checkedFields": ["artists", "date", "venue", "genre"],
        }],
    }


def fixture():
    events = [record(1), record(2)]
    return (queue(),
            {"schema": provenance.APPROVALS,
             "approvals": [approved(e) for e in events]},
            {"schemaVersion": 1, "venues": [copy.deepcopy(VENUE)],
             "events": copy.deepcopy(events)},
            {"schema": provenance.CATALOGUE,
             "venues": [{**VENUE,
                         "url": "https://" + HOST + "/agenda/"}]})


class HistoricalProvenanceTests(unittest.TestCase):
    def test_two_independent_approved_and_published_events_recover_source_history(self):
        q, a, c, s = fixture()
        original = copy.deepcopy((q, a, c, s))
        report = provenance.build(q, a, c, s, DAY)
        self.assertEqual(report["unreviewedSourceHostsConsidered"], 1)
        self.assertEqual(report["previouslySignedPublishedVenueOrigins"], 1)
        r = report["originChecks"][0]
        self.assertEqual(r["historicalVenueCandidates"][0]["venueId"], VENUE["id"])
        self.assertEqual(r["historicalVenueCandidates"][0]["historicalPublishedApprovals"], 2)
        self.assertTrue(r["historicalSignedProof"])
        self.assertFalse(r["sourceOwnershipFreshlyVerified"])
        self.assertFalse(r["automaticTrustGranted"])
        self.assertFalse(r["publicationAllowed"])
        self.assertEqual((q, a, c, s), original)

    def test_one_approval_is_not_enough(self):
        q, a, c, s = fixture()
        a["approvals"].pop()
        report = provenance.build(q, a, c, s, DAY)
        self.assertEqual(report["previouslySignedPublishedVenueOrigins"], 0)
        self.assertEqual(report["stillWithoutHistoricalProvenance"], 1)

    def test_not_in_public_catalogue_is_not_a_published_proof(self):
        q, a, c, s = fixture()
        c["events"].pop()
        report = provenance.build(q, a, c, s, DAY)
        self.assertEqual(report["previouslySignedPublishedVenueOrigins"], 0)

    def test_spoofed_independent_proof_is_not_admitted(self):
        variations = []
        q, a, c, s = fixture()
        evil = copy.deepcopy(a)
        evil["approvals"][1]["reviewedBy"] = "untrusted-reviewer"
        variations.append((q, evil, c, s))
        evil = copy.deepcopy(a)
        evil["approvals"][1]["officialEvidence"][0]["url"] = (
            "https://forged.example.org/agenda/another/")
        variations.append((q, evil, c, s))
        evil = copy.deepcopy(a)
        evil["approvals"][1]["officialEvidence"][0]["checkedAt"] = "2026-11-20"
        variations.append((q, evil, c, s))
        evil = copy.deepcopy(a)
        evil["approvals"][1]["event"]["genres"] = []
        variations.append((q, evil, c, s))
        evil = copy.deepcopy(a)
        evil["approvals"][1]["event"]["officialUrl"] = (
            "https://unrelated-venue.fr/agenda/not-metal/")
        variations.append((q, evil, c, s))
        evil = copy.deepcopy(a)
        evil["approvals"][1]["event"]["date"] = "2026-01-01"
        variations.append((q, evil, c, s))
        evil = copy.deepcopy(a)
        evil["approvals"][1]["reviewDecision"] = "held"
        variations.append((q, evil, c, s))
        for args in variations:
            with self.subTest(error=args[1]["approvals"][1]):
                self.assertEqual(
                    provenance.build(*args, DAY)[
                        "previouslySignedPublishedVenueOrigins"], 0)

    def test_same_host_cannot_substitute_different_venue_or_city(self):
        q, a, c, s = fixture()
        q["reviewQueue"][0]["venues"] = ["Autre Salle"]
        self.assertEqual(
            provenance.build(q, a, c, s, DAY)[
                "previouslySignedPublishedVenueOrigins"], 0)
        q, a, c, s = fixture()
        q["reviewQueue"][0]["cities"] = ["Autre Ville"]
        self.assertEqual(
            provenance.build(q, a, c, s, DAY)[
                "previouslySignedPublishedVenueOrigins"], 0)
        q, a, c, s = fixture()
        s["venues"][0]["url"] = "https://forged-source.fr/agenda/"
        self.assertEqual(
            provenance.build(q, a, c, s, DAY)[
                "previouslySignedPublishedVenueOrigins"], 0)

    def test_one_publisher_approval_reused_twice_is_still_one(self):
        q, a, c, s = fixture()
        a["approvals"] = [a["approvals"][0], copy.deepcopy(a["approvals"][0])]
        self.assertEqual(
            provenance.build(q, a, c, s, DAY)[
                "previouslySignedPublishedVenueOrigins"], 0)

    def test_research_not_limited_to_known_artist_or_fixed_domain_roster(self):
        q, a, c, s = fixture()
        out = provenance.build(q, a, c, s, DAY)
        self.assertEqual(out["previouslySignedPublishedVenueOrigins"], 1)
        for i in range(35):
            other_host = f"random-new-metal-{i:02d}.fr"
            q["reviewQueue"].append({
                "host": other_host, "alreadyReviewedAuthority": False,
                "venues": ["Another Unknown Venue"],
                "cities": ["Somewhere in France"], "examples": [],
                "stableOnDistinctDays": 1,
            })
        out = provenance.build(q, a, c, s, DAY)
        self.assertEqual(out["unreviewedSourceHostsConsidered"], 36)
        self.assertEqual(out["previouslySignedPublishedVenueOrigins"], 1)
        self.assertEqual(out["stillWithoutHistoricalProvenance"], 35)
        self.assertFalse(out["automaticTrustGranted"])

    def test_invalid_structures_fail_closed(self):
        q, a, c, s = fixture()
        for args in (
            ({}, a, c, s, DAY),
            (q, {"schema": "wrong", "approvals": []}, c, s, DAY),
            (q, a, {"schemaVersion": 1}, s, DAY),
            (q, a, c, {"schema": "other", "venues": []}, DAY),
            (q, a, c, s, "2026-11-21"),
        ):
            with self.assertRaises(ValueError):
                provenance.build(*args)


if __name__ == "__main__":
    unittest.main()
