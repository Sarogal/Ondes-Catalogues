import io
import unittest
from unittest.mock import patch

from go_radio_v8_metadata_probe import read_icy, stream_title, MAX_INTERVAL, worker


def packet(text: bytes) -> bytes:
    size = (len(text) + 15) // 16
    return bytes([size]) + text.ljust(size * 16, b"\x00")


class MetadataProbeTest(unittest.TestCase):
    def test_artist_and_title(self):
        self.assertEqual(stream_title(b"StreamTitle='Metallica - One';")["raw"],
                         "Metallica - One")

    def test_apostrophe_and_legacy_encoding(self):
        result = stream_title("StreamTitle='Motörhead - Don't Let Daddy Kiss Me';".encode("cp1252"))
        self.assertEqual(result["raw"], "Motörhead - Don't Let Daddy Kiss Me")
        self.assertEqual(result["encoding"], "cp1252-fallback")

    def test_empty_then_positive(self):
        response = io.BytesIO(b"1234\x00" + b"1234" + packet(b"StreamTitle='Artist - Song';"))
        result = read_icy(response, 4)
        self.assertEqual(result["observation"], "icy_title_observed")
        self.assertEqual(result["blocks"], 2)

    def test_three_empty_blocks_not_absence(self):
        result = read_icy(io.BytesIO(b"1234\x00" * 3), 4)
        self.assertEqual(result["observation"], "icy_no_title_in_sample")

    def test_truncation_and_bound(self):
        self.assertEqual(read_icy(io.BytesIO(b"12"), 4)["observation"], "icy_sample_incomplete")
        self.assertEqual(read_icy(io.BytesIO(), MAX_INTERVAL + 1)["observation"],
                         "icy_interval_out_of_budget")

    def test_hard_timeout(self):
        import subprocess
        with patch("go_radio_v8_metadata_probe.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("probe", 18)):
            self.assertEqual(worker("https://example.org"), {"observation": "wall_timeout"})


if __name__ == "__main__":
    unittest.main()
