"""Snapshot the exact public v172 JavaScript, without modifying the website.

Executed exclusively on an isolated GitHub public runner; the output is a
review-only snapshot. No private tokens and no production publishing.
"""
import argparse
import hashlib
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

URL = "https://ptitesondes.fr/sorties-v172.js"
MAX_BYTES = 160_000
REQUIRED = (
    "pt-territoires-select",
    "installTerritorySelect",
    "outings-category",
    "outings-age",
    "setTerritory",
    "filterEvents",
    "categoryGroup",
    "categoryEmoji",
)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def inspect_source(source: str):
    if not isinstance(source, str):
        raise ValueError("non_text_javascript")
    if not 15_000 <= len(source.encode("utf-8")) <= MAX_BYTES:
        raise ValueError("unexpected_javascript_size")
    if not source.lstrip().startswith("(() => {"):
        raise ValueError("unexpected_javascript_prefix")
    missing = [part for part in REQUIRED if part not in source]
    if missing:
        raise ValueError("missing_live_v172_marker_" + ",".join(missing))
    if "<!doctype html" in source.lower():
        raise ValueError("received_html_instead_of_javascript")
    return {
        "bytes": len(source.encode("utf-8")),
        "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "verified_markers": len(REQUIRED),
    }


def fetch_source():
    if urlsplit(URL).scheme != "https":
        raise ValueError("https_required")
    req = Request(URL, headers={
        "Accept": "text/javascript,application/javascript,application/x-javascript,*/*",
        "User-Agent": "PtitesOndes-V172-ReadOnly-Snapshot/1.0",
        "Cache-Control": "no-cache",
    })
    with build_opener(NoRedirect).open(req, timeout=20) as response:
        if response.geturl() != URL:
            raise ValueError("redirect_not_allowed")
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("source_too_large")
    return body.decode("utf-8-sig")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        # Exact re-run is harmless; changing production source still produces
        # a new proposed snapshot commit, never a web deployment.
        pass
    js = fetch_source()
    info = inspect_source(js)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(js, encoding="utf-8")
    print("V172_READONLY_SNAPSHOT verified", info)


if __name__ == "__main__":
    main()
