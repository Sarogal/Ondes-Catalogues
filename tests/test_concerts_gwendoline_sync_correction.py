"""Guard one signed lineup correction through the concert synchronizer only.

The published catalogue must remain untouched on this PR. It is updated by
the cloud synchronizer after private approval becomes available.
"""
import copy
import json
import unittest
from pathlib import Path

from scripts import concerts_cloud_sync as sync


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "docs/grossesondes/concerts.json"
REFERENCE = ROOT / "docs/grossesondes/concerts-reference.json"
IDENT = "go-c-20261107-cenon-gwendoline"


def signature():
    spec = sync.ROCHER_PALMER_VERIFIED[IDENT]
    return {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": "2026-11-06",
        "officialEvidence": [{
            "url": "https://lerocherdepalmer.fr/agenda/gwendoline",
            "proofType": "official-organizer-or-venue",
            "checkedAt": "2026-11-06",
            "checkedFields": ["artists", "date", "venue", "genre", "startTime"],
            "notes": "Fiche individuelle officielle: Gwendoline + Bleu Panique, 7 novembre, début 20:30",
        }],
        "event": {
            "id": IDENT, "title": spec["title"], "date": spec["date"],
            "time": spec["time"], "artistIds": list(spec["artistIds"]),
            "venueId": "le-rocher-de-palmer-cenon",
            "genres": list(spec["genres"]), "status": "confirmed",
            "officialUrl": spec["officialUrl"], "sourceType": "salle",
            "organizer": "Le Rocher de Palmer",
        },
        "newArtists": [
            {"id": "gwendoline", "name": "Gwendoline"},
            {"id": "bleu-panique", "name": "Bleu Panique"}],
    }


def get_event(catalogue):
    return next(e for e in catalogue["events"] if e["id"] == IDENT)


class SignedExistingConcertCorrection(unittest.TestCase):
    def setUp(self):
        self.current = json.loads(PUBLIC.read_text(encoding="utf-8"))
        self.reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
        self.approval = signature()

    def test_prior_catalogue_is_untouched_and_protected(self):
        sync.protect_reference(self.reference, self.current)
        self.assertEqual(len([e for e in self.current["events"]
                              if e["id"] == IDENT]), 1)
        self.assertEqual(get_event(self.current)["title"], "Gwendoline")
        self.assertNotIn("bleu-panique",
                         {a["id"] for a in self.current["artists"]})

    def test_signed_patch_only_edits_one_event_and_appends_one_artist(self):
        original = copy.deepcopy(self.current)
        candidate = copy.deepcopy(self.current)
        sync.apply_gwendoline_signed_correction(candidate, self.approval)
        sync.protect_reference(self.reference, candidate)
        sync.validate_catalogue(candidate)
        before = get_event(original)
        after = get_event(candidate)
        self.assertEqual([e["id"] for e in original["events"]],
                         [e["id"] for e in candidate["events"]])
        self.assertEqual(len(original["events"]), len(candidate["events"]))
        self.assertEqual(original["venues"], candidate["venues"])
        self.assertEqual(original["events"][:len(self.reference["events"])],
                         candidate["events"][:len(self.reference["events"])])
        self.assertEqual({e["id"]: e for e in original["events"] if e["id"] != IDENT},
                         {e["id"]: e for e in candidate["events"] if e["id"] != IDENT})
        self.assertEqual(before["date"], after["date"])
        for key in ("id", "time", "timeMeaning", "venueId", "genres",
                    "officialUrl", "organizer", "status", "sourceType",
                    "sourceLabel", "locationPrecision"):
            self.assertEqual(before[key], after[key])
        self.assertEqual(after["title"], "Gwendoline + Bleu Panique")
        self.assertEqual(after["artistIds"], ["gwendoline", "bleu-panique"])
        self.assertEqual(after["lastVerified"], "2026-11-06")
        self.assertEqual(len(after["history"]), 2)
        self.assertEqual(after["history"][0], before["history"][0])
        self.assertIn("Bleu Panique", after["history"][1]["change"])
        self.assertEqual(len(candidate["artists"]), len(original["artists"]) + 1)
        self.assertEqual(candidate["artists"][:-1], original["artists"])
        self.assertEqual(candidate["artists"][-1],
                         {"id": "bleu-panique", "name": "Bleu Panique", "aliases": []})
        self.assertFalse(sync.validate_gwendoline_signed_correction(after,
                                                                      self.approval))
        with self.assertRaises(ValueError):
            sync.apply_gwendoline_signed_correction(candidate, self.approval)

    def test_mutated_signature_is_not_a_permission(self):
        for mutation in ("reviewer", "approval_date", "proof_source", "proof_date",
                         "proof_fields", "date", "lineup", "wrong_artist",
                         "doors_as_music", "wrong_venue", "wrong_genre"):
            a = copy.deepcopy(self.approval)
            if mutation == "reviewer":
                a["reviewedBy"] = "automated-official-recheck"
            elif mutation == "approval_date":
                a["reviewedAt"] = "2026-11-02"
            elif mutation == "proof_source":
                a["officialEvidence"][0]["url"] = "https://untrusted.example/show"
            elif mutation == "proof_date":
                a["officialEvidence"][0]["checkedAt"] = "2026-11-02"
            elif mutation == "proof_fields":
                a["officialEvidence"][0]["checkedFields"].remove("artists")
            elif mutation == "date":
                a["event"]["date"] = "2026-11-08"
            elif mutation == "lineup":
                a["event"]["artistIds"] = ["gwendoline"]
            elif mutation == "wrong_artist":
                a["newArtists"][1]["name"] = "Unknown Performer"
            elif mutation == "doors_as_music":
                a["event"]["time"] = "19:30"
            elif mutation == "wrong_venue":
                a["event"]["venueId"] = "other-venue"
            elif mutation == "wrong_genre":
                a["event"]["genres"] = ["Pop"]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                sync.apply_gwendoline_signed_correction(
                    copy.deepcopy(self.current), a)

    def test_invalid_old_state_or_preexisting_artist_is_rejected(self):
        for mutation in ("old_date", "old_artists", "old_time", "old_history",
                         "old_venue", "old_proof_date", "existing_artist_id",
                         "existing_artist_alias", "duplicate_event"):
            candidate = copy.deepcopy(self.current)
            e = get_event(candidate)
            if mutation == "old_date":
                e["date"] = "2026-11-08"
            elif mutation == "old_artists":
                e["artistIds"] = ["gwendoline", "someone-else"]
            elif mutation == "old_time":
                e["timeMeaning"] = "ouverture des portes"
            elif mutation == "old_history":
                e["history"] = []
            elif mutation == "old_venue":
                e["venueId"] = "another-room"
            elif mutation == "old_proof_date":
                e["lastVerified"] = "2026-11-01"
            elif mutation == "existing_artist_id":
                candidate["artists"].append(
                    {"id": "bleu-panique", "name": "Fake", "aliases": []})
            elif mutation == "existing_artist_alias":
                candidate["artists"].append(
                    {"id": "a-fake-id", "name": "Bleu Panique", "aliases": []})
            elif mutation == "duplicate_event":
                candidate["events"].append(copy.deepcopy(e))
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                sync.apply_gwendoline_signed_correction(candidate, self.approval)


if __name__ == "__main__":
    unittest.main()
