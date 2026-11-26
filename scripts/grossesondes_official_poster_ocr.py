"""Bounded OCR of first-party festival posters: review-only, no field authority.

The caller must independently verify the edition page and discover the image
on that page. Never turn these tokens directly into catalogue fields.
"""
from __future__ import annotations

import csv
from datetime import date
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
MIN_REVIEW_CONFIDENCE = 85
OCR_PROFILE = "tesseract-fra-eng-psm11-contrast-v2"
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


def _ocr_score(words):
    """Prefer confident alphanumeric tokens, without merging geometries."""
    return (sum(w["confidence"] >= MIN_REVIEW_CONFIDENCE
                and bool(re.search(r"[^\W_]", w["text"])) for w in words),
            sum(w["confidence"] >= 60
                and bool(re.search(r"[^\W_]", w["text"])) for w in words))


def _choose_ocr_pass(original, alternative):
    """An alternative must not change detected edition or cancellation signals."""
    from grossesondes_official_html_edition import explicit_ranges, fold, CANCEL
    def signals(words):
        text = fold(" ".join(w["text"] for w in words))
        years = set(re.findall(r"(?<!\d)20[2-4]\d(?!\d)", text))
        ranges = {(a, b) for year in years
                  for _, _, a, b in explicit_ranges(text, int(year))}
        day_numbers = set(re.findall(r"(?<!\d)[0-3]?\d(?!\d)", text))
        return years, bool(CANCEL.search(text)), ranges, day_numbers
    if signals(original) != signals(alternative):
        return original
    return alternative if _ocr_score(alternative) > _ocr_score(original) else original


def recognize_poster(mime, body):
    """Two bounded local OCR passes; preserve one complete word geometry."""
    from PIL import Image, ImageOps
    with tempfile.TemporaryDirectory(prefix="go-poster-") as directory:
        path = Path(directory) / "poster.png"
        normalized_image(mime, body, path)
        deadline = monotonic() + 25

        def run(image_path):
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("OCR time budget")
            completed = subprocess.run(
                ["tesseract", str(image_path), "stdout", "-l", "fra+eng", "--psm", "11", "tsv"],
                shell=False, capture_output=True, timeout=remaining, check=True)
            if len(completed.stdout) > MAX_TSV:
                raise ValueError("OCR output exceeds budget")
            return parse_tsv(completed.stdout.decode("utf-8", errors="strict"))

        original = run(path)
        if monotonic() >= deadline - 2:
            return original
        # Improve contrast on illustrated posters, preserving image dimensions.
        try:
            alternate_path = Path(directory) / "contrast.png"
            with Image.open(path) as image:
                adjusted = ImageOps.autocontrast(image, cutoff=1)
                histogram = adjusted.histogram()
                if sum(histogram[:128]) > sum(histogram[128:]):
                    adjusted = ImageOps.invert(adjusted)
                adjusted.save(alternate_path, format="PNG")
            alternative = run(alternate_path)
            return _choose_ocr_pass(original, alternative)
        except (OSError, ValueError, TypeError, UnicodeError, subprocess.SubprocessError):
            return original


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


def poster_word_lines(words):
    """Return separated geometric lines, or None for ambiguous overlap."""
    lines = []
    # Group vertically overlapping words conservatively, without merging
    # across unusually large horizontal gaps (e.g. sponsor columns).
    for word in sorted(words, key=lambda w: (w["box"][1] + w["box"][3]/2, w["box"][0])):
        x, y, width, height = word["box"]
        if width <= 0 or height <= 0:
            continue
        center = y + height/2
        choices = [line for line in lines
                   if abs(center - line["center"]) <= .30 * min(height, line["height"])]
        if len(choices) == 1:
            choices[0]["words"].append(word)
        elif not choices:
            lines.append({"center": center, "height": height, "words": [word]})
        else:
            return None
    texts = []
    for line in lines:
        ordered = sorted(line["words"], key=lambda w: w["box"][0])
        current = []
        previous = None
        for word in ordered:
            x, y, width, height = word["box"]
            if previous is not None:
                px, py, pw, ph = previous["box"]
                if x - px - pw > 2.5 * max(height, ph) or x < px + pw - min(width, pw)*.2:
                    if current:
                        texts.append(current)
                    current = []
            current.append(word)
            previous = word
        if current:
            texts.append(current)
    return texts


def poster_known_artist_candidates(reading, artist_names):
    """Exact known-name hints, not lineup claims or a whitelist.

    A whole high-confidence geometric segment must match a known name.
    A sponsor can still match: never grant field or publication authority.
    Unknown names remain eligible for future independent identification.
    """
    from grossesondes_official_html_edition import fold
    words = reading.get("words")
    if (reading.get("status") != "review_only" or reading.get("review_only") is not True
            or not _valid_cached_words(words)):
        return []
    lines = poster_word_lines(words)
    if lines is None:
        return []
    def key(value):
        return " ".join(re.findall(r"[a-z0-9]+", fold(value)))
    known = {}
    for name in artist_names:
        if not isinstance(name, str) or len(name) > 110:
            continue
        normalized = key(name)
        if len(normalized.replace(" ", "")) >= 4 and re.search(r"[a-z]", normalized):
            known.setdefault(normalized, set()).add(name)
    matches = set()
    for line in lines:
        if not all(w["confidence"] >= MIN_REVIEW_CONFIDENCE for w in line):
            continue
        normalized = key(" ".join(w["text"] for w in line))
        if re.search(r"\b(?:sponsors?|partenaires?|presented|presente|billetterie|tickets?)\b", normalized):
            continue
        names = known.get(normalized, set())
        if len(names) == 1:
            matches.update(names)
    return sorted(matches)


def poster_review_claims(row, reading):
    """Edition-bound diagnostic claims; no publication authority.

    Reuse only exact signed dates and name. Preserve line geometry and reject
    ambiguous rows rather than concatenating text from separate poster blocks.
    Unlabelled logos are not artist proof. No new date or coordinate is emitted.
    """
    from grossesondes_official_html_edition import explicit_ranges, fold, CANCEL
    out = {"status": "edition_unproven", "review_only": True,
           "publication_authorized": False, "claims": {}, "diagnostics": {}}
    if not isinstance(row, dict) or not isinstance(reading, dict):
        return out
    words = reading.get("words")
    if (reading.get("status") != "review_only" or reading.get("review_only") is not True
            or not _valid_cached_words(words) or not words):
        return out
    try:
        start, end = date.fromisoformat(row["startDate"]), date.fromisoformat(row["endDate"])
        brand = re.sub(r"\b20[2-4]\d\b", "", fold(row["name"]))
    except (KeyError, TypeError, ValueError):
        return out
    def tokens(value):
        return re.findall(r"[a-z0-9]+", fold(value))
    brand_words = [w for w in tokens(brand) if w not in ("festival", "fest")]
    if not brand_words or len("".join(brand_words)) < 3 or start.year != end.year:
        return out
    out["diagnostics"]["word_count"] = len(words)
    out["diagnostics"]["strong_word_count"] = sum(w["confidence"] >= MIN_REVIEW_CONFIDENCE for w in words)
    texts = poster_word_lines(words)
    if texts is None:
        out["diagnostics"]["ambiguous_line_geometry"] = True
        return out
    all_text = " ".join(w["text"] for w in words)
    years = set(re.findall(r"(?<!\d)20[2-4]\d(?!\d)", all_text))
    out["diagnostics"].update(year_matches=years == {str(start.year)},
                              cancellation_detected=bool(CANCEL.search(fold(all_text))))
    if years != {str(start.year)} or CANCEL.search(fold(all_text)):
        out["status"] = "edition_conflict_or_year_missing"
        return out
    strong = [" ".join(w["text"] for w in line) for line in texts
              if all(w["confidence"] >= MIN_REVIEW_CONFIDENCE for w in line)]
    name_pattern = " " + " ".join(brand_words) + " "
    brand_ok = any(name_pattern in " " + " ".join(tokens(line)) + " " for line in strong)
    ranges = {(a,b) for line in strong for _,_,a,b in explicit_ranges(fold(line), start.year)}
    all_ranges = {(a,b) for line in texts for _,_,a,b in
                  explicit_ranges(fold(" ".join(w["text"] for w in line)), start.year)}
    out["diagnostics"].update(
        brand_matches=brand_ok,
        strong_date_range_count=len(ranges),
        all_date_range_count=len(all_ranges),
        strong_exact_dates=(start, end) in ranges,
        contradictory_dates=bool(all_ranges - {(start, end)}),
    )
    if not brand_ok or ranges != {(start,end)} or all_ranges != {(start,end)}:
        out["status"] = "edition_identity_or_dates_unproven"
        return out
    out["status"] = "edition_matches_review_only"
    out["claims"]["dates"] = {"start": start.isoformat(), "end": end.isoformat()}
    # Explicit labels only. A logo, sponsor, bare amount, or unrelated place
    # must not silently become a field. Keep original text for later checks.
    patterns = {
        "artist_labels": r"^(?:artistes?|groupes?|line[\s-]?up)\s*:\s*(.{2,150})$",
        "location_labels": r"^(?:lieu|ville|commune|venue)\s*:\s*(.{2,150})$",
        "price_labels": r"^(?:tarifs?|pass(?:\s+\d\s*(?:j|jours?))?|billets?)\s*:\s*(.{2,100})$",
    }
    for key, pattern in patterns.items():
        claims = []
        for line in strong:
            match = re.fullmatch(pattern, line, re.I)
            if match and line not in claims:
                if key == "price_labels" and not re.search(r"\d+(?:[,.]\d{2})?\s*(?:€|euros?|EUR)\b|\d+\s*€", line, re.I):
                    continue
                claims.append(line)
        if claims:
            out["claims"][key] = claims
    return out
