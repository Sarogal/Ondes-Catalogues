"""Generic, event-bound first-party lineup correction contract.

A published event is the authority boundary: its *original signed approval*
pins the event URL, physical venue, date and existing artists. A private
correction never grants a new domain any authority. On first application the
publisher makes a fresh HTTPS DNS-pinned, robots-aware request and independently
parses the named bill. Already-applied patches replay from the persistent
signed ledger without depending on a past event remaining online.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
FIELDS = frozenset({
    "eventId", "reviewDecision", "reviewedBy", "reviewedAt",
    "date", "venueId", "officialUrl", "oldArtistIds", "artistIds",
    "title", "newArtists", "officialEvidence",
})
PROOF_FIELDS = frozenset({
    "url", "proofType", "checkedAt", "checkedFields", "confirmedArtists",
})
EVENT_CORE = ("id", "date", "venueId", "officialUrl")
ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def require(ok, reason):
    if not ok:
        raise ValueError("Lineup patch refused: " + reason)


def normal(value):
    value = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return " ".join(re.findall(
        r"[a-z0-9]+", value.encode("ascii", "ignore").decode("ascii")))


def network_fetch(url):
    """Reuse the security-reviewed #575/#582 transport, not urllib.urlopen."""
    source_dir = str(ROOT / "automation/concerts")
    if source_dir not in sys.path:
        sys.path.insert(0, source_dir)
    import source_evidence_probe
    return source_evidence_probe.safe_fetch(url, {})


def official_bill(html, event, venue, artists):
    source_dir = str(ROOT / "automation/concerts")
    if source_dir not in sys.path:
        sys.path.insert(0, source_dir)
    import published_lineup_audit
    return published_lineup_audit.bill_from_page(
        html, event, venue, {a["id"]: a for a in artists})


def _match_artist(name, all_artists):
    hits = []
    for artist in all_artists:
        aliases = [artist.get("name")] + (artist.get("aliases") or [])
        if normal(name) in {normal(a) for a in aliases if isinstance(a, str)}:
            hits.append(artist["id"])
    require(len(hits) == 1, "ambiguous or unknown artist in official bill")
    return hits[0]


def plan(row, signed_original, current, today):
    """Validate the complete immutable patch envelope; no network yet.

    The plan is not sufficient to publish a new patch. apply() also requires
    a fresh, matching official page. Replayed corrections still validate this
    envelope and the exact previously published result.
    """
    require(isinstance(row, dict) and set(row) == FIELDS,
            "unexpected fields in correction")
    require(isinstance(signed_original, dict)
            and signed_original.get("reviewDecision") == "approved"
            and isinstance(signed_original.get("event"), dict),
            "missing original signed approval")
    base = signed_original["event"]
    require(row["reviewDecision"] == "approved"
            and row["reviewedBy"] in (
                "independent-official-verifier", "automated-official-recheck"),
            "no independent review")
    try:
        checked = dt.date.fromisoformat(row["reviewedAt"])
        require(checked <= today, "future signature")
    except (ValueError, TypeError):
        raise ValueError("Lineup patch refused: invalid review date")
    require(all(row[k if k != "id" else "eventId"] == base[k]
                for k in EVENT_CORE), "event/date/venue/official URL changed")
    uri = urlsplit(row["officialUrl"])
    require(uri.scheme == "https" and uri.hostname and not uri.username
            and not uri.password and uri.port is None and not uri.fragment,
            "unsafe official URL")
    require(isinstance(base.get("artistIds"), list) and base["artistIds"],
            "unsigned original artist bill")
    require(row["oldArtistIds"] == base["artistIds"],
            "old artist IDs differ from original signed approval")
    new_ids = row["artistIds"]
    require(isinstance(new_ids, list) and len(new_ids) > len(base["artistIds"])
            and all(isinstance(i, str) and ID.fullmatch(i) for i in new_ids)
            and len(set(new_ids)) == len(new_ids)
            and all(i in new_ids for i in base["artistIds"]),
            "invalid new artist set")
    require(isinstance(row["newArtists"], list), "new artist list missing")
    existing = {a["id"]: a for a in current["artists"]}
    fresh = {}
    for artist in row["newArtists"]:
        require(isinstance(artist, dict)
                and set(artist) == {"id", "name", "aliases"}
                and isinstance(artist["id"], str)
                and ID.fullmatch(artist["id"])
                and artist["id"] in new_ids
                and artist["id"] not in existing and artist["id"] not in fresh
                and isinstance(artist["name"], str)
                and 2 <= len(artist["name"].strip()) <= 120
                and artist["aliases"] == [],
                "new artist identity is not independently bound")
        require(not any(normal(artist["name"]) in
                        {normal(a.get("name"))}
                        | {normal(x) for x in (a.get("aliases") or [])}
                        for a in list(existing.values()) + list(fresh.values())),
                "artist already exists under another identity")
        fresh[artist["id"]] = artist
    require(all(aid in existing or aid in fresh for aid in new_ids),
            "new or existing artist missing")
    require(set(fresh) == set(new_ids) - set(existing),
            "unexpected artist creation")
    proofs = row["officialEvidence"]
    require(isinstance(proofs, list) and len(proofs) == 1
            and isinstance(proofs[0], dict)
            and set(proofs[0]) == PROOF_FIELDS,
            "official named-bill proof absent")
    proof = proofs[0]
    require(proof["url"] == row["officialUrl"]
            and proof["proofType"] == "official-published-lineup-v1"
            and proof["checkedAt"] == row["reviewedAt"]
            and set(proof["checkedFields"]) == {"artists", "date", "venue"}
            and isinstance(proof["confirmedArtists"], list)
            and len(proof["confirmedArtists"]) == len(new_ids)
            and all(isinstance(n, str) and 2 <= len(n.strip()) <= 120
                    for n in proof["confirmedArtists"]),
            "proof does not bind all named artists, date and place")
    all_artists = list(existing.values()) + list(fresh.values())
    require([_match_artist(name, all_artists)
             for name in proof["confirmedArtists"]] == new_ids,
            "signed names cannot be reconciled with artist IDs")
    require(isinstance(row["title"], str)
            and normal(row["title"]) ==
                normal(" + ".join(proof["confirmedArtists"])),
            "title invents or omits named artists")
    return {"reviewedAt": row["reviewedAt"],
            "artistIds": list(new_ids), "title": row["title"],
            "officialNames": list(proof["confirmedArtists"]),
            "newArtists": list(fresh.values())}


def expected(event, plan_row):
    """Calculate the unique allowed result from a signed old-state event."""
    result = dict(event)
    result["artistIds"] = list(plan_row["artistIds"])
    result["title"] = plan_row["title"]
    result["lastVerified"] = plan_row["reviewedAt"]
    result["history"] = list(event.get("history") or []) + [{
        "date": plan_row["reviewedAt"],
        "change": "Programmation complétée après nouvelle vérification de la fiche officielle",
    }]
    return result


def apply(row, signed_original, catalogue, today, *, fetch=None):
    """Return new catalogue and whether it changed; never mutate inputs."""
    import copy
    result = copy.deepcopy(catalogue)
    signed = plan(row, signed_original, result, today)
    rows = [e for e in result["events"] if e.get("id") == row["eventId"]]
    require(len(rows) == 1, "published event absent or duplicate")
    old = rows[0]
    base = signed_original["event"]
    require(all(old.get(k) == base.get(k) for k in
                ("id", "date", "venueId", "officialUrl", "genres",
                 "status", "sourceType")), "protected event identity changed")
    already = (old["artistIds"] == signed["artistIds"]
               and old["title"] == signed["title"])
    if already:
        require(old.get("lastVerified") == signed["reviewedAt"]
                and old.get("history")
                and old["history"][-1]["change"] ==
                    "Programmation complétée après nouvelle vérification de la fiche officielle",
                "patched event differs from approved result")
        for artist in signed["newArtists"]:
            require(artist["id"] in {a["id"] for a in result["artists"]},
                    "previously published artist missing")
        return result, False, 0
    require(old["artistIds"] == row["oldArtistIds"]
            and old["title"] == base["title"], "current event is not signed old state")
    require(dt.date.fromisoformat(row["date"]) >= today
            and (today - dt.date.fromisoformat(row["reviewedAt"])).days <= 7,
            "new patch needs current fresh official proof")
    venue_rows = [v for v in result["venues"] if v["id"] == row["venueId"]]
    require(len(venue_rows) == 1, "physical venue not in existing catalogue")
    source = fetch if fetch is not None else network_fetch
    bill = official_bill(source(row["officialUrl"]), old, venue_rows[0],
                         result["artists"])
    require(bill["officialNames"] == signed["officialNames"],
            "fresh page disagrees with signed bill")
    # Never borrow a name from recommendations, biographies or another date.
    new_names = [normal(a.get("name")) for a in signed["newArtists"]]
    require(all(name in {normal(n) for n in bill["missingNamedArtists"]}
                for name in new_names), "new artists not on the official bill")
    for artist in signed["newArtists"]:
        result["artists"].append(copy.deepcopy(artist))
    updated = expected(old, signed)
    index = next(i for i, event in enumerate(result["events"])
                 if event["id"] == row["eventId"])
    result["events"][index] = updated
    return result, True, len(signed["newArtists"])
