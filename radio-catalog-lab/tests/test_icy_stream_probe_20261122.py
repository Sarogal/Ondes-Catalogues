#!/usr/bin/env python3
"""Legacy ICY audio headers must not crash a 358-stream live probe."""
import http.client
import io
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import probe_full_radio_streams_20261122 as mod  # noqa: E402


class FakeSocket:
    def __init__(self, reply):
        self.reply = reply

    def makefile(self, *args, **kwargs):
        return io.BytesIO(self.reply)


class IcyHeaderTests(unittest.TestCase):
    def test_legacy_icy_200_ok_is_audio_stream_response(self):
        r = mod.IcyHTTPResponse(FakeSocket(
            b"ICY 200 OK\r\nContent-Type: audio/mpeg\r\n\r\nMP3_BYTES"))
        r.begin()
        self.assertEqual(r.status, 200)
        self.assertEqual(r.getheader("Content-Type"), "audio/mpeg")
        self.assertEqual(r.read(), b"MP3_BYTES")

    def test_standard_http_200_still_works(self):
        r = mod.IcyHTTPResponse(FakeSocket(
            b"HTTP/1.1 200 OK\r\nContent-Type: audio/aac\r\n"
            b"Content-Length: 3\r\n\r\nAAC"))
        r.begin()
        self.assertEqual(r.status, 200)
        self.assertEqual(r.read(), b"AAC")

    def test_malformed_status_does_not_abort_all_stations(self):
        with patch.object(mod, "download_sample", side_effect=http.client.BadStatusLine("oops")):
            report = mod.inspect_stream("go-station-000001",
                {"stream_id": "legacy-stream-001", "url": "http://example.org/audio"},
                "ffmpeg", "2026-11-22T00:00:00Z")
        self.assertFalse(report["verified"])
        self.assertEqual(report["result"], "invalid_http_status_BadStatusLine")

    def test_redirect_to_local_ip_is_rejected(self):
        with self.assertRaises(ValueError):
            mod.check_public_host("http://169.254.169.254/latest/meta-data")


    def test_hls_media_segment_is_decoded_without_external_ffmpeg_urls(self):
        master = b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=128000\nvariant.m3u8\n"
        media = b"#EXTM3U\n#EXTINF:4.0,\nsegment-a.ts\n"
        audio = b"RANDOM_AUDIO_BYTES_FOR_MOCK"
        requests = []

        def fake_download(url, **kwargs):
            requests.append(url)
            if url.endswith("variant.m3u8"):
                return media, "application/vnd.apple.mpegurl", url
            if url.endswith("segment-a.ts"):
                return audio, "video/mp2t", url
            return master, "application/vnd.apple.mpegurl", url

        with patch.object(mod, "download_sample", side_effect=fake_download):
            with patch.object(mod, "decode_sample", return_value=(True, "audio_decoded")):
                result = mod.inspect_stream("go-station-000001",
                    {"stream_id": "one", "url": "https://example.org/live.m3u8"},
                    "ffmpeg", "2026-11-22T00:00:00Z")
        self.assertTrue(result["verified"])
        self.assertEqual(result["result"], "audio_decoded")
        self.assertEqual(requests, ["https://example.org/live.m3u8",
                                    "https://example.org/variant.m3u8",
                                    "https://example.org/segment-a.ts"])

    def test_hls_playlist_cannot_redirect_into_local_network(self):
        playlist = b"#EXTM3U\n#EXTINF:3\nhttp://127.0.0.1/admin\n"
        target, reason = mod.first_public_playlist_link(playlist, "https://radio.example.org/x.m3u8")
        self.assertIsNone(target)
        self.assertEqual(reason, "playlist_without_public_audio_url")

    def test_encrypted_hls_cannot_be_misreported_as_verified(self):
        encrypted = b'#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key.key"\n#EXTINF:3\nsegment.ts\n'
        _, reason = mod.first_public_playlist_link(encrypted, "https://example.org/live.m3u8")
        self.assertEqual(reason, "hls_encrypted_requires_player")


if __name__ == "__main__":
    unittest.main()
