#!/usr/bin/env python3
"""Offline unit tests for bounded audio-decoder evidence and status safeguards."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_open_radio_decoder import decode_prefix, parse_ffmpeg_time


class AudioDecoderEvidenceTests(unittest.TestCase):
    def test_progress_duration(self):
        text = "out_time=00:00:03.000\nprogress=continue\nout_time=00:00:06.019\n"
        self.assertAlmostEqual(parse_ffmpeg_time(text), 6.019)

    def test_safe_decoder_result_remains_candidate(self):
        with patch("probe_open_radio_decoder.shutil.which", return_value="/usr/bin/ffmpeg"), \
             patch("probe_open_radio_decoder.subprocess.run", return_value=SimpleNamespace(
                returncode=0, stdout="out_time=00:00:06.005\n", stderr=""
             )):
            result = decode_prefix("https://radio.example.org/live")
        self.assertTrue(result["audio_decoder_passed"])
        self.assertFalse(result["publication_allowed"])
        self.assertEqual(result["state"], "candidate")

    def test_decode_rejects_incomplete_data(self):
        with patch("probe_open_radio_decoder.shutil.which", return_value="/usr/bin/ffmpeg"), \
             patch("probe_open_radio_decoder.subprocess.run", return_value=SimpleNamespace(
                returncode=0, stdout="out_time=00:00:02.000\n", stderr=""
             )):
            result = decode_prefix("https://radio.example.org/live")
        self.assertFalse(result["audio_decoder_passed"])

    def test_refuses_private_urls_and_no_ffmpeg(self):
        self.assertFalse(decode_prefix("http://127.0.0.1/live")["audio_decoder_passed"])
        with patch("probe_open_radio_decoder.shutil.which", return_value=None):
            result = decode_prefix("https://radio.example.org/live")
        self.assertFalse(result["audio_decoder_passed"])
        self.assertEqual(result["reason"], "ffmpeg_missing")


if __name__ == "__main__":
    unittest.main()
