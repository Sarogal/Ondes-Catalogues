"""Public, read-only Grosses Ondes regional discovery pilot.

This runner has NO credentials, private intake, publication privileges or
write-back. It produces diagnostics, not confirmed festivals or date rows.
Run in public GitHub Actions standard runners to avoid private compute usage.
"""
import argparse
from datetime import datetime
from html.parser import HTMLParser
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
import unicodedata
from zoneinfo import ZoneInfo

# Explicitly curated public institution indexes. No URL from page content is fetched.
INDEXES = (
    ("Hauts-de-France", "https://www.phalempin.fr/mes-loisirs/evenements-manifestations/"),
    ("Nouvelle-Aquitaine", "https://www.saintes-tourisme.fr/agenda/concerts-et-festivals/"),
    ("Nouvelle-Aquitaine", "https://sortir.limoges.fr/agenda"),
    ("Nouvelle-Aquitaine", "https://sortir.limoges.fr/agenda?keys=rock"),
    ("Nouvelle-Aquitaine", "https://sortir.limoges.fr/agenda?keys=festival"),
    ("Pays de la Loire", "https://www.angers.fr/actualites-sorties/agenda/index.html"),
    ("Occitanie", "https://agenda.montpellier.fr/"),
    ("Occitanie", "https://www.tourisme-occitanie.com/agenda/par-theme/festivals/"),
    ("Île-de-France", "https://www.tourisme-seine-et-marne.fr/agenda/"),
    ("Centre-Val de Loire", "https://www.val-de-loire-41.com/agenda/grands-evenements/"),
    ("Bretagne", "https://www.tourismebretagne.com/preparer-mon-sejour/agenda/"),
    ("Bretagne", "https://www.tourismebretagne.com/preparer-mon-sejour/agenda/festivals-bretagne/"),
    ("Auvergne-Rhône-Alpes", "https://www.visiterlyon.com/sortir/l-agenda/festivals"),
    ("Provence-Alpes-Côte d'Azur", "https://www.dignelesbains-tourisme.com/agendas/tout-lagenda/"),
    ("Corse", "https://tourisme-centrecorse.corsica/agenda/"),
    ("Grand Est", "https://www.explore-grandest.com/agenda/"),
    ("Normandie", "https://www.normandie-tourisme.fr/agenda/"),
    ("Bourgogne-Franche-Comté", "https://www.bourgogne-tourisme.com/sejourner/agenda/"),
)
MAX_REQUESTS = 4
MAX_BYTES = 650_000
HIDDEN = {"script", "style", "svg", "noscript", "template", "iframe"}
VOID = {"br", "hr", "img", "input", "meta", "link", "source", "area", "wbr", "embed"}
GENRE = re.compile(r"\b(?:metal|hard rock|hardcore|rock|punk|metalcore|stoner|doom|sludge|grindcore)\b")
FESTIVAL = re.compile(r"\b(?:fest|festival)\b")


def normalized(value):
    raw = unicodedata.normalize("NFKD", value.casefold())
    text = "".join(c for c in raw if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", text))


class VisibleAnchors(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.anchor = None
        self.labels = []
        self.visible_anchors = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        opts = dict(attrs)
        hidden = (bool(self.stack and self.stack[-1][1]) or tag in HIDDEN
                  or "hidden" in opts or opts.get("aria-hidden") == "true"
                  or "display:none" in (opts.get("style") or "").lower().replace(" ", ""))
        if tag not in VOID:
            self.stack.append((tag, hidden))
        if tag == "a" and not hidden:
            self.anchor = {"depth": len(self.stack), "parts": []}

    def handle_data(self, data):
        if self.anchor and self.stack and not self.stack[-1][1]:
            self.anchor["parts"].append(data[:250])

    def handle_endtag(self, tag):
        tag = tag.lower()
        idx = next((i for i in range(len(self.stack)-1, -1, -1)
                    if self.stack[i][0] == tag), None)
        if idx is None:
            return
        if self.anchor and tag == "a" and idx == self.anchor["depth"] - 1:
            self.visible_anchors += 1
            label = normalized(" ".join(self.anchor["parts"])[:300])
            if len(self.labels) < 650 and label:
                self.labels.append(label)
            self.anchor = None
        del self.stack[idx:]


def inspect_index(html):
    if not isinstance(html, str) or len(html) > MAX_BYTES:
        raise ValueError("index HTML invalide ou trop volumineux")
    parser = VisibleAnchors()
    parser.feed(html)
    themed = sum(bool(FESTIVAL.search(t) and GENRE.search(t))
                 for t in parser.labels)
    return {
        "visible_anchor_count": parser.visible_anchors,
        "themed_visible_label_count": themed,
        "linkless_hint": parser.visible_anchors == 0 and "<script" in html.lower(),
        "confirmed_festivals": 0,
        "published": 0,
    }


def selected_indexes(day, slot, limit=MAX_REQUESTS):
    if not 1 <= limit <= MAX_REQUESTS or slot not in ("morning", "evening"):
        raise ValueError("tour invalide")
    if not hasattr(day, "toordinal"):
        raise ValueError("date invalide")
    offset = ((day.toordinal() * 2 + (slot == "evening")) * MAX_REQUESTS) % len(INDEXES)
    return [INDEXES[(offset + i) % len(INDEXES)] for i in range(limit)]


class SafeSameHostRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old = urlsplit(req.full_url)
        new = urlsplit(newurl)
        if (new.scheme != "https" or new.hostname != old.hostname
                or new.port not in (None, 443)
                or new.username or new.password):
            raise ValueError("redirection hors de la source autorisée")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_index(url):
    if url not in {index for _region, index in INDEXES}:
        raise ValueError("URL source non autorisée")
    request = Request(url, headers={"User-Agent": "GrossesOndesPublicDiscovery/1.0",
                                    "Accept": "text/html,application/xhtml+xml"})
    with build_opener(SafeSameHostRedirects()).open(request, timeout=12) as response:
        if (urlsplit(response.geturl()).hostname != urlsplit(url).hostname
                or response.headers.get_content_type() not in
                ("text/html", "application/xhtml+xml")):
            raise ValueError("réponse source non conforme")
        payload = response.read(MAX_BYTES + 1)
        if len(payload) > MAX_BYTES:
            raise ValueError("source trop volumineuse")
        return payload.decode(response.headers.get_content_charset() or "utf-8",
                              errors="replace")


def run(day, slot, fetch=fetch_index):
    rows = []
    for region, source_url in selected_indexes(day, slot):
        row = {"region": region, "index": source_url, "status": "UNAVAILABLE",
               "confirmed_festivals": 0, "published": 0}
        try:
            row.update(inspect_index(fetch(source_url)))
            row["status"] = "SCANNED"
        except (OSError, UnicodeError, ValueError, TimeoutError) as exc:
            row["error_type"] = type(exc).__name__  # No sensitive exception text.
        rows.append(row)
    return {
        "schema": "grossesondes.public-regional-probe.v1",
        "observed_at": day.isoformat(),
        "slot": slot,
        "configured_sources": len(INDEXES),
        "configured_regions": len({region for region, _ in INDEXES}),
        "attempted": len(rows),
        "accessible": sum(row["status"] == "SCANNED" for row in rows),
        "themed_visible_labels": sum(row.get("themed_visible_label_count", 0)
                                     for row in rows),
        "review_only": True, "publication_authorized": False,
        "confirmed_festivals": 0, "published": 0,
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slot", choices=("morning", "evening"), required=True)
    args = parser.parse_args()
    today = datetime.now(ZoneInfo("Europe/Paris")).date()
    result = run(today, args.slot)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("DECOUVERTE_REGIONALE_PUBLIQUE:", json.dumps({
        k: result[k] for k in ("configured_sources", "configured_regions",
                               "attempted", "accessible", "themed_visible_labels",
                               "confirmed_festivals", "published")
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
