"""Conservative, source-specific parsing of official family-venue schedules.

Every output is an unverified PRIVATE lead. This module is NOT a publisher.
No opening-hour, season, unspecified weekday or adult-only item is a session.
"""
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
import re
import unicodedata
from zoneinfo import ZoneInfo

MONTHS = ("janvier", "fevrier", "mars", "avril", "mai", "juin",
          "juillet", "aout", "septembre", "octobre", "novembre", "decembre")
WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
PARIS = ZoneInfo("Europe/Paris")


def norm(s):
    raw = unicodedata.normalize("NFKD", str(s or "").lower())
    return " ".join(re.sub(r"[^a-z0-9]+", " ", "".join(
        c for c in raw if not unicodedata.combining(c))).split())


def time_value(h, m):
    h, m = int(h), int(m or 0)
    if h > 23 or m > 59:
        raise ValueError("Heure invalide")
    return f"{h:02d}:{m:02d}"


def times_written(text):
    """Return starts only; 'de 10h à 12h' is ONE session, not two."""
    s = norm(text)
    # norm removes the 'h' separator before regex, so normalize from raw first.
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    range_ = re.search(r"\bde\s+(\d{1,2})h(\d{0,2})\s+a\s+(\d{1,2})h(\d{0,2})\b", plain)
    if range_:
        start = time_value(range_.group(1), range_.group(2))
        end = time_value(range_.group(3), range_.group(4))
        return [start] if start < end else []
    double = re.search(r"\ba\s+(\d{1,2})h(\d{0,2})\s+et\s+(?:a\s+)?(\d{1,2})h(\d{0,2})\b", plain)
    if double:
        values = [time_value(double.group(1), double.group(2)),
                  time_value(double.group(3), double.group(4))]
        return list(dict.fromkeys(values))
    one = re.search(r"\ba\s+(\d{1,2})h(\d{0,2})\b", plain)
    return [time_value(one.group(1), one.group(2))] if one else []


class Sections(HTMLParser):
    """Only heading and paragraph content, not scripts/nav/hidden templates."""
    IGNORE = {"script", "style", "noscript", "nav", "footer", "header", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.tag = None
        self.buffer = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORE:
            self.hidden += 1
        if not self.hidden and tag in ("h1", "h2", "h3", "p", "li"):
            self.finish()
            self.tag = tag
            self.buffer = []

    def handle_endtag(self, tag):
        if not self.hidden and tag == self.tag:
            self.finish()
        if tag in self.IGNORE and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden and self.tag:
            self.buffer.append(data)

    def finish(self):
        if self.tag and self.buffer:
            value = " ".join(" ".join(self.buffer).split())
            if value:
                self.rows.append((self.tag, value))
        self.tag = None
        self.buffer = []


def _dated(year, month, day, weekday, today):
    try:
        d = date(year, month, day)
    except ValueError:
        return None
    if d.weekday() != WEEKDAYS.index(weekday):
        return None
    return d if today <= d <= today + timedelta(days=183) else None


def _candidate(source, title, day, start, age_note):
    clock = datetime.strptime(start, "%H:%M").time()
    stamp = datetime.combine(day, clock, tzinfo=PARIS).isoformat(timespec="minutes")
    return {
        "place_id": source["place_id"], "name": title,
        "start": stamp, "end": None, "source_url": source["url"],
        "status": "requires_independent_session_proof",
        "age_evidence": age_note,
        "extraction": "curated_official_schedule_v1",
    }


def montpellier_leads(source, html, today):
    rows = Sections()
    rows.feed(html)
    rows.finish()
    year, month = None, None
    output = []
    for index, (tag, text) in enumerate(rows.rows):
        if tag == "h2":
            m = re.fullmatch(r"([A-Za-zÀ-ÿ]+)\s+(20\d{2})", text.strip())
            monthname = norm(m.group(1)) if m else ""
            month = MONTHS.index(monthname) + 1 if monthname in MONTHS else None
            year = int(m.group(2)) if month else None
            continue
        if tag != "h3" or not year or not month:
            continue
        header = norm(text)
        # Require the month spelled out in THIS heading, never roll an opening
        # hour from another section forward to another date.
        if MONTHS[month - 1] not in header:
            continue
        dates = re.match(
            r"^(" + "|".join(WEEKDAYS) + r")\s+(\d{1,2})"
            r"(?:\s+et\s+(" + "|".join(WEEKDAYS) + r")\s+(\d{1,2}))?"
            r"\s+" + MONTHS[month - 1] + r"\b", header)
        if not dates:
            continue
        day1 = _dated(year, month, int(dates.group(2)), dates.group(1), today)
        day2 = (_dated(year, month, int(dates.group(4)), dates.group(3), today)
                if dates.group(3) else None)
        if day1 is None and day2 is None:
            continue
        section = []
        for following, paragraph in rows.rows[index + 1:]:
            if following in {"h2", "h3"}:
                break
            if following in {"p", "li"}:
                section.append(paragraph)
        if not section:
            continue
        full = norm(" ".join(section))
        # Enforce a child-specific audience in this exact event section.
        if not re.search(r"\bde\s+\d{1,2}\s+a\s+\d{1,2}\s+ans\b", full) and (
                "enfant qui vient de naitre" not in full):
            continue
        if any(bad in full for bad in ("chants prenataux", "pour les adultes et l enfant a venir",
                                      "annule", "reporte")):
            continue
        first = section[0].strip()
        # First paragraph contains the title or the distinctive activity name,
        # never derive an event's name from the season title.
        title = re.split(r"\s+(?:par|avec|propose|proposée)\s+", first,
                         maxsplit=1, flags=re.I)[0].strip(" :-,.")
        title = re.split(r"\s+à\s+\d{1,2}h", title, maxsplit=1,
                         flags=re.I)[0].strip()
        if not 5 <= len(title) <= 130:
            continue
        # Some headings announce just the day; individual times can occur in
        # the first paragraph (e.g. Opéra buissonnier).
        times = times_written(text) or times_written(first[:150])
        if not times or len(times) > 3:
            continue
        for day in (day1, day2):
            if day is not None:
                for clock in times:
                    output.append(_candidate(source, title, day, clock, "programme municipal"))
                    if len(output) >= 35:
                        return output
    return output


def toulouse_bebes_leads(source, html, today):
    rows = Sections()
    rows.feed(html)
    rows.finish()
    content = norm(" ".join(value for _, value in rows.rows))
    heading = next((v for tag, v in rows.rows if tag == "h1"), "")
    expected = "les bébés explorateurs : formes et matières"
    # Direct official programme for this one article, never assume its dates
    # carry forward into another programme or a weekly recurring event.
    if norm(expected) not in norm(heading):
        return []
    if not all(x in content for x in (
        "mediatheque jeunesse", "pourquoi pas", "gratuit",
        "de 0 a 3 ans", "novembre", "samedis")):
        return []
    if any(bad in content for bad in ("annule", "reporte")):
        return []
    year_match = re.search(r"\b(?:7\s+21|7\s+au\s+21)\s+novembre\s+(20\d{2})\b", content)
    session_match = re.search(
        r"\bsamedis\s+(\d{1,2})\s+et\s+(\d{1,2})\s+novembre\s+de\s+"
        r"(\d{1,2})h(\d{0,2})\s+a\s+(\d{1,2})h(\d{0,2})\b",
        unicodedata.normalize("NFKD", " ".join(v for _, v in rows.rows).lower())
        .replace("\u0301", "").replace("\u0300", ""),
    )
    if not year_match or not session_match:
        return []
    # Pin the start/end days of this explicit two-date schedule to the year
    # in the institution's independently titled programme header.
    first, last = int(session_match.group(1)), int(session_match.group(2))
    if (first, last) != (7, 21):
        return []
    start = time_value(session_match.group(3), session_match.group(4))
    finish = time_value(session_match.group(5), session_match.group(6))
    if start >= finish:
        return []
    result = []
    for day in (first, last):
        d = _dated(int(year_match.group(1)), 11, day, "samedi", today)
        if d is not None:
            result.append(_candidate(source, "Les bébés explorateurs : formes et matières",
                                     d, start, "0 à 3 ans selon l'organisateur"))
    return result


def curated_leads(source, html, today):
    if source["id"] == "montpellier-mille-formes-programme":
        return montpellier_leads(source, html, today)
    if source["id"] == "toulouse-pourquoi-pas-bebes-explorateurs":
        return toulouse_bebes_leads(source, html, today)
    return []
