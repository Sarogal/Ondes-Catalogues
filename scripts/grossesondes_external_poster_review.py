"""Read-only raster research from fresh, signed official HTML.

No private input, publication path, cross-origin browser requests, redirects,
arbitrary CLI URL, credentials, or unbounded query parameters.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re
import ssl
import subprocess
import sys
from time import monotonic
from urllib.parse import parse_qsl, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "festival-automation"))

from grossesondes_existing_official_updates import (
    signed_rotation, page, home_matches_edition, linked_pages, fold,
)
from grossesondes_official_html_edition import (
    VisibleText, explicit_ranges, dominant_visible_range, fold as calendar_fold,
)
from dns_pinned_https import DNSPinnedHTTPSConnection, OfficialHTTPStatusError, safe_public_url, fetch_public_html
from grossesondes_official_poster_ocr import (
    MAX_BYTES, MIME_FORMAT, recognize_poster, poster_review_claims,
)

MAX_HOSTS = 4
MAX_SECONDS = 150


def raster_url(url):
    """Explicit, bounded raster path and typed image transformation options."""
    if not isinstance(url, str) or not 12 <= len(url) <= 800:
        return False
    try:
        p = urlsplit(url)
        base = urlunsplit((p.scheme, p.netloc, p.path, "", ""))
        if (p.fragment or safe_public_url(base) != base
                or any(ord(c) < 33 or ord(c) > 126 for c in url)
                or not re.fullmatch(r"/[A-Za-z0-9_./-]+\.(?:jpg|jpeg|png|webp)", p.path, re.I)
                or any(x in (".", "..") for x in p.path.split("/"))
                or len(p.query) > 180):
            return False
        if not p.query:
            return True
        pairs = parse_qsl(p.query, strict_parsing=True, max_num_fields=4)
        if len(dict(pairs)) != len(pairs):
            return False
        for k, v in pairs:
            if k == "enable-io" and v == "true":
                continue
            if k == "enable" and v == "upscale":
                continue
            if k == "width" and re.fullmatch(r"[0-9]{2,4}", v) and 64 <= int(v) <= 1920:
                continue
            if k == "crop" and re.fullmatch(r"[0-9]{1,2}(?:\.[0-9]{1,4})?:[0-9]{1,2}(?:\.[0-9]{1,4})?", v):
                if all(0 < float(x) <= 20 for x in v.split(":")):
                    continue
            return False
        # Only allow a percent-encoded colon in the original query.
        return bool(pairs) and not re.search(r"%(?!3[aA])|[+;]", p.query)
    except (ValueError, TypeError, UnicodeError):
        return False


def candidates(html, site, row):
    if not isinstance(html, str) or len(html) > 650_000 or safe_public_url(site) != site:
        return []
    year = date.fromisoformat(row["startDate"]).year
    brand = [x for x in fold(row["name"]).split() if x not in ("festival", "fest", str(year))]
    if len("".join(brand)) < 3:
        return []
    host = urlsplit(site).hostname

    class Images(VisibleText):
        def __init__(self):
            super().__init__()
            self.urls = set()

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag in ("nav", "footer", "aside", "header"):
                attrs = list(attrs) + [("hidden", None)]
            if (tag == "img" and not self.hidden() and "hidden" not in a
                    and a.get("aria-hidden") != "true"
                    and not re.search(r"display\s*:\s*none|visibility\s*:\s*hidden",
                                      a.get("style") or "", re.I)
                    and len(self.urls) < 4):
                url = a.get("src")
                if raster_url(url) and urlsplit(url).hostname != host:
                    filename = fold(urlsplit(url).path.rsplit("/", 1)[-1])
                    label = fold(" ".join((a.get(k) or "")[:300] for k in ("alt", "title")))
                    years = set(re.findall(r"\b20[2-4]\d\b", filename + " " + label))
                    if (years == {str(year)} and all(x in filename.split() for x in brand)
                            and not re.search(r"\b(?:logo|sponsor|partenaire|favicon|icon|thumbnail|thumb)\b", filename + " " + label)):
                        self.urls.add(url)
            super().handle_starttag(tag, attrs)

    parser = Images()
    parser.feed(html)
    parser.close()
    return sorted(parser.urls)


def read_raster(url):
    if not raster_url(url):
        raise ValueError("Invalid raster request")
    p = urlsplit(url)
    conn = DNSPinnedHTTPSConnection(p.hostname, port=443, timeout=8,
                                    context=ssl.create_default_context())
    try:
        conn.request("GET", p.path + ("?" + p.query if p.query else ""),
                     headers={"User-Agent": "GrossesOndesRasterResearch/1.0",
                              "Accept": "image/jpeg,image/png,image/webp",
                              "Accept-Encoding": "identity"})
        response = conn.getresponse()
        if response.status != 200:
            raise OfficialHTTPStatusError(response.status)
        mime = (response.getheader("Content-Type") or "").split(";", 1)[0].lower().strip()
        if mime not in MIME_FORMAT or response.getheader("Content-Encoding", "identity").lower() != "identity":
            raise ValueError("Unsupported raster")
        size = response.getheader("Content-Length")
        if size is not None and (not size.isascii() or not size.isdecimal()
                                 or len(size) > 8 or not 0 < int(size) <= MAX_BYTES):
            raise ValueError("Excessive raster length")
        deadline = monotonic() + 18
        body = bytearray()
        while True:
            if monotonic() >= deadline:
                raise TimeoutError("Raster budget")
            block = response.read1(min(65536, MAX_BYTES + 1 - len(body)))
            if not block:
                break
            body.extend(block)
            if len(body) > MAX_BYTES:
                raise ValueError("Excessive raster bytes")
        if not body or (size is not None and len(body) != int(size)):
            raise ValueError("Incomplete raster")
        return mime, bytes(body)
    finally:
        conn.close()


def exact_root_dates(parsed, row):
    """Require an actual visible current interval, not merely a year token."""
    try:
        start = date.fromisoformat(row["startDate"])
        end = date.fromisoformat(row["endDate"])
    except (ValueError, TypeError, KeyError):
        return False
    if start.year != end.year or end < start:
        return False
    blocks = [b for b in parsed.blocks if b["scope"] == "main"] or parsed.relevant()
    ranges = {(first, last) for block in blocks
              for _, _, first, last in explicit_ranges(calendar_fold(block["text"]), start.year)}
    return dominant_visible_range(ranges) == (start, end)


def scan(catalogue, today, tick=0, slug=None, *, fetch=fetch_public_html,
         read=read_raster, recognize=recognize_poster):
    report = {"review_only": True, "publication_authorized": False,
              "checked_hosts": 0, "external_candidates": 0, "images_read": 0, "rows": []}
    selected = signed_rotation(catalogue, today, MAX_HOSTS, tick, alternate_order=True)
    if slug is not None:
        selected = [(site, [r for r in rows if r.get("slug") == slug])
                    for i in range(20)
                    for site, rows in signed_rotation(catalogue, today, 60, i)
                    if any(r.get("slug") == slug for r in rows)]
        selected = selected[:1]
    deadline = monotonic() + MAX_SECONDS
    limited_raster_hosts = set()
    for site, rows in selected:
        if monotonic() >= deadline:
            break
        report["checked_hosts"] += 1
        try:
            html = fetch(site)
            parsed = page(html)
        except (OSError, ValueError, TypeError, UnicodeError):
            continue
        eligible = [r for r in rows if not r.get("cancelled")
                    and r.get("status") not in ("Annulé", "Reporté")
                    and r.get("startDate") and r.get("endDate")
                    and home_matches_edition(parsed, r, today)
                    and exact_root_dates(parsed, r)]
        if not eligible:
            continue
        surfaces = [html]
        limited = False
        for link in linked_pages(site, parsed, prefer_programme=True)[:2]:
            if monotonic() >= deadline:
                break
            try:
                surfaces.append(fetch(link))
            except OfficialHTTPStatusError as exc:
                if exc.status_code == 429:
                    limited = True
                    break
            except (OSError, ValueError, TypeError, UnicodeError):
                continue
        if limited:
            continue
        for row in eligible:
            urls = sorted({u for h in surfaces for u in candidates(h, site, row)})
            report["external_candidates"] += len(urls)
            diagnostic = {"slug": row["slug"], "candidates": len(urls), "outcome": "NO_CANDIDATE"}
            report["rows"].append(diagnostic)
            if len(urls) != 1 or monotonic() >= deadline:
                if len(urls) > 1:
                    diagnostic["outcome"] = "AMBIGUOUS"
                continue
            url = urls[0]
            raster_host = urlsplit(url).hostname
            if raster_host in limited_raster_hosts:
                diagnostic["outcome"] = "RATE_LIMITED_EARLIER"
                continue
            report["images_read"] += 1
            try:
                mime, body = read(url)
                words = recognize(mime, body)
                result = poster_review_claims(row, {"status": "review_only",
                    "review_only": True, "words": words})
                diagnostic.update(outcome=result["status"], qualification=result["diagnostics"],
                                  claim_types=sorted(result["claims"]))
            except OfficialHTTPStatusError as exc:
                diagnostic["outcome"] = "RATE_LIMITED" if exc.status_code == 429 else "HTTP_REJECTED"
                if exc.status_code == 429:
                    limited_raster_hosts.add(raster_host)
            except (OSError, ValueError, TypeError, UnicodeError, ImportError,
                    subprocess.SubprocessError, Warning):
                diagnostic["outcome"] = "RASTER_OR_OCR_UNAVAILABLE"
            # Maximum one raster read per signed host per run.
            break
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", required=True, type=Path)
    parser.add_argument("--tick", type=int, default=0)
    parser.add_argument("--slug")
    args = parser.parse_args()
    if args.catalogue.stat().st_size > 10_000_000:
        raise ValueError("Catalogue budget")
    print(json.dumps(scan(json.loads(args.catalogue.read_text(encoding="utf-8")),
                          date.today().isoformat(), args.tick, args.slug), indent=2))
