"""Generic station-bound metadata fallback, experimental hints only.

Only explicitly advertised JSON endpoints or scoped inert HTML/JSON.
No guessed paths, scripts, credentials, redirects, or catalogue changes.
"""
import datetime as dt
import http.client
import json
import re
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit, urlunsplit
from html.parser import HTMLParser

from radio_daily_editorial_preview import Page, fetch_html, homepage_url, normalize, station_nodes
from radio_daily_qualification_dossiers import safe_digest
from radio_stream_technical_probe import validate_endpoint, public_resolved_ips

MAX_BYTES = 128 * 1024
MAX_ENDPOINTS = 2
MAX_DOCUMENTS = 12
MAX_NODES = 256
ALTERNATIVE_METHODS = frozenset({"icecast_json", "shoutcast_json", "station_jsonld",
                                "station_now_playing_json", "station_embedded_json", "station_html",
                                "station_history_json", "hls_packed_id3"})


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
    generic = now_playing_hints(data, stream, source, "station_now_playing_json")
    history = history_hints(data, stream, source)
    if generic or history:
        return (generic + history)[:3]
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




def broadcast_day(value, now):
    """Explicit timestamp only: epoch seconds or timezone-aware ISO 8601."""
    try:
        if type(value) is int:
            when = dt.datetime.fromtimestamp(value, dt.timezone.utc)
        elif isinstance(value, str) and len(value) <= 40 and "T" in value:
            when = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            if when.tzinfo is None:
                return None
            when = when.astimezone(dt.timezone.utc)
        else:
            return None
        if not dt.timedelta(0) <= now - when < dt.timedelta(days=30):
            return None
        return when.date().isoformat()
    except (ValueError, OverflowError, OSError, TypeError):
        return None


def history_hints(data, stream, source, *, now=None):
    """Only dated history in a uniquely matched station record.
    
    Playlists, scheduled tracks and unbound sibling histories are not evidence.
    Return at most three different artist/title pairs per station and run.
    """
    now = now if now is not None else dt.datetime.now(dt.timezone.utc)
    pending = [(data, 0)]
    matched = []
    count = 0
    while pending:
        row, depth = pending.pop()
        count += 1
        if count > MAX_NODES:
            return []
        if depth > 8:
            continue
        if isinstance(row, list):
            if len(row) > 64:
                return []
            pending.extend((x, depth + 1) for x in row)
            continue
        if not isinstance(row, dict):
            continue
        station = row.get("station")
        if not isinstance(station, dict):
            station = row
        urls = [station[k] for k in ("listen_url", "listenUrl", "streamUrl", "stream_url", "contentUrl")
                if isinstance(station.get(k), str)]
        if stream in urls:
            matched.append(row)
            continue
        for key in ("stations", "data", "radios", "channels", "players", "props", "pageProps"):
            if key in row:
                pending.append((row[key], depth + 1))
    if len(matched) != 1:
        return []
    row = matched[0]
    histories = [row[k] for k in ("song_history", "songHistory", "playedTracks", "recentlyPlayed") if k in row]
    if len(histories) != 1 or not isinstance(histories[0], list) or len(histories[0]) > 100:
        return []
    candidates = []
    for event in histories[0]:
        if not isinstance(event, dict):
            continue
        stamps = [event[k] for k in ("played_at", "playedAt", "broadcastAt") if k in event]
        if len(stamps) != 1:
            continue
        day = broadcast_day(stamps[0], now)
        if day is None:
            continue
        track = event.get("song", event)
        if not isinstance(track, dict):
            continue
        artist = track.get("artist", track.get("byArtist"))
        if isinstance(artist, dict):
            artist = artist.get("name")
        h = hint(artist, track.get("title", track.get("name")), "station_history_json", source)
        if h:
            candidates.append(dict(h, broadcastDate=day))
    result, seen = [], set()
    for h in sorted(candidates, key=lambda x: (x["broadcastDate"], x["artistHint"], x["titleSha256"]), reverse=True):
        pair = h["artistHint"].casefold(), h["titleSha256"]
        if pair not in seen:
            result.append(h)
            seen.add(pair)
        if len(result) >= 3:
            break
    return result


def now_playing_hints(data, stream, source, method):
    """Common public Now Playing shapes, including AzuraCast.

    Traverse bounded structural containers only. A track must be a child of
    the very record declaring the exact stream; never join sibling stations.
    Multiple matching stations or contradictory tracks are ambiguous.
    """
    pending = [(data, 0)]
    matched = []
    count = 0
    while pending:
        row, depth = pending.pop()
        count += 1
        if count > MAX_NODES:
            return []
        if depth > 8:
            continue
        if isinstance(row, list):
            if len(row) > 64:
                return []
            pending.extend((x, depth + 1) for x in row)
            continue
        if not isinstance(row, dict):
            continue
        station = row.get("station")
        if not isinstance(station, dict):
            station = row
        urls = [station[k] for k in ("listen_url", "listenUrl", "streamUrl", "stream_url", "contentUrl")
                if isinstance(station.get(k), str)]
        if stream in urls:
            tracks = [row[k] for k in ("now_playing", "nowPlaying", "currentTrack", "current_track")
                      if k in row]
            if len(tracks) != 1 or not isinstance(tracks[0], dict):
                matched.append(None)
                continue
            track = tracks[0].get("song", tracks[0])
            if not isinstance(track, dict):
                matched.append(None)
                continue
            artist = track.get("artist", track.get("byArtist"))
            if isinstance(artist, dict):
                artist = artist.get("name")
            matched.append(hint(artist, track.get("title", track.get("name")), method, source))
            continue
        for key in ("stations", "data", "radios", "channels", "players", "props", "pageProps"):
            if key in row:
                pending.append((row[key], depth + 1))
    return [matched[0]] if len(matched) == 1 and matched[0] else []


class MetadataPage(HTMLParser):
    """Read inert JSON and explicitly scoped HTML metadata, never execute JS."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.documents = []
        self.script = None
        self.blocks = []
        self.ignored = None

    def handle_starttag(self, tag, attrs):
        if self.ignored:
            return
        a = dict(attrs)
        if tag in ("script", "style", "template", "noscript"):
            self.ignored = tag
            if tag == "script" and (a.get("type") or "").lower().strip() == "application/json":
                self.script = []
            return
        if tag in ("div", "section", "article", "audio") and a.get("data-stream-url"):
            if len(self.blocks) < 64:
                self.blocks.append((a["data-stream-url"], a.get("data-now-playing-artist"),
                                    a.get("data-now-playing-title")))

    def handle_data(self, data):
        if self.script is not None:
            self.script.append(data)

    def handle_endtag(self, tag):
        if tag != self.ignored:
            return
        if self.script is not None:
            raw = "".join(self.script)
            if len(raw) <= MAX_BYTES and len(self.documents) < MAX_DOCUMENTS:
                try:
                    self.documents.append(json.loads(raw))
                except (ValueError, RecursionError):
                    pass
            self.script = None
        self.ignored = None


def embedded_hints(body, stream, source):
    p = MetadataPage()
    p.feed(body.decode("utf-8", errors="replace"))
    # Treat each JSON document as a separate source declaration. No union
    # across records, and conflicting observations are not silently picked.
    candidates = []
    histories = []
    for data in p.documents:
        candidates.extend(now_playing_hints(data, stream, source, "station_embedded_json"))
        found = history_hints(data, stream, source)
        if found:
            histories.append(found)
    for url, artist, title in p.blocks:
        if urljoin(source, url) == stream:
            h = hint(artist, title, "station_html", source)
            if h:
                candidates.append(h)
    identities = {(h["artistHint"], h["titleSha256"]) for h in candidates}
    if len(identities) > 1 or len(histories) > 1:
        return []
    return (candidates[:1] + (histories[0] if histories else []))[:3]


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
    """Follow visible links to public JSON on the station or stream origin."""
    found = set()
    for href, label in page.links:
        try:
            url = urljoin(source, href)
            p = validate_endpoint(url)
            if p.scheme != "https" or origin(url) not in {origin(stream), origin(source)}:
                continue
            path = p.path.rsplit("/", 1)[-1].lower()
            if path not in {"status-json.xsl", "stats", "statistics", "stats.json", "nowplaying", "now-playing", "now_playing", "history", "song-history", "recently-played"} and not path.endswith(".json") and not re.search(r"/(?:nowplaying|now-playing|now_playing)/[^/]+$", p.path, re.I):
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
        hints = embedded_hints(body, stream, final)
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
