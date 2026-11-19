#!/usr/bin/env python3
"""Grosses Ondes real-logo PILOT: explicit, bounded, non-publishing HTTPS probe.

Default mode is read-only and makes ZERO network calls. --fetch must be
explicit, requires Pillow for a real image decode, and writes evidence only to
a NEW local output directory. Never writes the app's cache, a central catalog,
release files, legacy data, signatures or an approved SHA descriptor.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import warnings
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

MAX_LOGO_BYTES = 2 * 1024 * 1024
MAX_PILOT_OBJECTS = 8
GO_ID_RE = re.compile(r"^go-station-[0-9]{6,}$")
DNS_RE = re.compile(r"^[a-z0-9.-]{3,253}$")
MIME_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


def checked_https_url(url: str, expected_host: str) -> tuple[str, str]:
    if not isinstance(url, str) or any(ord(char) < 33 for char in url):
        raise ValueError("Untrusted image URL")
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if (parts.scheme != "https" or not host or
                parts.username or parts.password or parts.fragment or
                parts.port not in (None, 443) or
                not DNS_RE.fullmatch(host) or host.startswith(".") or
                host.endswith(".") or ".." in host or
                host != expected_host or
                host in {"localhost", "localhost.localdomain"} or
                host.endswith((".local", ".localhost")) or
                host.endswith(".radcap.ru") or host == "radcap.ru"):
            raise ValueError("HTTPS/host safety check failed")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError("Literal IP host forbidden")
        if len(url) > 1500 or not parts.path.startswith("/"):
            raise ValueError("Invalid image path")
        return host, parts.path + ("?" + parts.query if parts.query else "")
    except (ValueError, TypeError) as exc:
        raise ValueError("Unsafe pilot HTTPS URL") from exc


def plan_pilot(pilot: dict, staging: dict, reuse_map: dict) -> list[dict]:
    if (not isinstance(pilot, dict) or pilot.get("schema_version") != 1 or
            not isinstance(pilot.get("entries"), list) or
            not 1 <= len(pilot["entries"]) <= MAX_PILOT_OBJECTS):
        raise ValueError("Pilot must contain 1..8 explicitly selected URLs")
    if (not isinstance(staging, dict) or not isinstance(staging.get("stations"), list) or
            not isinstance(reuse_map, dict) or not isinstance(reuse_map.get("station_logos"), list)):
        raise ValueError("Invalid source snapshots")
    stages = {}
    for s in staging["stations"]:
        if not isinstance(s, dict) or not GO_ID_RE.fullmatch(str(s.get("go_station_id", ""))):
            raise ValueError("Invalid GO station in staging")
        if s["go_station_id"] in stages:
            raise ValueError("Duplicate GO station in staging")
        stages[s["go_station_id"]] = s
    reuse = {}
    for r in reuse_map["station_logos"]:
        if not isinstance(r, dict) or not GO_ID_RE.fullmatch(str(r.get("go_station_id", ""))):
            raise ValueError("Invalid reuse-map identity")
        if r["go_station_id"] in reuse:
            raise ValueError("Duplicate reuse-map identity")
        reuse[r["go_station_id"]] = r
    if set(stages) != set(reuse):
        raise ValueError("Stage/reuse IDs differ, refusing pilot")
    used_ids = set()
    used_urls = set()
    planned = []
    for entry in pilot["entries"]:
        if not isinstance(entry, dict):
            raise ValueError("Invalid pilot entry")
        url = entry.get("source_url")
        host = entry.get("allowed_host")
        ids = entry.get("go_station_ids")
        if (not isinstance(host, str) or host != host.lower() or
                not isinstance(ids, list) or not ids or
                len(ids) != len(set(ids)) or not isinstance(url, str)):
            raise ValueError("Malformed pilot source selection")
        checked_https_url(url, host)
        if url in used_urls:
            raise ValueError("Duplicate pilot URL, group stations in one entry")
        used_urls.add(url)
        for go_id in ids:
            if not isinstance(go_id, str) or go_id not in stages:
                raise ValueError("Unknown pilot GO identity")
            if go_id in used_ids:
                raise ValueError("Station assigned more than one pilot logo")
            used_ids.add(go_id)
            station = stages[go_id]
            reuse_row = reuse[go_id]
            if (station.get("status", {}).get("state") != "active" or
                    url not in reuse_row.get("logo_source_urls", []) or
                    not set(reuse_row.get("legacy_station_ids", [])).issubset(
                        set(station.get("legacy_aliases", [])))):
                raise ValueError("Source/identity does not match active historical station")
        planned.append({
            "source_url": url,
            "allowed_host": host,
            "go_station_ids": sorted(ids),
            "source_status": "historical_url_only_not_editorially_approved",
        })
    return sorted(planned, key=lambda x: x["source_url"])


def fetch_strict_https(url: str, expected_host: str) -> tuple[bytes, str]:
    """Pin a public DNS answer BEFORE TLS connection, no redirects or proxies."""
    host, path = checked_https_url(url, expected_host)
    answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    addresses = sorted(set(info[4][0] for info in answers))
    if not addresses:
        raise ValueError("No DNS answers")
    for value in addresses:
        address = ipaddress.ip_address(value.split("%", 1)[0])
        if not address.is_global:
            raise ValueError("Private/reserved DNS answer refused")

    class PinnedConnection(http.client.HTTPSConnection):
        def connect(self):
            last_error = None
            for address in addresses:
                try:
                    raw = socket.create_connection((address, 443), timeout=12)
                    try:
                        self.sock = self._context.wrap_socket(
                            raw, server_hostname=host,
                        )
                    except Exception:
                        raw.close()
                        raise
                    return
                except (OSError, ssl.SSLError) as exc:
                    last_error = exc
            raise OSError("No verified public HTTPS endpoint") from last_error

    connection = PinnedConnection(host, 443, timeout=12, context=ssl.create_default_context())
    try:
        connection.request("GET", path, headers={
            "Accept": "image/png,image/jpeg,image/webp",
            "User-Agent": "GrossesOndes-PilotLogoAudit/1.0",
            "Connection": "close",
        })
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("Non-200 image response (redirects prohibited)")
        mime = (response.getheader("Content-Type") or "").split(";", 1)[0].strip().lower()
        if mime not in MIME_TYPES.values():
            raise ValueError("Unexpected HTTP image MIME type")
        length = response.getheader("Content-Length")
        if length is not None and (not length.isdecimal() or int(length) > MAX_LOGO_BYTES):
            raise ValueError("Oversized HTTP image")
        data = response.read(MAX_LOGO_BYTES + 1)
        if not data or len(data) > MAX_LOGO_BYTES:
            raise ValueError("Empty or oversized image body")
        if length is not None and len(data) != int(length):
            raise ValueError("Truncated HTTP image")
        return data, mime
    finally:
        connection.close()


def decode_image(data: bytes) -> tuple[str, int, int]:
    """Require Pillow to actually decode, not merely recognize PNG magic."""
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:
        raise RuntimeError("Real image verification needs Pillow: py -3 -m pip install Pillow") from exc
    if not data or len(data) > MAX_LOGO_BYTES:
        raise ValueError("Invalid image byte size")
    Image.MAX_IMAGE_PIXELS = 16 * 1024 * 1024
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(data)) as image:
            fmt = image.format
            width, height = image.size
            if fmt not in MIME_TYPES or not (64 <= width <= 4096 and 64 <= height <= 4096):
                raise ValueError("Unsupported image format/dimensions")
            image.verify()
        with Image.open(BytesIO(data)) as decoded:
            decoded.load()
            if decoded.size != (width, height) or decoded.format != fmt:
                raise ValueError("Unstable image decoder metadata")
    return MIME_TYPES[fmt], width, height


def run_pilot(planned: list[dict], out_dir: Path, *,
              fetch=fetch_strict_https, decode=decode_image) -> dict:
    """Explicit fetching only; new output directory; never overwrite an object."""
    if out_dir.exists():
        raise ValueError("Pilot output directory already exists; refusing overwrite")
    if not planned or len(planned) > MAX_PILOT_OBJECTS:
        raise ValueError("Unbounded pilot batch")
    # Avoid accidental writes into the checkout or Android app support paths.
    out_dir.mkdir(parents=True, exist_ok=False)
    image_dir = out_dir / "evidence"
    image_dir.mkdir()
    records = []
    failures = []
    for entry in planned:
        url = entry["source_url"]
        host = entry["allowed_host"]
        # Each candidate has an independent result. One 403/TLS error must
        # not erase the proof gathered for other candidates, nor mark the
        # whole pilot successful. Failed candidates remain unapproved.
        try:
            checked_https_url(url, host)
            bytes_, content_type = fetch(url, host)
            if not isinstance(bytes_, bytes) or len(bytes_) > MAX_LOGO_BYTES:
                raise ValueError("Invalid fetched image byte count")
            mime, width, height = decode(bytes_)
            if mime != content_type:
                raise ValueError("HTTP MIME differs from decoded image")
            sha = hashlib.sha256(bytes_).hexdigest()
            target = image_dir / (sha + ".img")
            if target.exists():
                if target.read_bytes() != bytes_:
                    raise ValueError("Existing digest has different content")
            else:
                with target.open("xb") as output:
                    output.write(bytes_)
                    output.flush()
            records.append({
                **entry,
                "sha256_observed_not_signed": sha,
                "observed_bytes": len(bytes_),
                "decoded_mime_type": mime,
                "decoded_width": width,
                "decoded_height": height,
                "file": "evidence/" + sha + ".img",
                "editorial_review_required": True,
                "catalog_publication_authorized": False,
            })
        except Exception as exc:
            failures.append({
                "source_url": url,
                "go_station_ids": entry["go_station_ids"],
                "error_type": type(exc).__name__,
                "diagnostic": str(exc)[:180],
                "editorial_review_required": True,
                "catalog_publication_authorized": False,
            })
    report = {
        "status": ("PILOT_PARTIAL_FAILURE_NOT_APPROVED" if failures else
                   "PILOT_HTTPS_BYTES_VERIFIED_BUT_NOT_APPROVED"),
        "unique_fetched_urls": len(records),
        "attempted_source_urls": len(planned),
        "failed_source_urls": len(failures),
        "unique_sha256_objects": len(set(r["sha256_observed_not_signed"] for r in records)),
        "approved_logo_count": 0,
        "catalog_written": False,
        "play_or_informaniak_modified": False,
        "records": records,
        "failures": failures,
    }
    (out_dir / "pilot-evidence.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return report


def checked_local_output_dir(directory: Path, worktree: Path) -> Path:
    """Resolve relative build/ output; reject absolute paths and traversal."""
    root = (worktree / "build")
    if directory.is_absolute() or root.is_symlink():
        raise ValueError("Pilot output must be a relative path inside local build/")
    base = root.resolve()
    target = (worktree / directory).resolve()
    if target == base or not target.is_relative_to(base):
        raise ValueError("Pilot output escapes the worktree build/ sandbox")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--reuse-map", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true", help="Explicit bounded HTTPS download")
    parser.add_argument("--out-dir", type=Path, help="New local directory, mandatory with --fetch")
    args = parser.parse_args()
    planned = plan_pilot(
        json.loads(args.pilot.read_text(encoding="utf-8")),
        json.loads(args.staging.read_text(encoding="utf-8")),
        json.loads(args.reuse_map.read_text(encoding="utf-8")),
    )
    if args.fetch:
        if args.out_dir is None:
            parser.error("--fetch requires --out-dir for local proof files")
        # No absolute path, traversal or symlink bypass of the checkout's
        # designated untracked build sandbox, even if the input looks benign.
        try:
            safe_output = checked_local_output_dir(args.out_dir, Path.cwd())
        except ValueError as exc:
            parser.error(str(exc))
        result = run_pilot(planned, safe_output)
        print(json.dumps({k: v for k, v in result.items()
                          if k not in ("records", "failures")},
                         ensure_ascii=False))
        if result["failed_source_urls"]:
            raise SystemExit(2)  # Keep partial evidence; never return fake PASS.
    else:
        if args.out_dir is not None:
            parser.error("Output only applies to an explicit --fetch")
        print(json.dumps({
            "status": "PREFLIGHT_ONLY_NO_NETWORK_NO_APPROVAL",
            "image_urls": len(planned),
            "covered_go_station_ids": len(set(
                station_id for entry in planned for station_id in entry["go_station_ids"]
            )),
            "approved_logos": 0,
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
