import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from radio_daily_inherited_artwork_cache import populate, cached, filename
from radio_daily_live_inherited_artwork import recover_inherited, ArtworkUnavailable
from radio_daily_v9_generator import digest
from test_radio_daily_state_migration import sign
from test_radio_daily_logo_plan import reports, DATA, OLD, DAY, URL
import json


class InheritedCacheTests(unittest.TestCase):
    def setUp(self):
        raw,*_=reports(True)
        doc=json.loads(raw)
        doc["stations"][0]["logo"].update(sha256=digest(DATA),asset_id="sha256:"+digest(DATA),
                    byte_size=len(DATA),mime_type="image/png",width=128,height=128)
        self.doc=doc
        self.logo=doc["stations"][0]["logo"]
        self.pointer,self.raw,self.anchor=sign(doc)
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.previous=self.root/"previous"
        self.previous.mkdir()

    def run_cache(self, fetch, previous=None, name="out", limit=12):
        return populate(self.pointer,self.raw,anchor=self.anchor,day=DAY,
            previous=previous or self.previous,output=self.root/name,fetch=fetch,limit=limit)

    def test_exact_bytes_persist_and_reused_without_fetch(self):
        fetch=Mock(return_value=(DATA,"image/png"))
        r=self.run_cache(fetch)
        self.assertEqual(r["recoveredCount"],1)
        self.assertEqual(r["remainingCount"],0)
        fetch.assert_called_once()
        fetch.reset_mock()
        r=self.run_cache(fetch,previous=self.root/"out",name="second")
        self.assertEqual(r["cachedCount"],1)
        self.assertEqual(r["attemptedCount"],0)
        fetch.assert_not_called()

    def test_wrong_bytes_never_written(self):
        r=self.run_cache(lambda u,h:(OLD,"image/png"))
        self.assertEqual(r["remainingCount"],1)
        self.assertEqual(list((self.root/"out").iterdir()),[])

    def test_corrupt_existing_cache_refused(self):
        (self.previous/filename(self.logo)).write_bytes(OLD)
        fetch=Mock()
        with self.assertRaises(ValueError):
            self.run_cache(fetch)
        fetch.assert_not_called()

    def test_inherited_recovery_reads_cache_not_network(self):
        (self.previous/filename(self.logo)).write_bytes(DATA)
        fetch=Mock()
        self.assertEqual(recover_inherited(self.doc,self.doc,fetch=fetch,cache_dirs=[self.previous]),
                         {URL:DATA})
        fetch.assert_not_called()

    def test_missing_cache_holds_publication_without_refetch(self):
        fetch=Mock()
        with self.assertRaises(ArtworkUnavailable):
            recover_inherited(self.doc,self.doc,fetch=fetch,cache_dirs=[self.previous])
        fetch.assert_not_called()

    def test_budget_zero_never_downloads(self):
        fetch=Mock()
        r=self.run_cache(fetch,limit=0)
        self.assertEqual(r["attemptedCount"],0)
        fetch.assert_not_called()

    def test_symlink_cache_file_rejected(self):
        source=self.root/"source"
        source.write_bytes(DATA)
        (self.previous/filename(self.logo)).symlink_to(source)
        with self.assertRaises(ValueError):
            cached(self.logo,[self.previous])

    def first_party_fixture(self):
        self.logo["url"]="https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/feature/test/artwork/"+filename(self.logo)
        self.pointer,self.raw,self.anchor=sign(self.doc)
        local=self.root/"local"
        local.mkdir()
        return local

    def test_verified_first_party_import_without_network(self):
        local=self.first_party_fixture()
        (local/filename(self.logo)).write_bytes(DATA)
        fetch=Mock()
        report=populate(self.pointer,self.raw,anchor=self.anchor,day=DAY,
            previous=self.previous,output=self.root/"out",fetch=fetch,
            limit=0,local_sources=[local])
        self.assertEqual(report["localImportedCount"],1)
        self.assertEqual(report["localImportedBytes"],len(DATA))
        self.assertEqual(report["networkRecoveredCount"],0)
        self.assertEqual(report["remainingCount"],0)
        self.assertEqual((self.root/"out"/filename(self.logo)).read_bytes(),DATA)
        fetch.assert_not_called()

    def test_corrupt_local_source_is_not_imported(self):
        local=self.first_party_fixture()
        (local/filename(self.logo)).write_bytes(OLD)
        fetch=Mock()
        report=populate(self.pointer,self.raw,anchor=self.anchor,day=DAY,
            previous=self.previous,output=self.root/"out",fetch=fetch,
            limit=0,local_sources=[local])
        self.assertEqual(report["localImportedCount"],0)
        self.assertEqual(report["localRejectedCount"],1)
        self.assertEqual(report["remainingCount"],1)
        fetch.assert_not_called()

    def test_external_image_not_sourced_from_unrelated_checkout(self):
        local=self.root/"local"
        local.mkdir()
        (local/filename(self.logo)).write_bytes(DATA)
        report=populate(self.pointer,self.raw,anchor=self.anchor,day=DAY,
            previous=self.previous,output=self.root/"out",fetch=Mock(),
            limit=0,local_sources=[local])
        self.assertEqual(report["localImportedCount"],0)
        self.assertEqual(report["remainingCount"],1)

    def test_local_import_not_repeated_if_cache_contains_image(self):
        local=self.first_party_fixture()
        (local/filename(self.logo)).write_bytes(DATA)
        (self.previous/filename(self.logo)).write_bytes(DATA)
        fetch=Mock()
        report=populate(self.pointer,self.raw,anchor=self.anchor,day=DAY,
            previous=self.previous,output=self.root/"out",fetch=fetch,
            limit=0,local_sources=[local])
        self.assertEqual(report["cachedCount"],1)
        self.assertEqual(report["localImportedCount"],0)
        fetch.assert_not_called()
