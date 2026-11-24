"""No-network contract for an OPEN WORLD of artists, rooms and tours."""
import copy
import datetime as dt
import unittest

from automation.concerts import open_world_frontier as frontier

TODAY = dt.date(2026, 11, 24)


def public(artists=None, venues=None, events=None):
    return {
        "schemaVersion": 1,
        "artists": artists if artists is not None else [
            {"id": "old-group", "name": "Old Group"},
        ],
        "venues": venues if venues is not None else [
            {"id": "v1", "name": "Former Club", "city": "Lille",
             "department": "59"},
        ],
        "events": events if events is not None else [
            {"id": "old-show", "date": "2025-01-01",
             "artistIds": ["old-group"], "venueId": "v1",
             "genres": ["Metal"]},
        ],
    }


def lead(identifier, date, artist, venue, city, *, dept="34", **extra):
    c = {
        "candidateId": identifier, "date": date, "leadArtist": artist,
        "venue": venue, "city": city, "department": dept,
        "source": "agenda_officiel_structuré",
        "publicationAllowed": False, "reviewRequired": True,
    }
    c.update(extra)
    return {
        "status": "pending_review", "stableObservations": 1,
        "candidate": c,
    }


def registry(items):
    return {"schema": "grossesondes.concert.intake.v1", "items": items}


class OpenWorldFrontierTests(unittest.TestCase):
    def test_unknown_room_band_and_tour_stop_are_discovered_without_allowlists(self):
        private = registry({
            "1": lead("1", "2027-02-10", "Aster + New Band",
                      "Brand New Venue", "Montpellier"),
            "2": lead("2", "2027-03-12", "Aster",
                      "Brand New Venue", "Montpellier"),
            "3": lead("3", "2027-04-02", "New Band",
                      "Unlisted Club", "Nantes", dept="44"),
        })
        report = frontier.build(public(), private, TODAY)
        self.assertFalse(report["publicationAllowed"])
        self.assertEqual(report["approvalsProposed"], 0)
        self.assertEqual(report["networkRequests"], 0)
        self.assertEqual(report["counts"]["unlistedVenues"], 2)
        self.assertEqual(report["counts"]["unlistedArtists"], 2)
        self.assertEqual(report["counts"]["artistVenueDateRelations"], 5)
        self.assertEqual({a["name"] for a in report["artistResearch"]},
                         {"Old Group", "Aster", "New Band"})
        self.assertEqual({v["name"] for v in report["venueResearch"]},
                         {"Former Club", "Brand New Venue", "Unlisted Club"})
        self.assertTrue(all(v["researchOnly"] for v in report["venueResearch"]))

    def test_solo_is_not_inferred_to_be_band_member_or_replacement(self):
        private = registry({
            "a": lead("a", "2027-01-02", "Old Group Solo",
                      "Another Site", "Lyon", dept="69"),
        })
        report = frontier.build(public(), private, TODAY)
        names = {x["name"]: x for x in report["artistResearch"]}
        self.assertIn("Old Group", names)
        self.assertIn("Old Group Solo", names)
        self.assertNotEqual(names["Old Group"]["key"],
                            names["Old Group Solo"]["key"])
        self.assertIsNone(names["Old Group Solo"]["knownArtistId"])
        self.assertFalse(report["rules"]["soloActInheritsBandIdentity"])

    def test_per_artist_genres_are_not_inherited_from_the_full_bill(self):
        private = registry({
            "x": lead("x", "2027-01-15", "Punk Band + Jazz Guest",
                      "Another Site", "Paris", dept="75",
                      classification=["Punk", "Jazz"]),
        })
        report = frontier.build(public(), private, TODAY)
        names = {a["name"]: a for a in report["artistResearch"]}
        self.assertIn("Punk Band", names)
        self.assertIn("Jazz Guest", names)
        self.assertTrue(all("genre" not in a and "classification" not in a
                            for a in names.values()))
        self.assertFalse(report["rules"]["genreInheritedFromOtherArtistsOnBill"])

    def test_no_dates_does_not_close_an_existing_artist_or_venue(self):
        data = public()
        data["events"] = []
        report = frontier.build(data, registry({}), TODAY)
        self.assertEqual(report["counts"]["totalArtistIdentities"], 1)
        self.assertEqual(report["counts"]["totalVenueIdentities"], 1)
        self.assertFalse(report["rules"]["venueClosesWhenNoShows"])
        self.assertIn("Old Group", [x["name"] for x in report["artistResearch"]])

    def test_untrusted_or_past_or_cancelled_leads_never_authorize_anything(self):
        private = registry({
            "old": lead("old", "2025-05-05", "Old Party",
                        "Past Venue", "Paris"),
            "bad": lead("bad", "2027-07-01", "Malicious Artist",
                        "Malicious Room", "Paris",
                        sourceUrl="http://169.254.169.254/latest"),
            "cancel": lead("cancel", "2027-08-01", "Cancelled Artist",
                           "Cancelled Room", "Paris", cancellationNotice=True),
            "approved": lead("approved", "2027-09-01", "Unverified Artist",
                             "Unverified Room", "Paris", publicationAllowed=True),
        })
        result = frontier.build(public(), private, TODAY)
        self.assertEqual(result["counts"]["unlistedVenues"], 1)
        self.assertEqual(result["counts"]["unlistedArtists"], 1)
        self.assertNotIn("169.254", str(result))
        self.assertNotIn("http://", str(result))
        self.assertFalse(result["rules"]["candidateIsOfficialProof"])

    def test_three_slots_and_following_days_cover_new_and_existing_identities(self):
        known_artists = [
            {"id": f"known-{i}", "name": f"Known Group {i}"}
            for i in range(54)
        ]
        known_venues = [
            {"id": f"known-venue-{i}", "name": f"Existing Hall {i}",
             "city": "Rennes", "department": "35"}
            for i in range(54)
        ]
        data = public(known_artists, known_venues, [])
        pending = registry({
            str(i): lead(str(i), "2027-04-10",
                         f"Emerging Artist {i}",
                         f"Emerging Venue {i}", "Lyon", dept="69")
            for i in range(20)
        })
        all_artist, all_venue = set(), set()
        for tick in range(18):
            when = TODAY + dt.timedelta(days=tick // 3)
            got = frontier.build(data, pending, when, slot=tick % 3,
                                 artist_limit=12, venue_limit=12)
            self.assertEqual(len(got["artistResearch"]), 12)
            self.assertEqual(len(got["venueResearch"]), 12)
            all_artist.update(a["key"] for a in got["artistResearch"])
            all_venue.update(v["key"] for v in got["venueResearch"])
        self.assertEqual(len(all_artist), 74)
        self.assertEqual(len(all_venue), 74)

    def test_determinism_and_invalid_schema_fail_closed(self):
        data = public()
        r = registry({"a": lead("a", "2027-01-01", "A New Band",
                               "Somewhere", "Marseille")})
        first = frontier.build(data, r, TODAY)
        self.assertEqual(first, frontier.build(copy.deepcopy(data),
                                               copy.deepcopy(r), TODAY))
        with self.assertRaises(ValueError):
            frontier.build(data, {}, TODAY)
        with self.assertRaises(ValueError):
            frontier.build(data, r, TODAY, slot=8)
        with self.assertRaises(ValueError):
            frontier.build(data, r, TODAY, artist_limit=0)


if __name__ == "__main__":
    unittest.main()
