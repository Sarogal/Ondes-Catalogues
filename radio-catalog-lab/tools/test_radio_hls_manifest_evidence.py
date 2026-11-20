"""No-network HLS manifest classification; no segment or variant fetch."""
import unittest

from radio_hls_manifest_evidence import inspect_hls_manifest, MAX_HLS_BYTES

URL = "https://radio.example.org/hls/channel.m3u8"
MIME = "application/vnd.apple.mpegurl"


def inspect(text, mime=MIME, url=URL):
    return inspect_hls_manifest(text.encode("utf-8"), mime, url)


class HlsManifestTests(unittest.TestCase):
    def test_valid_live_media_is_a_candidate_not_audio_proof(self):
        data = "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:5\n#EXT-X-MEDIA-SEQUENCE:18\n#EXTINF:5,\nseg18.ts\n#EXTINF:5,\nseg19.ts\n"
        report = inspect(data)
        self.assertEqual(report["kind"], "live_manifest_candidate")
        self.assertEqual(report["segmentCount"], 2)
        self.assertEqual(report["variantCount"], 0)
        self.assertTrue(report["liveCandidate"])
        self.assertFalse(report["publicationAllowed"])
        self.assertNotIn("seg18", str(report))
        self.assertNotIn("radio.example", str(report))

    def test_live_candidate_not_equivalent_to_live_broadcast(self):
        data = "#EXTM3U\n#EXT-X-TARGETDURATION:5\n#EXTINF:5,\na.ts\n#EXTINF:5,\nb.ts\n"
        self.assertTrue(inspect(data)["liveCandidate"])
        self.assertFalse(inspect(data)["publicationAllowed"])

    def test_master_with_one_variant_is_not_auto_followed(self):
        report = inspect("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=128000,CODECS=\"mp4a.40.2\"\naudio/index.m3u8\n")
        self.assertEqual(report["kind"], "master_single_variant_pending")
        self.assertEqual(report["variantCount"], 1)
        self.assertNotIn("target", report)
        self.assertFalse(report["liveCandidate"])

    def test_multi_variant_master_is_ambiguous(self):
        report = inspect("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=80000\nlow.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=180000\nhi.m3u8\n")
        self.assertEqual(report["kind"], "master_ambiguous_pending")
        self.assertEqual(report["variantCount"], 2)

    def test_on_demand_vod_is_not_live(self):
        report = inspect("#EXTM3U\n#EXT-X-TARGETDURATION:5\n#EXTINF:5,\na.ts\n#EXTINF:5,\nb.ts\n#EXT-X-ENDLIST\n")
        self.assertEqual(report["kind"], "media_finite_playlist")
        self.assertFalse(report["liveCandidate"])

    def test_encryption_and_external_init_are_pending(self):
        for line in (
            '#EXT-X-KEY:METHOD=AES-128,URI="key.bin"',
            '#EXT-X-SESSION-KEY:METHOD=AES-128,URI="key.bin"',
            '#EXT-X-MAP:URI="init.mp4"',
            '#EXT-X-BYTERANGE:1200@0',
            '#EXT-X-PART:DURATION=0.2,URI="part.ts"',
            '#EXT-X-PRELOAD-HINT:TYPE=PART,URI="new.ts"',
            '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="1",URI="audio.m3u8"',
        ):
            with self.subTest(line=line):
                report = inspect("#EXTM3U\n" + line + "\n#EXT-X-TARGETDURATION:5\n#EXTINF:5,\na.ts\n#EXTINF:5,\nb.ts\n")
                self.assertEqual(report["kind"], "manifest_advanced_or_encrypted")
                self.assertFalse(report["liveCandidate"])

    def test_incomplete_no_terminal_line_is_not_live(self):
        report = inspect("#EXTM3U\n#EXT-X-TARGETDURATION:5\n#EXTINF:5,\na.ts\n#EXTINF:5,\nb")
        self.assertEqual(report["kind"], "manifest_incomplete")

    def test_valid_target_duration_required(self):
        for value in ("0", "9999", "unknown", "-5"):
            with self.subTest(value=value):
                report = inspect(f"#EXTM3U\n#EXT-X-TARGETDURATION:{value}\n#EXTINF:5,\na.ts\n#EXTINF:5,\nb.ts\n")
                self.assertEqual(report["kind"], "media_invalid_duration")

    def test_invalid_media_sequence_rejected(self):
        report = inspect("#EXTM3U\n#EXT-X-TARGETDURATION:5\n#EXT-X-MEDIA-SEQUENCE:abc\n#EXTINF:5,\na.ts\n#EXTINF:5,\nb.ts\n")
        self.assertEqual(report["kind"], "media_invalid_sequence")

    def test_incomplete_metadata_and_segment_mismatch(self):
        no_target = inspect("#EXTM3U\n#EXTINF:5,\na.ts\n#EXTINF:5,\nb.ts\n")
        self.assertEqual(no_target["kind"], "not_hls")
        mismatch = inspect("#EXTM3U\n#EXT-X-TARGETDURATION:5\n#EXTINF:5,\na.ts\nsecond.ts\n")
        self.assertEqual(mismatch["kind"], "media_incomplete_segments")

    def test_manifest_size_and_lines_are_bounded(self):
        report = inspect("#EXTM3U\n#EXT-X-TARGETDURATION:5\n" + "#comment\n" * 150)
        self.assertEqual(report["kind"], "manifest_too_many_lines")
        report = inspect("#EXTM3U\n" + "x" * MAX_HLS_BYTES + "\n")
        self.assertEqual(report["kind"], "manifest_oversized")
        report = inspect("#EXTM3U\n" + "x" * (MAX_HLS_BYTES - 9))
        self.assertEqual(report["kind"], "manifest_oversized")

    def test_manifest_over_old_512_byte_limit_is_scannable(self):
        text = ("#EXTM3U\n#EXT-X-TARGETDURATION:5\n"
                + "# annotation without URL: valid HLS extension \n" * 12
                + "#EXTINF:5,\na.ts\n#EXTINF:5,\nb.ts\n")
        self.assertGreater(len(text.encode("utf-8")), 512)
        self.assertLess(len(text.encode("utf-8")), MAX_HLS_BYTES)
        self.assertEqual(inspect(text)["kind"], "live_manifest_candidate")

    def test_html_and_simple_m3u_are_not_hls(self):
        for content in ("<html>hello</html>\n", "#EXTM3U\nhttps://radio.example.org/live.mp3\n"):
            self.assertEqual(inspect(content)["kind"], "not_hls")

    def test_segment_uri_not_exposed_and_special_schemes_rejected(self):
        for segment in ("file:///etc/passwd", "data:text/plain,hello", "//127.0.0.1/secret"):
            report = inspect("#EXTM3U\n#EXT-X-TARGETDURATION:5\n#EXTINF:5,\n" + segment + "\n#EXTINF:5,\nok.ts\n")
            self.assertEqual(report["kind"], "media_unsupported_reference")
            self.assertNotIn(segment, str(report))

    def test_untrusted_payload_never_allows_publication(self):
        data = "#EXTM3U\n#EXT-X-TARGETDURATION:5\n#EXTINF:5,\na.ts\n#EXTINF:5,\nb.ts\n"
        for mime in (MIME, "audio/x-mpegurl", "application/octet-stream"):
            result = inspect(data, mime)
            self.assertFalse(result["publicationAllowed"])


if __name__ == "__main__":
    unittest.main()
