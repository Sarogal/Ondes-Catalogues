"""Read-only bounded recovery of exact inherited artwork for the memory store."""
import http.client
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from radio_catalog_logo_pilot_probe import fetch_strict_https
from radio_daily_logo_plan import PREVIEW_BASE
from radio_daily_publication_simulator import check_logo, inventory

MAX_URLS = 320
MAX_BYTES = 48 * 1024 * 1024
MAX_SECONDS = 150
WORKERS = 8


class ArtworkUnavailable(ValueError):
    """No safe, complete predecessor artwork snapshot."""


def recover_inherited(old, new, *, fetch=fetch_strict_https, clock=time.monotonic, cache_dirs=None):
    descriptors = {}
    for doc in (old, new):
        for logo, path in inventory(doc):
            url = logo["url"]
            if path is not None:
                if doc is old:
                    raise ArtworkUnavailable("prior laboratory objects require existing store")
                continue
            key = (logo["sha256"], logo["byte_size"], logo["mime_type"],
                   logo["width"], logo["height"])
            if url in descriptors and descriptors[url][0] != key:
                raise ArtworkUnavailable("inherited URL descriptor conflict")
            descriptors[url] = (key, logo)
    if len(descriptors) > MAX_URLS or sum(k[0][1] for k in descriptors.values()) > MAX_BYTES:
        raise ArtworkUnavailable("inherited artwork budget")
    deadline = clock() + MAX_SECONDS
    result = {}
    def load(item):
        url, (_, logo) = item
        try:
            if cache_dirs is not None:
                from radio_daily_inherited_artwork_cache import cached
                data = cached(logo, cache_dirs)
                if data is None:
                    raise ArtworkUnavailable("inherited artwork cache incomplete")
                mime = logo["mime_type"]
            else:
                data, mime = fetch(url, urlsplit(url).hostname)
            if mime != logo["mime_type"]:
                raise ValueError("inherited MIME mismatch")
            check_logo(logo, data)
            return url, data
        except (ValueError, OSError, RuntimeError, http.client.HTTPException):
            raise ArtworkUnavailable("inherited artwork unverified") from None
    entries = sorted(descriptors.items())
    # No new batches after deadline. Network transport also bounds each socket;
    # the deadline is soft because an already running DNS lookup may overrun.
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for i in range(0, len(entries), WORKERS):
            if clock() >= deadline:
                raise ArtworkUnavailable("inherited artwork deadline")
            for url, data in pool.map(load, entries[i:i+WORKERS]):
                result[url] = data
            if clock() >= deadline:
                raise ArtworkUnavailable("inherited artwork deadline")
    return result
