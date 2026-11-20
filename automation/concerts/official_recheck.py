#!/usr/bin/env python3
"""Conservative independent recheck of Le Rex concert detail pages.

Never promotes discovery heuristics alone. Candidates must be stable, from an
allowlisted first-party event URL and corroborated on a freshly fetched detail
page (date, title, explicit genre, lineup and venue address). All other sources
remain pending. By default only produces an approvals candidate and a report;
--apply is explicitly required to alter the private approvals file.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import html.parser
import importlib
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import discover
from verifier_contract import VERIFIER_SPECS

CLOUD = "https://sarogal.github.io/Ondes-Catalogues/grossesondes/concerts.json"
ALLOWED_HOST = "www.lerextoulouse.com"
REX_VENUE = "le-rex-toulouse"
MONTHS = dict(zip(
    ("janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout",
     "septembre", "octobre", "novembre", "decembre"), range(1, 13)
))
GENRES = {
    "metal", "black metal", "death metal", "heavy metal", "doom", "doom metal",
    "stoner", "stoner rock", "sludge", "hard rock", "punk", "hardcore",
    "metalcore", "deathcore", "thrash", "thrash metal", "grindcore",
    "progressive metal", "post metal"
}
BANNED = re.compile(r"\b(guest|invite|surprise|tba|a confirmer|festival|fest|"
                    r"annule|annulee|report[eé]|postponed|cancelled|sold out)\b", re.I)
# An unnamed guest is not a musician identity. It may be omitted ONLY as an
# explicit final suffix, never from the middle of a named bill.
UNNAMED_GUEST_SUFFIX = re.compile(
    r"\s+(?:\+|&|et)\s+(?:guest(?:\s+surprise|\s*\(\s*surprise\s*\))?|"
    r"special guest|invité(?:e)? surprise|artiste surprise|surprise)\s*$", re.I)
# Keep cancellation, uncertainty and festival blockers; guest terms
# are handled by the named-lineup verifier. Sold out is availability, not
# cancellation, and must not block a verified concert.
BANNED_STATUS = re.compile(
    r"\b(?:tba|a confirmer|festival|fest|annule|annulee|"
    r"reporte|postponed|cancelled)\b", re.I)


def norm(text):
    text = unicodedata.normalize("NFKD", str(text or "").casefold())
    text = text.encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", text))


def slug(text):
    return norm(text).replace(" ", "-")[:72].strip("-")


class Detail(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.records = []
        self.kind = None
        self.depth = 0
        self.buffer = []

    def handle_starttag(self, tag, attrs):
        if self.kind and tag in ("br", "hr", "img", "input", "meta", "link"):
            self.buffer.append(" ")
        elif self.kind:
            self.depth += 1
        elif tag in ("h2", "p"):
            self.kind, self.depth, self.buffer = tag, 1, []

    def handle_startendtag(self, tag, attrs):
        if self.kind and tag == "br":
            self.buffer.append(" ")

    def handle_endtag(self, tag):
        if self.kind:
            self.depth -= 1
            if self.depth == 0:
                self.records.append((self.kind, " ".join(" ".join(self.buffer).split())))
                self.kind, self.buffer = None, []

    def handle_data(self, data):
        if self.kind:
            self.buffer.append(data)


def parse_detail(html_text):
    doc = Detail()
    doc.feed(html_text)
    records = doc.records
    headings = [(i, value) for i, (kind, value) in enumerate(records) if kind == "h2" and value]
    if len(headings) != 1:
        raise ValueError("Page sans titre de concert unique")
    pos, title = headings[0]
    date_rows = [value for kind, value in records[:pos] if kind == "p" and
                 re.search(r"\b20\d\d\s*-\s*\d{1,2}\s*h\s*\d\d\b", unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower())]
    if len(date_rows) != 1:
        raise ValueError("Date et heure non explicites avant le titre")
    date_match = re.search(
        r"\b(\d{1,2})\s+([a-z]+)\s+(20\d{2})\s*-\s*([0-2]?\d)h([0-5]\d)\b",
        unicodedata.normalize("NFKD", date_rows[0]).encode("ascii", "ignore").decode("ascii").lower()
    )
    if not date_match:
        raise ValueError("Date française illisible")
    day, month, year, hour, minute = date_match.groups()
    if month not in MONTHS:
        raise ValueError("Mois inconnu")
    date = dt.date(int(year), MONTHS[month], int(day)).isoformat()
    if int(hour) > 23:
        raise ValueError("Heure invalide")
    following = [value for kind, value in records[pos+1:] if kind == "p" and value]
    if not following:
        raise ValueError("Genre absent du détail officiel")
    labels = [s.strip() for s in following[0].split(",") if s.strip()]
    tags = {norm(x) for x in labels} & GENRES
    if not tags:
        raise ValueError("Aucun genre métal, punk ou assimilé affiché")
    if "31000 toulouse" not in norm(" ".join(v for _, v in records)):
        raise ValueError("Adresse officielle de la salle absente")
    artists = []
    for line in following[1:]:
        m = re.match(r"^\s*[✘×✖]\s*(.+?)(?:\s*\(|$)", line)
        if m:
            artists.append(m.group(1).strip())
    return {"title": title, "date": date, "genres": labels, "acceptedGenreTags": tags,
            "artists": artists, "descriptionParagraphs": following[1:]}


# Le Rex sometimes writes an announced support band as "(+ GROUP) !". It is
# a named artist, not a guest placeholder. No blanket parenthesis stripping.
REX_NAMED_SUPPORT = re.compile(
    r"^(?P<lead>[^()]{3,100}?)\s+\(\s*\+\s*"
    r"(?P<support>[^()]{3,100}?)\s*\)\s*!?\s*$", re.I)


def artist_names(title):
    if BANNED.search(norm(title)):
        raise ValueError("Intitulé incomplet, annulé ou de type festival")
    named_support = REX_NAMED_SUPPORT.fullmatch(title)
    parts = ([named_support.group("lead").strip(),
              named_support.group("support").strip()]
             if named_support else
             [p.strip() for p in re.split(r"\s+(?:[+&]|et)\s+", title, flags=re.I)])
    if not parts or any(len(norm(x)) < 3 for x in parts):
        raise ValueError("Affiche impossible à séparer avec certitude")
    if len({norm(p) for p in parts}) != len(parts):
        raise ValueError("Artistes en double")
    return parts


def rex_promoter_confirms_bill(paragraphs, parts):
    """Require one explicit first-party promoter announcement of the FULL bill.

    Biographies, isolated name mentions and title-only discovery are never
    sufficient to introduce a previously unknown artist.
    """
    if len(parts) < 2 or not isinstance(paragraphs, list):
        return False
    def fold(value):
        return " ".join(unicodedata.normalize("NFKD", str(value).casefold())
                        .encode("ascii", "ignore").decode("ascii").split())
    exact_bill = re.compile(
        r"(?<![a-z0-9])" + r"\s*\+\s*".join(
            re.escape(fold(name)) for name in parts) + r"(?![a-z0-9])")
    promoter = re.compile(
        r"\b(?:invite|invitent|presente|presentent|annonce|annoncent)\b")
    for paragraph in paragraphs:
        content = fold(paragraph)
        for match in exact_bill.finditer(content):
            # The producer must introduce this exact, ordered, plus-separated
            # lineup in the same sentence, not in an unrelated historic bio.
            prefix = content[max(0, match.start() - 140):match.start()]
            if promoter.search(prefix) and not re.search(r"[.!?]\s", prefix):
                return True
    return False



def rex_visible_divs_after_title(html_text):
    """Visible leaf <div> descriptions after the official event <h2> only.

    The Rex uses both <p> and rich-text <div> blocks for its promoter copy.
    Do not accept scripts, templates, hidden descendants or text from a
    different item before the event title. The exact promoter-bill test still
    validates any extracted text; these lines alone never approve artists.
    """
    class VisibleDivs(html.parser.HTMLParser):
        INVISIBLE = {"script", "style", "template", "noscript", "svg"}

        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.after_h2 = False
            self.hidden_depth = 0
            self.stack = []
            self.lines = []

        def handle_starttag(self, tag, attrs):
            if tag in self.INVISIBLE:
                self.hidden_depth += 1
                return
            if self.hidden_depth:
                return
            if tag == "h2":
                self.after_h2 = True
            elif tag == "footer":
                self.after_h2 = False
            if tag == "div" and self.after_h2:
                attrs = dict(attrs)
                style = attrs.get("style") or ""
                hidden = (attrs.get("aria-hidden") == "true" or
                          "hidden" in attrs or
                          bool(re.search(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)\b",
                                         style, re.I)) or
                          bool(self.stack and self.stack[-1]["hidden"]))
                if self.stack:
                    self.stack[-1]["has_child_div"] = True
                self.stack.append({"parts": [], "has_child_div": False,
                                   "hidden": hidden})
            elif tag == "br" and self.stack:
                self.stack[-1]["parts"].append(" ")

        def handle_data(self, data):
            if self.after_h2 and not self.hidden_depth and self.stack:
                self.stack[-1]["parts"].append(data)

        def handle_endtag(self, tag):
            if tag in self.INVISIBLE:
                self.hidden_depth = max(0, self.hidden_depth - 1)
                return
            if self.hidden_depth:
                return
            if tag == "div" and self.stack:
                item = self.stack.pop()
                if not item["has_child_div"] and not item["hidden"]:
                    value = " ".join(" ".join(item["parts"]).split())
                    if value:
                        self.lines.append(value)
            if tag == "footer":
                self.after_h2 = False

    parser = VisibleDivs()
    parser.feed(html_text)
    return parser.lines


def verify(candidate, html_text, catalogue, today):
    # Admission is based on a frozen, code-reviewed source-wide contract;
    # untrusted candidate URLs or discovery labels NEVER import a module.
    source = candidate.get("source")
    if not isinstance(source, str) or source not in VERIFIER_SPECS:
        raise ValueError("Seuls les détails officiels des sources agréées sont admissibles à ce stade")
    if source == "agenda_officiel_atabal_detail":
        import atabal_recheck
        # Preserve Atabal's previously signed pilot. Every other first-party
        # bill still uses its separate full-header multi-artist verifier.
        if candidate.get("sourceUrl") == atabal_recheck.URL:
            return atabal_recheck.verify(candidate, html_text, catalogue, today)
        import atabal_multi_recheck
        return atabal_multi_recheck.verify(candidate, html_text, catalogue, today)
    if source != "agenda_officiel_rex_genre":
        # The exact module is fixed by trusted source code (not remote JSON).
        handler_module = VERIFIER_SPECS[source].module
        if handler_module is None:
            raise ValueError("Vérificateur officiellement déclaré sans module")
        return importlib.import_module(handler_module).verify(
            candidate, html_text, catalogue, today)
    # Rex: original strict first-party date, venue, genre and full-bill proof
    # are intentionally kept below, bit-for-bit.
    if candidate.get("reviewBucket") != "genre_tag_review" or candidate.get("possibleExistingConcert"):
        raise ValueError("Piste incertaine, doublon probable ou festival")
    if candidate.get("publicationAllowed") is not False or candidate.get("reviewRequired") is not True:
        raise ValueError("Provenance découverte inattendue")
    if candidate.get("venue") != "Le Rex" or norm(candidate.get("city")) != "toulouse":
        raise ValueError("Salle ou ville incohérente")
    url = candidate.get("sourceUrl", "")
    target = urlsplit(url)
    if target.scheme != "https" or target.hostname != ALLOWED_HOST or not target.path.startswith("/fr/programmation/") or target.path.count("/") < 4:
        raise ValueError("URL individuelle officielle exigée")
    detail = parse_detail(html_text)
    if norm(detail["title"]) != norm(candidate.get("name")):
        raise ValueError("Intitulé différent entre découverte et fiche")
    if detail["date"] != candidate.get("date") or dt.date.fromisoformat(detail["date"]) < today:
        raise ValueError("Date incohérente ou passée")
    if not ({norm(x) for x in (candidate.get("classification") or [])} & detail["acceptedGenreTags"]):
        raise ValueError("Genre incompatible avec la découverte")
    if (BANNED_STATUS.search(norm(detail["title"]))
            or BANNED_STATUS.search(norm(html_text[:20000]))):
        raise ValueError("Indice d'annulation ou de festival")
    unnamed_guest = UNNAMED_GUEST_SUFFIX.search(detail["title"]) is not None
    verified_title = (UNNAMED_GUEST_SUFFIX.sub("", detail["title"]).strip()
                      if unnamed_guest else detail["title"])
    parts = artist_names(verified_title)
    lineup = {norm(a) for a in detail["artists"]}
    known_names = {norm(a["name"]) for a in catalogue["artists"]}
    promoter_bill = (not lineup and rex_promoter_confirms_bill(
        detail["descriptionParagraphs"] + rex_visible_divs_after_title(html_text), parts))
    # Some first-party pages expose the complete named lineup only as their H2.
    # That is acceptable only if EVERY band name is already identified in the
    # catalogue, removing the risk of inventing a new artist from an event title.
    if lineup:
        if any(norm(a) not in lineup for a in parts):
            raise ValueError("Programmation non corroborée dans la fiche détaillée")
    elif any(norm(a) not in known_names for a in parts) and not promoter_bill:
        raise ValueError("Affiche sans détail d'artistes et artiste inconnu du catalogue")
    venue = next((v for v in catalogue["venues"] if v["id"] == REX_VENUE), None)
    if not venue or norm(venue.get("city")) != "toulouse":
        raise ValueError("Salle inconnue du catalogue")
    artists = {}
    aliases = set()
    for a in catalogue["artists"]:
        artists.setdefault(norm(a["name"]), []).append(a)
        aliases.update(norm(alias) for alias in a.get("aliases", [])
                       if isinstance(alias, str) and norm(alias))
    ids, fresh = [], []
    for name in parts:
        matches = artists.get(norm(name), [])
        if len(matches) > 1:
            raise ValueError("Identité d'artiste ambiguë")
        if not matches and norm(name) in aliases:
            raise ValueError("Alias déjà répertorié : revue nominative nécessaire")
        aid = matches[0]["id"] if matches else slug(name)
        if not aid or (not matches and any(a["id"] == aid for a in catalogue["artists"])):
            raise ValueError("Collision d'identifiant artiste")
        ids.append(aid)
        if not matches:
            fresh.append({"id": aid, "name": name})
    if len(set(ids)) != len(ids):
        raise ValueError("IDs d'artistes répétés")
    # Same date, venue and an overlapping artist: no second listing.
    if any(e["date"] == detail["date"] and e["venueId"] == REX_VENUE and
           set(e["artistIds"]) & set(ids) for e in catalogue["events"]):
        raise ValueError("Concert déjà référencé pour cette salle et ce jour")
    event_id = "go-c-" + detail["date"].replace("-", "") + "-toulouse-" + slug(parts[0])
    if any(e["id"] == event_id for e in catalogue["events"]):
        raise ValueError("ID de concert déjà présent")
    return {
        "reviewDecision": "approved",
        "reviewedBy": "automated-official-recheck",
        "reviewedAt": today.isoformat(),
        "officialEvidence": [{
            "url": url, "proofType": "official-organizer-or-venue",
            "checkedAt": today.isoformat(), "checkedFields": ["artists", "date", "venue", "genre"],
            "notes": ("Relecture automatisée d'une fiche individuelle officielle; dates, genres et programmation réconciliés."
                      + (" Guest non nommé omis : aucun artiste créé ou présumé."
                         if unnamed_guest else "")),
            **({"sourceStructure": "rex-promoter-exact-bill",
                "officialArtistNames": parts} if promoter_bill else {})
        }],
        "event": {
            "id": event_id, "title": verified_title, "date": detail["date"],
            "time": None, "artistIds": ids, "venueId": REX_VENUE,
            "genres": detail["genres"], "status": "confirmed", "officialUrl": url,
            "sourceType": "salle", "organizer": "Le Rex"
        },
        "newArtists": fresh
    }


def download_official(url, robots_cache):
    if not discover.robots_allow(url, robots_cache):
        raise ValueError("robots.txt interdit la récupération")
    response = Request(url, headers={"User-Agent": discover.AGENT})
    with urlopen(response, timeout=12) as r:
        # Generic source-wide venues cannot delegate their event proof through
        # any redirect, even to another already trusted official domain.
        original_host = urlsplit(url).hostname
        if original_host in ("larayonne.org", "lemetronum.fr"):
            if (urlsplit(r.geturl()).hostname != original_host or
                    r.geturl().rstrip("/") != url.rstrip("/")):
                raise ValueError("Redirection générique hors fiche officielle")
        if urlsplit(r.geturl()).scheme != "https" or urlsplit(r.geturl()).hostname not in (ALLOWED_HOST, "lemolotov.com", "www.leferrailleur.fr", "leferrailleur.fr", "www.backstage-btm.com", "www.atabal-biarritz.fr", "theblacklab.fr", "www.artefact.org", "rockstore.fr", "www.rockstore.fr", "www.bateauivre.coop", "bonjour-minuit.fr", "bigbandcafe.com", "caveauxpoetes.com", "larayonne.org", "lemetronum.fr"):
            raise ValueError("Redirection hors domaine officiel")
        raw = r.read(500_001)
        if len(raw) > 500_000:
            raise ValueError("Page trop volumineuse")
        return raw.decode(r.headers.get_content_charset() or "utf-8", errors="replace")


def process(registry, catalogue, approvals, today, fetch=download_official,
            limit=10, site_fetch=None):
    if approvals.get("schema") != "grossesondes.concert.approvals.v1":
        raise ValueError("Fichier d'approbations inattendu")
    if catalogue.get("schemaVersion") != 1 or catalogue.get("mode") != "preview-public-unlisted":
        raise ValueError("Catalogue inattendu")
    out = copy.deepcopy(approvals)
    catalogue = copy.deepcopy(catalogue)
    known = {x["event"]["id"] for x in out["approvals"]}
    # The registry is cumulative, so a published lead can remain pending there
    # forever. Skip an EXACT officially approved URL + event date before any
    # network call; a different date at the same URL still gets rechecked.
    # The separate published-watch workflow monitors cancellations/changes.
    approved_pairs = {
        (a["event"].get("officialUrl"), a["event"].get("date"))
        for a in out["approvals"]
        if a.get("reviewDecision") == "approved" and isinstance(a.get("event"), dict)
    }
    items = list(registry.get("items", {}).values())
    # Historical rows without a stability counter stay quarantined until
    # reobserved with the SAME identity on two distinct UTC calendar days.
    # Raw observations can be dozens of same-day duplicate scans.
    candidates = [i for i in items if
                  i.get("stableObservations", 0) >= 2 and
                  isinstance(i.get("candidate", {}).get("source"), str) and
                  ((i.get("candidate", {}).get("source") in VERIFIER_SPECS
                    and i.get("candidate", {}).get("reviewBucket") == "genre_tag_review")
                   or (i.get("candidate", {}).get("source")
                       in {"artist_official_tour", "promoter_official_tour"}
                       and i.get("candidate", {}).get("newVenueToReview") is True
                       and i.get("candidate", {}).get("reviewBucket")
                       in {"genre_tag_review", "genre_unknown"}))]
    # A private human decision is permanent: never reconsider a rejected or
    # superseded candidate even if discovery keeps observing the same ID.
    reviewable = [i for i in candidates if i.get("status", "pending_review") == "pending_review"]
    skipped_decided = len(candidates) - len(reviewable)
    unapproved = [i for i in reviewable if
                  (i["candidate"].get("sourceUrl"), i["candidate"].get("date"))
                  not in approved_pairs]
    already_approved_skipped = len(reviewable) - len(unapproved)
    # Conserver les dates passées dans l'historique privé sans refaire de réseau.
    # Un format invalide continue d'être inspecté et retenu, jamais ignoré.
    def is_expired(row):
        try:
            return dt.date.fromisoformat(row["candidate"].get("date")) < today
        except (TypeError, ValueError):
            return False
    expired_skipped = sum(is_expired(i) for i in unapproved)
    eligible = [i for i in unapproved if not is_expired(i)]
    eligible.sort(key=lambda x: x["candidate"].get("candidateId", ""))
    # Rotation ensures every eligible candidate gets checked over successive days.
    offset = (today.toordinal() * limit) % len(eligible) if eligible else 0
    chosen = [eligible[(offset + i) % len(eligible)] for i in range(min(limit, len(eligible)))]
    results, cache, new, sites = [], {}, [], []
    for row in chosen:
        c = row["candidate"]
        try:
            if c.get("source") in {
                    "agenda_officiel_structuré",
                    "agenda_officiel_visible_bill",
            }:
                # Untrusted registry hosts must not even reach the network.
                # Both generic verifiers use the same reviewed venue manifest.
                import generic_music_event
                if generic_music_event.trusted_spec(c) is None:
                    raise ValueError("Salle générique non agréée : pas de réseau")
            site = None
            if c["source"] in {"artist_official_tour", "promoter_official_tour"}:
                # Candidate authority is checked against the committed artist/
                # promoter registry BEFORE the first network request. A new
                # physical site requires TWO independently fetched proofs.
                import event_site_pair_recheck as site_review
                def do_fetch(url, cap):
                    if site_fetch is not None:
                        return site_fetch(url, cap)
                    return site_review.fetch_verified(url, cap, cache)
                approval, site = site_review.verify(
                    c, catalogue, today, fetch=do_fetch)
                if not isinstance(out.get("venueApprovals"), list):
                    raise ValueError("Registre privé des lieux absent")
                if any(v.get("id") == site["venue"]["id"]
                       for v in catalogue.get("venues", [])):
                    raise ValueError("Site géographique déjà référencé")
            else:
                html_text = fetch(c["sourceUrl"], cache)
                approval = verify(c, html_text, catalogue, today)
            if approval["event"]["id"] in known:
                raise ValueError("Déjà approuvé")
            # Add to the working catalogue so same-run collisions cannot pass.
            e = approval["event"]
            if site is not None:
                # Pair is append-only. The real approval_preflight and cloud
                # publisher must accept BOTH or persist NEITHER.
                out["venueApprovals"].append(site)
                catalogue["venues"].append(site["venue"])
                sites.append(site["venue"]["id"])
            for a in approval["newArtists"]:
                catalogue["artists"].append(a)
            catalogue["events"].append(e)
            out["approvals"].append(approval)
            known.add(e["id"])
            new.append(e["id"])
            results.append({"candidateId": c["candidateId"], "status": "approved", "id": e["id"]})
        except Exception as ex:
            results.append({"candidateId": c.get("candidateId"), "status": "held",
                            "reason": str(ex)[:180]})
    return out, {"evaluated": len(chosen), "totalEligible": len(eligible),
                 "decidedSkipped": skipped_decided,
                 "alreadyApprovedSkipped": already_approved_skipped,
                 "expiredSkipped": expired_skipped,
                 "newApprovals": new, "newSiteApprovals": sites,
                 "held": [r for r in results if r["status"] == "held"],
                 "results": results}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--registry", required=True)
    p.add_argument("--catalogue", default=CLOUD)
    p.add_argument("--approvals", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--report", required=True)
    p.add_argument("--apply", action="store_true",
                   help="Write approved.json only after explicit CI feature gate")
    args = p.parse_args()
    def load(value):
        if str(value).startswith("https://"):
            with urlopen(value, timeout=18) as r:
                return json.load(r)
        return json.loads(Path(value).read_text(encoding="utf-8"))
    original = load(args.approvals)
    reviewed, report = process(load(args.registry), load(args.catalogue), original,
                               discover.today_fr())
    Path(args.out).write_text(json.dumps(reviewed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.apply and report["newApprovals"]:
        Path(args.approvals).write_text(
            json.dumps(reviewed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps({"evaluated": report["evaluated"],
                      "newApprovals": len(report["newApprovals"]),
                      "held": len(report["held"]), "apply": args.apply}, ensure_ascii=False))


if __name__ == "__main__":
    main()
