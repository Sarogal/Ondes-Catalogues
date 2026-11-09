"""Publisher-side contract for an official Black Lab single-artist recheck.

These tests import the actual publisher validator, not a mock acceptance path.
All fixtures are fictitious and require no confidential candidate data.
"""
from __future__ import annotations

import copy
import datetime as dt
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "automation" / "concerts"))
import concerts_cloud_sync as publisher
import blacklab_adapter as source
import blacklab_official_recheck as verifier
from test_blacklab_adapter import DETAIL, SOURCE

NOW = dt.date(2026, 11, 9)
URL = "https://theblacklab.fr/agenda/fixture-metal-band/"
HTML = DETAIL.format(
    title="FIXTURE METAL BAND",
    date="mercredi 3 février 2027 @ 19h00 23h30",
    organizer="The Black Lab",
    description="FIXTURE METAL BAND est un groupe de death metal.",
)


def catalogue():
    return {
        "schemaVersion": 1, "mode": "preview-public-unlisted",
        "venues": [{
            "id": "the-black-lab-wasquehal",
            "name": "The Black Lab", "city": "Wasquehal",
            "department": "59", "latitude": 50.652602,
            "longitude": 3.122069,
        }],
        "artists": [{"id": "fixture-metal-band", "name": "FIXTURE METAL BAND"}],
        "events": [],
    }


def official_approval():
    cat = catalogue()
    candidate = source.detail_candidate(HTML, URL, SOURCE, NOW.isoformat())
    candidate["reviewBucket"] = "genre_tag_review"
    candidate["possibleExistingConcert"] = False
    return verifier.verify(candidate, HTML, cat, NOW)


def check_with_real_publisher(approval):
    cat = catalogue()
    venues = {v["id"]: v for v in cat["venues"]}
    artists = {a["id"]: a for a in cat["artists"]}
    return publisher.validate_approval(approval, venues, artists, NOW)


class BlackLabPublisherContractTests(unittest.TestCase):
    def test_matching_official_verifier_output_passes_real_publisher(self):
        approval = official_approval()
        approved_event, added = check_with_real_publisher(approval)
        self.assertEqual(approved_event, approval["event"])
        self.assertEqual(added, {})
        self.assertIsNone(approved_event["time"])

    def test_wrong_lineup_or_claimed_identity_rejected(self):
        for key, value in [
            ("officialArtistNames", ["Someone Else"]),
            ("sourceStructure", "generic-card"),
            ("proofType", "third-party-ticketing"),
            ("checkedAt", "2026-11-08"),
            ("checkedFields", ["artists", "date", "genre"]),
        ]:
            with self.subTest(key=key):
                proposal = copy.deepcopy(official_approval())
                proposal["officialEvidence"][0][key] = value
                with self.assertRaises(ValueError):
                    check_with_real_publisher(proposal)

    def test_narrow_artist_date_venue_and_genre_contract(self):
        for key, value in [
            ("title", "Another Artist"),
            ("id", "go-c-20270203-wasquehal-unknown"),
            ("venueId", "another-venue"),
            ("date", "2027-02-04"),
            ("genres", ["Reggae"]),
            ("time", "19:00"),
            ("organizer", "Third-party Agency"),
        ]:
            with self.subTest(key=key):
                proposal = copy.deepcopy(official_approval())
                proposal["event"][key] = value
                with self.assertRaises((ValueError, KeyError)):
                    check_with_real_publisher(proposal)

    def test_new_artist_and_multiple_artists_are_never_admitted(self):
        changed = copy.deepcopy(official_approval())
        changed["newArtists"] = [{"id": "fake-new-act", "name": "Fake New Act"}]
        changed["event"]["artistIds"].append("fake-new-act")
        with self.assertRaises(ValueError):
            check_with_real_publisher(changed)
        changed = copy.deepcopy(official_approval())
        changed["event"]["artistIds"] += ["second-band"]
        with self.assertRaises(ValueError):
            check_with_real_publisher(changed)

    def test_bad_host_paths_and_manual_locked_ids_are_denied(self):
        for url in (
            "https://example.org/agenda/fixture-metal-band/",
            "https://theblacklab.fr/agenda/",
            "https://theblacklab.fr/agenda/fixture-metal-band/?utm=1",
            "http://theblacklab.fr/agenda/fixture-metal-band/",
        ):
            proposal = copy.deepcopy(official_approval())
            proposal["event"]["officialUrl"] = url
            with self.subTest(url=url), self.assertRaises(ValueError):
                check_with_real_publisher(proposal)
        # Earlier human-signed bills cannot be replaced with an auto signature.
        proposal = copy.deepcopy(official_approval())
        proposal["event"]["id"] = next(
            i for i,v in publisher.ROCKSTORE_BLACKLAB_OFFICIAL_VERIFIED.items()
            if v["venueId"] == "the-black-lab-wasquehal"
        )
        with self.assertRaises(ValueError):
            check_with_real_publisher(proposal)


if __name__ == "__main__":
    unittest.main()
