"""Read-only live evidence services for the strict experimental release gates.

A session is local to one operation on one authenticated baseline and scan day.
Repeated validation uses the same fresh, in-memory observation, not a durable
preview assertion. No publication, signing, remote writes or raw URL logging.
"""
import copy
import http.client
import time

from radio_daily_discovery import fetch_page, resolve_api_mirrors
from radio_daily_editorial_preview import fetch_html
from radio_stream_technical_probe import PinnedHttpTransport, probe_url
from radio_daily_continuity_preview import observe_url
from radio_daily_hls_preview import observe as observe_hls

MAX_CALLS = 24
MAX_SECONDS = 180


class EvidenceDeferred(ValueError):
    """Network or budget failure: do not authorize a release."""


class LiveEvidence:
    def __init__(self, *, max_calls=MAX_CALLS, max_seconds=MAX_SECONDS,
                 clock=time.monotonic, directory_limit=100):
        if not 0 < max_calls <= MAX_CALLS or not 0 < max_seconds <= MAX_SECONDS:
            raise ValueError("invalid live evidence budget")
        if directory_limit not in (50, 100):
            raise ValueError("invalid directory page budget")
        self._directory_limit = directory_limit
        self._clock = clock
        self._deadline = clock() + max_seconds
        self._max_calls = max_calls
        self._cache = {}
        self._hosts = None
        self.calls = 0

    def _invoke(self, kind, value, service):
        key = (kind, value)
        if self._clock() >= self._deadline:
            raise EvidenceDeferred("live evidence deadline")
        if key in self._cache:
            ok, result = self._cache[key]
            if not ok:
                raise EvidenceDeferred("live evidence unavailable")
            return copy.deepcopy(result)
        if self.calls >= self._max_calls:
            raise EvidenceDeferred("live evidence call budget")
        self.calls += 1
        try:
            result = service(value)
        except (ValueError, OSError, RuntimeError, http.client.HTTPException):
            self._cache[key] = (False, None)
            raise EvidenceDeferred("live evidence unavailable") from None
        if self._clock() >= self._deadline:
            raise EvidenceDeferred("live evidence deadline")
        self._cache[key] = (True, copy.deepcopy(result))
        return copy.deepcopy(result)

    def search(self, name):
        def lookup(term):
            if self._hosts is None:
                self._hosts = resolve_api_mirrors()[:2]
            return fetch_page(self._hosts, "name", term, 0, self._directory_limit)
        return self._invoke("search", name, lookup)

    def fetch(self, url):
        return self._invoke("html", url, fetch_html)

    def probe(self, url):
        return self._invoke("probe", url,
                            lambda u: probe_url(u, PinnedHttpTransport().request))

    def continuity(self, url):
        return self._invoke("icy", url, observe_url)

    def hls(self, url):
        return self._invoke("hls", url, observe_hls)

    def services(self):
        return {name: getattr(self, name) for name in
                ("search", "fetch", "probe", "continuity", "hls")}
