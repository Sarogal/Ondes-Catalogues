"""Bounded same-origin sitemap programme discovery, research only.

A sitemap URL is never evidence of edition identity or artist names.
No browser policy change, guessed programme paths, redirects or private leads.
"""
import re
import ssl
from urllib.parse import urlsplit
from xml.etree import ElementTree

from dns_pinned_https import DNSPinnedHTTPSConnection, safe_public_url

MAX_XML = 350_000
MAX_LOCS = 1000
NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
PROGRAMME = re.compile(
    r"/(?:lineup|line-up|programme|programmation|program|artists|artistes)/?$",
    re.I)


def sitemap_url(site):
    if not isinstance(site, str) or safe_public_url(site) != site:
        return None
    return "https://" + urlsplit(site).hostname + "/sitemap.xml"


def read_sitemap(url):
    if not isinstance(url, str) or sitemap_url(url) != url:
        raise ValueError("Invalid sitemap origin")
    host = urlsplit(url).hostname
    conn = DNSPinnedHTTPSConnection(host, port=443, timeout=8,
                                    context=ssl.create_default_context())
    try:
        conn.request("GET", "/sitemap.xml",
                     headers={"User-Agent": "GrossesOndesSitemapResearch/1.0",
                              "Accept": "application/xml,text/xml",
                              "Accept-Encoding": "identity"})
        response = conn.getresponse()
        if (response.status != 200
                or response.getheader("Content-Encoding", "identity").lower() != "identity"
                or response.getheader("Content-Type", "").split(";", 1)[0].lower().strip()
                   not in ("application/xml", "text/xml")):
            return None
        body = response.read(MAX_XML + 1)
        return body if len(body) <= MAX_XML else None
    finally:
        conn.close()


def programme_urls(site, data):
    """Direct sitemap URL set only; no DTD, indexes, nested requests or redirects."""
    if (sitemap_url(site) is None or not isinstance(data, bytes)
            or not 0 < len(data) <= MAX_XML):
        return []
    try:
        # UTF-8 only avoids alternative encodings concealing XML declarations.
        text = data.decode("utf-8", errors="strict")
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", text, re.I) or "\x00" in text:
            return []
        root = ElementTree.fromstring(text)
        if root.tag != NS + "urlset" or len(root) > MAX_LOCS:
            return []
        host = urlsplit(site).hostname
        selected = set()
        for entry in root:
            if entry.tag != NS + "url":
                continue
            locs = entry.findall(NS + "loc")
            if len(locs) != 1 or len(locs[0]) or not locs[0].text:
                continue
            url = locs[0].text.strip()
            if safe_public_url(url) != url:
                continue
            path = urlsplit(url).path
            if (urlsplit(url).hostname != host or url == site
                    or "%" in path or ".." in path.split("/")
                    or re.search(r"/(?:20[01]\d|202[0-6])(?:/|$)", path)
                    or not PROGRAMME.search(path)):
                continue
            selected.add(url)
        return sorted(selected)[:2]
    except (ValueError, TypeError, UnicodeError, ElementTree.ParseError, RecursionError):
        return []


def discover_programme_urls(site, *, fetch=read_sitemap):
    """One fixed HTTPS endpoint for a caller-validated official site."""
    url = sitemap_url(site)
    if url is None:
        return []
    try:
        return programme_urls(site, fetch(url))
    except (OSError, TimeoutError, ValueError, TypeError, UnicodeError):
        return []
