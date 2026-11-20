"""Offline tests for bounded, non-publishing continuous transport sampling."""
import unittest

from radio_stream_continuity_evidence import (
    MAX_OBSERVED_BYTES, MIN_SECONDS, observe_continuity,
)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Reader:
    def __init__(self, clock, chunks, interval=0.5):
        self.clock = clock
        self.chunks = list(chunks)
        self.interval = interval

    def read1(self, size):
        self.clock.t += self.interval
        if not self.chunks:
            return b""
        chunk = self.chunks.pop(0)
        if len(chunk) > size:
            self.chunks.insert(0, chunk[size:])
        return chunk[:size]


class ContinuityEvidenceTests(unittest.TestCase):
    def test_continuous_arrival_has_no_publication_approval(self):
        clock = Clock()
        reader = Reader(clock, [b"x" * 4096 for _ in range(18)], interval=0.5)
        result = observe_continuity(reader, b"ID3" + b"\0" * 509, clock=clock)
        self.assertEqual(result.state, "transport_sustained")
        self.assertGreaterEqual(result.elapsed_ms, MIN_SECONDS * 1000)
        self.assertGreaterEqual(result.observed_bytes, 4096)
        self.assertFalse(result.as_dict()["publicationAllowed"])

    def test_instant_large_static_payload_does_not_count_as_sustained(self):
        clock = Clock()
        reader = Reader(clock, [b"x" * 8192 for _ in range(128)], interval=0.0)
        result = observe_continuity(reader, b"ID3" + b"\0" * 509, clock=clock)
        self.assertEqual(result.state, "not_confirmed")
        self.assertEqual(result.reason, "byte_budget_reached")
        self.assertLessEqual(result.observed_bytes, MAX_OBSERVED_BYTES)

    def test_finite_content_length_not_falsely_classified_as_live(self):
        clock = Clock()
        result = observe_continuity(
            Reader(clock, [b"x" * 8192 for _ in range(20)]),
            b"ID3" + b"\0" * 509, content_length="120000", clock=clock)
        self.assertEqual(result.reason, "finite_content_length")
        self.assertEqual(result.read_chunks, 1)

    def test_early_end_does_not_count(self):
        clock = Clock()
        result = observe_continuity(
            Reader(clock, [b"x" * 4096], interval=1.0),
            b"ID3" + b"\0" * 509, clock=clock)
        self.assertEqual(result.reason, "stream_ended")

    def test_long_wait_without_sufficient_bytes_is_not_sustained(self):
        clock = Clock()
        result = observe_continuity(
            Reader(clock, [b"x" * 40] * 4, interval=2.5),
            b"ID3" + b"\0" * 509, clock=clock)
        self.assertEqual(result.state, "not_confirmed")
        self.assertEqual(result.reason, "time_budget_reached")

    def test_slow_stream_read_failure_is_not_published(self):
        clock = Clock()
        class Broken:
            def read1(self, size):
                raise TimeoutError("stream stalled")
        result = observe_continuity(Broken(), b"fLaC" + b"\0" * 100, clock=clock)
        self.assertEqual(result.reason, "stream_read_failed")
        self.assertFalse(result.as_dict()["publicationAllowed"])

    def test_absent_initial_signature_is_not_confirmed(self):
        clock = Clock()
        result = observe_continuity(Reader(clock, [b"x" * 4096]), b"", clock=clock)
        self.assertEqual(result.reason, "empty_initial_sample")


if __name__ == "__main__":
    unittest.main()
