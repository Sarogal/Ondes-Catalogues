"""Bounded OCR of first-party festival posters: review-only, no field authority.

The caller must independently verify the edition page and discover the image
on that page. Never turn these tokens directly into catalogue fields.
"""
from __future__ import annotations

import csv
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import tempfile
from time import monotonic
from urllib.parse import urlsplit
import warnings

from dns_pinned_https import (
    DNSPinnedHTTPSConnection, OfficialHTTPStatusError, safe_public_url,
)

MAX_BYTES = 6 * 1024 * 1024
MAX_PIXELS = 12_000_000
MAX_SIDE = 6000
MAX_TSV = 256_000
MAX_WORDS = 1500
MAX_CACHE = 64
MAX_CACHE_BYTES = 8 * 1024 * 1024
OCR_PROFILE = "tesseract-fra-eng-psm11-v1"
MIME_FORMAT = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


def qualified_url(site, url):
    """Same-origin, visible-candidate URL contract; no new domain or redirect."""
    if (not isinstance(site, str) or not isinstance(url, str)
            or safe_public_url(site) != site or safe_public_url(url) != url):
        return False
    path = urlsplit(url).path
    return (urlsplit(site).hostname == urlsplit(url).hostname
            and not any(c in path for c in ("%","\\"))
            and ".." not in path.split("/")
            and bool(re.search(r"\.(?:jpe?g|png|webp)$", path, re.I)))


def fetch_poster(site, url):
    if not qualified_url(site, url):
        raise ValueError("Unqualified image URL")
    parts = urlsplit(url)
    connection = DNSPinnedHTTPSConnection(
        parts.hostname, port=443, timeout=8, context=ssl.create_default_context())
    deadline = monotonic() + 18
    try:
        connection.request("GET", parts.path, headers={
            "User-Agent": "GrossesOndesOfficialPosterReview/1.0",
            "Accept": "image/jpeg,image/png,image/webp",
            "Accept-Encoding": "identity",
        })
        response = connection.getresponse()
        # No redirects or retries: never follow a CDN or bypass a 429.
        if response.status != 200:
            raise OfficialHTTPStatusError(response.status)
        mime = (response.getheader("Content-Type") or "").split(";", 1)[0].strip().lower()
        if mime not in MIME_FORMAT or (response.getheader("Content-Encoding") or "identity").lower() != "identity":
            raise ValueError("Unsupported image response")
        size = response.getheader("Content-Length")
        if size is not None and (not size.isascii() or not size.isdecimal()
                                 or len(size) > 8 or not 0 < int(size) <= MAX_BYTES):
            raise ValueError("Image length exceeds budget")
        data = bytearray()
        while True:
            if monotonic() >= deadline:
                raise TimeoutError("Image download time budget")
            block = response.read1(min(65536, MAX_BYTES + 1 - len(data)))
            if not block:
                break
            data.extend(block)
            if len(data) > MAX_BYTES:
                raise ValueError("Image exceeds byte budget")
        if not data or (size is not None and len(data) != int(size)):
            raise ValueError("Empty or incomplete image")
        return mime, bytes(data)
    finally:
        connection.close()


def normalized_image(mime, body, destination):
    """Validate actual raster and dimensions; discard metadata/animation."""
    from PIL import Image
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(body)) as image:
            if (image.format != MIME_FORMAT.get(mime)
                    or image.width <= 0 or image.height <= 0
                    or max(image.size) > MAX_SIDE
                    or image.width * image.height > MAX_PIXELS
                    or getattr(image, "n_frames", 1) != 1):
                raise ValueError("Invalid poster raster")
            image.verify()
        with Image.open(io.BytesIO(body)) as image:
            image.convert("L").save(destination, format="PNG")


def parse_tsv(raw):
    """Keep word-level geometry and confidence, not guessed artist names."""
    if not isinstance(raw, str) or len(raw) > MAX_TSV:
        raise ValueError("OCR output exceeds budget")
    fields = ("left", "top", "width", "height", "conf", "text")
    reader = csv.DictReader(io.StringIO(raw), delimiter="\t", quoting=csv.QUOTE_NONE)
    if reader.fieldnames is None or not set(fields + ("level",)).issubset(reader.fieldnames):
        raise ValueError("Invalid OCR output")
    words = []
    for row in reader:
        if row.get("level") != "5":
            continue
        text = (row.get("text") or "").strip()
        if not text:
            continue
        if len(text) > 200 or any(ord(c) < 32 for c in text):
            raise ValueError("Invalid OCR word")
        try:
            confidence = float(row["conf"])
            box = [int(row[k]) for k in fields[:4]]
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError("Invalid OCR word geometry") from exc
        if not 0 <= confidence <= 100 or min(box) < 0 or max(box) > MAX_SIDE:
            raise ValueError("Invalid OCR word confidence or bounds")
        words.append({"text": text, "confidence": round(confidence, 2),
                      "box": box, "review_only": True})
        if len(words) > MAX_WORDS:
            raise ValueError("Too many OCR words")
    return words


def recognize_poster(mime, body):
    """Local Tesseract; bounded image, no shell, no network, no paid service."""
    with tempfile.TemporaryDirectory(prefix="go-poster-") as directory:
        path = Path(directory) / "poster.png"
        normalized_image(mime, body, path)
        completed = subprocess.run(
            ["tesseract", str(path), "stdout", "-l", "fra+eng", "--psm", "11", "tsv"],
            shell=False, capture_output=True, timeout=25, check=True)
        if len(completed.stdout) > MAX_TSV:
            raise ValueError("OCR output exceeds budget")
        return parse_tsv(completed.stdout.decode("utf-8", errors="strict"))


def _valid_cached_words(words):
    if not isinstance(words, list) or len(words) > MAX_WORDS:
        return False
    for word in words:
        if not isinstance(word, dict) or set(word) != {"text", "confidence", "box", "review_only"}:
            return False
        text, confidence, box = word["text"], word["confidence"], word["box"]
        if (not isinstance(text, str) or not 0 < len(text) <= 200
                or any(ord(c) < 32 for c in text)
                or type(confidence) not in (float, int) or not 0 <= confidence <= 100
                or not isinstance(box, list) or len(box) != 4
                or any(type(x) is not int or not 0 <= x <= MAX_SIDE for x in box)
                or word["review_only"] is not True):
            return False
    return True


def load_ocr_cache(path):
    """Read bounded, versioned diagnostic state; corruption is a cache miss."""
    try:
        with Path(path).open("rb") as handle:
            raw = handle.read(MAX_CACHE_BYTES + 1)
        if len(raw) > MAX_CACHE_BYTES:
            return {}
        doc = json.loads(raw)
        if not isinstance(doc, dict) or doc.get("profile") != OCR_PROFILE:
            return {}
        entries = doc.get("entries")
        if not isinstance(entries, dict) or len(entries) > MAX_CACHE:
            return {}
        return {(OCR_PROFILE, digest): words for digest, words in entries.items()
                if re.fullmatch(r"[0-9a-f]{64}", digest) and _valid_cached_words(words)}
    except (OSError, ValueError, TypeError, RecursionError, UnicodeError):
        return {}


def save_ocr_cache(path, cache):
    """Atomically save only bounded OCR diagnostics in caller-owned state.

    The caller must use a private, trusted state directory, never docs/ or a
    public artifact. No source URL, downloaded image, or editorial proof.
    """
    entries = {}
    for k, words in list(cache.items())[-MAX_CACHE:]:
        if (isinstance(k, tuple) and len(k) == 2 and k[0] == OCR_PROFILE
                and isinstance(k[1], str) and re.fullmatch(r"[0-9a-f]{64}", k[1])
                and _valid_cached_words(words)):
            entries[k[1]] = words
    while True:
        raw = json.dumps({"profile": OCR_PROFILE, "entries": entries},
                         ensure_ascii=False, allow_nan=False,
                         separators=(",", ":")).encode("utf-8")
        if len(raw) <= MAX_CACHE_BYTES:
            break
        entries.pop(next(iter(entries)))
    destination = Path(path)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".poster-ocr-",
                                         delete=False) as handle:
            tmp = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, destination)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def read_official_poster(site, url, *, cache, fetch=None, recognize=None):
    """Cache successful OCR by bytes and profile, not URL. Never authorize edits.

    The caller owns the bounded cache and optional private persistence;
    edition/field verification remains a separate Publisher integration.
    """
    out = {"status": "unqualified", "review_only": True}
    if not qualified_url(site, url):
        return out
    fetch = fetch or fetch_poster
    recognize = recognize or recognize_poster
    try:
        mime, body = fetch(site, url)
        if mime not in MIME_FORMAT or not isinstance(body, bytes) or not 0 < len(body) <= MAX_BYTES:
            raise ValueError("Invalid image payload")
        digest = sha256(body).hexdigest()
        cache_key = (OCR_PROFILE, digest)
        out["sha256"] = digest
        cached = cache_key in cache and _valid_cached_words(cache[cache_key])
        words = cache[cache_key] if cached else recognize(mime, body)
        if not _valid_cached_words(words):
            raise ValueError("Invalid OCR word result")
        if not cached:
            if len(cache) >= MAX_CACHE:
                cache.pop(next(iter(cache)))
            cache[cache_key] = words
        out.update(status="review_only", words=words, cache_hit=cached)
    except OfficialHTTPStatusError as exc:
        out["status"] = "rate_limited" if exc.status_code == 429 else "http_rejected"
    except (ImportError, OSError, ValueError, TypeError, UnicodeError,
            subprocess.SubprocessError, Warning):
        out["status"] = "image_or_ocr_unavailable"
    return out
