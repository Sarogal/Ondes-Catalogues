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
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import discover

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
BANNED = re.compile(r"\b(guest|invite|surprise|tba|a confirmer|festival|fest|open air|"
                    r"annule|annulee|report[eé]|postponed|cancelled|sold out)\b", re.I)


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
            "artists": artists}


def artist_names(title):
    if BANNED.search(norm(title)):
        raise ValueError("Intitulé incomplet, annulé ou de type festival")
    parts = [p.strip() for p in re.split(r"\s+(?:[+&]|et)\s+", title, flags=re.I)]
    if not 1 <= len(parts) <= 5 or any(len(norm(x)) < 3 for x in parts):
        raise ValueError("Affiche impossible à séparer avec certitude")
    if len({norm(p) for p in parts}) != len(parts):
        raise ValueError("Artistes en double")
    return parts


def verify(candidate, html_text, catalogue, today):
    if candidate.get("source") == "bateau_ivre_official_detail_review":
        import bateau_ivre_official_recheck
        return bateau_ivre_official_recheck.verify(candidate, html_text, catalogue, today)
    if candidate.get("source") == "agenda_officiel_rockstore_detail_review":
        import rockstore_official_recheck
        return rockstore_official_recheck.verify(candidate, html_text, catalogue, today)
    if candidate.get("source") == "agenda_officiel_laiterie_detail_review":
        import laiterie_official_recheck
        return laiterie_official_recheck.verify(candidate, html_text, catalogue, today)
    if candidate.get("source") == "agenda_officiel_blacklab_detail_review":
        import blacklab_official_recheck
        return blacklab_official_recheck.verify(candidate, html_text, catalogue, today)
    if candidate.get("source") == "agenda_officiel_atabal_detail":
        import atabal_recheck
        # Retain the previously signed pilot unchanged; all other bills pass
        # a separate, strict header + named artist section verifier.
        if candidate.get("sourceUrl") == atabal_recheck.URL:
            return atabal_recheck.verify(candidate, html_text, catalogue, today)
        import atabal_multi_recheck
        return atabal_multi_recheck.verify(candidate, html_text, catalogue, today)
    if candidate.get("source") == "agenda_officiel_backstage_detail":
        import backstage_recheck
        return backstage_recheck.verify(candidate, html_text, catalogue, today)
    if candidate.get("source") == "agenda_officiel_ferrailleur_genre":
        # Never use an agenda card as an approval: re-fetch its own event page.
        import ferrailleur_official
        return ferrailleur_official.verify(candidate, html_text, catalogue, today)
    if candidate.get("source") == "agenda_officiel_molotov_genre":
        # Imported only when needed to avoid a circular module dependency.
        import molotov_official
        return molotov_official.verify(candidate, html_text, catalogue, today)
    if candidate.get("source") != "agenda_officiel_rex_genre":
        raise ValueError("Seul le détail officiel Le Rex est admissible à ce stade")
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
    if BANNED.search(norm(detail["title"])) or BANNED.search(norm(html_text[:20000])):
        raise ValueError("Indice d'annulation ou de festival")
    parts = artist_names(detail["title"])
    lineup = {norm(a) for a in detail["artists"]}
    known_names = {norm(a["name"]) for a in catalogue["artists"]}
    # Some first-party pages expose the complete named lineup only as their H2.
    # That is acceptable only if EVERY band name is already identified in the
    # catalogue, removing the risk of inventing a new artist from an event title.
    if lineup:
        if any(norm(a) not in lineup for a in parts):
            raise ValueError("Programmation non corroborée dans la fiche détaillée")
    elif any(norm(a) not in known_names for a in parts):
        raise ValueError("Affiche sans détail d'artistes et artiste inconnu du catalogue")
    venue = next((v for v in catalogue["venues"] if v["id"] == REX_VENUE), None)
    if not venue or norm(venue.get("city")) != "toulouse":
        raise ValueError("Salle inconnue du catalogue")
    artists = {}
    for a in catalogue["artists"]:
        artists.setdefault(norm(a["name"]), []).append(a)
    ids, fresh = [], []
    for name in parts:
        matches = artists.get(norm(name), [])
        if len(matches) > 1:
            raise ValueError("Identité d'artiste ambiguë")
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
            "notes": "Relecture automatisée d'une fiche individuelle officielle; dates, genres et programmation réconciliés."
        }],
        "event": {
            "id": event_id, "title": detail["title"], "date": detail["date"],
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
        if urlsplit(r.geturl()).scheme != "https" or urlsplit(r.geturl()).hostname not in (ALLOWED_HOST, "lemolotov.com", "www.leferrailleur.fr", "leferrailleur.fr", "www.backstage-btm.com", "www.atabal-biarritz.fr", "theblacklab.fr", "www.artefact.org", "rockstore.fr", "www.rockstore.fr", "www.bateauivre.coop"):
            raise ValueError("Redirection hors domaine officiel")
        raw = r.read(500_001)
        if len(raw) > 500_000:
            raise ValueError("Page trop volumineuse")
        return raw.decode(r.headers.get_content_charset() or "utf-8", errors="replace")


def process(registry, catalogue, approvals, today, fetch=download_official, limit=10):
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
                  i.get("candidate", {}).get("source") in
                  ("agenda_officiel_rex_genre", "agenda_officiel_molotov_genre",
                   "agenda_officiel_ferrailleur_genre",
                   "agenda_officiel_backstage_detail",
                   "agenda_officiel_atabal_detail",
                   "agenda_officiel_blacklab_detail_review",
                   "agenda_officiel_laiterie_detail_review",
                   "agenda_officiel_rockstore_detail_review",
                   "bateau_ivre_official_detail_review") and
                  i.get("candidate", {}).get("reviewBucket") == "genre_tag_review"]
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
    results, cache, new = [], {}, []
    for row in chosen:
        c = row["candidate"]
        try:
            html_text = fetch(c["sourceUrl"], cache)
            approval = verify(c, html_text, catalogue, today)
            if approval["event"]["id"] in known:
                raise ValueError("Déjà approuvé")
            # Add to the working catalogue so same-run collisions cannot pass.
            e = approval["event"]
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
                 "newApprovals": new, "held": [r for r in results if r["status"] == "held"],
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
