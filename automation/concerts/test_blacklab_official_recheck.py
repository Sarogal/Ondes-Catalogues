"""The Black Lab verifier must reject speculative or changed concerts."""
from __future__ import annotations

import copy
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blacklab_adapter as adapter
import blacklab_official_recheck as check
import official_recheck as orchestrator
from test_blacklab_adapter import SOURCE, DETAIL, dahlia, BLACK_DAHLIA


def catalog():
    return {
        "schemaVersion": 1, "mode": "preview-public-unlisted",
        "artists": [{"id": "the-black-dahlia-murder",
                     "name": "The Black Dahlia Murder"}],
        "venues": [{"id": "the-black-lab-wasquehal",
                    "name": "The Black Lab", "city": "Wasquehal",
                    "department": "59", "latitude": 50.6526,
                    "longitude": 3.1220}],
        "events": [],
    }


def lead(page=None, url=BLACK_DAHLIA):
    page = page if page is not None else dahlia()
    row = adapter.detail_candidate(
        page, url, SOURCE, "2026-11-09"
    )
    return {**row, "reviewBucket": "genre_tag_review",
            "possibleExistingConcert": False}


class BlackLabOfficialRecheckTests(unittest.TestCase):
    TODAY = dt.date(2026, 11, 9)

    def test_known_single_artist_with_live_official_detail_approves(self):
        candidate = lead()
        inputs = copy.deepcopy((candidate, catalog()))
        decision = check.verify(candidate, dahlia(), catalog(), self.TODAY)
        self.assertEqual(decision["reviewedBy"], "automated-official-recheck")
        self.assertEqual(decision["event"]["artistIds"], ["the-black-dahlia-murder"])
        self.assertEqual(decision["event"]["venueId"], "the-black-lab-wasquehal")
        self.assertEqual(decision["event"]["date"], "2027-02-03")
        self.assertEqual(decision["event"]["time"], None)
        self.assertEqual(decision["newArtists"], [])
        self.assertEqual(candidate, inputs[0])

    def test_existing_recheck_dispatch_with_day_stability(self):
        candidate = lead()
        reg = {"schema": "grossesondes.concert.intake.v1",
               "items": {"blacklab": {"status": "pending_review",
                                      "candidate": candidate,
                                      "stableObservations": 2}}}
        originals = {"schema": "grossesondes.concert.approvals.v1",
                     "approvals": []}
        output, report = orchestrator.process(
            reg, catalog(), originals, self.TODAY,
            fetch=lambda url, cache: dahlia())
        self.assertEqual(report["evaluated"], 1)
        self.assertEqual(len(report["newApprovals"]), 1)
        self.assertEqual(len(output["approvals"]), 1)
        self.assertEqual(originals["approvals"], [])
        # One same-day sighting cannot be mistaken for two days.
        reg["items"]["blacklab"]["stableObservations"] = 1
        reg["items"]["blacklab"]["observations"] = 99
        denied, held = orchestrator.process(
            reg, catalog(), originals, self.TODAY,
            fetch=lambda url, cache: self.fail("No fetch expected"))
        self.assertEqual(held["evaluated"], 0)
        self.assertEqual(denied, originals)

    def test_multiartist_titles_need_nominative_lineup_verifier(self):
        page = DETAIL.format(
            title="THE BLACK DAHLIA MURDER + GUEST BAND",
            date="mercredi 3 février 2027",
            organizer="The Black Lab",
            description="death metal live")
        candidate = lead(page, BLACK_DAHLIA)
        with self.assertRaisesRegex(ValueError, "multi-artistes"):
            check.verify(candidate, page, catalog(), self.TODAY)

    def test_artist_unknown_not_created_from_title(self):
        page = DETAIL.format(
            title="NEW FANTASY BAND", date="mercredi 3 février 2027",
            organizer="The Black Lab", description="death metal live")
        with self.assertRaisesRegex(ValueError, "canonique"):
            check.verify(lead(page), page, catalog(), self.TODAY)

    def test_reported_event_in_slug_refused_even_if_genre(self):
        candidate = lead()
        candidate["sourceUrl"] = "https://theblacklab.fr/agenda/reporte-morgan/"
        with self.assertRaises(ValueError):
            check.verify(candidate, dahlia(), catalog(), self.TODAY)

    def test_cancelled_or_postponed_in_extended_event_body_rejected(self):
        page = DETAIL.format(
            title="THE BLACK DAHLIA MURDER",
            date="mercredi 3 février 2027",
            organizer="The Black Lab",
            description="death metal concert. La date est annulée.")
        with self.assertRaises(ValueError):
            check.verify(lead(dahlia()), page, catalog(), self.TODAY)

    def test_official_date_change_refused(self):
        changed = dahlia(date="vendredi 5 février 2027 @ 20h00")
        with self.assertRaisesRegex(ValueError, "modifiée"):
            check.verify(lead(), changed, catalog(), self.TODAY)

    def test_official_genre_change_refused(self):
        page = dahlia(description="THE BLACK DAHLIA MURDER grindcore (USA)")
        with self.assertRaisesRegex(ValueError, "modifiée"):
            check.verify(lead(), page, catalog(), self.TODAY)

    def test_wrong_official_host_or_missing_agenda(self):
        candidate = lead()
        candidate["sourceUrl"] = candidate["sourceUrl"].replace(
            "theblacklab.fr", "other.example")
        with self.assertRaises(ValueError):
            check.verify(candidate, dahlia(), catalog(), self.TODAY)
        bad = lead()
        bad["sourcePage"] = "https://other.example"
        with self.assertRaises(ValueError):
            check.verify(bad, dahlia(), catalog(), self.TODAY)

    def test_unknown_or_ungeolocated_venue_refused(self):
        candidate = lead()
        cl = catalog()
        cl["venues"][0]["latitude"] = None
        with self.assertRaisesRegex(ValueError, "Géolocalisation"):
            check.verify(candidate, dahlia(), cl, self.TODAY)

    def test_published_event_with_same_url_or_day_and_artist_refused(self):
        cl = catalog()
        cl["events"] = [{"id": "already", "date": "2027-02-03",
                         "venueId": "the-black-lab-wasquehal",
                         "artistIds": ["the-black-dahlia-murder"]}]
        with self.assertRaisesRegex(ValueError, "déjà"):
            check.verify(lead(), dahlia(), cl, self.TODAY)
        cl["events"] = [{"id": "already", "officialUrl": BLACK_DAHLIA,
                         "date": "2027-01-01", "venueId": "elsewhere",
                         "artistIds": []}]
        with self.assertRaisesRegex(ValueError, "déjà"):
            check.verify(lead(), dahlia(), cl, self.TODAY)

    def test_tampered_quarantine_and_genre_review_not_approved(self):
        for field, value in [
            ("publicationAllowed", True), ("reviewRequired", False),
            ("reviewBucket", "genre_unknown"),
            ("possibleExistingConcert", True),
            ("officialDetailFound", False),
        ]:
            with self.subTest(field=field):
                candidate = lead()
                candidate[field] = value
                with self.assertRaises(ValueError):
                    check.verify(candidate, dahlia(), catalog(), self.TODAY)

    def test_alias_collision_never_invents_artist(self):
        cl = catalog()
        cl["artists"].append({"id": "same-band", "name": "The Black Dahlia Murder"})
        with self.assertRaises(ValueError):
            check.verify(lead(), dahlia(), cl, self.TODAY)


if __name__ == "__main__":
    unittest.main()
