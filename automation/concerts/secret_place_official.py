#!/usr/bin/env python3
"""Read-only official Secret Place (Tout À Fond) calendar cross-check.

Wix calendar cells sometimes omit the YEAR even when day and month are visible.
Never assert a dated concert or approve an event based on a calendar cell alone.
This process writes a review report only; third-party calendars remain leads.
"""
from __future__ import annotations
import argparse
import datetime as dt
from html.parser import HTMLParser
import json
import re
import unicodedata
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
from pathlib import Path

OFFICIAL = "https://www.toutafond.com/nos-evenements"
HOST = "www.toutafond.com"
MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
}
STOP = re.compile(r"\b(annul[eé]|report[eé]|blind.test|cours|atelier|"
                  r"masterclass|festival|open.air)\b", re.I)
DAY = re.compile(r"\b(\d{1,2})\s+(janvier|f[ée]vrier|mars|avril|mai|juin|"
                 r"juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre)\b", re.I)
HOUR = re.compile(r"\b(?:[01]\d|2[0-3]):[0-5]\d\b")


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or "")).casefold()
    value = value.encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", value))


class Calendar(HTMLParser):
    VOID = {"br", "img", "input", "meta", "link", "hr", "area"}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current = None
        self.depth = 0
        self.rows = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if self.current is not None:
            if tag not in self.VOID:
                self.depth += 1
            if tag == "a":
                href = values.get("href") or ""
                absolute = urljoin(OFFICIAL, href)
                parsed = urlsplit(absolute)
                if (parsed.scheme == "https" and parsed.hostname == HOST and
                    re.fullmatch(r"/event-details/[a-z0-9-]+/?", parsed.path) and
                    not parsed.query and not parsed.fragment):
                    self.current["detailUrls"].add(absolute)
            return
        label = values.get("aria-label") or ""
        if values.get("role") != "gridcell" or not DAY.search(label):
            return
        if not re.search(r"\b1\s+[eé]v[eé]nement\b", label, re.I):
            return
        self.current = {"label": label, "detailUrls": set(), "text": []}
        self.depth = 1

    def handle_endtag(self, tag):
        if self.current is None or tag in self.VOID:
            return
        self.depth -= 1
        if self.depth == 0:
            self.rows.append(self.current)
            self.current = None

    def handle_data(self, text):
        if self.current is not None:
            self.current["text"].append(text)


def parse_calendar(page):
    parser = Calendar()
    parser.feed(page)
    output = []
    for item in parser.rows:
        day = DAY.search(item["label"])
        if not day:
            continue
        mon = MONTHS.get(norm(day.group(2)))
        if not mon:
            continue
        text = " ".join(" ".join(item["text"]).split())
        clock = HOUR.search(text)
        if not clock:
            continue
        title = text[clock.end():].strip(" -–—:|")
        if len(title) < 4 or len(title) > 220 or STOP.search(title):
            continue
        urls = sorted(item["detailUrls"])
        output.append({
            "day": int(day.group(1)), "month": mon,
            "title": title, "time": clock.group(),
            "sourceUrl": urls[0] if len(urls) == 1 else OFFICIAL,
            "detailUrlConfirmed": len(urls) == 1,
            "yearConfirmed": False, "publicationAllowed": False,
            "reviewRequired": True,
        })
    return output


def crosscheck(calendar, registry):
    """Corroborate month/day and lineup without guessing an official year."""
    candidates = [r.get("candidate") or {} for r in registry.get("items", {}).values()]
    matches = []
    for item in calendar:
        found = []
        title = norm(item["title"])
        for c in candidates:
            if norm(c.get("venue")) != "secret place" or not c.get("date"):
                continue
            try:
                date = dt.date.fromisoformat(c["date"])
            except (ValueError, TypeError):
                continue
            if date.month != item["month"] or date.day != item["day"]:
                continue
            other = norm(c.get("name"))
            # At least a named headliner; generic words never establish a match.
            if len(title) >= 12 and (title == other or
                                     other.startswith(title + " ") or
                                     title.startswith(other + " ")):
                found.append(c.get("candidateId"))
        matches.append({
            **item, "corroboratingCandidateIds": sorted(set(x for x in found if x)),
            "status": "official_day_month_title_corrob" if found else "official_calendar_lead",
            "note": "Année non établie par la seule cellule Wix : recoupement nécessaire.",
        })
    return matches


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    try:
        req = Request(OFFICIAL, headers={"User-Agent": "GrossesOndesConcertWatch/0.1 (discovery only)"})
        with urlopen(req, timeout=19) as response:
            if urlsplit(response.geturl()).hostname != HOST:
                raise ValueError("Redirection hors site officiel")
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("Calendrier volumineux")
        rows = parse_calendar(raw.decode("utf-8", errors="replace"))
        status = "read_only_success" if rows else "official_calendar_not_extractable"
    except Exception as e:
        rows, status = [], "official_calendar_unavailable:" + type(e).__name__
    compared = crosscheck(rows, registry)
    result = {
        "schema": "grossesondes.concert.secretplace.review.v1",
        "officialCalendar": OFFICIAL, "status": status,
        "publicationAllowed": False, "yearConfirmed": False,
        "calendarLeads": len(compared),
        "crosschecked": sum(bool(x["corroboratingCandidateIds"]) for x in compared),
        "events": compared,
        "notes": "Rapport privé uniquement. Aucune date d'année, programmation, genre ou approbation déduite du calendrier seul."
    }
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k not in ("events","notes")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
