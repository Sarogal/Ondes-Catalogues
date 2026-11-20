"""Decoder safety and opt-in behavior tests (subprocess mocked, no network)."""
import subprocess
import unittest
from unittest.mock import patch

from radio_stream_decode_evidence import (
    MAX_INPUT_BYTES, decode_audio_prefix, _detect_demuxer,
)


def mp3_sample():
    return b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\0" * 4096


class DecoderEvidenceTests(unittest.TestCase):
    def test_unknown_html_mime_and_unbounded_input_are_never_decoded(self):
        for content in (b"<html>" + b" " * 1000, b"\xff" * 800,
                        mp3_sample() + b"\0" * MAX_INPUT_BYTES):
            with patch("radio_stream_decode_evidence.subprocess.run") as runner:
                out = decode_audio_prefix(content)
            self.assertEqual(out["state"], "not_decoded")
            self.assertFalse(out["publicationAllowed"])
            runner.assert_not_called()

    def test_stream_misaligned_first_frame_still_has_demuxer(self):
        from radio_stream_frame_chain import mpeg_header
        header = bytes((0xFF, 0xFB, 0x90, 0x64))
        frame = header + bytes(1) * (mpeg_header(header, 0)[0] - 4)
        self.assertEqual(_detect_demuxer(b"xyz" + frame * 3), "mp3")

    def test_codec_hint_is_conservative(self):
        self.assertEqual(_detect_demuxer(mp3_sample()), "mp3")
        self.assertEqual(_detect_demuxer(b"fLaC" + b"\0" * 1000), "flac")
        self.assertEqual(_detect_demuxer(
            b"OggS\0" + b"OpusHead" + b"\0" * 1024), "ogg")
        self.assertIsNone(_detect_demuxer(b"random audio/mpeg" * 100))

    @patch("radio_stream_decode_evidence.sys.platform", "linux")
    @patch("radio_stream_decode_evidence.shutil.which", return_value=None)
    def test_missing_decoder_remains_pending(self, which):
        out = decode_audio_prefix(mp3_sample())
        self.assertEqual(out["state"], "decoder_unavailable")
        self.assertFalse(out["publicationAllowed"])

    @patch("radio_stream_decode_evidence.sys.platform", "linux")
    @patch("radio_stream_decode_evidence.shutil.which", return_value="/usr/bin/ffmpeg")
    @patch("radio_stream_decode_evidence.subprocess.run")
    def test_real_pcm_bytes_are_only_experimental_evidence(self, run, which):
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b"\0" * 8192)
        out = decode_audio_prefix(mp3_sample())
        self.assertEqual(out["state"], "decoded_pcm")
        self.assertEqual(out["pcmBytes"], 8192)
        self.assertFalse(out["publicationAllowed"])
        call = run.call_args
        cmd = call.args[0]
        self.assertIn("-protocol_whitelist", cmd)
        self.assertEqual(cmd[cmd.index("-protocol_whitelist") + 1], "pipe")
        self.assertEqual(cmd[cmd.index("-frames:a") + 1], "3")
        self.assertEqual(cmd[cmd.index("-i") + 1], "pipe:0")
        self.assertEqual(cmd[-1], "pipe:1")
        self.assertEqual(call.kwargs["timeout"], 4)
        self.assertIsNotNone(call.kwargs["preexec_fn"])
        self.assertEqual(call.kwargs["stderr"], subprocess.DEVNULL)
        self.assertEqual(call.kwargs["input"], mp3_sample())
        self.assertEqual(call.kwargs["env"].get("HOME"), "/nonexistent")

    @patch("radio_stream_decode_evidence.sys.platform", "linux")
    @patch("radio_stream_decode_evidence.shutil.which", return_value="/usr/bin/ffmpeg")
    @patch("radio_stream_decode_evidence.subprocess.run")
    def test_subprocess_errors_do_not_count_as_decoded(self, run, which):
        run.side_effect = subprocess.TimeoutExpired("ffmpeg", 4)
        out = decode_audio_prefix(mp3_sample())
        self.assertEqual(out["state"], "decoder_failed_or_timed_out")
        self.assertEqual(out["pcmBytes"], 0)
        run.side_effect = None
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=b"\0" * 8192)
        self.assertEqual(decode_audio_prefix(mp3_sample())["state"], "not_decoded")
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b"\0" * 10)
        self.assertEqual(decode_audio_prefix(mp3_sample())["state"], "not_decoded")

    @patch("radio_stream_decode_evidence.sys.platform", "win32")
    def test_non_linux_platform_is_not_used(self):
        out = decode_audio_prefix(mp3_sample())
        self.assertEqual(out["state"], "decoder_not_supported")

    @patch("radio_stream_decode_evidence.shutil.which", return_value=None)
    def test_decoder_never_returns_raw_bytes_or_stream_urls(self, which):
        out = decode_audio_prefix(mp3_sample())
        self.assertNotIn("bytes_payload", out)
        self.assertFalse(any(isinstance(x, bytes) for x in out.values()))


if __name__ == "__main__":
    unittest.main()
