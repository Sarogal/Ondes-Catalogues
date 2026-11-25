import unittest
from go_radio_v8_hls_id3_probe import playlist_target, id3_evidence


def syncsafe(n):
    return bytes((n >> shift) & 127 for shift in (21, 14, 7, 0))


def frame(name, value):
    raw = b"\x03" + value.encode()
    return name + len(raw).to_bytes(4, "big") + b"\x00\x00" + raw


class HlsId3Tests(unittest.TestCase):
    def test_latest_complete_segment(self):
        text = b"#EXTM3U\n#EXTINF:5,\na.aac\n#EXTINF:5,\nb.aac\n"
        self.assertEqual(playlist_target(text, "https://example.org/live/list.m3u8"),
                         ("https://example.org/live/b.aac", "media_segment"))

    def test_encrypted_not_probed(self):
        text = b'#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key"\n#EXTINF:5,\na.aac\n'
        self.assertEqual(playlist_target(text, "https://example.org/list.m3u8")[1],
                         "encrypted_hls_not_probed")

    def test_master_audio(self):
        text = b'#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,URI="audio.m3u8"\n#EXT-X-STREAM-INF:BANDWIDTH=1000\nvideo.m3u8\n'
        self.assertEqual(playlist_target(text, "https://example.org/list.m3u8"),
                         ("https://example.org/audio.m3u8", "master_audio"))

    def test_direct_id3_pair(self):
        frames = frame(b"TPE1", "Motörhead") + frame(b"TIT2", "Ace of Spades")
        tag = b"ID3\x03\x00\x00" + syncsafe(len(frames)) + frames
        evidence = id3_evidence(tag)
        self.assertTrue(evidence["artist_title_pair_observed"])
        self.assertEqual(evidence["text_frames"][0]["TPE1"], "Motörhead")
        self.assertFalse(id3_evidence(tag[:-1])["artist_title_pair_observed"])

    def test_no_pair_not_absence(self):
        self.assertEqual(id3_evidence(b"\xff\xfb\x00\x00")["complete_id3_tags"], 0)


if __name__ == "__main__":
    unittest.main()
