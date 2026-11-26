"""Conservative correction of previously signed OpenAgenda bill identities.

A non-nominative support label is not an artist. A named guest prefix
is not part of the name. A compound pipe title can be split only when
the independently fetched original event confirms each named act.
No generic permission to replace a real artist is granted.
"""
from __future__ import annotations

import re
from automation.concerts import openagenda_official_concert as oa
from automation.concerts import official_rss_jsonld_bridge as bridge

PROOF = "official-published-openagenda-bill-identity-v1"
PROFILES = frozenset({
    "dynamic-existing-venue-openagenda-single-source-v1",
    "dynamic-openagenda-new-site-v1",
})


def require(ok, reason):
    if not ok:
        raise ValueError("OpenAgenda bill identity: " + reason)


def possible(name):
    return isinstance(name, str) and (
        bridge.is_unnamed_performer(name) or
        oa._named_guest(name) != " ".join(name.split()) or
        bool(re.search(r"\s+\|\s+", name)))


def source(original, catalogue):
    event = original.get("event")
    require(original.get("reviewDecision") == "approved"
            and original.get("reviewedBy") == "independent-official-verifier"
            and isinstance(event, dict) and event.get("status") == "confirmed",
            "missing original independent approval")
    evidence = original.get("officialEvidence")
    require(isinstance(evidence, list), "missing signed evidence")
    proofs = [p for p in evidence if isinstance(p, dict)
              and p.get("proofType") in PROFILES]
    require(len(proofs) == 1, "missing unique original export identity")
    proof = proofs[0]
    require(proof.get("url") == event.get("officialUrl")
            and proof.get("checkedAt") == original.get("reviewedAt")
            and oa.is_openagenda_event_url(event.get("officialUrl")),
            "original source or review changed")
    old_names = proof.get("officialArtistNames")
    ids = event.get("artistIds")
    artists = {a["id"]: a for a in catalogue["artists"]}
    require(isinstance(old_names, list) and isinstance(ids, list)
            and len(old_names) == len(ids) and bool(ids)
            and all(isinstance(n, str) and oa.normalized(n)
                    and aid in artists
                    and oa.normalized(artists[aid]["name"]) == oa.normalized(n)
                    for aid, n in zip(ids, old_names)),
            "original artist identities missing or altered")
    names = []
    for name in old_names:
        if bridge.is_unnamed_performer(name):
            continue
        name = oa._named_guest(name)
        parts = re.split(r"\s+\|\s+", name)
        require(all(2 <= len(p.strip()) <= 120 and oa.normalized(p)
                    and not bridge.is_unnamed_performer(p) for p in parts),
                "ambiguous compound bill")
        names.extend(p.strip() for p in parts)
    require(bool(names) and len(set(map(oa.normalized, names))) == len(names)
            and list(map(oa.normalized, names)) != list(map(oa.normalized, old_names)),
            "no unambiguous defective identity to correct")
    return {"names": names, "oldNames": old_names,
            "agendaUid": proof.get("officialOpenAgendaUid"),
            "eventUid": proof.get("officialOpenAgendaEventUid"),
            "url": oa.official_export_url(proof.get("officialOpenAgendaUid"),
                                         proof.get("officialOpenAgendaEventUid"))}


def recheck(original, catalogue, *, fetch):
    info = source(original, catalogue)
    event = original["event"]
    venues = [v for v in catalogue["venues"] if v["id"] == event["venueId"]]
    require(len(venues) == 1, "missing published physical venue")
    names, genres = oa.verified_export(
        fetch(info["url"]), event["officialUrl"], event["date"], venues[0],
        agenda_uid=info["agendaUid"], event_uid=info["eventUid"])
    require(list(map(oa.normalized, names)) == list(map(oa.normalized, info["names"])),
            "fresh source does not corroborate the exact repaired bill")
    require(set(map(oa.normalized, genres)) == set(map(oa.normalized, event["genres"])),
            "genre changed, separate editorial review required")
    return names
