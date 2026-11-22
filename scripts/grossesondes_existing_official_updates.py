"""Recheck updates for already SIGNED festivals on their official first-party sites.

No closed lists of festivals, artists, places or domains. One official site is
a sufficient editorial source; the cloud Publisher itself re-fetches it and
only follows bounded, safe same-host news/line-up/ticket links. A checksum
change, an undated old edition or an external news site cannot modify data.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import date
from hashlib import sha256
from html.parser import HTMLParser
from math import ceil
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

from dns_pinned_https import fetch_public_html, safe_public_url
from source_qualification import classify
from future_city_preflight import exact_edition_city, _normal as normal_city
from official_admin_communes import verified_commune

MAX_LINKS = 5
MAX_HOSTS = 8
COMMUNE_FIELDS = frozenset((
    "city", "lat", "lon", "showOnMap", "geoCity", "geoPrecision",
    "geoInsee", "geoSource", "geoVerification",
))
CHANGEABLE = frozenset(("lineup", "bands", "price", "lastVerified", "auditSources")) | COMMUNE_FIELDS
ROLE = re.compile(r"\b(?:programmation|line up|lineup|groupes?|noms|artistes?|"
                  r"annonce|affiche|actualites?|news|billetterie|tarifs?|pass|202[7-9])\b")
GENRE_LIST = re.compile(r"\b(?:groupes?|noms|artistes?|programmation|lineup|affiche|ils seront)\b")
ANNOUNCE = re.compile(r"\b(?:nouveaux?|annonces?|programmation|affiche|ils seront|trois groupes)\b")
SENSITIVE = re.compile(r"\b(?:annule|annulee|reportee|cancelled|postponed)\b")
PRICE = re.compile(r"(\d{2,4}(?:[,.]\d{2})?)\s*€")
PASS = re.compile(r"\bpass\s*([1-7])\s*jours?\b")


def fold(s):
    s = unicodedata.normalize("NFKD", str(s)).casefold()
    return " ".join(re.findall(r"[a-z0-9]+",
                    "".join(c for c in s if not unicodedata.combining(c))))


def key(s):
    return fold(s).replace(" ", "")


class Page(HTMLParser):
    """Visible heading, paragraph, bullet, bold bullet and anchor evidence."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.links, self.open, self.anchors = [], [], [], []
        self.hidden_tag = None
        self.main = self.article = 0
        self.strong = None

    def handle_starttag(self, tag, attrs):
        if self.hidden_tag is not None:
            return
        if (tag in ("script", "style", "noscript", "svg", "template") or
                any(k in ("hidden", "aria-hidden") and (v is None or v == "true")
                    for k, v in attrs) or
                any(k == "style" and re.search(r"display\s*:\s*none", v or "", re.I)
                    for k, v in attrs)):
            self.hidden_tag = tag
            return
        if tag == "main":
            self.main += 1
        if tag == "article":
            self.article += 1
        if tag in ("h1", "h2", "h3", "p", "li"):
            self.open.append({"tag": tag, "buf": [], "lead": "",
                              "scope": "article" if self.article else
                              "main" if self.main else "other"})
        if tag == "strong" and self.open and self.open[-1]["tag"] == "li":
            self.strong = []
        if tag == "a":
            self.anchors.append([dict(attrs).get("href"), []])

    def handle_data(self, value):
        if self.hidden_tag is not None:
            return
        for b in self.open:
            b["buf"].append(value)
        for a in self.anchors:
            a[1].append(value)
        if self.strong is not None:
            self.strong.append(value)

    def handle_endtag(self, tag):
        if self.hidden_tag is not None:
            if tag == self.hidden_tag:
                self.hidden_tag = None
            return
        if tag == "strong" and self.strong is not None:
            if self.open and self.open[-1]["tag"] == "li":
                self.open[-1]["lead"] = " ".join(" ".join(self.strong).split())
            self.strong = None
        if tag in ("h1", "h2", "h3", "p", "li"):
            for i in range(len(self.open) - 1, -1, -1):
                if self.open[i]["tag"] == tag:
                    b = self.open.pop(i)
                    b["text"] = " ".join(" ".join(b.pop("buf")).split())
                    if b["text"]:
                        self.blocks.append(b)
                    break
        if tag == "a" and self.anchors:
            href, values = self.anchors.pop()
            self.links.append((href, " ".join(" ".join(values).split())))
        if tag == "article":
            self.article = max(0, self.article - 1)
        if tag == "main":
            self.main = max(0, self.main - 1)

    def relevant(self):
        for scope in ("article", "main", "other"):
            found = [b for b in self.blocks if b["scope"] == scope]
            if found:
                return found
        return []


def page(html):
    if not isinstance(html, str) or not 0 < len(html) <= 650_000:
        raise ValueError("Untrusted official HTML")
    out = Page()
    out.feed(html)
    out.close()
    return out


def linked_pages(site, parsed):
    if safe_public_url(site) != site:
        return []
    host = urlsplit(site).hostname
    ranked = {}
    for href, label in parsed.links[:300]:
        if not isinstance(href, str) or not 0 < len(href) <= 500:
            continue
        if any(c in href for c in ("%", "\\", "#")):
            continue
        raw = urlsplit(href)
        if ".." in raw.path.split("/"):
            continue
        url = urljoin(site, href)
        bits = urlsplit(url)
        # A relative href on a language-prefixed homepage sometimes repeats
        # that locale (e.g. /fr/ + fr/news => /fr/fr/news, a 404). Derive
        # the unique nonduplicated path ONLY from its actual first-party
        # anchor, without allowing a different host or a candidate URL.
        locale = urlsplit(site).path.strip("/")
        if (re.fullmatch(r"[a-z]{2}", locale or "") and
                bits.path.startswith("/" + locale + "/" + locale + "/")):
            url = "https://" + host + bits.path[len(locale)+1:]
            bits = urlsplit(url)
        if (bits.scheme != "https" or bits.hostname != host or bits.query or
                bits.fragment or bits.username or bits.password or
                bits.port is not None or url == site or
                safe_public_url(url) != url):
            continue
        if re.search(r"/(?:20[01]\d|202[0-6])(?:/|$)", bits.path):
            continue
        label = fold(label + " " + bits.path.replace("-", " "))
        if not ROLE.search(label):
            continue
        rank = (0 if re.search(r"nouveaux? noms|groupes? annonces?|annonce|affiche", label)
                else 1 if re.search(r"programmation|lineup|groupes", label)
                else 2 if re.search(r"billetterie|pass|tarif", label)
                else 3)
        ranked[url] = min(rank, ranked.get(url, rank))
    return sorted(ranked, key=lambda u: (ranked[u], u))[:MAX_LINKS]


def good_artist(value):
    name = " ".join(str(value).strip().strip(" .:;").split())
    if (not 2 <= len(key(name)) <= 90 or len(name) > 110 or
            not re.search(r"[A-Za-zÀ-ÿ]", name) or
            re.search(r"[\r\n<>@/\\]", name) or
            re.search(r"\b(?:billetterie|pass|festival|programmation|"
                      r"concert|vente|tarif|groupes|nouveaux)\b", fold(name))):
        return None
    return name


def listed_artists(blocks):
    names, active = [], False
    for i, b in enumerate(blocks):
        text = fold(b["text"])
        if b["tag"].startswith("h"):
            active = bool(GENRE_LIST.search(text) and
                          (ANNOUNCE.search(text) or "groupes" in text))
        if b["tag"] == "li" and active:
            found = good_artist(b["lead"] or b["text"])
            if found:
                names.append(found)
        if b["tag"] != "p" or not (GENRE_LIST.search(text)
                                  and re.search(r"\b(?:nouveaux|nouvelles|"
                                                r"groupes attendus|groupes annonces)\b", text)
                                  and ":" in b["text"] and i + 1 < len(blocks)):
            continue
        nxt = blocks[i + 1]
        if nxt["tag"] != "p" or not 5 <= len(nxt["text"]) <= 2500 or nxt["text"].count(",") < 2:
            continue
        parts = re.split(r"\s*,\s*|\s+et\s+(?=[^,]{2,85}\.?$)", nxt["text"])
        if 3 <= len(parts) <= 60:
            valid = [good_artist(p) for p in parts]
            if all(valid):
                names.extend(valid)
    unique, result = set(), []
    for name in names:
        k = key(name)
        if k not in unique:
            unique.add(k)
            result.append(name)
    return result[:60]


def advertised_passes(blocks):
    found = {}
    text = [b["text"] for b in blocks]
    for i, block in enumerate(text):
        for category in PASS.finditer(fold(block)):
            # The price and sale status may be in distinct consecutive
            # blocks. Stop BEFORE another pass category, never borrow its
            # price for a different pass.
            pieces = [block]
            for sibling in text[i + 1:i + 4]:
                if PASS.search(fold(sibling)):
                    break
                pieces.append(sibling)
            near = " ".join(pieces)[:480]
            price = PRICE.search(near)
            if price is None:
                continue
            norm = fold(near)
            if not re.search(r"\b(?:en vente|ouverte|ouvert|disponible)\b", norm):
                continue
            if re.search(r"\b(?:epuise|sold out|complet)\b", norm):
                continue
            found[int(category.group(1))] = price.group(1).replace(".", ",") + " €"
    return found


def matches_edition(doc, row, today, *, root_ok):
    try:
        start = date.fromisoformat(row["startDate"])
        end = date.fromisoformat(row["endDate"])
        if not start <= end or start < date.fromisoformat(today):
            return False
    except (KeyError, TypeError, ValueError):
        return False
    visible = fold(" ".join(b["text"] for b in doc.relevant()))
    if SENSITIVE.search(visible):
        return False
    brand = [w for w in fold(row.get("name", "")).split()
             if len(w) >= 5 and w not in
             ("festival", "festivals", "metal", "rock", "open", "music", "edition")]
    named = any(re.search(r"\b" + re.escape(w) + r"\b", visible)
                for w in brand)
    has_year = re.search(r"\b" + str(start.year) + r"\b", visible) is not None
    if named and has_year:
        return True
    # A first-party news item may refer to "18e édition" and the exact
    # published weekend without repeating the brand/year. Its signed home
    # MUST explicitly name the actual year and edition first.
    days = str(start.day) + " au " + str(end.day)
    return bool(root_ok and "edition" in visible and
                start.month == end.month and days in visible)


def home_matches_edition(doc, row, today):
    """Festival home may have 2026 news <article> before 2027 <main>.

    A news teaser must not hide the signed current edition's own homepage
    section. A cross-edition article itself is still independently checked.
    """
    if matches_edition(doc, row, today, root_ok=False):
        return True
    main_only = Page()
    main_only.blocks = [b for b in doc.blocks if b["scope"] == "main"]
    return bool(main_only.blocks and
                matches_edition(main_only, row, today, root_ok=False))


def signed_rotation(published, today, limit=MAX_HOSTS, tick=None):
    if (not isinstance(published, dict) or published.get("schema") != 1 or
            type(limit) is not int or not 0 <= limit <= 30):
        raise ValueError("Invalid signed source rotation")
    grouped = {}
    for row in published["festivals"]:
        url = row.get("officialSite")
        if (not isinstance(url, str) or safe_public_url(url) != url or
                classify(url) in ("TICKETING", "SOCIAL", "MEDIA", "THIRD_PARTY")):
            continue
        try:
            if date.fromisoformat(row["startDate"]) < date.fromisoformat(today):
                continue
        except (ValueError, TypeError, KeyError):
            continue
        grouped.setdefault(url, []).append(row)
    urls = sorted(grouped, key=lambda u: sha256(u.encode()).hexdigest())
    if not urls or not limit:
        return []
    # All slots are reached even when total source count is divisible by 8.
    batch = (date.fromisoformat(today).toordinal() * 2 if tick is None else tick)
    offset = batch % ceil(len(urls) / limit) * limit
    return [(url, grouped[url]) for url in urls[offset:offset + limit]]


def apply_independently_verified_updates(
        target, published, today, fetch=fetch_public_html, limit=MAX_HOSTS,
        tick=None, commune_resolver=verified_commune):
    """Recheck signed artists/prices and exact first-party city proof.

    A commune marker is only an indicative administrative centre: no precise
    festival entrance is inferred from a former venue or an organizer footer.
    """
    result = deepcopy(target)
    positions = {r["slug"]: i for i, r in enumerate(result["festivals"])}
    report = {"checked_official_hosts": 0, "rechecked_pages": 0,
              "accepted": [], "accepted_changes": [], "unavailable": 0,
              "private_proposal_is_authority": False}
    for site, rows in signed_rotation(published, today, limit, tick):
        report["checked_official_hosts"] += 1
        try:
            root_html = fetch(site)
            root = page(root_html)
            report["rechecked_pages"] += 1
        except (OSError, TimeoutError, ValueError, UnicodeError):
            report["unavailable"] += 1
            continue
        pages = [(site, root)]
        # On a current-edition homepage, old news cards may be nested in
        # <article> while the live ticket categories are in <main>. Inspect
        # both as separate first-party content scopes, not one mixed roster.
        main_only = Page()
        main_only.blocks = [b for b in root.blocks if b["scope"] == "main"]
        if main_only.blocks:
            pages.append((site, main_only))
        for link in linked_pages(site, root):
            try:
                pages.append((link, page(fetch(link))))
                report["rechecked_pages"] += 1
            except (OSError, TimeoutError, ValueError, UnicodeError):
                continue
        for old in rows:
            slug = old["slug"]
            new = result["festivals"][positions[slug]]
            if (any(old.get(f) != new.get(f) for f in set(old) | set(new)) or
                    not isinstance(old.get("lineup"), list)):
                continue
            root_ok = home_matches_edition(root, old, today)
            claims, prices, sources = [], {}, []
            for url, doc in pages:
                if not matches_edition(doc, old, today, root_ok=root_ok):
                    continue
                names = listed_artists(doc.relevant())
                offers = advertised_passes(doc.relevant())
                if names or offers:
                    claims += names
                    prices.update(offers)
                    sources.append(url)
            new_names, seen = [], {key(n) for n in old["lineup"]}
            for n in claims:
                if key(n) not in seen:
                    seen.add(key(n))
                    new_names.append(n)
            fields = []
            if (new_names and len(new_names) <= 45 and
                    type(old.get("bands")) is int and
                    old["bands"] == len(old["lineup"])):
                new["lineup"] = list(old["lineup"]) + new_names
                new["bands"] = len(new["lineup"])
                fields.extend(("lineup", "bands"))
            if prices:
                summary = " ; ".join(
                    f"Pass {n} jour{'s' if n > 1 else ''} : {prices[n]}"
                    for n in sorted(prices, reverse=True))
                summary += " — billetterie officielle ouverte"
                old_price = old.get("price")
                if ((old_price is None or
                     (isinstance(old_price, str) and any(
                         f"pass {n} jour" in fold(old_price) for n in prices))) and
                        old_price != summary):
                    new["price"] = summary
                    fields.append("price")
            # The signed current-edition title may explicitly name the town.
            # Publisher re-fetches the site itself, then independently resolves
            # that exact commune through the fixed government geocoding API.
            # Neither private leads nor a previously used venue are authority.
            if (old.get("lat") is None and old.get("lon") is None
                    and old.get("showOnMap") is not True
                    and old.get("futureVenueConfirmed") is not True
                    and old.get("geoVerification") is None
                    and old.get("geoPrecision") is None):
                # A title with signed brand, EXACT dates and one town is its
                # own first-party edition proof. The site's news teaser may
                # omit the year, so root_ok cannot be an additional gate.
                claim = exact_edition_city(root_html, old)
                if (claim and claim.get("source") == site
                        and claim.get("slug") == slug
                        and (not old.get("city")
                             or normal_city(old["city"]) == normal_city(claim["city"]))):
                    try:
                        commune = commune_resolver(claim["city"], old.get("department"))
                    except (OSError, TimeoutError, ValueError, UnicodeError):
                        commune = None
                    if (commune and normal_city(commune.get("city")) == normal_city(claim["city"])
                            and type(commune.get("lat")) in (float, int)
                            and type(commune.get("lon")) in (float, int)
                            and isinstance(commune.get("codeInsee"), str)
                            and isinstance(commune.get("geoSource"), str)):
                        new.update({
                            "city": commune["city"],
                            "lat": commune["lat"], "lon": commune["lon"],
                            "geoCity": commune["city"],
                            "geoPrecision": "commune",
                            "geoInsee": commune["codeInsee"],
                            "geoSource": commune["geoSource"],
                            "showOnMap": True,
                            "geoVerification": {
                                "proofMode": "current-edition-commune-direct-official.v1",
                                "firstObserved": today,
                                "verifiedAt": today,
                                "officialSite": site,
                                "markerMeaning": "centre_indicatif_de_commune",
                            },
                        })
                        fields.extend(sorted(COMMUNE_FIELDS))
                        sources.append(site)
            if not fields:
                continue
            if isinstance(old.get("lastVerified"), str):
                new["lastVerified"] = today
                fields.append("lastVerified")
            previous_urls = old.get("auditSources")
            used = [u for u in previous_urls if isinstance(u, str)] if isinstance(previous_urls, list) else []
            for source in sources:
                if source not in used:
                    used.append(source)
            new["auditSources"] = used[:20]
            fields.append("auditSources")
            if any(old.get(f) != new.get(f) for f in set(old) | set(new)
                   if f not in CHANGEABLE):
                raise ValueError("Unproven mutation of festival fields")
            report["accepted"].append(slug)
            report["accepted_changes"].append({
                "slug": slug, "fields": fields,
                "artists_added": len(new_names) if "lineup" in fields else 0})
    if report["accepted"]:
        result["generatedAt"] = today
    return result, report
