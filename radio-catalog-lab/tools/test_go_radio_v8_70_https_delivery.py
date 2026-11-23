#!/usr/bin/env python3
"""Read-only GET all 70 canonical SHA image objects exactly as the APK will.

The client forbids redirects, unexpected MIME and changing bytes. Verify those
over actual HTTPS, not merely Git tree content. Never mutates the catalog.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

from test_go_radio_v8_70_canonical_test_release_gate import (
    CANONICAL, TEST_PREFIX,
)

MIME = {"image/jpeg", "image/png", "image/webp"}

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, msg, headers, new_url):
        return None


FETCH = urllib.request.build_opener(NoRedirect())


def verify(station: dict) -> dict:
    logo = station["logo"]
    url = logo["url"]
    if not url.startswith(TEST_PREFIX):
        raise ValueError("Logo URL escaped TEST SHA store")
    last = "RETRY_EXHAUSTED"
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={
                "Accept": "image/jpeg,image/png,image/webp",
                "Accept-Encoding": "identity",
                "User-Agent": "GrossesOndesTestRadioLogoQA/1",
            })
            with FETCH.open(request, timeout=18) as response:
                if response.status != 200 or response.geturl() != url:
                    raise ValueError("Redirect or status not 200")
                content_type = response.headers.get("Content-Type", "").split(";")[0].lower().strip()
                if content_type not in MIME or content_type != logo["mime_type"]:
                    raise ValueError("Image Content-Type incompatible with strict phone client: " + content_type)
                length = response.headers.get("Content-Length")
                if length and int(length) != logo["byte_size"]:
                    raise ValueError("Content-Length differs from signed descriptor")
                raw = response.read(logo["byte_size"] + 1)
                if len(raw) != logo["byte_size"]:
                    raise ValueError("Invalid actual transferred byte length")
                if hashlib.sha256(raw).hexdigest() != logo["sha256"]:
                    raise ValueError("SHA-256 differs from signed descriptor")
                return {"id": station["go_station_id"], "result": "HTTPS_SHA_OK"}
        except (OSError, urllib.error.URLError, ValueError) as e:
            last = type(e).__name__ + ":" + str(e)[:120]
            if attempt < 2: time.sleep(1)
    return {"id": station["go_station_id"], "result": "FAILED", "reason": last}


def main() -> None:
    catalog = json.loads(CANONICAL.read_bytes())
    chosen = [s for s in catalog["stations"] if s["logo"] is not None and
              s["logo"]["url"].startswith(TEST_PREFIX)]
    assert len(chosen) == 70
    results = []
    with ThreadPoolExecutor(max_workers=7) as executor:
        futures = [executor.submit(verify, station) for station in chosen]
        for future in as_completed(futures):
            results.append(future.result())
    failed = [r for r in results if r["result"] != "HTTPS_SHA_OK"]
    print(json.dumps({
        "result": "GO_V8_70_PUBLIC_TEST_SHA_HTTPS_EXACT_BYTE_AUDIT",
        "validated": len(results) - len(failed), "total": len(results),
        "failed": failed, "test_pointer_changed": False,
    }, ensure_ascii=False, sort_keys=True))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
