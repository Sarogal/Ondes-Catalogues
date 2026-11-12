#!/usr/bin/env python3
"""Independent first-party Molotov event-detail verifier (no listing heuristics).

Only the genuine Le Molotov venue (not nearby Le Dodu) is supported. Dates,
full heading, explicitly named artists, and explicit genre must agree with
discovery and the public artist/venue registry. No automatic new identities.
"""
from __future__ import annotations

import datetime as dt
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

from official_recheck import norm, slug, GENRES, BANNED, artist_names

HOST = "lemolotov.com"
VENUE = "le-molotov-marseille"
MONTHS = {
    "jan": 1, "fev": 2, "mar": 3, "avr": 4, "mai": 5, "jun": 6,
    "jul": 7, "aou": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
}
# Genre labels in the HTML must be explicit; broad venue descriptions are ignored.
ALLOWED = GENRES | {"alt metal", "melodic death metal", "modern metal",
                    "blackened hardcore", "post punk", "street punk",
                    "punk hxc", "grunge", "progressive metal", "groove metal",
                    "post hardcore"}



UNANNOUNCED_SUPPORT = frozenset({
    "guest", "guests", "special guest", "special guests", "invite",
    "invite surprise", "artiste surprise",
    "premiere partie", "1ere partie", "1re partie", "support",
    "a confirmer", "tba", "surprise",
})
PARTIAL_STRUCTURE = "molotov-first-party-bill-with-unannounced-support"
VERIFIED_NEW_STRUCTURE = "molotov-first-party-named-artist-profiles"
def identity_key(name):
    """Normalize French/Latin ligatures before new-artist identity checks.

    The common NFKD+ASCII fold loses Æ entirely, making PÆRISH become
    'prish' and potentially duplicating an existing PAERISH identity.
    """
    return norm(str(name).replace("Æ", "AE").replace("æ", "ae")
               .replace("Œ", "OE").replace("œ", "oe"))


SOCIAL_HOSTS = frozenset({
    "facebook.com", "www.facebook.com",
    "instagram.com", "www.instagram.com",
    "open.spotify.com", "soundcloud.com", "www.soundcloud.com",
    "www.youtube.com", "youtube.com", "linktr.ee",
})


class NamedArtistProfiles(HTMLParser):
    """Record artist identity headings and associated social links in ONE event.

    The Molotov template prints <strong>Artist<br/>[Genre | Country]</strong>
    followed by that artist's first-party description and social profiles.
    An event title alone cannot create a catalogue artist.
    """
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.article_count = 0
        self.article_open = False
        self.published = False
        self.in_strong = 0
        self.strong_parts = []
        self.profiles = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "article":
            self.article_count += 1
            self.article_open = self.article_count == 1
            self.published = self.published or (
                self.article_open and
                "status-publish" in attrs.get("class", "").split() and
                "event" in attrs.get("class", "").split())
        if not self.article_open:
            return
        if tag == "strong":
            self.in_strong += 1
            if self.in_strong == 1:
                self.strong_parts = []
        if tag == "br" and self.in_strong:
            self.strong_parts.append("\n")
        if tag == "a" and self.profiles:
            u = urlsplit(attrs.get("href", ""))
            host = (u.hostname or "").lower()
            if (u.scheme == "https" and not u.username and not u.password
                    and not u.port and u.path.strip("/") and
                    (host in SOCIAL_HOSTS or host.endswith(".bandcamp.com"))):
                self.profiles[-1]["links"].add(host)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        if self.article_open and self.in_strong:
            self.strong_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "strong" and self.article_open and self.in_strong:
            self.in_strong -= 1
            if not self.in_strong:
                label = "".join(self.strong_parts)
                match = re.fullmatch(
                    r"\s*([^\n\[\]]{3,100})\s*\n\s*\[([^\]]{3,140})\]\s*",
                    label)
                if match and "|" in match[2]:
                    name = " ".join(match[1].split())
                    self.profiles.append({"name": name, "links": set()})
                self.strong_parts = []
        if tag == "article" and self.article_open:
            self.article_open = False


def verified_new_artists(page, names, missing):
    """Require both name/genre first-party blocks and distinct social sources."""
    p = NamedArtistProfiles()
    p.feed(page)
    if p.article_count != 1 or not p.published:
        raise ValueError("Molotov : article officiel publié et unique exigé")
    if len(p.profiles) != len(names):
        raise ValueError("Molotov : une biographie individuelle par artiste exigée")
    if [norm(x["name"]) for x in p.profiles] != [norm(x) for x in names]:
        raise ValueError("Molotov : identité ou ordre des biographies discordant")
    counts = []
    for name, section in zip(names, p.profiles):
        if len(section["links"]) < 2:
            raise ValueError("Molotov : liens officiels d'artiste insuffisants")
        counts.append(len(section["links"]))
    return counts



def confirmed_bill(title):
    """Keep only named artists, and omit an exact trailing guest placeholder."""
    # Only a + separator may introduce an unknown guest, never a text
    # fragment of a band's proper name. This is NOT a generic title cleaner.
    parts = [x.strip() for x in re.split(r"\s+\+\s+", title)]
    unknown = norm(parts[-1]) if len(parts) >= 2 else None
    if unknown in UNANNOUNCED_SUPPORT:
        named = parts[:-1]
        if (not 1 <= len(named) <= 4
                or len({norm(x) for x in named}) != len(named)
                or any(len(norm(x)) < 3 or BANNED.search(norm(x))
                       for x in named)):
            raise ValueError("Affiche principale invalide ou invitée ambiguë")
        # Canonical singular proof label keeps the publishing policy strict.
        return named, "guest" if unknown in {"guests", "special guests"} else unknown
    # Retain the established strict path for fully named official bills.
    return artist_names(title), None


class Headings(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.article = 0
        self.collect = None
        self.depth = 0
        self.text_parts = []
        self.div_ids = []
        self.scopes = []
        self.current_scope = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "article":
            self.article += 1
        if not self.article:
            return
        if tag == "div":
            self.div_ids.append(attrs.get("id"))
        if self.collect and tag in ("br", "hr", "img", "input"):
            self.text_parts.append(" ")
        elif self.collect:
            self.depth += 1
        elif tag in ("h1", "h2", "h3", "h4"):
            self.collect = tag
            self.depth = 1
            self.text_parts = []
            self.current_scope = (
                "entry-title" if tag == "h1" and
                "entry-title" in attrs.get("class", "").split()
                else "event-card" if tag == "h1" and
                "eveCardsolo" in self.div_ids and "eveName" in self.div_ids
                else None
            )

    def handle_endtag(self, tag):
        if self.collect:
            self.depth -= 1
            if self.depth == 0:
                self.rows.append((self.collect, " ".join(" ".join(self.text_parts).split())))
                self.scopes.append(self.current_scope)
                self.collect = None
                self.current_scope = None
                self.text_parts = []
        if tag == "div" and self.article and self.div_ids:
            self.div_ids.pop()
        if tag == "article":
            self.article = max(0, self.article - 1)

    def handle_data(self, data):
        if self.collect:
            self.text_parts.append(data)


def parse_detail(page):
    parser = Headings()
    parser.feed(page)
    rows = parser.rows
    title_at = [(n, text) for n, (tag, text) in enumerate(rows) if tag == "h1" and text]
    if len(title_at) == 1:
        pos, title = title_at[0]
    elif (len(title_at) == 2
          and parser.scopes[title_at[0][0]] == "entry-title"
          and parser.scopes[title_at[1][0]] == "event-card"
          and norm(title_at[0][1]) == norm(title_at[1][1])):
        # The live Molotov WordPress template repeats ONE identical title in
        # the article header and inside #eveCardsolo > #eveName.
        # Select the card title so the complete date/address precede it.
        pos, title = title_at[1]
    else:
        raise ValueError("Une seule affiche officielle détaillée est nécessaire")
    before = rows[:pos]
    # Require exactly one date and the venue and street address in detail
    days = [v for k, v in before if k == "h2" and re.fullmatch(r"\d{1,2}", v)]
    months = [norm(v) for k, v in before if k == "h3" and norm(v) in MONTHS]
    years = [v for k, v in before if k == "h3" and re.fullmatch(r"20\d\d", v)]
    if len(days) != 1 or len(months) != 1 or len(years) != 1:
        raise ValueError("Date complète absente ou ambiguë")
    date = dt.date(int(years[0]), MONTHS[months[0]], int(days[0])).isoformat()
    locations = [norm(v) for k, v in before if k == "h4"]
    if locations.count("le molotov") != 1 or not any("3 place paul cezanne" in x for x in locations):
        raise ValueError("Le lieu n'est pas précisément Le Molotov")
    after = rows[pos + 1:]
    if not after or after[0][0] != "h2":
        raise ValueError("Genres officiels absents")
    genre_labels = [x.strip() for x in after[0][1].split(",") if x.strip()]
    if not ({norm(g) for g in genre_labels} & ALLOWED):
        raise ValueError("Aucun genre métal ou punk explicite")
    return {"title": title, "date": date, "genres": genre_labels,
            "genreTags": {norm(g) for g in genre_labels}}


def verify(candidate, page, catalogue, today):
    if candidate.get("source") != "agenda_officiel_molotov_genre":
        raise ValueError("Source officielle Molotov requise")
    if candidate.get("reviewBucket") != "genre_tag_review" or candidate.get("possibleExistingConcert"):
        raise ValueError("Doublon ou piste nécessitant une vérification distincte")
    if candidate.get("publicationAllowed") is not False or candidate.get("reviewRequired") is not True:
        raise ValueError("Candidat non isolé par la veille")
    if candidate.get("venue") != "Le Molotov" or norm(candidate.get("city")) != "marseille":
        raise ValueError("Le lieu est différent de Le Molotov")
    url = candidate.get("sourceUrl") or ""
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != HOST
            or parsed.username or parsed.password or parsed.port
            or parsed.query or parsed.fragment
            or not re.fullmatch(r"/events/[a-z0-9-]{3,160}/", parsed.path)):
        raise ValueError("Page événement individuelle officielle obligatoire")
    detail = parse_detail(page)
    if norm(detail["title"]) != norm(candidate.get("name")):
        raise ValueError("Affiche incohérente entre la veille et la page officielle")
    if detail["date"] != candidate.get("date") or dt.date.fromisoformat(detail["date"]) <= today:
        raise ValueError("Date modifiée, passée ou imminente")
    if not (detail["genreTags"] & {norm(g) for g in candidate.get("classification") or []}):
        raise ValueError("Genres contradictoires")
    parts, unannounced = confirmed_bill(detail["title"])
    artists_by_norm = {}
    for artist in catalogue.get("artists", []):
        artists_by_norm.setdefault(norm(artist["name"]), []).append(artist["id"])
    ids, new_artists = [], []
    aliases = {norm(alias)
               for artist in catalogue.get("artists", [])
               for alias in (artist.get("aliases") or [])
               if isinstance(alias, str)}
    reserved = {artist["id"] for artist in catalogue.get("artists", [])}
    canonical_names = {identity_key(a["name"])
                       for a in catalogue.get("artists", [])}
    canonical_aliases = {identity_key(alias)
                         for a in catalogue.get("artists", [])
                         for alias in (a.get("aliases") or [])
                         if isinstance(alias, str)}
    absent = []
    for name in parts:
        match = artists_by_norm.get(norm(name), [])
        if len(match) > 1:
            raise ValueError("Artiste absent ou ambigu dans le catalogue")
        if match:
            ids.append(match[0])
        else:
            absent.append(name)
            aid = identity_key(name).replace(" ", "-")[:72]
            if (not aid or aid in reserved or norm(name) in aliases
                    or identity_key(name) in canonical_names | canonical_aliases
                    or BANNED.search(norm(name))):
                raise ValueError("Molotov : nouvel artiste ambigu ou alias déjà connu")
            ids.append(aid)
            new_artists.append({"id": aid, "name": name})
            reserved.add(aid)
    if len(set(ids)) != len(ids):
        raise ValueError("Identités d'artistes en collision")
    if absent:
        if unannounced or len(new_artists) > 2:
            raise ValueError("Artiste absent ou ambigu dans le catalogue Molotov")
        try:
            profile_counts = verified_new_artists(page, parts, absent)
        except ValueError as ex:
            # Keep the legacy refusal contract: an undocumented name is
            # always an absent artist, even when it occurs in a page title.
            raise ValueError("Artiste absent, profil officiel incomplet : " +
                             str(ex)) from ex
    else:
        profile_counts = []
    venues = {v["id"]: v for v in catalogue.get("venues", [])}
    if VENUE not in venues or norm(venues[VENUE].get("city")) != "marseille":
        raise ValueError("Salle absente ou incohérente du catalogue")
    for event in catalogue.get("events", []):
        if event.get("officialUrl") == url:
            raise ValueError("Concert déjà référencé par son URL officielle")
        if event.get("date") == detail["date"] and event.get("venueId") == VENUE:
            if set(event.get("artistIds", [])) & set(ids):
                raise ValueError("Concert déjà référencé sur la même scène et même date")
    lead_id = ids[0] if any(a["id"] == ids[0] for a in new_artists) else slug(parts[0])
    event_id = "go-c-" + detail["date"].replace("-", "") + "-marseille-" + lead_id
    if any(e["id"] == event_id for e in catalogue.get("events", [])):
        raise ValueError("Identifiant d'événement déjà utilisé")
    proof = {
        "url": url, "proofType": "official-organizer-or-venue",
        "checkedAt": today.isoformat(),
        "checkedFields": ["artists", "date", "venue", "genre"],
        "notes": "Fiche individuelle officielle Molotov : titre, date, salle et genres vérifiés.",
    }
    if new_artists:
        proof.update({
            "officialArtistNames": parts,
            "sourceStructure": VERIFIED_NEW_STRUCTURE,
            "verifiedNewArtists": [x["name"] for x in new_artists],
            "officialArtistProfileLinkCounts": profile_counts,
        })
    if unannounced:
        proof.update({
            "officialArtistNames": [next(a["name"] for a in catalogue["artists"]
                                         if a["id"] == artist_id) for artist_id in ids],
            "sourceStructure": PARTIAL_STRUCTURE,
            "unannouncedSupportLabel": unannounced,
        })
    return {
        "reviewDecision": "approved", "reviewedBy": "automated-official-recheck",
        "reviewedAt": today.isoformat(),
        "officialEvidence": [proof],
        "event": {"id": event_id, "title": " + ".join(proof["officialArtistNames"]) if unannounced else detail["title"],
                  "date": detail["date"], "time": None,
                  "artistIds": ids, "venueId": VENUE,
                  "genres": detail["genres"], "status": "confirmed",
                  "officialUrl": url, "sourceType": "salle",
                  "organizer": "Le Molotov"},
        "newArtists": new_artists
    }
