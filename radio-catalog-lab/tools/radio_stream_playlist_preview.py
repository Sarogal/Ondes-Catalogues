#!/usr/bin/env python3
"""Conservative M3U/PLS playlist resolution for the radio stream probe.

No network access in this module. HLS playlists never return a stream URL:
their segment/variant manifests need a separate, purpose-built validator.
All external URLs get rechecked by the caller's SSRF-aware transport.
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass

MAX_PLAYLIST_BYTES = 512
MAX_PLAYLIST_LINES = 32
MAX_PLAYLIST_ENTRIES = 8

@dataclass(frozen=True)
class PlaylistHint:
    kind: str
    target: str | None = None


def playlist_hint(body: bytes, content_type: str, current_url: str) -> PlaylistHint:
    if not isinstance(body, bytes) or len(body) > MAX_PLAYLIST_BYTES:
        return PlaylistHint("playlist_unbounded")
    if not isinstance(content_type, str) or len(content_type) > 250:
        return PlaylistHint("playlist_bad_content_type")
    mime = content_type.split(";", 1)[0].strip().lower()
    path = urllib.parse.urlsplit(current_url).path.lower()
    try:
        text = body.decode("utf-8-sig")
    except UnicodeError:
        # PLS/M3U files frequently use latin-1; this is for detection only.
        try:
            text = body.decode("latin-1")
        except UnicodeError:
            return PlaylistHint("playlist_bad_encoding")
    if mime in {"text/html", "application/json", "application/xml", "text/xml"} or (
        text.lstrip().lower().startswith(("<html", "<!doctype", "<?xml", "{"))
    ):
        return PlaylistHint("playlist_non_manifest_content")
    lines = [l.strip() for l in text.replace("\r\n", "\n").split("\n")]
    if len(lines) > MAX_PLAYLIST_LINES:
        return PlaylistHint("playlist_too_many_lines")
    hls = (path.endswith(".m3u8") or
           mime == "application/vnd.apple.mpegurl" or
           any(line.upper().startswith("#EXT-X-") for line in lines))
    if hls:
        # Do not download segments or master playlist child variants.
        return PlaylistHint("hls_manifest_pending")
    pls = (path.endswith(".pls") or "scpls" in mime or
           any(line.lower() == "[playlist]" for line in lines))
    m3u = (path.endswith(".m3u") or "mpegurl" in mime or
           any(line.upper().startswith("#EXTM3U") for line in lines))
    if not pls and not m3u:
        return PlaylistHint("playlist_unknown_format")
    entries = []
    for line in lines:
        if not line:
            continue
        if pls:
            match = re.fullmatch(r"File[1-9][0-9]*\s*=\s*(.+)", line, re.I)
            if match:
                entries.append(match.group(1).strip())
        elif not line.startswith("#"):
            entries.append(line)
        if len(entries) > MAX_PLAYLIST_ENTRIES:
            return PlaylistHint("playlist_too_many_targets")
    if not entries:
        return PlaylistHint("playlist_no_target")
    if len(set(entries)) != 1:
        return PlaylistHint("playlist_multiple_targets")
    target = urllib.parse.urljoin(current_url, entries[0])
    if target == current_url:
        return PlaylistHint("playlist_loop")
    if not target.startswith(("http://", "https://")):
        return PlaylistHint("playlist_invalid_target")
    return PlaylistHint("playlist_single_target", target)
