"""Recheck updates for already SIGNED festivals on their official first-party sites.

No closed lists of festivals, artists, places or domains. One official site is
a sufficient editorial source; the cloud Publisher itself re-fetches it and
only follows bounded, safe same-host news/line-up/ticket links. A checksum
change, an undated old edition or an external news site cannot modify data.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import date
from hashlib import sha256
from html.parser import HTMLParser
from math import ceil
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

from dns_pinned_https import fetch_public_html, safe_public_url
from source_qualification import classify
from future_city_preflight import (
    exact_edition_city, _normal as normal_city, _EditionTitle,
    current_edition_description,
)
from official_admin_communes import verified_commune
from grossesondes_institutional_edition import VisibleInstitutionHeadings
from grossesondes_archived_html_intake import (
    official_date, official_structured_date, matching_official_jsonld_present,
)
from grossesondes_official_html_edition import (
    VisibleText, MONTHS as OFFICIAL_MONTHS, CANCEL as OFFICIAL_CANCELLATION,
    explicit_ranges as current_visible_ranges,
)

MAX_LINKS = 5
MAX_HOSTS = 8
COMMUNE_FIELDS = frozenset((
    "city", "lat", "lon", "showOnMap", "geoCity", "geoPrecision",
    "geoInsee", "geoSource", "geoVerification",
))
DATE_FIELDS = frozenset((
    "startDate", "endDate", "days", "dateRangeIsContinuous",
    "status", "verificationStatus",
))
CHANGEABLE = (frozenset(("lineup", "bands", "price", "notes", "lastVerified", "auditSources"))
              | COMMUNE_FIELDS | DATE_FIELDS)
ROLE = re.compile(r"\b(?:programmation|line up|lineup|groupes?|noms|artistes?|"
                  r"annonce|affiche|actualites?|news|billetterie|tarifs?|pass|202[7-9])\b")
GENRE_LIST = re.compile(r"\b(?:groupes?|noms|artistes?|programmation|lineup|affiche|ils seront)\b")
ANNOUNCE = re.compile(r"\b(?:nouveaux?|annonces?|programmation|affiche|ils seront|trois groupes)\b")
SENSITIVE = re.compile(r"\b(?:annule|annulee|reportee|cancelled|postponed)\b")
PRICE = re.compile(r"(\d{2,4}(?:[,.]\d{2})?)\s*€")
PASS = re.compile(r"\bpass\s*([1-7])\s*(?:jours?|j)\b")
# A trusted festival page can announce a new normal-price tier at the exact
# moment its EARLY BIRD tier sells out. The sentence must affirm the CURRENT
# pass is available and bind the category and price locally.
NORMAL_PRICE_AVAILABLE = re.compile(
    r"\bpass\s*([1-7])\s*(?:jours?|j)\s+"
    # Both official constructions identify the NEW normal-price tier:
    # "Pass 4J est désormais disponible au tarif normal de 239 €" and
    # "Pass 4J passe au tarif normal de 239 €". The latter commonly shares
    # a teaser with "Pass 1J reste en vente" without stating any 1J price.
    r"(?:est\s+(?:d[eé]sormais\s+)?disponible\s+au\s+|"
    r"passe\s+au\s+)"
    r"tarif\s+(?:normal|public)\s+de\s+"
    r"(\d{2,4}(?:[,.]\d{2})?)\s*€", re.I)



def fold(s):
    s = unicodedata.normalize("NFKD", str(s)).casefold()
    return " ".join(re.findall(r"[a-z0-9]+",
                    "".join(c for c in s if not unicodedata.combining(c))))


def key(s):
    return fold(s).replace(" ", "")




def signed_programmer_city_url(row):
    """Only a previously SIGNED official co-organizer/programmer source.

    Never take a new URL from a private intake patch, website link, or
    candidate. The signed public row must already identify the professional
    programming role and include this exact source in its audited URLs.
    """
    if not isinstance(row, dict):
        return None
    source, audit = row.get("source"), row.get("auditSources")
    trust = fold(row.get("sourceConfidence", ""))
    if (not isinstance(source, str)
            or source == row.get("officialSite")
            or not isinstance(audit, list) or source not in audit
            or not trust.startswith("organisateur programmateur officiel")
            or safe_public_url(source) is None):
        return None
    return source


def signed_programmer_current_city(html, row):
    """Current future-year city of exactly ONE festival on an official index.

    The festival heading, dated next edition, and named municipal production
    must all belong to the SAME visible h1/h2 section. A generic page footer,
    an adjacent festival's city/date or an archive never authorizes a marker.
    Only verifies the pre-existing signed town; returns no GPS or venue.
    """
    if (signed_programmer_city_url(row) is None
            or not isinstance(html, str) or not 0 < len(html) <= 650_000
            or not isinstance(row.get("city"), str)
            or not isinstance(row.get("department"), str)
            or not isinstance(row.get("name"), str)):
        return False
    try:
        start = date.fromisoformat(row["startDate"])
        end = date.fromisoformat(row["endDate"])
    except (KeyError, TypeError, ValueError):
        return False
    match = re.fullmatch(r"(.{8,160})\s+(20[2-4]\d)", row["name"].strip())
    if (match is None or int(match.group(2)) != start.year
            or end.year != start.year or end < start
            or (end - start).days > 7):
        return False
    expected = key(match.group(1))
    parser = VisibleInstitutionHeadings()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError, UnicodeError):
        return False
    headings = [i for i, label in enumerate(parser.headings)
                if key(label) == expected]
    if len(headings) != 1:
        return False
    index = headings[0]
    begin = parser.heading_starts[index]
    finish = (parser.heading_starts[index + 1]
              if index + 1 < len(parser.headings) else len(parser.parts))
    section = " ".join(" ".join(parser.parts[begin:finish]).split())
    if not 15 <= len(section) <= 1800:
        return False
    visible = fold(section)
    years = set(re.findall(r"(?<!\d)20[2-4]\d(?!\d)", visible))
    if years != {str(start.year)} or OFFICIAL_CANCELLATION.search(visible):
        return False
    dates = {(a, b) for _, _, a, b
             in current_visible_ranges(visible, start.year)}
    if dates != {(start, end)} or "prochaine edition" not in visible:
        return False
    city_words = fold(row["city"]).split()
    if not 1 <= len(city_words) <= 6:
        return False
    city = r"\s+".join(re.escape(word) for word in city_words)
    municipal = (r"\b(?:production|organisation)\s+"
                 r"(?:mairie|ville|commune)\s+(?:de|du|d)\s+"
                 + city + r"\b")
    return re.search(municipal, visible) is not None


def current_official_ticket_city(html, row):
    """Exact summer-edition locality printed on a CURRENT first-party ticket page.

    Generic evidence: title must identify the signed festival and season/year,
    and visible content must bind the SAME signed date interval to one city.
    Never derive a town from a generic footer, a former venue or winter dates.
    Only call for a same-host ticket/news link discovered in the signed home.
    """
    if not isinstance(html, str) or not 0 < len(html) <= 650_000:
        return None
    try:
        begin = date.fromisoformat(row["startDate"])
        end = date.fromisoformat(row["endDate"])
        if (begin.year != end.year or begin.month != end.month
                or end < begin or (end - begin).days > 7):
            return None
        title_parser = _EditionTitle()
        title_parser.feed(html)
        title_parser.close()
        title = fold(" ".join(title_parser.parts))
        identity = fold(re.sub(r"\b20[2-4]\d\b", "", row["name"])).strip()
        if (not identity or key(identity) not in key(title)
                or "billetterie" not in title
                or f"ete {begin.year}" not in title):
            return None
        visible = VisibleText()
        visible.feed(html)
        visible.close()
        body = " ".join(visible.parts)
        months = ("janvier", "février", "mars", "avril", "mai", "juin",
                  "juillet", "août", "septembre", "octobre", "novembre", "décembre")
        month = months[begin.month - 1]
        pattern = (
            rf"\b(?:été|ete)\s+{begin.year}\s*[·:|–—-]?\s*"
            rf"{begin.day}\s*[-–—]\s*{end.day}\s+{month}\s+à\s+"
            r"([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’\-]*"
            r"(?:\s+[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’\-]*){0,2})"
            r"\s*\(([^()]{2,35})\)"
        )
        cities = {match.group(1) for match in re.finditer(pattern, body, re.I)}
        return next(iter(cities)) if len({key(x) for x in cities}) == 1 else None
    except (KeyError, TypeError, ValueError, UnicodeError):
        return None


def verified_artist_alias_cleanup(lineup, official_names):
    """Collapse a billed soloist and its explicit performance description.

    The long name must also appear in the freshly read official roster. This
    cannot silently combine unrelated acts merely sharing a first word.
    """
    if not isinstance(lineup, list):
        return lineup
    confirmed = {key(x) for x in official_names if isinstance(x, str)}
    kept = list(lineup)
    for short in lineup:
        if not isinstance(short, str):
            continue
        prefix = fold(short) + " celebrating the songs of "
        if len(fold(short)) < 6:
            continue
        if any(isinstance(long, str) and long != short
               and fold(long).startswith(prefix) and key(long) in confirmed
               for long in lineup):
            if short in kept:
                kept.remove(short)
    return kept


def clean_obsolete_date_notes(notes):
    """Retire seulement les assertions de dates manquantes devenues fausses.

    Conserve les archives, indications de site, tarifs et faits historiques.
    L'appelant doit revérifier la période exacte sur la source officielle.
    """
    if not isinstance(notes, str):
        return notes
    sections = []
    removed_obsolete_claim = False
    for section in re.split(r"\s+\|\s+", notes):
        sentences = []
        for sentence in re.split(r"(?<=\.)\s+", section):
            clauses = []
            for clause in sentence.split(";"):
                normalized = fold(clause)
                wrong_end = ("date de fin" in normalized and any(
                    x in normalized for x in (
                        "pas etablie", "inconnue", "pas connue", "non connue",
                        "a confirmer", "inventee")))
                wrong_empty = ("startdate enddate vides" in normalized or
                               "statut dates a venir" in normalized)
                wrong_range = ("periode continue inventee" in normalized)
                if wrong_end or wrong_empty or wrong_range:
                    removed_obsolete_claim = True
                elif clause.strip():
                    clauses.append(clause.strip())
            if clauses:
                sentences.append("; ".join(clauses))
        if sentences:
            sections.append(" ".join(sentences))
    # Absolutely no editorial rewrite when nothing was obsolete.
    # In particular preserve punctuation, whitespace and semicolon spacing
    # in verified descriptions across successive scheduled rechecks.
    return " | ".join(sections) if removed_obsolete_claim else notes



TICKET_EARLY_BIRD_CURRENT = (
    "Actualisation officielle : les trois paliers Early Bird "
    "du pass 4 jours sont épuisés."
)


def expected_ticket_notes_after_official_sale(notes, four_day_price):
    """Deterministic, narrowly scoped note delta for the signed-head guard.

    This function is NOT evidence that a ticket is sold out. Only the
    separate first-party Publisher HTML recheck supplies that evidence.
    """
    if (not isinstance(notes, str) or "early bird" not in fold(notes)
            or not isinstance(four_day_price, str)
            or re.fullmatch(r"\d{2,4}(?:,\d{2})? €", four_day_price) is None):
        return notes
    amount = re.escape(four_day_price[:-2].strip())
    updated, count = re.subn(
        rf"(palier\s+(?:r[eé]gulier|normal)\s+affich[eé]\s+[aà]\s+"
        rf"{amount}\s*€)\s*\(non encore disponible à cette vérification\)",
        r"\1", notes, flags=re.I)
    if count != 1:
        return notes
    # A stale note may describe the final Early Bird as "offered for sale"
    # at a dated historical checkpoint. Preserve the historical amount/date,
    # but do not continue presenting that exhausted tier as for sale today.
    updated = re.sub(
        r"(Early\s+Bird\s+[1-3]\s+[aà]\s+\d{2,4}\s*€)"
        r"\s+propos[eé]\s+[aà]\s+la\s+vente\s+au\s+"
        r"(\d{1,2}\s+[a-zA-ZÀ-ÿ]+\s+20\d{2})",
        r"\1 (désormais épuisé ; annonce initiale du \2)",
        updated, flags=re.I)
    if TICKET_EARLY_BIRD_CURRENT not in updated:
        updated = updated.rstrip() + " | " + TICKET_EARLY_BIRD_CURRENT
    return updated


def _current_official_early_bird_sold_out(visible_words):
    """Require both related current statements in ONE visible document.

    A headline mentioning one expired tier is insufficient. The sentence
    declaring ALL three tiers exhausted must be adjacent to that headline.
    No claims from other pages or old catalogue text can be stitched together.
    """
    if not isinstance(visible_words, str) or not visible_words:
        return False
    headline = re.search(
        r"\bpass\s*4\s*(?:j|jours)\s+early\s+birds?\s+sont\s+sold\s+out\b",
        visible_words)
    exhausted = re.search(
        r"\btrois\s+paliers\s+d\s+early\s+birds?\s+sont\s+epuises\b",
        visible_words)
    return bool(headline and exhausted and
                0 <= exhausted.start() - headline.end() <= 450)


def _ticket_visible_words_from_html(official_html):
    """Read visible same-host HTML, not only h1/h2/h3/p/li blocks.

    Official Astro news teasers may use div/h4 spans. The existing bounded
    VisibleText parser rejects script, template and hidden DOM content.
    """
    if not isinstance(official_html, str) or not 0 < len(official_html) <= 650_000:
        return ""
    p = VisibleText()
    try:
        p.feed(official_html)
        p.close()
        return fold(" ".join(p.parts))
    except (TypeError, ValueError, UnicodeError):
        return ""


def reconcile_obsolete_ticket_notes(notes, prices, current_official_blocks,
                                    current_official_html=None):
    """Reconcile old ticket statuses using newly fetched first-party proof.

    The old block extraction is kept for compatibility. The additional
    visible-HTML channel covers actual dynamic first-party markup that doesn't
    use the tags recognized by the roster/ticket extractor.
    """
    if (not isinstance(notes, str) or not isinstance(prices, dict)
            or 4 not in prices or not isinstance(current_official_blocks, list)):
        return notes
    blocks_text = fold(" ".join(
        block.get("text", "") for block in current_official_blocks
        if isinstance(block, dict) and isinstance(block.get("text"), str)))
    current_text = _ticket_visible_words_from_html(current_official_html)
    if not (_current_official_early_bird_sold_out(blocks_text)
            or _current_official_early_bird_sold_out(current_text)):
        return notes
    return expected_ticket_notes_after_official_sale(notes, prices[4])


class Page(HTMLParser):
    """Visible heading, paragraph, bullet, bold bullet and anchor evidence."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.links, self.open, self.anchors = [], [], [], []
        self.hidden_tag = None
        self.main = self.article = 0
        self.strong = None

    def handle_starttag(self, tag, attrs):
        if self.hidden_tag is not None:
            return
        if (tag in ("script", "style", "noscript", "svg", "template") or
                any(k in ("hidden", "aria-hidden") and (v is None or v == "true")
                    for k, v in attrs) or
                any(k == "style" and re.search(r"display\s*:\s*none", v or "", re.I)
                    for k, v in attrs)):
            self.hidden_tag = tag
            return
        # Visible edition logos often provide the accessible H1 title as
        # an image alt rather than a text node (e.g. the Motocultor 2027
        # Astro homepage). Respect hidden/aria-hidden checks above and use
        # only the first-party <img> alt inside a visible heading. Never
        # read img src, OCR artwork, or third-party image URLs.
        if tag == "img" and self.open and self.open[-1]["tag"] in (
                "h1", "h2", "h3"):
            alt = dict(attrs).get("alt")
            if isinstance(alt, str) and 8 <= len(alt) <= 180:
                self.open[-1]["buf"].append(alt)
        if tag == "main":
            self.main += 1
        if tag == "article":
            self.article += 1
        if tag in ("h1", "h2", "h3", "p", "li"):
            self.open.append({"tag": tag, "buf": [], "lead": "",
                              "scope": "article" if self.article else
                              "main" if self.main else "other"})
        if tag == "strong" and self.open and self.open[-1]["tag"] == "li":
            self.strong = []
        if tag == "a":
            self.anchors.append([dict(attrs).get("href"), []])

    def handle_data(self, value):
        if self.hidden_tag is not None:
            return
        for b in self.open:
            b["buf"].append(value)
        for a in self.anchors:
            a[1].append(value)
        if self.strong is not None:
            self.strong.append(value)

    def handle_endtag(self, tag):
        if self.hidden_tag is not None:
            if tag == self.hidden_tag:
                self.hidden_tag = None
            return
        if tag == "strong" and self.strong is not None:
            if self.open and self.open[-1]["tag"] == "li":
                self.open[-1]["lead"] = " ".join(" ".join(self.strong).split())
            self.strong = None
        if tag in ("h1", "h2", "h3", "p", "li"):
            for i in range(len(self.open) - 1, -1, -1):
                if self.open[i]["tag"] == tag:
                    b = self.open.pop(i)
                    b["text"] = " ".join(" ".join(b.pop("buf")).split())
                    if b["text"]:
                        self.blocks.append(b)
                    break
        if tag == "a" and self.anchors:
            href, values = self.anchors.pop()
            self.links.append((href, " ".join(" ".join(values).split())))
        if tag == "article":
            self.article = max(0, self.article - 1)
        if tag == "main":
            self.main = max(0, self.main - 1)

    def relevant(self):
        for scope in ("article", "main", "other"):
            found = [b for b in self.blocks if b["scope"] == scope]
            if found:
                return found
        return []


def page(html):
    if not isinstance(html, str) or not 0 < len(html) <= 650_000:
        raise ValueError("Untrusted official HTML")
    out = Page()
    out.feed(html)
    out.close()
    return out


def linked_pages(site, parsed):
    if safe_public_url(site) != site:
        return []
    host = urlsplit(site).hostname
    ranked = {}
    for href, label in parsed.links[:300]:
        if not isinstance(href, str) or not 0 < len(href) <= 500:
            continue
        if any(c in href for c in ("%", "\\", "#")):
            continue
        raw = urlsplit(href)
        if ".." in raw.path.split("/"):
            continue
        url = urljoin(site, href)
        bits = urlsplit(url)
        # A relative href on a language-prefixed homepage sometimes repeats
        # that locale (e.g. /fr/ + fr/news => /fr/fr/news, a 404). Derive
        # the unique nonduplicated path ONLY from its actual first-party
        # anchor, without allowing a different host or a candidate URL.
        locale = urlsplit(site).path.strip("/")
        if (re.fullmatch(r"[a-z]{2}", locale or "") and
                bits.path.startswith("/" + locale + "/" + locale + "/")):
            url = "https://" + host + bits.path[len(locale)+1:]
            bits = urlsplit(url)
        if (bits.scheme != "https" or bits.hostname != host or bits.query or
                bits.fragment or bits.username or bits.password or
                bits.port is not None or url == site or
                safe_public_url(url) != url):
            continue
        if re.search(r"/(?:20[01]\d|202[0-6])(?:/|$)", bits.path):
            continue
        label = fold(label + " " + bits.path.replace("-", " "))
        if not ROLE.search(label):
            continue
        rank = (0 if re.search(r"nouveaux? noms|groupes? annonces?|annonce|affiche", label)
                else 1 if re.search(r"programmation|lineup|groupes", label)
                else 2 if re.search(r"billetterie|pass|tarif", label)
                else 3)
        ranked[url] = min(rank, ranked.get(url, rank))
    return sorted(ranked, key=lambda u: (ranked[u], u))[:MAX_LINKS]


def good_artist(value):
    name = " ".join(str(value).strip().strip(" :;").split())
    # Preserve official acronyms ending in dot-separated initials
    # (e.g. "Cavalera Chaos A.D.") while trimming sentence punctuation.
    if not re.search(r"(?:\b[A-Za-z]\.){2,}$", name):
        name = name.rstrip(".")
    if (not 2 <= len(key(name)) <= 90 or len(name) > 110 or
            not re.search(r"[A-Za-zÀ-ÿ]", name) or
            re.search(r"[\r\n<>@/\\]", name) or
            re.search(r"\b(?:billetterie|pass|festival|programmation|"
                      r"concert|vente|tarif|groupes|nouveaux)\b", fold(name))):
        return None
    return name


def listed_artists(blocks):
    names, active = [], False
    for i, b in enumerate(blocks):
        text = fold(b["text"])
        if b["tag"].startswith("h"):
            # Some official current-edition lineups use a location heading
            # ("Ils seront à Carhaix") instead of "groupes annoncés".
            # The caller already binds these blocks to the signed edition,
            # and headings stop the list at the next unrelated section.
            roster_heading = re.fullmatch(
                r"(?:ils|elles) seront a [a-z0-9 ]{3,90}", text)
            active = bool(roster_heading or (
                GENRE_LIST.search(text) and
                (ANNOUNCE.search(text) or "groupes" in text)))
        if b["tag"] == "li" and active:
            found = good_artist(b["lead"] or b["text"])
            if found:
                names.append(found)
        if b["tag"] != "p" or not (GENRE_LIST.search(text)
                                  and re.search(r"\b(?:nouveaux|nouvelles|"
                                                r"groupes attendus|groupes annonces)\b", text)
                                  and ":" in b["text"] and i + 1 < len(blocks)):
            continue
        nxt = blocks[i + 1]
        if nxt["tag"] != "p" or not 5 <= len(nxt["text"]) <= 2500 or nxt["text"].count(",") < 2:
            continue
        parts = re.split(r"\s*,\s*|\s+et\s+(?=[^,]{2,85}\.?$)", nxt["text"])
        if 3 <= len(parts) <= 60:
            valid = [good_artist(p) for p in parts]
            if all(valid):
                names.extend(valid)
    unique, result = set(), []
    for name in names:
        k = key(name)
        if k not in unique:
            unique.add(k)
            result.append(name)
    return result



def season_scoped_first_names(doc, html, row, today):
    """Read a locally labelled first-names list, not another seasonal edition.

    The official title must independently prove the signed exact dates/city.
    A separate visible season/year label immediately before the roster heading
    binds the list to that edition. Stop at the next non-list block; navigation,
    historical cards and another season's names never authorize this route.
    """
    if not exact_edition_city(html, row):
        return []
    try:
        start = date.fromisoformat(row["startDate"])
        if start < date.fromisoformat(today):
            return []
        title = _EditionTitle()
        title.feed(html)
        title.close()
        seasons = set(re.findall(
            rf"\b(ete|hiver|printemps|automne)\s+{start.year}\b",
            fold(" ".join(title.parts))))
    except (KeyError, ValueError, TypeError):
        return []
    description = current_edition_description(html, row)
    if description is not None:
        seasons.add(description['season'])
    if len(seasons) != 1:
        return []
    label = next(iter(seasons)) + " " + str(start.year)
    names = []
    blocks = doc.blocks
    for i, heading in enumerate(blocks):
        if (i == 0 or heading["tag"] not in ("h2", "h3")
                or heading["scope"] not in ("main", "article")
                or fold(heading["text"]) not in (
                    "les premiers noms", "premiers noms",
                    "les premiers artistes", "premiers artistes",
                    "les premiers groupes", "premiers groupes")):
            continue
        previous = blocks[i - 1]
        if (previous["tag"] != "p" or previous["scope"] != heading["scope"]
                or fold(previous["text"]) != label):
            continue
        for item in blocks[i + 1:]:
            if item["tag"] != "li" or item["scope"] != heading["scope"]:
                break
            if SENSITIVE.search(fold(item["text"])):
                continue
            name = good_artist(re.sub(r"\s*[↗→]\s*$", "",
                                      item["lead"] or item["text"]))
            if name:
                names.append(name)
    return names



class _SeasonTicketCards(VisibleText):
    """Read visible first-party image alt and status within one section/list item."""
    def __init__(self):
        super().__init__()
        self.sections = []
        self.active = []
        self.cards = []
        self.labels = []

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        tags = [t for t, _ in self.stack]
        if (self.hidden() or "main" not in tags
                or any(t in tags for t in ("nav", "header", "footer", "aside"))):
            return
        if tag == "section":
            section = {"labels": [], "cards": []}
            self.sections.append(section)
            self.active.append((len(self.stack), section))
        if not self.active:
            return
        section = self.active[-1][1]
        if tag == "p" and not self.cards:
            self.labels.append((len(self.stack), section, []))
        if tag == "li":
            self.cards.append((len(self.stack), section, [], []))
        if tag == "img" and self.cards and self.cards[-1][1] is section:
            attributes = dict(attrs)
            if ("hidden" in attributes or attributes.get("aria-hidden") == "true"
                    or re.search(r"display\s*:\s*none|visibility\s*:\s*hidden",
                                 attributes.get("style") or "", re.I)):
                return
            alt = attributes.get("alt")
            # Unlike OCR, this is a literal organizer-authored accessible label.
            if isinstance(alt, str) and 0 < len(alt) <= 180:
                self.cards[-1][3].append(alt)

    def handle_data(self, data):
        if (not self.hidden() and
                not any(t in ("nav", "header", "footer", "aside") for t, _ in self.stack)):
            if self.cards:
                self.cards[-1][2].append(data)
            if self.labels:
                self.labels[-1][2].append(data)

    def handle_endtag(self, tag):
        super().handle_endtag(tag)
        depth = len(self.stack)
        while self.labels and self.labels[-1][0] > depth:
            _, section, values = self.labels.pop()
            section["labels"].append(fold(" ".join(values)))
        while self.cards and self.cards[-1][0] > depth:
            _, section, values, alts = self.cards.pop()
            section["cards"].append((" ".join(values), alts))
        while self.active and self.active[-1][0] > depth:
            self.active.pop()


def seasonal_ticket_card_offers(html, row, today):
    """All explicitly priced and status-labelled tiers of the signed season.

    Unknown status, incomplete price cards and inconsistent duplicate tiers
    defer the entire section. Never pair a price from another list item with
    a status, infer a duration from a festival's dates or advertise a sold
    out tier as available. Only exact signed first-party editions qualify.
    """
    if not exact_edition_city(html, row):
        return {}
    try:
        start = date.fromisoformat(row["startDate"])
        if start < date.fromisoformat(today):
            return {}
        title = _EditionTitle()
        title.feed(html)
        title.close()
        seasons = set(re.findall(
            rf"\b(ete|hiver|printemps|automne)\s+{start.year}\b",
            fold(" ".join(title.parts))))
        description = current_edition_description(html, row)
        if description:
            seasons.add(description["season"])
        if len(seasons) != 1:
            return {}
        label = next(iter(seasons)) + " " + str(start.year)
        parser = _SeasonTicketCards()
        parser.feed(html)
        parser.close()
    except (KeyError, TypeError, ValueError, UnicodeError):
        return {}
    offers = {}
    for section in parser.sections:
        labels = set(section["labels"])
        if not labels.intersection({"billetterie " + label, "les pass " + label,
                                    "tarifs " + label}):
            continue
        season_labels = {m.group() for text in labels for m in re.finditer(
            r"\b(?:ete|hiver|printemps|automne)\s+20[2-4]\d\b", text)}
        if season_labels != {label}:
            continue
        local = {}
        for raw, alts in section["cards"]:
            candidates = [re.fullmatch(
                r"Pass\s+([1-7])\s+jours?\s+([^:;€]{1,65}?)\s*:\s*"
                r"(\d{2,4}(?:[,.]\d{2})?)\s*€\.?", alt.strip(), re.I)
                for alt in alts]
            matched = [m for m in candidates if m]
            if not matched:
                # A paid festival card without a priced accessible label is
                # incomplete. A separate free camping card is not a price tier.
                if re.search(r"\bfestival\b", fold(raw)):
                    return {}
                continue
            if len(matched) != 1:
                return {}
            m = matched[0]
            duration, tier, price = int(m[1]), m[2].strip(), m[3].replace(".", ",")
            visible = fold(raw)
            if (not re.search(r"\b" + re.escape(fold(tier)) + r"\b", visible)
                    or re.search(r"\b(?:disponibilite actualisation|bientot disponible)\b", visible)):
                return {}
            statuses = set(re.findall(
                r"\bdisponibilite\s+(disponible|epuise|complet|sold out)\b", visible))
            statuses = {"disponible" if value == "disponible" else "épuisé"
                        for value in statuses}
            if len(statuses) != 1:
                return {}
            offer_key = (duration, fold(tier))
            value = (tier, price + " €", next(iter(statuses)))
            if offer_key in local and local[offer_key] != value:
                return {}
            local[offer_key] = value
        for k, v in local.items():
            if k in offers and offers[k] != v:
                return {}
            offers[k] = v
    return offers


def seasonal_ticket_summary(offers):
    if not offers or not any(v[2] == "disponible" for v in offers.values()):
        return None
    summary = " ; ".join(
        f"Pass {days} jour{'s' if days > 1 else ''} — {tier} : {price} ({status})"
        for (days, _), (tier, price, status) in sorted(offers.items()))
    summary += " — billetterie officielle ouverte"
    return summary if len(summary) <= 350 else None


def advertised_passes(blocks):
    found = {}
    # Explicit, visible ticket-card offers take precedence over generic
    # article snippets. On live festival pages an old Early Bird tier can
    # read "sold out" beside a CURRENT "tarif normal ... en vente" tier
    # of that same 4-day category. Never veto the newer priced offer
    # merely because a DIFFERENT tier is exhausted.
    for card in blocks:
        if card.get("tag") != "li" or not isinstance(card.get("text"), str):
            continue
        raw = card["text"]
        categories = {int(x.group(1)) for x in PASS.finditer(fold(raw))}
        if len(categories) != 1:
            continue
        prices = list(PRICE.finditer(raw))
        for idx, match in reversed(list(enumerate(prices))):
            following = raw[match.end():min(
                match.end() + 115,
                prices[idx + 1].start() if idx + 1 < len(prices)
                else len(raw))]
            status = fold(following)
            if (re.search(r"\b(?:en vente|ouverte|ouvert|disponible)\b", status)
                    and not re.search(r"\b(?:epuise|sold out|complet)\b", status)):
                found[next(iter(categories))] = (
                    match.group(1).replace(".", ",") + " €")
                break

    # Full official announcements are also first-party price evidence:
    # "Pass 4J est désormais disponible au tarif normal de 239 €"
    # remains true even if ANOTHER tier (Early Bird) is labelled SOLD OUT.
    for block in blocks:
        if not isinstance(block.get("text"), str):
            continue
        for current in NORMAL_PRICE_AVAILABLE.finditer(block["text"]):
            found[int(current.group(1))] = (
                current.group(2).replace(".", ",") + " €")

    text = [b["text"] for b in blocks]
    for i, block in enumerate(text):
        # An article may say "Pass 4J: 239 €; Pass 1J also on sale".
        # Its 4J amount is NOT a 1J price. Only use this fallback if the
        # local block names exactly one pass category. Explicit bound offers
        # above remain usable even in multi-category announcements.
        categories = list(PASS.finditer(fold(block)))
        if len({match.group(1) for match in categories}) != 1:
            continue
        for category in categories:
            if int(category.group(1)) in found:
                continue
            # The price and sale status may be in distinct consecutive
            # blocks. Stop BEFORE another pass category, never borrow its
            # price for a different pass.
            pieces = [block]
            for sibling in text[i + 1:i + 4]:
                if PASS.search(fold(sibling)):
                    break
                pieces.append(sibling)
            near = " ".join(pieces)[:480]
            price = PRICE.search(near)
            if price is None:
                continue
            norm = fold(near)
            if not re.search(r"\b(?:en vente|ouverte|ouvert|disponible)\b", norm):
                continue
            if re.search(r"\b(?:epuise|sold out|complet)\b", norm):
                continue
            found[int(category.group(1))] = price.group(1).replace(".", ",") + " €"
    return found


def matches_edition(doc, row, today, *, root_ok):
    try:
        start = date.fromisoformat(row["startDate"])
        end = date.fromisoformat(row["endDate"])
        if not start <= end or start < date.fromisoformat(today):
            return False
    except (KeyError, TypeError, ValueError):
        return False
    visible = fold(" ".join(b["text"] for b in doc.relevant()))
    if SENSITIVE.search(visible):
        return False
    brand = [w for w in fold(row.get("name", "")).split()
             if len(w) >= 5 and w not in
             ("festival", "festivals", "metal", "rock", "open", "music", "edition")]
    named = any(re.search(r"\b" + re.escape(w) + r"\b", visible)
                for w in brand)
    has_year = re.search(r"\b" + str(start.year) + r"\b", visible) is not None
    if named and has_year:
        return True
    # A first-party news item may refer to "18e édition" and the exact
    # published weekend without repeating the brand/year. Its signed home
    # MUST explicitly name the actual year and edition first.
    days = str(start.day) + " au " + str(end.day)
    return bool(root_ok and "edition" in visible and
                start.month == end.month and days in visible)


def home_matches_edition(doc, row, today):
    """Festival home may have 2026 news <article> before 2027 <main>.

    A news teaser must not hide the signed current edition's own homepage
    section. A cross-edition article itself is still independently checked.
    """
    if matches_edition(doc, row, today, root_ok=False):
        return True
    main_only = Page()
    main_only.blocks = [b for b in doc.blocks if b["scope"] == "main"]
    return bool(main_only.blocks and
                matches_edition(main_only, row, today, root_ok=False))


def signed_rotation(published, today, limit=MAX_HOSTS, tick=None,
                    browser_sites=()):
    if (not isinstance(published, dict) or published.get("schema") != 1 or
            type(limit) is not int or not 0 <= limit <= 60):
        raise ValueError("Invalid signed source rotation")
    grouped = {}
    for row in published["festivals"]:
        url = row.get("officialSite")
        if (not isinstance(url, str) or safe_public_url(url) != url or
                classify(url) in ("TICKETING", "SOCIAL", "MEDIA", "THIRD_PARTY")):
            continue
        try:
            start = row.get("startDate")
            if start is None and row.get("endDate") is None:
                # Recheck signed year-specific future editions awaiting dates.
                m = re.fullmatch(r".+\s+(20[2-4]\d)", row.get("name") or "")
                if (not m or not str(row.get("slug", "")).endswith("-" + m[1])
                        or not date.fromisoformat(today).year <= int(m[1])
                               <= date.fromisoformat(today).year + 2):
                    continue
            elif date.fromisoformat(start) < date.fromisoformat(today):
                continue
        except (ValueError, TypeError, KeyError):
            continue
        grouped.setdefault(url, []).append(row)
    urls = sorted(grouped, key=lambda u: sha256(u.encode()).hexdigest())
    if not urls or not limit:
        return []
    # All slots are reached even when total source count is divisible by 8.
    batch = (date.fromisoformat(today).toordinal() * 2 if tick is None else tick)
    offset = batch % ceil(len(urls) / limit) * limit
    selected = urls[offset:offset + limit]
    # Both the regular 24-host budget and the 48-host push catch-up are
    # full budgets, not just a bound on a partial final slice. Fill unused
    # slots with the start of the same signed rotation. The original batch
    # remains the prefix, so every host is still covered within one complete
    # rotation; overlap between runs is intentional, never within a run.
    if limit >= 24 and len(urls) > limit and len(selected) < limit:
        selected += urls[:limit - len(selected)]
    # Chromium and HTTPS use different rotations. Process the successfully
    # rendered signed roots in THIS cycle, even when outside the raw batch.
    # The regular raw rotation is untouched; browser-only links and unknown
    # domains cannot create extra targets. At most eight roots are added.
    browser_extra = [url for url in urls
                     if url in browser_sites and url not in selected][:8]
    selected += browser_extra[:max(0, 60 - len(selected))]
    return [(url, grouped[url]) for url in selected]


class _OfficialImageEditionIdentity(HTMLParser):
    """Read visible first-party image alt text; no external image fetch."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.alts = []

    def handle_starttag(self, tag, attrs):
        if tag != "img" or len(self.alts) >= 50:
            return
        props = dict(attrs)
        if ("hidden" in props or props.get("aria-hidden") == "true"
                or re.search(r"display\s*:\s*none", props.get("style") or "", re.I)):
            return
        value = props.get("alt")
        if isinstance(value, str) and 8 <= len(value) <= 180:
            self.alts.append(value)


WEEKDAY_2027_LABELS = {
    "lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3,
    "vendredi": 4, "samedi": 5, "dimanche": 6,
}
WEEKDAY_NAMES = "|".join(WEEKDAY_2027_LABELS)
MONTH_NAMES = "|".join(sorted(OFFICIAL_MONTHS, key=len, reverse=True))
WEEKDAY_DATE_SEQUENCE = re.compile(
    r"(?<![a-z0-9])((?:(?:" + WEEKDAY_NAMES +
    r")\s+\d{1,2}\s+){2,7})(" + MONTH_NAMES + r")\s+(20[2-4]\d)\b"
)


def reconcile_official_date_ranges(ranges):
    """One fully dated range may contain corroborating single-day mentions.

    A page can say "Friday 27, Saturday 28, Sunday 29 August" while a
    second conservative parser recognizes only "29 August". That is not
    a contradiction. However, two distinct multi-day intervals, disjoint
    dates and partly overlapping ranges must not silently be reconciled.
    """
    unique = set(ranges)
    if not unique:
        return None
    candidates = [
        interval for interval in unique
        if all(other == interval or (
            other[0] == other[1]
            and interval[0] <= other[0] <= interval[1])
            for other in unique)
    ]
    return candidates[0] if len(candidates) == 1 else None


def undated_official_evidence_diagnostic(html, row, year):
    """Report safe proof flags for an undated signed official site.

    Never return scraped text or HTML, and never grant publication authority:
    the existing independent source validators remain decisive.
    """
    flags = {
        "raw_year_token": False,
        "visible_year_token": False,
        "visible_weekday_sequence": False,
        "title_matches_identity": False,
        "current_edition_logo_alt": False,
    }
    if not isinstance(html, str) or not 0 < len(html) <= 650_000:
        return flags
    title = _EditionTitle()
    images = _OfficialImageEditionIdentity()
    body = VisibleText()
    try:
        title.feed(html)
        title.close()
        images.feed(html)
        images.close()
        body.feed(html)
        body.close()
    except (ValueError, TypeError, UnicodeError):
        return flags
    brand = fold(re.sub(r"\b20[2-4]\d\b", "", row.get("name", "")))
    if len(key(brand)) < 8:
        return flags
    expression = re.compile(
        r"(?<![a-z0-9])" + r"\s+".join(map(re.escape, brand.split()))
        + r"(?![a-z0-9])"
    )
    title_words = fold(" ".join(title.parts))
    visible = fold(" ".join(body.parts))
    flags["raw_year_token"] = bool(re.search(
        r"(?<!\d)" + str(year) + r"(?!\d)", html))
    flags["visible_year_token"] = bool(re.search(
        r"\b" + str(year) + r"\b", visible))
    flags["visible_weekday_sequence"] = any(
        match.group(3) == str(year)
        for match in WEEKDAY_DATE_SEQUENCE.finditer(visible)
    )
    flags["title_matches_identity"] = bool(expression.search(title_words))
    flags["current_edition_logo_alt"] = any(
        expression.search(fold(alt))
        and set(re.findall(r"\b20[2-4]\d\b", fold(alt))) == {str(year)}
        for alt in images.alts
    )
    return flags


def weekday_labelled_official_dates(html, row, year):
    """Bind explicit weekday/day sequences to the registered festival title.

    Some official festivals print VENDREDI 27 SAMEDI 28 DIMANCHE 29 AOUT 2027
    without a numeric range. Do not borrow days from an unrelated organizer
    event, infer an end date, or trust a mismatching weekday/year.
    """
    if not isinstance(html, str) or not 0 < len(html) <= 650_000:
        return None
    title = _EditionTitle()
    images = _OfficialImageEditionIdentity()
    body = VisibleText()
    try:
        title.feed(html)
        title.close()
        images.feed(html)
        images.close()
        body.feed(html)
        body.close()
    except (ValueError, TypeError, UnicodeError):
        return None
    title_words = fold(" ".join(title.parts))
    brand = fold(re.sub(r"\b20[2-4]\d\b", "", row.get("name", "")))
    if len(key(brand)) < 8:
        return None
    expected_brand = re.compile(
        r"(?<![a-z0-9])" +
        r"\s+".join(map(re.escape, brand.split())) + r"(?![a-z0-9])"
    )
    title_brand = bool(expected_brand.search(title_words))
    image_brand = any(
        expected_brand.search(fold(alt))
        and set(re.findall(r"\b20[2-4]\d\b", fold(alt))) == {str(year)}
        for alt in images.alts
    )
    # An explicit contradictory year in the first-party title is a veto,
    # even when an image logo contains the requested edition year.
    title_years = set(re.findall(r"\b20[2-4]\d\b", title_words))
    if ((title_years and title_years != {str(year)})
            or not (title_brand or image_brand)):
        return None
    visible = fold(" ".join(body.parts))
    if OFFICIAL_CANCELLATION.search(visible):
        return None
    matches = set()
    for match in WEEKDAY_DATE_SEQUENCE.finditer(visible):
        if int(match.group(3)) != year:
            continue
        month = OFFICIAL_MONTHS.get(match.group(2))
        if month is None:
            continue
        labels = re.findall(r"(" + WEEKDAY_NAMES + r")\s+(\d{1,2})",
                            match.group(1))
        if not 2 <= len(labels) <= 7:
            return None
        try:
            dates = [date(year, month, int(day)) for _, day in labels]
        except ValueError:
            return None
        if (any(day.weekday() != WEEKDAY_2027_LABELS[label]
                for (label, _), day in zip(labels, dates))
                or any(right.toordinal() != left.toordinal() + 1
                       for left, right in zip(dates, dates[1:]))):
            return None
        matches.add((dates[0], dates[-1]))
    return next(iter(matches)) if len(matches) == 1 else None

def apply_independently_verified_updates(
        target, published, today, fetch=fetch_public_html, limit=MAX_HOSTS,
        tick=None, commune_resolver=verified_commune, browser_fetch=None,
        browser_sites=()):
    """Recheck signed artists/prices and exact first-party city proof.

    A commune marker is only an indicative administrative centre: no precise
    festival entrance is inferred from a former venue or an organizer footer.
    """
    result = deepcopy(target)
    positions = {r["slug"]: i for i, r in enumerate(result["festivals"])}
    report = {"checked_official_hosts": 0, "rechecked_pages": 0,
              "accepted": [], "accepted_changes": [], "unavailable": 0,
              "checked_official_sources": [], "unavailable_official_sources": [],
              "official_edition_diagnostics": [], "browser_recoveries": 0,
              "private_proposal_is_authority": False}
    report["browser_roots_checked"] = 0
    for site, rows in signed_rotation(
            published, today, limit, tick, browser_sites=browser_sites):
        if site in browser_sites:
            report["browser_roots_checked"] += 1
        report["checked_official_hosts"] += 1
        # These URLs are from the previously signed catalogue, never private
        # suggestions. A bounded diagnostics list makes real omissions auditable.
        report["checked_official_sources"].append(site)
        try:
            root_html = fetch(site)
            root = page(root_html)
            report["rechecked_pages"] += 1
        except (OSError, TimeoutError, ValueError, UnicodeError) as exc:
            # This callback comes ONLY from a separate no-secret job that
            # rendered a signed public officialSite. Never launch Chromium
            # inside the privileged Publisher itself. The HTML remains
            # untrusted and must still pass every edition/field validator.
            try:
                if browser_fetch is None:
                    raise ValueError("No isolated browser proof")
                root_html = browser_fetch(site)
                if (not isinstance(root_html, str)
                        or not 0 < len(root_html.encode("utf-8")) <= 1_400_000):
                    raise ValueError("Invalid browser HTML")
                root = page(root_html)
                report["rechecked_pages"] += 1
                report["browser_recoveries"] += 1
            except (OSError, TimeoutError, ValueError, UnicodeError, TypeError,
                    KeyError):
                report["unavailable"] += 1
                # Do not log untrusted exception text, response HTML, or secrets.
                report["unavailable_official_sources"].append({
                    "url": site, "error_type": type(exc).__name__})
                continue
        pages = [(site, root)]
        # Store only independently fetched, safely linked first-party HTML;
        # a future date may appear in official news rather than on the home.
        html_pages = [(site, root_html)]
        # On a current-edition homepage, old news cards may be nested in
        # <article> while the live ticket categories are in <main>. Inspect
        # both as separate first-party content scopes, not one mixed roster.
        main_only = Page()
        main_only.blocks = [b for b in root.blocks if b["scope"] == "main"]
        if main_only.blocks:
            pages.append((site, main_only))
        # The current-edition H1 logo can be outside <main>, while old news
        # teasers are <article> inside it. The article-first selection then
        # hides the official 2027 heading and the live ticket categories.
        # Recompose visible non-article blocks of the SAME signed homepage.
        current_home = Page()
        current_home.blocks = [
            dict(b, scope="main") for b in root.blocks
            if b["scope"] != "article"
        ]
        if current_home.blocks:
            pages.append((site, current_home))
        for link in linked_pages(site, root):
            try:
                try:
                    linked_html = fetch(link)
                except (OSError, TimeoutError, ValueError, UnicodeError):
                    if browser_fetch is None:
                        raise
                    # Only same-origin links proven by the parsed home DOM;
                    # the loader separately checks their exact provenance.
                    linked_html = browser_fetch(link)
                linked_doc = page(linked_html)
                pages.append((link, linked_doc))
                html_pages.append((link, linked_html))
                report["rechecked_pages"] += 1
            except (OSError, TimeoutError, ValueError, UnicodeError, TypeError):
                continue
        for old in rows:
            slug = old["slug"]
            new = result["festivals"][positions[slug]]
            # An independently staged ticket-availability update is not a
            # competing date/lineup/price edit. Permit the OFFICIAL scanner
            # to enrich its signed edition in the SAME run; all earlier stage
            # changes are separately validated by safe_target before this
            # second, independently sourced delta is admitted.
            prior_fields = {f for f in set(old) | set(new)
                            if (f in old) != (f in new)
                            or old.get(f) != new.get(f)}
            if prior_fields - {"ticketAvailability"}:
                if len(report["official_edition_diagnostics"]) < 75:
                    report["official_edition_diagnostics"].append({
                        "slug": slug, "official_site": site,
                        "reason": "different_from_current_signed_edition"})
                continue
            before_official = deepcopy(new)
            root_ok = (home_matches_edition(root, old, today)
                       or matches_edition(current_home, old, today,
                                          root_ok=False))
            claims, prices, sources = [], {}, []
            for url, doc in pages:
                if not matches_edition(doc, old, today, root_ok=root_ok):
                    continue
                names = listed_artists(doc.relevant())
                offers = advertised_passes(doc.relevant())
                if names or offers:
                    claims += names
                    prices.update(offers)
                    sources.append(url)
            # A page can explicitly separate winter and summer rosters.
            # This additional route independently binds the list to the
            # exact signed edition rather than accepting brand/year alone.
            for url, html in html_pages:
                seasonal_names = season_scoped_first_names(
                    page(html), html, old, today)
                if seasonal_names:
                    claims.extend(seasonal_names)
                    sources.append(url)
            # Separate complete, explicitly labelled price tiers from the
            # legacy one-price-per-duration parser. Do not reconcile conflicting
            # page snapshots or replace an unrelated existing price summary.
            seasonal_offers, seasonal_sources = {}, []
            seasonal_conflict = False
            for url, html in html_pages:
                offers = seasonal_ticket_card_offers(html, old, today)
                if not offers:
                    continue
                if any(k in seasonal_offers and seasonal_offers[k] != v
                       for k, v in offers.items()):
                    seasonal_conflict = True
                seasonal_offers.update(offers)
                seasonal_sources.append(url)
            # A successful raw HTTPS response can still contain only the
            # site's loading placeholder for dynamic ticket availability.
            # Read the isolated same-root browser evidence in that case only,
            # not as a way to override a contradictory concrete raw status.
            rendered_ticket_offers = False
            raw_visible = VisibleText()
            raw_visible.feed(root_html)
            raw_visible.close()
            raw_words = fold(" ".join(raw_visible.parts))
            if (not seasonal_offers and not seasonal_conflict and not prices
                    and old.get("price") is None
                    and browser_fetch is not None and site in browser_sites
                    and exact_edition_city(root_html, old)
                    and re.search(r"\bdisponibilite actualisation\b", raw_words)
                    and not re.search(
                        r"\bdisponibilite (?:disponible|epuise|complet|sold out)\b",
                        raw_words)):
                try:
                    rendered = browser_fetch(site)
                    if (not isinstance(rendered, str)
                            or not 0 < len(rendered.encode("utf-8")) <= 650_000):
                        raise ValueError("Invalid rendered ticket evidence")
                    if rendered != root_html:
                        offers = seasonal_ticket_card_offers(rendered, old, today)
                        if offers:
                            seasonal_offers = offers
                            seasonal_sources.append(site)
                            rendered_ticket_offers = True
                except (OSError, TimeoutError, ValueError, UnicodeError, TypeError, KeyError):
                    pass
            tier_summary = (seasonal_ticket_summary(seasonal_offers)
                            if not seasonal_conflict else None)
            current_lineup = old.get("lineup")
            current_lineup = current_lineup if isinstance(current_lineup, list) else []
            cleaned_lineup = verified_artist_alias_cleanup(current_lineup, claims)
            new_names, seen = [], {
                key(n) for n in current_lineup if isinstance(n, str)
            }
            for n in claims:
                # A long artist billing is the same solo act only for an
                # explicit "celebrating the songs of" performance qualifier.
                equivalent = (key(n) in seen or
                              any(fold(n).startswith(fold(old_name) +
                                      " celebrating the songs of ")
                                  for old_name in current_lineup
                                  if isinstance(old_name, str)))
                if not equivalent:
                    seen.add(key(n))
                    new_names.append(n)
            fields = []
            if ((new_names or cleaned_lineup != current_lineup)
                    and isinstance(old.get("lineup"), list)
                    and type(old.get("bands")) is int and
                    old["bands"] == len(old["lineup"])):
                new["lineup"] = cleaned_lineup + new_names
                new["bands"] = len(new["lineup"])
                fields.extend(("lineup", "bands"))
            if prices:
                summary = " ; ".join(
                    f"Pass {n} jour{'s' if n > 1 else ''} : {prices[n]}"
                    for n in sorted(prices, reverse=True))
                summary += " — billetterie officielle ouverte"
                old_price = old.get("price")
                if ((old_price is None or
                     (isinstance(old_price, str) and any(
                         f"pass {n} jour" in fold(old_price) for n in prices))) and
                        old_price != summary):
                    new["price"] = summary
                    fields.append("price")
            if (tier_summary is not None and old.get("price") is None
                    and not prices):
                new["price"] = tier_summary
                fields.append("price")
                sources.extend(seasonal_sources)
            commune_diagnostic = "not_eligible"
            # The signed current-edition title may explicitly name the town.
            # Publisher re-fetches the site itself, then independently resolves
            # that exact commune through the fixed government geocoding API.
            # Neither private leads nor a previously used venue are authority.
            if (old.get("lat") is None and old.get("lon") is None
                    and old.get("showOnMap") is not True
                    and old.get("futureVenueConfirmed") is not True
                    and old.get("geoVerification") is None
                    and old.get("geoPrecision") is None):
                # A title with signed brand, EXACT dates and one town is its
                # own first-party edition proof. The site's news teaser may
                # omit the year, so root_ok cannot be an additional gate.
                # A current edition's town may be proved only by a
                # same-host linked official ticket/news page. Reject any
                # disagreement between independently parsed current-year
                # claims; do not borrow last year's venue or winter dates.
                claims_city = []
                for linked_url, html in html_pages:
                    claim = exact_edition_city(html, old)
                    if claim is None and linked_url != site:
                        city = current_official_ticket_city(html, old)
                        if city:
                            claim = {"slug": slug, "city": city, "source": site}
                    if claim is not None:
                        claims_city.append(claim)
                distinct_cities = {
                    normal_city(c["city"]) for c in claims_city}
                commune_diagnostic = ("no_current_city_proof" if not distinct_cities
                                      else "conflicting_current_cities" if len(distinct_cities) > 1
                                      else "city_claim_not_accepted")
                claim = (claims_city[0] if len(distinct_cities) == 1
                         else None)
                if (claim and claim.get("source") == site
                        and claim.get("slug") == slug
                        and (not old.get("city")
                             or normal_city(old["city"]) == normal_city(claim["city"]))):
                    try:
                        commune = commune_resolver(claim["city"], old.get("department"))
                    except (OSError, TimeoutError, ValueError, UnicodeError):
                        commune = None
                    commune_diagnostic = ("admin_resolution_returned" if commune
                                          else "admin_resolution_unavailable_or_ambiguous")
                    if (commune and normal_city(commune.get("city")) == normal_city(claim["city"])
                            and type(commune.get("lat")) in (float, int)
                            and type(commune.get("lon")) in (float, int)
                            and isinstance(commune.get("codeInsee"), str)
                            and isinstance(commune.get("geoSource"), str)):
                        new.update({
                            "city": commune["city"],
                            "lat": commune["lat"], "lon": commune["lon"],
                            "geoCity": commune["city"],
                            "geoPrecision": "commune",
                            "geoInsee": commune["codeInsee"],
                            "geoSource": commune["geoSource"],
                            "showOnMap": True,
                            "geoVerification": {
                                "proofMode": "current-edition-commune-direct-official.v1",
                                "firstObserved": today,
                                "verifiedAt": today,
                                "officialSite": site,
                                "markerMeaning": "centre_indicatif_de_commune",
                            },
                        })
                        fields.extend(sorted(COMMUNE_FIELDS))
                        sources.append(site)
            # A published, SIGNED future-edition city is already an accepted
            # municipality, but not proof of this year's exact entrance.
            # When the same official homepage independently reaffirms the
            # exact future weekend, the government's unique administrative
            # centre can become an APPROXIMATE marker (never copied venue GPS).
            # This is a *city* fallback only; don't infer the town from an
            # archive, a private discovery hint or unlabelled other-event text.
            # An organizer may still display its previous edition while a
            # named official programming partner has announced the next one.
            # Recheck ONLY the already signed, role-qualified producer URL;
            # an event card must prove the exact city + dates in ONE section.
            programmer_proven, programmer_url = False, None
            if (not root_ok and old.get("lat") is None
                    and old.get("lon") is None
                    and isinstance(old.get("city"), str)
                    and isinstance(old.get("department"), str)
                    and old.get("startDate") and old.get("endDate")):
                programmer_url = signed_programmer_city_url(old)
                if programmer_url:
                    try:
                        # A contradictory current-year organizer announcement
                        # is a veto, even if the partner page looks correct.
                        visible_home = VisibleText()
                        visible_home.feed(root_html)
                        visible_home.close()
                        first = date.fromisoformat(old["startDate"])
                        second = date.fromisoformat(old["endDate"])
                        current_home_intervals = {
                            (a, b) for _, _, a, b in current_visible_ranges(
                                fold(" ".join(visible_home.parts)), first.year)}
                        if not current_home_intervals or current_home_intervals == {
                                (first, second)}:
                            html = fetch(programmer_url)
                            report["rechecked_pages"] += 1
                            programmer_proven = signed_programmer_current_city(
                                html, old)
                    except (OSError, TimeoutError, ValueError, UnicodeError):
                        programmer_proven = False
            if ((root_ok or programmer_proven)
                    and isinstance(old.get("city"), str) and old["city"].strip()
                    and isinstance(old.get("department"), str)
                    and re.fullmatch(r"(?:\d{2,3}|2[AB])",
                                     old["department"].upper())
                    and old.get("startDate") is not None
                    and old.get("endDate") is not None
                    and old.get("lat") is None and old.get("lon") is None
                    and new.get("lat") is None and new.get("lon") is None
                    and new.get("showOnMap") is not True
                    and old.get("futureVenueConfirmed") is not True
                    and new.get("geoVerification") is None
                    and new.get("geoPrecision") is None):
                try:
                    begin = date.fromisoformat(old["startDate"])
                    end = date.fromisoformat(old["endDate"])
                    first_party = VisibleText()
                    first_party.feed(root_html)
                    first_party.close()
                    current_words = " ".join(
                        fold(" ".join(first_party.parts)).split())
                    intervals = {
                        (a, b) for _from, _to, a, b
                        in current_visible_ranges(current_words, begin.year)
                    }
                    # Reject multiple competing event weekends: one signed
                    # municipality cannot rescue ambiguous first-party dates.
                    exact_current_weekend = (
                        begin >= date.fromisoformat(today)
                        and begin.year == end.year
                        and (intervals == {(begin, end)}
                             or (programmer_proven and not intervals))
                        and not OFFICIAL_CANCELLATION.search(current_words))
                except (TypeError, ValueError, UnicodeError, KeyError):
                    exact_current_weekend = False
                if exact_current_weekend:
                    try:
                        commune = commune_resolver(
                            old["city"], old["department"])
                    except (OSError, TimeoutError, ValueError, UnicodeError):
                        commune = None
                    if (commune
                            and normal_city(commune.get("city"))
                                == normal_city(old["city"])
                            and type(commune.get("lat")) in (float, int)
                            and type(commune.get("lon")) in (float, int)
                            and isinstance(commune.get("codeInsee"), str)
                            and isinstance(commune.get("geoSource"), str)):
                        new.update({
                            "city": commune["city"],
                            "lat": commune["lat"], "lon": commune["lon"],
                            "geoCity": commune["city"],
                            "geoPrecision": "commune",
                            "geoInsee": commune["codeInsee"],
                            "geoSource": commune["geoSource"],
                            "showOnMap": True,
                            "geoVerification": {
                                "proofMode": "signed-city-current-edition-centre.v1",
                                "firstObserved": today,
                                "verifiedAt": today,
                                "officialSite": site,
                                "markerMeaning": "centre_indicatif_de_commune",
                            },
                        })
                        fields.extend(sorted(COMMUNE_FIELDS))
                        sources.append(programmer_url if programmer_proven else site)
            # An already signed future edition without dates is rechecked
            # directly on the registered first-party homepage. Do not infer
            # a multi-day festival from an isolated opening date.
            if old.get("startDate") is None and old.get("endDate") is None:
                m = re.fullmatch(r"(.+)\s+(20[2-4]\d)", old.get("name") or "")
                if m and str(old.get("slug", "")).endswith("-" + m[2]):
                    parent = {"name": m[1]}
                    year = int(m[2])
                    proposed_ranges, verified_urls = set(), []
                    undated_page_proof = []
                    contradicted = False
                    for official_url, official_html in html_pages:
                        visible = official_date(official_html, parent, year)
                        jsonld = official_structured_date(official_html, parent, year)
                        weekdays = weekday_labelled_official_dates(
                            official_html, old, year)
                        matching_jsonld = matching_official_jsonld_present(
                            official_html, parent, year)
                        undated_page_proof.append({
                            "page_role": ("registered_home" if official_url == site
                                          else "same_host_link"),
                            **undated_official_evidence_diagnostic(
                                official_html, old, year),
                            "visible_date_validator": visible is not None,
                            "structured_date_validator": jsonld is not None,
                            "weekday_date_validator": weekdays is not None,
                            "visible_date_single_day": bool(
                                visible and visible[0] == visible[1]),
                            "weekday_date_spans_days": bool(
                                weekdays and weekdays[1] > weekdays[0]),
                            "date_readings_differ": bool(
                                visible and weekdays and visible != weekdays),
                            "matching_jsonld_invalid": bool(
                                matching_jsonld and jsonld is None),
                        })
                        # A full date range and one of its constituent
                        # days agree. Two distinct multi-day ranges never do.
                        if matching_jsonld and jsonld is None:
                            contradicted = True
                            break
                        found = [d for d in (visible, jsonld, weekdays)
                                 if d is not None]
                        if found:
                            proposed_ranges.update(found)
                            verified_urls.append(official_url)
                    # Reconcile only nested single days, across all first-party
                    # pages. Never invent a missing end date or pick between
                    # incompatible calendar announcements.
                    dates = (reconcile_official_date_ranges(proposed_ranges)
                             if not contradicted else None)
                    if (dates and dates[0] > date.fromisoformat(today)
                            and dates[1] > dates[0]
                            and (dates[1] - dates[0]).days <= 7):
                        new["startDate"], new["endDate"] = (
                            dates[0].isoformat(), dates[1].isoformat())
                        new["days"] = str((dates[1] - dates[0]).days + 1)
                        new["dateRangeIsContinuous"] = True
                        new["status"] = "Annoncé"
                        new["verificationStatus"] = (
                            "Dates confirmées sur le site officiel")
                        fields.extend(("startDate", "endDate", "days",
                                       "dateRangeIsContinuous", "status",
                                       "verificationStatus"))
                        sources.extend(verified_urls)
            # A previously verified edition may still carry an obsolete
            # "end date unknown" note from its earlier undated publication.
            # Do not mutate text from intuition: re-read the exact multi-day
            # range from the signed official host in this same Publisher run.
            fresh_notes = clean_obsolete_date_notes(old.get("notes"))
            if (fresh_notes != old.get("notes") and
                    isinstance(old.get("startDate"), str) and
                    isinstance(old.get("endDate"), str)):
                try:
                    signed_range = (date.fromisoformat(old["startDate"]),
                                    date.fromisoformat(old["endDate"]))
                except ValueError:
                    signed_range = None
                if signed_range and signed_range[0] < signed_range[1]:
                    edition_year = signed_range[0].year
                    parent_name = re.sub(
                        r"\s+20[2-4]\d$", "", str(old.get("name") or ""))
                    parent_name = {"name": parent_name}
                    ranges, official_date_urls = set(), []
                    for official_url, official_html in html_pages:
                        proofs = (
                            official_date(official_html, parent_name, edition_year),
                            official_structured_date(
                                official_html, parent_name, edition_year),
                            weekday_labelled_official_dates(
                                official_html, old, edition_year))
                        valid = [d for d in proofs if d is not None]
                        if valid:
                            ranges.update(valid)
                            official_date_urls.append(official_url)
                    if (reconcile_official_date_ranges(ranges) == signed_range
                            and official_date_urls):
                        new["notes"] = fresh_notes
                        fields.append("notes")
                        sources.extend(official_date_urls)
            # Reconcile old ticket-status prose only after the signed
            # current edition has been freshly checked on its own homepage.
            # This runs even when the canonical price is already correct.
            if root_ok and prices:
                fresh_ticket_notes = reconcile_obsolete_ticket_notes(
                    new.get("notes"), prices, root.blocks, root_html)
                if fresh_ticket_notes != new.get("notes"):
                    new["notes"] = fresh_ticket_notes
                    if "notes" not in fields:
                        fields.append("notes")
                    sources.append(site)
            if len(report["official_edition_diagnostics"]) < 75:
                report["official_edition_diagnostics"].append({
                    "slug": slug, "official_site": site,
                    "homepage_matches_signed_edition": root_ok,
                    "linked_pages_fetched": len(html_pages) - 1,
                    "artist_names_claimed": len(claims),
                    "artist_names_new": len(new_names),
                    "open_pass_categories_found": sorted(prices),
                    "seasonal_ticket_tiers_found": len(seasonal_offers),
                    "seasonal_ticket_conflict": seasonal_conflict,
                    "seasonal_ticket_rendered_proof": rendered_ticket_offers,
                    "commune_diagnostic": ("accepted" if "geoVerification" in fields
                                           else commune_diagnostic),
                    "fields_proposed": list(fields),
                    "ticket_note_proof": ({
                        "old_note_outdated": (
                            expected_ticket_notes_after_official_sale(
                                old["notes"], prices[4]) != old["notes"]),
                        "visible_html_sold_out": (
                            _current_official_early_bird_sold_out(
                                _ticket_visible_words_from_html(root_html))),
                        "parsed_blocks_sold_out": (
                            _current_official_early_bird_sold_out(fold(" ".join(
                                b["text"] for b in root.blocks)))),
                    } if root_ok and 4 in prices and
                    isinstance(old.get("notes"), str) and
                    "early bird" in fold(old["notes"]) else None),
                    **({"undated_page_proof": undated_page_proof}
                       if old.get("startDate") is None and
                          old.get("endDate") is None and
                          isinstance(old.get("name"), str) and
                          re.fullmatch(r".+\s+20[2-4]\d", old["name"])
                       else {}),
                    "reason": ("proven_update" if fields
                               else "no_changed_fields_from_official_evidence"),
                })
            if not fields:
                continue
            if isinstance(old.get("lastVerified"), str):
                new["lastVerified"] = today
                fields.append("lastVerified")
            previous_urls = old.get("auditSources")
            used = [u for u in previous_urls if isinstance(u, str)] if isinstance(previous_urls, list) else []
            for source in sources:
                if source not in used:
                    used.append(source)
            new["auditSources"] = used[:20]
            fields.append("auditSources")
            if any((f in before_official) != (f in new)
                   or before_official.get(f) != new.get(f)
                   for f in set(before_official) | set(new)
                   if f not in CHANGEABLE):
                raise ValueError("Unproven mutation of festival fields")
            report["accepted"].append(slug)
            report["accepted_changes"].append({
                "slug": slug, "fields": fields,
                "artists_added": len(new_names) if "lineup" in fields else 0})
    if report["accepted"]:
        result["generatedAt"] = today
    return result, report
