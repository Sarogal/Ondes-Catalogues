"""Generic station-bound metadata fallback, experimental hints only.

Only explicitly advertised JSON endpoints or scoped station JSON-LD.
No guessed paths, scripts, credentials, redirects, or catalogue changes.
"""
import http.client
import json
import re
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

from radio_daily_editorial_preview import Page, fetch_html, homepage_url, normalize, station_nodes
from radio_daily_qualification_dossiers import safe_digest
from radio_stream_technical_probe import validate_endpoint, public_resolved_ips

MAX_BYTES = 128 * 1024
MAX_ENDPOINTS = 2


def origin(url):
    p = validate_endpoint(url)
    return p.scheme, p.hostname, p.port or (443 if p.scheme == "https" else 80)


def hint(artist, title, method, source):
    if not isinstance(artist, str) or not isinstance(title, str):
        return None
    artist, title = artist.strip(), title.strip()
    if not (2 <= len(artist) <= 100 and 1 <= len(title) <= 140 and any(c.isalpha() for c in artist)):
        return None
    if any(ord(c) < 32 or ord(c) == 127 for c in artist + title):
        return None
    if re.search(r"https?://|www\.|@|[?=]", artist + title, re.I):
        return None
    return {"artistHint": artist, "titleHint": title, "titleSha256": safe_digest(title),
            "method": method, "sourceSha256": safe_digest(source)}


def combined(value, method, source):
    if not isinstance(value, str) or value.count(" - ") != 1:
        return None
    return hint(*value.split(" - ", 1), method, source)


def json_hints(data, stream, source):
    """Icecast source or Shoutcast stats must explicitly name the exact stream."""
    if not isinstance(data, dict):
        return []
    stats = data.get("icestats")
    if isinstance(stats, dict):
        rows = stats.get("source", [])
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list) or len(rows) > 128:
            return []
        matches = [r for r in rows if isinstance(r, dict) and r.get("listenurl") == stream]
        if len(matches) != 1:
            return []
        row = matches[0]
        h = (hint(row.get("artist"), row.get("title"), "icecast_json", source)
             if row.get("artist") else combined(row.get("title"), "icecast_json", source))
    elif data.get("streamurl") == stream and "songtitle" in data:
        h = combined(data["songtitle"], "shoutcast_json", source)
    else:
        return []
    return [h] if h else []


def page_hints(page, name, stream, source):
    identity = normalize(name)
    if len(identity) < 5 or identity in {"radio", "metal", "punk", "hard rock"}:
        return []
    matches = [n for n in station_nodes(page.structured)
               if isinstance(n.get("name"), str) and normalize(n["name"]) == identity
               and stream in [urljoin(source, n[k]) for k in ("contentUrl", "streamUrl")
                              if isinstance(n.get(k), str)]]
    if len(matches) != 1:
        return []
    node = matches[0]
    track = node.get("nowPlaying", node.get("currentTrack"))
    if not isinstance(track, dict):
        return []
    artist = track.get("byArtist", track.get("artist"))
    if isinstance(artist, dict):
        artist = artist.get("name")
    h = hint(artist, track.get("name", track.get("title")), "station_jsonld", source)
    return [h] if h else []


def advertised_endpoints(page, source, stream):
    """Follow only visible links to recognized public JSON formats on stream origin."""
    found = set()
    for href, label in page.links:
        try:
            url = urljoin(source, href)
            p = validate_endpoint(url)
            if p.scheme != "https" or origin(url) != origin(stream):
                continue
            path = p.path.rsplit("/", 1)[-1].lower()
            if path not in {"status-json.xsl", "stats", "statistics", "stats.json"} and not path.endswith(".json"):
                continue
            if p.query and not re.fullmatch(r"(?:sid=[1-9][0-9]{0,3}&json=1|json=1&sid=[1-9][0-9]{0,3}|json=1)", p.query):
                continue
            found.add(url)
        except (ValueError, TypeError):
            continue
    return sorted(found)[:MAX_ENDPOINTS]


def fetch_json(url):
    p = validate_endpoint(url)
    if p.scheme != "https":
        raise ValueError("HTTPS required")
    host, port = p.hostname, p.port or 443
    deadline = time.monotonic() + 8
    ip = public_resolved_ips(host, port)[0]
    if time.monotonic() >= deadline:
        raise TimeoutError("metadata deadline")
    conn = http.client.HTTPSConnection(host, port, timeout=min(3, deadline-time.monotonic()),
                                       context=ssl.create_default_context())
    def pinned(address, timeout=None, source_address=None):
        if address != (host, port):
            raise ValueError("unexpected socket target")
        return socket.create_connection((ip, port), timeout=min(3, max(.1, deadline-time.monotonic())))
    conn._create_connection = pinned
    try:
        conn.request("GET", urlunsplit(("", "", p.path or "/", p.query, "")),
                     headers={"Accept": "application/json", "Accept-Encoding": "identity",
                              "Connection": "close", "User-Agent": "GrossesOndesMetadataPreview/1.0"})
        response = conn.getresponse()
        if response.status != 200 or (response.getheader("Content-Encoding") or "identity").lower() != "identity":
            raise ValueError("unsupported response")
        if (response.getheader("Content-Type") or "").split(";")[0].strip().lower() not in ("application/json", "text/json"):
            raise ValueError("not JSON")
        body = bytearray()
        while len(body) <= MAX_BYTES:
            if time.monotonic() >= deadline:
                raise TimeoutError("metadata deadline")
            part = response.read1(min(8192, MAX_BYTES+1-len(body)))
            if not part:
                return json.loads(body)
            body.extend(part)
        raise ValueError("metadata body too large")
    finally:
        conn.close()


def observe_alternative(stream, station, *, fetch_page=fetch_html, fetch_api=fetch_json):
    homepage = homepage_url(station.get("homepage"))
    if not homepage:
        return []
    try:
        final, body = fetch_page(homepage)
        if origin(final)[1].removeprefix("www.") != origin(homepage)[1].removeprefix("www."):
            return []
        if not isinstance(body, bytes) or len(body) > 256 * 1024:
            return []
        page = Page()
        page.feed(body.decode("utf-8", errors="replace"))
        hints = page_hints(page, station.get("name"), stream, final)
        if hints:
            return hints
        for endpoint in advertised_endpoints(page, final, stream):
            try:
                hints = json_hints(fetch_api(endpoint), stream, endpoint)
                if hints:
                    return hints
            except (ValueError, OSError, http.client.HTTPException, RecursionError):
                continue
    except (ValueError, OSError, http.client.HTTPException, RecursionError):
        pass
    return []
