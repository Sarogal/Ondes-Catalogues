"""Security/regression cases: schema.org details remain search clues, never proof."""
import json
import unittest

from national_structured_clues import detail_event_clues, valid_clues
from national_detail_qualification import _inspect_detail, _valid_observation
from source_qualification import visible_text

SOURCE = {
    "dossier_id": "national-example", "url": "https://agenda.montpellier.fr/metal-2027",
    "index_url": "https://agenda.montpellier.fr/",
    "title": "Festival Metal des Garrigues 2027", "year": 2027,
}
TODAY = "2026-11-06"
NAME = "Festival Metal des Garrigues 2027"


def document(event, body=None):
    return (
        "<html><main><h1>" + (body if body is not None else NAME) + "</h1></main>"
        '<script type="application/ld+json">' + json.dumps(event) + "</script></html>"
    )


def event(**kwargs):
    row = {
        "@context": "https://schema.org",
        "@type": "MusicEvent",
        "name": NAME,
        "startDate": "2027-06-04",
        "endDate": "2027-06-05",
        "location": {"@type": "Place", "name": "Salle du Cratere",
                     "address": {"@type": "PostalAddress",
                                 "addressLocality": "Montpellier"}},
        "organizer": {"@type": "Organization", "name": "Association Garrigues Metal",
                      "url": "https://organisateur.example/"},
    }
    row.update(kwargs)
    return row


class NationalStructuredCluesTests(unittest.TestCase):
    def clues(self, e, body=NAME):
        html = document(e, body)
        return detail_event_clues(html, SOURCE, visible_text(html))

    def test_matching_event_yields_unverified_hints_only(self):
        items = self.clues(event(), NAME + " Les 4 et 5 juin 2027.")
        self.assertEqual(len(items), 1)
        clue = items[0]
        self.assertEqual(clue["start_date_hint"], "2027-06-04")
        self.assertEqual(clue["end_date_hint"], "2027-06-05")
        self.assertEqual(clue["venue_name_hint"], "Salle du Cratere")
        self.assertEqual(clue["city_name_hint"], "Montpellier")
        self.assertEqual(clue["organizer_name_hint"], "Association Garrigues Metal")
        self.assertTrue(clue["start_date_visible_near_name"])
        for field in ("event_dates_verified", "event_location_verified",
                      "organizer_identity_verified", "publisher_independence_verified",
                      "publication_authorized"):
            self.assertIs(clue[field], False)
        self.assertTrue(clue["review_only"])
        # Organizer URLs are never emitted as unapproved fetch targets.
        self.assertNotIn("organisateur.example", json.dumps(clue))
        self.assertTrue(valid_clues(items, SOURCE, True))

    def test_json_only_date_not_visible_on_public_page(self):
        items = self.clues(event())
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0]["start_date_visible_near_name"])
        self.assertFalse(items[0]["end_date_visible_near_name"])

    def test_wrong_edition_year_rejected_even_when_date_next_year(self):
        self.assertEqual(self.clues(event(name="Festival Metal des Garrigues 2026")), [])
        self.assertEqual(self.clues(event(startDate="2028-06-04")), [])

    def test_other_event_or_loose_name_rejected(self):
        self.assertEqual(self.clues(event(name="Festival Metal des Garages 2027")), [])
        self.assertEqual(self.clues(event(name="Festival Metal des Garrigues Junior 2027")), [])

    def test_bad_date_range_rejected(self):
        self.assertEqual(self.clues(event(startDate="2027-06-07", endDate="2027-06-01")), [])
        self.assertEqual(self.clues(event(startDate="2027-06-01", endDate="2027-07-09")), [])
        self.assertEqual(self.clues(event(startDate="2027-06-42")), [])

    def test_non_event_json_ld_ignored(self):
        self.assertEqual(self.clues({"@type": "Organization", "name": NAME,
                                     "startDate": "2027-06-04"}), [])

    def test_multiple_independent_schemas_cap_and_deduplicate(self):
        events = [event(startDate=f"2027-06-0{day}", endDate=f"2027-06-0{day}")
                  for day in (4, 4, 5, 6)]
        html = document({"@graph": events}, NAME)
        hints = detail_event_clues(html, SOURCE, visible_text(html))
        self.assertEqual(len(hints), 2)
        self.assertEqual(hints[0]["start_date_hint"], "2027-06-04")
        self.assertEqual(hints[1]["start_date_hint"], "2027-06-05")

    def test_persisted_approval_attempt_rejected(self):
        item = self.clues(event())[0]
        for field in ("event_dates_verified", "organizer_identity_verified",
                      "publisher_independence_verified", "publication_authorized"):
            corrupted = dict(item, **{field: True})
            self.assertFalse(valid_clues([corrupted], SOURCE, True), field)

    def test_suspicious_organizer_or_city_not_persisted(self):
        items = self.clues(event(
            organizer={"name": "<b>Unsafe</b>"},
            location={"name": "Venue", "address": {"addressLocality": "{x}"}}))
        self.assertEqual(len(items), 1)
        self.assertIsNone(items[0]["organizer_name_hint"])
        self.assertIsNone(items[0]["city_name_hint"])

    def test_visible_date_must_be_close_to_event_name(self):
        distant = NAME + " Concerts internationaux " + " et autres annonces " * 60 + "4 juin 2027"
        item = self.clues(event(), distant)[0]
        self.assertFalse(item["start_date_visible_near_name"])

    def test_inspection_and_validation_keep_structured_hints_review_only(self):
        html = document(event(), NAME + " 4 juin 2027 à Montpellier et 5 juin 2027")
        observation = _inspect_detail(html, SOURCE, TODAY)
        self.assertEqual(len(observation["structured_event_clues_private"]), 1)
        self.assertTrue(_valid_observation(SOURCE, observation, TODAY))
        item = observation["structured_event_clues_private"][0]
        item["event_dates_verified"] = True
        self.assertFalse(_valid_observation(SOURCE, observation, TODAY))

    def test_script_only_date_remains_unconfirmed_in_observation(self):
        html = document(event())
        observation = _inspect_detail(html, SOURCE, TODAY)
        self.assertFalse(observation["date_claim_verified"])
        self.assertFalse(observation["structured_event_clues_private"][0]["start_date_visible_near_name"])

    def test_forged_non_future_date_is_rejected_in_persisted_clues(self):
        item = self.clues(event())[0]
        item["start_date_hint"] = "2028-06-04"
        self.assertFalse(valid_clues([item], SOURCE, True))


if __name__ == "__main__":
    unittest.main()
