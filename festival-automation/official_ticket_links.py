"""Discover ticket-provider links from already registered festival official pages.

Links are editorial leads only. They are never fetched as trusted sources,
never converted to category availability, and never published automatically.
"""
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

PROVIDERS = {
    "helloasso.com": "HelloAsso",
    "billetweb.fr": "Billetweb",
    "shotgun.live": "Shotgun",
    "shotguntheapp.com": "Shotgun",
    "weezevent.com": "Weezevent",
    "festik.net": "Festik",
    "fnacspectacles.com": "Fnac Spectacles",
    "mapado.com": "Mapado",
}


class TicketAnchors(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            href = next((value for name, value in attrs if name.lower() == "href"), None)
            if isinstance(href, str) and 0 < len(href) <= 2048:
                self.hrefs.append(href)


def provider_for_host(hostname):
    host = (hostname or "").lower().rstrip(".")
    for domain, name in PROVIDERS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return None


def ticket_link_leads(html, source_url, permitted_url, limit=6):
    """Return bounded, de-duplicated URL leads without authorizing a single ticket.

    A link on the organiser's page indicates a possible point of sale, not the
    edition, year, price, category, inventory or official vendor relationship.
    """
    if (not isinstance(html, str) or len(html) > 650_000
            or not permitted_url(source_url) or not 1 <= limit <= 12):
        return []
    parser = TicketAnchors()
    parser.feed(html)
    seen, leads = set(), []
    for raw in parser.hrefs[:500]:
        if any(ord(char) < 32 for char in raw):
            continue
        try:
            candidate = urljoin(source_url, raw.strip())
            parsed = urlsplit(candidate)
        except (TypeError, ValueError):
            continue
        provider = provider_for_host(parsed.hostname)
        if not provider or not permitted_url(candidate):
            continue
        # Never write possible account tokens, referral codes or fragments into
        # an artifact. A bare provider homepage is not a festival ticket lead.
        cleaned = parsed._replace(query="", fragment="").geturl()
        if not permitted_url(cleaned) or parsed.path in ("", "/"):
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        leads.append({"ticket_url": cleaned, "provider": provider,
                      "verification_status": "LINK_ONLY",
                      "publication_authorized": False})
        if len(leads) >= limit:
            break
    return leads
