"""Publisher proof for previously unknown festivals linked by a public directory.

A directory entry proves only an attributed first-party website link, never
2027 dates, venue or a festival publication. The publisher reconstructs the
directory URL from the edition NAME (not an untrusted private URL), independently
fetches the page, extracts one visible attributed official website and then
independently checks the precise future edition on that site's DNS-pinned HTTPS.
No named-festival allowlist; malformed, ambiguous and conflicting claims fail
closed. The public addition contains no inferred artists, venue or map pin.
"""
from __future__ import annotations

from datetime import date
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

from dns_pinned_https import fetch_public_html, safe_public_url
from source_qualification import Anchors, normalized, visible_text
from grossesondes_institutional_linked_edition import prove_dates
from grossesondes_institutional_edition import (
    slug_for, conflicts_with_signed_catalogue,
)
from grossesondes_structured_edition import ROW_KEYS, PRIVATE_KEYS

PROOF_MODE = "generic-directory-first-party-edition.v1"
DIRECTORY = "https://www.festivalenfrance.com/festival/"
PRIVATE_NOTES = (
    "Site officiel lié par un annuaire indépendant ; dates actuelles "
    "et genre à revérifier par le publisher. Lieu, artistes et coordonnées inconnus."
)
PUBLISHED_NOTES = (
    "Lien vers le site du festival retrouvé dans un annuaire public puis "
    "dates et genre revérifiés directement sur le site officiel. "
    "Lieu exact, artistes et coordonnées à confirmer."
)
PRIVATE_STATUS = "Provenance et édition en attente de recontrôle indépendant"
PUBLISHED_STATUS = "Provenance et édition revérifiées indépendamment"
PRIVATE_CONFIDENCE = "Annuaire public (site lié) + preuve primaire en attente"
PUBLISHED_CONFIDENCE = "Annuaire public (lien vérifié) + site officiel (dates)"
GENRE = re.compile(r"\b(?:metal|hard rock|punk|rock|hardcore|stoner|doom|"
                   r"sludge|grindcore|deathcore|metalcore|black metal|"
                   r"thrash metal|heavy metal)\b")
CANCELLED = re.compile(
    r"\b(?:edition|festival)\s+20[2-4][0-9]\s+"
    r"(?:annulee?|reporte[e]?|cancelled|postponed)\b"
)


class Heading(HTMLParser):
    """Visible h1 text only, with concealed ancestors ignored."""
    HIDDEN_TAGS = {"script", "style", "template", "noscript", "svg"}
    VOID = {"area", "base", "br", "col", "embed", "hr", "img",
            "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.current = None
        self.headings = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        style = (attributes.get("style") or "").replace(" ", "").lower()
        parent_hidden = bool(self.stack and self.stack[-1][1])
        hidden = (parent_hidden or tag in self.HIDDEN_TAGS
                  or "hidden" in attributes
                  or attributes.get("aria-hidden") == "true"
                  or "display:none" in style)
        if tag not in self.VOID:
            self.stack.append((tag, hidden))
        if tag == "h1" and not hidden:
            self.current = []

    def handle_data(self, value):
        if (self.current is not None and
                self.stack and not self.stack[-1][1]):
            self.current.append(value)

    def handle_endtag(self, tag):
        if tag == "h1" and self.current is not None:
            self.headings.append(normalized(" ".join(self.current)))
            self.current = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

def directory_url(title):
    if not isinstance(title, str) or not 8 <= len(title) <= 150:
        return None
    m = re.fullmatch(r"(.{7,130}?)\s+(20[2-4][0-9])", title.strip())
    if m is None:
        return None
    label = "".join(normalized(m.group(1)).split())
    if not re.fullmatch(r"[a-z][a-z0-9]{7,75}", label):
        return None
    return DIRECTORY + label


def trusted_linked_site(directory_html, title):
    """Exact visible h1 and an unambiguous labelled external website."""
    if (directory_url(title) is None or not isinstance(directory_html, str)
            or not 0 < len(directory_html) <= 650_000):
        return None
    header = Heading()
    anchors = Anchors()
    try:
        header.feed(directory_html)
        header.close()
        anchors.feed(directory_html)
        anchors.close()
    except (ValueError, TypeError, UnicodeError):
        return None
    base = normalized(title.rsplit(" ", 1)[0])
    if header.headings.count(base) != 1:
        return None
    urls = set()
    for href, label, prefix in anchors.anchors[:700]:
        if not isinstance(href, str) or not isinstance(label, str):
            continue
        if safe_public_url(href) is None:
            continue
        parts = urlsplit(href)
        if parts.scheme != "https" or parts.username or parts.password or (
                parts.path not in ("", "/") or parts.query or parts.fragment):
            continue
        host = parts.hostname or ""
        if host in ("www.festivalenfrance.com", "festivalenfrance.com"):
            continue
        # Link text must name the destination or its exact editorial role.
        link = normalized(label)
        context = normalized(prefix)
        hostname = normalized(host.removeprefix("www."))
        role = ("site web" in context or "site officiel" in context
                or link in ("site web", "site officiel"))
        # A labelled link to a different host is a conflict even when a
        # preceding list item labels it "site web".
        if not (role and
                link in (hostname, normalized(host), "site web", "site officiel")):
            continue
        if not re.search(r"\b(?:site web|site officiel)\b", context + " " + link):
            continue
        canonical = "https://" + host + "/"
        if safe_public_url(canonical) is None:
            continue
        urls.add(canonical)
    return next(iter(urls)) if len(urls) == 1 else None


def verify_primary(html, title, year, today):
    if not isinstance(html, str):
        return None
    dates = prove_dates(html, title, year, today)
    if dates is None:
        return None
    try:
        words = visible_text(html)
    except (TypeError, ValueError, UnicodeError):
        return None
    if (not GENRE.search(words) or "festival" not in words
            or CANCELLED.search(words)):
        return None
    return dates


def private_proposal(title, site, dates, today):
    if (directory_url(title) is None or slug_for(title) is None
            or not isinstance(site, str) or safe_public_url(site) is None):
        return None
    try:
        parts = urlsplit(site)
        if (parts.scheme != "https" or not parts.hostname
                or parts.username or parts.password or parts.port
                or parts.path != "/" or parts.query or parts.fragment
                or site != "https://" + parts.hostname + "/"):
            return None
    except (TypeError, ValueError):
        return None
    try:
        start, end = map(date.fromisoformat, dates)
        current = date.fromisoformat(today)
    except (TypeError, ValueError):
        return None
    year = int(title.rsplit(" ", 1)[-1])
    if (not current <= start <= end or start.year != year
            or end.year != year or (end - start).days > 7
            or safe_public_url(site) is None):
        return None
    return {
        "slug": slug_for(title), "name": title,
        "startDate": start.isoformat(), "endDate": end.isoformat(),
        "city": None, "department": None, "region": None, "venue": None,
        "lat": None, "lon": None, "showOnMap": False,
        "dateRangeIsContinuous": False, "lineup": [], "bands": 0,
        "price": None, "status": "Annoncé",
        "officialSite": site, "source": site,
        "lastVerified": today, "notes": PRIVATE_NOTES,
        "verificationStatus": PRIVATE_STATUS,
        "sourceConfidence": PRIVATE_CONFIDENCE,
        "proofMode": PROOF_MODE, "originSlug": directory_url(title),
        "evidence": [directory_url(title), site], "verified_at": today,
    }


def validate_private_proposal(row, today):
    if not isinstance(row, dict) or set(row) != ROW_KEYS | PRIVATE_KEYS:
        return None
    try:
        observed = date.fromisoformat(row["verified_at"])
        if (observed > date.fromisoformat(today)
                or (date.fromisoformat(today) - observed).days > 7):
            return None
    except (TypeError, ValueError, KeyError):
        return None
    if (not isinstance(row.get("evidence"), list)
            or len(row["evidence"]) != 2
            or row["evidence"] != [directory_url(row.get("name")),
                                    row.get("officialSite")]
            or row.get("originSlug") != directory_url(row.get("name"))):
        return None
    expected = private_proposal(
        row.get("name"), row.get("officialSite"),
        (row.get("startDate"), row.get("endDate")), row["verified_at"])
    return expected if expected == row else None


def validate_verified_row(proposal, verified, today):
    if validate_private_proposal(proposal, today) is None:
        return None
    expected = {key: proposal[key] for key in ROW_KEYS}
    expected.update(
        verificationStatus=PUBLISHED_STATUS,
        sourceConfidence=PUBLISHED_CONFIDENCE,
        notes=PUBLISHED_NOTES,
    )
    return expected if verified == expected else None


def independently_verify(proposal, today, directory_fetch=fetch_public_html,
                         organizer_fetch=fetch_public_html):
    """Never fetch proposed organizer URL until rederived from fixed directory."""
    if validate_private_proposal(proposal, today) is None:
        return None
    url = directory_url(proposal["name"])
    try:
        document = directory_fetch(url)
        site = trusted_linked_site(document, proposal["name"])
        if site is None or site != proposal["officialSite"]:
            return None
        html = organizer_fetch(site)
    except (OSError, ValueError, TypeError, UnicodeError, KeyError):
        return None
    year = int(proposal["name"].rsplit(" ", 1)[-1])
    dates = verify_primary(html, proposal["name"], year, today)
    if dates != (proposal["startDate"], proposal["endDate"]):
        return None
    approved = {key: proposal[key] for key in ROW_KEYS}
    approved.update(
        verificationStatus=PUBLISHED_STATUS,
        sourceConfidence=PUBLISHED_CONFIDENCE,
        notes=PUBLISHED_NOTES,
    )
    return approved
