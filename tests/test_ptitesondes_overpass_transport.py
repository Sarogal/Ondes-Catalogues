"""Offline contracts for the shared Overpass transport."""
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError

import ptitesondes_generic_venue_osm_preflight as osm
from ptitesondes_catalogue_geo_proof_batch import fetch_named_osm


def response(payload):
    reply = MagicMock()
    reply.status = 200
    reply.read.return_value = payload
    reply.__enter__.return_value = reply
    return reply


class TransportTests(unittest.TestCase):
    def setUp(self):
        osm._osm_counters.clear()
        osm._osm_cooldowns.clear()
        self.addCleanup(osm._osm_counters.clear)
        self.addCleanup(osm._osm_cooldowns.clear)

    def test_rate_limit_fallback_and_shared_cooldown(self):
        opener = MagicMock()
        success = response(b'{"elements":[]}')
        def opened(req, timeout):
            if "lz4" in req.full_url:
                raise HTTPError(req.full_url, 429, "private detail", {}, None)
            success.geturl.return_value = req.full_url
            return success
        opener.open.side_effect = opened
        with patch.object(osm, "build_opener", return_value=opener), patch.object(osm, "monotonic", return_value=1):
            self.assertEqual(fetch_named_osm("12345", "Private venue"), {"elements": []})
            self.assertEqual(osm.fetch_overpass((43.0, 3.0)), {"elements": []})
        self.assertEqual(opener.open.call_count, 3)
        self.assertEqual(osm.osm_transport_diagnostics(), {
            "named.lz4.http_429": 1, "named.private_coffee.success": 1,
            "nearby.lz4.cooldown": 1, "nearby.private_coffee.success": 1})

    def test_timeout_and_bad_json_are_distinguished(self):
        opener = MagicMock()
        invalid = response(b"<html>not JSON</html>")
        def opened(req, timeout):
            if "lz4" in req.full_url:
                raise URLError(TimeoutError("secret"))
            invalid.geturl.return_value = req.full_url
            return invalid
        opener.open.side_effect = opened
        with patch.object(osm, "build_opener", return_value=opener):
            with self.assertRaisesRegex(ValueError, "^named_provider_unavailable$"):
                fetch_named_osm("12345", "Private venue")
        self.assertEqual(osm.osm_transport_diagnostics(), {
            "named.lz4.timeout": 1, "named.private_coffee.invalid_json": 1})

    def test_incomplete_response_uses_fallback(self):
        opener = MagicMock()
        def opened(req, timeout):
            payload = (b'{"elements":[],"remark":"private detail"}'
                       if "lz4" in req.full_url else b'{"elements":[]}')
            reply = response(payload)
            reply.geturl.return_value = req.full_url
            return reply
        opener.open.side_effect = opened
        with patch.object(osm, "build_opener", return_value=opener):
            self.assertEqual(osm.fetch_overpass((43.0, 3.0)), {"elements": []})
        self.assertEqual(osm.osm_transport_diagnostics(), {
            "nearby.lz4.incomplete_response": 1, "nearby.private_coffee.success": 1})

    def test_cooldown_expires(self):
        opener = MagicMock()
        def opened(req, timeout):
            reply = response(b'{"elements":[]}')
            reply.geturl.return_value = req.full_url
            return reply
        opener.open.side_effect = opened
        osm._osm_cooldowns["lz4"] = 60
        with patch.object(osm, "build_opener", return_value=opener), patch.object(osm, "monotonic", return_value=61):
            self.assertEqual(osm.fetch_overpass((43.0, 3.0)), {"elements": []})
        self.assertEqual(osm.osm_transport_diagnostics(), {"nearby.lz4.success": 1})
