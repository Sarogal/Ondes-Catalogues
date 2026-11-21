"""Cross-origin leads signal research opportunities, never publisher trust."""
import copy
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import source_cross_domain_corroboration as cross

DAY = dt.date(2026, 11, 21)
CATALOGUE = {"schemaVersion": 1, "events": []}


def lead(host="artist.fr", *, artist="UNKNOWN METAL BAND",
         title="UNKNOWN METAL BAND", venue="La Salle Nouvelle",
         city="Bordeaux", date="2027-03-12", stable=2,
         status="pending_review", bucket="genre_tag_review"):
    url = "https://" + host + "/agenda/unknown-metal/"
    return {
        "status": status, "stableObservations": stable,
        "candidate": {
            "candidateId": host + date + title,
            "source": "artist_official_tour_listing",
            "sourceUrl": url, "date": date,
            "name": title, "leadArtist": artist,
            "venue": venue, "city": city,
            "reviewBucket": bucket, "publicationAllowed": False,
            "reviewRequired": True, "possibleExistingConcert": False,
        },
    }


def registry(*rows):
    return {"schema": "grossesondes.concert.intake.v1",
            "items": {f"i{n}": x for n, x in enumerate(rows)}}


class CrossHostEvidenceTests(unittest.TestCase):
    def test_artist_and_venue_domains_match_without_known_bands_or_venues(self):
        record = registry(
            lead(),
            lead("new-venue.fr", venue="Salle Nouvelle",
                 title="UNKNOWN METAL BAND + JAZZ OPENER"))
        frozen = copy.deepcopy(record)
        out = cross.build(record, CATALOGUE, DAY)
        self.assertEqual(out["futureCrossDomainLeadGroups"], 1)
        self.assertEqual(out["stableSameVenueCrossDomainGroups"], 1)
        show = out["groups"][0]
        self.assertEqual(show["leadArtist"], "unknown metal band")
        self.assertEqual(show["distinctDomainHints"], 2)
        self.assertEqual(show["normalizedVenue"], "salle nouvelle")
        self.assertEqual(len(show["sources"]), 2)
        self.assertFalse(show["independentOwnershipVerified"])
        self.assertFalse(show["automaticTrustGranted"])
        self.assertFalse(show["publicationAllowed"])
        self.assertEqual(record, frozen)

    def test_late_second_source_observation_stays_in_waiting_bucket(self):
        out = cross.build(registry(lead(),
                                  lead("new-venue.fr", stable=1)), CATALOGUE, DAY)
        self.assertEqual(out["futureCrossDomainLeadGroups"], 1)
        self.assertEqual(out["awaitingSecondDayGroups"], 1)
        self.assertEqual(out["stableSameVenueCrossDomainGroups"], 0)

    def test_two_subdomains_one_owner_are_not_independent_sources(self):
        out = cross.build(registry(
            lead("www.example-venue.fr"), lead("tickets.example-venue.fr")),
            CATALOGUE, DAY)
        self.assertEqual(out["futureCrossDomainLeadGroups"], 0)

    def test_wrong_date_city_and_band_do_not_corroborate(self):
        for changes in ({"date": "2027-03-13"},
                        {"city": "Toulouse"},
                        {"artist": "ANOTHER METAL BAND"}):
            out = cross.build(registry(lead(), lead("new-venue.fr", **changes)),
                              CATALOGUE, DAY)
            self.assertEqual(out["futureCrossDomainLeadGroups"], 0)

    def test_conflicting_venue_names_never_claim_same_physical_place(self):
        out = cross.build(registry(
            lead(), lead("other.org", venue="Un Autre Lieu")), CATALOGUE, DAY)
        self.assertEqual(out["conflictingVenueGroups"], 1)
        self.assertEqual(out["stableSameVenueCrossDomainGroups"], 0)
        self.assertIsNone(out["groups"][0]["normalizedVenue"])

    def test_many_support_bands_never_limit_research(self):
        out = cross.build(registry(
            lead(), lead("new-venue.fr", title="UNKNOWN METAL BAND + "
                 + " + ".join(f"JAZZ SUPPORT {i}" for i in range(42)))),
            CATALOGUE, DAY)
        self.assertEqual(out["stableSameVenueCrossDomainGroups"], 1)

    def test_festival_cancelled_untrusted_and_expired_are_not_counted(self):
        candidates = [
            lead(), lead("new-venue.fr", bucket="festival_overlap_review"),
            lead("other.org", bucket="cancellation_watch"),
            lead("third.fr", date="2026-10-10"),
            lead("bad.fr", status="rejected"),
            lead("localhost", status="pending_review"),
        ]
        out = cross.build(registry(*candidates), CATALOGUE, DAY)
        self.assertEqual(out["futureCrossDomainLeadGroups"], 0)
        self.assertFalse(out["automaticTrustGranted"])

    def test_already_published_exactly_matched_lead_is_not_recorroborated(self):
        first = lead()
        catalogue = {"schemaVersion": 1, "events": [{
            "date": first["candidate"]["date"],
            "officialUrl": first["candidate"]["sourceUrl"],
        }]}
        out = cross.build(registry(first, lead("new-venue.fr")),
                          catalogue, DAY)
        self.assertEqual(out["futureCrossDomainLeadGroups"], 0)

    def test_malformed_private_registry_fails_closed(self):
        for bad in ({}, {"schema": "wrong", "items": {}},
                    {"schema": "grossesondes.concert.intake.v1", "items": []}):
            with self.assertRaises(ValueError):
                cross.build(bad, CATALOGUE, DAY)


if __name__ == "__main__":
    unittest.main()
