#!/usr/bin/env python3
"""Read-only HLS manifest evidence (NOT playlist playback or publication).

Inspects at most 512 bytes already fetched by the DNS-pinned audio probe.
NEVER follows playlist variants or segment URIs, and never returns a URL.
Recognizing a plausible live playlist is not proof of audio or availability.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

MAX_HLS_BYTES = 4096
MAX_HLS_LINES = 128
MAX_HLS_SEGMENTS = 12
MAX_HLS_VARIANTS = 8


def inspect_hls_manifest(data: bytes, content_type: str, url: str) -> dict:
    output = {
        "kind": "not_hls",
        "segmentCount": 0,
        "variantCount": 0,
        "liveCandidate": False,
        "publicationAllowed": False,
    }
    if not isinstance(data, bytes) or len(data) >= MAX_HLS_BYTES:
        output["kind"] = "manifest_oversized"
        return output
    if not isinstance(content_type, str) or len(content_type) > 250:
        output["kind"] = "invalid_content_type"
        return output
    if not isinstance(url, str) or len(url) > 2048:
        output["kind"] = "invalid_source_url"
        return output
    try:
        urlsplit(url)
        value = data.decode("utf-8-sig")
    except (ValueError, UnicodeError):
        output["kind"] = "manifest_invalid_encoding"
        return output

    lines = [line.strip() for line in value.replace("\r\n", "\n").split("\n")]
    if len(lines) > MAX_HLS_LINES:
        output["kind"] = "manifest_too_many_lines"
        return output
    if not lines or lines[0] != "#EXTM3U":
        return output
    is_hls = any(line.startswith("#EXT-X-") for line in lines)
    if not is_hls:
        return output
    # A partial network read must not be treated as a trustworthy manifest.
    if data and not data.endswith(b"\n"):
        output["kind"] = "manifest_incomplete"
        return output
    tags = [line for line in lines if line.startswith("#EXT-X-")]
    unsafe_tags = (
        "#EXT-X-KEY:", "#EXT-X-SESSION-KEY:", "#EXT-X-MAP:",
        "#EXT-X-BYTERANGE:", "#EXT-X-PART:", "#EXT-X-PRELOAD-HINT:",
        "#EXT-X-DEFINE:", "#EXT-X-SKIP:", "#EXT-X-I-FRAME-STREAM-INF:",
        "#EXT-X-MEDIA:",
    )
    if any(line.startswith(unsafe_tags) for line in tags):
        output["kind"] = "manifest_advanced_or_encrypted"
        return output
    segments = [line for line in lines if line and not line.startswith("#")]
    variants = sum(line.startswith("#EXT-X-STREAM-INF:") for line in tags)
    output["variantCount"] = variants
    if variants:
        # Variants are not chosen arbitrarily; no nested request is made.
        output["kind"] = (
            "master_single_variant_pending" if variants == 1 and len(segments) == 1
            else "master_ambiguous_pending"
        )
        return output
    if len(segments) > MAX_HLS_SEGMENTS:
        output["kind"] = "manifest_too_many_segments"
        return output
    output["segmentCount"] = len(segments)
    if "#EXT-X-ENDLIST" in tags:
        output["kind"] = "media_finite_playlist"
        return output
    target_duration = [line for line in tags if line.startswith("#EXT-X-TARGETDURATION:")]
    media_sequences = [line for line in tags if line.startswith("#EXT-X-MEDIA-SEQUENCE:")]
    extinf = [line for line in lines if line.startswith("#EXTINF:")]
    if len(target_duration) != 1 or len(media_sequences) > 1:
        output["kind"] = "media_incomplete_metadata"
        return output
    raw_duration = target_duration[0].split(":", 1)[1]
    if not re.fullmatch(r"[1-9][0-9]{0,3}", raw_duration) or int(raw_duration) > 3600:
        output["kind"] = "media_invalid_duration"
        return output
    if media_sequences and not re.fullmatch(r"[0-9]{1,14}", media_sequences[0].split(":", 1)[1]):
        output["kind"] = "media_invalid_sequence"
        return output
    if len(segments) < 2 or len(extinf) != len(segments):
        output["kind"] = "media_incomplete_segments"
        return output
    # Disallow embedded controls and unsupported URI syntax; do NOT access URIs.
    for segment in segments:
        if (len(segment) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in segment)
            or segment.startswith(("//", "data:", "file:", "ftp:"))):
            output["kind"] = "media_unsupported_reference"
            return output
    output["kind"] = "live_manifest_candidate"
    output["liveCandidate"] = True
    return output
