from copy import deepcopy
import base64
import hashlib
import json
import unittest
from unittest.mock import Mock

from test_ptitesondes_catalogue_geo_correction_preview import DAY, fixture, page
from ptitesondes_historical_gps_cloud import prepare_cloud_repairs, read_private_json
from ptitesondes_historical_gps_ledger import empty_ledger, reconcile


class GPSCloudTests(unittest.TestCase):
    def test_private_checkpoint_only_is_not_proof(self):
        doc, state, proof = fixture()
        inputs = {"catalogue-geo-rotation.json": state}
        read = lambda name, token: inputs.get(name)
        updated, ledger, count = prepare_cloud_repairs(doc, doc, empty_ledger(),
            DAY, "test", reader=read, researcher_factory=lambda _: lambda *_: None,
            source_reader=lambda _: self.fail("source without fresh proof"))
        self.assertEqual(count, 0)
        self.assertEqual(updated, doc)
        self.assertEqual(ledger, empty_ledger())

    def test_fresh_recheck_and_future_reconciliation(self):
        doc, state, proof = fixture()
        before = deepcopy(doc)
        read = lambda name, token: state if name == "catalogue-geo-rotation.json" else None
        updated, ledger, count = prepare_cloud_repairs(doc, doc, empty_ledger(),
            DAY, "test", reader=read, researcher_factory=lambda _: lambda *_: proof,
            source_reader=lambda _: page())
        self.assertEqual(count, 1)
        self.assertEqual(doc, before)
        self.assertEqual(reconcile(doc, updated, ledger), updated)
        self.assertEqual(updated["events"][1:], before["events"][1:])
        again, same, count = prepare_cloud_repairs(doc, updated, ledger, DAY, "test",
            reader=read, researcher_factory=lambda _: lambda *_: self.fail("already valid"))
        self.assertEqual((again, same, count), (updated, ledger, 0))

    def test_missing_checkpoint_no_effect(self):
        doc, _, _ = fixture()
        reader = Mock(return_value=None)
        self.assertEqual(prepare_cloud_repairs(doc, doc, empty_ledger(), DAY, "test",
            reader=reader), (doc, empty_ledger(), 0))
        reader.assert_called_once()

    def test_pinned_private_blob_verified(self):
        name = "catalogue-geo-rotation.json"
        data = b'{"test": true}'
        sha = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        from private_intake import PATH
        meta = dict(type="file", path=PATH + "/" + name, size=len(data), sha=sha)
        blob = dict(encoding="base64", size=len(data), sha=sha,
                    content=base64.b64encode(data).decode())
        reader = Mock(side_effect=[meta, blob])
        self.assertEqual(read_private_json(name, "test", reader=reader), {"test": True})
        self.assertEqual(reader.call_args_list[1].kwargs, {"blob": True})
        bad = dict(blob, content=base64.b64encode(b"x" * len(data)).decode())
        with self.assertRaisesRegex(ValueError, "integrity"):
            read_private_json(name, "test", reader=Mock(side_effect=[meta,bad]))
        with self.assertRaisesRegex(ValueError, "unknown"):
            read_private_json("../secret", "test", reader=Mock())
