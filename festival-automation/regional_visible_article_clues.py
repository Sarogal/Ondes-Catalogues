"""Visible, linkless event-card observations from curator-approved regional indexes.

A visible article without an HTML event link can be a research lead, but never
a URL to fetch, a confirmed festival, a date, or a public edition. No scripts,
JSON-LD or DOM-provided URLs enter this pipeline.
"""
from datetime import date
from hashlib import sha256
from html.parser import HTMLParser
import re

from source_qualification import normalized

STATUS = "UNVERIFIED_VISIBLE_ARTICLE"
MAX_HTML = 650_000
MAX_ARTICLES = 70
MAX_CARD_TEXT = 750
MAX_PENDING = 100
MAX_AGE_DAYS = 45
MAX_NEW_PER_PASS = 12
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr"}
HIDDEN = {"script", "style", "svg", "noscript", "template", "iframe"}
HEADINGS = {"h1", "h2", "h3", "h4"}
MUSIC = re.compile(
    r"\b(?:metal|heavy metal|death metal|black metal|hard rock|"
    r"punk|hardcore|rock|stoner|doom|sludge|grindcore|metalcore|"
    r"post rock|post metal|thrash)\b")
GENRE = re.compile(
    r"\b(?:genre|genres|categorie|categories|musique|programmation)"
    r" (?:de |du |en )?(?:metal|rock|punk|hardcore|hard rock|"
    r"stoner|doom|sludge|grindcore|metalcore)\b")
FEST = re.compile(r"\b(?:fest|festival)\b")
NOT_MUSIC = re.compile(
    r"\b(?:cinema|film|films|livre|livres|litterature|"
    r"photographie|theatre|gastronomie|moto|sports?|science|bd)\b")
YEAR = re.compile(r"\b20[2-4]\d\b")


class VisibleArticles(HTMLParser):
    """Read at most 70 visible <article> cards, with a local heading only."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.active = None
        self.heading_depth = None
        self.cards = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        options = dict(attrs)
        concealed = ((self.stack and self.stack[-1][1])
                     or tag in HIDDEN or "hidden" in options
                     or options.get("aria-hidden") == "true"
                     or "display:none" in (options.get("style") or
                                            "").replace(" ", "").lower())
        if tag not in VOID:
            self.stack.append((tag, bool(concealed)))
        if concealed or len(self.cards) >= MAX_ARTICLES:
            return
        if tag == "article" and self.active is None:
            self.active = {"depth": len(self.stack), "heading": [],
                           "text": [], "anchors": 0}
        elif self.active is not None:
            if tag == "a":
                self.active["anchors"] += 1
            elif tag in HEADINGS and self.heading_depth is None:
                self.heading_depth = len(self.stack)

    def handle_data(self, data):
        if self.active is None or (self.stack and self.stack[-1][1]):
            return
        if sum(map(len, self.active["text"])) < MAX_CARD_TEXT:
            self.active["text"].append(data[:MAX_CARD_TEXT])
        if (self.heading_depth is not None
                and len(self.stack) >= self.heading_depth
                and sum(map(len, self.active["heading"])) < 180):
            self.active["heading"].append(data[:180])

    def handle_endtag(self, tag):
        tag = tag.lower()
        idx = next((i for i in range(len(self.stack)-1, -1, -1)
                    if self.stack[i][0] == tag), None)
        if idx is None:
            return
        if self.heading_depth is not None and idx < self.heading_depth:
            self.heading_depth = None
        if self.active is not None and idx < self.active["depth"]:
            # Close only the article that opened this candidate, not a nested
            # article. Malformed HTML is deliberately bounded and skipped.
            if tag == "article" and idx == self.active["depth"] - 1:
                self.cards.append(self.active)
            self.active = None
            self.heading_depth = None
        del self.stack[idx:]


def visible_article_clues(html, today, archive_hints=None):
    if not isinstance(html, str) or len(html) > MAX_HTML:
        raise ValueError("HTML regional invalide")
    current_year = date.fromisoformat(today).year
    parser = VisibleArticles()
    parser.feed(html)
    matches, seen = [], set()
    for card in parser.cards:
        if card["anchors"]:
            continue  # Normal hyperlinks belong to the existing pipeline.
        title = " ".join("".join(card["heading"]).split())[:160]
        name = normalized(title)
        context = normalized(" ".join(card["text"]))
        if (not 8 <= len(name) <= 140 or NOT_MUSIC.search(name)
                or len(context) < len(name)):
            continue
        years = {int(y) for y in YEAR.findall(name)}
        if years and (len(years) != 1 or next(iter(years)) not in
                      (current_year, current_year + 1, current_year + 2)):
            continue
        year = next(iter(years)) if years else None
        archive_slug = None
        if year is not None:
            root = re.sub(r" (?:edition )?20[2-4]\d$", "", name)
            old = (archive_hints or {}).get(root)
            if (isinstance(old, dict) and type(old.get("last_known_year")) is int
                    and old["last_known_year"] < year
                    and isinstance(old.get("slug"), str)):
                archive_slug = old["slug"]
        thematic = bool(
            (FEST.search(name) and (MUSIC.search(name) or GENRE.search(context)))
            or (MUSIC.search(name) and FEST.search(context))
            or (FEST.search(context) and GENRE.search(context)))
        if not thematic and not archive_slug:
            continue
        key = (name, year)
        if key in seen:
            continue
        seen.add(key)
        matches.append({
            "title": title, "edition_year_hint": year,
            "historical_name_slug": archive_slug,
            "signal": ("VISIBLE_ARTICLE_HISTORICAL_NAME_ONLY" if archive_slug
                       and not thematic else "VISIBLE_ARTICLE_MUSIC_CONTEXT_ONLY"),
            "date_verified": False, "festival_verified": False,
            "publication_authorized": False, "fetch_eligible": False,
        })
        if len(matches) >= MAX_NEW_PER_PASS:
            break
    return matches, len(parser.cards)


def update_private_articles(state, origin, region, clues, today, approved):
    """Only stable, non-fetchable observations. Corrupt prior state is pruned."""
    if origin not in approved or region != approved[origin]:
        raise ValueError("origine regionale inconnue")
    now = date.fromisoformat(today)
    key_name = "regional_festival_article_clues_review_only"
    previous = state.get(key_name, {})
    if not isinstance(previous, dict):
        raise ValueError("file de fiches visibles invalide")
    safe = {}
    for key, item in list(previous.items())[:MAX_PENDING * 2]:
        if (not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{20}", key)
                or not isinstance(item, dict)
                or item.get("publication_authorized") is not False
                or item.get("fetch_eligible") is not False
                or item.get("status") != STATUS
                or not isinstance(item.get("source_index"), str)
                or item["source_index"] not in approved
                or item.get("region") != approved.get(item["source_index"])):
            continue
        try:
            day = date.fromisoformat(item["lastSeen"])
            first = date.fromisoformat(item["firstSeen"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (first <= day <= now and (now - day).days <= MAX_AGE_DAYS):
            continue
        title = item.get("title")
        if (not isinstance(title, str) or not 8 <= len(normalized(title)) <= 140
                or item.get("edition_year_hint") not in
                (None, now.year - 1, now.year, now.year + 1, now.year + 2)
                or key != sha256((
                    item["source_index"] + "\n" + normalized(title) + "\n"
                    + str(item["edition_year_hint"])).encode()).hexdigest()[:20]):
            continue
        safe[key] = item
        if len(safe) >= MAX_PENDING:
            break
    created = []
    for clue in clues:
        if (not isinstance(clue, dict)
                or clue.get("publication_authorized") is not False
                or clue.get("fetch_eligible") is not False):
            continue
        key = sha256((origin + "\n" + normalized(clue["title"]) + "\n"
                      + str(clue["edition_year_hint"])).encode()).hexdigest()[:20]
        old = safe.get(key)
        if old is None and len(safe) >= MAX_PENDING:
            continue
        row = {
            "title": clue["title"],
            "edition_year_hint": clue["edition_year_hint"],
            "historical_name_slug": clue["historical_name_slug"],
            "discovery_signal": clue["signal"],
            "source_index": origin, "region": region,
            "firstSeen": old["firstSeen"] if old else today,
            "lastSeen": today, "status": STATUS,
            "festival_verified": False, "date_verified": False,
            "publication_authorized": False, "fetch_eligible": False,
        }
        safe[key] = row
        if old is None:
            created.append(row)
    state[key_name] = safe
    return created, len(safe)
