"""Private-only research on dynamically discovered official municipality websites.

A website in a private intake report cannot authorize an HTTP request.
The engine first independently reconstructs the current Geo -> DILA -> mairie
link, THEN and only then visits that precise independently rederived HTTPS
host. This scans at most 3 same-host links, stores only bounded festival-name
research clues and cannot create a catalogue patch, approve a festival,
verify an edition or make the municipality an organizer.

New municipalities, domains, rock and punk festivals need no allowlist.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from dns_pinned_https import safe_public_url, fetch_public_html
from national_municipal_source_research import (
    INSEE, SAFE_ID, SCHEMA as MUNICIPAL_SCHEMA,
    verified_commune, delegated_municipal_commune,
    mairie_records_url, fetch_dila_records, verified_mairie_site,
)
from source_qualification import Anchors, normalized

SCHEMA = "grossesondes.national-municipal-pages-private.v1"
QUEUE_SCHEMA = "grossesondes.national-festival-discovery-private.v1"
MAX_WEBSITES = 2
MAX_PAGES_PER_WEBSITE = 4  # homepage + three same-host pages
MAX_ANCHORS_PER_PAGE = 180
MAX_DISCOVERED_URLS = 12
MAX_PAGE_HTML = 650_000
MAX_VISIBLE_CHARS = 45_000
MAX_UNKNOWN_MUSIC_LINKS = 16  # bounded PRIVATE clues, no event acceptance

# Generic editorial page roles, NOT festival names, municipality hostnames,
# or an authorized list of festival/event sources.
AGENDA_ROLE = re.compile(
    r"\b(?:agenda|actualites?|actus?|news|evenements?|"
    r"manifestations?|sortir|sorties|culture|festivals?|"
    r"concerts?|spectacles?|programmation|vie associative|associations?)\b"
)
INVALID_PATH = re.compile(r"(?:^|/)\.\.?(?:/|$)")
HTML_EXT = re.compile(r"\.(?:pdf|json|xml|csv|ics|docx?|xlsx?|zip|rar|7z|"
                      r"jpe?g|png|gif|svg|webp|mp[34]|avi|exe|php5)$", re.I)
# A security gateway is not an absence of a festival. Do not bypass it.
ACCESS_CHALLENGE = re.compile(
    r"\b(?:secure handler for intelligent enforcement|"
    r"verification de securite|verifie que votre navigateur est legitime|"
    r"checking your browser|just a moment cloudflare|captcha required)\b"
)


def safe_same_host_article(href, base, root):
    """Even an attributed mairie may not redirect research to arbitrary URLs."""
    if (not isinstance(href, str) or not 0 < len(href) <= 800
            or "%" in href or "\\" in href
            or not isinstance(root, str)
            or safe_public_url(root) != root
            or urlsplit(root).path != "/"):
        return None
    try:
        # urljoin() normalizes dot segments, so reject them in the ORIGINAL
        # untrusted href before normalizing a potentially dangerous path.
        raw = urlsplit(href)
        if (INVALID_PATH.search(raw.path) or "//" in raw.path
                or raw.scheme not in ("", "https")):
            return None
        value = urljoin(base, href)
        parts = urlsplit(value)
        if (safe_public_url(value) != value
                or parts.hostname != urlsplit(root).hostname
                or parts.path in ("", "/")
                or "//" in parts.path
                or INVALID_PATH.search(parts.path)
                or HTML_EXT.search(parts.path)
                or len(parts.path) > 500):
            return None
        return value
    except (TypeError, ValueError, UnicodeError):
        return None



class VisibleResearchText(HTMLParser):
    """Visible HTML text only; hidden ancestor content is not evidence.

    A hidden DOM subtree may include fabricated event dates or names. Unlike
    a generic text stripper, this parser refuses those elements, including
    aria-hidden, templates, scripts, SVG, CSS-hidden blocks, and descendants.
    """
    HIDDEN_TAGS = {"script", "style", "template", "noscript", "svg", "iframe"}
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.parts = []
        self.characters = 0

    def handle_starttag(self, tag, attrs):
        if self.skip_depth:
            if tag not in self.VOID:
                self.skip_depth += 1
            return
        attributes = dict(attrs)
        style = (attributes.get("style") or "").lower().replace(" ", "")
        concealed = (
            tag in self.HIDDEN_TAGS or
            "hidden" in attributes or
            str(attributes.get("aria-hidden", "")).lower() == "true" or
            "display:none" in style or "visibility:hidden" in style
        )
        if concealed and tag not in self.VOID:
            self.skip_depth = 1

    def handle_endtag(self, tag):
        if self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data):
        if not self.skip_depth and self.characters < MAX_VISIBLE_CHARS:
            snippet = data[:MAX_VISIBLE_CHARS - self.characters]
            self.parts.append(snippet)
            self.characters += len(snippet)


def _visible(html):
    if not isinstance(html, str) or not 0 < len(html) <= MAX_PAGE_HTML:
        raise ValueError("Unsafe or oversized municipal HTML")
    parser = VisibleResearchText()
    parser.feed(html)
    parser.close()
    raw = " ".join(parser.parts)
    if len(raw) > MAX_VISIBLE_CHARS:
        raw = raw[:MAX_VISIBLE_CHARS]
    return normalized(raw)


def _visible_named_festival(html, name):
    """A named mention is ONLY evidence to investigate, NEVER a proof."""
    text = _visible(html)
    title = normalized(name)
    if not 7 <= len(title) <= 160 or len(title.split()) < 2:
        return False
    # Exact word-sequence, not "Rock" anywhere on a tourism home page.
    return re.search(r"(?<![a-z0-9])" + re.escape(title) +
                     r"(?![a-z0-9])", text) is not None


def _candidate_links(html, base, root, festival_name, year, today):
    if not isinstance(html, str) or len(html) > MAX_PAGE_HTML:
        return []
    parser = Anchors()
    try:
        parser.feed(html)
        parser.close()
    except (TypeError, ValueError, UnicodeError):
        return []
    title = normalized(festival_name)
    year_text = str(year)
    choices = {}
    for href, label, _context in parser.anchors[:MAX_ANCHORS_PER_PAGE]:
        url = safe_same_host_article(href, base, root)
        if url is None:
            continue
        path = urlsplit(url).path.replace("-", " ").replace("_", " ")
        words = normalized(str(label)[:180] + " " + path)
        years = set(re.findall(r"(?<![0-9])20[2-4][0-9](?![0-9])", words))
        if years and year_text not in years:
            continue
        exact = len(title.split()) >= 2 and re.search(
            r"(?<![a-z0-9])" + re.escape(title) +
            r"(?![a-z0-9])", words) is not None
        has_role = AGENDA_ROLE.search(words) is not None
        if not exact and not has_role:
            continue
        score = 0 if exact else (1 if year_text in years else 2)
        choices[url] = min(score, choices.get(url, score))
    # Week-based rotation lets a long municipal navigation menu be covered
    # over time, without a fixed URL or organizer inventory.
    ordered = sorted(choices.items(), key=lambda x: (x[1], x[0]))
    if not ordered:
        return []
    best = [u for u, score in ordered if score < 2]
    generic = [u for u, score in ordered if score == 2]
    if generic:
        offset = (date.fromisoformat(today).toordinal() // 7) % len(generic)
        generic = generic[offset:] + generic[:offset]
    return (best + generic)[:MAX_DISCOVERED_URLS]



# Festival and Concerts must accept previously unknown names. Genre keywords
# are only broad SEARCH HINTS, not a whitelist of artists or festival brands.
MUSIC_WORDS = re.compile(
    r"\b(?:metal|metallique|rock|hardrock|hardcore|punk|"
    r"grind|doom|stoner|sludge|heavy|thrash|deathcore|metalcore|"
    r"rockabilly|grunge|screamo|concerts?|musique|"
    r"festival|fest|tournee|tourne es|live|gig|showcase)\b"
)
# Artistic event names often embed their genre in one token:
# e.g. "GermiRock'n Co". This only authorizes private research.
EMBEDDED_MUSIC_NAME = re.compile(
    r"\b[a-z0-9]*(?:rock|metal|punk|hardcore)[a-z0-9]*\b"
    # Named festivals may end in -fest (Hellfest, an unknown XXfest).
    # Never use an arbitrary interior 'fest' substring: the word
    # "manifestation" is administrative, not a music event.
    r"|\b[a-z0-9]{3,}fest\b"
)
GENERIC_LABEL = re.compile(
    r"^(?:agenda|actualites?|evenements?|manifestations?|"
    r"concerts?|festivals?|culture|programmation|"
    r"en savoir plus|voir plus|lire la suite|decouvrir|"
    r"consulter|infos? pratiques?|voir l evenement|billetterie)$"
)
FESTIVAL_LABEL = re.compile(r"\b(?:festival|fest)\b")
TOUR_LABEL = re.compile(r"\b(?:tournee|tour|tour dates)\b")
CONCERT_LABEL = re.compile(r"\b(?:concert|concerts|live|gig|soiree)\b")
MUNICIPAL_EVENT_PATH = re.compile(
    r"/(?:evenement|evenements|event|agenda|actualite|"
    r"actualites|manifestation|festivals?|concerts?)(?:/|-|$)"
)


def unknown_municipal_music_links(html, base, site):
    """Visible linked event NAMES unknown to the pre-existing festival catalog.

    Called ONLY on pages visited after fresh independent Geo+DILA proof.
    Each clue is a non-authorizing index-to-URL research suggestion.
    No untrusted link is fetched here. A title with no explicit music/festival
    hint remains outside this narrow research queue; it can still be found
    through broader indexes elsewhere.
    """
    if (not isinstance(html, str) or len(html) > MAX_PAGE_HTML
            or safe_public_url(site) != site):
        return []
    parser = Anchors()
    try:
        parser.feed(html)
        parser.close()
    except (TypeError, UnicodeError, ValueError):
        return []
    rows, seen = [], set()
    for href, label, _nearby in parser.anchors[:MAX_ANCHORS_PER_PAGE]:
        target = safe_same_host_article(href, base, site)
        if target is None or target in seen:
            continue
        if not isinstance(label, str) or not 7 <= len(label.strip()) <= 160:
            continue
        # No URL, scripts, email, or copied HTML can be an event title.
        if re.search(r"[<>{}\x00-\x1f]", label):
            continue
        name = " ".join(label.split())
        name_fold = normalized(name)
        if not 5 <= len(name_fold) <= 160 or GENERIC_LABEL.fullmatch(name_fold):
            continue
        path_fold = normalized(urlsplit(target).path.replace("-", " "))
        # When the event's name is unconventional (e.g. GermiRock'n Co),
        # an event detail URL supplies context, but it never supplies proof.
        contextual = MUNICIPAL_EVENT_PATH.search(
            urlsplit(target).path.lower()) is not None
        genre = MUSIC_WORDS.search(name_fold) or EMBEDDED_MUSIC_NAME.search(name_fold)
        path_music = MUSIC_WORDS.search(path_fold) or EMBEDDED_MUSIC_NAME.search(path_fold)
        if not genre and not (contextual and path_music):
            continue
        if FESTIVAL_LABEL.search(name_fold):
            classification = "POSSIBLE_FESTIVAL_REVIEW_ONLY"
        elif TOUR_LABEL.search(name_fold) or CONCERT_LABEL.search(name_fold):
            classification = "POSSIBLE_CONCERT_OR_TOUR_REVIEW_ONLY"
        else:
            classification = "UNCLASSIFIED_MUSIC_EVENT_REVIEW_ONLY"
        seen.add(target)
        rows.append({
            "title_hint": name,
            "detail_url_review_only": target,
            "index_url_review_only": base,
            "classification": classification,
            "review_only": True,
            "festival_verified": False,
            "concert_verified": False,
            "date_verified": False,
            "publication_authorized": False,
        })
        if len(rows) >= MAX_UNKNOWN_MUSIC_LINKS:
            break
    return rows


def _rederive_municipal_site(record, dossier,
                             commune_lookup=verified_commune,
                             delegated_lookup=delegated_municipal_commune,
                             directory_fetch=fetch_dila_records):
    """Private report and candidate names NEVER suffice to fetch a website."""
    if (not isinstance(record, dict) or not isinstance(dossier, dict)
            or record.get("status") != "MUNICIPAL_WEBSITE_RESEARCH_ONLY"
            or record.get("dossier_id") != dossier.get("id")
            or record.get("city_hint") != dossier.get("city_hint")
            or not isinstance(dossier.get("name_hint"), str)
            or not isinstance(dossier.get("city_hint"), str)
            or not isinstance(record.get("code_insee"), str)
            or INSEE.fullmatch(record["code_insee"]) is None
            or not isinstance(record.get("municipal_website"), str)):
        return None
    site = record["municipal_website"]
    if (safe_public_url(site) != site
            or site != "https://" + (urlsplit(site).hostname or "") + "/"
            or record.get("municipal_directory_source") !=
            mairie_records_url(record["code_insee"])):
        return None

    city = dossier["city_hint"]
    current = commune_lookup(city)
    if current is None:
        current = delegated_lookup(city)
    if not isinstance(current, dict):
        return None
    verified_city = current.get("city")
    if (not isinstance(verified_city, str)
            or current.get("codeInsee") != record["code_insee"]):
        return None

    if record.get("administrative_relation") == "COMMUNE_DELEGUEE_RESEARCH_ONLY":
        if (current.get("delegated_city") != city
                or current.get("delegated_code_insee") !=
                record.get("delegated_code_insee")
                or record.get("parent_commune") != verified_city):
            return None
    elif (record.get("delegated_commune") is not None
          or record.get("parent_commune") is not None
          or normalized(verified_city) != normalized(city)):
        return None
    official = verified_mairie_site(directory_fetch(
        mairie_records_url(record["code_insee"])),
        record["code_insee"], verified_city)
    if official != site:
        return None
    return site


def scan(queue, municipal, today, *, fetch=fetch_public_html,
         commune_lookup=verified_commune,
         delegated_lookup=delegated_municipal_commune,
         directory_fetch=fetch_dila_records, limit=MAX_WEBSITES):
    if (not isinstance(queue, dict) or queue.get("schema") != QUEUE_SCHEMA
            or not isinstance(queue.get("dossiers"), list)
            or not isinstance(municipal, dict)
            or municipal.get("schema") != MUNICIPAL_SCHEMA
            or municipal.get("as_of") != today
            or municipal.get("review_only") is not True
            or municipal.get("publication_authorized") is not False
            or municipal.get("publications") != 0
            or not isinstance(municipal.get("rows"), list)
            or len(municipal["rows"]) > 3
            or type(limit) is not int or not 0 <= limit <= MAX_WEBSITES):
        raise ValueError("Untrusted municipal private source report")
    current = date.fromisoformat(today)
    dossiers = {
        x["id"]: x for x in queue["dossiers"][:200]
        if isinstance(x, dict) and isinstance(x.get("id"), str)
        and SAFE_ID.fullmatch(x["id"])
        and type(x.get("edition_year_hint")) is int
        and current.year <= x["edition_year_hint"] <= current.year + 2
    }
    eligible = [
        x for x in municipal["rows"]
        if isinstance(x, dict)
        and x.get("status") == "MUNICIPAL_WEBSITE_RESEARCH_ONLY"
        and x.get("dossier_id") in dossiers
    ]
    eligible.sort(key=lambda x: x["dossier_id"])
    # Two sites per run, bounded even if the private state is poisoned.
    selected = eligible[:limit]
    rows = []
    for row in selected:
        dossier = dossiers[row["dossier_id"]]
        result = {
            "dossier_id": row["dossier_id"],
            "status": "INDEPENDENT_MAIRIE_RECHECK_NOT_PROVEN",
            "pages_checked": 0,
            "named_visible_pages": [],
            "unknown_music_links_review_only": [],
            "site_rederived": False,
            "access_challenge_pages": 0,
            "publication_authorized": False,
        }
        try:
            site = _rederive_municipal_site(
                row, dossier, commune_lookup, delegated_lookup,
                directory_fetch)
            if site is None:
                rows.append(result)
                continue
            result["site_rederived"] = True
            result["municipal_website"] = site
            pending = [site]
            seen = set()
            year = dossier["edition_year_hint"]
            while pending and len(seen) < MAX_PAGES_PER_WEBSITE:
                url = pending.pop(0)
                if url in seen:
                    continue
                seen.add(url)
                try:
                    html = fetch(url)
                    content = _visible(html)
                except (OSError, ValueError, TypeError, UnicodeError, KeyError):
                    continue
                result["pages_checked"] += 1
                if ACCESS_CHALLENGE.search(content):
                    result["access_challenge_pages"] += 1
                    # A page returned by an anti-bot intermediary is NOT a
                    # negative festival observation and must not be parsed as
                    # a genuine institutional announcement.
                    continue
                # Record *unknown* music names from the verified municipal
                # page without opening their URLs or granting authority.
                # A concert discovered by Festivals must not disappear.
                found = {item["detail_url_review_only"] for item in
                         result["unknown_music_links_review_only"]}
                for clue in unknown_municipal_music_links(html, url, site):
                    # The dossier's already-known title must not be counted
                    # as a *new* event. Normalize the visible year suffix.
                    candidate_name = normalized(clue["title_hint"])
                    known_name = normalized(dossier["name_hint"])
                    known_without_year = re.sub(
                        r"\s+20[2-4][0-9]$", "", known_name)
                    candidate_without_year = re.sub(
                        r"\s+20[2-4][0-9]$", "", candidate_name)
                    if (candidate_name not in (known_name, known_without_year)
                            and candidate_without_year not in
                                (known_name, known_without_year)
                            and clue["detail_url_review_only"] not in found
                            and len(result["unknown_music_links_review_only"])
                                < MAX_UNKNOWN_MUSIC_LINKS):
                        result["unknown_music_links_review_only"].append(clue)
                        found.add(clue["detail_url_review_only"])
                if _visible_named_festival(html, dossier["name_hint"]):
                    result["named_visible_pages"].append({
                        "url": url,
                        "content_digest": sha256(content.encode("utf-8"))
                                          .hexdigest()[:20],
                        "edition_year_visible_review_only":
                            str(year) in re.findall(
                                r"(?<![0-9])20[2-4][0-9](?![0-9])", content),
                    })
                if len(seen) < MAX_PAGES_PER_WEBSITE:
                    for link in _candidate_links(
                            html, url, site, dossier["name_hint"], year, today):
                        if (link not in seen and link not in pending
                                and len(pending) < MAX_DISCOVERED_URLS):
                            pending.append(link)
            if result["named_visible_pages"]:
                result["status"] = "NAMED_MUNICIPAL_MENTION_RESEARCH_ONLY"
            elif result["access_challenge_pages"]:
                result["status"] = "MUNICIPAL_ACCESS_CHALLENGE_RESEARCH_UNAVAILABLE"
            elif result["pages_checked"]:
                result["status"] = "NO_NAMED_MUNICIPAL_MENTION"
            else:
                result["status"] = "MUNICIPAL_HTTPS_FETCH_FAILED"
        except (OSError, ValueError, TypeError, UnicodeError, KeyError):
            result["status"] = "INDEPENDENT_MAIRIE_RECHECK_UNAVAILABLE"
        rows.append(result)
    return {
        "schema": SCHEMA, "as_of": today,
        "review_only": True, "safe_to_publish": False,
        "publication_authorized": False, "publications": 0,
        "eligible_municipal_sites": len(eligible),
        "checked_sites": len(rows),
        "rederived_official_municipal_sites": sum(
            1 for x in rows if x["site_rederived"]),
        "named_municipal_mention_count": sum(
            len(x["named_visible_pages"]) for x in rows),
        "unknown_music_links_count": sum(
            len(x["unknown_music_links_review_only"]) for x in rows),
        "unknown_music_links_publications": 0,
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=MAX_WEBSITES)
    args = parser.parse_args()
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    directory = args.intake
    queue = json.loads((directory / "national-festival-discovery-review.json")
                       .read_text(encoding="utf-8"))
    municipal = json.loads((directory / "national-municipal-source-research.json")
                           .read_text(encoding="utf-8"))
    result = scan(queue, municipal, today, limit=args.limit)
    (directory / "national-municipal-pages-review.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print("Municipal first-party page research: eligible="
          + str(result["eligible_municipal_sites"])
          + ", checked=" + str(result["checked_sites"])
          + ", rederived=" + str(result["rederived_official_municipal_sites"])
          + ", named_visible_clues=" + str(result["named_municipal_mention_count"])
          + ", unknown_music_links=" + str(result["unknown_music_links_count"])
          + ", publications=0")


if __name__ == "__main__":
    main()
