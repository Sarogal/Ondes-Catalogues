"""The Stranglers 2026: four pre-existing venues, independent exact signatures.

Offline tests: no website is fetched and no catalogue is rewritten.
"""
import copy
import datetime as dt
import unittest
from scripts import concerts_cloud_sync as sync

TODAY = dt.date(2026, 11, 6)
IDS = {
    "go-c-20261121-penmarch-the-stranglers",
    "go-c-20261128-aix-the-stranglers",
    "go-c-20261130-villeurbanne-the-stranglers",
    "go-c-20261203-vaureal-the-stranglers",
}
KNOWN = {
    "the-stranglers": {"id": "the-stranglers", "name": "The Stranglers", "aliases": []},
    "brother-junior": {"id": "brother-junior", "name": "Brother Junior", "aliases": []},
}
VENUES = {
    "salle-cap-caval-penmarch": {
        "id": "salle-cap-caval-penmarch", "name": "Salle Cap Caval", "city": "Penmarc’h"},
    "6mic-aix-en-provence": {
        "id": "6mic-aix-en-provence", "name": "6MIC", "city": "Aix-en-Provence"},
    "le-transbordeur-villeurbanne": {
        "id": "le-transbordeur-villeurbanne", "name": "Le Transbordeur", "city": "Villeurbanne"},
    "le-forum-vaureal": {
        "id": "le-forum-vaureal", "name": "Le Forum", "city": "Vauréal"},
}


def approval(event_id):
    signed = sync.STRANGLERS_FOUR_SIGNED_20261106[event_id]
    proofs = [dict(x, checkedAt="2026-11-06") for x in signed["proofs"]]
    return {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": "2026-11-06",
        "officialEvidence": proofs,
        "event": copy.deepcopy(signed["event"]),
        "newArtists": [],
    }


class FourVenueSignedApproval(unittest.TestCase):
    def test_each_exactly_pinned_official_event_passes(self):
        self.assertEqual(set(sync.STRANGLERS_FOUR_SIGNED_20261106), IDS)
        for ident in IDS:
            with self.subTest(ident=ident):
                event, artists = sync.validate_approval(
                    approval(ident), VENUES, KNOWN, TODAY)
                self.assertEqual(event["id"], ident)
                self.assertEqual(artists, {})
                self.assertEqual(event["artistIds"][0], "the-stranglers")
                self.assertEqual(
                    event["time"],
                    next(p["concertStartTimeConfirmed"] for p
                         in approval(ident)["officialEvidence"]
                         if "concertStartTime" in p["checkedFields"]))

    def test_mutated_billing_start_time_date_source_or_venue_rejected(self):
        for ident in IDS:
            for change in (
                "id", "title", "date", "time", "artistIds", "venue",
                "genres", "officialUrl", "organizer", "reviewer",
                "checkedAt", "reviewedAt", "missingProof", "wrongProofUrl",
                "proofFields", "proofArtist", "timeProof", "newArtist",
                "status", "sourceType",
            ):
                row = approval(ident)
                event = row["event"]
                if change == "id":
                    event["id"] = "go-c-20261129-mystery-band"
                elif change == "title":
                    event["title"] = "The Stranglers + Mystery Band"
                elif change == "date":
                    event["date"] = "2026-11-29"
                elif change == "time":
                    event["time"] = "19:30"
                elif change == "artistIds":
                    event["artistIds"] = (["brother-junior"]
                                          if len(event["artistIds"]) == 1
                                          else ["the-stranglers"])
                elif change == "venue":
                    event["venueId"] = "le-forum-vaureal" if event["venueId"] != \
                        "le-forum-vaureal" else "6mic-aix-en-provence"
                elif change == "genres":
                    event["genres"] = ["Pop"]
                elif change == "officialUrl":
                    event["officialUrl"] = "https://other.example/show"
                elif change == "organizer":
                    event["organizer"] = "Fake promoter"
                elif change == "reviewer":
                    row["reviewedBy"] = "automated-official-recheck"
                elif change == "checkedAt":
                    row["officialEvidence"][0]["checkedAt"] = "2026-11-05"
                elif change == "reviewedAt":
                    row["reviewedAt"] = "2026-10-01"
                elif change == "missingProof":
                    row["officialEvidence"].pop()
                elif change == "wrongProofUrl":
                    row["officialEvidence"][1]["url"] = "https://fake.example/tickets"
                elif change == "proofFields":
                    row["officialEvidence"][0]["checkedFields"] = ["artists"]
                elif change == "proofArtist":
                    row["officialEvidence"][0]["officialArtistNames"] = ["Unknown"]
                elif change == "timeProof":
                    source = next(p for p in row["officialEvidence"]
                                  if "concertStartTimeConfirmed" in p)
                    source["concertStartTimeConfirmed"] = "19:30"
                elif change == "newArtist":
                    row["newArtists"] = [{"id": "fake", "name": "Fake"}]
                elif change == "status":
                    event["status"] = "cancelled"
                elif change == "sourceType":
                    event["sourceType"] = "third-party"
                with self.subTest(ident=ident, mutation=change):
                    with self.assertRaises(ValueError):
                        sync.validate_approval(row, VENUES, KNOWN, TODAY)

    def test_no_general_venue_permission_is_added(self):
        original = approval("go-c-20261203-vaureal-the-stranglers")
        original["event"]["id"] = "go-c-20261204-vaureal-other-act"
        with self.assertRaises(ValueError):
            sync.validate_approval(original, VENUES, KNOWN, TODAY)
        original = approval("go-c-20261128-aix-the-stranglers")
        original["event"]["id"] = "go-c-20261129-aix-other-act"
        with self.assertRaises(ValueError):
            sync.validate_approval(original, VENUES, KNOWN, TODAY)
        original = approval("go-c-20261121-penmarch-the-stranglers")
        original["event"]["id"] = "go-c-20261122-penmarch-other-act"
        with self.assertRaises(ValueError):
            sync.validate_approval(original, VENUES, KNOWN, TODAY)


if __name__ == "__main__":
    unittest.main()
