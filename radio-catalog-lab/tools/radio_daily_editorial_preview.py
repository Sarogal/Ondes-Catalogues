#!/usr/bin/env python3
"""Bounded generic homepage evidence; no editorial or artwork approval.

Only declared public HTTPS pages, no credentials, queries or cross-site
redirects. Page text is untrusted; signals are not proof of station ownership.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import http.client
import json
import re
import socket
import ssl
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from radio_catalog_logo_pilot_probe import checked_https_url
from radio_stream_technical_probe import validate_endpoint, public_resolved_ips
from radio_stream_recheck_ledger import parse_day, SHA256_RE
from radio_daily_qualification_dossiers import index, safe_digest

MAX_BYTES = 256 * 1024
MAX_PAGES = 8
MAX_INPUT = 12 * 1024 * 1024
ANALYZER_VERSION = 4
MAX_FOLLOWUP_PAGES = 2
TARGET = re.compile(r"\b(?:(?:heavy|black|death|thrash|doom|power|folk|pagan|nu|glam|hair|speed|progressive|symphonic|industrial|groove|alternative|extreme|sludge|stoner|gothic|viking|melodic)\s+metal|metal|metalcore|deathcore|grindcore|hard\s+rock|punk(?:\s+rock)?|hardcore\s+punk|punkrock|thrash|djent|nwobhm)\b")
ELECTRONIC = re.compile(r"\b(?:techno|electronic|edm|gabber|hardstyle|happy hardcore|drum and bass|rave|speedcore|uptempo hardcore|dubstep)\b")


def normalize(value):
    s = unicodedata.normalize("NFKD", str(value or "").casefold())
    return " ".join(re.sub(r"[^\w\s]", " ", "".join(c for c in s if not unicodedata.combining(c))).split())


def homepage_url(raw):
    try:
        p = validate_endpoint(raw)
        if p.scheme not in ("http", "https") or p.query or p.port not in (None, 80 if p.scheme == "http" else 443):
            return None
        # Upgrade a declared HTTP homepage; never downgrade TLS.
        url = urlunsplit(("https", p.hostname, p.path or "/", "", ""))
        checked_https_url(url, p.hostname)
        return url
    except (ValueError, TypeError):
        return None


def related_host(url, original):
    return (urlsplit(url).hostname or "").removeprefix("www.") == (urlsplit(original).hostname or "").removeprefix("www.")


def fetch_html(url):
    original = url
    deadline = time.monotonic() + 15
    for hop in range(3):
        if homepage_url(url) != url or not related_host(url, original):
            raise ValueError("unsafe homepage hop")
        host, target = checked_https_url(url, urlsplit(url).hostname)
        ip = public_resolved_ips(host, 443)[0]
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("homepage deadline")
        connection = http.client.HTTPSConnection(host, 443, timeout=min(5, remaining),
                                                  context=ssl.create_default_context())
        def pinned(address, timeout=None, source_address=None):
            if address != (host, 443):
                raise ValueError("unexpected socket target")
            return socket.create_connection((ip, 443), timeout=min(5, max(.1, deadline-time.monotonic())))
        connection._create_connection = pinned
        try:
            connection.request("GET", target, headers={"Accept": "text/html,application/xhtml+xml",
                "Accept-Encoding": "identity", "Connection": "close",
                "User-Agent": "GrossesOndesEditorialPreview/1.0 (+https://grosses-ondes.fr/)"})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                loc = response.getheader("Location")
                if not loc:
                    raise ValueError("missing redirect")
                target_url = urljoin(url, loc)
                if urlsplit(target_url).scheme != "https":
                    raise ValueError("TLS downgrade")
                url = target_url
                continue
            if response.status != 200 or (response.getheader("Content-Type") or "").split(";")[0].strip().lower() not in ("text/html", "application/xhtml+xml"):
                raise ValueError("not HTML")
            if (response.getheader("Content-Encoding") or "identity").lower() != "identity":
                raise ValueError("compressed response not supported")
            chunks = bytearray()
            while len(chunks) < MAX_BYTES:
                if time.monotonic() >= deadline:
                    raise TimeoutError("homepage deadline")
                chunk = response.read1(min(8192, MAX_BYTES-len(chunks)))
                if not chunk:
                    break
                chunks.extend(chunk)
            if not chunks:
                raise ValueError("empty HTML")
            return url, bytes(chunks)
        finally:
            connection.close()
    raise ValueError("redirect budget")


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignored = []
        self.section = None
        self.identity = []
        self.descriptions = []
        self.body = []
        self.images = []
        self.structured = []
        self.jsonld = None
        self.audio_urls = []
        self.in_audio = 0
        self.paragraphs = []
        self.paragraph = None
        self.links = []
        self.anchor = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and not self.ignored and (a.get("type") or "").lower().split(";")[0].strip() == "application/ld+json":
            self.jsonld = [] if len(self.structured) < 12 else None
        if tag in ("script", "style", "noscript", "template", "svg"):
            self.ignored.append(tag)
        if self.ignored:
            return
        if tag == "a" and a.get("href") and len(self.links) < 160:
            self.anchor = [a["href"][:1500], (a.get("title") or "")[:200]]
        if tag in ("title", "h1"):
            self.section = tag
            self.identity.append("")
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            value = a.get("content") or ""
            if key in ("og:title", "og:site_name"):
                self.identity.append(value[:500])
            if key in ("description", "og:description"):
                self.descriptions.append(value[:1000])
            if key in ("og:image", "og:image:secure_url"):
                self.images.append(value)
        if tag == "audio":
            self.in_audio += 1
        if tag == "p":
            self.paragraph = ""
        # Typed player declarations, not arbitrary links or executable JS.
        # An audio source inside video is not a radio player.
        if len(self.audio_urls) < 32:
            if (tag == "audio" or (tag == "source" and self.in_audio)) and a.get("src"):
                self.audio_urls.append(a["src"])
            elif tag == "a" and (a.get("type") or "").lower().startswith("audio/") and a.get("href"):
                self.audio_urls.append(a["href"])
            elif tag in ("audio", "button", "div") and a.get("data-stream-url"):
                self.audio_urls.append(a["data-stream-url"])
        if tag == "link" and "icon" in (a.get("rel") or "").lower().split():
            self.images.append(a.get("href") or "")

    def handle_endtag(self, tag):
        if self.ignored:
            if self.ignored[-1] == tag:
                self.ignored.pop()
                if tag == "script" and self.jsonld is not None:
                    raw = "".join(self.jsonld)
                    if len(raw) <= 32768:
                        try:
                            self.structured.append(json.loads(raw))
                        except (ValueError, RecursionError):
                            pass
                    self.jsonld = None
            return
        if tag == "a" and self.anchor is not None:
            if len(self.links) < 160:
                self.links.append(self.anchor)
            self.anchor = None
        if tag == "audio":
            self.in_audio = max(0, self.in_audio-1)
        if tag == "p" and self.paragraph is not None:
            if len(self.paragraphs) < 80:
                self.paragraphs.append(self.paragraph)
            self.paragraph = None
        if tag == self.section:
            self.section = None

    def handle_data(self, data):
        if self.ignored:
            if self.jsonld is not None and self.ignored[-1] == "script":
                self.jsonld.append(data[:32769])
            return
        if self.anchor is not None:
            self.anchor[1] = (self.anchor[1] + " " + data)[:300]
        if self.section and self.identity:
            self.identity[-1] = (self.identity[-1] + " " + data)[:500]
        if self.paragraph is not None:
            self.paragraph = (self.paragraph + " " + data)[:1500]
        if len(self.body) < 4000:
            self.body.append(data[:500])


def station_nodes(documents):
    """Only station/service entities, not unrelated articles or music albums."""
    pending = [(x, 0) for x in documents]
    count = 0
    while pending and count < 256:
        value, depth = pending.pop()
        count += 1
        if depth > 8:
            continue
        if isinstance(value, list):
            pending.extend((x, depth + 1) for x in value[:64])
        elif isinstance(value, dict):
            kinds = value.get("@type", [])
            if isinstance(kinds, str):
                kinds = [kinds]
            if isinstance(kinds, list) and any(
                isinstance(k, str) and k.rsplit("/", 1)[-1] in ("RadioStation", "BroadcastService")
                for k in kinds
            ):
                yield value
            for key in ("@graph", "mainEntity", "broadcastService"):
                if key in value:
                    pending.append((value[key], depth + 1))


def matches_identity(identity, value):
    return (len(identity) >= 5 and identity not in {"radio", "metal", "punk", "hard rock"}
            and " " + identity + " " in " " + normalize(value) + " ")


def format_text(value, identity):
    normalized = normalize(value)
    if identity:
        normalized = (" " + normalized + " ").replace(" " + identity + " ", " ").strip()
    return normalized


# Explicit station-level scope phrases, rather than keyword count or brand.
# More languages can extend these generic linguistic patterns independently.
SCOPE = re.compile(r"\b(?:24\s*7|24\s*(?:h|hours|heures)|around the clock|non stop|nonstop|all day|only|exclusively|dedicated to|speciali[sz]ed in|exclusivement|consacree? a|specialisee? dans|en continu|rund um die uhr|ausschliesslich|spezialisiert auf|dedicada? a|exclusivamente|todo el dia|sem parar)\b")
EPISODIC = re.compile(r"\b(?:show|episode|podcast|every (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|weekly|emission|chaque (?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)|hebdomadaire|sendung|programa semanal)\b")
NEGATION = re.compile(r"\b(?:not|no|never|without|sans|pas de|aucun|kein|ohne|sin|nunca)\b")
OTHER_FORMAT = re.compile(r"\b(?:indie|pop music|pop|hip hop|rap|jazz|classical|country|talk|news|variety|variete|reggae|dance music)\b")


def scope_terms(text, identity):
    value = format_text(text, identity)
    # Restrict scope to a single short declaration. A dedicated weekly show
    # or a negated genre must not certify a whole station.
    if len(value)>350 or EPISODIC.search(value) or NEGATION.search(value):
        return []
    if not SCOPE.search(value) or ELECTRONIC.search(value) or OTHER_FORMAT.search(value):
        return []
    return sorted(set(m.group() for m in TARGET.finditer(value)))[:20]


def inspect_page(name, url, body, stream_url=None):
    page = Page()
    page.feed(body.decode("utf-8", errors="replace"))
    identity = normalize(name)
    # Full normalized name, not arbitrary individual common words.
    # Very short names and generic labels are not enough to bind identity.
    identity_hit = any(matches_identity(identity, x) for x in page.identity)
    structured = []
    typed_genres = []
    for node in station_nodes(page.structured):
        if isinstance(node.get("name"), str) and normalize(node["name"]) == identity and matches_identity(identity, node["name"]):
            genres = node.get("genre", [])
            if isinstance(genres, str):
                genres = [genres]
            if isinstance(genres, list):
                accepted = [x[:200] for x in genres[:20] if isinstance(x, str)]
                typed_genres.extend(accepted)
                structured.extend(accepted)
            if isinstance(node.get("description"), str):
                structured.append(node["description"][:1000])
            # Exact URL only, on a matching typed station node.
            for key in ("contentUrl", "streamUrl"):
                if isinstance(node.get(key), str) and len(page.audio_urls) < 32:
                    page.audio_urls.append(node[key])
            identity_hit = True
    # A genre in the station name alone is not independent programme evidence.
    primary = " ".join(format_text(x, identity) for x in page.identity + page.descriptions + structured)
    visible = format_text(" ".join(page.body), identity)
    stream_match = False
    if isinstance(stream_url, str):
        try:
            validate_endpoint(stream_url)
            stream_match = any(urljoin(url, x) == stream_url for x in page.audio_urls)
        except ValueError:
            pass
    # Accept explicit station scope from typed genre declarations or from
    # ordinary HTML. A paragraph needs the station name in the same paragraph
    # (or matching player link and matching page identity).
    scope_sources = []
    scope = []
    genre_text = " ".join(normalize(x) for x in typed_genres)
    if (identity_hit and TARGET.search(genre_text) and not ELECTRONIC.search(genre_text)
            and not OTHER_FORMAT.search(genre_text) and not NEGATION.search(genre_text)):
        scope_sources.append("typed_station_genre")
        scope.extend(m.group() for m in TARGET.finditer(genre_text))
    if identity_hit:
        for text in page.descriptions + page.paragraphs:
            if not (matches_identity(identity, text) or stream_match):
                continue
            hits = scope_terms(text, identity)
            if hits:
                scope_sources.append("explicit_html_station_scope")
                scope.extend(hits)
    # Explicit terms in descriptions/title are stronger than body/navigation
    # hits, but never sufficient to approve editorial format.
    strong = sorted(set([m.group() for m in TARGET.finditer(primary)] + scope))[:20]
    weak = sorted(set(m.group() for m in TARGET.finditer(visible)))[:20]
    electronic = sorted(set(m.group() for m in ELECTRONIC.finditer(primary)))[:20]
    other_format = sorted(set(m.group() for m in OTHER_FORMAT.finditer(primary)))[:20]
    if electronic or other_format:
        scope_sources = []
        scope = []
    if strong and electronic:
        signal = "mixed_programme_indication"
    elif strong and identity_hit:
        signal = "identity_and_target_indication"
    elif electronic and not strong:
        signal = "electronic_indication"
    elif strong or weak:
        signal = "unbound_target_indication"
    else:
        signal = "no_format_evidence"
    images = []
    for value in page.images[:20]:
        candidate = urljoin(url, value)
        try:
            p = urlsplit(candidate)
            if p.query or not related_host(candidate, url):
                continue
            checked_https_url(candidate, p.hostname or "")
            images.append(safe_digest(candidate))
        except (ValueError, TypeError):
            continue
    return {"identityNameMatch": bool(identity_hit), "signal": signal,
            "structuredProgrammeEvidence": bool(structured),
            "programmeScopeEvidence": bool(scope_sources),
            "programmeScopeSources": sorted(set(scope_sources)),
            "programmeScopeTerms": sorted(set(scope))[:20],
            "otherFormatTerms": other_format,
            "declaredStreamLinked": stream_match,
            "primaryTargetTerms": strong, "visibleTargetTerms": weak,
            "primaryElectronicTerms": electronic, "pageSha256": hashlib.sha256(body).hexdigest(),
            "finalPageSha256": safe_digest(url), "imageHintSha256": sorted(set(images))[:8]}


# Follow only links actually present in the broadcaster's HTML, never a
# guessed URL or an arbitrary external search result. No recursive crawl.
FOLLOW_SCOPE = re.compile(r"\b(?:about|about us|about radio|our station|programme|programming|programacion|programacao|schedule|format|uber uns|programm|a propos|qui sommes nous|presentation|programmation|quienes somos|sobre nos|sobre nosotros|musica)\b")
FOLLOW_PLAYER = re.compile(r"\b(?:listen|listen live|player|live radio|ecouter|ecoute|en direct|ao vivo|escuchar|horen|webplayer)\b")
FOLLOW_EXCLUDE = re.compile(r"\b(?:podcast|episode|archive|login|register|privacy|contact|shop|donate|advertis|newsletter|download|facebook|instagram)\b")


def followup_links(url, body):
    page = Page()
    page.feed(body.decode("utf-8", errors="replace"))
    ranked = {}
    for href, label in page.links:
        try:
            candidate = urljoin(url, href)
            p = urlsplit(candidate)
            if p.scheme != "https" or p.query or p.fragment or not related_host(candidate, url):
                continue
            if homepage_url(candidate) != candidate or candidate == url:
                continue
            text = normalize(p.path + " " + label)
            if FOLLOW_EXCLUDE.search(text) or re.search(r"\.(?:pdf|mp3|aac|m3u8?|pls|jpg|png|zip)$", p.path, re.I):
                continue
            score = 2 if FOLLOW_SCOPE.search(text) else 1 if FOLLOW_PLAYER.search(text) else 0
            if score:
                ranked[candidate] = max(score, ranked.get(candidate, 0))
        except (ValueError, TypeError):
            continue
    # Reserve one slot for a player page where available.
    scope = sorted(u for u, score in ranked.items() if score == 2)
    player = sorted(u for u, score in ranked.items() if score == 1)
    return (scope[:1] + player[:1] + scope[1:] + player[1:])[:MAX_FOLLOWUP_PAGES]


def inspect_site(name, final, data, stream_url, children):
    root = inspect_page(name, final, data, stream_url)
    root["linkedPageEvidence"] = []
    if not root["identityNameMatch"]:
        return root
    for child_url, child_data in children:
        child = inspect_page(name, child_url, child_data, stream_url)
        if not child["identityNameMatch"]:
            continue
        root["linkedPageEvidence"].append({
            "pageSha256": child["pageSha256"],
            "finalPageSha256": child["finalPageSha256"],
            "programmeScopeEvidence": child["programmeScopeEvidence"],
            "declaredStreamLinked": child["declaredStreamLinked"],
        })
        for key in ("primaryTargetTerms", "visibleTargetTerms", "primaryElectronicTerms",
                    "otherFormatTerms", "programmeScopeTerms", "programmeScopeSources", "imageHintSha256"):
            root[key] = sorted(set(root[key] + child[key]))[:20 if key != "imageHintSha256" else 8]
        for key in ("structuredProgrammeEvidence", "programmeScopeEvidence", "declaredStreamLinked"):
            root[key] = root[key] or child[key]
    if root["primaryElectronicTerms"] or root["otherFormatTerms"]:
        root["programmeScopeEvidence"] = False
        root["programmeScopeTerms"] = []
        root["programmeScopeSources"] = []
    if root["primaryTargetTerms"]:
        root["signal"] = ("mixed_programme_indication" if root["primaryElectronicTerms"]
                          else "identity_and_target_indication")
    return root


def collect(discovery, reconciliation, *, previous=None, limit=0, fetch=fetch_html):
    day = parse_day(discovery.get("scanDate"))
    if (discovery.get("schemaVersion") != 1 or discovery.get("publicationAllowed") is not False
            or reconciliation.get("schemaVersion") != 1 or reconciliation.get("scanDate") != day
            or reconciliation.get("automaticAdmissionAllowed") is not False
            or reconciliation.get("catalogChanged") is not False or not 0 <= limit <= MAX_PAGES):
        raise ValueError("invalid editorial inputs")
    rows, rec = index(discovery, "candidates"), index(reconciliation, "candidates")
    if set(rows) != set(rec):
        raise ValueError("mismatched UUIDs")
    old = {}
    if previous is not None:
        if (previous.get("schemaVersion") != 1 or previous.get("publicationAllowed") is not False
                or previous.get("editoriallyApprovedCount") != 0 or parse_day(previous["scanDate"]) > day):
            raise ValueError("invalid previous editorial report")
        old = index(previous, "records")
        for x in old.values():
            if (x.get("editorialApproved") is not False or x.get("publicationAllowed") is not False
                    or parse_day(x["observedDate"]) > day
                    or not SHA256_RE.fullmatch(x.get("homepageSha256") or "")):
                raise ValueError("invalid prior editorial evidence")
    result = {uid: dict(x, observedInScan=False) for uid, x in old.items() if uid not in rows}
    groups = {}
    for uid, row in sorted(rows.items()):
        if rec[uid]["classification"] != "unmapped_candidate":
            continue
        url = homepage_url(row.get("homepage"))
        if not url:
            continue
        digest = safe_digest(url)
        prior = old.get(uid)
        if prior and prior["homepageSha256"] == digest and prior.get("identityNameSha256") == safe_digest(normalize(row.get("name"))):
            result[uid] = dict(prior, observedInScan=True)
            age = (dt.date.fromisoformat(day) - dt.date.fromisoformat(prior["observedDate"])).days
            if prior.get("analyzerVersion") == ANALYZER_VERSION and age < (7 if prior.get("retrieval") == "html_observed" else 1):
                # A changed stream URL invalidates even a cached link match.
                if prior.get("streamSha256") == safe_digest(row.get("streamUrl")):
                    continue
            if prior.get("analyzerVersion") != ANALYZER_VERSION or prior.get("streamSha256") != safe_digest(row.get("streamUrl")):
                result[uid] = dict(result[uid], signal="stale_analyzer_or_stream_review", declaredStreamLinked=False, programmeScopeEvidence=False)
        groups.setdefault(url, []).append((uid, row))
    # Previously untested URLs first; repeated failures cannot monopolize queue.
    # Refresh previously promising pages first, then alternate fresh discovery
    # and stale analyzer rows so an upgrade cannot monopolize the crawl.
    promising = [u for u in groups if any(old.get(uid, {}).get("signal") == "identity_and_target_indication"
                  or old.get(uid, {}).get("declaredStreamLinked") is True for uid, _ in groups[u])]
    promising = sorted(promising)[:max(1, limit//2)] if limit else []
    remaining = sorted(set(groups)-set(promising))
    fresh_pages = [u for u in remaining if any(uid not in result for uid,_ in groups[u])]
    refresh_pages = [u for u in remaining if u not in fresh_pages]
    queue = list(promising)
    while len(queue) < limit and (fresh_pages or refresh_pages):
        if fresh_pages and len(queue)<limit:
            queue.append(fresh_pages.pop(0))
        if refresh_pages and len(queue)<limit:
            queue.append(refresh_pages.pop(0))
    def request(url):
        try:
            final, data = fetch(url)
            if (homepage_url(final) != final or not related_host(final, url)
                    or not isinstance(data, bytes) or not 0 < len(data) <= MAX_BYTES):
                raise ValueError("invalid response")
            children = []
            for link in followup_links(final, data):
                try:
                    child_url, child_data = fetch(link)
                    if (homepage_url(child_url) == child_url and related_host(child_url, final)
                            and child_url != final and isinstance(child_data, bytes)
                            and 0 < len(child_data) <= MAX_BYTES
                            and child_url not in {u for u, _ in children}):
                        children.append((child_url, child_data))
                except Exception:
                    continue
            return url, final, data, children
        except Exception:
            return url, None, None, []
    followup_count = 0
    with ThreadPoolExecutor(max_workers=3) as pool:
        for url, final, data, children in pool.map(request, queue):
            followup_count += len(children)
            for uid, row in groups[url]:
                try:
                    evidence = inspect_site(row.get("name"), final, data, row.get("streamUrl"), children) if data else {}
                except (ValueError, TypeError, RecursionError):
                    data_for_row = None
                    evidence = {}
                else:
                    data_for_row = data
                result[uid] = {"stationuuid": uid, "homepageSha256": safe_digest(url),
                    "identityNameSha256": safe_digest(normalize(row.get("name"))),
                    "reportedHost": urlsplit(url).hostname, "observedDate": day,
                    "observedInScan": True, "retrieval": "html_observed" if data_for_row else "failed_review",
                    "analyzerVersion": ANALYZER_VERSION, "streamSha256": safe_digest(row.get("streamUrl")),
                    "editorialApproved": False, "publicationAllowed": False, **evidence}
    records = [result[uid] for uid in sorted(result)]
    for row in records:
        if row.get("analyzerVersion") != ANALYZER_VERSION:
            row["signal"] = "stale_analyzer_or_stream_review"
            row["declaredStreamLinked"] = False
            row["programmeScopeEvidence"] = False
    if len(records) > 20000:
        raise ValueError("editorial register capacity")
    return {"schemaVersion": 1, "scanDate": day, "publicationAllowed": False,
            "editoriallyApprovedCount": 0, "attemptedPageCount": len(queue),
            "linkedPagesFetched": followup_count,
            "htmlObservedCount": sum(x["retrieval"] == "html_observed" for x in records),
            "identityTargetCount": sum(x.get("signal") == "identity_and_target_indication" for x in records),
            "structuredProgrammeCount": sum(x.get("analyzerVersion") == ANALYZER_VERSION and x.get("structuredProgrammeEvidence") is True for x in records),
            "programmeScopeCount": sum(x.get("analyzerVersion") == ANALYZER_VERSION and x.get("programmeScopeEvidence") is True for x in records),
            "declaredStreamLinkedCount": sum(x.get("declaredStreamLinked") is True for x in records),
            "records": records}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("discovery", "reconciliation", "output"):
        p.add_argument("--" + key, type=Path, required=True)
    p.add_argument("--previous", type=Path)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--allow-network", action="store_true")
    a = p.parse_args()
    if a.limit and not a.allow_network:
        p.error("network must be explicitly enabled")
    def load(path):
        if path.stat().st_size > MAX_INPUT:
            raise ValueError("input size exceeded")
        return json.loads(path.read_text())
    report = collect(load(a.discovery), load(a.reconciliation),
                     previous=load(a.previous) if a.previous else None, limit=a.limit)
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if len(output.encode("utf-8")) > MAX_INPUT:
        raise ValueError("output size exceeded")
    a.output.write_text(output, encoding="utf-8")
    print("RADIO_EDITORIAL_PREVIEW_ONLY", {k: v for k, v in report.items() if k != "records"})


if __name__ == "__main__":
    main()
