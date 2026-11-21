#!/usr/bin/env python3
"""Offline Ed25519 artwork pointer tests: distinct context, SHA and monotonicity."""
from copy import deepcopy
import json
import unittest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from artwork_release_packager import (
    ArtworkBundleError,sign_pending,verify,wire,validate_body,
)

PUBLISHED="2026-11-21T11:30:00Z"
KEY_ID="go-apk-test-20261121"


def manifest():
    return {
        "schema_version":1,"catalog_id":"grosses-ondes-artwork",
        "release_sequence":1,"generated_at":PUBLISHED,
        "source_radio_catalog_min_sequence":4,
        "scope":"TEST_ONLY","production_publication_allowed":False,
        "selection_mode":"manual_visual_review_of_open_discovery_candidates",
        "assets":[{
            "legacy_media_id":"123e4567-e89b-42d3-a456-426614174000",
            "station_name":"New future Punk Radio",
            "replace_existing_logo":False,
            "logo":{
                "asset_id":"sha256:"+"f"*64,
                "sha256":"f"*64,
                "url":"https://assets.laut.fm/"+"a"*32,
                "byte_size":20000,"width":600,"height":600,
                "mime_type":"image/png","revision":1,
            },
            "source":{
                "provider":"laut.fm",
                "official_station_page":"https://laut.fm/future_punk_radio",
                "station_slug":"future_punk_radio",
                "visual_identity_evidence":"Explicit FUTURE PUNK RADIO logo",
                "review_scope":"test_only",
            }
        }],
    }


class SignedSidecarTests(unittest.TestCase):
    def setUp(self):
        self.secret=Ed25519PrivateKey.generate()
        self.doc=manifest()
        self.content=wire(self.doc)
        self.ptr=sign_pending(self.content,self.secret,KEY_ID,PUBLISHED)

    def test_new_unseen_station_uuid_is_valid_without_closed_list(self):
        d=verify(self.ptr,self.content,self.secret.public_key())
        self.assertEqual(len(d["assets"]),1)
        self.assertEqual(d["source_radio_catalog_min_sequence"],4)
        self.assertFalse(d["production_publication_allowed"])

    def test_content_change_or_unknown_key_rejected(self):
        body=bytearray(self.content)
        body[-3]=ord("x")
        with self.assertRaises(ArtworkBundleError):
            verify(self.ptr,bytes(body),self.secret.public_key())
        with self.assertRaises(ArtworkBundleError):
            verify(self.ptr,self.content,Ed25519PrivateKey.generate().public_key())

    def test_signature_context_is_not_radio_catalog_context(self):
        p=json.loads(self.ptr)
        from artwork_release_packager import sign_message
        self.assertTrue(
            sign_message(p).startswith(b"GO-RADIO-ARTWORK-POINTER-V1\n")
        )
        self.assertFalse(
            sign_message(p).startswith(b"GO-RADIO-CATALOG-POINTER-V1\n")
        )

    def test_replacement_and_duplicate_uuid_forbidden(self):
        d=deepcopy(self.doc)
        d["assets"][0]["replace_existing_logo"]=True
        with self.assertRaises(ArtworkBundleError):
            validate_body(wire(d))
        d=deepcopy(self.doc)
        d["assets"].append(deepcopy(d["assets"][0]))
        with self.assertRaises(ArtworkBundleError):
            validate_body(wire(d))

    def test_signed_rollback_prevented(self):
        with self.assertRaises(ArtworkBundleError):
            validate_body(self.content,previous=self.doc)
        d=deepcopy(self.doc)
        d["release_sequence"]=2
        updated=wire(d)
        p=sign_pending(updated,self.secret,KEY_ID,PUBLISHED,previous=self.doc)
        self.assertEqual(
            verify(p,updated,self.secret.public_key(),previous=self.doc)
            ["release_sequence"],2)

    def test_unknown_official_provider_is_supported_after_explicit_review(self):
        d=deepcopy(self.doc)
        s=d["assets"][0]["source"]
        s["provider"]="new-independent-community-radio"
        s["official_station_page"]="https://brand-new.example.net/stations/punk"
        s["station_slug"]="unique-channel-2026"
        s["visual_identity_evidence"]="Verified station-specific wordmark from the official station page"
        d["assets"][0]["logo"]["url"] = (
            "https://new-cdn.example.net/artwork/channel_logo.png?revision=5"
        )
        content=wire(d)
        pointer=sign_pending(content,self.secret,KEY_ID,PUBLISHED)
        self.assertEqual(len(verify(pointer,content,self.secret.public_key())["assets"]),1)

    def test_non_laut_source_still_needs_official_page_and_identity_review(self):
        d=deepcopy(self.doc)
        d["assets"][0]["source"]["provider"]="new-independent-radio"
        d["assets"][0]["source"]["official_station_page"]="http://localhost/private"
        with self.assertRaises(ArtworkBundleError):
            validate_body(wire(d))
        d["assets"][0]["source"]["official_station_page"] = (
            "https://independent.example.org/stations/punk"
        )
        d["assets"][0]["source"]["visual_identity_evidence"]="just favicon"
        with self.assertRaises(ArtworkBundleError):
            validate_body(wire(d))

    def test_laut_fm_existing_strict_source_mapping_is_unchanged(self):
        d=deepcopy(self.doc)
        d["assets"][0]["logo"]["url"]="https://unrelated.example.org/logo.png"
        with self.assertRaises(ArtworkBundleError):
            validate_body(wire(d))

    def test_rejects_http_private_ips_and_low_res(self):
        for url in ("http://station.example.org/a.png","https://127.0.0.1/a",
                    "https://localhost/logo.png"):
            d=deepcopy(self.doc)
            d["assets"][0]["logo"]["url"]=url
            with self.assertRaises(ArtworkBundleError):
                validate_body(wire(d))
        d=deepcopy(self.doc)
        d["assets"][0]["logo"]["width"]=120
        with self.assertRaises(ArtworkBundleError):
            validate_body(wire(d))


if __name__=="__main__":unittest.main()
