#!/usr/bin/env python3
"""Read-only audit of Grosses Ondes historical artwork, with open discovery.

Never writes playable catalogues, never signs or publishes images and does
not impose a known-station or host allowlist. All existing media IDs are
preserved. Images found on a homepage are candidates, not auto-approved logos.

Fetches are HTTPS only, limited, DNS-checked and content-decoded. No original
image bytes are saved; JSON reports contain hashes/size/dimensions only.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
from io import BytesIO
import ipaddress
import json
from pathlib import Path
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
import ssl

from PIL import Image, UnidentifiedImageError

MAX_IMAGE = 2 * 1024 * 1024
MAX_HTML = 256 * 1024
MAX_DIM = 4096
MIN_DIM = 64
MAX_INVENTORY = 20000
MAX_DISCOVERED = 8
ALLOWED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
REJECT_SUFFIXES = (".localhost", ".local", ".internal", ".onion", ".test")
UA = "GrossesOndes/central-artwork-inventory-audit-test (read-only)"


class InventoryError(ValueError):
    pass


def public_https(url: str, *, resolve: bool = False) -> bool:
    if not isinstance(url, str) or len(url) > 2048:
        return False
    try:
        u = urlsplit(url)
        if (u.scheme != "https" or not u.hostname or
                u.username is not None or u.password is not None or
                u.fragment or u.port not in (None, 443)):
            return False
        host = u.hostname.lower().rstrip(".")
        if ("." not in host or host == "localhost" or
                host.endswith(REJECT_SUFFIXES)):
            return False
        try:
            ip = ipaddress.ip_address(host.strip("[]"))
            if not ip.is_global:
                return False
        except ValueError:
            if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,251}[a-z0-9]", host):
                return False
        if resolve:
            addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            if not addresses:
                return False
            for addr in addresses:
                if not ipaddress.ip_address(addr[4][0]).is_global:
                    return False
        return True
    except (ValueError, TypeError, OSError):
        return False


class PublicHttpsRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not public_https(newurl, resolve=True):
            raise InventoryError("Disallowed redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def opener():
    return build_opener(
        HTTPSHandler(context=ssl.create_default_context()),
        PublicHttpsRedirects(),
    )


def _request(url: str, *, max_bytes: int, accept: str) -> tuple[bytes, str, str]:
    if not public_https(url, resolve=True):
        raise InventoryError("Unsafe/unresolved HTTPS source")
    req = Request(url, headers={
        "User-Agent": UA, "Accept": accept, "Accept-Encoding": "identity",
    })
    with opener().open(req, timeout=9) as response:
        if not public_https(response.geturl(), resolve=True):
            raise InventoryError("Unsafe final HTTPS target")
        mime = response.headers.get("Content-Type", "").split(";")[0].lower().strip()
        body = response.read(max_bytes + 1)
        if not body or len(body) > max_bytes:
            raise InventoryError("Empty/oversized response")
        return body, mime, response.geturl()


def inspect_bytes(body: bytes, *, content_type: str) -> dict:
    if len(body) > MAX_IMAGE or len(body) < 128:
        raise InventoryError("Invalid image byte length")
    try:
        with Image.open(BytesIO(body)) as img:
            size = img.size
            mime = ALLOWED_FORMATS.get(img.format)
            if (mime is None or not MIN_DIM <= size[0] <= MAX_DIM or
                    not MIN_DIM <= size[1] <= MAX_DIM or
                    size[0]*size[1] > 12_000_000):
                raise InventoryError("Image format/dimension quality gate")
            if content_type not in (mime, "application/octet-stream", ""):
                raise InventoryError("HTTP MIME does not match decoded image")
            img.verify()
    except (OSError, UnidentifiedImageError, ValueError) as e:
        raise InventoryError("Image decoder rejected response") from e
    return {
        "sha256": hashlib.sha256(body).hexdigest(),
        "byte_size": len(body),
        "width": size[0],
        "height": size[1],
        "mime_type": mime,
    }


def probe_image(url: str) -> dict:
    result = {"candidate_url": url, "verified_bytes": False,
              "approved_station_logo": False, "publication_allowed": False}
    try:
        body, mime, final_url = _request(
            url, max_bytes=MAX_IMAGE,
            accept="image/png,image/jpeg,image/webp",
        )
        inspected = inspect_bytes(body, content_type=mime)
        result.update(inspected)
        result["verified_bytes"] = True
        result["final_source_url"] = final_url
        result["quality_review_required"] = True
        result["reason"] = "decoded_sha_only_editorial_identity_unreviewed"
    except (InventoryError, HTTPError, URLError, TimeoutError,
            OSError, ssl.SSLError) as exc:
        result["reason"] = type(exc).__name__
    return result


class MetadataImages(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str|None]]):
        fields = dict(attrs)
        if tag == "meta":
            kind = fields.get("property") or fields.get("name") or ""
            if kind.lower() in {
                "og:image", "og:image:url", "twitter:image", "twitter:image:src",
            } and fields.get("content"):
                self.urls.append((kind.lower(), fields["content"]))
        elif tag == "link":
            rel = (fields.get("rel") or "").lower().split()
            href = fields.get("href")
            if href and any(x in rel for x in {
                "icon", "apple-touch-icon", "apple-touch-icon-precomposed",
                "image_src",
            }):
                self.urls.append(("html:link-icon-unreviewed", href))


def upgraded_https_homepage(raw_url: str) -> str | None:
    """Never fetch a plaintext homepage, not even as a fallback.

    Historical HTTP links may be used only as hints for an independent
    HTTPS request to the identical hostname/path, with the final HTTPS
    origin revalidated by the shared safe URL and DNS checks.
    """
    if not isinstance(raw_url, str) or len(raw_url) > 2048:
        return None
    candidate = raw_url.strip()
    if candidate.startswith("http://"):
        candidate = "https://" + candidate[len("http://"):]
    return candidate if public_https(candidate) else None


def discover_official_page(url: str) -> dict:
    report = {"homepage": url, "discovery_state": "unverified",
              "logo_approved": False, "publication_allowed": False,
              "image_candidates": []}
    # Only HTTPS is requested, never HTTP and never a guessed identity.
    chosen = upgraded_https_homepage(url)
    if chosen is None:
        report["reason"] = "homepage_not_safe_https"
        return report
    report["attempted_https_homepage"] = chosen
    try:
        body, mime, final = _request(chosen, max_bytes=MAX_HTML, accept="text/html")
        if mime not in {"text/html", "application/xhtml+xml", ""}:
            raise InventoryError("Homepage not HTML")
        parser = MetadataImages()
        parser.feed(body.decode("utf-8", errors="replace"))
        seen = set()
        for kind, raw in parser.urls:
            candidate = urljoin(final, raw)
            if public_https(candidate) and candidate not in seen:
                report["image_candidates"].append({
                    "url": candidate, "source_meta": kind,
                    "editorial_status": "needs_identity_review",
                })
                seen.add(candidate)
            if len(seen) >= MAX_DISCOVERED:
                break
        report["reason"] = (
            "homepage_metadata_candidates_not_approved"
            if seen else "homepage_no_image_metadata"
        )
    except (InventoryError, HTTPError, URLError, TimeoutError,
            OSError, ssl.SSLError) as exc:
        report["reason"] = type(exc).__name__
    return report


def validate_inventory(doc: dict) -> list[dict]:
    if not isinstance(doc, dict) or doc.get("schema_version") != 1 or \
       doc.get("publication_allowed") is not False or \
       doc.get("no_closed_station_list") is not True:
        raise InventoryError("Non-audit inventory or publication flag")
    stations = doc.get("stations")
    if not isinstance(stations, list) or not 1 <= len(stations) <= MAX_INVENTORY:
        raise InventoryError("Invalid inventory station count")
    ids = set()
    for row in stations:
        if not isinstance(row, dict) or row.get("editorial_decision") != "none":
            raise InventoryError("Unexpected editorial approval")
        id_ = row.get("legacy_media_id")
        if not isinstance(id_, str) or not id_ or id_ in ids:
            raise InventoryError("Missing/duplicate historical media ID")
        ids.add(id_)
        if not isinstance(row.get("display_name"), str) or not row["display_name"]:
            raise InventoryError("Unnamed historical radio")
        logo = row.get("source_logo_url")
        if not isinstance(logo, str):
            raise InventoryError("Malformed logo source")
        expected = "unverified_historical" if logo else "discovery_needed"
        if row.get("logo_state") != expected:
            raise InventoryError("Status inconsistent with source")
    return stations


def audit(doc: dict, *, shard_index: int, shard_count: int, network: bool) -> dict:
    stations = validate_inventory(doc)
    if not 1 <= shard_count <= 64 or not 0 <= shard_index < shard_count:
        raise InventoryError("Unsafe shard")
    selected = [row for pos, row in enumerate(stations)
                if pos % shard_count == shard_index]
    records = []
    for row in selected:
        source = row["source_logo_url"].strip()
        entry = {
            "legacy_media_id": row["legacy_media_id"],
            "display_name": row["display_name"],
            "source_logo_url": source,
            "publication_allowed": False,
            "station_logo_approved": False,
        }
        if source:
            if source.startswith("http://"):
                # An HTTPS upgrade must be independently retrievable.
                candidate = "https://" + source[7:]
                entry["source_kind"] = "legacy_http"
                entry["historical_http_never_fetched"] = True
                entry["probe"] = (probe_image(candidate) if network else
                                  {"reason":"offline_unsafe_http_source"})
            elif public_https(source):
                entry["source_kind"] = "legacy_https"
                entry["probe"] = (probe_image(source) if network else
                                  {"reason":"offline_read_only"})
            else:
                entry["source_kind"] = "unsafe_or_unsupported"
                entry["probe"] = {"reason":"source_rejected"}
        else:
            entry["source_kind"] = "needs_discovery"
            page = row.get("homepage", "")
            entry["discovery"] = (
                discover_official_page(page) if network else
                {"reason":"offline_discovery_not_attempted"}
            )
        records.append(entry)
    return {
        "schema_version": 1,
        "scope": "UNREVIEWED_ARTWORK_EVIDENCE_ONLY",
        "source_blob_sha": doc["source"]["blob_sha"],
        "shard_index": shard_index, "shard_count": shard_count,
        "inventory_total": len(stations),
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "publication_allowed": False,
        "signed_catalog_created": False,
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=8)
    parser.add_argument("--network", action="store_true")
    args = parser.parse_args()
    if args.inventory.stat().st_size > 3*1024*1024:
        raise InventoryError("Oversized inventory file")
    doc = json.loads(args.inventory.read_text(encoding="utf-8"))
    report = audit(doc, shard_index=args.shard_index,
                   shard_count=args.shard_count, network=args.network)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2)+"\n",
        encoding="utf-8",
    )
    results = report["records"]
    validated = sum(bool(x.get("probe", {}).get("verified_bytes")) for x in results)
    discovered = sum(len(x.get("discovery", {}).get("image_candidates", []))
                     for x in results)
    print(json.dumps({
        "status":"GO_ARTWORK_INVENTORY_AUDIT_ONLY",
        "shard":args.shard_index, "stations":len(results),
        "decoded_images":validated, "unreviewed_meta_candidates":discovered,
        "publication_allowed":False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
