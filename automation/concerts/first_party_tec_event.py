"""Read one official The Events Calendar event through its own same-origin API.

This is NOT a venue/artist allowlist or a publisher authorization. The public
event page must bind an exact WordPress post ID and its unique visible H1 to
the REST response on the SAME HTTPS origin. The independent Publisher repeats
these same requests with DNS-pinned TLS/robots checks before signing.
"""
from __future__ import annotations

import datetime as dt
from html import escape
import json
import re
from urllib.parse import urlsplit

import official_html_evidence

_BODY = re.compile(r"<body\b[^>]{0,9000}>", re.I | re.S)
_CLASSES = re.compile(r"\bclass\s*=\s*(['\"])([^'\"]{1,8000})\1", re.I | re.S)
_ID = re.compile(r"(?<![\w-])postid-([1-9][0-9]{0,11})(?![0-9])")
_DATE = re.compile(r"20[0-9]{2}-[01][0-9]-[0-3][0-9] [0-2][0-9]:[0-5][0-9]:[0-5][0-9]\Z")


def _body_post_id(html):
    if not isinstance(html, str) or len(html) > 1_000_000:
        return None
    match = _BODY.search(html)
    if match is None:
        return None
    classes = _CLASSES.search(match.group())
    if classes is None:
        return None
    found = _ID.findall(classes.group(2))
    return found[0] if len(found) == 1 else None


def read(html, url, fetch, *, normalize, artists_from_description):
    """Return a single fully bound Event, None when the source has no TEC ID.

    fetch is injected by the caller and MUST enforce pinned public HTTPS,
    same-URL/no redirects, robots and an upper byte bound. It receives only a
    SAME-ORIGIN fixed-shape HTTPS URL with the numeric ID from the page body.
    """
    ident = _body_post_id(html)
    if ident is None:
        return None
    if not isinstance(url, str):
        raise ValueError("Invalid official event URL")
    parts = urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.username
            or parts.password or parts.port or parts.query or parts.fragment
            or not parts.path.strip("/")):
        raise ValueError("Unsafe official event URL")
    origin = "https://" + parts.hostname
    api = origin + "/wp-json/tribe/events/v1/events/" + ident
    body = fetch(api)
    if not isinstance(body, str) or not 30 <= len(body) <= 350_000:
        raise ValueError("Official event API missing or oversized")
    try:
        row = json.loads(body)
    except (ValueError, TypeError) as ex:
        raise ValueError("Invalid same-origin official event API") from ex
    if not isinstance(row, dict):
        raise ValueError("Official event API not an event object")
    if (type(row.get("id")) is not int or str(row["id"]) != ident
            or row.get("url") != url or row.get("status") != "publish"):
        raise ValueError("Official API event identity or publication state differs")
    title = row.get("title")
    description = row.get("description")
    start = row.get("start_date")
    if (not isinstance(title, str) or not 3 <= len(title) <= 1000
            or not isinstance(description, str)
            or not 50 <= len(description) <= 250_000
            or not isinstance(start, str) or not _DATE.fullmatch(start)):
        raise ValueError("Official API title, date or description missing")
    try:
        dt.datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
    except ValueError as ex:
        raise ValueError("Invalid official event date") from ex
    # The actual article, not the API alone, must name this very event.
    page = official_html_evidence.VisibleBlocks()
    page.feed(html)
    page.close()
    headings = [v for k, v in page.blocks if k == "h1"]
    if len(headings) != 1 or normalize(headings[0]) != normalize(title):
        raise ValueError("Official event page headline differs from same-origin API")
    # Only the named artists' genre-labelled headings of THIS one official
    # event description qualify. Marketing and unrelated biographies cannot.
    synthetic = "<main><h1>" + escape(title) + "</h1>" + description + "</main>"
    performers = artists_from_description(synthetic, title)
    if not performers:
        raise ValueError("Complete official artist bill not found in event API")
    venue = row.get("venue")
    if not isinstance(venue, dict):
        raise ValueError("Official event venue absent")
    name = venue.get("venue")
    city = venue.get("city")
    postcode = str(venue.get("zip") or "")
    street = venue.get("address")
    country = venue.get("country_code") or venue.get("country")
    region = venue.get("province") or ""
    if (not all(isinstance(v, str) and v.strip()
                for v in (name, city, street, country))
            or not re.fullmatch(r"[0-9]{5}", postcode)
            or normalize(country) not in ("fr", "france", "republique francaise")):
        raise ValueError("Official event postal venue identity incomplete")
    # A punctuation comma immediately after the house number is typographic,
    # not a changed number, street, postcode or municipality.
    street = re.sub(r"^([0-9]{1,5})\s*,\s*", r"\1 ", street.strip())
    return {
        "@type": "Event", "url": url, "name": title,
        "startDate": start.replace(" ", "T"),
        "performer": performers,
        "location": {
            "@type": "Place", "name": name,
            "address": {
                "@type": "PostalAddress",
                "streetAddress": street, "addressLocality": city,
                "postalCode": postcode, "addressCountry": country,
                "addressRegion": region if isinstance(region, str) else "",
            },
        },
    }


def compatible(existing, official, normalize, iso_day):
    """A partial schema.org Event must not be silently contradicted by API."""
    if not isinstance(existing, dict) or not isinstance(official, dict):
        return False
    if existing.get("performer") not in (None, "", []):
        return False
    if existing.get("url") not in (None, "", official["url"]):
        return False
    if existing.get("name") and normalize(existing["name"]) != normalize(
            official["name"]):
        return False
    if existing.get("startDate") and iso_day(
            existing["startDate"]) != iso_day(official["startDate"]):
        return False
    status = str(existing.get("eventStatus") or "").lower()
    if any(x in status for x in ("cancel", "postpon", "resched", "report", "annul")):
        return False
    place = existing.get("location")
    if place is not None:
        if not isinstance(place, dict):
            return False
        if place.get("name") and normalize(place["name"]) != normalize(
                official["location"]["name"]):
            return False
        addr = place.get("address")
        if addr is not None:
            if not isinstance(addr, dict):
                return False
            verified_addr = official["location"]["address"]
            for key in ("addressLocality", "postalCode"):
                if addr.get(key) and normalize(addr[key]) != normalize(
                        verified_addr[key]):
                    return False
    return True
