#!/usr/bin/env python3
"""Conservative MPEG-audio and ADTS frame-chain evidence (no decoding).

Pure byte parser, no network or external subprocess. Three full consecutive
frames are required. A valid frame chain does NOT prove audible/music content,
continuous live radio, station identity, or publication eligibility.
"""
from __future__ import annotations

MAX_FRAME_SAMPLE_BYTES = 65536
MIN_FRAME_CHAIN = 3
MAX_FRAME_SEARCH = 4096

_MPEG1_L1 = (0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448, 0)
_MPEG1_L2 = (0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384, 0)
_MPEG1_L3 = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0)
_MPEG2_L1 = (0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256, 0)
_MPEG2_L23 = (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0)
_SAMPLE_RATES = {
    0: (11025, 12000, 8000),
    2: (22050, 24000, 16000),
    3: (44100, 48000, 32000),
}


def mpeg_header(data: bytes, offset: int) -> tuple[int, tuple] | None:
    if offset < 0 or offset + 4 > len(data):
        return None
    a, b, c, _d = data[offset:offset + 4]
    if a != 0xFF or (b & 0xE0) != 0xE0:
        return None
    version = (b >> 3) & 3
    layer = (b >> 1) & 3
    rate_index = (c >> 2) & 3
    bitrate_index = c >> 4
    if version == 1 or layer == 0 or rate_index == 3 or bitrate_index in (0, 15):
        return None
    sample_rate = _SAMPLE_RATES[version][rate_index]
    if version == 3:
        bitrate = (_MPEG1_L1 if layer == 3 else
                   _MPEG1_L2 if layer == 2 else _MPEG1_L3)[bitrate_index]
    else:
        bitrate = (_MPEG2_L1 if layer == 3 else _MPEG2_L23)[bitrate_index]
    padding = (c >> 1) & 1
    if layer == 3:
        frame_bytes = (12 * bitrate * 1000 // sample_rate + padding) * 4
    elif layer == 2 or version == 3:
        frame_bytes = 144 * bitrate * 1000 // sample_rate + padding
    else:
        frame_bytes = 72 * bitrate * 1000 // sample_rate + padding
    if not 24 <= frame_bytes <= 4096:
        return None
    return frame_bytes, ("mpeg_audio", version, layer, sample_rate)


def adts_header(data: bytes, offset: int) -> tuple[int, tuple] | None:
    if offset < 0 or offset + 7 > len(data):
        return None
    a, b, c, d, e, f, _g = data[offset:offset + 7]
    if a != 0xFF or b & 0xF6 != 0xF0:
        return None
    profile = (c >> 6) & 3
    frequency = (c >> 2) & 15
    channel = ((c & 1) << 2) | (d >> 6)
    if profile == 3 or frequency > 12 or not 1 <= channel <= 7:
        return None
    header_len = 7 if b & 1 else 9
    frame_bytes = ((d & 3) << 11) | (e << 3) | (f >> 5)
    if not header_len <= frame_bytes <= 8191 or offset + header_len > len(data):
        return None
    return frame_bytes, ("aac_adts", frequency, channel, profile)


def _after_id3(data: bytes) -> int | None:
    if not data.startswith(b"ID3"):
        return 0
    if len(data) < 10 or data[3] not in (2, 3, 4):
        return None
    sizes = data[6:10]
    if any(x & 0x80 for x in sizes):
        return None
    tag_bytes = (sizes[0] << 21) | (sizes[1] << 14) | (sizes[2] << 7) | sizes[3]
    return 10 + tag_bytes + (10 if data[3] == 4 and data[5] & 0x10 else 0)


def analyze_frame_chain(data: bytes) -> dict:
    """Return only a bounded evidence summary, never raw audio or a URL."""
    result = {"state": "not_confirmed", "codec": "unconfirmed",
              "frameCount": 0, "sampleBytes": 0, "publicationAllowed": False}
    if not isinstance(data, bytes) or not data or len(data) > MAX_FRAME_SAMPLE_BYTES:
        return result
    result["sampleBytes"] = len(data)
    start = _after_id3(data)
    if start is None or start >= len(data):
        return result
    for offset in range(start, min(len(data) - 6, start + MAX_FRAME_SEARCH)):
        for parser in (mpeg_header, adts_header):
            first = parser(data, offset)
            if first is None:
                continue
            frame_len, signature = first
            end = offset + frame_len
            if end > len(data):
                continue
            frames = 1
            while frames < MIN_FRAME_CHAIN:
                following = parser(data, end)
                if following is None or following[1] != signature:
                    break
                frame_len = following[0]
                end += frame_len
                if end > len(data):
                    break
                frames += 1
            if frames >= MIN_FRAME_CHAIN:
                return {"state": "frame_chain", "codec": signature[0],
                        "frameCount": frames, "sampleBytes": len(data),
                        "publicationAllowed": False}
    return result
