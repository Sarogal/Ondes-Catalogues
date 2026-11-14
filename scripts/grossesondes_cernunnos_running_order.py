"""Bounded, first-party recheck of Cernunnos 2027 day-by-day artists.

A public stage may add ONLY five explicitly named artists confirmed on BOTH
pinned 2027 organizer pages, after checking the existing 20 published artists
against the dated running order. This never infers an unnamed surprise act.
No private patch, new domain, geolocation or calendar date can influence it.
"""
from datetime import date
from html.parser import HTMLParser
import re

from grossesondes_field_proof import normalize

RUNNING_ORDER_URL = "https://www.cernunnospaganfest.fr/running-order/"
GROUPS_URL = "https://www.cernunnospaganfest.fr/groupes/"
EVENT_SLUG = "cernunnos-pagan-fest"
OLD_LINEUP = (
    "Adfeilion", "Arthuan Rebis Trio", "Domhain", "Einherjer",
    "Fejd", "Firemage", "Maruna", "Morgarten", "Ondfødt",
    "Rhesus", "Saor", "Svartsot", "Trold", "Uttern",
    "XIV Dark Centuries", "Ydhessä", "Glyphe", "Askemåne",
    "Keltania", "Ruadh",
)
NEW_LINEUP = ("Albaluna", "Lili Refrain", "Vreid", "Waldkauz", "Fianna Bán")
DAYS = {
    "2027-02-12": (
        "Einherjer", "Saor", "Albaluna", "Ondfødt", "Askemåne", "Glyphe",
    ),
    "2027-02-13": (
        "Lili Refrain", "Fejd", "XIV Dark Centuries",
        "Arthuan Rebis Trio", "Firemage", "Uttern", "Domhain",
        "Keltania", "Ydhessä", "Adfeilion",
    ),
    "2027-02-14": (
        "Vreid", "Svartsot", "Waldkauz", "Rhesus", "Morgarten",
        "Maruna", "Trold", "Fianna Bán", "Ruadh",
    ),
}
MARKERS = (
    "vendredi 12 fevrier", "samedi 13 fevrier", "dimanche 14 fevrier",
)
FIELDS = (
    "lineup", "bands", "lineupByDate", "notes", "verificationStatus",
    "sourceConfidence", "auditSources", "lastVerified",
)


class VisibleOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg", "template"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg", "template"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, value):
        if not self.hidden:
            self.parts.append(value)


def _visible(html):
    if not isinstance(html, str) or not 0 < len(html) <= 1_400_000:
        return ""
    parser = VisibleOnly()
    parser.feed(html)
    return normalize(" ".join(parser.parts))


def _has_word(section, title):
    value = normalize(title)
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(value)
                          + r"(?![a-z0-9])", section))


def _official_day_sections(text):
    if not ("repartion des groupes pour 2027" in text
            or "repartition des groupes pour 2027" in text):
        return None
    if "running order cernunnos2027" not in text:
        return None
    found = [list(re.finditer(r"(?<![a-z0-9])" + re.escape(heading)
                              + r"(?![a-z0-9])", text))
             for heading in MARKERS]
    # Refuse ambiguous 2026 menus or multiple copies of a day heading.
    if any(len(x) != 1 for x in found):
        return None
    spans = [x[0] for x in found]
    if not (spans[0].start() < spans[1].start() < spans[2].start()):
        return None
    sections = (
        text[spans[0].end():spans[1].start()],
        text[spans[1].end():spans[2].start()],
        text[spans[2].end():spans[2].end()+1000],
    )
    # Bounded checks avoid accidentally matching footer or previous seasons.
    if any(len(s) > 1600 or len(s) < 25 for s in sections):
        return None
    return sections


def revalidate(entry, running_html, groups_text, today):
    """Return a new, safely enriched published row or None. Never mutate."""
    if (not isinstance(entry, dict)
            or entry.get("slug") != EVENT_SLUG
            or entry.get("officialSite") != "https://www.cernunnospaganfest.fr/"
            or entry.get("startDate") != "2027-02-12"
            or entry.get("endDate") != "2027-02-14"
            or entry.get("status") != "Confirmé"
            or not isinstance(groups_text, str)):
        return None
    try:
        now = date.fromisoformat(today)
    except (TypeError, ValueError):
        return None
    if not date(2026, 11, 1) <= now <= date(2027, 2, 14):
        return None
    old = list(OLD_LINEUP)
    complete = old + list(NEW_LINEUP)
    existing = entry.get("lineup")
    if not (existing == old or existing == complete):
        return None
    if entry.get("bands") != len(existing):
        return None
    # Current-edition heading is mandatory for the independently fetched
    # groups page; 2026 performer bios elsewhere are not sufficient.
    groups = normalize(groups_text)
    if not ("les groupes de l edition 2027" in groups
            and "lineup cernunnos2027" in groups
            and all(_has_word(groups, name) for name in NEW_LINEUP)):
        return None
    text = _visible(running_html)
    sections = _official_day_sections(text)
    if sections is None:
        return None
    expected = [name for day in DAYS.values() for name in day]
    if (len(expected) != len(complete)
            or {normalize(x) for x in expected} != {normalize(x) for x in complete}):
        return None
    # Every name must occur in exactly its assigned day's current-edition
    # section, not just in the page header, JS, or a retrospective.
    for i, names in enumerate(DAYS.values()):
        for name in names:
            if not _has_word(sections[i], name):
                return None
            if any(_has_word(sections[j], name) for j in range(3) if j != i):
                return None
    by_date = {day: list(names) for day, names in DAYS.items()}
    if existing == complete and entry.get("lineupByDate") == by_date:
        return None  # Idempotent: no artificial daily generatedAt updates.
    updated = dict(entry)
    updated["lineup"] = complete
    updated["bands"] = len(complete)
    updated["lineupByDate"] = by_date
    updated["notes"] = (
        "Cernunnos Pagan Fest 2027 à la Ferme du Buisson, Noisiel, "
        "du 12 au 14 février. 25 artistes nommés et répartis par "
        "journée sur le running order officiel 2027 ; un invité surprise "
        "est annoncé sans nom et n'est pas compté. "
        "Les horaires individuels restent à confirmer."
    )
    updated["verificationStatus"] = (
        "25 artistes 2027 identifiés sur les pages officielles ; "
        "répartition par journée vérifiée, horaires encore inconnus."
    )
    updated["sourceConfidence"] = (
        "Programmation et jours observés sur les pages officielles "
        "running-order et groupes ; aucune déduction depuis 2026."
    )
    updated["auditSources"] = list(dict.fromkeys(
        entry.get("auditSources", []) + [GROUPS_URL, RUNNING_ORDER_URL]
    ))
    updated["lastVerified"] = today
    return updated
