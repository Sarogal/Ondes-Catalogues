"""Independent OpenAgenda -> attributed festival website -> official-edition proof.

OpenAgenda is an *additional* public provenance route, not a closed roster or
an edition authority. Neither private dates nor a private website URL may
authorize publication. The Publisher re-fetches the exact public OpenAgenda
event, derives ONE visible official festival website, then independently
rechecks first-party festival identity, genre and dates over DNS-pinned HTTPS.
All published rows are map-free until a separate geo proof succeeds.
"""
from __future__ import annotations

from datetime import date
import re
from urllib.parse import urlsplit

from dns_pinned_https import fetch_public_html, safe_public_url
from grossesondes_generic_directory_edition import (
    Heading, verify_official_site_pages,
    private_proposal as directory_proposal,
)
from grossesondes_institutional_edition import slug_for
from grossesondes_structured_edition import ROW_KEYS, PRIVATE_KEYS
from source_qualification import Anchors, normalized, classify

PROOF_MODE = "generic-openagenda-first-party-edition.v1"
PRIVATE_NOTES = ("Lien officiel repéré dans une fiche publique OpenAgenda ; "
                 "dates et genre à revérifier. Lieu, artistes et GPS inconnus.")
PUBLISHED_NOTES = ("Site de festival retrouvé dans une fiche OpenAgenda et "
                   "édition revérifiée sur le site officiel ; lieu, artistes "
                   "et coordonnées à confirmer.")
PRIVATE_STATUS = "Attribution OpenAgenda en attente de vérification indépendante"
PUBLISHED_STATUS = "Site et édition revérifiés indépendamment"
PRIVATE_CONFIDENCE = "OpenAgenda (site lié) + site officiel à revérifier"
PUBLISHED_CONFIDENCE = "OpenAgenda (lien recontrôlé) + site officiel (dates)"
OA_PATH = re.compile(r"/(?:[a-z]{2}/)?[a-z0-9-]+/events/[a-z0-9-]+")
SITE_LABELS = frozenset(("site officiel", "site web", "site internet",
                         "site du festival"))
ALLOWED_ROLES = frozenset(("UNKNOWN", "ORGANIZER_CANDIDATE"))


def event_url(url):
    """One real OpenAgenda EVENT on its sole public origin; no path tricks."""
    if not isinstance(url, str) or not 20 <= len(url) <= 500:
        return None
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.netloc != "openagenda.com"
                or parsed.query or parsed.fragment
                or OA_PATH.fullmatch(parsed.path) is None):
            return None
    except (TypeError, ValueError):
        return None
    return url if safe_public_url(url) == url else None


def attributed_site(event_html, title, url):
    """One exact visible event h1 + unique labelled festival website root.

    The event platform's URLs, tickets, other events and hidden links are
    never site attribution. Source HTML merely nominates a host; primary
    dates must subsequently be proven on that host independently.
    """
    if (event_url(url) is None or not isinstance(event_html, str)
            or not 0 < len(event_html) <= 650_000
            or not isinstance(title, str)
            or not re.fullmatch(r".{7,150}\s20[2-4][0-9]", title)):
        return None
    heading, anchors = Heading(), Anchors()
    try:
        heading.feed(event_html)
        heading.close()
        anchors.feed(event_html)
        anchors.close()
    except (ValueError, TypeError, UnicodeError):
        return None
    base = normalized(title.rsplit(" ", 1)[0])
    from national_openagenda_research import provider_title_matches
    edition_year = int(title.rsplit(" ", 1)[-1])
    if len(base) < 7 or sum(
            provider_title_matches(x, title, edition_year)
            for x in heading.headings) != 1:
        return None
    # Avoid attributing a site for a different edition via an old OA page.
    from grossesondes_official_html_edition import VisibleText, fold
    visible = VisibleText()
    try:
        visible.feed(event_html)
        visible.close()
        words = " ".join(fold(" ".join(visible.parts)).split())
    except (TypeError, ValueError, UnicodeError):
        return None
    year = title.rsplit(" ", 1)[-1]
    if re.search(r"(?<![0-9])" + re.escape(year) + r"(?![0-9])", words) is None:
        return None
    sites = set()
    for href, label, prefix in anchors.anchors[:500]:
        if not isinstance(href, str) or not isinstance(label, str):
            continue
        label_key = normalized(label)
        context = normalized(prefix[-180:]) if isinstance(prefix, str) else ""
        role = (label_key in SITE_LABELS or
                ("site officiel" in context and
                 label_key.startswith("www ")))
        if not role or safe_public_url(href) is None:
            continue
        parts = urlsplit(href)
        if (parts.scheme != "https" or parts.username or parts.password
                or parts.port is not None
                or not parts.path.startswith("/")
                or parts.query or parts.fragment
                or parts.hostname == "openagenda.com"
                or classify(href) not in ALLOWED_ROLES):
            continue
        site = "https://" + parts.hostname + "/"
        if safe_public_url(site) == site:
            sites.add(site)
    return next(iter(sites)) if len(sites) == 1 else None


def municipal_selector(city):
    """A city is a search key only, never evidence or a network destination."""
    return (isinstance(city, str) and 2 <= len(city) <= 80
            and city == city.strip()
            and all(c.isalpha() or c in " -'’." for c in city)
            and any(c.isalpha() for c in city))


def _municipal_heading_matches(heading, title, year):
    """Exact brand, optionally followed by an explicit year or edition number."""
    brand = normalized(title.rsplit(" ", 1)[0])
    value = normalized(heading)
    # A bare trailing number is accepted only with a printed # or edition
    # label. A different named event, city, artist or year cannot match.
    if value in (brand, brand + " " + str(year)):
        return True
    if not re.search(r"(?:#\s*\d{1,2}|\b[ée]dition\s+\d{1,2})\s*$",
                     heading, re.I):
        return False
    return re.fullmatch(re.escape(brand) +
                        r"(?: edition)? [0-9]{1,2}", value) is not None


def _municipal_detail_dates(html, title, year, today):
    """A bounded named event section may contain a separate date heading.

    Municipal CMS templates often place the event in h2, not h1, and give
    its edition number rather than a year in the title. Only that section
    may establish its explicit current dates, musical genre and format.
    """
    from grossesondes_institutional_edition import VisibleInstitutionHeadings, TOURING_SHOW
    from grossesondes_official_html_edition import (
        fold, explicit_ranges, dominant_visible_range, CANCEL,
        administrative_calendar_dates,
    )
    from grossesondes_generic_directory_edition import (
        verify_primary, ROCK_METAL_PUNK_GENRES,
    )
    from grossesondes_structured_edition import no_same_edition_jsonld_contradiction
    from festival_event_kind import touring_concert_stop
    if not isinstance(html, str) or not 0 < len(html) <= 650_000:
        return False, None
    parser = VisibleInstitutionHeadings()
    parser.feed(html)
    parser.close()
    matches = [i for i, heading in enumerate(parser.headings)
               if _municipal_heading_matches(heading, title, year)]
    if len(matches) != 1 or len(parser.headings) != len(parser.heading_starts):
        return bool(matches), None
    index = matches[0]
    start = parser.heading_starts[index]
    end = (parser.heading_starts[index + 1]
           if index + 1 < len(parser.heading_starts) else len(parser.parts))
    section = " ".join(fold(" ".join(parser.parts[start:end])).split())
    brand = normalized(title.rsplit(" ", 1)[0])
    outside = re.sub(r"(?<![a-z0-9])" + re.escape(brand)
                     + r"(?![a-z0-9])", " ", normalized(section))
    if (not ROCK_METAL_PUNK_GENRES.search(outside)
            or CANCEL.search(section) or TOURING_SHOW.search(outside)):
        return True, None
    excluded = administrative_calendar_dates(html, title, year)
    intervals = {(a, b) for _, _, a, b in explicit_ranges(section, year)
                 if (a, b) not in excluded}
    target = dominant_visible_range(intervals)
    if (target is None or target[0] < date.fromisoformat(today)
            or touring_concert_stop(html, *target)
            or not no_same_edition_jsonld_contradiction(html, title, *target)):
        return True, None
    dates = tuple(d.isoformat() for d in target)
    if verify_primary(html, title, year, today) == dates:
        return True, dates
    # Fallback for a named "Fest" with no literal "festival" in the page:
    # an explicit recurring edition or festival description plus a calendar
    # date immediately following the event heading. Never a ticket-sale day.
    if not (re.search(r"\bfestival\b", outside)
            or (re.search(r"\bfest\b", brand)
                and re.search(r"\b(?:edition|editions)\b", outside))):
        return True, None
    leading = section[:240]
    for offset, _, a, b in explicit_ranges(leading, year):
        if (a, b) != target:
            continue
        prefix = leading[:offset]
        if re.search(r"\b(?:billetterie|prevente|tickets?|vente|inscription)\b", prefix):
            continue
        # The date must be next to the named event, not a different paragraph
        # much further down a multi-event agenda.
        if len(prefix) <= 120:
            return True, dates
    return True, None


def prove_municipal_edition(city, title, today, *, fetch=fetch_public_html,
                            commune_lookup=None, directory_fetch=None):
    """Reconstruct a mairie origin, then read its own event-detail publication.

    No privately supplied domain or detail URL is fetched. An institutional
    listing is not evidence of municipal organization, nor a proof of GPS.
    """
    from national_municipal_source_research import (
        verified_commune, mairie_records_url, fetch_dila_records,
        verified_mairie_site, INSEE,
    )
    from national_municipal_pages_preflight import (
        _candidate_links, _visible, safe_same_host_article,
    )
    if (not municipal_selector(city) or not isinstance(title, str)
            or not re.fullmatch(r".{7,150} 20[2-4][0-9]", title)):
        return None
    try:
        year = int(title.rsplit(" ", 1)[-1])
        admin = (commune_lookup or verified_commune)(city)
        if not isinstance(admin, dict):
            return None
        name, code = admin.get("city"), admin.get("codeInsee")
        if (not isinstance(name, str) or normalized(name) != normalized(city)
                or not isinstance(code, str) or not INSEE.fullmatch(code)):
            return None
        record = (directory_fetch or fetch_dila_records)(mairie_records_url(code))
        root = verified_mairie_site(record, code, name)
        if root is None:
            return None
        pending = [(0, root)]
        seen = set()
        proofs = []
        unresolved_named = False
        # Bounded crawl, exact event links before generic navigation.
        while pending and len(seen) < 6:
            priority, url = pending.pop(0)
            if url in seen:
                continue
            seen.add(url)
            try:
                html = fetch(url)
                _visible(html)  # reject malformed or oversized responses
                named, dates = (_municipal_detail_dates(html, title, year, today)
                                if url != root else (False, None))
                if named:
                    if dates is None:
                        unresolved_named = True
                    else:
                        proofs.append((url, tuple(dates)))
                for rank, link in _candidate_links(
                        html, url, root, title, year, today, ranked=True):
                    if (link not in seen and
                            safe_same_host_article(link, url, root) == link
                            and (rank == 0 or not named)):
                        pending.append((rank, link))
                best = {}
                for rank, link in pending:
                    if link not in seen:
                        best[link] = min(rank, best.get(link, rank))
                # Never truncate an excess of exact event links and then
                # silently accept a potentially conflicting edition.
                if sum(rank == 0 for rank in best.values()) > 12:
                    return None
                pending = sorted((rank, link) for link, rank in best.items())[:12]
            except (OSError, ValueError, TypeError, UnicodeError, KeyError):
                if priority == 0 and url != root:
                    unresolved_named = True
        # Conflicting or unresolved exact-name pages fail closed.
        if unresolved_named or any(rank == 0 and link not in seen
                                   for rank, link in pending):
            return None
        if len({dates for _, dates in proofs}) != 1:
            return None
        return sorted(proofs)[0]
    except (OSError, ValueError, TypeError, UnicodeError, KeyError):
        return None


MUNICIPAL_PRIVATE_NOTES = ("Fiche événement institutionnelle repérée ; "
                           "dates et genre à revérifier. Lieu précis inconnu.")
MUNICIPAL_PUBLIC_NOTES = ("Dates et genre revérifiés sur une fiche municipale "
                          "officielle ; lieu précis, artistes et GPS à confirmer.")
MUNICIPAL_PRIVATE_CONFIDENCE = "Agenda municipal (origine à recontrôler)"
MUNICIPAL_PUBLIC_CONFIDENCE = "Agenda municipal officiel (Geo/DILA et fiche revérifiés)"


PROFESSIONAL_MARKER = "professional-profile.v1"
PROFESSIONAL_PRIVATE_NOTES = "Fiche professionnelle repérée ; identité, genre et dates à revérifier."
PROFESSIONAL_PUBLIC_NOTES = "Édition revérifiée sur la fiche officielle professionnelle ; lieu, artistes et GPS à confirmer."
PROFESSIONAL_PRIVATE_CONFIDENCE = "Profil professionnel et fiche officielle à recontrôler"
PROFESSIONAL_PUBLIC_CONFIDENCE = "Provenance OpenData et fiche professionnelle revérifiées"


def private_proposal(title, site, dates, today, *, event_ref, municipality=None,
                     professional_ticket=None):
    if event_url(event_ref) is None or slug_for(title) is None:
        return None
    if professional_ticket is not None:
        from national_professional_profile_discovery import _path_identity, ALLOWED_WEBSITE_ROLES
        if (municipality is not None or safe_public_url(site) is None
                or classify(site) not in ALLOWED_WEBSITE_ROLES
                or _path_identity(professional_ticket) is None):
            return None
        root = "https://" + urlsplit(site).hostname + "/"
        row = directory_proposal(title, root, dates, today)
        if row is None:
            return None
        row.update(proofMode=PROOF_MODE, originSlug=event_ref,
                   evidence=[event_ref, site, PROFESSIONAL_MARKER, professional_ticket],
                   officialSite=site, source=site, notes=PROFESSIONAL_PRIVATE_NOTES,
                   verificationStatus=PRIVATE_STATUS,
                   sourceConfidence=PROFESSIONAL_PRIVATE_CONFIDENCE)
        return row
    if municipality is not None:
        from national_municipal_pages_preflight import safe_same_host_article
        if not municipal_selector(municipality) or not isinstance(site, str):
            return None
        try:
            root = "https://" + urlsplit(site).netloc + "/"
            if safe_same_host_article(site, root, root) != site:
                return None
        except (TypeError, ValueError):
            return None
        row = directory_proposal(title, root, dates, today)
        if row is None:
            return None
        row.update(
            proofMode=PROOF_MODE, originSlug=event_ref,
            evidence=[event_ref, site, municipality],
            officialSite=site, source=site, notes=MUNICIPAL_PRIVATE_NOTES,
            verificationStatus=PRIVATE_STATUS,
            sourceConfidence=MUNICIPAL_PRIVATE_CONFIDENCE)
        return row
    row = directory_proposal(title, site, dates, today)
    if row is None:
        return None
    row.update(
        proofMode=PROOF_MODE, originSlug=event_ref,
        evidence=[event_ref, site],
        notes=PRIVATE_NOTES, verificationStatus=PRIVATE_STATUS,
        sourceConfidence=PRIVATE_CONFIDENCE)
    return row


def validate_private_proposal(row, today):
    if (not isinstance(row, dict) or set(row) != ROW_KEYS | PRIVATE_KEYS
            or event_url(row.get("originSlug")) is None):
        return None
    evidence = row.get("evidence")
    expected_evidence = [row.get("originSlug"), row.get("officialSite")]
    municipality = None
    professional_ticket = None
    if isinstance(evidence, list) and len(evidence) == 4:
        if evidence[2] != PROFESSIONAL_MARKER or not isinstance(evidence[3], str):
            return None
        professional_ticket = evidence[3]
        expected_evidence.extend((PROFESSIONAL_MARKER, professional_ticket))
    if isinstance(evidence, list) and len(evidence) == 3:
        municipality = evidence[2]
        if not municipal_selector(municipality):
            return None
        expected_evidence.append(municipality)
    if evidence != expected_evidence:
        return None
    try:
        verified = date.fromisoformat(row["verified_at"])
        actual = date.fromisoformat(today)
        if actual < verified or (actual - verified).days > 7:
            return None
    except (TypeError, ValueError, KeyError):
        return None
    expected = private_proposal(
        row.get("name"), row.get("officialSite"),
        (row.get("startDate"), row.get("endDate")), row["verified_at"],
        event_ref=row["originSlug"], municipality=municipality,
        professional_ticket=professional_ticket)
    return row if expected == row else None


def _approved(proposal):
    row = {key: proposal[key] for key in ROW_KEYS}
    municipal = len(proposal["evidence"]) == 3
    if len(proposal["evidence"]) == 4:
        row.update(verificationStatus=PUBLISHED_STATUS,
                   sourceConfidence=PROFESSIONAL_PUBLIC_CONFIDENCE,
                   notes=PROFESSIONAL_PUBLIC_NOTES)
        return row
    row.update(
        verificationStatus=PUBLISHED_STATUS,
        sourceConfidence=(MUNICIPAL_PUBLIC_CONFIDENCE if municipal
                          else PUBLISHED_CONFIDENCE),
        notes=MUNICIPAL_PUBLIC_NOTES if municipal else PUBLISHED_NOTES)
    return row


def validate_verified_row(proposal, row, today):
    if validate_private_proposal(proposal, today) is None:
        return None
    return row if row == _approved(proposal) else None


def independently_verify(proposal, today, event_fetch=fetch_public_html,
                         organizer_fetch=fetch_public_html):
    """Private hints never pick the official website the Publisher visits."""
    if validate_private_proposal(proposal, today) is None:
        return None
    if len(proposal["evidence"]) == 4:
        from national_professional_publisher_provenance import prove
        proofs = prove(proposal["originSlug"], proposal["name"], today,
                       fetch=organizer_fetch)
        expected = {"official_detail_url": proposal["officialSite"],
                    "ticket_url": proposal["evidence"][3],
                    "start_date": proposal["startDate"],
                    "end_date": proposal["endDate"],
                    "publication_authorized": False}
        return _approved(proposal) if expected in proofs else None
    if len(proposal["evidence"]) == 3:
        proven = prove_municipal_edition(
            proposal["evidence"][2], proposal["name"], today,
            fetch=organizer_fetch)
        expected = (proposal["officialSite"],
                    (proposal["startDate"], proposal["endDate"]))
        return _approved(proposal) if proven == expected else None
    try:
        html = event_fetch(proposal["originSlug"])
        site = attributed_site(
            html, proposal["name"], proposal["originSlug"])
        if site is None or site != proposal["officialSite"]:
            return None
        root = organizer_fetch(site)
        dates = verify_official_site_pages(
            site, root, proposal["name"],
            int(proposal["name"].rsplit(" ", 1)[-1]), today,
            fetch=organizer_fetch)
    except (OSError, TypeError, ValueError, UnicodeError, KeyError):
        return None
    if dates != (proposal["startDate"], proposal["endDate"]):
        return None
    return _approved(proposal)
