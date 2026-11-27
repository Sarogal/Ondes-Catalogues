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
from scripts import concert_openagenda_bill_identity as bill_identity

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
PROMOTIONAL_PROOF = "official-published-promotional-identity-v1"
ADDITIVE_PROOF = "official-published-lineup-v1"
ADDITIVE_HISTORY = "Programmation complétée après nouvelle vérification de la fiche officielle"
PROMOTIONAL_HISTORY = "Identité artistique rectifiée après nouvelle vérification de la fiche officielle"
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


def promotional_source(signed_original, current):
    """Bind a possible name correction to the immutable original OA proof.

    Return the UID-bound export and expected cleaned names. This is only a
    candidate mapping until the real original announcement is fetched.
    """
    from automation.concerts import openagenda_official_concert as oa
    require(isinstance(signed_original, dict)
            and signed_original.get("reviewDecision") == "approved"
            and signed_original.get("reviewedBy") in (
                "independent-official-verifier", "automated-official-recheck"),
            "original independent approval absent")
    event = signed_original.get("event")
    evidence = signed_original.get("officialEvidence")
    require(isinstance(event, dict) and isinstance(evidence, list)
            and all(isinstance(p, dict) for p in evidence),
            "original OpenAgenda proof absent")
    venues = [v for v in current["venues"] if v["id"] == event.get("venueId")]
    require(len(venues) == 1, "physical venue not in existing catalogue")
    venue = venues[0]
    if len(evidence) == 1:
        proof = evidence[0]
        require(proof.get("proofType") ==
                "dynamic-existing-venue-openagenda-single-source-v1"
                and proof.get("officialOpenAgendaEventUrl") == event.get("officialUrl"),
                "original existing-venue OpenAgenda proof required")
    elif len(evidence) == 2:
        # Historical paired site has already passed the independent Publisher.
        # Reconstruct the same signed binding, never grant new site authority.
        from scripts import concert_dynamic_new_site_source as site
        proof = evidence[1]
        require(evidence[0].get("proofType") == "official-organizer-or-venue"
                and evidence[0].get("url") == event.get("officialUrl")
                and evidence[0].get("checkedAt") == signed_original.get("reviewedAt")
                and evidence[0].get("checkedFields") == ["artists", "date", "venue", "genre"]
                and set(proof) == site.OPENAGENDA_NEW_FIELDS
                and proof.get("proofType") == site.OPENAGENDA_NEW_PROFILE
                and proof.get("checkedFields") == site.OPENAGENDA_NEW_CHECKED
                and proof.get("namedOsmUrl") == venue.get("geoSource")
                and event.get("sourceType") == "organisateur"
                and event.get("genres") == proof.get("officialGenreLabels"),
                "original new-site OpenAgenda proof required")
    else:
        raise ValueError("Lineup patch refused: original OpenAgenda proof absent")
    require(proof.get("url") == event.get("officialUrl")
            and proof.get("checkedAt") == signed_original.get("reviewedAt")
            and oa.is_openagenda_event_url(event.get("officialUrl")),
            "original UID-bound OpenAgenda proof required")
    raw = proof.get("officialArtistNames")
    ids = event.get("artistIds")
    require(isinstance(raw, list) and isinstance(ids, list)
            and bool(ids) and len(raw) == len(ids)
            and len(set(ids)) == len(ids)
            and all(isinstance(name, str) and name.strip() for name in raw),
            "original artist names not bound")
    artists = {a["id"]: a for a in current["artists"]}
    require(all(aid in artists and normal(artists[aid].get("name")) == normal(name)
                for aid, name in zip(ids, raw)),
            "original published identities changed")
    candidates = [oa.promotional_artist_candidate(name)
                  or oa.city_artist_candidate(name, venue.get("city"))
                  or name for name in raw]
    require(any(normal(before) != normal(after)
                for before, after in zip(raw, candidates))
            and len({normal(name) for name in candidates}) == len(candidates),
            "no unambiguous promotional identity correction")
    uid = proof.get("officialOpenAgendaUid")
    eid = proof.get("officialOpenAgendaEventUid")
    url = oa.official_export_url(uid, eid)
    return {"url": url, "agendaUid": uid, "eventUid": eid,
            "names": candidates, "originalNames": raw}


def recheck_promotional(signed_original, current, *, fetch=None):
    """Fresh independent export; the cleaned name must be explicitly proven."""
    from automation.concerts import openagenda_official_concert as oa
    source = promotional_source(signed_original, current)
    event = signed_original["event"]
    venues = [v for v in current["venues"] if v["id"] == event["venueId"]]
    require(len(venues) == 1, "physical venue not in existing catalogue")
    fetch = fetch if fetch is not None else network_fetch
    names, _genres = oa.verified_export(
        fetch(source["url"]), event["officialUrl"], event["date"], venues[0],
        agenda_uid=source["agendaUid"], event_uid=source["eventUid"])
    require(list(map(normal, names)) == list(map(normal, source["names"])),
            "fresh original export disagrees with promotional identities")
    return names


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
    proofs = row["officialEvidence"]
    require(isinstance(proofs, list) and len(proofs) == 1
            and isinstance(proofs[0], dict)
            and set(proofs[0]) == PROOF_FIELDS,
            "official named-bill proof absent")
    proof = proofs[0]
    promotional = proof["proofType"] == PROMOTIONAL_PROOF
    repaired_bill = proof["proofType"] == bill_identity.PROOF
    require(promotional or repaired_bill or proof["proofType"] == ADDITIVE_PROOF,
            "unsupported correction proof")
    new_ids = row["artistIds"]
    require(isinstance(new_ids, list)
            and all(isinstance(i, str) and ID.fullmatch(i) for i in new_ids)
            and len(set(new_ids)) == len(new_ids),
            "invalid new artist set")
    if promotional:
        source = promotional_source(signed_original, current)
        require(len(new_ids) == len(base["artistIds"])
                and new_ids != base["artistIds"],
                "promotional correction must be one-to-one")
        for old_id, new_id, old_name, name in zip(
                base["artistIds"], new_ids, source["originalNames"], source["names"]):
            require((old_id == new_id) == (normal(old_name) == normal(name)),
                    "non-promotional identity changed or promotional identity retained")
    elif repaired_bill:
        source = bill_identity.source(signed_original, current)
        require(bool(new_ids) and new_ids != base["artistIds"],
                "bill repair must change the defective artist set")
    else:
        require(len(new_ids) > len(base["artistIds"])
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
                and artist["id"] not in fresh
                and isinstance(artist["name"], str)
                and 2 <= len(artist["name"].strip()) <= 120
                and artist["aliases"] == [],
                "new artist identity is not independently bound")
        if artist["id"] in existing:
            require(existing[artist["id"]] == artist,
                    "persisted new artist changed after publication")
            continue
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
    require(proof["url"] == row["officialUrl"]
            and proof["checkedAt"] == row["reviewedAt"]
            and set(proof["checkedFields"]) == {"artists", "date", "venue"}
            and isinstance(proof["confirmedArtists"], list)
            and len(proof["confirmedArtists"]) == len(new_ids)
            and all(isinstance(n, str) and 2 <= len(n.strip()) <= 120
                    for n in proof["confirmedArtists"]),
            "proof does not bind all named artists, date and place")
    if promotional or repaired_bill:
        require(list(map(normal, proof["confirmedArtists"])) ==
                list(map(normal, source["names"])),
                "correction does not match the signed promotional mapping")
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
            "newArtists": list(fresh.values()),
            "promotional": promotional, "repairedBill": repaired_bill,
            "historyChange": PROMOTIONAL_HISTORY if (promotional or repaired_bill) else ADDITIVE_HISTORY}


def expected(event, plan_row):
    """Calculate the unique allowed result from a signed old-state event."""
    result = dict(event)
    result["artistIds"] = list(plan_row["artistIds"])
    result["title"] = plan_row["title"]
    result["lastVerified"] = plan_row["reviewedAt"]
    result["history"] = list(event.get("history") or []) + [{
        "date": plan_row["reviewedAt"],
        "change": plan_row["historyChange"],
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
                    signed["historyChange"],
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
    if signed["promotional"]:
        names = recheck_promotional(signed_original, result, fetch=source)
        require(list(map(normal, names)) == list(map(normal, signed["officialNames"])),
                "fresh export disagrees with signed identities")
    elif signed["repairedBill"]:
        names = bill_identity.recheck(signed_original, result, fetch=source)
        require(list(map(normal, names)) == list(map(normal, signed["officialNames"])),
                "fresh export disagrees with signed repaired bill")
    else:
        bill = official_bill(source(row["officialUrl"]), old, venue_rows[0],
                             result["artists"])
        require(bill["officialNames"] == signed["officialNames"],
                "fresh page disagrees with signed bill")
        # Never borrow a name from recommendations, biographies or another date.
        new_names = [normal(a.get("name")) for a in signed["newArtists"]]
        require(all(name in {normal(n) for n in bill["missingNamedArtists"]}
                    for name in new_names), "new artists not on the official bill")
    # Keep former IDs in the append-only artist table for historical
    # consumers. Removing or redirecting them is a separate schema migration.
    for artist in signed["newArtists"]:
        result["artists"].append(copy.deepcopy(artist))
    updated = expected(old, signed)
    index = next(i for i, event in enumerate(result["events"])
                 if event["id"] == row["eventId"])
    result["events"][index] = updated
    return result, True, len(signed["newArtists"])
