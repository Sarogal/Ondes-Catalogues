"""Synthetic safe playlist resolution and HLS manifest classification."""
import unittest
from radio_stream_playlist_preview import (
    MAX_PLAYLIST_BYTES, playlist_hint,
)

BASE = "https://radio.example.org/listen.m3u"


class RadioPlaylistPreviewTests(unittest.TestCase):
    def test_m3u_single_absolute_stream(self):
        hint = playlist_hint(
            b"#EXTM3U\n#EXTINF:-1,Metal FM\nhttps://stream.example.org/live\n",
            "audio/x-mpegurl", BASE)
        self.assertEqual(hint.kind, "playlist_single_target")
        self.assertEqual(hint.target, "https://stream.example.org/live")

    def test_m3u_single_relative_stream(self):
        hint = playlist_hint(b"#EXTM3U\n../radio.mp3\n",
                             "audio/x-mpegurl", BASE)
        self.assertEqual(hint.target, "https://radio.example.org/radio.mp3")

    def test_pls_single_stream(self):
        hint = playlist_hint(
            b"[playlist]\nnumberofentries=1\nFile1=http://radio.example.org:8080/live\nTitle1=Hard Rock\n",
            "audio/x-scpls", "http://radio.example.org/playlist.pls")
        self.assertEqual(hint.kind, "playlist_single_target")
        self.assertEqual(hint.target, "http://radio.example.org:8080/live")

    def test_pls_lowercase_key(self):
        hint = playlist_hint(b"[playlist]\nfile1=/radio\n",
                             "audio/x-scpls", "http://radio.example.org/listen.pls")
        self.assertEqual(hint.target, "http://radio.example.org/radio")

    def test_hls_media_manifest_is_never_followed_as_audio(self):
        hint = playlist_hint(
            b"#EXTM3U\n#EXT-X-TARGETDURATION:5\n#EXTINF:5,\nsegment.ts",
            "application/vnd.apple.mpegurl",
            "https://radio.example.org/hls/live.m3u8")
        self.assertEqual(hint.kind, "hls_manifest_pending")
        self.assertIsNone(hint.target)

    def test_hls_master_manifest_is_not_descended(self):
        hint = playlist_hint(
            b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=96000\n"
            b"lower/index.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=192000\nhigher/index.m3u8",
            "application/vnd.apple.mpegurl",
            "https://radio.example.org/master.m3u8")
        self.assertEqual(hint.kind, "hls_manifest_pending")
        self.assertIsNone(hint.target)

    def test_hls_detected_by_manifest_marker_not_filename(self):
        hint = playlist_hint(b"#EXTM3U\n#EXT-X-VERSION:3\nsegment.ts",
                             "audio/x-mpegurl", BASE)
        self.assertEqual(hint.kind, "hls_manifest_pending")

    def test_multiple_distinct_targets_not_arbitrarily_merged(self):
        hint = playlist_hint(
            b"#EXTM3U\nhttps://a.example.org/live\nhttps://b.example.org/live\n",
            "audio/x-mpegurl", BASE)
        self.assertEqual(hint.kind, "playlist_multiple_targets")
        self.assertIsNone(hint.target)

    def test_more_than_eight_targets_rejected(self):
        body = b"#EXTM3U\n" + b"\n".join(
            f"https://radio.example.org/{i}".encode() for i in range(9))
        hint = playlist_hint(body, "audio/x-mpegurl", BASE)
        self.assertEqual(hint.kind, "playlist_too_many_targets")

    def test_empty_or_unrecognized_playlist_not_followed(self):
        for data, mime, path, expected in (
            (b"#EXTM3U", "audio/x-mpegurl", BASE, "playlist_no_target"),
            (b"<html>not a playlist</html>", "text/html", BASE, "playlist_unknown_format"),
            (b"[playlist]\nnumberofentries=1", "audio/x-scpls",
             "https://radio.example.org/listen.pls", "playlist_no_target"),
        ):
            with self.subTest(expected=expected):
                self.assertEqual(playlist_hint(data, mime, path).kind, expected)

    def test_m3u_uri_cannot_point_back_to_playlist(self):
        hint = playlist_hint(b"#EXTM3U\nlisten.m3u\n", "audio/x-mpegurl", BASE)
        self.assertEqual(hint.kind, "playlist_loop")

    def test_playlist_oversize_fails_closed(self):
        hint = playlist_hint(b"A" * (MAX_PLAYLIST_BYTES + 1), "audio/x-mpegurl", BASE)
        self.assertEqual(hint.kind, "playlist_unbounded")

    def test_playlist_excessive_line_count_rejected(self):
        body = b"#EXTM3U\n" + b"#comment\n"*35
        hint = playlist_hint(body, "audio/x-mpegurl", BASE)
        self.assertEqual(hint.kind, "playlist_too_many_lines")

    def test_duplicate_same_target_is_not_a_multiple_source(self):
        hint = playlist_hint(
            b"#EXTM3U\nhttps://radio.example.org/live\nhttps://radio.example.org/live\n",
            "audio/x-mpegurl", BASE)
        self.assertEqual(hint.kind, "playlist_single_target")

    def test_m3u_uri_credentials_are_checked_by_probe_before_fetching(self):
        # The parser just describes untrusted text; the probe must validate it.
        hint = playlist_hint(b"#EXTM3U\nhttp://127.0.0.1/private\n",
                             "audio/x-mpegurl", BASE)
        self.assertEqual(hint.kind, "playlist_single_target")
        self.assertEqual(hint.target, "http://127.0.0.1/private")


if __name__ == "__main__":
    unittest.main()
