import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from structured_evidence import inspect_official_html


SOURCE = "https://festival.example.org/programmation"


def edition(year=2027, **overrides):
    doc = {
        "slug": f"winter-rising-fest-{year}",
        "name": f"Winter Rising Fest {year}",
        "startDate": f"{year}-08-12",
        "endDate": f"{year}-08-13",
        "lineup": ["Alpha"],
        "venue": "Le Forum",
        "price": None,
        "status": "Annoncé",
    }
    doc.update(overrides)
    return doc


def html(event, graph=False):
    value = {"@context": "https://schema.org", "@graph": [event]} if graph else event
    return '<script type="application/ld+json">' + json.dumps(value, ensure_ascii=False) + "</script>"


def event(name="Winter Rising Fest 2027", **overrides):
    v = {"@type": "MusicEvent", "name": name, "startDate": "2027-08-12",
         "endDate": "2027-08-13"}
    v.update(overrides)
    return v


class StructuredEvidenceTests(unittest.TestCase):
    def test_new_edition_must_be_named_and_is_only_review(self):
        observed = inspect_official_html(html(event()), edition(2026), SOURCE, "2026-11-04")
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0]["hints"]["new_edition_year"], 2027)
        self.assertIs(observed[0]["publication_authorized"], False)

    def test_no_new_edition_from_generic_recurrence(self):
        observed = inspect_official_html(html(event(name="Winter Rising Fest")), edition(2026), SOURCE, "2026-11-04")
        self.assertEqual(observed, [])

    def test_exact_current_event_changes_suggest_only_dates_and_new_artists(self):
        proof = event(startDate="2027-08-11", performer=[{"@type": "MusicGroup", "name": "Alpha"}, {"@type": "MusicGroup", "name": "Beta"}])
        observed = inspect_official_html(html(proof), edition(), SOURCE, "2026-11-04")
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0]["hints"]["startDate"], "2027-08-11")
        self.assertEqual(observed[0]["hints"]["new_performers"], ["Beta"])
        self.assertEqual(observed[0]["startDate_source"], "2027-08-11")
        self.assertIs(observed[0]["publication_authorized"], False)

    def test_motocultor_peelingflesh_not_new_artist(self):
        row = edition(name="Motocultor Festival", slug="motocultor-festival",
                      lineup=["Peeling Flesh", "The Hu"],
                      startDate="2027-08-19", endDate="2027-08-22")
        page = html(event(name="Motocultor Festival 2027",
                          startDate="2027-08-19", endDate="2027-08-22",
                          performer=[{"name": "Peelingflesh"}]))
        self.assertEqual(inspect_official_html(page, row, SOURCE, "2026-11-04"), [])

    def test_non_fuzzy_distinct_artist_still_proposed(self):
        row = edition(lineup=["Dark Funeral", "Peeling Flesh"])
        page = html(event(performer=["Dark Funeral UK", "Peelingflesh", "New Act"]))
        observed = inspect_official_html(page, row, SOURCE, "2026-11-04")
        self.assertEqual(observed[0]["hints"]["new_performers"],
                         ["Dark Funeral UK", "New Act"])

    def test_spacing_and_punctuation_aliases_deduplicated(self):
        row = edition(lineup=["AC/DC", "Mötley Crüe"])
        page = html(event(performer=["ACDC", "Motley Crue"]))
        self.assertEqual(inspect_official_html(page, row, SOURCE, "2026-11-04"), [])

    def test_prices_require_eur_and_provide_no_ticket_inference(self):
        proof = event(offers=[{"@type": "Offer", "price": 29.50, "priceCurrency": "EUR"},
                              {"price": 34, "priceCurrency": "USD"}, {"price": "NaN", "priceCurrency": "EUR"}])
        observed = inspect_official_html(html(proof), edition(), SOURCE, "2026-11-04")
        self.assertEqual(observed[0]["hints"]["offer_prices_eur"], ["29.50"])
        self.assertNotIn("price", observed[0]["hints"])

    def test_cancelled_always_needs_secondary_confirmation(self):
        proof = event(eventStatus="https://schema.org/EventCancelled")
        observed = inspect_official_html(html(proof), edition(), SOURCE, "2026-11-04")
        self.assertEqual(observed[0]["hints"]["sensitive_event_status"], "EventCancelled")
        self.assertTrue(observed[0]["hints"]["requires_secondary_confirmation"])
        self.assertIs(observed[0]["publication_authorized"], False)

    def test_discontinuous_range_not_turned_into_daily_sessions(self):
        proof = event(endDate="2027-08-25", location={"@type": "Place", "name": "La Fabrique"})
        observed = inspect_official_html(html(proof), edition(), SOURCE, "2026-11-04")
        self.assertTrue(observed[0]["range_needs_sessions"])
        self.assertEqual(observed[0]["hints"]["endDate"], "2027-08-25")
        self.assertNotIn("sessionDates", observed[0]["hints"])

    def test_other_event_and_wrong_year_rejected(self):
        a = event(name="Not the same festival 2027")
        b = event(startDate="2025-08-12")
        self.assertEqual(inspect_official_html(html({"@graph":[a, b]}), edition(), SOURCE, "2026-11-04"), [])

    def test_graph_and_timestamps_are_supported(self):
        proof = event(startDate="2027-08-11T19:30:00+02:00", performer=["Gamma"])
        observed = inspect_official_html(html(proof, graph=True), edition(), SOURCE, "2026-11-04")
        self.assertEqual(observed[0]["hints"]["startDate"], "2027-08-11")
        self.assertEqual(observed[0]["hints"]["new_performers"], ["Gamma"])

    def test_no_proof_from_unstructured_text_or_bad_json(self):
        html_text = '<p>Winter Rising Fest 2027, annulé !</p><script type="application/ld+json">bad data</script>'
        self.assertEqual(inspect_official_html(html_text, edition(), SOURCE, "2026-11-04"), [])

    def test_festival_identity_must_be_specific(self):
        row = edition(name="Fest 2027")
        self.assertEqual(inspect_official_html(html(event(name="Fest 2027")), row, SOURCE, "2026-11-04"), [])

    def test_duplicate_graph_events_not_duplicated(self):
        source = html({"@graph": [event(performer=["Beta"]), event(performer=["Beta"])]})
        self.assertEqual(len(inspect_official_html(source, edition(), SOURCE, "2026-11-04")), 1)

    def test_invalid_dates_rejected(self):
        proof = event(startDate="2027-02-31")
        self.assertEqual(inspect_official_html(html(proof), edition(), SOURCE, "2026-11-04"), [])
        proof = event(endDate="2027-07-01")
        self.assertEqual(inspect_official_html(html(proof), edition(), SOURCE, "2026-11-04"), [])


if __name__ == "__main__":
    unittest.main()
