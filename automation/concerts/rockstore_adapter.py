"""Rockstore Montpellier: bounded first-party concert-detail discovery, review only.

The public /concerts/ agenda is a link index; the dated, individually tagged
official detail is mandatory. The displayed clock is not guaranteed to be a
show start time. Never infer it, publish automatically, or geocode.
"""
from __future__ import annotations

import datetime as dt
from html import unescape
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin, urlsplit


AGENDA = "https://rockstore.fr/concerts/"
HOSTS = {"rockstore.fr", "www.rockstore.fr"}
MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12
}
PATH = re.compile(
    r"^/([a-z0-9][a-z0-9-]{2,160})-(0?[1-9]|[12]\d|3[01])-"
    r"(janvier|fevrier|mars|avril|mai|juin|juillet|aout|"
    r"septembre|octobre|novembre|decembre)-(20\d{2})/?$"
)
FULL_DATE = re.compile(
    r"\b(\d{1,2})(?:er)?\s+(janvier|fevrier|mars|avril|mai|juin|"
    r"juillet|aout|septembre|octobre|novembre|decembre)\s+(20\d{2})\b"
)
# 'Rock' alone may mean mainstream pop-rock, so it is deliberately insufficient.
GENRE = re.compile(
    r"(?<![a-z])(?:metal|punk|hardcore|stoner|doom|sludge|thrash|grunge|"
    r"metalcore|deathcore|shoegaze|post[- ]rock|hard[- ]rock|"
    r"rock alternatif|rock indus|noise rock|garage rock)(?![a-z])"
)
INVALID = re.compile(
    r"\b(?:annule|annulee|reporte|reportee|deplace|deplacee|"
    r"cancelled|canceled|postponed)\b"
)


def fold(value):
    return unicodedata.normalize(
        "NFKD", unescape(str(value)).casefold()
    ).encode("ascii", "ignore").decode("ascii")


def detail_identity(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in HOSTS
            or parsed.query or parsed.fragment or parsed.port
            or parsed.username or parsed.password):
        return None
    match = PATH.fullmatch(parsed.path)
    if not match:
        return None
    try:
        date = dt.date(int(match[4]), MONTHS[match[3]], int(match[2]))
    except ValueError:
        return None
    return date, match[1]


class _Html(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.visible = []
        self.in_h1 = False
        self.heading = []
        self.heading_end = None
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ("head", "script", "style", "nav", "footer"):
            self.hidden += 1
        if tag == "a":
            for key, value in attrs:
                if key.lower() == "href" and value:
                    self.links.append(value)
        if tag == "h1" and not self.hidden and self.heading_end is None:
            self.in_h1 = True

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "h1" and self.in_h1:
            self.in_h1 = False
            self.heading_end = len(self.visible)
        if tag in ("head", "script", "style", "nav", "footer") and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if self.hidden:
            return
        value = " ".join(data.split())
        if value:
            self.visible.append(value)
            if self.in_h1:
                self.heading.append(value)


def detail_urls(html, listing_url, today, horizon_days=365):
    base = urlsplit(listing_url)
    if (base.scheme != "https" or base.hostname not in HOSTS
            or base.path.rstrip("/") != "/concerts"):
        raise ValueError("Official Rockstore concert agenda required")
    today = dt.date.fromisoformat(today)
    parser = _Html()
    parser.feed(html)
    urls = set()
    for href in parser.links:
        url = urljoin(listing_url, href)
        ident = detail_identity(url)
        if ident and today <= ident[0] <= today + dt.timedelta(days=horizon_days):
            urls.add(url)
    return sorted(urls, key=lambda url: (detail_identity(url)[0], url))



def selected_details(urls, known, today, limit=12, priority_days=45):
    """Rotate near-future and later first-party leads, prioritizing new URLs.

    A fixed list of the first five concerts repeatedly re-fetched pop/club
    listings on the daily Rockstore run. Split the available budget into
    8 imminent dates and 4 later ones, rotating both daily.
    """
    day = dt.date.fromisoformat(today)
    limit = max(1, min(14, int(limit)))
    cutoff = day + dt.timedelta(days=priority_days)
    unique = sorted(set(urls), key=lambda u: (detail_identity(u)[0], u)
                    if detail_identity(u) else (dt.date.max, u))
    valid = [url for url in unique if
             (ident := detail_identity(url)) and
             day <= ident[0] <= day + dt.timedelta(days=365)]
    near = [u for u in valid if detail_identity(u)[0] <= cutoff and
            ("officialUrl", u) not in known]
    far = [u for u in valid if detail_identity(u)[0] > cutoff and
           ("officialUrl", u) not in known]
    seen = [u for u in valid if ("officialUrl", u) in known]

    def take(pool, amount):
        if not pool or amount <= 0:
            return []
        k = min(amount, len(pool))
        offset = (day.toordinal() * max(1, k)) % len(pool)
        return [pool[(offset + i) % len(pool)] for i in range(k)]

    near_quota = min(8, limit)
    chosen = take(near, near_quota)
    chosen.extend(take(far, limit - len(chosen)))
    if len(chosen) < limit:
        remaining_near = [u for u in near if u not in chosen]
        chosen.extend(take(remaining_near, limit - len(chosen)))
    if len(chosen) < limit:
        remaining_far = [u for u in far if u not in chosen]
        chosen.extend(take(remaining_far, limit - len(chosen)))
    if len(chosen) < limit:
        chosen.extend(take(seen, limit - len(chosen)))
    return chosen

def detail_candidate(html, url, source, today):
    ident = detail_identity(url)
    day = dt.date.fromisoformat(today)
    if ident is None or not day <= ident[0] <= day + dt.timedelta(days=365):
        raise ValueError("Out-of-range or non-official Rockstore detail")
    if (source.get("name") != "Rockstore" or
            source.get("city") != "Montpellier"):
        raise ValueError("Unexpected venue identity")
    page = _Html()
    page.feed(html)
    if not page.heading or page.heading_end is None:
        raise ValueError("No individual concert heading")
    title = " ".join(page.heading)
    after = page.visible[page.heading_end:]
    if not 3 <= len(title) <= 210 or len(after) < 2:
        raise ValueError("Insufficient event evidence")
    # The source prints a full year-qualified French date immediately below
    # the event heading. Biography dates are not acceptable alternatives.
    date_line = fold(after[0])
    dates = []
    for dd, mm, yyyy in FULL_DATE.findall(date_line):
        try:
            dates.append(dt.date(int(yyyy), MONTHS[mm], int(dd)))
        except ValueError:
            raise ValueError("Invalid detailed event date") from None
    if dates != [ident[0]]:
        raise ValueError("URL date and first-party event date differ")
    genre = after[1].strip()
    if not 2 <= len(genre) <= 80 or not GENRE.search(fold(genre)):
        raise ValueError("Genre is not independently tagged rock/metal/punk")
    if INVALID.search(fold(" ".join(after[:6]))):
        raise ValueError("Postponed, moved or cancelled event")
    if re.search(r"\b(?:dj set|club night|afterparty)\b", fold(title)):
        raise ValueError("Club night is not verified as a gig")
    lead = re.split(r"\s+\+\s+", title, maxsplit=1)[0].strip()
    return {
        "candidateId": f"rockstore:{ident[0].isoformat()}:{ident[1]}",
        "date": ident[0].isoformat(),
        "name": title, "leadArtist": lead,
        "venue": "Rockstore", "city": "Montpellier", "department": "34",
        "classification": [genre], "genreEvidence": "official_detail_genre",
        "genreToConfirm": True,
        "source": "agenda_officiel_rockstore_detail_review",
        "sourcePage": source["url"], "sourceUrl": url,
        "sourceConfidence": (
            "Fiche officielle Rockstore: date complète concordante avec URL, "
            "titre et genre explicite. Horaire non publié comme début certain."),
        "officialDetailFound": True, "localTime": None,
        "publicationAllowed": False, "reviewRequired": True,
        "geoReviewRequired": True,
    }
