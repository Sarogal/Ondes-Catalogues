#!/usr/bin/env python3
"""Veille nationale des concerts. Ne publie jamais; écrit seulement des rapports locaux."""
from __future__ import annotations

import argparse
import datetime as dt
import html.parser
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import feeds
import triage
import venue_adapters
import club_pages
import glazart_adapter
import trabendo_adapter
import maroquinerie_adapter
import boule_noire_adapter
import regional_clubs
import molotov_adapter
import ferrailleur_adapter
import malterie_adapter
import joker_adapter
import partner_calendars
import ticketmaster_venue_probes
import echo_system_adapter
import rocher_palmer_adapter
import cave_poetes_adapter
import carene_adapter
import hydrophone_adapter
import atabal_adapter
import brin_de_zinc_adapter
import bikini_adapter
import rockstore_adapter
import blacklab_adapter
import laiterie_adapter
import astrolabe_adapter
import le106_adapter
import antipode_adapter
import bonjour_minuit_adapter
import chatodo_adapter
import letempsmachine_adapter
import undercovered_official_adapter
import bateau_ivre_adapter
import echonova_adapter
import tetris_adapter
import cargo_adapter
import bbc_adapter
import urllib.robotparser
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
CATALOG = "https://sarogal.github.io/Ondes-Catalogues/grossesondes/concerts.json"
FESTIVALS = "https://sarogal.github.io/Ondes-Catalogues/grossesondes/festivals.json"
# GitHub raw is the authoritative repository copy when Pages is temporarily unavailable.
CATALOG_RAW = "https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/main/docs/grossesondes/concerts.json"
FESTIVALS_RAW = "https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/main/docs/grossesondes/festivals.json"
TICKETMASTER = "https://app.ticketmaster.com/discovery/v2/events.json"
AGENT = "GrossesOndesConcertWatch/0.1 (discovery only)"
CATEGORIES = ("Metal", "Hard Rock", "Punk", "Hardcore")
GENRE = re.compile(r"\b(metal|hardcore|punk|grind|deathcore|death metal|black metal|doom|stoner|sludge|thrash|heavy metal|post.metal|hard rock|metalcore)\b", re.I)
EVENT_URL = re.compile(r"(concert|event|evenement|spectacle|agenda|programmation|show|billet)", re.I)


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    value = value.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", value)


def today_fr():
    return dt.datetime.now(ZoneInfo("Europe/Paris")).date()


def download(url, timeout=12, cap=3_000_000):
    req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "application/json,text/html,application/ld+json,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read(cap + 1)
        if len(body) > cap:
            raise ValueError("Document trop volumineux")
        return body.decode(response.headers.get_content_charset() or "utf-8", errors="replace"), response.geturl()


def json_url(url):
    """Cloud Pages first; repository-main raw as failover, never stale Infomaniak.

    A bad or unreachable source never counts as evidence; both failures abort
    discovery rather than comparing against an outdated local snapshot.
    """
    fallbacks = {CATALOG: CATALOG_RAW, FESTIVALS: FESTIVALS_RAW}
    last_error = None
    for source in (url, fallbacks.get(url)):
        if not source:
            continue
        try:
            content, _ = download(source, timeout=20, cap=8_000_000)
            data = json.loads(content)
            if not isinstance(data, (dict, list)):
                raise ValueError("Unexpected cloud document type")
            return data
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            last_error = exc
    raise RuntimeError("Neither GitHub Pages nor GitHub main catalogue is readable") from last_error


def artist_name(event, artists):
    ids = event.get("artistIds") or []
    if ids:
        return artists.get(ids[0], {}).get("name") or event.get("title", "")
    return event.get("title", "")


def make_known_keys(catalogue):
    venues = {str(x["id"]): x for x in catalogue.get("venues", [])}
    artists = {str(x["id"]): x for x in catalogue.get("artists", [])}
    keys = set()
    for event in catalogue.get("events", []):
        venue = venues.get(str(event.get("venueId")), {})
        if event.get("date") and venue.get("city"):
            keys.add((event["date"], norm(venue["city"]), norm(artist_name(event, artists))))
        # Identical first-party detail URLs are a strong published-record
        # match, even when an agenda title omits supporting artists.
        source_url=event.get("officialUrl")
        if isinstance(source_url,str) and source_url.startswith("https://"):
            keys.add(("officialUrl",source_url))
    return keys


def mark_match(event, known):
    artist = event.get("leadArtist") or event.get("name") or ""
    match = (event.get("date"), norm(event.get("city")), norm(artist))
    url=event.get("sourceUrl")
    event["possibleExistingConcert"] = (match in known or
        (isinstance(url,str) and ("officialUrl",url) in known))
    event["publicationAllowed"] = False
    event["reviewRequired"] = True
    return event


def reject_listing(title):
    """Bloque les annulations, réunions et festivals clairement nommés."""
    title = __import__("html").unescape(str(title or ""))
    title = unicodedata.normalize("NFKD", title.casefold()).encode("ascii", "ignore").decode()
    return bool(re.search(r"\b(annule|annulee|annulation|cancelled|canceled|reporte|reportee|postponed|festival|fest|reunion|atelier|conference|formation|cours)\b", title))


def iso_day(value):
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value[:10]).isoformat()
    except (ValueError, TypeError):
        return None


def event_status_cancelled(raw):
    status = ((raw.get("dates") or {}).get("status") or {}).get("code", "")
    status = str(status or raw.get("eventStatus") or "").casefold()
    return any(x in status for x in ("cancel", "postpon", "resched"))


def ticketmaster_candidate(raw, known, day):
    if event_status_cancelled(raw):
        return None
    starts = (raw.get("dates") or {}).get("start") or {}
    date = iso_day(starts.get("localDate"))
    venues = ((raw.get("_embedded") or {}).get("venues") or [])
    venue = venues[0] if venues else {}
    city = (venue.get("city") or {}).get("name", "")
    country = (venue.get("country") or {}).get("countryCode", "")
    attractions = ((raw.get("_embedded") or {}).get("attractions") or [])
    artist = (attractions[0].get("name") if attractions else None) or raw.get("name")
    name = raw.get("name") or artist
    if reject_listing(name):
        return None
    url = raw.get("url", "")
    if not date or date < day or country != "FR" or not city or not venue.get("name") or not artist:
        return None
    if not url.startswith("https://") or not raw.get("id"):
        return None
    labels = []
    for cat in raw.get("classifications") or []:
        for field in ("segment", "genre", "subGenre"):
            label = (cat.get(field) or {}).get("name")
            if label:
                labels.append(label)
    result = {
        "candidateId": "ticketmaster:" + str(raw["id"]),
        "source": "ticketmaster_api", "sourceUrl": url,
        "date": date, "localTime": starts.get("localTime"),
        "name": name, "leadArtist": artist, "venue": venue["name"],
        "city": city, "classification": sorted(set(labels)),
        "genreToConfirm": True, "sourceConfidence": "billetterie; à confirmer auprès du lieu",
    }
    return mark_match(result, known)


class EventHtml(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ld = []
        self.links = []
        self._script = False
        self._chunks = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("type", "").split(";")[0].strip().casefold() == "application/ld+json":
            self._script = True
            self._chunks = []
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])

    def handle_data(self, data):
        if self._script:
            self._chunks.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._script:
            self.ld.append("".join(self._chunks))
            self._script = False


def flatten_ld(node):
    if isinstance(node, list):
        for item in node:
            yield from flatten_ld(item)
    elif isinstance(node, dict):
        types = node.get("@type", [])
        if isinstance(types, str):
            types = [types]
        if any(str(t).rsplit("/", 1)[-1] in ("Event", "MusicEvent") for t in types):
            yield node
        for name in ("@graph", "itemListElement"):
            yield from flatten_ld(node.get(name, []))
        if "item" in node:
            yield from flatten_ld(node["item"])


def read_ld(html_text):
    parser = EventHtml()
    parser.feed(html_text)
    for script in parser.ld:
        try:
            yield from flatten_ld(json.loads(script))
        except (ValueError, TypeError, json.JSONDecodeError):
            continue


def safe_name(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " + ".join(filter(None, (safe_name(x) for x in value)))
    if isinstance(value, dict):
        return str(value.get("name", ""))
    return ""


def venue_candidate(raw, source, page_url, known, day):
    date = iso_day(raw.get("startDate"))
    status = safe_name(raw.get("eventStatus")).casefold()
    if not date or date < day or ("cancel" in status or "postpon" in status):
        return None
    name = __import__("html").unescape(safe_name(raw.get("name")))
    if reject_listing(name):
        return None
    location = raw.get("location") or {}
    if isinstance(location, list):
        location = location[0] if location else {}
    if isinstance(location, str):
        location = {"name": location}
    address = location.get("address") or {}
    if isinstance(address, str):
        address = {}
    venue = safe_name(location) or source["name"]
    city = address.get("addressLocality") or source["city"]
    # Un agenda peut inclure des concerts d'autres salles : ne jamais
    # attribuer un événement extérieur à la salle en cours de vérification.
    source_venue = norm(source["name"])
    event_venue = norm(venue)
    source_city = norm(source["city"])
    event_city = norm(city)
    if (event_venue and source_venue and
            source_venue not in event_venue and
            event_venue not in source_venue):
        return None
    if source_city and event_city and source_city != event_city:
        return None
    artist = safe_name(raw.get("performer")) or name
    keywords = " ".join(map(str, [raw.get("genre", ""), raw.get("keywords", ""), raw.get("description", "")]))
    if not name or not venue or not city:
        return None
    # Le titre peut être imprécis; aucune déduction automatique de la pertinence métal.
    relevant = bool(GENRE.search(unicodedata.normalize("NFKD", keywords).encode("ascii", "ignore").decode()))
    ref_url = raw.get("url") if isinstance(raw.get("url"), str) else ""
    if not ref_url.startswith("https://"):
        ref_url = page_url
    record = {
        "candidateId": "venue:" + norm(source["name"]) + ":" + date + ":" + norm(name),
        "source": "agenda_officiel_structuré", "sourceUrl": ref_url,
        "sourcePage": page_url, "date": date, "name": name, "leadArtist": artist,
        "venue": venue, "city": city, "department": source["department"],
        "genreToConfirm": not relevant,
        "sourceConfidence": "agenda de salle; programmation et pertinence à contrôler",
    }
    return mark_match(record, known)


def robots_allow(url, cache):
    p = urllib.parse.urlsplit(url)
    root = p.scheme + "://" + p.netloc
    if root not in cache:
        robot_url = root + "/robots.txt"
        try:
            text, _ = download(robot_url, timeout=7, cap=150_000)
        except urllib.error.HTTPError as error:
            if error.code != 404:
                cache[root] = None
            else:
                cache[root] = True
        except Exception:
            cache[root] = None
        else:
            parser = urllib.robotparser.RobotFileParser()
            parser.parse(text.splitlines())
            cache[root] = parser
    policy = cache[root]
    return policy is True or (policy is not None and policy.can_fetch(AGENT, url))


def same_host(link, root):
    a, b = urllib.parse.urlsplit(link), urllib.parse.urlsplit(root)
    return a.scheme == "https" and a.netloc.lower().removeprefix("www.") == b.netloc.lower().removeprefix("www.")


def record_detail_hold(diag, exc, official_url):
    """Keep bounded private diagnostics for rejected official detail pages.

    The rejection does NOT become a candidate or an approval.
    """
    diag["heldOrIrrelevant"] += 1
    reason = (str(exc).strip().splitlines() or [type(exc).__name__])[0][:140]
    reasons = diag.setdefault("heldReasons", {})
    if len(reasons) >= 20 and reason not in reasons:
        reason = "Other rejection"
    reasons[reason] = reasons.get(reason, 0) + 1
    samples = diag.setdefault("heldReviewSamples", [])
    if len(samples) < 6:
        samples.append({"url": official_url, "reason": reason})


def scan_slot_for_hour(hour):
    """Three deterministic local-time slots without altering source quotas."""
    if not isinstance(hour, int) or not 0 <= hour <= 23:
        raise ValueError("Invalid local scan hour")
    return 0 if hour < 12 else 1 if hour < 18 else 2


def scan_venues(sources, known, day, report, max_p2=7, scan_slot=0):
    if scan_slot not in (0, 1, 2):
        raise ValueError("Only the three bounded local scan windows are allowed")
    sites = sources.get("venues") or []
    p1 = [s for s in sites if s["priority"] == "P1"]
    p2 = [s for s in sites if s["priority"] == "P2"]
    # Same number of P2 fetches per run; three daily runs discover distinct
    # venue cohorts instead of inspecting the same sites each time.
    start = ((day.toordinal() + scan_slot) * max_p2) % len(p2) if p2 else 0
    chosen = p1 + [p2[(start + i) % len(p2)] for i in range(min(max_p2, len(p2)))]
    collected = {}
    robot_cache = {}
    for source in chosen:
        base = source["url"]
        info = {"venue": source["name"], "url": base}
        try:
            if not robots_allow(base, robot_cache):
                raise RuntimeError("robots.txt indisponible ou accès non autorisé")
            first, final = download(base)
            if not same_host(final, base):
                raise RuntimeError("redirection hors domaine, examen nécessaire")
            parser = EventHtml()
            parser.feed(first)
            pages = [(first, final)]
            # Navigation limitée aux pages d'événements du même site, sans scrapping massif.
            links = []
            for href in parser.links:
                next_url = urllib.parse.urljoin(final, href).split("#")[0]
                if same_host(next_url, base) and EVENT_URL.search(urllib.parse.urlsplit(next_url).path):
                    if next_url not in links and next_url != final:
                        links.append(next_url)
            for link in ([] if source.get("adapter") in (
                    "tetris_official_detail_review", "cargo_official_detail_review",
                    "bbc_official_detail_review",
                    "antipode_official_detail_review",
                    "bonjour_minuit_official_detail_review",
                    "grillen_official_detail_review",
                    "limoges_municipal_card_detail_review",
                    "bateau_ivre_official_detail_review",
                    "laiterie_official_detail_review",
                    "echonova_official_detail_review")
                         else links[:3]):
                if robots_allow(link, robot_cache):
                    try:
                        text, url = download(link)
                        if same_host(url, base):
                            pages.append((text, url))
                    except Exception:
                        pass
            count = 0
            if source.get("adapter") == "echonova_official_detail_review":
                # Exact first-party programme and at most six named details.
                # Rock/metal/punk must be confirmed on each individual page;
                # electronic "hardcore" is never sufficient.
                adapter = echonova_adapter
                urls = adapter.agenda_links(first, final)
                chosen_urls = adapter.select_urls(
                    urls, known, day.isoformat(),
                    source.get("maxDetailPagesPerRun", 6))
                diag = {
                    "method": "bounded_echonova_official_detail_review",
                    "agendaPagesRead": 1, "eventLinksFound": len(urls),
                    "detailPagesRead": 0, "detailErrors": 0,
                    "datedGenreLeads": 0, "alreadyLikelyPublished": 0,
                    "heldOrIrrelevant": 0, "publicationAllowed": False,
                }
                for detail_url in chosen_urls:
                    try:
                        if not robots_allow(detail_url, robot_cache):
                            diag["detailErrors"] += 1
                            continue
                        detail_html, actual = download(
                            detail_url, timeout=12, cap=1_000_000)
                        if actual != detail_url:
                            diag["detailErrors"] += 1
                            continue
                        diag["detailPagesRead"] += 1
                        try:
                            record = adapter.candidate(
                                detail_html, actual, source, day.isoformat())
                        except (ValueError, TypeError, KeyError) as exc:
                            record_detail_hold(diag, exc, detail_url)
                            continue
                        mark_match(record, known)
                        diag["alreadyLikelyPublished"] += int(
                            record["possibleExistingConcert"])
                        collected[record["candidateId"]] = record
                        diag["datedGenreLeads"] += 1
                        count += 1
                    except Exception:
                        diag["detailErrors"] += 1
                info["adapterDiagnostic"] = diag
            if source.get("adapter") == "bateau_ivre_official_detail_review":
                # WordPress event links contain an accented segment and are
                # therefore not picked up by the old ASCII generic scanner.
                # Two separately pinned sources: current-month programme and
                # 2027 index; no historical/paginated crawls, no publication.
                adapter = bateau_ivre_adapter
                urls = adapter.archive_links(first, final)
                chosen_urls = adapter.select_urls(
                    urls, known, day.isoformat(),
                    source.get("maxDetailPagesPerRun", 6),
                    scan_slot=scan_slot)
                diag = {
                    "method": ("pinned_current_programme_to_detail"
                               if source["url"] == adapter.CURRENT
                               else "single_2027_annual_official_archive_to_detail"),
                    "agendaPagesRead": 1, "eventLinksFound": len(urls),
                    "detailPagesRead": 0, "detailErrors": 0,
                    "datedGenreLeads": 0, "alreadyLikelyPublished": 0,
                    "heldOrIrrelevant": 0, "publicationAllowed": False,
                }
                for detail_url in chosen_urls:
                    try:
                        if not robots_allow(detail_url, robot_cache):
                            diag["detailErrors"] += 1
                            continue
                        html_detail, actual = download(
                            detail_url, timeout=12, cap=1_000_000)
                        if actual != detail_url:
                            diag["detailErrors"] += 1
                            continue
                        diag["detailPagesRead"] += 1
                        try:
                            item = adapter.candidate(
                                html_detail, actual, source, day.isoformat())
                        except (ValueError, TypeError, KeyError) as exc:
                            record_detail_hold(diag, exc, detail_url)
                            continue
                        mark_match(item, known)
                        diag["alreadyLikelyPublished"] += int(
                            item["possibleExistingConcert"])
                        collected[item["candidateId"]] = item
                        diag["datedGenreLeads"] += 1
                        count += 1
                    except Exception:
                        diag["detailErrors"] += 1
                info["adapterDiagnostic"] = diag
            if source.get("adapter") == "grillen_official_detail_review":
                # Three first-party agenda pages maximum, nine named details.
                # A missing 2026/2027 year is a *held* lead, never guessed.
                adapter = undercovered_official_adapter
                all_urls = adapter.grillen_links(first, final)
                agenda_pages, agenda_errors = 1, 0
                for page_no in (1, 2):
                    page_url = adapter.GRILLEN_AGENDA + "&page=" + str(page_no)
                    try:
                        if not robots_allow(page_url, robot_cache):
                            agenda_errors += 1
                            continue
                        page_body, actual = download(page_url, timeout=11, cap=850_000)
                        if actual != page_url:
                            agenda_errors += 1
                            continue
                        all_urls += adapter.grillen_links(page_body, actual)
                        agenda_pages += 1
                    except Exception:
                        agenda_errors += 1
                selected = adapter.select_urls(
                    all_urls, known, day.isoformat(),
                    source.get("maxDetailPagesPerRun", 8))
                diag = {
                    "method": "grillen_bounded_first_party_detail_year_check",
                    "agendaPagesRead": agenda_pages, "agendaErrors": agenda_errors,
                    "eventLinksFound": len(set(all_urls)), "detailPagesRead": 0,
                    "detailErrors": 0, "heldOrIrrelevant": 0,
                    "datedGenreLeads": 0, "alreadyLikelyPublished": 0,
                    "publicationAllowed": False,
                }
                for detail_url in selected:
                    try:
                        if not robots_allow(detail_url, robot_cache):
                            diag["detailErrors"] += 1
                            continue
                        page, actual = download(detail_url, timeout=11, cap=850_000)
                        if actual != detail_url:
                            diag["detailErrors"] += 1
                            continue
                        diag["detailPagesRead"] += 1
                        try:
                            record = adapter.grillen_detail(
                                page, actual, source, day.isoformat())
                        except (ValueError, KeyError, TypeError) as exc:
                            record_detail_hold(diag, exc, detail_url)
                            continue
                        mark_match(record, known)
                        diag["alreadyLikelyPublished"] += int(
                            record["possibleExistingConcert"])
                        collected[record["candidateId"]] = record
                        diag["datedGenreLeads"] += 1
                        count += 1
                    except Exception:
                        diag["detailErrors"] += 1
                info["adapterDiagnostic"] = diag
            if source.get("adapter") == "limoges_municipal_card_detail_review":
                adapter = undercovered_official_adapter
                cards = adapter.limoges_cards(first, final, day.isoformat())
                # De-dup by exact first-party detail URL; a municipal agenda
                # may contain several venues, never relabel their events.
                card_by_url = {c["url"]: c for c in cards}
                urls = adapter.select_urls(
                    list(card_by_url), known, day.isoformat(),
                    source.get("maxDetailPagesPerRun", 5))
                diag = {
                    "method": "municipal_card_full_date_and_named_detail",
                    "agendaPagesRead": 1, "agendaErrors": 0,
                    "eventLinksFound": len(card_by_url),
                    "detailPagesRead": 0, "detailErrors": 0,
                    "heldOrIrrelevant": 0, "datedGenreLeads": 0,
                    "alreadyLikelyPublished": 0, "publicationAllowed": False,
                }
                for detail_url in urls:
                    try:
                        if not robots_allow(detail_url, robot_cache):
                            diag["detailErrors"] += 1
                            continue
                        page, actual = download(detail_url, timeout=11, cap=800_000)
                        if actual != detail_url:
                            diag["detailErrors"] += 1
                            continue
                        diag["detailPagesRead"] += 1
                        try:
                            record = adapter.limoges_detail(
                                page, card_by_url[detail_url],
                                source, day.isoformat())
                        except (ValueError, KeyError, TypeError) as exc:
                            record_detail_hold(diag, exc, detail_url)
                            continue
                        mark_match(record, known)
                        diag["alreadyLikelyPublished"] += int(
                            record["possibleExistingConcert"])
                        collected[record["candidateId"]] = record
                        diag["datedGenreLeads"] += 1
                        count += 1
                    except Exception:
                        diag["detailErrors"] += 1
                info["adapterDiagnostic"] = diag
            if source.get("adapter") == "letempsmachine_official_detail_review":
                # The agenda is only a URL index. A detail must establish its
                # own full year, venue and genre; never infer musical start
                # from ticket times (the venue explicitly says 'doors').
                urls = letempsmachine_adapter.agenda_links(first, final)
                pages_checked, page_errors = 1, 0
                extra_url = letempsmachine_adapter.AGENDA + "&page=1"
                if (source.get("maxAgendaPagesPerRun", 2) >= 2
                        and letempsmachine_adapter.valid_agenda(extra_url)):
                    try:
                        if robots_allow(extra_url, robot_cache):
                            extra_html, actual = download(
                                extra_url, timeout=11, cap=1_400_000)
                            if actual == extra_url:
                                urls += letempsmachine_adapter.agenda_links(
                                    extra_html, actual)
                                pages_checked += 1
                            else:
                                page_errors += 1
                        else:
                            page_errors += 1
                    except Exception:
                        page_errors += 1
                selected = letempsmachine_adapter.choose(
                    urls, known, day.isoformat(),
                    limit=source.get("maxDetailPagesPerRun", 8))
                diag = {
                    "method": "bounded_letempsmachine_official_individual_pages",
                    "agendaPagesRead": pages_checked, "agendaErrors": page_errors,
                    "eventLinksFound": len(set(urls)),
                    "detailPagesRead": 0, "detailErrors": 0,
                    "datedGenreLeads": 0, "alreadyLikelyPublished": 0,
                    "heldOrIrrelevant": 0, "publicationAllowed": False,
                }
                cached = {page_url: text for text, page_url in pages}
                for url in selected:
                    try:
                        if not robots_allow(url, robot_cache):
                            diag["detailErrors"] += 1
                            continue
                        if url in cached:
                            page, actual = cached[url], url
                        else:
                            page, actual = download(url, timeout=11, cap=1_000_000)
                        if actual != url:
                            diag["detailErrors"] += 1
                            continue
                        diag["detailPagesRead"] += 1
                        try:
                            record = letempsmachine_adapter.candidate(
                                page, url, source, day.isoformat())
                        except (ValueError, TypeError, KeyError):
                            diag["heldOrIrrelevant"] += 1
                            continue
                        mark_match(record, known)
                        diag["alreadyLikelyPublished"] += int(
                            record["possibleExistingConcert"])
                        collected[record["candidateId"]] = record
                        diag["datedGenreLeads"] += 1
                        count += 1
                    except Exception:
                        diag["detailErrors"] += 1
                info["adapterDiagnostic"] = diag
            if source.get("adapter") == "tetris_official_detail_review":
                # Le Tetris frequently omits the year: NEVER derive it from
                # current month, programme order or a previous publication.
                # Only first-party detail evidence can produce a dated lead.
                urls = tetris_adapter.agenda_links(first, final)
                selected = tetris_adapter.choose(
                    urls, known, day.isoformat(),
                    limit=source.get("maxDetailPagesPerRun", 8))
                diag = {
                    "method": "bounded_tetris_first_party_detail_review",
                    "agendaPagesRead": 1, "eventLinksFound": len(urls),
                    "detailPagesRead": 0, "detailErrors": 0,
                    "datedGenreLeads": 0, "undatedYearReviewLeads": 0,
                    "heldOrIrrelevant": 0, "alreadyLikelyPublished": 0,
                    "publicationAllowed": False,
                }
                for detail_url in selected:
                    try:
                        if not robots_allow(detail_url, robot_cache):
                            diag["detailErrors"] += 1
                            continue
                        page, actual = download(
                            detail_url, timeout=11, cap=900_000)
                        if actual != detail_url:
                            diag["detailErrors"] += 1
                            continue
                        diag["detailPagesRead"] += 1
                        try:
                            record = tetris_adapter.candidate(
                                page, detail_url, source, day.isoformat())
                        except (ValueError, TypeError, KeyError):
                            diag["heldOrIrrelevant"] += 1
                            continue
                        mark_match(record, known)
                        collected[record["candidateId"]] = record
                        diag["alreadyLikelyPublished"] += int(
                            record["possibleExistingConcert"])
                        if record["date"]:
                            diag["datedGenreLeads"] += 1
                        else:
                            diag["undatedYearReviewLeads"] += 1
                        count += 1
                    except Exception:
                        diag["detailErrors"] += 1
                info["adapterDiagnostic"] = diag
            if source.get("adapter") == "cargo_official_detail_review":
                # The broad Concert menu mixes genres and venues. Only
                # individual official on-site details with a full ticket date
                # and distinct door/concert-start labels can produce leads.
                urls = cargo_adapter.agenda_links(first, final)
                selected = cargo_adapter.selected_urls(
                    urls, known, day.isoformat(),
                    limit=source.get("maxDetailPagesPerRun", 8))
                diag = {
                    "method": "bounded_cargo_ticket_facts_detail_review",
                    "eventLinksFound": len(urls), "agendaPagesRead": 1,
                    "detailPagesRead": 0, "detailErrors": 0,
                    "datedGenreLeads": 0, "heldOrIrrelevant": 0,
                    "possibleExisting": 0, "explicitConcertStart": 0,
                    "publicationAllowed": False,
                }
                for detail_url in selected:
                    try:
                        if not robots_allow(detail_url, robot_cache):
                            diag["detailErrors"] += 1
                            continue
                        page, actual = download(detail_url, timeout=11, cap=1_000_000)
                        if actual != detail_url:
                            diag["detailErrors"] += 1
                            continue
                        diag["detailPagesRead"] += 1
                        try:
                            record = cargo_adapter.candidate(
                                page, detail_url, source, day.isoformat())
                        except (ValueError, TypeError, KeyError):
                            diag["heldOrIrrelevant"] += 1
                            continue
                        mark_match(record, known)
                        diag["possibleExisting"] += int(
                            record["possibleExistingConcert"])
                        diag["explicitConcertStart"] += int(
                            record["timeMeaning"] == "explicit_first_party_concert_start")
                        collected[record["candidateId"]] = record
                        diag["datedGenreLeads"] += 1
                        count += 1
                    except Exception:
                        diag["detailErrors"] += 1
                info["adapterDiagnostic"] = diag
            if source.get("adapter") == "bbc_official_detail_review":
                # BBC WordPress listing gives first-party named detail URLs.
                # The individual H2 proves full day/month/year but its printed
                # 20:00 NEVER proves the musical start. All leads stay private.
                urls = bbc_adapter.official_links(first, final)
                selected = bbc_adapter.selected_urls(
                    urls, known, day.isoformat(),
                    limit=source.get("maxDetailPagesPerRun", 8))
                diag = {
                    "method": "bounded_bbc_first_party_detail_review",
                    "eventLinksFound": len(urls), "agendaPagesRead": 1,
                    "detailPagesRead": 0, "detailErrors": 0,
                    "datedGenreLeads": 0, "heldOrIrrelevant": 0,
                    "possibleExisting": 0, "unqualifiedDisplayClocks": 0,
                    "publicationAllowed": False,
                }
                for detail_url in selected:
                    try:
                        if not robots_allow(detail_url, robot_cache):
                            diag["detailErrors"] += 1
                            continue
                        page, actual = download(
                            detail_url, timeout=11, cap=1_000_000)
                        if actual != detail_url:
                            diag["detailErrors"] += 1
                            continue
                        diag["detailPagesRead"] += 1
                        try:
                            record = bbc_adapter.candidate(
                                page, detail_url, source, day.isoformat())
                        except (ValueError, TypeError, KeyError):
                            diag["heldOrIrrelevant"] += 1
                            continue
                        mark_match(record, known)
                        diag["possibleExisting"] += int(
                            record["possibleExistingConcert"])
                        diag["unqualifiedDisplayClocks"] += int(
                            record["announcedClock"] is not None)
                        collected[record["candidateId"]] = record
                        diag["datedGenreLeads"] += 1
                        count += 1
                    except Exception:
                        diag["detailErrors"] += 1
                info["adapterDiagnostic"] = diag
            if source.get("adapter") == "chatodo_official_detail_review":
                # WordPress cards omit the YEAR: first-party individual pages
                # must prove year, genre, headline and exact Chato'do room.
                pages_seen, page_errors = 1, 0
                links = chatodo_adapter.official_links(first, final)
                for number in range(2, max(2, min(4, int(
                        source.get("maxAgendaPagesPerRun", 2))) + 1)):
                    page_url = chatodo_adapter.AGENDA + "page/" + str(number) + "/"
                    try:
                        if not chatodo_adapter.agenda_url(page_url) or not robots_allow(
                                page_url, robot_cache):
                            page_errors += 1
                            continue
                        html_page, actual = download(
                            page_url, timeout=12, cap=1_500_000)
                        if actual != page_url:
                            page_errors += 1
                            continue
                        links += chatodo_adapter.official_links(html_page, actual)
                        pages_seen += 1
                    except Exception:
                        page_errors += 1
                selected = chatodo_adapter.selected_urls(
                    links, known, day.isoformat(),
                    limit=source.get("maxDetailPagesPerRun", 8))
                diag = {"method": "bounded_chatodo_first_party_individual_details",
                        "agendaPagesRead": pages_seen,
                        "agendaErrors": page_errors,
                        "eventLinksFound": len(set(links)),
                        "detailPagesRead": 0, "detailErrors": 0,
                        "datedGenreLeads": 0, "heldOrIrrelevant": 0,
                        "alreadyLikelyPublished": 0,
                        "publicationAllowed": False}
                cached = {u: t for t, u in pages}
                for url in selected:
                    try:
                        if not robots_allow(url, robot_cache):
                            diag["detailErrors"] += 1
                            continue
                        if url in cached:
                            detail, actual = cached[url], url
                        else:
                            detail, actual = download(url, timeout=11, cap=1_100_000)
                        if actual != url:
                            diag["detailErrors"] += 1
                            continue
                        diag["detailPagesRead"] += 1
                        try:
                            record = chatodo_adapter.candidate(
                                detail, url, source, day.isoformat())
                        except (ValueError, TypeError, KeyError):
                            diag["heldOrIrrelevant"] += 1
                            continue
                        mark_match(record, known)
                        diag["alreadyLikelyPublished"] += int(
                            record["possibleExistingConcert"])
                        collected[record["candidateId"]] = record
                        diag["datedGenreLeads"] += 1
                        count += 1
                    except Exception:
                        diag["detailErrors"] += 1
                info["adapterDiagnostic"] = diag
            if source.get("adapter") == "astrolabe_official_detail_review":
                # Homepage is a curated current-event index; /agenda/ includes
                # many years of archives and is deliberately never scanned.
                urls = astrolabe_adapter.detail_urls(first, final)
                selected = astrolabe_adapter.selected_urls(
                    urls, known, day.isoformat(),
                    limit=source.get("maxDetailPagesPerRun", 8))
                diag = {
                    "method": "bounded_astrolabe_first_party_event_details",
                    "eventLinksFound": len(urls),
                    "detailPagesChecked": 0,
                    "datedGenreLeads": 0,
                    "alreadyKnownUrls": sum(("officialUrl", u) in known for u in urls),
                    "heldOrIrrelevant": 0,
                    "fetchErrors": 0,
                    "publicationAllowed": False,
                }
                for event_url in selected:
                    try:
                        if not robots_allow(event_url, robot_cache):
                            diag["fetchErrors"] += 1
                            continue
                        page, actual = download(event_url, timeout=10, cap=900_000)
                        if actual != event_url:
                            diag["fetchErrors"] += 1
                            continue
                        diag["detailPagesChecked"] += 1
                        try:
                            record = astrolabe_adapter.detail_candidate(
                                page, event_url, source, day.isoformat())
                        except (ValueError, TypeError, KeyError):
                            diag["heldOrIrrelevant"] += 1
                            continue
                        mark_match(record, known)
                        collected[record["candidateId"]] = record
                        count += 1
                        diag["datedGenreLeads"] += 1
                    except Exception:
                        diag["fetchErrors"] += 1
                info["adapterDiagnostic"] = diag
            if source.get("adapter") == "bonjour_minuit_official_detail_review":
                # Bonjour Minuit: index is ONLY an event URL index. Event
                # date/genre/room must all come from the named first-party
                # detail, not the agenda's door clocks or a biography.
                urls = bonjour_minuit_adapter.agenda_links(first, final)
                selected = bonjour_minuit_adapter.choose(
                    urls, known, day.isoformat(),
                    limit=source.get("maxDetailPagesPerRun", 8))
                diag = {
                    "method": "bounded_bonjour_minuit_named_first_party_details",
                    "agendaPagesRead": 1, "agendaErrors": 0,
                    "eventLinksFound": len(urls),
                    "detailPagesRead": 0, "detailErrors": 0,
                    "datedGenreLeads": 0, "alreadyLikelyPublished": 0,
                    "heldOrIrrelevant": 0, "soldOutReviewNotices": 0,
                    "cancellationReviewNotices": 0,
                    "publicationAllowed": False,
                }
                # One page / max eight nominated first-party detail requests.
                # No unverified load-more, archive, calendar or ticketing API.
                for detail_url in selected:
                    try:
                        if not bonjour_minuit_adapter.detail_url(detail_url) == detail_url or not robots_allow(
                                detail_url, robot_cache):
                            diag["detailErrors"] += 1
                            continue
                        html, actual = download(detail_url, timeout=11, cap=900_000)
                        if actual != detail_url:
                            diag["detailErrors"] += 1
                            continue
                        diag["detailPagesRead"] += 1
                        try:
                            item = bonjour_minuit_adapter.candidate(
                                html, detail_url, source, day.isoformat())
                        except (ValueError, TypeError, KeyError):
                            diag["heldOrIrrelevant"] += 1
                            continue
                        mark_match(item, known)
                        diag["alreadyLikelyPublished"] += int(
                            item["possibleExistingConcert"])
                        diag["soldOutReviewNotices"] += int(item["soldOutNotice"])
                        diag["cancellationReviewNotices"] += int(
                            item["cancellationNotice"])
                        collected[item["candidateId"]] = item
                        diag["datedGenreLeads"] += 1
                        count += 1
                    except Exception:
                        diag["detailErrors"] += 1
                info["adapterDiagnostic"] = diag
            if source.get("adapter") == "antipode_official_detail_review":
                # Antipode: the dated full-year agenda is the index. Every
                # event must have a matching first-party named page and exact
                # Antipode Grande Scène. The site has no verified pagination.
                cards = antipode_adapter.agenda_cards(
                    first, final, day.isoformat())
                distinct = {c["url"]: c for c in cards}
                limit = max(1,min(10,int(source.get("maxDetailPagesPerRun",8))))
                selected = antipode_adapter.selected_cards(
                    cards,known,day.isoformat(),limit=limit)
                diag = {
                    "method":"bounded_first_party_antipode_agenda_details",
                    "agendaPagesRead":1,"agendaErrors":0,
                    "datedGenreLinks":len(distinct),
                    "detailPagesRead":0,"detailErrors":0,
                    "datedGenreLeads":0,"alreadyLikelyPublished":0,
                    "cancellationReviewNotices":0,"soldOutReviewNotices":0,
                    "heldOrIrrelevant":0,"publicationAllowed":False,
                }
                # One detail per official link; never follow venue footers or
                # card recommendations and never use a guessed ?page= query.
                cached = {u: text for text,u in pages}
                for card in selected:
                    link = card["url"]
                    try:
                        if not antipode_adapter.official_link(link) == link or not robots_allow(
                                link,robot_cache):
                            diag["detailErrors"] += 1
                            continue
                        if link in cached:
                            detail,actual=cached[link],link
                        else:
                            detail,actual=download(link,timeout=11,cap=900_000)
                        if actual != link:
                            diag["detailErrors"] += 1
                            continue
                        diag["detailPagesRead"] += 1
                        try:
                            item = antipode_adapter.candidate(
                                detail,link,card,source,day.isoformat())
                        except (ValueError,TypeError,KeyError):
                            diag["heldOrIrrelevant"] += 1
                            continue
                        mark_match(item,known)
                        diag["alreadyLikelyPublished"] += int(
                            item["possibleExistingConcert"])
                        diag["cancellationReviewNotices"] += int(
                            item["cancellationNotice"])
                        diag["soldOutReviewNotices"] += int(
                            item["soldOutNotice"])
                        collected[item["candidateId"]] = item
                        diag["datedGenreLeads"] += 1
                        count += 1
                    except Exception:
                        diag["detailErrors"] += 1
                info["adapterDiagnostic"] = diag
            if source.get("adapter") == "le106_official_agenda_review":
                # Le 106: agenda officiel paginé avec années explicites.
                # Le détail nominatif permet de retrouver les premières parties,
                # mais ne prouve JAMAIS l'heure de début musical.
                max_pages = max(1, min(3, int(source.get("maxAgendaPagesPerRun", 3))))
                max_rotation = max(1, min(5, int(source.get("agendaPageRotationMax", 5))))
                cards = le106_adapter.agenda_cards(first, final, day.isoformat())
                agenda_pages_read, agenda_errors = 1, 0
                for offset in range(min(max_pages - 1, max_rotation)):
                    page_number = 1 + ((day.toordinal() + offset) % max_rotation)
                    page_url = le106_adapter.AGENDA + "?page=" + str(page_number)
                    try:
                        if not le106_adapter.valid_agenda(page_url) or not robots_allow(
                                page_url, robot_cache):
                            agenda_errors += 1
                            continue
                        page_html, actual = download(page_url, timeout=11, cap=1_500_000)
                        if actual != page_url:
                            agenda_errors += 1
                            continue
                        cards.extend(le106_adapter.agenda_cards(
                            page_html, page_url, day.isoformat()))
                        agenda_pages_read += 1
                    except Exception:
                        agenda_errors += 1
                distinct = {x["url"]: x for x in cards}
                limit = max(1, min(8, int(source.get("maxDetailPagesPerRun", 8))))
                selected = le106_adapter.selected_cards(
                    list(distinct.values()), known, day.isoformat(), limit=limit)
                diag = {
                    "method": "bounded_official_106_agenda_detail_review",
                    "agendaPagesRead": agenda_pages_read,
                    "agendaErrors": agenda_errors,
                    "datedGenreLinks": len(distinct),
                    "detailPagesRead": 0,
                    "detailErrors": 0,
                    "datedGenreLeads": 0,
                    "alreadyLikelyPublished": 0,
                    "publicationAllowed": False,
                }
                cached = {u: t for t, u in pages}
                for card in selected:
                    detail_url = card["url"]
                    try:
                        if not robots_allow(detail_url, robot_cache):
                            diag["detailErrors"] += 1
                            continue
                        if detail_url in cached:
                            detail, actual = cached[detail_url], detail_url
                        else:
                            detail, actual = download(
                                detail_url, timeout=11, cap=900_000)
                        if actual != detail_url:
                            diag["detailErrors"] += 1
                            continue
                        diag["detailPagesRead"] += 1
                        try:
                            candidate = le106_adapter.candidate(
                                detail, detail_url, card, source, day.isoformat())
                        except (ValueError, TypeError, KeyError):
                            continue
                        mark_match(candidate, known)
                        diag["alreadyLikelyPublished"] += int(
                            candidate["possibleExistingConcert"])
                        collected[candidate["candidateId"]] = candidate
                        diag["datedGenreLeads"] += 1
                        count += 1
                    except Exception:
                        diag["detailErrors"] += 1
                info["adapterDiagnostic"] = diag
            if source.get("adapter") == "laiterie_official_detail_review":
                # The official programme has several pages, but discovery
                # remains bounded to page one and one rotating later page.
                last = laiterie_adapter.max_agenda_page(first, final)
                page_number = (2 + (day.toordinal() + scan_slot) % (last - 1)) if last > 1 else None
                extra_agendas = []
                diag = {"method": "rotating_first_party_laiterie_details",
                        "lastAgendaPage": last, "agendaPagesChecked": 1,
                        "agendaErrors": 0, "eventLinksFound": 0,
                        "detailPagesChecked": 0, "datedGenreLeads": 0,
                        "alreadyKnownUrls": 0, "heldOrIrrelevant": 0,
                        "fetchErrors": 0, "publicationAllowed": False}
                if page_number:
                    second = f"https://www.artefact.org/la-laiterie/programmation/page/{page_number}/"
                    try:
                        if robots_allow(second, robot_cache):
                            html2, actual2 = download(second, timeout=12, cap=1_200_000)
                            if actual2 == second:
                                extra_agendas.append((html2, actual2))
                                diag["agendaPagesChecked"] += 1
                            else:
                                diag["agendaErrors"] += 1
                        else:
                            diag["agendaErrors"] += 1
                    except Exception:
                        diag["agendaErrors"] += 1
                detail_urls = sorted({
                    u for html_text, site_url in [(first,final), *extra_agendas]
                    for u in laiterie_adapter.links(html_text,site_url)
                })
                # Prioritize unpublished evidence pages without treating
                # them as confirmed new events.
                unseen = [u for u in detail_urls if ("officialUrl", u) not in known]
                seen = [u for u in detail_urls if ("officialUrl", u) in known]
                diag["eventLinksFound"] = len(detail_urls)
                diag["alreadyKnownUrls"] = len(seen)
                limit = max(1, min(10, int(source.get("maxDetailPagesPerRun", 8))))
                head = min(3, len(unseen), limit)
                selected = unseen[:head]
                pool = unseen[head:] + seen
                if pool and len(selected) < limit:
                    slots = min(len(pool), limit-len(selected))
                    offset = ((day.toordinal() + scan_slot)*slots) % len(pool)
                    selected.extend(pool[(offset+i) % len(pool)] for i in range(slots))
                for url in selected:
                    try:
                        if not robots_allow(url, robot_cache):
                            diag["fetchErrors"] += 1
                            continue
                        page, actual = download(url, timeout=10, cap=900_000)
                        if actual != url:
                            diag["fetchErrors"] += 1
                            continue
                        diag["detailPagesChecked"] += 1
                        try:
                            record = laiterie_adapter.details(
                                page, url, source, day.isoformat())
                        except (ValueError, TypeError, KeyError):
                            diag["heldOrIrrelevant"] += 1
                            continue
                        mark_match(record, known)
                        collected[record["candidateId"]] = record
                        count += 1
                        diag["datedGenreLeads"] += 1
                    except Exception:
                        diag["fetchErrors"] += 1
                info["adapterDiagnostic"] = diag
            if source.get("adapter") == "blacklab_official_detail_review":
                # The Events Calendar at /agenda/: first party event details.
                # Only explicitly year-qualified date labels qualify.
                candidates = set(blacklab_adapter.detail_urls(first, final))
                diag = {
                    "method": "bounded_official_blacklab_individual_details",
                    "agendaPagesChecked": 1, "eventLinksFound": 0,
                    "detailPagesChecked": 0, "datedGenreLeads": 0,
                    "yearMissingOrIrrelevant": 0,
                    "unavailable": 0, "publicationAllowed": False,
                }
                next_page = "https://theblacklab.fr/agenda/liste/page/2/"
                if next_page in [
                        urllib.parse.urljoin(final, href)
                        for href in parser.links]:
                    try:
                        if robots_allow(next_page, robot_cache):
                            extra, actual = download(
                                next_page, timeout=12, cap=900_000)
                            if actual == next_page:
                                candidates.update(
                                    blacklab_adapter.detail_urls(extra, actual))
                                diag["agendaPagesChecked"] += 1
                            else:
                                diag["unavailable"] += 1
                        else:
                            diag["unavailable"] += 1
                    except Exception:
                        diag["unavailable"] += 1
                links = sorted(candidates)
                unseen = [u for u in links if ("officialUrl", u) not in known]
                seen = [u for u in links if ("officialUrl", u) in known]
                diag["eventLinksFound"] = len(links)
                limit = max(1, min(12, int(source.get("maxDetailPagesPerRun", 10))))
                selected = unseen[:min(5, len(unseen), limit)]
                pool = unseen[len(selected):] + seen
                if pool and len(selected) < limit:
                    slots = min(len(pool), limit - len(selected))
                    offset = (day.toordinal() * slots) % len(pool)
                    selected.extend(pool[(offset+i) % len(pool)]
                                    for i in range(slots))
                for link in selected:
                    try:
                        if not robots_allow(link, robot_cache):
                            diag["unavailable"] += 1
                            continue
                        page, actual = download(
                            link, timeout=10, cap=850_000)
                        if actual != link:
                            diag["unavailable"] += 1
                            continue
                        diag["detailPagesChecked"] += 1
                        try:
                            record = blacklab_adapter.detail_candidate(
                                page, link, source, day.isoformat())
                        except (ValueError, TypeError, KeyError):
                            diag["yearMissingOrIrrelevant"] += 1
                            continue
                        mark_match(record, known)
                        collected[record["candidateId"]] = record
                        count += 1
                        diag["datedGenreLeads"] += 1
                    except Exception:
                        diag["unavailable"] += 1
                info["adapterDiagnostic"] = diag
            if source.get("adapter") == "rockstore_official_detail_review":
                # Rockstore /concerts/: link index covering 2026-2027.
                # Read bounded individual official details; avoid club nights
                # and do not derive a concert-start time from event clock text.
                urls = rockstore_adapter.detail_urls(first, final, day.isoformat())
                limit = max(1, min(14, int(source.get("maxDetailPagesPerRun", 12))))
                seen = [u for u in urls if ("officialUrl", u) in known]
                selected = rockstore_adapter.selected_details(
                    urls, known, day.isoformat(), limit)
                diag = {
                    "method": "rotating_official_rockstore_individual_detail",
                    "officialEventLinks": len(urls),
                    "alreadyPublishedUrls": len(seen),
                    "detailPagesChecked": 0, "datedGenreLeads": 0,
                    "possibleExisting": 0, "unavailable": 0,
                    "heldOrIrrelevant": 0, "publicationAllowed": False,
                }
                for url in selected:
                    try:
                        if not robots_allow(url, robot_cache):
                            diag["unavailable"] += 1
                            continue
                        body, actual = download(url, timeout=10, cap=800_000)
                        if actual != url:
                            diag["unavailable"] += 1
                            continue
                        diag["detailPagesChecked"] += 1
                        try:
                            record = rockstore_adapter.detail_candidate(
                                body, url, source, day.isoformat())
                        except (ValueError, TypeError, KeyError):
                            diag["heldOrIrrelevant"] += 1
                            continue
                        mark_match(record, known)
                        collected[record["candidateId"]] = record
                        count += 1
                        diag["datedGenreLeads"] += 1
                        diag["possibleExisting"] += int(
                            record["possibleExistingConcert"])
                    except Exception:
                        diag["unavailable"] += 1
                info["adapterDiagnostic"] = diag
            if source.get("adapter") == "bikini_official_details_review":
                urls = bikini_adapter.detail_urls(first, final, day.isoformat())
                limit = max(1, min(24, int(source.get("maxDetailPagesPerRun", 24))))
                head_count = min(8, len(urls), limit)
                selected = urls[:head_count]
                rest = urls[head_count:]
                if rest and len(selected) < limit:
                    slots = min(limit - len(selected), len(rest))
                    start = (day.toordinal() * slots) % len(rest)
                    selected.extend(rest[(start + i) % len(rest)]
                                    for i in range(slots))
                diagnostic = {
                    "method": "bounded_official_bikini_individual_detail",
                    "officialEventLinks": len(urls),
                    "detailPagesChecked": 0,
                    "datedReviewLeads": 0,
                    "possibleExisting": 0,
                    "blockedOrUnavailable": 0,
                    "rejectedOrIrrelevant": 0,
                    "publicationAllowed": False,
                }
                for url in selected:
                    try:
                        if not robots_allow(url, robot_cache):
                            diagnostic["blockedOrUnavailable"] += 1
                            continue
                        body, actual = download(url, timeout=10, cap=850_000)
                        if actual != url:
                            diagnostic["blockedOrUnavailable"] += 1
                            continue
                        diagnostic["detailPagesChecked"] += 1
                        try:
                            record = bikini_adapter.detail_candidate(
                                body, url, source, day.isoformat())
                        except (TypeError, ValueError, KeyError):
                            diagnostic["rejectedOrIrrelevant"] += 1
                            continue
                        mark_match(record, known)
                        collected[record["candidateId"]] = record
                        count += 1
                        diagnostic["datedReviewLeads"] += 1
                        diagnostic["possibleExisting"] += int(
                            record["possibleExistingConcert"])
                    except Exception:
                        diagnostic["blockedOrUnavailable"] += 1
                info["adapterDiagnostic"] = diagnostic
            if source.get("adapter") in (
                    "backstage_individual_details", "forum_individual_details"):
                kind = ("backstage" if source["adapter"] ==
                        "backstage_individual_details" else "forum")
                # Exact agenda serves only as a *link index*. One-by-one
                # first-party pages must prove year, genre, venue and title.
                # No year inferred from today's date or calendar position.
                candidates = club_pages.detail_urls(first, final, kind)
                limit = max(1,min(8,int(source.get("maxDetailPagesPerRun",6))))
                start_index = day.toordinal() % len(candidates) if candidates else 0
                inspect_urls = [
                    candidates[(start_index+i)%len(candidates)]
                    for i in range(min(limit,len(candidates)))
                ]
                diagnostics = {
                    "method":"rotating_official_individual_event_pages",
                    "eventLinksFound":len(candidates),
                    "detailPagesChecked":0,
                    "detailErrors":0,
                    "undatedOrNotMetal":0,
                    "datedGenreLeads":0,
                    "likelyExisting":0,
                    "publicationAllowed":False
                }
                # First 3 generic event-detail fetches may already be cached.
                cache = {page_url:html_text for html_text,page_url in pages}
                for url in inspect_urls:
                    try:
                        if not robots_allow(url, robot_cache):
                            diagnostics["detailErrors"] += 1
                            continue
                        if url in cache:
                            content,redirected=cache[url],url
                        else:
                            content,redirected=download(url,timeout=10,cap=650_000)
                        if redirected != url:
                            diagnostics["detailErrors"] += 1
                            continue
                        diagnostics["detailPagesChecked"] += 1
                        try:
                            record=club_pages.detail_candidate(
                                content,url,source,day.isoformat(),kind)
                        except (ValueError,TypeError,KeyError):
                            diagnostics["undatedOrNotMetal"] += 1
                            continue
                        mark_match(record, known)
                        if record["possibleExistingConcert"]:
                            diagnostics["likelyExisting"] += 1
                        collected[record["candidateId"]] = record
                        diagnostics["datedGenreLeads"] += 1
                        count += 1
                    except Exception:
                        diagnostics["detailErrors"] += 1
                info["adapterDiagnostic"] = diagnostics
            if source.get("adapter") in (
                    "maroquinerie_official_detail_review",
                    "boule_noire_official_detail_review"):
                # Exactly first-party individual gig details, never generic
                # cards, album release dates or an inferred event year.
                mod = (maroquinerie_adapter
                       if source["adapter"] == "maroquinerie_official_detail_review"
                       else boule_noire_adapter)
                urls=mod.detail_links(first,final)
                calendar_dates=(maroquinerie_adapter.verified_calendar_dates(first,final)
                    if source.get('adapter')=='maroquinerie_official_detail_review'
                    else {})
                limit=max(1,min(8,int(source.get("maxDetailPagesPerRun",8))))
                # Check imminent gigs first, rotate the rest to cover the
                # whole venue's rolling programme without scraping it all.
                head=min(3,len(urls),limit)
                selected=list(urls[:head])
                rest=urls[head:]
                if rest and len(selected)<limit:
                    n=limit-len(selected)
                    offset=(day.toordinal()*n)%len(rest)
                    selected.extend(rest[(offset+i)%len(rest)]
                                    for i in range(min(n,len(rest))))
                diag={"method":"first_party_event_detail_review_only",
                      "eventLinksFound":len(urls),"detailPagesChecked":0,
                      "datedReviewLeads":0,"undatedOrIrrelevant":0,
                      "unavailable":0,"publicationAllowed":False}
                for link in selected:
                    try:
                        if not robots_allow(link,robot_cache):
                            diag["unavailable"]+=1
                            continue
                        body,redirected=download(link,timeout=10,cap=800_000)
                        if redirected!=link:
                            diag["unavailable"]+=1
                            continue
                        diag["detailPagesChecked"]+=1
                        try:
                            if source["adapter"]=="maroquinerie_official_detail_review":
                                row=mod.detail_candidate(
                                    body,link,source,day.isoformat(),
                                    calendar_proof=calendar_dates.get(link))
                            else:
                                row=mod.detail_candidate(
                                    body,link,source,day.isoformat())
                        except (ValueError,TypeError,KeyError):
                            diag["undatedOrIrrelevant"]+=1
                            continue
                        mark_match(row,known)
                        collected[row["candidateId"]]=row
                        diag["datedReviewLeads"]+=1
                        count+=1
                    except Exception:
                        diag["unavailable"]+=1
                info["adapterDiagnostic"]=diag
            if source.get("adapter") == "trabendo_official_detail_review":
                priority,other=trabendo_adapter.categorized_detail_links(
                    first,final)
                limit=max(1,min(8,int(source.get("maxDetailPagesPerRun",6))))
                inspected=[]
                if priority:
                    # Always review two earliest relevant listings; rotate
                    # remaining metal/hardcore/punk first and all others last.
                    recent=min(2,limit,len(priority))
                    inspected.extend(priority[:recent])
                    pool=priority[recent:]
                    slots=min(4,limit-len(inspected),len(pool))
                    if slots:
                        offset=(day.toordinal()*slots)%len(pool)
                        inspected.extend(pool[(offset+i)%len(pool)]
                                         for i in range(slots))
                    slots=min(limit-len(inspected),len(other))
                    if slots:
                        offset=(day.toordinal()*slots)%len(other)
                        inspected.extend(other[(offset+i)%len(other)]
                                         for i in range(slots))
                else:
                    slots=min(limit,len(other))
                    offset=(day.toordinal()*slots)%len(other) if other else 0
                    inspected.extend(other[(offset+i)%len(other)]
                                     for i in range(slots))
                diag={"method":"read_only_first_party_details_with_genre_prioritization",
                      "eventLinksFound":len(priority)+len(other),
                      "categoryRelevantLinks":len(priority),
                      "selectedForReview":len(inspected),
                      "detailPagesChecked":0,"datedReviewLeads":0,
                      "rejectedOrUnavailable":0,
                      "blockedOrRobotsUnavailable":0,
                      "fetchErrors":0,"redirected":0,
                      "validationRejected":0,"validationReasons":{},
                      "publicationAllowed":False}
                # Static internal diagnostic labels only: never copy an
                # exception containing a remote URL or private credentials
                # into a report or GitHub summary.
                reason_labels={
                    "Untrusted concert URL":"url_invalid",
                    "Venue identity mismatch":"venue_mismatch",
                    "Concert incomplete":"empty_content",
                    "Official unique Trabendo event title absent":"headline_missing",
                    "Unexpected Trabendo event identity":"headline_unexpected",
                    "Cancellation or venue change requires human review":"cancellation_or_relocation",
                    "No single dated official event card with matching title and genre":
                        "date_title_or_genre_not_correlated",
                }
                for link in inspected:
                    try:
                        allowed=robots_allow(link,robot_cache)
                    except Exception:
                        allowed=False
                    if not allowed:
                        diag["blockedOrRobotsUnavailable"]+=1
                        diag["rejectedOrUnavailable"]+=1
                        continue
                    try:
                        content,actual=download(link,timeout=11,cap=900000)
                    except Exception:
                        diag["fetchErrors"]+=1
                        diag["rejectedOrUnavailable"]+=1
                        continue
                    if actual!=link:
                        diag["redirected"]+=1
                        diag["rejectedOrUnavailable"]+=1
                        continue
                    diag["detailPagesChecked"]+=1
                    try:
                        row=trabendo_adapter.detail_candidate(
                            content,link,source,day.isoformat())
                    except (ValueError,TypeError,KeyError) as exc:
                        reason=reason_labels.get(str(exc),"other_validation")
                        diag["validationRejected"]+=1
                        diag["rejectedOrUnavailable"]+=1
                        counts=diag["validationReasons"]
                        counts[reason]=counts.get(reason,0)+1
                        continue
                    mark_match(row,known)
                    collected[row["candidateId"]]=row
                    diag["datedReviewLeads"]+=1
                    count+=1
                info["adapterDiagnostic"]=diag
            if source.get("adapter") == "glazart_official_detail_review":
                # Page d'agenda = index de liens UNIQUEMENT. Les fiches
                # individuelles doivent confirmer une date cohérente avec
                # l'URL et le titre officiel de concert. Aucun contenu du
                # collecteur ne vaut approbation pour la carte publique.
                candidate_links=glazart_adapter.detail_links(first,final)
                limit=max(1,min(8,int(source.get("maxDetailPagesPerRun",7))))
                shift=(day.toordinal()*limit)%len(candidate_links) if candidate_links else 0
                inspected=[candidate_links[(shift+i)%len(candidate_links)]
                           for i in range(min(limit,len(candidate_links)))]
                diagnostics={"method":"rotating_first_party_event_details_read_only",
                             "eventLinksFound":len(candidate_links),
                             "detailPagesChecked":0,"detailErrors":0,
                             "undatedOrWrongPage":0,"datedReviewLeads":0,
                             "likelyExisting":0,"lineupHints":0,
                             "publicationAllowed":False}
                cache={page_url:html_text for html_text,page_url in pages}
                for link in inspected:
                    try:
                        if not robots_allow(link,robot_cache):
                            diagnostics["detailErrors"]+=1
                            continue
                        if link in cache:
                            detail,redirected=cache[link],link
                        else:
                            detail,redirected=download(link,timeout=10,cap=650_000)
                        if redirected!=link:
                            diagnostics["detailErrors"]+=1
                            continue
                        diagnostics["detailPagesChecked"]+=1
                        try:
                            row=glazart_adapter.detail_candidate(
                                detail,link,source,day.isoformat())
                        except (ValueError,TypeError,KeyError):
                            diagnostics["undatedOrWrongPage"]+=1
                            continue
                        mark_match(row,known)
                        if row.get("possibleExistingConcert"):
                            diagnostics["likelyExisting"]+=1
                        if row.get("artistNamesToVerify"):
                            diagnostics["lineupHints"]+=1
                        collected[row["candidateId"]]=row
                        diagnostics["datedReviewLeads"]+=1
                        count+=1
                    except Exception:
                        diagnostics["detailErrors"]+=1
                info["adapterDiagnostic"]=diagnostics
            if source.get("adapter") in (
                    "rockneat_official_listing_review",
                    "maisonbleue_official_listing_review"):
                # These venue calendars are first-party leads, not event
                # approvals. Rock n' Eat does not label the genre per event;
                # Maison Bleue has an explicit full year and genre badge.
                kind = ("rockneat" if source["adapter"] ==
                        "rockneat_official_listing_review" else "maisonbleue")
                parser = (regional_clubs.rockneat if kind == "rockneat"
                          else regional_clubs.maison_bleue)
                leads = parser(
                    first, final, source, day.isoformat(),
                    cap=min(25,max(1,int(source.get("maxListingLeadsPerRun",20)))))
                for record in leads:
                    mark_match(record, known)
                    collected[record["candidateId"]] = record
                    count += 1
                info["adapterDiagnostic"] = {
                    "method":"official_first_party_list_read_only",
                    "venueType":kind, "leads":len(leads),
                    "genreUnconfirmed":sum(x["genreToConfirm"] for x in leads),
                    "publicationAllowed":False,
                }
            if source.get("adapter") == "la_malterie_ical":
                # La liste Drupal peut masquer les noms des artistes; ses fiches
                # individuelles, elles, donnent titre et date complète.
                # Ne jamais déduire le genre des seules descriptions du lieu.
                links = malterie_adapter.detail_urls(first, final, limit=24)
                limit = max(1, min(10, int(source.get("maxDetailPagesPerRun", 9))))
                start_index = (day.toordinal() * limit) % len(links) if links else 0
                chosen_links = [links[(start_index + i) % len(links)]
                                for i in range(min(limit, len(links)))]
                diagnostics = {"method": "individual_official_pages",
                               "eventLinksFound": len(links),
                               "detailPagesRead": 0, "detailErrors": 0,
                               "datedGenreLeads": 0, "icsProbed": 0}
                existing_pages = {url: body for body, url in pages}
                for link in chosen_links:
                    try:
                        if not robots_allow(link, robot_cache):
                            diagnostics["detailErrors"] += 1
                            continue
                        if link in existing_pages:
                            detail_html, detail_url = existing_pages[link], link
                        else:
                            detail_html, detail_url = download(
                                link, timeout=9, cap=650_000)
                            if not same_host(detail_url, final):
                                diagnostics["detailErrors"] += 1
                                continue
                        diagnostics["detailPagesRead"] += 1
                        for record in malterie_adapter.list_fallback_candidates(
                                detail_html, detail_url, source, day.isoformat()):
                            mark_match(record, known)
                            collected[record["candidateId"]] = record
                            diagnostics["datedGenreLeads"] += 1
                            count += 1
                    except Exception:
                        diagnostics["detailErrors"] += 1
                # Une page sans accès ou sans genre lisible ne devient pas
                # un événement. Les ICS individuels bloqués ne sont plus sondés
                # quotidiennement; ils sont conservés dans le module de test.
                info["adapterDiagnostic"] = diagnostics
            if source.get("adapter") == "jokers_pub_home_and_detail":
                rows = joker_adapter.listing_candidates(
                    first, final, source, day.isoformat())
                diagnostics = {"datedListings": len(rows),
                               "detailPagesChecked": 0,
                               "genreTagsFound": 0,
                               "detailErrors": 0,
                               "layout": joker_adapter.diagnose_layout(first)}
                # Rotation : le classement des événements ne dépend pas des
                # résultats de l'extracteur ou d'un tri par genre supposé.
                limit = min(max(1, int(source.get("maxDetailPagesPerRun", 7))),
                            10)
                start_pos = (day.toordinal() * limit) % len(rows) if rows else 0
                check_ids = {(start_pos + i) % len(rows)
                             for i in range(min(limit, len(rows)))}
                for i, record in enumerate(rows):
                    if i in check_ids:
                        url = record["sourceUrl"]
                        try:
                            if robots_allow(url, robot_cache):
                                detail_html, redirected = download(
                                    url, timeout=9, cap=450_000)
                                if same_host(redirected, final):
                                    record = joker_adapter.with_details(
                                        record, detail_html)
                                    diagnostics["detailPagesChecked"] += 1
                                    if record.get("classification"):
                                        diagnostics["genreTagsFound"] += 1
                        except Exception:
                            diagnostics["detailErrors"] += 1
                    mark_match(record, known)
                    collected[record["candidateId"]] = record
                    count += 1
                info["adapterDiagnostic"] = diagnostics
            if source.get("adapter") == "echo_system_official_detail":
                # Official agenda cards show day/month but not YEAR. Fetch a
                # small rotating set of detail pages and use ONLY their
                # full dated genre/venue evidence; no direct approvals.
                candidates = echo_system_adapter.official_links(first, final)
                limit = max(1, min(8, int(source.get("maxDetailPagesPerRun", 8))))
                position = (day.toordinal() * limit) % len(candidates) if candidates else 0
                inspect_urls = [candidates[(position + i) % len(candidates)]
                                for i in range(min(limit,len(candidates)))]
                diagnostics = {"method":"first_party_individual_event_details",
                               "eventLinksFound":len(candidates),
                               "detailPagesRead":0,"detailErrors":0,
                               "datedMetalPunkLeads":0,"alreadyLikelyPublished":0}
                cache = {url:body for body,url in pages}
                for link in inspect_urls:
                    try:
                        if not robots_allow(link, robot_cache):
                            diagnostics["detailErrors"] += 1
                            continue
                        if link in cache:
                            detail, redirected = cache[link], link
                        else:
                            detail, redirected = download(
                                link, timeout=10, cap=600_000)
                        if not same_host(redirected, final):
                            diagnostics["detailErrors"] += 1
                            continue
                        diagnostics["detailPagesRead"] += 1
                        try:
                            record = echo_system_adapter.detail_candidate(
                                detail, link, source, day.isoformat())
                        except (ValueError, TypeError, KeyError):
                            continue
                        mark_match(record, known)
                        if record.get("possibleExistingConcert"):
                            diagnostics["alreadyLikelyPublished"] += 1
                        collected[record["candidateId"]] = record
                        diagnostics["datedMetalPunkLeads"] += 1
                        count += 1
                    except Exception:
                        # A network/robots failure is a held lead, not a
                        # reason to change the public catalogue.
                        diagnostics["detailErrors"] += 1
                info["adapterDiagnostic"] = diagnostics
            if source.get("adapter") == "atabal_official_detail":
                # WordPress official /agenda/concerts/ event link index.
                # The slug and the detail must agree on the full date;
                # genre comes only from the individual event's official page.
                cards=atabal_adapter.cards(first)
                eligible=[x for x in cards if x["date"]>=day.isoformat()]
                limit=max(1,min(12,int(source.get("maxDetailPagesPerRun",12))))
                # Prioritize official upcoming punk/metal acts already found
                # in the national gap audit, then rotate other live pages.
                # Priority alone never makes a concert publishable.
                priority_terms=("anestesia","burning-heads","mairu",
                                "frankie","iguana-death","svinkels")
                high=[x for x in eligible if any(t in x["slug"] for t in priority_terms)]
                other=[x for x in eligible if x not in high]
                high.sort(key=lambda x:(x["date"],x["url"]))
                other.sort(key=lambda x:(x["date"],x["url"]))
                take=high[:min(4,limit)]
                rest=high[len(take):]+other
                if rest and len(take)<limit:
                    n=limit-len(take)
                    offset=(day.toordinal()*n)%len(rest)
                    take.extend(rest[(offset+i)%len(rest)]
                                for i in range(min(n,len(rest))))
                stats={"method":"bounded_official_atabal_detail_review",
                       "eventLinksFound":len(cards),"detailPagesRead":0,
                       "detailErrors":0,"datedGenreLeads":0,
                       "alreadyLikelyPublished":0,"publicationAllowed":False}
                cache={u:t for t,u in pages}
                for card in take:
                    url=card["url"]
                    try:
                        if not robots_allow(url,robot_cache):
                            stats["detailErrors"]+=1
                            continue
                        if url in cache:
                            details,redirected=cache[url],url
                        else:
                            details,redirected=download(url,timeout=11,cap=1_000_000)
                        if redirected!=url:
                            stats["detailErrors"]+=1
                            continue
                        stats["detailPagesRead"]+=1
                        try:
                            item=atabal_adapter.candidate(details,url,card,source,
                                                          day.isoformat())
                        except (ValueError,KeyError,TypeError):
                            continue
                        mark_match(item,known)
                        stats["alreadyLikelyPublished"]+=int(
                            item["possibleExistingConcert"])
                        collected[item["candidateId"]]=item
                        stats["datedGenreLeads"]+=1
                        count+=1
                    except Exception:
                        stats["detailErrors"]+=1
                info["adapterDiagnostic"]=stats
            if source.get("adapter") == "hydrophone_spip_review":
                # Official SPIP cards do NOT include year. Do not derive the
                # year from current time, chronology, site footer or URL.
                # The exact-event allowlist requires full date from an
                # independently checked ticket distributor record.
                cards=hydrophone_adapter.agenda_cards(first)
                eligible=[x for x in cards if not x["festivalContext"]
                          and not x["blocked"]]
                limit=max(1,min(9,int(source.get("maxDetailPagesPerRun",9))))
                known_year=[c for c in eligible if
                    c["url"] in hydrophone_adapter.YEAR_PROOFS]
                others=[c for c in eligible if c not in known_year]
                if others:
                    offset=day.toordinal()%len(others)
                    others=(others[offset:]+others[:offset])
                inspect=(known_year+others)[:limit]
                stats={"method":"spip_individual_page_plus_exact_ticket_year",
                    "agendaCards":len(cards),"festivalAndNonconcertFiltered":
                    len(cards)-len(eligible),"yearUnverifiedCards":
                    sum(x["url"] not in hydrophone_adapter.YEAR_PROOFS
                        for x in eligible),"detailPagesRead":0,
                    "detailErrors":0,"yearUnverifiedDetailLeads":0,
                    "datedGenreLeads":0,"alreadyLikelyPublished":0,
                    "publicationAllowed":False}
                cached={u:t for t,u in pages}
                for card in inspect:
                    url=card["url"]
                    try:
                        if not robots_allow(url,robot_cache):
                            stats["detailErrors"]+=1
                            continue
                        if url in cached:
                            body,final_url=cached[url],url
                        else:
                            body,final_url=download(url,timeout=12,cap=750_000)
                        if not same_host(final_url,base):
                            stats["detailErrors"]+=1
                            continue
                        stats["detailPagesRead"]+=1
                        try:
                            proposal=hydrophone_adapter.candidate(
                                body,url,card,source,day.isoformat())
                        except (ValueError,KeyError,TypeError) as e:
                            if "year" in str(e).lower():
                                stats["yearUnverifiedDetailLeads"]+=1
                            continue
                        mark_match(proposal,known)
                        stats["alreadyLikelyPublished"]+=int(
                            proposal["possibleExistingConcert"])
                        collected[proposal["candidateId"]]=proposal
                        stats["datedGenreLeads"]+=1
                        count+=1
                    except Exception:
                        stats["detailErrors"]+=1
                info["adapterDiagnostic"]=stats
            if source.get("adapter") == "carene_spip_official_detail":
                # SPIP /-agenda-.html is paginated in pages of 25: only the
                # exact individual venue page can substantiate subgenre,
                # physical room and headline. Festivals remain quarantined.
                all_cards=carene_adapter.agenda_cards(first)
                pages_checked=1
                page_errors=0
                for offset in (25,):
                    second=carene_adapter.BASE+"?debut_agenda="+str(offset)
                    try:
                        if not robots_allow(second,robot_cache):
                            page_errors+=1
                            continue
                        body,final_url=download(second,timeout=12,cap=1_200_000)
                        if final_url!=second:
                            page_errors+=1
                            continue
                        pages_checked+=1
                        all_cards.extend(carene_adapter.agenda_cards(body))
                    except Exception:
                        page_errors+=1
                distinct={x["url"]:x for x in all_cards}
                eligible=[x for x in distinct.values() if
                          x["date"]>=day.isoformat() and not x["festivalContext"]
                          and not x["cancellationNotice"]]
                eligible.sort(key=lambda x:(x["date"],x["url"]))
                limit=max(1,min(9,int(source.get("maxDetailPagesPerRun",9))))
                first_choices=eligible[:min(3,limit)]
                rest=eligible[len(first_choices):]
                if rest:
                    n=limit-len(first_choices)
                    start=(day.toordinal()*max(1,n))%len(rest)
                    first_choices.extend(rest[(start+i)%len(rest)]
                                         for i in range(min(n,len(rest))))
                stats={"method":"bounded_official_spip_agenda_detail",
                       "agendaPagesRead":pages_checked,"agendaErrors":page_errors,
                       "datedLinks":len(distinct),"festivalAndCanceledFiltered":
                       sum(int(x["festivalContext"] or x["cancellationNotice"])
                           for x in distinct.values()),
                       "detailPagesRead":0,"detailErrors":0,
                       "datedGenreLeads":0,"alreadyLikelyPublished":0,
                       "publicationAllowed":False}
                cached={u:t for t,u in pages}
                for card in first_choices:
                    url=card["url"]
                    try:
                        if not robots_allow(url,robot_cache):
                            stats["detailErrors"]+=1
                            continue
                        if url in cached:
                            event_html,final_url=cached[url],url
                        else:
                            event_html,final_url=download(url,timeout=12,
                                                          cap=1_000_000)
                        if final_url!=url:
                            stats["detailErrors"]+=1
                            continue
                        stats["detailPagesRead"]+=1
                        try:
                            proposal=carene_adapter.candidate(event_html,url,
                                     card,source,day.isoformat())
                        except (TypeError,ValueError,KeyError):
                            continue
                        mark_match(proposal,known)
                        stats["alreadyLikelyPublished"]+=int(
                            proposal["possibleExistingConcert"])
                        collected[proposal["candidateId"]]=proposal
                        stats["datedGenreLeads"]+=1
                        count+=1
                    except Exception:
                        stats["detailErrors"]+=1
                info["adapterDiagnostic"]=stats
            if source.get("adapter") == "cave_poetes_first_party_detail":
                # The official WordPress agenda has "unevt" cards. Some
                # cards are at Salle Watremez, some cancelled and several
                # are NOT punk despite the broad "Rock / Metal / Punk" label.
                cards=cave_poetes_adapter.cards(first)
                eligible=[x for x in cards if x["date"]>=day.isoformat()]
                limit=max(1,min(10,int(source.get("maxDetailPagesPerRun",9))))
                # Check near dates first, rotate the rest by local date to
                # reach small indie shows too without an unbounded crawl.
                eligible.sort(key=lambda x:(x["date"],x["url"]))
                lead=eligible[:min(2,limit)]
                rest=eligible[len(lead):]
                if rest:
                    slots=limit-len(lead)
                    offset=(day.toordinal()*max(1,slots))%len(rest)
                    lead.extend(rest[(offset+i)%len(rest)]
                                for i in range(min(slots,len(rest))))
                stats={"method":"official_cave_individual_detail_review",
                       "eventLinksFound":len(cards),
                       "detailPagesRead":0,"detailErrors":0,
                       "datedGenreLeads":0,"possibleExisting":0,
                       "publicationAllowed":False}
                cached={u:t for t,u in pages}
                for card in lead:
                    url=card["url"]
                    try:
                        if not robots_allow(url,robot_cache):
                            stats["detailErrors"]+=1
                            continue
                        if url in cached:
                            detail,final_url=cached[url],url
                        else:
                            detail,final_url=download(url,timeout=11,cap=850_000)
                        if final_url!=url:
                            stats["detailErrors"]+=1
                            continue
                        stats["detailPagesRead"]+=1
                        try:
                            row=cave_poetes_adapter.candidate(
                                detail,url,card,source,day.isoformat())
                        except (ValueError,TypeError,KeyError):
                            continue
                        mark_match(row,known)
                        stats["possibleExisting"]+=int(row["possibleExistingConcert"])
                        collected[row["candidateId"]]=row
                        stats["datedGenreLeads"]+=1
                        count+=1
                    except Exception:
                        stats["detailErrors"]+=1
                info["adapterDiagnostic"]=stats
            if source.get("adapter") == "rocher_palmer_official_detail":
                # Official Drupal agenda is paginated and contains workshops,
                # out-of-town events and unrelated genres. Each lead requires
                # matching date+headline+venue+genre on an individual page.
                # Bounded daily rotating pagination, strict robots and URLs.
                limit=max(1,min(8,int(source.get("maxDetailPagesPerRun",8))))
                max_pages=max(1,min(5,int(source.get("maxAgendaPagesPerRun",3))))
                cards=rocher_palmer_adapter.agenda_cards(first,final)
                pages_read=1
                unavailable=0
                extra_pages=list(range(1,max(2,int(source.get("agendaPageRotationMax",5)))))
                offset=day.toordinal()%len(extra_pages)
                for i in range(min(max_pages-1,len(extra_pages))):
                    number=extra_pages[(offset+i)%len(extra_pages)]
                    url=rocher_palmer_adapter.AGENDA+"?page="+str(number)
                    try:
                        if not robots_allow(url,robot_cache):
                            unavailable+=1
                            continue
                        html_page,redirected=download(url,timeout=12,cap=1_500_000)
                        if redirected!=url:
                            unavailable+=1
                            continue
                        pages_read+=1
                        cards.extend(rocher_palmer_adapter.agenda_cards(
                            html_page,rocher_palmer_adapter.AGENDA))
                    except Exception:
                        unavailable+=1
                # Keep a stable single page per event; the rotation gives
                # later months coverage without harvesting all pages.
                all_cards=list({x["url"]:x for x in cards}.values())
                active=[x for x in all_cards if x["date"]>=day.isoformat()
                        and rocher_palmer_adapter.card_priority(x)>=0]
                priority=[x for x in active
                          if rocher_palmer_adapter.card_priority(x)>0]
                other=[x for x in active
                       if rocher_palmer_adapter.card_priority(x)==0]
                priority.sort(key=lambda x:(x["date"],x["url"]))
                other.sort(key=lambda x:(x["date"],x["url"]))
                # First two explicitly promising listings, then rotate both
                # promising and genre-unknown listings to avoid starvation.
                selected=priority[:min(2,limit)]
                remaining=priority[min(2,limit):]
                pool=remaining+other
                if pool and len(selected)<limit:
                    n=limit-len(selected)
                    start=(day.toordinal()*n)%len(pool)
                    selected.extend(pool[(start+i)%len(pool)]
                                    for i in range(min(n,len(pool))))
                diagnostics={"method":"bounded_official_agenda_individual_detail",
                             "agendaPagesRead":pages_read,
                             "agendaErrors":unavailable,
                             "eventLinksFound":len(all_cards),
                             "detailPagesRead":0,"detailErrors":0,
                             "datedGenreLeads":0,"alreadyLikelyPublished":0,
                             "publicationAllowed":False}
                cache={url:html_text for html_text,url in pages}
                for card in selected:
                    url=card["url"]
                    try:
                        if not robots_allow(url,robot_cache):
                            diagnostics["detailErrors"]+=1
                            continue
                        if url in cache:
                            body,actual=cache[url],url
                        else:
                            body,actual=download(url,timeout=11,cap=1_000_000)
                        if actual!=url:
                            diagnostics["detailErrors"]+=1
                            continue
                        diagnostics["detailPagesRead"]+=1
                        try:
                            record=rocher_palmer_adapter.detail_candidate(
                                body,url,card,source,day.isoformat())
                        except (TypeError,ValueError,KeyError):
                            continue
                        mark_match(record,known)
                        diagnostics["alreadyLikelyPublished"]+=int(
                            record["possibleExistingConcert"])
                        collected[record["candidateId"]]=record
                        diagnostics["datedGenreLeads"]+=1
                        count+=1
                    except Exception:
                        diagnostics["detailErrors"]+=1
                info["adapterDiagnostic"]=diagnostics
            if source.get("adapter") == "brin_de_zinc_billetweb_review":
                # Le programme public WordPress de la salle est peu extractible.
                # Sa billetterie liée est une source SECONDAIRE, jamais preuve
                # d'approbation. Un domaine ou robots refusé = 0 piste.
                ticket_url = source.get("ticketingUrl")
                diagnostics = {"method": "secondary_ticketing_read_only",
                               "status": "source_unavailable",
                               "datedMetalPunkLeads": 0}
                if ticket_url == brin_de_zinc_adapter.TICKETING:
                    try:
                        if not robots_allow(ticket_url, robot_cache):
                            diagnostics["status"] = "blocked_by_robots"
                        else:
                            ticket_html, redirected = download(
                                ticket_url, timeout=11, cap=1_800_000)
                            leads = brin_de_zinc_adapter.candidates(
                                ticket_html, redirected, source, day.isoformat())
                            diagnostics["status"] = "readable"
                            for record in leads:
                                mark_match(record, known)
                                collected[record["candidateId"]] = record
                                count += 1
                            diagnostics["datedMetalPunkLeads"] = len(leads)
                    except (ValueError, TimeoutError, OSError, urllib.error.URLError):
                        diagnostics["status"] = "source_unavailable_or_layout_changed"
                else:
                    diagnostics["status"] = "ticketing_url_not_allowlisted"
                info["adapterDiagnostic"] = diagnostics
            if source.get("adapter") == "le_rex":
                for record in venue_adapters.rex_candidates(first, final, source, day.isoformat()):
                    mark_match(record, known)
                    collected[record["candidateId"]] = record
                    count += 1
            if source.get("adapter") == "le_molotov":
                for record in molotov_adapter.molotov_candidates(
                        first, final, source, day.isoformat()):
                    mark_match(record, known)
                    collected[record["candidateId"]] = record
                    count += 1
            if source.get("adapter") == "le_ferrailleur":
                info["adapterDiagnostic"] = ferrailleur_adapter.diagnose_markup(first)
                for record in ferrailleur_adapter.extract_ferrailleur(
                        first, final, source, day.isoformat()):
                    mark_match(record, known)
                    collected[record["candidateId"]] = record
                    count += 1
            for body, url in ([] if source.get("adapter") in (
                              "antipode_official_detail_review",
                              "bonjour_minuit_official_detail_review",
                              "echonova_official_detail_review") else pages):
                for event in read_ld(body):
                    candidate = venue_candidate(event, source, url, known, day.isoformat())
                    if candidate:
                        collected[candidate["candidateId"]] = candidate
                        count += 1
            # Flux officiels déclarés dans le HTML : un maximum de deux liens de chaque type.
            # Jamais de publication : chaque événement ICS et chaque actualité RSS sont des pistes.
            feed_stats = {"ics": 0, "rss": 0, "feedErrors": []}
            all_links = feeds.feed_links(first, final, same_host)
            preferred_ics = source.get("preferred_ics_url")
            # Un flux officiel 'concerts uniquement' prévaut sur l'agenda général,
            # mais il n'atteste PAS que tous les événements sont du métal.
            if (preferred_ics and preferred_ics.startswith("https://") and
                    same_host(preferred_ics, final)):
                all_links["ics"] = [preferred_ics]
            for kind in ("ics", "rss"):
                for feed_url in all_links[kind]:
                    try:
                        if not robots_allow(feed_url, robot_cache):
                            continue
                        feed_text, feed_final = download(feed_url, timeout=10, cap=2_000_000)
                        if not same_host(feed_final, base):
                            continue
                        if kind == "ics":
                            candidates = feeds.ics_candidates(feed_text, source, feed_final, day.isoformat())
                        else:
                            candidates = feeds.rss_candidates(feed_text, source, feed_final)
                        for candidate in candidates:
                            if kind == "ics":
                                mark_match(candidate, known)
                            collected[candidate["candidateId"]] = candidate
                        feed_stats[kind] += len(candidates)
                    except Exception as feed_error:
                        feed_stats["feedErrors"].append({
                            "type": kind, "errorType": type(feed_error).__name__
                        })
            info.update({"pagesChecked": len(pages), "candidatesDetected": count,
                         "feeds": feed_stats})
        except Exception as err:
            info["error"] = type(err).__name__ + ": " + str(err)[:130]
        report.append(info)
    return list(collected.values())


def scan_ticketmaster(key, known, day, report, max_pages=2):
    """Bounded rolling API audit; never request all genres in one daily burst.

    The observed Discovery API returned zero French classified events with
    date filters, but a valid unfiltered FR diagnostic showed 32 listings.
    Include ONLY explicitly metal/punk classified future French events from
    that index, with source status requiring independent confirmation.
    """
    if not key:
        report.append({"status":"not_configured","message":"Secret TICKETMASTER_API_KEY absent"})
        return []
    found={}
    horizon=day+dt.timedelta(days=240)
    classes=CATEGORIES
    keywords=("metal","metalcore","hardcore","punk","thrash","doom")
    plan=[
        ("classification",classes[day.toordinal()%len(classes)],True),
        ("keyword",keywords[day.toordinal()%len(keywords)],True),
        ("fr_unfiltered_genre_audit","",True),
    ]
    rate_limited=False
    for kind, term, collect in plan:
        if rate_limited:
            break
        pages=min(max(1,int(max_pages)),2) if kind!="fr_unfiltered_genre_audit" else 1
        for page in range(pages):
            params={"apikey":key,"countryCode":"FR",
                    "size":"100","page":str(page)}
            if kind!="fr_unfiltered_genre_audit":
                params["startDateTime"]=day.isoformat()+"T00:00:00Z"
                params["endDateTime"]=horizon.isoformat()+"T23:59:59Z"
            if kind=="classification":
                params["classificationName"]=term
            elif kind=="keyword":
                params["keyword"]=term
            url=TICKETMASTER+"?"+urllib.parse.urlencode(params)
            try:
                # Pace even empty responses. Existing loop only slept on
                # subsequent pages and could hit HTTP 429 during bursts.
                time.sleep(0.45)
                raw,_=download(url,timeout=15,cap=4_000_000)
                response=json.loads(raw)
                if not isinstance(response,dict) or response.get("fault"):
                    report.append({"queryKind":kind,"term":term,"page":page,
                                   "error":"api_fault"})
                    break
            except urllib.error.HTTPError as exc:
                report.append({"queryKind":kind,"term":term,"page":page,
                               "error":"HTTP "+str(exc.code)})
                if exc.code==429:
                    rate_limited=True
                break
            except Exception as exc:
                # Never print exception strings containing API URLs/keys.
                report.append({"queryKind":kind,"term":term,"page":page,
                               "errorType":type(exc).__name__})
                break
            events=((response.get("_embedded") or {}).get("events") or [])
            if not isinstance(events,list):
                report.append({"queryKind":kind,"term":term,"page":page,
                               "error":"invalid_events"})
                break
            accepted=0
            for evt in events:
                if not isinstance(evt,dict):
                    continue
                candidate=ticketmaster_candidate(evt,known,day.isoformat())
                if candidate is None:
                    continue
                if kind=="fr_unfiltered_genre_audit":
                    # No date/keyword search relevance: require an explicit
                    # genre from the event's classification, never infer one
                    # from a room name or a music keyword.
                    categories=" ".join(
                        str((entry.get(field) or {}).get("name",""))
                        for entry in evt.get("classifications",[])
                        if isinstance(entry,dict)
                        for field in ("genre","subGenre"))
                    if not GENRE.search(categories):
                        continue
                found[candidate["candidateId"]]=candidate
                accepted+=1
            page_info=response.get("page") or {}
            report.append({"queryKind":kind,"term":term,"page":page,
                           "received":len(events),
                           "genreDatedLeads":accepted,
                           "totalElements":page_info.get("totalElements"),
                           "diagnosticOnly":False})
            if len(events)<100 or (
                page_info.get("totalPages") and
                page+1>=int(page_info["totalPages"])
            ):
                break
    return list(found.values())


def scan_partner_ics(sources, known, day, report):
    """Flux publics de tiers : pistes uniquement, JAMAIS vérification officielle."""
    collected = {}
    robots_cache = {}
    if sources.get("schema") != "grossesondes.concert.partner-calendar.v1":
        raise ValueError("Registre des flux tiers invalide")
    for source in sources.get("feeds", [])[:10]:
        entry = {"source": source.get("id"), "kind": "third_party_public_ical"}
        url = source["url"]
        try:
            if not robots_allow(url, robots_cache):
                raise RuntimeError("robots.txt indisponible ou accès non autorisé")
            body, final = download(url, timeout=18, cap=2_000_000)
            if not same_host(final, url):
                raise RuntimeError("redirection hors domaine")
            records = partner_calendars.partner_ics_candidates(body, source, day.isoformat())
            for record in records:
                mark_match(record, known)
                collected[record["candidateId"]] = record
            entry["entries"] = len(records)
            entry["status"] = "leads_unverified"
        except Exception as exc:
            entry["error"] = type(exc).__name__
            entry["entries"] = 0
        report.append(entry)
    return list(collected.values())


def candidate_sort_key(candidate):
    return (candidate.get("date") or "9999-12-31",
            candidate.get("city") or "", candidate.get("name") or "")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    dest = Path(args.output)
    dest.mkdir(parents=True, exist_ok=True)
    day = today_fr()
    try:
        catalog = json_url(CATALOG)
        if catalog.get("schemaVersion") != 1 or not isinstance(catalog.get("events"), list):
            raise ValueError("Schéma concerts inattendu")
        festivals = json_url(FESTIVALS)
        if not isinstance(festivals, (dict, list)):
            raise ValueError("Catalogue festivals invalide")
        source_file = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
        partner_sources = json.loads((ROOT / "partner-calendars.json").read_text(encoding="utf-8"))
        known = make_known_keys(catalog)
    except Exception as err:
        print("ÉCHEC FERMÉ : référence publique indisponible/invalide : " + type(err).__name__, file=sys.stderr)
        sys.exit(2)
    venues_checks, ticket_checks = [], []
    scan_slot = scan_slot_for_hour(
        dt.datetime.now(ZoneInfo("Europe/Paris")).hour)
    venue_candidates = scan_venues(
        source_file, known, day, venues_checks, scan_slot=scan_slot)
    partner_checks = []
    partner_candidates = scan_partner_ics(partner_sources, known, day, partner_checks)
    api_candidates = scan_ticketmaster(os.environ.get("TICKETMASTER_API_KEY", "").strip(), known, day, ticket_checks)
    # Separate bounded probes for exact known small venues (not scraped tickets).
    # Ticketmaster venueId is discovered from their public API, NEVER guessed.
    scoped_checks = []
    scoped_candidates = []
    key = os.environ.get("TICKETMASTER_API_KEY", "").strip()
    try:
        probe_config = json.loads((ROOT / "ticketmaster-venues.json").read_text(encoding="utf-8"))
        def api_json(url):
            time.sleep(0.45)
            content, _ = download(url, timeout=16, cap=3_000_000)
            return json.loads(content)
        scoped_candidates, scoped_checks = ticketmaster_venue_probes.probe(
            probe_config, catalog, key, day, api_json,
            ticketmaster_candidate, known)
    except Exception as exc:
        # Never interpolate URL or exception string: URLs carry API secrets.
        scoped_checks = [{"status": "probe_unavailable", "errorType": type(exc).__name__}]
    api_ids = {x["candidateId"] for x in api_candidates}
    api_candidates.extend(x for x in scoped_candidates if x["candidateId"] not in api_ids)
    # Les flux RSS sont des pistes SANS date de concert : tri après les vrais événements.
    candidates = sorted(venue_candidates + partner_candidates + api_candidates, key=candidate_sort_key)
    classified, shortlist, triage_counts = triage.classify(candidates, catalog)
    review = {
        "schema": "grossesondes.concert.discovery.v1",
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "catalogue": {"url": CATALOG, "edition": catalog.get("edition"), "events": len(catalog["events"])},
        "festivalsReferenceRead": True,
        "publicationAllowed": False, "automaticPublication": False,
        "scanSlot": scan_slot,
        "venueChecks": venues_checks, "partnerChecks": partner_checks, "ticketmasterChecks": ticket_checks,
        "ticketmasterVenueProbes": scoped_checks,
        "counts": {"venueCandidates": len(venue_candidates), "partnerCalendarLeads": len(partner_candidates), "ticketmasterCandidates": len(api_candidates),
                   "datedIcsEntriesUnverified": sum(x.get("source") == "agenda_ics" for x in candidates),
                   "icsCancellationNotices": sum(x.get("source") == "ics_cancellation_notice" for x in candidates),
                   "rssUndatedAnnouncements": sum(x.get("source") == "actualite_rss_non_datee" for x in candidates),
                   "structuredEventLeads": sum(x.get("source") == "agenda_officiel_structuré" for x in candidates),
                   "possibleExistingConcerts": sum(x.get("possibleExistingConcert", False) for x in classified),
                   "requiresHumanOrIndependentVerification": len(candidates),
                   "officiallyConfirmedNewMetalConcerts": 0},
        "triageCounts": triage_counts,
        "shortlistReviewCount": len(shortlist),
        "candidates": classified[:1000],
        "notes": ["Aucun candidat n'est publiable sans confirmation indépendante de date, genre, artistes, salle, et contrôle de festival.",
                  "Les salles P2 sont contrôlées par rotation. Une salle sans données structurées nécessite un collecteur adapté.",
                  "Le résultat ne modifie ni les catalogues ni GitHub Pages ni le WebFTP."],
    }
    (dest / "candidates.json").write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (dest / "shortlist.json").write_text(json.dumps({
        "schema": "grossesondes.concert.shortlist.v1",
        "generatedAt": review["generatedAt"],
        "count": len(shortlist), "publicationAllowed": False,
        "notes": [
            "Chaque ligne reste à revérifier auprès de sa salle et de la source originale.",
            "Les doublons et annulations sont des alertes, pas des concerts à ajouter.",
            "Le filtre de genre ne classe aucun événement comme confirmé automatiquement."
        ],
        "candidates": shortlist[:1000]
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = [
        "# Veille concerts — " + day.isoformat(),
        "",
        "Catalogue public de comparaison : " + str(len(catalog["events"])) + " événements.",
        "Salles inspectées : " + str(len(venues_checks)) + ".",
        "Pistes de salles (NON des concerts validés) : " + str(len(venue_candidates)) + ".",
        "Entrées ICS à confirmer : " + str(review["counts"]["datedIcsEntriesUnverified"]) + ".",
        "Pistes calendrier tiers à recouper (Secret Place) : " + str(len(partner_candidates)) + ".",
        "Alertes annulation ICS : " + str(review["counts"]["icsCancellationNotices"]) + ".",
        "Annonces RSS SANS date de concert : " + str(review["counts"]["rssUndatedAnnouncements"]) + ".",
        "Événements structurés à vérifier : " + str(review["counts"]["structuredEventLeads"]) + ".",
        "Classement des pistes (aucune confirmation automatique) :",
        *["  - " + bucket + " : " + str(total) for bucket, total in sorted(triage_counts.items())],
        "À examiner en priorité : " + str(len(shortlist)) + " (annulations, doublons, genre ou festival).",
        "Nouveaux concerts métal confirmés automatiquement : 0.",
        "Candidats Ticketmaster : " + str(len(api_candidates)) + ".",
        "Sondes Ticketmaster par salle : " + str(len(scoped_checks)) +
        ", salles trouvées avec identité exacte : " + str(sum(x.get("matchedVenueCount") == 1 for x in scoped_checks)) + ".",
        "Déjà probablement présents : " + str(review["counts"]["possibleExistingConcerts"]) + ".",
        "Publication : **interdite**.",
        "",
        "## Sources en erreur",
    ]
    summary.extend("- " + e["venue"] + " : " + e["error"] for e in venues_checks if e.get("error"))
    summary.extend("- Flux tiers " + str(e["source"]) + " : " + e["error"] for e in partner_checks if e.get("error"))
    summary += ["", "## Liste courte à examiner", ""]
    for entry in shortlist[:30]:
        summary.append("- " + (entry.get("date") or "sans date") + " — " +
                       entry.get("city", "?") + " — " + entry.get("name", "?") + " (" +
                       entry["reviewBucket"] + ") — " + entry.get("sourceUrl", "sans lien"))
    (dest / "rapport.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print("Veille terminée :", len(venue_candidates), "pistes salles /", len(partner_candidates), "pistes calendriers tiers /", len(api_candidates), "candidats Ticketmaster. Aucun déploiement.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
