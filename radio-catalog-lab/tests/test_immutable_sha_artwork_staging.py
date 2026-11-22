#!/usr/bin/env python3
"""Tests for immutable SHA object staging: no mismatched image is published."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from stage_immutable_sha_artwork import mirror, normalized_assets  # noqa: E402


class ImmutableImageTests(unittest.TestCase):
    def setUp(self):
        self.raw=b"\x89PNG\r\n\x1a\n" + b"byte-perfect-test-bytes"
        self.sha=hashlib.sha256(self.raw).hexdigest()
        self.logo={
            "asset_id":"sha256:"+self.sha, "sha256":self.sha, "revision":1,
            "url":"https://example.org/logo.png", "byte_size":len(self.raw),
            "width":600,"height":600,"mime_type":"image/png"}
        self.catalog={"release_sequence":5,
            "stations":[{"go_station_id":f"go-station-{i:06d}","logo":None}
                        for i in range(1,321)]}
        self.catalog["stations"][0]["logo"]=self.logo

    def inspect(self, b, *, content_type):
        self.assertEqual(content_type,"image/png")
        return {"sha256":hashlib.sha256(b).hexdigest(),"byte_size":len(b),
            "width":600,"height":600,"mime_type":"image/png"}

    def test_correct_bytes_saved_under_digest_only(self):
        with tempfile.TemporaryDirectory() as root:
            d=Path(root)/"new"
            report=mirror(self.catalog,index=0,count=1,destination=d,
                fetcher=lambda url,**kw:(self.raw,"image/png",url),
                inspector=self.inspect)
            self.assertEqual(report["stored"],1)
            self.assertEqual(report["failed"],0)
            self.assertEqual((d/"sha256"/(self.sha+".png")).read_bytes(),self.raw)
            self.assertFalse(report["signed_or_published"])
            with self.assertRaises(ValueError):
                mirror(self.catalog,index=0,count=1,destination=d)

    def test_mutated_bytes_rejected_without_creating_any_image(self):
        with tempfile.TemporaryDirectory() as root:
            d=Path(root)/"new"
            report=mirror(self.catalog,index=0,count=1,destination=d,
                fetcher=lambda url,**kw:(self.raw+b"extra","image/png",url),
                inspector=self.inspect)
            self.assertEqual(report["stored"],0)
            self.assertEqual(report["failed"],1)
            self.assertEqual(list((d/"sha256").iterdir()),[])

    def test_same_sha_shared_by_two_stations_stores_one_blob(self):
        self.catalog["stations"][1]["logo"]=dict(self.logo)
        self.assertEqual(len(normalized_assets(self.catalog)),1)

    def test_conflicting_metadata_is_rejected(self):
        self.catalog["stations"][1]["logo"]=dict(self.logo,width=601)
        with self.assertRaises(ValueError):
            normalized_assets(self.catalog)

    def test_non_public_url_rejected(self):
        self.catalog["stations"][0]["logo"]=dict(self.logo,url="http://127.0.0.1/evil")
        with self.assertRaises(ValueError):
            normalized_assets(self.catalog)


if __name__ == "__main__":
    unittest.main(verbosity=2)
