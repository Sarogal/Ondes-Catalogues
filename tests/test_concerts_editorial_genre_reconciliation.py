"""Editorial review never treats source failure or ambiguity as withdrawal."""
import copy
import datetime as dt
import json
import unittest

from automation.concerts import editorial_genre_reconciliation as review
import test_concerts_openagenda_description_genres as fixture


class EditorialGenreReconciliationTests(unittest.TestCase):
    def setup_case(self):
        raw = fixture.official_record(
            description="<p>Soirée chaâbi au Punk Paradise.</p>",
            keywords={"fr": ["chaâbi", "raï", "Arabic pop", "R&B"]},
            title={"fr": "Example Band"})
        record = json.loads(raw)["events"][0]
        record["location"]["name"] = "Punk Paradise"
        venue = fixture.fixture.producer._unpublished_location(record)
        venue["id"] = "test-venue"
        date = fixture.fixture.DAY
        event = {"id": "test-concert", "title": "Example Band",
                 "date": date, "venueId": venue["id"],
                 "artistIds": ["example-band"], "genres": ["punk"],
                 "status": "confirmed", "sourceType": "organisateur",
                 "officialUrl": fixture.fixture.URL}
        proof = {"proofType": "dynamic-openagenda-new-site-v1",
                 "url": event["officialUrl"], "checkedAt": date,
                 "officialOpenAgendaUid": fixture.fixture.AGENDA_UID,
                 "officialOpenAgendaEventUid": fixture.fixture.EVENT_UID,
                 "officialArtistNames": ["Example Band"],
                 "officialGenreLabels": ["punk"]}
        approval = {"reviewDecision": "approved",
                    "reviewedBy": "independent-official-verifier",
                    "reviewedAt": date, "event": copy.deepcopy(event),
                    "officialEvidence": [
                        {"proofType": "official-organizer-or-venue"}, proof]}
        return record, venue, event, approval

    def check(self, record, venue, event, approval, fetch=None):
        return review.verify(approval, event, venue,
            dt.date.fromisoformat(event["date"]),
            fetch=fetch or (lambda url: json.dumps({"total": 1, "events": [record]})))

    def test_positive_source_bound_editorial_evidence(self):
        record, venue, event, approval = self.setup_case()
        calls = []
        def fetch(url):
            calls.append(url)
            return json.dumps({"total": 1, "events": [record]})
        result = self.check(record, venue, event, approval, fetch)
        self.assertEqual(result["reason"], "venue-name-genre-contamination")
        self.assertEqual(result["explicitOutsideGenres"],
                         ["chaabi", "rai", "arabic pop", "r b"])
        self.assertEqual(result["eventId"], event["id"])
        self.assertFalse(result["publicationAllowed"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], review.oa.official_export_url(
            fixture.fixture.AGENDA_UID, fixture.fixture.EVENT_UID))

    def test_missing_or_conflicting_genre_not_enough(self):
        for keywords, description in (
                ({}, "Jazz au Punk Paradise."),
                ({"fr": ["unclassified"]}, "Jazz au Punk Paradise."),
                ({"fr": ["jazz", "punk"]}, "Jazz au Punk Paradise."),
                ({"fr": ["jazz"]}, "Concert punk au Punk Paradise."),
                ({"fr": ["jazz"]}, "Concert de jazz."),
                ({"fr": ["jazz"]}, "<span hidden>Punk Paradise</span> Jazz.")):
            with self.subTest(keywords=keywords, description=description):
                record, venue, event, approval = self.setup_case()
                record["keywords"] = keywords
                record["description"] = {"fr": description}
                with self.assertRaises(ValueError):
                    self.check(record, venue, event, approval)

    def test_identity_and_schedule_failures_do_not_authorize_retraction(self):
        for changes in ({"status": 2}, {"eventStatus": "cancelled"},
                        {"uid": 999}, {"firstDate": "2027-11-01"},
                        {"title": {"fr": "Other Band"}}):
            with self.subTest(changes=changes):
                record, venue, event, approval = self.setup_case()
                record.update(changes)
                with self.assertRaises(ValueError):
                    self.check(record, venue, event, approval)

    def test_network_failure_and_unsigned_change_never_produce_evidence(self):
        record, venue, event, approval = self.setup_case()
        def unavailable(url):
            raise OSError("source offline")
        with self.assertRaises(OSError):
            self.check(record, venue, event, approval, unavailable)
        event["artistIds"] = ["different"]
        with self.assertRaises(ValueError):
            self.check(record, venue, event, approval,
                       lambda url: self.fail("unsigned event must not be fetched"))


if __name__ == "__main__":
    unittest.main()
