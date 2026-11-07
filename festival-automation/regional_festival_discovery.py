"""Conservative, independent festival lead discovery from fixed regional indexes.

This is NOT event qualification: it fetches ONLY hardcoded institutional
indexes, records visible themed detail links, and never fetches a discovered
URL, certifies an organizer, or modifies a public catalogue.
"""
import argparse
from datetime import date, timedelta, datetime
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from regional_visible_article_clues import (
    visible_article_clues, update_private_articles)

from official_watch import get_page, permitted_url
from source_qualification import Anchors, VisibleContent, clean_url, normalized
from regional_source_diagnostics import record_regional_diagnostics
from regional_agenda_pagination import (
    canonical_page_url, discover_pagination, eligible_page_checks,
    prune_page_queue, remember_page_links, MAX_PAGES_DISCOVERED_PER_SCAN, MAX_PAGE)

SCHEMA = "grossesondes.regional-festival-indexes.v1"
# Host AND exact index path must be deliberately reviewed in code before use.
APPROVED = {
    "https://www.phalempin.fr/mes-loisirs/evenements-manifestations/": "Hauts-de-France",
    "https://www.saintes-tourisme.fr/agenda/concerts-et-festivals/": "Nouvelle-Aquitaine",
    "https://sortir.limoges.fr/agenda": "Nouvelle-Aquitaine",
    "https://sortir.limoges.fr/agenda?keys=rock": "Nouvelle-Aquitaine",
    "https://sortir.limoges.fr/agenda?keys=festival": "Nouvelle-Aquitaine",
    "https://www.angers.fr/actualites-sorties/agenda/index.html": "Pays de la Loire",
    "https://agenda.montpellier.fr/": "Occitanie",
    "https://www.tourisme-occitanie.com/agenda/par-theme/festivals/": "Occitanie",
    "https://www.tourisme-seine-et-marne.fr/agenda/": "Île-de-France",
    "https://www.val-de-loire-41.com/agenda/grands-evenements/": "Centre-Val de Loire",
    "https://www.tourismebretagne.com/preparer-mon-sejour/agenda/": "Bretagne",
    "https://www.tourismebretagne.com/preparer-mon-sejour/agenda/festivals-bretagne/": "Bretagne",
    "https://www.visiterlyon.com/sortir/l-agenda/festivals": "Auvergne-Rhône-Alpes",
    "https://www.dignelesbains-tourisme.com/agendas/tout-lagenda/": "Provence-Alpes-Côte d'Azur",
    "https://tourisme-centrecorse.corsica/agenda/": "Corse",
    "https://www.explore-grandest.com/agenda/": "Grand Est",
    "https://www.normandie-tourisme.fr/agenda/": "Normandie",
    "https://www.bourgogne-tourisme.com/sejourner/agenda/": "Bourgogne-Franche-Comté",
}
# Only these already reviewed, public first-party search URLs are allowed.
# Queries from discovered HTML are NEVER added as new seeds.
CURATED_QUERY_VIEWS = frozenset((
    "https://sortir.limoges.fr/agenda?keys=rock",
    "https://sortir.limoges.fr/agenda?keys=festival",
))
MAX_INDEXES = 4
MAX_NEW_PER_INDEX = 6
MAX_PENDING = 100
MAX_AGE = 45
THEMES = re.compile(r"\b(?:metal|metallique|hardcore|punk|hard rock|rock|"
                    r"stoner|doom|sludge|grindcore|deathcore|metalcore|"
                    r"post metal|post rock)\b")
FESTIVAL = re.compile(r"\b(?:fest|festival)\b")
SHRED_FEST = re.compile(r"\bshred fest\b")
EXCLUDED_EXT = re.compile(r"\.(?:pdf|png|jpe?g|gif|webp|svg|zip)(?:$|/)", re.I)

HISTORY_PAGES = ("https://sarogal.github.io/Ondes-Catalogues/"
                 "grossesondes/festival-history.json")
HISTORY_GIT = ("https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
               "main/docs/grossesondes/festival-history.json")
MAX_ARCHIVE_NAMES = 500
ARCHIVE_SIGNAL = "HISTORICAL_NAME_YEAR_ONLY"
THEMATIC_SIGNAL = "THEMATIC_NAME_ONLY"
CONTEXT_SIGNAL = "MUSIC_CATEGORY_CONTEXT_ONLY"
# Only visible, adjacent attribution creates a new PRIVATE discovery hint.
MUSIC_GENRE = (r"(?:heavy metal|death metal|black metal|thrash metal|"
               r"metalcore|hardcore|hard rock|rock alternatif|rock|metal|punk|"
               r"stoner|doom|sludge|grindcore|deathcore|post metal|post rock)")
MUSIC_CATEGORY_CONTEXT = re.compile(
    r"\b(?:genre|genres|categorie|categories|musique|programmation)"
    r" (?:de |du |en )?" + MUSIC_GENRE + r"\b")
FESTIVAL_MUSIC_CONTEXT = re.compile(
    r"\bfestival (?:de |du |des |d )?" + MUSIC_GENRE + r"\b")
NON_MUSIC_TITLE = re.compile(
    r"\b(?:cinema|film|films|bd|bande dessinee|livre|livres|"
    r"litterature|gastronomie|theatre|photo|photographie|sport|"
    r"moto|science|sciences|jeux video)\b")
GENERIC_LINK_TEXT = re.compile(
    r"^(?:en savoir plus|voir plus|decouvrir|details|billetterie|"
    r"programme|programmation|site officiel|lire la suite|"
    r"plus d infos|reserver|acheter des billets)(?: 20[2-4]\d)?$")


def archive_hints(document, today):
    """Old edition identity is a search *hint*, not a 2027 announcement."""
    if (not isinstance(document, dict) or document.get("schema") != 2
            or not isinstance(document.get("knownFestivals"), list)
            or len(document["knownFestivals"]) > MAX_ARCHIVE_NAMES):
        raise ValueError("archives de festivals non conformes")
    hints, slugs = {}, set()
    current = date.fromisoformat(today)
    for row in document["knownFestivals"]:
        if not isinstance(row, dict):
            raise ValueError("entree d'archive invalide")
        slug, name, year = row.get("slug"), row.get("name"), row.get("lastKnownYear")
        if (not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9-]{3,160}", slug)
                or slug in slugs or not isinstance(name, str)):
            raise ValueError("identite archive invalide")
        slugs.add(slug)
        # No guessed last edition: skip undated, uncertain and first-future entries.
        try:
            last_day = date.fromisoformat(row["endDate"])
            first_day = date.fromisoformat(row["startDate"])
        except (KeyError, ValueError, TypeError):
            continue
        if (type(year) is not int or year != last_day.year
                or first_day > last_day or last_day >= current):
            continue
        title = normalized(name)
        if not 7 <= len(title) <= 110 or title in hints:
            continue
        hints[title] = {"slug": slug, "last_known_year": year}
    return hints


def load_verified_archive_hints(today, fetch_json):
    """Read two immutable-target public URLs. Divergence disables archive hints.

    These URLs are fixed in the source; no link from archive data is fetched.
    Independent thematic discovery continues if historical sources are stale.
    """
    try:
        page, git = fetch_json(HISTORY_PAGES), fetch_json(HISTORY_GIT)
        if page != git:
            return {}, "DIVERGENT", 0
        hints = archive_hints(git, today)
        return hints, "CONSISTENT", len(git["knownFestivals"])
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        return {}, "UNAVAILABLE_OR_INVALID", 0



def load_indexes(config):
    if (not isinstance(config, dict) or config.get("schema") != SCHEMA
            or not isinstance(config.get("indexes"), list)
            or not 1 <= len(config["indexes"]) <= len(APPROVED)):
        raise ValueError("index régionaux invalides")
    output, seen = [], set()
    for row in config["indexes"]:
        if not isinstance(row, dict) or set(row) != {"id", "region", "url"}:
            raise ValueError("format source régionale invalide")
        key, region, url = row["id"], row["region"], row["url"]
        if (not isinstance(key, str) or not re.fullmatch(r"[a-z0-9-]{5,60}", key)
                or key in seen or not isinstance(url, str)
                or APPROVED.get(url) != region or not permitted_url(url)
                or urlsplit(url).fragment
                or (bool(urlsplit(url).query) and url not in CURATED_QUERY_VIEWS)
                or (not urlsplit(url).query and clean_url(url) != url)):
            raise ValueError("source régionale non approuvée")
        seen.add(key)
        output.append(row)
    if len({row["url"] for row in output}) != len(output):
        raise ValueError("URL source régionale dupliquée")
    return output


def municipal_event_title(label):
    """Recover a visible event name from a city's exact 'more information' label.

    The prefix is factual navigation text, NOT part of a festival identity.
    No keyword supplied by the page is used as a new search URL or a date.
    Require a colon and a meaningful title so generic buttons cannot qualify.
    """
    if not isinstance(label, str) or len(label) > 300:
        return None
    prefix, separator, tail = label.partition(":")
    if (not separator or normalized(prefix) not in
            ("plus d information sur l evenement",
             "plus d informations sur l evenement")):
        return None
    title = " ".join(tail.split())
    if not (8 <= len(normalized(title)) <= 140 and len(title) <= 160):
        return None
    return title


class RegionalEventAnchors(Anchors):
    """Read an explicitly labelled, *visible* municipal event link.

    Some approved agendas render 'En savoir plus' as anchor text and put the
    exact event identity only in aria-label. The source's normal visible text
    remains primary; only an exact event-label convention may replace an
    otherwise generic anchor. Existing hidden-element filtering is inherited.
    """

    def __init__(self):
        super().__init__()
        self.accessible_event_label = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self.accessible_event_label = None
        super().handle_starttag(tag, attrs)
        if tag.lower() == "a" and self.current is not None:
            attributes = dict(attrs)
            for field in ("aria-label", "title"):
                label = attributes.get(field)
                if municipal_event_title(label):
                    self.accessible_event_label = label
                    break

    def handle_endtag(self, tag):
        if tag.lower() == "a":
            if self.current is not None and self.accessible_event_label:
                visible = normalized("".join(self.current[1]))
                if not visible or GENERIC_LINK_TEXT.fullmatch(visible):
                    self.current[1].clear()
                    self.current[1].append(self.accessible_event_label)
        super().handle_endtag(tag)
        if tag.lower() == "a":
            self.accessible_event_label = None


def candidate_links(html, source, today, historical_hints=None, diagnostics=None):
    if not isinstance(html, str) or len(html) > 650_000:
        raise ValueError("HTML agenda inexploitable")
    if source not in APPROVED:
        raise ValueError("source non approuvée")
    year = date.fromisoformat(today).year
    parser = RegionalEventAnchors()
    parser.feed(html)
    if isinstance(diagnostics, dict):
        # Navigation is not a candidate; this only diagnoses page visibility.
        diagnostics["visible_anchors"] = len(parser.anchors)
    found, seen = [], set()
    historical_hints = historical_hints or {}
    for href, label, prefix in parser.anchors[:650]:
        if not isinstance(href, str) or not isinstance(label, str):
            continue
        event_title = municipal_event_title(label)
        title = event_title if event_title is not None else " ".join(label.split())[:160]
        name = normalized(title)
        if not 8 <= len(name) <= 140:
            continue
        years = {int(x) for x in re.findall(r"(?<!\d)20[2-4]\d(?!\d)", name)}
        if years and (len(years) != 1 or next(iter(years)) not in
                      (year, year + 1, year + 2)):
            continue
        thematic = bool((THEMES.search(name) and FESTIVAL.search(name))
                        or SHRED_FEST.search(name))
        # Local visible category metadata can indicate a festival whose link
        # title omits its genre. No global page text and no hidden script.
        nearby = normalized(prefix[-100:]) if isinstance(prefix, str) else ""
        contextual = bool(
            not thematic and not NON_MUSIC_TITLE.search(name)
            and not GENERIC_LINK_TEXT.fullmatch(name)
            and ((FESTIVAL.search(name)
                  and MUSIC_CATEGORY_CONTEXT.search(nearby))
                 or (FESTIVAL_MUSIC_CONTEXT.search(nearby)
                     and not re.match(
                         r"^(?:concert|spectacle|soiree|show|live)\b", name)))
        )
        # An archive title must have a *new* explicit edition year, and the
        # normalized title must be exactly the historical identity + year.
        # "Motocultor Festival Junior 2027" must not match "Motocultor Festival".
        archive_slug = None
        if years and len(years) == 1:
            edition_year = next(iter(years))
            identity = re.sub(r" (?:edition )?20[2-4]\d$", "", name)
            old = historical_hints.get(identity)
            if (isinstance(old, dict)
                    and type(old.get("last_known_year")) is int
                    and isinstance(old.get("slug"), str)
                    and old["last_known_year"] < edition_year):
                archive_slug = old["slug"]
        if not thematic and not contextual and not archive_slug:
            continue
        url = clean_url(urljoin(source, href))
        if (not url or url == source or url in seen
                or urlsplit(url).hostname != urlsplit(source).hostname
                # A query-only link on the agenda is never an event detail.
                or urlsplit(url).path == urlsplit(source).path
                or EXCLUDED_EXT.search(urlsplit(url).path)):
            continue
        seen.add(url)
        found.append({"candidate_url": url, "title": title,
                      "signal": (THEMATIC_SIGNAL if thematic else
                                 ARCHIVE_SIGNAL if archive_slug else CONTEXT_SIGNAL),
                      "archive_slug": archive_slug})
        if len(found) >= MAX_NEW_PER_INDEX:
            break
    return found


def curated_count_pages(html, source_url, origin, already_queued=None):
    """Next-day-only page hints from visible result totals on two approved views.

    Limoges sometimes renders pagination without regular anchor links. The
    result count may nominate at most two predefined same-host page URLs; it
    never authorizes fetching event details or publishing any edition.
    """
    if (origin not in CURATED_QUERY_VIEWS or source_url != origin
            or not isinstance(html, str) or len(html) > 650_000):
        return []
    parser = VisibleContent()
    parser.feed(html)
    visible = normalized(" ".join(parser.parts))
    match = re.search(
        r"\baffichage des evenements 1 a ([0-9]{1,2}) sur ([0-9]{1,4}) au total\b",
        visible)
    if not match:
        return []
    page_size, total = map(int, match.groups())
    if not (1 <= page_size <= 30 and page_size < total <= 5000):
        return []
    # Continue beyond pages 1-2 across independent daily visits to this
    # *fixed* view. Never use an offset, URI or query supplied by the page.
    known = already_queued if isinstance(already_queued, set) else set()
    result = []
    for number in range(1, min(MAX_PAGE, (total - 1) // page_size) + 1):
        url = origin + "&page=" + str(number)
        if (url not in known
                and canonical_page_url(url, origin, permitted_url) == url):
            result.append(url)
            if len(result) >= MAX_PAGES_DISCOVERED_PER_SCAN:
                break
    return result


def select_indexes(indexes, state, today, limit=MAX_INDEXES):
    if not 1 <= limit <= MAX_INDEXES:
        raise ValueError("limite index incorrecte")
    history = state.get("regional_festival_index_last_checked", {})
    if not isinstance(history, dict):
        raise ValueError("historique régional invalide")
    choices = []
    for row in indexes:
        last = history.get(row["url"], "")
        if last:
            try:
                checked = date.fromisoformat(last)
            except (ValueError, TypeError):
                raise ValueError("date de consultation invalide")
            if checked >= date.fromisoformat(today):
                if checked > date.fromisoformat(today):
                    raise ValueError("historique futur")
                continue
        choices.append((last, row["region"], row["id"], row))
    choices.sort(key=lambda item: (bool(item[0]), item[0], item[1], item[2]))
    chosen, regions = [], set()
    for _, _, _, row in choices:
        if row["region"] in regions:
            continue
        chosen.append(row)
        regions.add(row["region"])
        if len(chosen) == limit:
            return chosen
    for _, _, _, row in choices:
        if row not in chosen and len(chosen) < limit:
            chosen.append(row)
    return chosen


def known_cross_pipeline_urls(report, state):
    """Avoid claiming a prior institutional/source lead as a new discovery."""
    known = set()
    for lead in report.get("source_reference_leads_review_only", []):
        if not isinstance(lead, dict):
            continue
        for url in lead.get("candidate_urls", []):
            if isinstance(url, str) and clean_url(url) == url:
                known.add(url)
    institutional = state.get("institutional_agenda_candidate_pages", {})
    if isinstance(institutional, dict):
        for records in institutional.values():
            if not isinstance(records, list):
                continue
            for record in records:
                if isinstance(record, dict):
                    url = record.get("candidate_url")
                    if isinstance(url, str) and clean_url(url) == url:
                        known.add(url)
    checked = state.get("source_qualification_last_checked", {})
    if isinstance(checked, dict):
        for records in checked.values():
            if isinstance(records, dict):
                for url in records:
                    if isinstance(url, str) and clean_url(url) == url:
                        known.add(url)
    return known


def scan_regional_indexes(report, state, indexes, today, fetch=get_page,
                          limit=MAX_INDEXES, historical_hints=None,
                          archive_status="NOT_CHECKED", archive_total=0):
    if (report.get("schema") != "grossesondes.source-watch-report.v1"
            or report.get("date") != today):
        raise ValueError("rapport régional non conforme")
    checks = state.setdefault("regional_festival_index_last_checked", {})
    pending = state.setdefault("regional_festival_candidates_review_only", {})
    pages = state.setdefault("regional_festival_page_queue_review_only", {})
    if not isinstance(checks, dict) or not isinstance(pending, dict):
        raise ValueError("file privée régionale invalide")
    prune_page_queue(pages, APPROVED, today, permitted_url)
    now = date.fromisoformat(today)
    known_elsewhere = known_cross_pipeline_urls(report, state)
    # Revalidate persisted intake; an attacker-controlled private state is not
    # allowed to introduce a new fetch target or an authorized publication.
    cleaned = {}
    for url, record in list(pending.items())[:MAX_PENDING * 2]:
        if not isinstance(record, dict):
            continue
        origin = record.get("source_index")
        if (url in known_elsewhere or origin not in APPROVED or not isinstance(url, str)
                or clean_url(url) != url
                or urlsplit(url).hostname != urlsplit(origin).hostname
                or record.get("status") != "UNVERIFIED_THEME_LINK"
                or record.get("publication_authorized") is not False):
            continue
        try:
            age = now - date.fromisoformat(record["lastSeen"])
        except (KeyError, ValueError, TypeError):
            continue
        if not timedelta(0) <= age <= timedelta(days=MAX_AGE):
            continue
        # A persisted page may only be a pre-approved root or one of the
        # canonical 1..6 pages previously recorded in the bounded queue.
        # Reject altered state before it can reach national qualification.
        source_page = record.get("source_page", origin)
        if source_page != origin:
            entry = pages.get(source_page)
            if (canonical_page_url(source_page, origin, permitted_url) != source_page
                    or not isinstance(entry, dict)
                    or entry.get("candidate_url") != source_page
                    or entry.get("source_index") != origin
                    or entry.get("publication_authorized") is not False
                    or entry.get("status") != "UNVERIFIED_INDEX_PAGE"):
                continue
        cleaned[url] = dict(record, candidate_url=url, source_page=source_page,
                            publication_authorized=False)
    pending.clear()
    pending.update(dict(list(cleaned.items())[-MAX_PENDING:]))
    outcomes, new, already_known = [], [], set()
    new_article_clues = []
    article_cards_seen = 0
    due_pages = eligible_page_checks(
        pages, APPROVED, today, permitted_url, limit=min(2, max(0, limit - 1)))
    base_budget = limit - len(due_pages)
    base_seeds = (select_indexes(indexes, state, today, base_budget)
                  if base_budget else [])
    checks_to_run = [(seed["url"], seed["url"], seed["region"])
                     for seed in base_seeds]
    checks_to_run.extend((origin, url, APPROVED[origin])
                         for origin, url in due_pages)
    page_attempted = page_checked = page_new = 0
    for origin, source_url, region in checks_to_run:
        outcome = {"region": region, "index_url": origin,
                   "checked_url": source_url,
                   "page_kind": ("ROOT" if source_url == origin else "PAGINATION"),
                   "status": "INACCESSIBLE", "publication_authorized": False}
        if source_url != origin:
            page_attempted += 1
        try:
            html = fetch(source_url)
            page_diagnostics = {}
            links = candidate_links(
                html, origin, today, historical_hints, page_diagnostics)
            # Visible <article> cards without event links are not fetch targets.
            # Store a bounded identity clue only, never a page URL or date proof.
            article_clues, cards_seen = visible_article_clues(
                html, today, historical_hints)
            added_articles, _ = update_private_articles(
                state, origin, region, article_clues, today, APPROVED)
            article_cards_seen += cards_seen
            new_article_clues.extend(added_articles)
            discovered_pages = discover_pagination(
                html, source_url, origin, Anchors, permitted_url)
            # Known navigation links do not consume the budget for NEW pages.
            # Still refresh their lastSeen without adding more than two fresh
            # page targets during this scan.
            new_page_links = [url for url in discovered_pages if url not in pages]
            for page_url in curated_count_pages(
                    html, source_url, origin,
                    set(pages) | set(discovered_pages)):
                if (page_url not in new_page_links
                        and len(new_page_links) < MAX_PAGES_DISCOVERED_PER_SCAN):
                    new_page_links.append(page_url)
            page_new += remember_page_links(
                pages, discovered_pages + new_page_links,
                origin, today, permitted_url)
            outcome["status"] = "SCANNED"
            outcome["thematic_links"] = len(links)
            outcome["visible_anchors"] = page_diagnostics["visible_anchors"]
            outcome["page_diagnostic"] = (
                "CANDIDATE_LINKS_REVIEW_ONLY" if links
                else "VISIBLE_LINKS_NO_CANDIDATE" if outcome["visible_anchors"]
                else "NO_VISIBLE_LINKS")
            # A script alone is not proof of client rendering or a festival.
            outcome["script_backed_linkless_hint"] = bool(
                not outcome["visible_anchors"]
                and re.search(r"<script\b", html, re.I))
            for match in links:
                url = match["candidate_url"]
                if url in known_elsewhere:
                    already_known.add(url)
                    continue
                if url not in pending and len(pending) >= MAX_PENDING:
                    continue
                old = pending.get(url)
                record = {
                    "candidate_url": url, "title": match["title"],
                    "source_index": origin, "region": region,
                    # Preserve where this link was actually seen. An index
                    # root cannot stand in for page=2/3 during next-day review.
                    "source_page": source_url,
                    "firstSeen": old["firstSeen"] if old else today,
                    "lastSeen": today, "status": "UNVERIFIED_THEME_LINK",
                    "discovery_signal": match["signal"],
                    "historical_name_slug": match["archive_slug"],
                    "date_verified": False,
                    "publication_authorized": False,
                }
                pending[url] = record
                if old is None:
                    new.append(dict(record, new_this_pass=True))
        except (OSError, ValueError, UnicodeError):
            pass
        if source_url == origin:
            checks[origin] = today
        else:
            # A failed fetch is an attempt, not a successful check. Keep the
            # same-day throttle while allowing next-day retries.
            pages[source_url]["lastAttempted"] = today
            if outcome["status"] == "SCANNED":
                pages[source_url]["lastChecked"] = today
                page_checked += 1
        outcomes.append(outcome)
    # Configuration is not proof of successful network coverage.
    report["regional_festival_configured_sources_review_only"] = len(indexes)
    report["regional_festival_curated_search_views_review_only"] = sum(
        bool(urlsplit(seed["url"]).query) for seed in indexes)
    report["regional_festival_configured_regions_review_only"] = len(
        {seed["region"] for seed in indexes})
    report["regional_festival_regions_attempted_review_only"] = len(
        {seed["region"] for seed in indexes if seed["url"] in checks})
    report["regional_festival_regions_this_pass_review_only"] = len(
        {row["region"] for row in outcomes})
    report["regional_festival_no_visible_links_review_only"] = sum(
        row.get("page_diagnostic") == "NO_VISIBLE_LINKS" for row in outcomes)
    report["regional_festival_visible_unmatched_review_only"] = sum(
        row.get("page_diagnostic") == "VISIBLE_LINKS_NO_CANDIDATE"
        for row in outcomes)
    report["regional_festival_possible_dynamic_review_only"] = sum(
        row.get("script_backed_linkless_hint") is True for row in outcomes)
    report["regional_festival_scanned_this_pass_review_only"] = sum(
        row["status"] == "SCANNED" for row in outcomes)
    report["regional_festival_inaccessible_this_pass_review_only"] = sum(
        row["status"] == "INACCESSIBLE" for row in outcomes)
    report["regional_festival_visible_articles_review_only"] = article_cards_seen
    report["regional_festival_article_clues_new_review_only"] = len(new_article_clues)
    report["regional_festival_article_clues_pending_review_only"] = len(
        state.get("regional_festival_article_clues_review_only", {}))
    report["regional_festival_article_new_review_only"] = new_article_clues[:12]
    report["regional_festival_archive_status_review_only"] = archive_status
    report["regional_festival_archive_reference_count_review_only"] = archive_total
    report["regional_festival_archive_hints_count_review_only"] = len(historical_hints or {})
    report["regional_festival_archive_links_new_review_only"] = sum(
        row.get("discovery_signal") == ARCHIVE_SIGNAL for row in new)
    report["regional_festival_contextual_links_new_review_only"] = sum(
        row.get("discovery_signal") == CONTEXT_SIGNAL for row in new)
    report["regional_festival_pagination_attempted_review_only"] = page_attempted
    report["regional_festival_pagination_checked_review_only"] = page_checked
    report["regional_festival_pagination_inaccessible_review_only"] = (
        page_attempted - page_checked)
    report["regional_festival_pagination_discovered_review_only"] = page_new
    report["regional_festival_pagination_pending_review_only"] = len(pages)
    report["regional_festival_indexes_review_only"] = outcomes
    report["regional_festival_discoveries_review_only"] = new
    report["regional_festival_new_links_review_only"] = len(new)
    report["regional_festival_existing_links_skipped_review_only"] = len(already_known)
    report["regional_festival_pending_links_review_only"] = len(pending)
    report["regional_festival_detail_pages_checked_review_only"] = 0
    report["regional_festival_publications"] = 0
    record_regional_diagnostics(state, outcomes, APPROVED, today, permitted_url)
    return new


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=MAX_INDEXES)
    args = parser.parse_args()
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    config = json.loads(Path(__file__).with_name("regional_festival_indexes.json")
                        .read_text(encoding="utf-8"))
    seeds = load_indexes(config)
    state_path = args.intake / "source-watch-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("schema") != "grossesondes.source-watch.v1":
        raise ValueError("schéma d'état incorrect")
    report = json.loads(args.report.read_text(encoding="utf-8"))
    # Two fixed, independently served archive documents must agree before
    # historical *names* can be used; their URLs never enter the fetch queue.
    from official_watch import get_json
    hints, archive_status, archive_total = load_verified_archive_hints(
        today, get_json)
    new = scan_regional_indexes(
        report, state, seeds, today, limit=args.limit,
        historical_hints=hints, archive_status=archive_status,
        archive_total=archive_total)
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    print("DECOUVERTE_REGIONALE:", json.dumps({
        "configured_sources": report["regional_festival_configured_sources_review_only"],
        "curated_search_views": report["regional_festival_curated_search_views_review_only"],
        "configured_regions": report["regional_festival_configured_regions_review_only"],
        "regions_attempted_today": report["regional_festival_regions_attempted_review_only"],
        "regions_attempted_pass": report["regional_festival_regions_this_pass_review_only"],
        "index_checks": len(report["regional_festival_indexes_review_only"]),
        "pagination_checks": report["regional_festival_pagination_checked_review_only"],
        "new_index_pages": report["regional_festival_pagination_discovered_review_only"],
        "pending_index_pages": report["regional_festival_pagination_pending_review_only"],
        "scanned": report["regional_festival_scanned_this_pass_review_only"],
        "inaccessible": report["regional_festival_inaccessible_this_pass_review_only"],
        "linkless": report["regional_festival_no_visible_links_review_only"],
        "visible_articles": report["regional_festival_visible_articles_review_only"],
        "article_clues_new": report["regional_festival_article_clues_new_review_only"],
        "article_clues_pending": report["regional_festival_article_clues_pending_review_only"],
        "unmatched_visible": report["regional_festival_visible_unmatched_review_only"],
        "script_backed_linkless": report["regional_festival_possible_dynamic_review_only"],
        "archive_status": archive_status,
        "historical_hints": len(hints),
        "new_historical_link_hints": report["regional_festival_archive_links_new_review_only"],
        "new_contextual_links": report["regional_festival_contextual_links_new_review_only"],
        "new_unverified_urls": len(new),
        "pending": len(state["regional_festival_candidates_review_only"]),
        "verified_events": 0, "published": 0,
    }))


if __name__ == "__main__":
    main()
