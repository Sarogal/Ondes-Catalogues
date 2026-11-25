import copy
import datetime as dt
import unittest
from unittest import mock

from automation.concerts import existing_venue_geo_evidence as evidence
from scripts import concert_existing_venue_geo_contract as contract
from test_concerts_existing_venue_geo_evidence import VENUE, EVENT, URL, OSM

TODAY = dt.date(2026, 11, 25)


def fixture():
    venue = dict(VENUE, geoSource="Géolocalisation indicative par commune")
    event = dict(EVENT, status="confirmed")
    catalogue = {"venues": [venue], "events": [event], "artists": []}
    proposal = {"schema": evidence.SCHEMA, "venueId": venue["id"],
                "eventId": event["id"], "eventDate": event["date"],
                "officialUrl": URL, "officialVenueSourceUrl": "https://unknown-room.fr/",
                "originalVenue": copy.deepcopy(venue),
                "venuePatch": {"address": "19 rue des Jardins", "postalCode": "68000",
                               "latitude": 48.08, "longitude": 7.36,
                               "geoPrecision": "named-site-point", "geoSource": OSM},
                "publicationAllowed": False, "publisherAuthorityGranted": False}
    row = contract.signed_proposal(proposal, TODAY)
    return catalogue, proposal, row


class GenericVenueGeoContractTests(unittest.TestCase):
    def test_first_application_and_idempotent_offline_replay(self):
        original, proof, row = fixture()
        ledger = {contract.KEY: [row]}
        before = copy.deepcopy(original)
        with mock.patch.object(evidence, "verify", return_value=proof) as verify:
            normalized, plans = contract.prepare(original, ledger, TODAY)
            verify.assert_called_once()
        self.assertEqual(normalized, before)
        self.assertEqual(contract.apply(normalized, plans), 1)
        self.assertEqual(original, before)
        self.assertEqual(normalized["events"], before["events"])
        self.assertEqual(normalized["artists"], before["artists"])
        self.assertEqual(normalized["venues"][0]["id"], before["venues"][0]["id"])
        self.assertEqual(normalized["venues"][0]["address"], "19 rue des Jardins")
        self.assertEqual(contract.restore_originals(normalized, plans), before)
        with mock.patch.object(evidence, "verify", side_effect=AssertionError("network")):
            replay, p = contract.prepare(normalized, ledger, dt.date(2027, 5, 1))
            self.assertEqual(contract.apply(replay, p), 0)
            self.assertEqual(replay, normalized)

    def test_rejects_protected_fields_and_wrong_original(self):
        for field, value in (("city", "Paris"), ("name", "Another Room"),
                             ("id", "other"), ("latitude", True)):
            original, proof, row = fixture()
            row["venuePatch"][field] = value
            with self.assertRaises(ValueError):
                contract.prepare(original, {contract.KEY: [row]}, TODAY)
        original, proof, row = fixture()
        row["originalVenue"]["name"] = "Other"
        with self.assertRaises(ValueError):
            contract.prepare(original, {contract.KEY: [row]}, TODAY)

    def test_rejects_fresh_proof_conflict(self):
        original, proof, row = fixture()
        proof["venuePatch"]["latitude"] = 48.09
        with self.assertRaisesRegex(ValueError, "disagrees"):
            contract.prepare(original, {contract.KEY: [row]}, TODAY,
                             verify_one=lambda *args: proof)

    def test_rejects_missing_event_wrong_source_and_duplicate(self):
        original, proof, row = fixture()
        for change in ({"eventId": "wrong"}, {"eventDate": "2027-02-13"},
                       {"officialUrl": "https://other.fr/e/1"}):
            with self.assertRaises(ValueError):
                contract.prepare(original, {contract.KEY: [dict(row, **change)]}, TODAY)
        with self.assertRaises(ValueError):
            contract.prepare(original, {contract.KEY: [row, row]}, TODAY)

    def test_rejects_stale_unapplied_signature_and_tampered_replay(self):
        original, proof, row = fixture()
        ledger = {contract.KEY: [row]}
        with self.assertRaisesRegex(ValueError, "fresh"):
            contract.prepare(original, ledger, TODAY + dt.timedelta(days=8))
        normalized, plans = contract.prepare(original, ledger, TODAY,
                                             verify_one=lambda *args: proof)
        contract.apply(normalized, plans)
        normalized["venues"][0]["latitude"] = 49.0
        with self.assertRaises(ValueError):
            contract.prepare(normalized, ledger, TODAY)

    def test_conflicting_legacy_change_cannot_be_overwritten(self):
        original, proof, row = fixture()
        normalized, plans = contract.prepare(original, {contract.KEY: [row]}, TODAY,
                                             verify_one=lambda *args: proof)
        normalized["venues"][0]["address"] = "A different historical correction"
        with self.assertRaisesRegex(ValueError, "conflicts"):
            contract.apply(normalized, plans)
