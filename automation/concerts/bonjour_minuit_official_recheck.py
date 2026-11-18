"""Reusable, fail-closed Bonjour Minuit official concert verifier.

The venue's H1 and every named artist H2 must agree on the complete bill.
Artist H2s are accepted only when immediately followed by a genre badge.
Artist biographies, recommendations, ticketing H2s, nav and footers never
create a musician. This module has no network or publication side effects.
"""
from __future__ import annotations

import datetime as dt
from html.parser import HTMLParser
import re

import bonjour_minuit_adapter as venue

SOURCE = "agenda_officiel_bonjour_minuit_detail_review"
VENUE = "bonjour-minuit-saint-brieuc"
STRUCTURE = "bonjour-minuit-named-h2-and-immediate-genre-badge"
# On this venue the *first* artist must carry an independently checked
# rock/punk/metal badge (enforced by the existing discovery parser). Opening
# and supporting acts may be electro, pop, hip-hop, etc.; they must still have
# their own first-party artist H2 and immediate genre badge.
STYLE_PREFIX = re.compile(
    r"^(?:(?:transe|math|electro|art|indie|kraut|psych) rock|"
    r"rock|metal|punk|hardcore|post punk|noise|grunge|stoner|"
    r"electro|electronique|pop|indie|dj set|rap|hip hop|jazz|"
    r"ska|soul|folk|new wave|ambient|experimental|chanson|"
    r"psych(?:e|edelique)|post rock|shoegaze|indus|trip hop)\b"
)
UNNAMED = frozenset({
    "guest", "special guest", "premiere partie",
    "premiere partie surprise", "support", "surprise",
    "a confirmer", "tba", "invite surprise", "artiste surprise"
})


def identity(value):
    """A staging note is not part of a band's canonical artist identity."""
    name = re.sub(r"\s+(?:release party|sortie d album)$", "",
                  str(value or ""), flags=re.I)
    name = re.sub(r"\s+\(live\)$", "", name, flags=re.I)
    return name.strip()


class OfficialArtistHeadings(HTMLParser):
    """Read the first H1 and every immediately badged artist H2 on its page.

    Only text following the H2 and preceding its first paragraph can be
    used as a genre badge. This bounds the evidence before artist biographies.
    For each H2, suppress <sup> accessibility badges. Ignore site chrome.
    """
    SKIP = frozenset({"nav", "footer", "script", "style", "noscript", "sup"})
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.in_h1 = False
        self.h1s = []
        self.in_h2 = False
        self.current = None
        self.collecting_badge = False
        self.sections = []
        self.potential_short_badge = None

    def _finish(self):
        if self.current is not None:
            title = " ".join("".join(self.current["title"]).split())
            badge = venue.plain(" ".join(self.current["badge"]))[:100]
            if not badge and self.current.get("first_short_p"):
                badge = venue.plain(self.current["first_short_p"])[:100]
            if title and STYLE_PREFIX.search(badge):
                self.sections.append((title, badge))
        self.current = None
        self.in_h2 = False
        self.collecting_badge = False
        self.potential_short_badge = None

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.hidden += 1
            return
        if self.hidden:
            return
        if tag == "h1":
            self._finish()
            self.in_h1 = True
            self.h1s.append([])
        elif tag == "h2" and self.h1s:
            self._finish()
            self.current = {"title": [], "badge": []}
            self.in_h2 = True
            self.collecting_badge = False
        elif tag == "p" and self.current is not None and not self.in_h2:
            # Some legitimate venue templates express the genre as a
            # single short P instead of a DIV/SPAN. Capture ONLY the first
            # short P when no preceding badge exists; never use a biography.
            self.potential_short_badge = (
                [] if not self.current["badge"]
                and not self.current.get("first_p_seen") else None
            )
            self.current["first_p_seen"] = True
            self.collecting_badge = False

    def handle_data(self, text):
        if self.hidden:
            return
        if self.in_h1 and self.h1s:
            self.h1s[-1].append(text)
        elif self.in_h2 and self.current is not None:
            self.current["title"].append(text)
        elif self.potential_short_badge is not None:
            self.potential_short_badge.append(text)
        elif self.collecting_badge and self.current is not None:
            self.current["badge"].append(text)

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            if self.hidden:
                self.hidden -= 1
            return
        if self.hidden:
            return
        if tag == "p" and self.potential_short_badge is not None:
            possible = " ".join(" ".join(self.potential_short_badge).split())
            if self.current is not None and len(possible) <= 85:
                self.current["first_short_p"] = possible
            self.potential_short_badge = None
        if tag == "h1":
            self.in_h1 = False
        elif tag == "h2" and self.in_h2:
            self.in_h2 = False
            self.collecting_badge = True

    def close(self):
        super().close()
        self._finish()


def verify(candidate, page, catalogue, today):
    if not isinstance(candidate, dict) or not isinstance(today, dt.date):
        raise ValueError("Bonjour Minuit : entrée invalide")
    if (candidate.get("source") != SOURCE
            or candidate.get("reviewBucket") != "genre_tag_review"
            or candidate.get("reviewRequired") is not True
            or candidate.get("publicationAllowed") is not False
            or candidate.get("possibleExistingConcert") is not False
            or candidate.get("officialDetailFound") is not True
            or candidate.get("sourcePage") != venue.AGENDA
            or candidate.get("venue") != "Bonjour Minuit"
            or candidate.get("venueCatalogueId") != VENUE
            or candidate.get("city") != "Saint-Brieuc"
            or str(candidate.get("department")) != "22"):
        raise ValueError("Bonjour Minuit : source ou quarantaine non confirmée")
    url = candidate.get("sourceUrl")
    if not isinstance(url, str) or venue.detail_url(url) != url:
        raise ValueError("Bonjour Minuit : fiche HTTPS individuelle obligatoire")
    if not isinstance(page, str) or not 100 <= len(page) <= 500_000:
        raise ValueError("Bonjour Minuit : réponse officielle absente")
    if not isinstance(catalogue, dict) or any(
            not isinstance(catalogue.get(key), list)
            for key in ("artists", "venues", "events")):
        raise ValueError("Bonjour Minuit : catalogue invalide")

    source_meta = {"name": "Bonjour Minuit", "city": "Saint-Brieuc",
                   "department": "22", "url": venue.AGENDA}
    # Re-run the DISCOVERY parser from independent raw HTML; a carried
    # discovery card or an artist's own page cannot prove anything by itself.
    fresh = venue.candidate(page, url, source_meta, today.isoformat())
    for key in ("source", "sourcePage", "sourceUrl", "name",
                "date", "leadArtist", "venue", "venueCatalogueId",
                "venueHall", "city", "department", "classification",
                "genreEvidenceScope", "localTime", "officialDetailFound"):
        if candidate.get(key) != fresh.get(key):
            raise ValueError("Bonjour Minuit : annonce modifiée : " + key)
    if (dt.date.fromisoformat(fresh["date"]) <= today
            or fresh["statusNotice"] in ("cancelled", "postponed")
            or fresh.get("cancellationNotice") is True
            or candidate.get("cancellationNotice") is True):
        raise ValueError("Bonjour Minuit : concert passé, annulé ou reporté")
    if len(fresh["classification"]) != 1 or not venue.STYLE.fullmatch(
            venue.plain(fresh["classification"][0])):
        raise ValueError("Bonjour Minuit : genre principal non démontré")

    parsed = OfficialArtistHeadings()
    parsed.feed(page)
    parsed.close()
    if len(parsed.h1s) != 1:
        raise ValueError("Bonjour Minuit : unique affiche H1 obligatoire")
    official_title = " ".join("".join(parsed.h1s[0]).split())
    if venue.plain(official_title) != venue.plain(fresh["name"]):
        raise ValueError("Bonjour Minuit : intitulé officiel incohérent")
    if not parsed.sections:
        raise ValueError("Bonjour Minuit : artiste avec genre officiel absent")
    names = [identity(name) for name, _badge in parsed.sections]
    normalized = [venue.plain(name) for name in names]
    if (len(set(normalized)) != len(normalized)
            or any(not 3 <= len(name) <= 100 or name in UNNAMED
                   for name in normalized)):
        raise ValueError("Bonjour Minuit : artiste sans identité fiable")
    if normalized[0] != venue.plain(fresh["leadArtist"]):
        raise ValueError("Bonjour Minuit : tête d'affiche non concordante")
    # H1 has no reliable separator between artists on this venue. Every
    # official H2 must reconstruct the same sequence; all extra unbadged
    # text (e.g. a named support lacking a section) is held for review.
    joined = venue.plain(" ".join(names))
    headline = venue.plain(identity(fresh["name"]))
    headline = re.sub(r"\brelease party\b", "", headline)
    headline = " ".join(headline.split())
    guest = None
    if headline != joined:
        # The official H1 may advertise an unnamed support; accept it
        # only as a recognized final *generic* label, never as an artist.
        for marker in sorted(UNNAMED, key=len, reverse=True):
            if headline == joined + " " + marker:
                guest = marker
                break
        if guest is None:
            raise ValueError("Bonjour Minuit : affiche H1 et sections H2 divergentes")

    venue_matches = [v for v in catalogue["venues"] if v.get("id") == VENUE]
    if (len(venue_matches) != 1 or
            venue.plain(venue_matches[0].get("city")) != "saint brieuc"
            or any(venue_matches[0].get(x) is None
                   for x in ("latitude", "longitude"))):
        raise ValueError("Bonjour Minuit : salle non enregistrée ou non localisée")
    by_name, aliases, used = {}, set(), set()
    for artist in catalogue["artists"]:
        aid = artist.get("id")
        if not isinstance(aid, str) or not aid:
            raise ValueError("Bonjour Minuit : catalogue artiste corrompu")
        used.add(aid)
        by_name.setdefault(venue.plain(artist.get("name")), []).append(artist)
        aliases.update(venue.plain(alias)
                       for alias in artist.get("aliases") or []
                       if isinstance(alias, str))

    ids, new_artists = [], []
    for name in names:
        key = venue.plain(name)
        match = by_name.get(key, [])
        if len(match) > 1:
            raise ValueError("Bonjour Minuit : identité canonique multiple")
        if match:
            aid = match[0]["id"]
        else:
            if key in aliases:
                raise ValueError("Bonjour Minuit : alias existant à réconcilier")
            aid = key.replace(" ", "-")[:90].strip("-")
            if not 3 <= len(aid) <= 100 or aid in used:
                raise ValueError("Bonjour Minuit : nouvel artiste ambigu")
            new_artists.append({"id": aid, "name": name})
            used.add(aid)
        ids.append(aid)
    if len(set(ids)) != len(ids):
        raise ValueError("Bonjour Minuit : groupe répété")
    if any(e.get("officialUrl") == url or (
            e.get("date") == fresh["date"] and e.get("venueId") == VENUE
            and set(e.get("artistIds") or []) & set(ids))
            for e in catalogue["events"]):
        raise ValueError("Bonjour Minuit : concert déjà publié")
    eid = ("go-c-" + fresh["date"].replace("-", "") +
           "-saint-brieuc-" + ids[0])
    if len(eid) > 150 or any(e.get("id") == eid
                             for e in catalogue["events"]):
        raise ValueError("Bonjour Minuit : identifiant déjà utilisé")
    return {
        "reviewDecision": "approved",
        "reviewedBy": "automated-official-recheck",
        "reviewedAt": today.isoformat(),
        "officialEvidence": [{
            "url": url, "proofType": "official-organizer-or-venue",
            "checkedAt": today.isoformat(),
            "checkedFields": ["artists", "date", "venue", "genre"],
            "sourceStructure": STRUCTURE, "officialArtistNames": names,
            "officialArtistBadges": [badge for _name, badge in parsed.sections],
            "verifiedNewArtists": [a["name"] for a in new_artists],
            "officialRoom": fresh["venueHall"],
            **({"unannouncedSupportLabel": guest,
                "originalOfficialHeadline": fresh["name"]} if guest else {}),
        }],
        "event": {
            "id": eid, "title": " + ".join(names), "date": fresh["date"],
            "time": None, "artistIds": ids, "venueId": VENUE,
            "genres": fresh["classification"], "status": "confirmed",
            "officialUrl": url, "sourceType": "salle",
            "organizer": "Bonjour Minuit",
        },
        "newArtists": new_artists,
    }
