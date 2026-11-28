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


def valid_xml_url(url):
    if not isinstance(url, str) or safe_public_url(url) != url:
        return False
    path = urlsplit(url).path
    return (len(path) <= 500 and "%" not in path
            and all(part not in (".", "..") for part in path.split("/"))
            and re.fullmatch(r"/[A-Za-z0-9_./-]+\.xml", path, re.I) is not None)


def read_sitemap(url):
    # The initial URL is fixed by sitemap_url; children may only originate
    # in a bounded, same-host index parsed by discover_programme_urls.
    if not valid_xml_url(url):
        raise ValueError("Invalid sitemap URL")
    host = urlsplit(url).hostname
    conn = DNSPinnedHTTPSConnection(host, port=443, timeout=8,
                                    context=ssl.create_default_context())
    try:
        conn.request("GET", urlsplit(url).path,
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


def xml_root(data):
    """Reject oversized or non-UTF-8 XML, entities and DTDs before parsing."""
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_XML:
        return None
    try:
        text = data.decode("utf-8", errors="strict")
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", text, re.I) or "\x00" in text:
            return None
        root = ElementTree.fromstring(text)
        return root if len(root) <= MAX_LOCS else None
    except (ValueError, TypeError, UnicodeError, ElementTree.ParseError, RecursionError):
        return None


def programme_urls(site, data):
    """Direct sitemap URL set only; an index is not a programme page."""
    if sitemap_url(site) is None:
        return []
    try:
        root = xml_root(data)
        if root is None or root.tag != NS + "urlset":
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


def index_children(site, data):
    """Same-host XML files explicitly nominated by the root index."""
    if sitemap_url(site) is None:
        return []
    root = xml_root(data)
    if root is None or root.tag != NS + "sitemapindex":
        return []
    host = urlsplit(site).hostname
    selected = set()
    for entry in root:
        if entry.tag != NS + "sitemap":
            continue
        locs = entry.findall(NS + "loc")
        if len(locs) != 1 or len(locs[0]) or not locs[0].text:
            continue
        url = locs[0].text.strip()
        if (valid_xml_url(url) and urlsplit(url).hostname == host
                and url != sitemap_url(site)):
            selected.add(url)
    return sorted(selected)


def discover_programme_urls(site, *, fetch=read_sitemap, tick=0):
    """At most two XML reads: one fixed root, one rotating indexed child.

    No nested indexes, arbitrary candidate URL, cross-host redirects or
    further request when the root/child cannot be fetched.
    """
    url = sitemap_url(site)
    if url is None or type(tick) is not int or tick < 0:
        return []
    try:
        raw = fetch(url)
        direct = programme_urls(site, raw)
        if direct:
            return direct
        children = index_children(site, raw)
        if not children:
            return []
        return programme_urls(site, fetch(children[tick % len(children)]))
    except (OSError, TimeoutError, ValueError, TypeError, UnicodeError):
        return []
