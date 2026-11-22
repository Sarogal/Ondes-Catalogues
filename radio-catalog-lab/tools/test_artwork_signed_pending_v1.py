#!/usr/bin/env python3
"""Only inspect signed ARTWORK TEST pending v1; radio generation 4 stays active."""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from artwork_release_packager import (
    ArtworkBundleError, verify,wire,
)

ROOT=Path(__file__).resolve().parents[2]
TEST=ROOT/"grossesondes/radio-test-apk"
ART=TEST/"artwork"
SHA="b85a4ddc27783e2a242747924f28a5438f1fb8d5adb6500c28126a90e588235d"


class SignedArtTestPendingFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pointer=(ART/"pending/test-current-v1.json").read_bytes()
        cls.body=(ART/f"releases/{SHA}.json").read_bytes()
        cls.pub=Ed25519PublicKey.from_public_bytes(
            base64.b64decode((TEST/"TEST_PUBLIC_KEY.b64").read_bytes().strip())
        )

    def test_signature_body_and_nine_verified_reviewed_identities(self):
        d=verify(self.pointer,self.body,self.pub)
        self.assertEqual(d["release_sequence"],1)
        self.assertEqual(len(d["assets"]),9)
        self.assertEqual(hashlib.sha256(self.body).hexdigest(),SHA)
        self.assertEqual(
            {r["source"]["provider"] for r in d["assets"]},{"laut.fm"})
        self.assertTrue(all(
            r["replace_existing_logo"] is False and
            r["logo"]["width"]==600 and r["logo"]["height"]==600
            for r in d["assets"]
        ))

    def test_radio_catalog_v4_and_artwork_pointer_do_not_move(self):
        current=json.loads((TEST/"current.json").read_text(encoding="utf-8"))
        self.assertEqual(current["release_sequence"],4)
        self.assertEqual(current["catalog_id"],"grosses-ondes-radio")
        self.assertFalse((ART/"current.json").exists(),
                         "The artwork manifest MUST NOT activate automatically")
        self.assertEqual(len(list((ART/"pending").glob("test-current-*.json"))),1)

    def test_tamper_or_wrong_key_rejected(self):
        data=bytearray(self.body)
        data[-3]^=1
        with self.assertRaises(ArtworkBundleError):
            verify(self.pointer,bytes(data),self.pub)
        wrong=Ed25519PublicKey.from_public_bytes(bytes([1])*32)
        with self.assertRaises(ArtworkBundleError):
            verify(self.pointer,self.body,wrong)

    def test_sideload_is_test_key_not_production(self):
        p=json.loads(self.pointer)
        self.assertEqual(p["scope"],"TEST_ONLY")
        self.assertEqual(p["catalog_id"],"grosses-ondes-artwork")
        self.assertEqual(p["signature"]["key_id"],"go-apk-test-20261121")


if __name__=="__main__":
    unittest.main()
