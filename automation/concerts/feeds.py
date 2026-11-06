"""Connecteurs prudents ICS et RSS/Atom pour les agendas officiels.
Chaque sortie est une piste NON PUBLIABLE, jamais un concert vérifié.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import html
import html.parser
import re
import urllib.parse
import xml.etree.ElementTree as ET


class Feeds(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = {"ics": [], "rss": []}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        href = a.get("href", "")
        if not href:
            return
        low = href.lower()
        typ = a.get("type", "").lower()
        if tag == "link" and ("rss" in typ or "atom" in typ):
            self.links["rss"].append(href)
        if ("text/calendar" in typ or low.split("?")[0].endswith(".ics") or
                ("ical" in low and tag == "a")):
            self.links["ics"].append(href)


def comment_feed(url):
    """WordPress discussion replies are not concert news; do not harvest them."""
    path = urllib.parse.urlsplit(url).path.casefold().rstrip("/")
    return path.endswith("/comments/feed") or "/comment-page-" in path


def feed_links(page, source, same_host):
    """N'accepte que des liens https du même hôte, jamais un tiers par inférence."""
    p = Feeds()
    p.feed(page)
    feeds = {}
    for typ, links in p.links.items():
        valid = []
        for link in links:
            if link.startswith("webcal://"):
                link = "https://" + link[len("webcal://"):]
            absolute = urllib.parse.urljoin(source, link).split("#")[0]
            if (absolute not in valid and same_host(absolute, source)
                    and not (typ == "rss" and comment_feed(absolute))):
                valid.append(absolute)
        feeds[typ] = valid[:2]
    return feeds


def unfold_ics(body):
    lines = []
    for line in body.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.startswith((" ", "\t")) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def ics_unescape(text):
    return (text.replace("\\n", " ").replace("\\N", " ")
            .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\"))


def nonconcert_title(title):
    import unicodedata
    plain = unicodedata.normalize("NFKD", str(title).casefold()).encode("ascii","ignore").decode()
    return bool(re.search(r"\b(atelier|conference|formation|masterclass|reunion|blind.test|vernissage|stage|webinaire|portes.ouvertes)\b", plain))


def cancelled_title(title):
    import unicodedata
    plain = unicodedata.normalize("NFKD", str(title).casefold()).encode("ascii","ignore").decode()
    return bool(re.search(r"\b(annule|annulee|annulation|cancelled|canceled|reporte|reportee|postponed)\b", plain))


def ics_candidates(body, venue, source_url, day, limit=100):
    if len(body) > 2_000_000:
        return []
    found = []
    raw = None
    for line in unfold_ics(body):
        if line == "BEGIN:VEVENT":
            raw = {}
        elif line == "END:VEVENT":
            if raw:
                title = raw.get("SUMMARY", "").strip()
                date_field = raw.get("DTSTART", "")
                date_match = re.match(r"^(\d{4})(\d{2})(\d{2})(?:T\d{6}(?:Z)?)?$", date_field)
                date = None
                if date_match:
                    try:
                        date = dt.date(*map(int, date_match.groups())).isoformat()
                    except ValueError:
                        pass
                if date and date >= day and title and not raw.get("RRULE") and not nonconcert_title(title):
                    uid = raw.get("UID", title + date)
                    digest = hashlib.sha256((uid + "|" + date + "|" + source_url).encode()).hexdigest()[:20]
                    found.append({
                        "candidateId": "ics:" + digest, "source": "agenda_ics",
                        "sourceUrl": source_url, "date": date, "name": title,
                        "leadArtist": title, "venue": venue["name"], "city": venue["city"],
                        "department": venue.get("department"),
                        "locationAsAnnounced": raw.get("LOCATION") or None,
                        "genreToConfirm": True, "reviewRequired": True,
                        "possibleExistingConcert": False, "publicationAllowed": False,
                        "sourceConfidence": "ICS de salle : présence et genre à confirmer"
                    })
                    if raw.get("STATUS", "").upper() == "CANCELLED" or cancelled_title(title):
                        found[-1]["source"] = "ics_cancellation_notice"
                        found[-1]["cancellationNotice"] = True
                        found[-1]["leadOnly"] = True
                        found[-1]["reviewType"] = "cancellation_not_new_concert"
                    if len(found) >= limit:
                        break
            raw = None
        elif raw is not None and ":" in line:
            key, value = line.split(":", 1)
            key = key.split(";", 1)[0].upper()
            if key in ("DTSTART", "SUMMARY", "STATUS", "UID", "LOCATION", "RRULE"):
                raw[key] = ics_unescape(value)
    return found


def rss_candidates(body, venue, source_url, limit=35):
    """RSS/Atom fournit des annonces, PAS une date de concert."""
    if len(body) > 2_000_000 or comment_feed(source_url):
        return []
    root = ET.fromstring(body)
    items = list(root.findall(".//item"))
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    result = []
    for item in items[:limit]:
        title = (item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
        if not title:
            continue
        url = (item.findtext("link") or "").strip()
        if not url:
            l = item.find("{http://www.w3.org/2005/Atom}link")
            url = l.attrib.get("href", "") if l is not None else ""
        if url and not url.startswith("https://"):
            url = ""
        # A general news feed can still contain imported comment replies.
        # Never turn them into artist leads, even when a feed URL is valid.
        title_norm = re.sub(r"\s+", " ", html.unescape(title).casefold()).strip()
        if (title_norm.startswith(("commentaires sur ", "comment on ", "comments on "))
                or (url and ("#comment-" in url.casefold()
                             or "replytocom=" in url.casefold()))):
            continue
        digest = hashlib.sha256((title + "|" + (url or source_url)).encode()).hexdigest()[:20]
        result.append({
            "candidateId": "rss:" + digest, "source": "actualite_rss_non_datee",
            "sourceUrl": url or source_url, "sourceFeed": source_url,
            "date": None, "name": html.unescape(title), "leadArtist": "",
            "venue": venue["name"], "city": venue["city"],
            "department": venue.get("department"),
            "genreToConfirm": True, "reviewRequired": True,
            "possibleExistingConcert": False, "publicationAllowed": False,
            "leadOnly": True,
            "sourceConfidence": "Actualité RSS : la date de publication NE PROUVE PAS une date de concert"
        })
    return result
