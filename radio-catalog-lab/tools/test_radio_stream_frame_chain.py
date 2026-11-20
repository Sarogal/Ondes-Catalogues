"""Synthetic bounded MP3/MPEG and AAC ADTS frame-chain tests (no network)."""
import unittest

from radio_stream_frame_chain import (
    MAX_FRAME_SAMPLE_BYTES, analyze_frame_chain, mpeg_header, adts_header,
)


def mp3_frame(bitrate_index=9):
    # MPEG-1 layer III, 44100 Hz, payload does not need to be decodable.
    header = bytes((0xFF, 0xFB, (bitrate_index << 4), 0x64))
    frame_len = mpeg_header(header, 0)[0]
    return header + b"\x00" * (frame_len - 4)


def adts_frame(frame_len=100, frequency=4, channel=2):
    # MPEG-4 AAC-LC ADTS, seven-byte header, 44.1 kHz stereo.
    header = bytes((
        0xFF, 0xF1,
        0x40 | (frequency << 2) | ((channel >> 2) & 1),
        ((channel & 3) << 6) | ((frame_len >> 11) & 3),
        (frame_len >> 3) & 255,
        ((frame_len & 7) << 5) | 0x1F,
        0xFC,
    ))
    return header + b"\x00" * (frame_len - 7)


class RadioFrameChainTests(unittest.TestCase):
    def test_three_consecutive_mp3_frames(self):
        data = mp3_frame() * 3
        report = analyze_frame_chain(data)
        self.assertEqual(report["state"], "frame_chain")
        self.assertEqual(report["codec"], "mpeg_audio")
        self.assertEqual(report["frameCount"], 3)
        self.assertFalse(report["publicationAllowed"])
        self.assertNotIn("payload", report)

    def test_three_consecutive_adts_frames(self):
        data = adts_frame() * 3
        report = analyze_frame_chain(data)
        self.assertEqual(report["state"], "frame_chain")
        self.assertEqual(report["codec"], "aac_adts")

    def test_vbr_mp3_with_changing_bitrates(self):
        data = mp3_frame(9) + mp3_frame(11) + mp3_frame(7)
        self.assertEqual(analyze_frame_chain(data)["state"], "frame_chain")

    def test_id3_tag_skip_exact_synchsafe_length(self):
        prefix = b"ID3\x04\x00\x00\x00\x00\x01\x00" + b"\x00" * 128
        self.assertEqual(analyze_frame_chain(prefix + mp3_frame() * 3)["state"],
                         "frame_chain")

    def test_one_or_two_headers_are_insufficient(self):
        for data in (mp3_frame(), mp3_frame() * 2,
                     adts_frame() * 2, b"ID3\x04\x00\x00" + b"\0" * 50):
            with self.subTest(size=len(data)):
                self.assertEqual(analyze_frame_chain(data)["state"], "not_confirmed")

    def test_false_or_truncated_frame_boundaries(self):
        good = mp3_frame() * 3
        broken = good[:len(mp3_frame()) * 2] + b"randomdata"
        self.assertEqual(analyze_frame_chain(broken)["state"], "not_confirmed")
        self.assertEqual(analyze_frame_chain(good[:-1])["state"], "not_confirmed")
        adts = adts_frame() * 3
        self.assertEqual(analyze_frame_chain(adts[:-1])["state"], "not_confirmed")

    def test_corrupt_reserved_headers_are_not_accepted(self):
        for payload in (
            b"\xff\xfb\x00\x64" * 500,
            b"\xff\xe9\xff\x64" * 500,
            b"\xff\xf1\xfc\x80\x0c\x9f\xfc" * 60,
            b"\x00" * 7000,
        ):
            with self.subTest(payload=payload[:4]):
                self.assertEqual(analyze_frame_chain(payload)["state"], "not_confirmed")

    def test_mpeg_and_adts_header_metadata(self):
        self.assertEqual(mpeg_header(mp3_frame(), 0)[1][0], "mpeg_audio")
        self.assertEqual(adts_header(adts_frame(), 0)[1][0], "aac_adts")
        self.assertIsNone(adts_header(b"\xff\xf1\x50", 0))

    def test_wrong_id3_size_remains_unconfirmed(self):
        prefix = b"ID3\x04\x00\x00\x00\x00\x7f\x7f"
        self.assertEqual(analyze_frame_chain(prefix + mp3_frame() * 3)["state"],
                         "not_confirmed")

    def test_size_budget_and_no_payload_leak(self):
        huge = mp3_frame() * 200
        self.assertGreater(len(huge), MAX_FRAME_SAMPLE_BYTES)
        result = analyze_frame_chain(huge)
        self.assertEqual(result["state"], "not_confirmed")
        self.assertEqual(result["sampleBytes"], 0)
        self.assertFalse(result["publicationAllowed"])

    def test_noise_and_html_do_not_confirm(self):
        for data in (b"not audio" * 100, b"<html>oops</html>",
                     b"OggS" + b"OpusHead" + b"\x00" * 8000):
            self.assertEqual(analyze_frame_chain(data)["state"], "not_confirmed")


if __name__ == "__main__":
    unittest.main()
