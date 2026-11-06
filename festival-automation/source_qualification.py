"""Private qualification of unverified festival sources.

Candidate URLs originate from published source/auditSources and from a
small, explicitly curated private lead file. All remain unverified.
Neither page text nor a ticketing platform certifies an officialSite, lineup or
ticket stock. This module never creates a public patch or marks VERIFIED.
"""
import argparse
from datetime import date
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit, urljoin

from official_watch import get_page, permitted_url
from official_ticket_links import provider_for_host
from lineup_dispute_probe import load_curated, probe_disputes
from organizer_domain_evidence import organizer_domain_dossiers
from organizer_structured_links import structured_organizer_links
from festival_website_discovery import (event_website_links, discovery_queue,
                                        visible_event_website_links)

SCHEMA = "grossesondes.source-qualification.v1"
ROLES = {"TICKETING", "VENUE", "INSTITUTION", "ORGANIZER_CANDIDATE",
         "SOCIAL", "MEDIA", "THIRD_PARTY", "UNKNOWN"}
STATUSES = {"NOT_VERIFIED", "REVIEW_REQUIRED", "REJECTED", "VERIFIED"}
VENUES = {"zinor.fr", "camji.com", "bar-graine-dorge.fr", "lebikini.com"}
MEDIA = {"culturemetal.com", "france-metal-agenda.com",
         "festivalenfrance.com"}
INSTITUTIONS = {"saintes-tourisme.fr", "savigny-le-temple.fr",
                "saint-verand.fr", "saintsauveur38.fr", "gattieres.fr",
                "sortir.limoges.fr", "destination-limoges.com",
                "pevelecarembault.fr", "vendeebocage.fr", "phalempin.fr",
                "valdahon.com", "tourisme-seine-et-marne.fr", "izeron.fr"}
THIRD_PARTIES = {"m-o-music.com"}
ORGANIZER_HINT_DOMAINS = {"execution-mgt.fr"}
# Shared-host website: the exact association account AND festival path matter.
# A random wixsite.com subsite cannot inherit the organizer-candidate label.
ORGANIZER_HINT_PATHS = {
    ("backinblackasso.wixsite.com", "/metalfest09/home"),
    ("backinblackasso.wixsite.com", "/metalfest09/groupes"),
}


def normalized(value):
    value = unicodedata.normalize("NFKD", str(value).casefold())
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", value))


class VisibleContent(HTMLParser):
    """Ignore scripts and markup: a hidden schema.org value is not proof."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "svg", "noscript"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "svg", "noscript"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden and len(self.parts) < 16000:
            self.parts.append(data)


def visible_text(html):
    if not isinstance(html, str) or len(html) > 650_000:
        raise ValueError("HTML non exploitable")
    parser = VisibleContent()
    parser.feed(html)
    text = " ".join(parser.parts)
    if len(normalized(text)) < 30:
        raise ValueError("page vide ou dynamique")
    return normalized(text)


def clean_url(value):
    if not permitted_url(value):
        return None
    try:
        parsed = urlsplit(value)
        clean = parsed._replace(query="", fragment="").geturl()
    except ValueError:
        return None
    return clean if permitted_url(clean) and len(clean) <= 1500 else None


def domain_is(host, domain):
    return host == domain or host.endswith("." + domain)


def classify(url):
    host = (urlsplit(url).hostname or "").lower()
    if provider_for_host(host):
        return "TICKETING"
    if any(domain_is(host, domain) for domain in VENUES):
        return "VENUE"
    if (host.endswith(".gouv.fr") or host.endswith(".fr") and
            any(token in host for token in ("mairie-", ".ville-", ".agglo-")) or
            any(domain_is(host, domain) for domain in INSTITUTIONS)):
        return "INSTITUTION"
    if any(domain_is(host, domain) for domain in MEDIA):
        return "MEDIA"
    path = urlsplit(url).path.rstrip("/")
    if (host, path) in ORGANIZER_HINT_PATHS:
        return "ORGANIZER_CANDIDATE"
    if any(domain_is(host, domain) for domain in ORGANIZER_HINT_DOMAINS):
        return "ORGANIZER_CANDIDATE"
    if any(domain_is(host, domain) for domain in THIRD_PARTIES):
        return "THIRD_PARTY"
    if any(domain_is(host, domain) for domain in
           ("facebook.com", "instagram.com", "tiktok.com", "x.com")):
        return "SOCIAL"
    # A standalone festival-looking domain may be organizer-controlled, but
    # this cannot be established by hostname heuristics.
    if "festival" in host or "fest" in host:
        return "ORGANIZER_CANDIDATE"
    return "UNKNOWN"


MONTHS = ("janvier", "fevrier", "mars", "avril", "mai", "juin",
          "juillet", "aout", "septembre", "octobre", "novembre", "decembre")
ENGLISH_MONTHS = ("january", "february", "march", "april", "may", "june",
                  "july", "august", "september", "october", "november", "december")


def matches_slash_date_range(html, expected):
    """Recognize visible '06/07 novembre 2026' without accepting bare numbers.

    Text from hidden scripts/styles cannot corroborate an event. This is only
    a REVIEW_REQUIRED clue, never proof of organizer control or ticket stock.
    """
    try:
        moment = date.fromisoformat(expected)
    except (TypeError, ValueError):
        return False
    if not isinstance(html, str):
        return False
    parser = VisibleContent()
    parser.feed(html)
    raw = unicodedata.normalize("NFKD", " ".join(parser.parts).casefold())
    visible = "".join(char for char in raw if not unicodedata.combining(char))
    day, month, year = moment.day, MONTHS[moment.month - 1], moment.year
    pattern = (rf"\b(?:0?{day}\s*/\s*\d{{1,2}}|\d{{1,2}}\s*/\s*0?{day})"
               rf"\s+{month}\s+{year}\b")
    return re.search(pattern, visible) is not None


def matches_date(text, expected):
    """Require an explicit calendar day AND year, never year alone."""
    try:
        moment = date.fromisoformat(expected)
    except (TypeError, ValueError):
        return False
    # Accept punctuation in English/French date labels without accepting
    # year-only or day-only mentions.
    text = normalized(text)
    day, month, year = moment.day, moment.month, moment.year
    month_name = MONTHS[month-1]
    month_abbrev = month_name[:3]
    month_pattern = rf"(?:{month_name}|{month_abbrev})"
    month_en = ENGLISH_MONTHS[month-1]
    month_en_pattern = rf"(?:{month_en}|{month_en[:3]})"
    expressions = [
        rf"\b{year}\s*{month:02d}\s*{day:02d}\b",  # ISO normalized
        rf"\b0?{day}\s*0?{month}\s*{year}\b",       # dd/mm/yyyy
        rf"\b0?{day}\s+{month_pattern}\s+{year}\b",
        rf"\b{month_en_pattern}\s+0?{day}\s+{year}\b",
        rf"\b0?{day}\s+{month_en_pattern}\s+{year}\b",
        # 6 et 7 novembre 2026; bare adjacent numerals are not dates.
        rf"\b0?{day}\s+(?:et|au|a)\s+(?:(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+)?\d{{1,2}}\s+{month_pattern}\s+{year}\b",
    ]
    return any(re.search(expr, text) for expr in expressions)



def organizer_aliases(value):
    """Only explicit full names and parenthesized names, never fuzzy guesses.

    Example: 'Association Le Refuge (Le Refuge 59)' can be linked under
    'Le Refuge 59'. Neither alias establishes site ownership.
    """
    if not isinstance(value, str):
        return []
    names = re.findall(r"\(([^()]{5,100})\)", value)
    # The legal name *before* parentheses is also explicitly stated.
    # "Association Le Refuge (Le Refuge 59)" can name "Le Refuge",
    # not just the parenthesized alias or the entire concatenation.
    names.append(re.sub(r"\([^()]{5,100}\)", " ", value))
    names.append(value)
    aliases = []
    for raw in names:
        alias = re.sub(r"^(?:association|l association) ", "", normalized(raw))
        if len(alias) >= 7 and alias not in aliases:
            aliases.append(alias)
    return aliases


class Anchors(HTMLParser):
    """Visible anchor labels with a *local* attribution prefix, never a proof."""
    HIDDEN = {"script", "style", "svg", "noscript", "template", "iframe"}
    CONTEXT = {"p", "li", "div", "dt", "dd"}
    VOID = {"area", "base", "br", "col", "embed", "hr", "img",
            "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current = None
        self.current_prefix = ""
        self.hidden = 0
        self.concealed = 0
        self.anchors = []
        self.contexts = []
        self.definition_label = ""

    def handle_starttag(self, tag, attrs):
        if self.concealed:
            if tag not in self.VOID:
                self.concealed += 1
            return
        if self.hidden:
            if tag in self.HIDDEN:
                self.hidden += 1
            return
        attributes = dict(attrs)
        hidden_element = (
            "hidden" in attributes or attributes.get("aria-hidden") == "true"
            or "display:none" in (attributes.get("style") or "").replace(" ", "").lower()
        )
        if hidden_element:
            if tag not in self.VOID:
                self.concealed = 1
            return
        if tag in self.HIDDEN:
            self.hidden += 1
            return
        if tag in self.CONTEXT:
            prefix = self.definition_label if tag == "dd" else ""
            if tag == "dd":
                self.definition_label = ""
            self.contexts.append({"tag": tag, "text": prefix})
        if tag == "a":
            attributes = dict(attrs)
            href = attributes.get("href")
            hidden = ("hidden" in attributes
                      or attributes.get("aria-hidden") == "true"
                      or "display:none" in (attributes.get("style") or "").replace(" ", "").lower())
            self.current = (href, []) if isinstance(href, str) and not hidden else None
            self.current_prefix = (self.contexts[-1]["text"][-100:]
                                   if self.contexts else "")

    def handle_data(self, data):
        if self.hidden or self.concealed:
            return
        if self.current is not None:
            if len(self.current[1]) < 20:
                self.current[1].append(data)
        elif self.contexts:
            frame = self.contexts[-1]
            if len(frame["text"]) < 250:
                frame["text"] += data[:250 - len(frame["text"])]

    def handle_endtag(self, tag):
        if self.concealed:
            self.concealed -= 1
            return
        if self.hidden:
            if tag in self.HIDDEN:
                self.hidden = max(0, self.hidden - 1)
            return
        if tag == "a" and self.current is not None:
            label = "".join(self.current[1])
            if len(self.anchors) < 500:
                self.anchors.append((self.current[0], label, self.current_prefix))
            if self.contexts:
                frame = self.contexts[-1]
                frame["text"] = (frame["text"] + " " + label)[-250:]
            self.current = None
        if tag in self.CONTEXT and self.contexts and self.contexts[-1]["tag"] == tag:
            frame = self.contexts.pop()
            if tag == "dt":
                self.definition_label = frame["text"][-100:]


def attributed_anchor(label, prefix, aliases):
    """Require an exact organizer name plus explicit visible attribution.

    When the attribution is outside the anchor, it must end immediately
    before the anchor within the same small content block (or dt/dd pair).
    """
    text = normalized(label)
    nearby = normalized(prefix)
    markers = ("site officiel de", "site internet de",
               "propose par", "organisateur", "site de")
    # A word boundary is not sufficient: "Le Refuge" must not match
    # "Le Refuge International" or other longer association names.
    for marker in markers:
        if text.startswith(marker + " "):
            candidate = re.sub(
                r"^(?:association|l association) ", "", text[len(marker) + 1:])
            return candidate in aliases
    contextual = any(nearby.endswith(marker) for marker in markers)
    candidate = re.sub(r"^(?:association|l association) ", "", text)
    return contextual and candidate in aliases


def organizer_links(html, source_url, organizer):
    """Only label-matched, cross-domain research leads. Never proves ownership.

    A venue/municipal page can link to an organizer whose domain does not
    contain "festival" or other recognizable tokens. Such UNKNOWN targets
    deserve *private human review*, not automatic fetching or certification.
    """
    aliases = organizer_aliases(organizer)
    if (not aliases or not isinstance(html, str) or len(html) > 650_000
            or classify(source_url) not in ("INSTITUTION", "VENUE")):
        return []
    parser = Anchors()
    parser.feed(html)
    source_host = urlsplit(source_url).hostname
    found = []
    for raw, label, prefix in parser.anchors:
        if not attributed_anchor(label, prefix, aliases):
            continue
        try:
            url = clean_url(urljoin(source_url, raw))
        except (TypeError, ValueError):
            continue
        if not url:
            continue
        host = urlsplit(url).hostname
        # A municipal subdomain and its parent are not external organizer sites.
        if (domain_is(host, source_host) or domain_is(source_host, host)
                or provider_for_host(host)):
            continue
        # Discard commercial, institutional, social, media and venue links.
        # UNKNOWN is only a research lead, as is ORGANIZER_CANDIDATE.
        if classify(url) not in ("ORGANIZER_CANDIDATE", "UNKNOWN"):
            continue
        if url not in found:
            found.append(url)
        if len(found) >= 4:
            break
    return found


def with_curated_leads(leads, curated):
    """Add small human-reviewed research leads without modifying public data."""
    if not isinstance(curated, dict) or not isinstance(leads, list):
        raise ValueError("pistes de recherche éditoriale invalides")
    # A once-missing edition may already have received a certified
    # officialSite. In that case, ignore stale curated leads: never keep
    # re-probing a festival that has left the review queue.
    copy = []
    for lead in leads:
        row = dict(lead)
        urls = list(row.get("candidate_urls") or [])
        extra = curated.get(row["slug"], [])
        if not isinstance(extra, list) or len(extra) > 8:
            raise ValueError("volume ou format des références éditoriales invalide")
        for raw in extra:
            clean = clean_url(raw)
            if not clean:
                raise ValueError("URL éditoriale non autorisée")
            if clean not in urls and len(urls) < 12:
                urls.append(clean)
        row["candidate_urls"] = urls
        copy.append(row)
    return copy


def assess_candidate(lead, url, observed_at, html=None, error=None):
    """One bounded proof dossier. Never mark an observed website VERIFIED."""
    cleaned = clean_url(url)
    if cleaned is None:
        return {
            "slug": lead.get("slug"), "url": str(url)[:200],
            "status": "REJECTED", "role": "UNKNOWN",
            "observed_at": observed_at, "reason": "URL_NOT_ALLOWED",
            "contradictions": [], "publication_authorized": False,
        }
    role = classify(cleaned)
    entry = {
        "slug": lead["slug"], "url": cleaned, "role": role,
        "observed_at": observed_at, "status": "NOT_VERIFIED",
        "name_match": False, "date_match": False,
        "contradictions": [], "publication_authorized": False,
        "official_site_authorized": False,
    }
    if role == "TICKETING" and provider_for_host(urlsplit(cleaned).hostname) == "HelloAsso":
        match = re.match(r"^/associations/([a-z0-9-]{2,100})(?:/|$)",
                         urlsplit(cleaned).path, re.I)
        if match:
            # Publisher's account label, not a certified organizer identity.
            entry["association_account_hint_unverified"] = match.group(1).lower()
    if error is not None:
        entry["reason"] = "INACCESSIBLE_OR_UNKNOWN"
        return entry
    try:
        text = visible_text(html)
    except (ValueError, TypeError):
        entry["reason"] = "NO_VISIBLE_EVIDENCE"
        return entry
    entry["fingerprint_sha256"] = sha256(text.encode("utf-8")).hexdigest()
    title = normalized(lead.get("name") or "")
    entry["name_match"] = (len(title) >= 7 and re.search(
        r"(?<![a-z0-9])" + re.escape(title) + r"(?![a-z0-9])", text) is not None)
    entry["date_match"] = (matches_date(text, lead.get("start_date"))
                           or matches_slash_date_range(html, lead.get("start_date")))
    if entry["name_match"] and entry["date_match"]:
        entry["status"] = "REVIEW_REQUIRED"
        entry["reason"] = "NAME_AND_START_DATE_MATCH"
    else:
        entry["reason"] = "INSUFFICIENT_EDITION_MATCH"
        if entry["name_match"] and not entry["date_match"]:
            entry["contradictions"].append("START_DATE_NOT_CORROBORATED")
        if entry["date_match"] and not entry["name_match"]:
            entry["contradictions"].append("EDITION_NAME_NOT_CORROBORATED")
    # Only note artists that are EXPLICITLY visible on a corroborating
    # edition page. A non-mention is NOT proof of cancellation or replacement:
    # the page may present a partial lineup or even contain a typo.
    if (entry["status"] == "REVIEW_REQUIRED" and
            role in ("ORGANIZER_CANDIDATE", "INSTITUTION", "VENUE")):
        reference = lead.get("lineup")
        if (isinstance(reference, list) and 1 <= len(reference) <= 30
                and all(isinstance(name, str) for name in reference)):
            matched, unmentioned, seen = [], [], set()
            for name in reference:
                normalized_name = normalized(name)
                if len(normalized_name) < 3 or normalized_name in seen:
                    continue
                seen.add(normalized_name)
                found = re.search(
                    r"(?<![a-z0-9])" + re.escape(normalized_name) +
                    r"(?![a-z0-9])", text) is not None
                (matched if found else unmentioned).append(name)
            if seen:
                entry["roster_names_mentioned_review_only"] = matched
                entry["roster_names_unmentioned_review_only"] = unmentioned
                entry["roster_evidence_is_complete"] = False
                entry["artist_update_authorized"] = False
    if (role in ("INSTITUTION", "VENUE") and
            entry["status"] == "REVIEW_REQUIRED"):
        entry["organizer_links_review_only"] = organizer_links(
            html, cleaned, lead.get("organizer"))
        entry["structured_organizer_links_review_only"] = structured_organizer_links(
            html, cleaned, lead.get("name"), lead.get("start_date"),
            lead.get("end_date"), organizer_aliases(lead.get("organizer")),
            clean_url, classify, normalized)
        # Event.url/sameAs: private research leads, never organizer proof.
        entry["festival_event_links_review_only"] = event_website_links(
            html, cleaned, lead.get("name"), lead.get("start_date"),
            lead.get("end_date"), clean_url, classify, normalized)
        anchors = Anchors()
        anchors.feed(html)
        entry["visible_festival_website_links_review_only"] = visible_event_website_links(
            anchors.anchors, cleaned, lead.get("name"), lead.get("start_date"),
            clean_url, classify, normalized)
    # A ticketing page can corroborate the event, not the organizer's domain;
    # a venue or municipality can corroborate an edition without owning it.
    return entry


def choose_checks(leads, history, today, limit=3, diagnostics=None):
    if not isinstance(leads, list) or not isinstance(history, dict) or not 1 <= limit <= 6:
        raise ValueError("entrées de qualification invalides")
    ref = date.fromisoformat(today)
    if diagnostics is not None:
        if not isinstance(diagnostics, dict):
            raise ValueError("diagnostic de sélection invalide")
        diagnostics.update(already_checked_today=0, inaccessible_backoff=0,
                           eligible_editions=0)
    choices = []
    seen_slugs = set()
    for lead in leads:
        if not isinstance(lead, dict) or lead.get("allowed_to_publish") is not False:
            raise ValueError("piste de source non bornée à la revue")
        if lead.get("official_status") != "NOT_VERIFIED":
            raise ValueError("piste déjà approuvée ou statut inattendu")
        slug = lead.get("slug")
        if not isinstance(slug, str) or slug in seen_slugs:
            raise ValueError("doublon / identifiant d'édition invalide")
        seen_slugs.add(slug)
        try:
            start = date.fromisoformat(lead.get("start_date"))
        except (TypeError, ValueError):
            continue
        # An edition that ended yesterday is already historical, while a
        # multi-week festival can remain active long after its start date.
        # Fall back to start only for legacy reports without end_date.
        raw_end = lead.get("end_date") or lead.get("start_date")
        try:
            end = date.fromisoformat(raw_end)
        except (TypeError, ValueError):
            continue
        if end < ref or end < start:
            continue
        previous = history.get(slug, {})
        if not isinstance(previous, dict):
            raise ValueError("historique de qualification invalide")
        urls = []
        if not isinstance(lead.get("candidate_urls"), list):
            raise ValueError("URLs candidates invalides")
        for url in lead["candidate_urls"][:12]:
            clean = clean_url(url)
            if clean and clean not in urls:
                urls.append(clean)
        if not urls:
            continue
        # Neither a PR smoke nor the morning watch should cause the evening
        # run to retry exactly the same source on the same calendar date.
        # A failed HTTP/HTML probe also cools down for one *additional* day;
        # other sources for the same edition remain eligible immediately.
        eligible = []
        for index, url in enumerate(urls):
            record = previous.get(url, {})
            if not isinstance(record, dict):
                raise ValueError("historique de référence corrompu")
            last = record.get("lastChecked") or ""
            if last:
                try:
                    previous_day = date.fromisoformat(last)
                except (ValueError, TypeError):
                    raise ValueError("date de qualification corrompue")
                if previous_day > ref:
                    raise ValueError("date de qualification future")
                if previous_day == ref:
                    if diagnostics is not None:
                        diagnostics["already_checked_today"] += 1
                    continue
                if (record.get("reason") == "INACCESSIBLE_OR_UNKNOWN"
                        and (ref - previous_day).days < 2):
                    if diagnostics is not None:
                        diagnostics["inaccessible_backoff"] += 1
                    continue
            eligible.append((index, url))
        if not eligible:
            continue
        # Prefer primary institutions and venues for *first* visits when
        # the organizer is named. This avoids wasting scarce daily checks on
        # a HelloAsso 403 before an untouched municipal announcement.
        # Previously checked URLs still rotate oldest-first as before.
        named_organizer = bool(organizer_aliases(lead.get("organizer")))
        source_order = {
            "INSTITUTION": 0, "VENUE": 1, "ORGANIZER_CANDIDATE": 2,
            "UNKNOWN": 3, "MEDIA": 4, "THIRD_PARTY": 5,
            "TICKETING": 6, "SOCIAL": 7,
        }
        def source_key(pair):
            last = previous.get(pair[1], {}).get("lastChecked", "")
            role_order = (source_order.get(classify(pair[1]), 8)
                          if named_organizer and not last else 0)
            return (bool(last), last, role_order, pair[0])
        chosen = min(eligible, key=source_key)[1]
        if diagnostics is not None:
            diagnostics["eligible_editions"] += 1
        # Schedule by edition, not by URL. A festival already visited
        # must not jump ahead of an untouched festival merely because it
        # has another untested auditSources URL. Within its own turn, the
        # selected URL still rotates independently.
        recent_checks = [
            record.get("lastChecked") for url, record in previous.items()
            if url in urls and isinstance(record, dict)
            and isinstance(record.get("lastChecked"), str)
            and record["lastChecked"] <= today
        ]
        last_edition = max(recent_checks, default="")
        # Festivals beginning within 48 hours get a bounded priority share.
        # Keep other slots for first visits and nationally distributed checks.
        imminent = 0 <= (start - ref).days <= 2
        choices.append((bool(last_edition), last_edition,
                        start.isoformat(), slug, lead, chosen, imminent))
    choices.sort(key=lambda item: item[:4])
    urgent = [item for item in choices if item[6]]
    urgent_budget = (limit + 1) // 2
    reserved = urgent[:urgent_budget]
    reserved_slugs = {item[3] for item in reserved}
    selected = reserved + [
        item for item in choices if item[3] not in reserved_slugs
    ][:limit - len(reserved)]
    return [(item[4], item[5]) for item in selected]


def qualify(report, state, fetch=get_page, limit=3, curated=None, disputes=None,
            index_seeds=None):
    if report.get("schema") != "grossesondes.source-watch-report.v1":
        raise ValueError("rapport de veille invalide")
    today = report.get("date")
    date.fromisoformat(today)
    leads = report.get("source_reference_leads_review_only")
    if curated is not None:
        leads = with_curated_leads(leads, curated)
    if index_seeds is not None:
        from institutional_agenda_discovery import accepted_index_leads
        leads = accepted_index_leads(leads, state, index_seeds, today,
                                     clean_url, classify)
    history = state.setdefault("source_qualification_last_checked", {})
    if not isinstance(history, dict):
        raise ValueError("historique de qualification corrompu")
    # Measure fresh discoveries against the known queue *before* this pass;
    # repeated historical links must not masquerade as daily discoveries.
    before = {(item["slug"], item["candidate_url"]) for item in
              discovery_queue(leads, history, today, clean_url, classify)}
    result = []
    scheduling = {}
    pending = choose_checks(leads, history, today, limit, diagnostics=scheduling)
    for lead, url in pending:
        try:
            html = fetch(url)
            entry = assess_candidate(lead, url, today, html=html)
        except (OSError, ValueError, UnicodeError) as exc:
            entry = assess_candidate(lead, url, today, error=type(exc).__name__)
        result.append(entry)
        previous = history.setdefault(lead["slug"], {})
        previous[url] = {
            "lastChecked": today, "status": entry["status"],
            "role": entry["role"],
            "reason": entry["reason"],
            "fingerprint_sha256": entry.get("fingerprint_sha256"),
            "contradictions": entry["contradictions"],
            "organizer_links_review_only": entry.get("organizer_links_review_only", []),
            "structured_organizer_links_review_only": entry.get(
                "structured_organizer_links_review_only", []),
            "festival_event_links_review_only": entry.get(
                "festival_event_links_review_only", []),
            "visible_festival_website_links_review_only": entry.get(
                "visible_festival_website_links_review_only", []),
            "roster_names_mentioned_review_only": entry.get(
                "roster_names_mentioned_review_only", []),
            "roster_names_unmentioned_review_only": entry.get(
                "roster_names_unmentioned_review_only", []),
        }
        # Only 12 URLs per edition, no raw page text or query tokens.
        if len(previous) > 12:
            oldest = sorted(previous, key=lambda key: (
                previous[key].get("lastChecked", ""), key))
            for key in oldest[:-12]:
                del previous[key]
    # Extra daily probes are capped at two, on already-listed research URLs.
    # The private lineup conflict dossier does not authorize any artist patch.
    report["lineup_dispute_checks_review_only"] = probe_disputes(
        leads, state, today, disputes or {}, fetch, assess_candidate,
        visible_text, clean_url, normalized, limit=2)
    report["source_qualification_scheduler_review_only"] = {
        **scheduling, "publication_authorized": False}
    report["source_qualification_review_only"] = result
    report["organizer_domain_leads_review_only"] = [
        {"slug": entry["slug"], "source_url": entry["url"],
         "source_role": entry["role"], "candidate_url": url,
         "candidate_role": classify(url), "link_only": True,
         "evidence_format": format_name, "publication_authorized": False}
        for entry in result
        for format_name, key in (("VISIBLE_ANCHOR", "organizer_links_review_only"),
                                 ("SCHEMA_ORG", "structured_organizer_links_review_only"))
        for url in entry.get(key, [])
    ]
    # Consolidate separately dated, corroborating *links* for an editor.
    # Nothing in this dossier certifies ownership or enters public patches.
    report["organizer_domain_evidence_review_only"] = organizer_domain_dossiers(
        leads, history, today, clean_url, classify)
    # Discovered domains remain private: not scheduled/fetched without a
    # separately reviewed security and provenance policy.
    queue = discovery_queue(leads, history, today, clean_url, classify)
    report["festival_source_discovery_review_only"] = queue
    report["festival_source_discovery_pending_urls_review_only"] = len(queue)
    report["festival_source_discovery_new_urls_review_only"] = sum(
        (entry["slug"], entry["candidate_url"]) not in before
        for entry in queue)
    report["source_qualification_checked"] = len(result)
    report["source_qualification_review_required"] = sum(
        item["status"] == "REVIEW_REQUIRED" for item in result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    statefile = args.intake / "source-watch-state.json"
    state = json.loads(statefile.read_text(encoding="utf-8"))
    if state.get("schema") != "grossesondes.source-watch.v1":
        raise ValueError("état de veille inattendu")
    curated_path = Path(__file__).with_name("curated_source_leads.json")
    curated = json.loads(curated_path.read_text(encoding="utf-8"))
    disputes_path = Path(__file__).with_name("curated_lineup_disputes.json")
    disputes = load_curated(disputes_path)
    from institutional_agenda_discovery import load_seeds
    indexes = json.loads(Path(__file__).with_name(
        "curated_agenda_indexes.json").read_text(encoding="utf-8"))
    seeds = load_seeds(indexes, clean_url, classify)
    qualify(report, state, limit=args.limit, curated=curated, disputes=disputes,
            index_seeds=seeds)
    statefile.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Qualifications privées tentées :", report["source_qualification_checked"],
          "; à examiner :", report["source_qualification_review_required"],
          "; publications : 0")


if __name__ == "__main__":
    main()
