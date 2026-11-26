"""Published touring Festival stops must be nominated to private Concerts only."""
from copy import deepcopy
from datetime import date
import unittest

import published_festival_tour_research as bridge
import intake_archive
import source_admission_intake as source_intake
import triage

TODAY = date(2026, 11, 21)
LINEUP = ["Obscura", "Pestilence", "Cryptic Shift", "Thus", "DVRK"]


def festival(city, day, slug, **changes):
    row = {
        "slug": slug,
        "name": "Touring Metal Event 2027 — " + city,
        "city": city, "department": "34",
        "startDate": day, "endDate": day,
        "venue": "Salle du Rock, " + city,
        "officialSite": "https://festival-tour.example.fr/",
        "notes": ("Étape française du festival itinérant européen : "
                  "Obscura, Pestilence, Cryptic Shift, Thus, DVRK."),
        "lineup": list(LINEUP),
    }
    return {**row, **changes}


def signed(rows):
    return {"schema": 1, "festivals": rows}


def fixture():
    return signed([
        festival("Montpellier", "2027-02-04", "tour-montpellier"),
        festival("Toulouse", "2027-02-11", "tour-toulouse"),
        festival("Limoges", "2027-02-12", "tour-limoges"),
    ])


class PublishedToursTests(unittest.TestCase):
    def test_three_city_tour_nominated_without_authority(self):
        rows = fixture()
        source_snapshot = deepcopy(rows)
        report = bridge.find_research(rows, TODAY)
        self.assertEqual(rows, source_snapshot)
        self.assertEqual(len(report["candidates"]), 3)
        self.assertEqual(report["triageCounts"]["tour_source_research"], 3)
        self.assertFalse(report["automaticPublication"])
        self.assertEqual(
            [x["date"] for x in report["candidates"]],
            ["2027-02-04", "2027-02-11", "2027-02-12"])
        for candidate in report["candidates"]:
            self.assertIs(candidate["publicationAllowed"], False)
            self.assertIs(candidate["reviewRequired"], True)
            self.assertIs(candidate["officialDetailFound"], False)
            self.assertIs(candidate["festivalCatalogueHintsOnly"], True)
            self.assertIs(candidate["requiresArtistAndVenueReproof"], True)
            self.assertIs(candidate["genreToConfirm"], True)
            self.assertEqual(candidate["classification"], [])
            self.assertEqual(len(candidate["artistNamesFromFestivalOnly"]), 5)
            self.assertEqual(candidate["reviewBucket"], "tour_source_research")
            self.assertTrue(candidate["candidateId"].startswith(
                "concert-from-festival-"))
        registry, stats = intake_archive.merge(
            None, report, "2026-11-21T04:22:00+00:00")
        self.assertEqual(registry["total"], 3)
        self.assertEqual(stats["added"], 3)
        self.assertTrue(all(r["status"] == "pending_review"
                            and r["stableObservations"] == 1
                            for r in registry["items"].values()))
        same, stats2 = intake_archive.merge(
            registry, report, "2026-11-21T05:22:00+00:00")
        self.assertEqual(stats2["stableReobservedOnNewDay"], 0)
        self.assertTrue(all(r["stableObservations"] == 1
                            for r in same["items"].values()))
        new_day, stats3 = intake_archive.merge(
            same, report, "2026-11-22T04:22:00+00:00")
        self.assertEqual(stats3["stableReobservedOnNewDay"], 3)
        self.assertTrue(all(r["stableObservations"] == 2
                            for r in new_day["items"].values()))

    def test_large_tour_lineup_retained_in_full_without_publication(self):
        rows = fixture()
        names = [f"Artist {i:03}" for i in range(1, 101)]
        for row in rows["festivals"]:
            row["lineup"] = list(names)
        report = bridge.find_research(rows, TODAY)
        self.assertEqual(len(report["candidates"]), 3)
        for candidate in report["candidates"]:
            self.assertEqual(candidate["artistNamesFromFestivalOnly"], names)
            self.assertFalse(candidate["publicationAllowed"])
        registry, _ = intake_archive.merge(
            None, report, "2026-11-21T04:22:00+00:00")
        for record in registry["items"].values():
            self.assertEqual(record["candidate"]["artistNamesFromFestivalOnly"], names)
        self.assertFalse(bridge.valid_artist_names(
            [f"Artist {i:04} " + "x" * 110 for i in range(600)]))
        self.assertFalse(bridge.valid_artist_names(["Artist 1", "ARTIST 1"]))
        self.assertFalse(bridge.valid_artist_names(["Artist 1", None]))

    def test_tour_organizer_is_queued_as_unknown_source_not_approved(self):
        report = bridge.find_research(fixture(), TODAY)
        registry, _ = intake_archive.merge(
            None, report, "2026-11-21T10:00:00+00:00")
        registered, _ = intake_archive.merge(
            registry, report, "2026-11-22T10:00:00+00:00")
        out = source_intake.build(
            registered,
            {"schemaVersion": 1, "events": [], "artists": [], "venues": []},
            date(2026, 11, 22),
            organizer_sources=[], reviewed_venues={})
        self.assertEqual(out["candidateSourceHosts"], 1)
        self.assertEqual(out["previouslyUnreviewedHosts"], 1)
        entry = out["reviewQueue"][0]
        self.assertEqual(entry["host"], "festival-tour.example.fr")
        self.assertEqual(entry["eventLeads"], 3)
        self.assertEqual(entry["stableOnDistinctDays"], 3)
        self.assertEqual(entry["individualDetailClaimed"], 0)
        self.assertFalse(entry["automaticTrustGranted"])
        self.assertFalse(entry["networkChecked"])
        self.assertFalse(entry["independentCorroborationVerified"])
        self.assertFalse(out["publicationAllowed"])

    def test_reviewed_retraction_transfers_once_without_republishing(self):
        previous = festival("Montpellier", "2027-02-04", "wrong-festival",
                            lineup=[], venue=None)
        previous["city"] = None
        detail = "https://festival-tour.example.fr/event/tour/"
        correction = {
            "schema": 1, "action": "retract_false_edition_only",
            "retainHistoricalFestival": True, "continueEditionWatch": True,
            "previousRow": previous, "evidence": [detail],
            "concertLead": {
                "title": "Tour", "date": "2027-02-04",
                "venue": "Salle du Rock", "city": "Montpellier",
                "department": "34", "artists": list(LINEUP),
                "officialUrl": detail, "publicationAuthorized": False,
            },
        }
        report = bridge.find_research(signed([]), TODAY,
                                      corrections=[correction, correction])
        self.assertEqual(len(report["candidates"]), 1)
        candidate = report["candidates"][0]
        self.assertEqual(candidate["sourceUrl"], detail)
        self.assertEqual(candidate["artistNamesFromFestivalOnly"], LINEUP)
        self.assertEqual(candidate["reviewBucket"], "tour_source_research")
        self.assertFalse(candidate["publicationAllowed"])
        self.assertFalse(candidate["officialDetailFound"])
        self.assertTrue(candidate["requiresArtistAndVenueReproof"])
        registry, stats = intake_archive.merge(
            None, report, "2026-11-21T04:22:00+00:00")
        self.assertEqual(stats["added"], 1)
        self.assertEqual(registry["total"], 1)
        for key, value in (("publicationAuthorized", True),
                           ("date", "2027-02-05"),
                           ("officialUrl", "https://other.example.fr/event/"),
                           ("artists", ["Only one"])):
            invalid = deepcopy(correction)
            invalid["concertLead"][key] = value
            self.assertEqual(bridge.find_research(
                signed([]), TODAY, corrections=[invalid])["candidates"], [])

    def test_only_one_city_is_not_inferred_touring_concert(self):
        report = bridge.find_research(signed([fixture()["festivals"][0]]),
                                      TODAY)
        self.assertEqual(report["candidates"], [])

    def test_a_genuine_multi_day_festival_is_not_reclassified(self):
        festival_rows = fixture()["festivals"]
        festival_rows[1]["endDate"] = "2027-02-12"
        festival_rows[2]["endDate"] = "2027-02-13"
        report = bridge.find_research(signed(festival_rows), TODAY)
        self.assertEqual(report["candidates"], [])

    def test_tour_proof_must_be_explicit_in_festival_rows(self):
        fixture_rows = fixture()["festivals"]
        fixture_rows[0]["notes"] = "Festival de metal local, programmations à venir."
        fixture_rows[1]["notes"] = "Festival de metal local, programmations à venir."
        self.assertEqual(
            bridge.find_research(signed(fixture_rows), TODAY)["candidates"], [])

    def test_conflicting_band_bill_does_not_cross_qualify(self):
        fixture_rows = fixture()["festivals"]
        fixture_rows[1]["lineup"] = ["Autre Groupe", "Pestilence"]
        fixture_rows[2]["lineup"] = ["Un autre groupe", "DVRK"]
        self.assertEqual(
            bridge.find_research(signed(fixture_rows), TODAY)["candidates"], [])

    def test_variable_tour_bills_preserve_each_local_lineup(self):
        rows = fixture()["festivals"]
        rows[0]["lineup"] = ["Obscura", "Pestilence", "Local Montpellier"]
        rows[1]["lineup"] = ["Pestilence", "Obscura", "Local Toulouse"]
        rows[2]["lineup"] = ["Obscura", "Pestilence", "Local Limoges"]
        out = bridge.find_research(signed(rows), TODAY)
        self.assertEqual(len(out["candidates"]), 3)
        by_city = {c["city"]: c for c in out["candidates"]}
        for row in rows:
            c = by_city[row["city"]]
            self.assertEqual(c["artistNamesFromFestivalOnly"], row["lineup"])
            self.assertFalse(c["publicationAllowed"])
            self.assertTrue(c["requiresArtistAndVenueReproof"])

    def test_variable_bills_require_direct_same_title_origin_and_distinct_stage(self):
        rows = fixture()["festivals"][:2]
        rows[0]["lineup"] = ["Obscura", "Pestilence", "Local A"]
        rows[1]["lineup"] = ["Obscura", "Pestilence", "Local B"]
        for change in (
                {"name": "Another Tour 2027 — Toulouse"},
                {"officialSite": "https://another-tour.example.fr/"},
                {"city": "Montpellier"},
                {"startDate": rows[0]["startDate"], "endDate": rows[0]["endDate"]},
                {"lineup": ["Obscura", "Another Act", "Local B"]}):
            altered = [rows[0], {**rows[1], **change}]
            self.assertEqual(bridge.find_research(signed(altered), TODAY)["candidates"], [])

    def test_expired_or_unsafe_urls_cannot_nominate_a_concert(self):
        rows = fixture()["festivals"]
        rows[0]["startDate"] = rows[0]["endDate"] = "2026-11-01"
        rows[1]["officialSite"] = "https://127.0.0.1/admin"
        rows[2]["officialSite"] = "http://festival-tour.example.fr/"
        self.assertEqual(
            bridge.find_research(signed(rows), TODAY)["candidates"], [])

    def test_two_distinct_cities_and_dates_required(self):
        rows = fixture()["festivals"]
        rows[1]["city"] = "Montpellier"
        rows[2]["city"] = "Montpellier"
        self.assertEqual(
            bridge.find_research(signed(rows), TODAY)["candidates"], [])
        rows = fixture()["festivals"]
        rows[1]["startDate"] = rows[1]["endDate"] = "2027-02-04"
        rows[2]["startDate"] = rows[2]["endDate"] = "2027-02-04"
        self.assertEqual(
            bridge.find_research(signed(rows), TODAY)["candidates"], [])

    def test_untrusted_global_source_fails_closed(self):
        for data in (
            {"schema": "unknown", "festivals": []},
            {"schema": 1, "festivals": None},
        ):
            with self.assertRaises(ValueError):
                bridge.find_research(data, TODAY)

    def test_large_catalogue_archives_every_eligible_tour_cohort(self):
        rows = []
        for i in range(205):
            site = f"https://tour-{i}.example.fr/"
            rows.extend([
                festival("Montpellier", "2027-02-04", f"tour-{i}-montpellier",
                         officialSite=site),
                festival("Toulouse", "2027-02-11", f"tour-{i}-toulouse",
                         officialSite=site),
            ])
        rows.extend([{}] * 250)
        report = bridge.find_research(signed(rows), TODAY,
                                      corrections=[{}] * 601)
        self.assertEqual(len(report["candidates"]), 410)
        self.assertEqual(report["triageCounts"]["tour_source_research"], 410)
        self.assertFalse(report["publicationAllowed"])
        self.assertEqual(len({c["candidateId"] for c in report["candidates"]}), 410)
        registry, stats = intake_archive.merge(
            None, report, "2026-11-21T04:22:00+00:00")
        self.assertEqual(stats["added"], 410)
        self.assertEqual(registry["total"], 410)

    def test_unflagged_fest_sounding_events_follow_normal_overlap_review(self):
        candidate = {
            "name": "Touring Fest 2027", "date": "2027-02-04",
            "source": bridge.SOURCE,
            "publicationAllowed": False, "reviewRequired": True,
        }
        self.assertEqual(
            triage.triage(candidate)["reviewBucket"],
            "festival_overlap_review")


if __name__ == "__main__":
    unittest.main()
