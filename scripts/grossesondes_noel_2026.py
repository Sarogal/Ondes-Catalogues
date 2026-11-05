"""Pinned editorial approval of the four Festival de Noël XXXIV 2026 sessions.

No raw private patch or untrusted organizer URL can change a public field.
Each candidate must be re-proved against the pre-approved organizer homepage
and four distinct municipal culture pages. A missing source holds the patch.
"""
from datetime import date
from html.parser import HTMLParser
import re
import unicodedata

PROOF_MODE = "official-noel-sessions.v1"
SLUG = "festival-de-noel-xxxiv-2026"
ORGANIZER_URL = "https://execution-mgt.fr/"
MUNICIPAL_URLS = {
    "2026-12-11": "https://sortir.limoges.fr/agenda/festival-de-noel-xxxiv",
    "2026-12-12": "https://sortir.limoges.fr/agenda/festival-de-noel-xxxiv-0",
    "2026-12-18": "https://sortir.limoges.fr/agenda/festival-de-noel-xxxiv-1",
    "2026-12-19": "https://sortir.limoges.fr/agenda/festival-de-noel-xxxiv-2",
}
# Official organizer ticketing references used as documentary audit links.
# Their HTTP accessibility is NEVER interpreted as a stock indication.
TICKET_URLS = {
    "2026-12-11": "https://www.helloasso.com/associations/association-execution-mgt/evenements/festival-de-noel-xxxiv-jour-1-pussy-miel-sex-shop-m-one-burning-m-emprise",
    "2026-12-12": "https://www.helloasso.com/associations/association-execution-mgt/evenements/festival-de-noel-xxxiv-jour2-monkey-on-mars-monkey-3-mars-red-sky-goathfather",
    "2026-12-18": "https://www.helloasso.com/associations/association-execution-mgt/evenements/festival-de-noel-xxxiv-jour-3-houle-alta-rossa-galibot-messalina-les-batards",
    "2026-12-19": "https://www.helloasso.com/associations/association-execution-mgt/evenements/festival-de-noel-xxxiv-jour-4-revnoir-ashen-wake-the-dead-jiro",
}
PROOF_SOURCES = {"noel_organizer": ORGANIZER_URL, **{
    "noel_city_" + day: url for day, url in MUNICIPAL_URLS.items()
}}
GROUPS = {
    "2026-12-11": ["Pussy Miel", "Sex Shop Mushrooms", "One Burning Match", "Emprise"],
    "2026-12-12": ["Monkeys on Mars", "Mars Red Sky", "Monkey3", "Goatfather"],
    "2026-12-18": ["Houle", "Alta Rossa", "Galibot", "Messalina", "Les Bâtards du Roi"],
    "2026-12-19": ["Revnoir", "Ashen", "Wake the Dead", "Jiro"],
}
NOTE = (
    "34e édition au CCM John-Lennon de Limoges, en quatre soirées distinctes "
    "les 11, 12, 18 et 19 décembre 2026. La répartition des 17 artistes dans "
    "lineupByDate est documentée par les annonces d'EXECUTION Mgt et corroborée "
    "par les programmes des Centres culturels de Limoges. Pas de concert annoncé "
    "les 13–17 décembre. Pass quatre soirées à 70 € ; gratuit moins de 15 ans. "
    "La disponibilité actuelle des billets n'est pas certifiée. Red Gordon figure "
    "sur certains programmes institutionnels, mais pas dans la billetterie "
    "organisateur de la dernière soirée : participation à revalider, sans ajout."
)
STATUS = (
    "Quatre soirées et répartition des 17 artistes par date corroborées ; "
    "Red Gordon à revalider ; disponibilité des billets non vérifiée."
)
FIELDS = {"officialSite", "notes", "verificationStatus", "auditSources", "lastVerified"}


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "svg", "noscript"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "svg", "noscript"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden and len(self.text) < 16000:
            self.text.append(data)


def norm(text):
    v = str(text).casefold()
    v = unicodedata.normalize("NFKD", v)
    v = "".join(char for char in v if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", v))


def visible(html):
    if not isinstance(html, str) or not 100 <= len(html) <= 1_400_000:
        return ""
    parser = Text()
    parser.feed(html)
    return norm(" ".join(parser.text))


def present(document, phrase):
    return re.search(r"(?<![a-z0-9])" + re.escape(norm(phrase)) +
                     r"(?![a-z0-9])", document) is not None


def expected_sources(original):
    return list(dict.fromkeys(original.get("auditSources", []) +
                              [ORGANIZER_URL] +
                              list(MUNICIPAL_URLS.values()) +
                              list(TICKET_URLS.values())))


def noel_2026_update(original, update, sources, today):
    """Returns a strictly limited field update or None. Never guesses stock."""
    if not (isinstance(original, dict) and original.get("slug") == SLUG
            and isinstance(update, dict) and update.get("slug") == SLUG
            and update.get("proofMode") == PROOF_MODE):
        return None
    if not (original.get("officialSite") is None
            and original.get("organizer") == "Association EXECUTION Mgt"
            and original.get("startDate") == "2026-12-11"
            and original.get("endDate") == "2026-12-19"
            and original.get("dateRangeIsContinuous") is False
            and original.get("sessionDates") == list(GROUPS)
            and original.get("lineupByDate") == GROUPS
            and original.get("lineup") ==
                [artist for groups in GROUPS.values() for artist in groups]
            and original.get("bands") == 17):
        return None
    changes = update.get("changes")
    if not isinstance(changes, list) or len(changes) != len(FIELDS):
        return None
    fields = {item.get("field"): item for item in changes
              if isinstance(item, dict)}
    if set(fields) != FIELDS or len(fields) != len(changes):
        return None
    try:
        verified_at = date.fromisoformat(fields["lastVerified"]["after"])
        first = date.fromisoformat(original["lastVerified"])
        now = date.fromisoformat(today)
        if not first <= verified_at <= now:
            return None
    except (ValueError, TypeError, KeyError):
        return None
    desired = {
        "officialSite": ORGANIZER_URL,
        "notes": NOTE,
        "verificationStatus": STATUS,
        "auditSources": expected_sources(original),
        "lastVerified": verified_at.isoformat(),
    }
    for key, change in fields.items():
        if (key not in original or "before" not in change
                or "after" not in change
                or change["before"] != original[key]
                or change["after"] != desired[key]):
            return None
    # All provenance is fixed in this validator. An attacker's evidence list
    # cannot redirect or replace any live re-fetch.
    evidence = update.get("evidence")
    if (not isinstance(evidence, list) or not all(isinstance(u, str) for u in evidence)
            or len(evidence) != len(set(evidence))
            or set(evidence) != set(PROOF_SOURCES.values()) | set(TICKET_URLS.values())):
        return None
    homepage = visible(sources.get("noel_organizer", ""))
    if not (present(homepage, "34 festival de noel")
            and "execution" in homepage and "2026" in homepage):
        return None
    municipal = {}
    for day, groups in GROUPS.items():
        raw = sources.get("noel_city_" + day)
        body = visible(raw)
        if not (present(body, "festival de noel xxxiv")
                and present(body, "jour " + str(list(GROUPS).index(day) + 1))
                and present(body, day[-2:] + " dec")
                and "execution mgt" in body):
            return None
        if not all(present(body, group) for group in groups):
            return None
        municipal[day] = body
    # The municipal venue/organizer link is an independent association
    # between the domain and EXECUTION Mgt. It must appear in at least one
    # independently fetched page, not only in the proposed JSON.
    if not any("execution-mgt.fr" in sources.get("noel_city_" + day, "").lower()
               for day in GROUPS):
        return None
    revised = dict(original)
    revised.update(desired)
    return revised, sorted(FIELDS), []
