#!/usr/bin/env python3
"""Experimental sandboxed decoder evidence for bounded radio samples.

This opt-in FFmpeg path runs on Linux CI only, does not fetch network URLs,
has a strict pipe-only protocol whitelist, time/CPU/memory bounds, and never
writes PCM or raw audio to an artifact. It is NOT a publication certificate.
"""
from __future__ import annotations

import shutil
import subprocess
import sys

MAX_INPUT_BYTES = 65536
MIN_PCM_OUTPUT_BYTES = 1024
MAX_PCM_OUTPUT_BYTES = 65536
DECODE_TIMEOUT_SECONDS = 4


def _detect_demuxer(data: bytes) -> str | None:
    from radio_stream_frame_chain import adts_header, mpeg_header, analyze_frame_chain

    if data.startswith(b"ID3") or mpeg_header(data, 0):
        return "mp3"
    if adts_header(data, 0):
        return "aac"
    # A genuine continuous stream can begin mid-frame; reuse the bounded
    # multi-frame parser instead of assuming the first byte is a sync word.
    frame = analyze_frame_chain(data)
    if frame["state"] == "frame_chain":
        return "mp3" if frame["codec"] == "mpeg_audio" else "aac"
    if data.startswith(b"OggS") and any(
        x in data[:512] for x in (b"OpusHead", b"\x01vorbis", b"Speex   ", b"fLaC")
    ):
        return "ogg"
    if data.startswith(b"fLaC"):
        return "flac"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "wav"
    return None


def _restricted_linux_process() -> None:
    """Resource limits applied in the child before executing FFmpeg."""
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))


def decode_audio_prefix(data: bytes) -> dict:
    """Decode a tiny PCM prefix and return only counts/diagnostic state."""
    evidence = {
        "state": "not_decoded",
        "demuxer": "",
        "pcmBytes": 0,
        "inputBytes": 0,
        "publicationAllowed": False,
    }
    if not isinstance(data, bytes) or not 512 <= len(data) <= MAX_INPUT_BYTES:
        return evidence
    evidence["inputBytes"] = len(data)
    demuxer = _detect_demuxer(data)
    if demuxer is None:
        return evidence
    evidence["demuxer"] = demuxer
    if not sys.platform.startswith("linux"):
        evidence["state"] = "decoder_not_supported"
        return evidence
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        evidence["state"] = "decoder_unavailable"
        return evidence

    args = [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
        "-protocol_whitelist", "pipe", "-probesize", "65536",
        "-analyzeduration", "500000", "-f", demuxer,
        "-i", "pipe:0", "-map", "0:a:0",
        "-frames:a", "3", "-ac", "1", "-ar", "8000",
        "-f", "s16le", "pipe:1",
    ]
    try:
        completed = subprocess.run(
            args,
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=DECODE_TIMEOUT_SECONDS,
            preexec_fn=_restricted_linux_process,
            env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"},
        )
    except (subprocess.TimeoutExpired, OSError, ValueError):
        evidence["state"] = "decoder_failed_or_timed_out"
        return evidence

    decoded_size = len(completed.stdout)
    if (completed.returncode == 0 and
            MIN_PCM_OUTPUT_BYTES <= decoded_size <= MAX_PCM_OUTPUT_BYTES):
        evidence["state"] = "decoded_pcm"
        evidence["pcmBytes"] = decoded_size
    return evidence
