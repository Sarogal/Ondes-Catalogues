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


    def test_real_publisher_preserves_reference_and_replays_signed_geo(self):
        import json
        from pathlib import Path
        from scripts import concerts_cloud_sync as sync
        root = Path(__file__).resolve().parents[1]
        reference = json.loads((root / "docs/grossesondes/concerts-reference.json").read_text(encoding="utf-8"))
        original = next(v for v in reference["venues"] if v["id"] == "le-grillen-colmar")
        event = next(e for e in reference["events"] if e["venueId"] == original["id"])
        # Synthetic first-party event in a copy of the real-size baseline.
        # No reference fixture or public catalogue is changed on disk.
        event.update(sourceType="salle", status="confirmed", officialUrl=URL,
                     date="2027-02-12")
        _, proof, _ = fixture()
        proof.update(venueId=original["id"], eventId=event["id"],
                     originalVenue=copy.deepcopy(original))
        row = contract.signed_proposal(proof, TODAY)
        ledger = {"schema": sync.SCHEMA, "approvals": [], contract.KEY: [row]}
        current = copy.deepcopy(reference)
        with mock.patch.object(evidence, "verify", return_value=proof):
            changed, stats = sync.merge(reference, current, ledger, TODAY)
        self.assertEqual(stats["correctedVenues"], 1)
        self.assertEqual(stats["newEvents"], 0)
        self.assertEqual(changed["events"], current["events"])
        self.assertEqual(changed["artists"], current["artists"])
        self.assertEqual(next(v for v in changed["venues"] if v["id"] == original["id"]),
                         dict(original, **row["venuePatch"]))
        self.assertEqual(reference, current)
        with self.assertRaises(ValueError):
            sync.merge(reference, changed, {"schema": sync.SCHEMA, "approvals": []}, TODAY)
        with mock.patch.object(evidence, "verify", side_effect=AssertionError("network")):
            repeated, stats2 = sync.merge(reference, changed, ledger, dt.date(2027, 5, 1))
            sync.protect_reference(reference, repeated, approvals=ledger, today=dt.date(2027, 5, 1))
        self.assertEqual(stats2["correctedVenues"], 0)
        self.assertEqual(changed, repeated)
