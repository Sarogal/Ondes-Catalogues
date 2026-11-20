#!/usr/bin/env python3
"""Non-certifying, bounded *transport continuity* evidence for radio streams.

This observes repeated bytes arriving over time, not successful audio decoding.
It must NEVER be interpreted as technical qualification or publication approval.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from radio_stream_frame_chain import MAX_FRAME_SAMPLE_BYTES, analyze_frame_chain
from radio_stream_decode_evidence import decode_audio_prefix

MIN_SECONDS = 6.0
MAX_SECONDS = 10.0
MAX_OBSERVED_BYTES = 512 * 1024
MIN_OBSERVED_BYTES = 4096
MAX_READ_CHUNK = 8192
MAX_READ_CHUNKS = 1024


@dataclass(frozen=True)
class ContinuityEvidence:
    state: str
    reason: str
    elapsed_ms: int
    observed_bytes: int
    read_chunks: int
    frame_evidence: dict | None = None
    decode_evidence: dict | None = None

    def as_dict(self) -> dict:
        report = {
            "state": self.state,
            "reason": self.reason,
            "elapsedMs": self.elapsed_ms,
            "observedBytes": self.observed_bytes,
            "readChunks": self.read_chunks,
            "publicationAllowed": False,
        }
        if self.frame_evidence is not None:
            report["frameEvidence"] = self.frame_evidence
        if self.decode_evidence is not None:
            report["decodeEvidence"] = self.decode_evidence
        return report


def observe_continuity(
    response: object,
    initial_bytes: bytes,
    *,
    content_length: str | None = None,
    clock: Callable[[], float] | None = None,
    experimental_decode: bool = False,
) -> ContinuityEvidence:
    """Observe the SAME open HTTP connection after a recognizable audio header.

    No payload or station URL is returned; requests are handled by the separate
    DNS-pinned transport. This function cannot prove decoding or that a radio
    is live; a slow non-radio file can also last six seconds.
    """
    if clock is None:
        clock = time.monotonic
    start = clock()
    size = len(initial_bytes)
    chunks = 1 if size else 0
    frame_sample = bytearray(initial_bytes[:MAX_FRAME_SAMPLE_BYTES])

    def result(state: str, reason: str) -> ContinuityEvidence:
        return ContinuityEvidence(
            state=state,
            reason=reason,
            elapsed_ms=max(0, round((clock() - start) * 1000)),
            observed_bytes=size,
            read_chunks=chunks,
            frame_evidence=analyze_frame_chain(bytes(frame_sample)),
            decode_evidence=(
                decode_audio_prefix(bytes(frame_sample))
                if experimental_decode and state == "transport_sustained"
                else None
            ),
        )

    if not isinstance(initial_bytes, bytes) or not initial_bytes:
        return result("not_confirmed", "empty_initial_sample")
    if content_length not in (None, ""):
        # Never mistake a finite audio file returned by HTTP for a live stream.
        return result("not_confirmed", "finite_content_length")
    if size > MAX_OBSERVED_BYTES:
        return result("not_confirmed", "initial_sample_too_large")
    while True:
        elapsed = clock() - start
        if (elapsed >= MIN_SECONDS and size >= MIN_OBSERVED_BYTES and chunks >= 2):
            return result("transport_sustained", "repeated_bytes_over_time")
        if elapsed >= MAX_SECONDS:
            return result("not_confirmed", "time_budget_reached")
        if size >= MAX_OBSERVED_BYTES:
            return result("not_confirmed", "byte_budget_reached")
        if chunks >= MAX_READ_CHUNKS:
            return result("not_confirmed", "chunk_budget_reached")
        try:
            chunk = response.read1(min(MAX_READ_CHUNK, MAX_OBSERVED_BYTES - size))
        except (OSError, TimeoutError):
            return result("not_confirmed", "stream_read_failed")
        if not isinstance(chunk, bytes) or not chunk:
            return result("not_confirmed", "stream_ended")
        if len(chunk) > MAX_READ_CHUNK or size + len(chunk) > MAX_OBSERVED_BYTES:
            return result("not_confirmed", "invalid_read_size")
        size += len(chunk)
        chunks += 1
        if len(frame_sample) < MAX_FRAME_SAMPLE_BYTES:
            frame_sample.extend(chunk[:MAX_FRAME_SAMPLE_BYTES - len(frame_sample)])
