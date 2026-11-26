#!/usr/bin/env python3
"""Private, open-world artist-genre research without a closed artist registry.

Per-performer website links are untrusted NAVIGATION HINTS. An exact artist
self-description, safely fetched from the hinted domain, can enrich a
persistent research memory, but NEVER authenticates the artist's domain,
signs an approval or asserts that a concert is musically qualified.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import artist_genre_knowledge as knowledge
import artist_official_bio as bio
import open_world_frontier as frontier
import open_world_musicbrainz as mb
import open_world_wikidata as wd
import open_world_site_research as sites
import source_evidence_probe as probe
from triage import words

SCHEMA = "grossesondes.concert.open-world-artist-genre-research.v1"
MAX_SOURCES = 24
MAX_HTML = probe.MAX_BYTES


def candidate_sources(registry, today, *, musicbrainz=None, wikidata=None):
    """Follow only named, performer-specific links; ambiguous hosts stay held."""
    if (not isinstance(registry, dict)
            or registry.get("schema") != "grossesondes.concert.intake.v1"
            or not isinstance(registry.get("items"), dict)
            or not isinstance(today, dt.date) or isinstance(today, dt.datetime)):
        raise ValueError("Invalid private concert registry")
    hints = defaultdict(set)
    for record in registry["items"].values():
        if (not isinstance(record, dict)
                or record.get("status", "pending_review") != "pending_review"
                or not isinstance(record.get("candidate"), dict)):
            continue
        lead = record["candidate"]
        if lead.get("cancellationNotice") is True:
            continue
        try:
            if dt.date.fromisoformat(lead.get("date")) < today:
                continue
        except (ValueError, TypeError):
            continue
        named = {frontier.normalized(name): name
                 for name in frontier.observed_artists(lead)}
        if not named:
            continue
        for link in (lead.get("artistWebsiteHints")
                     if isinstance(lead.get("artistWebsiteHints"), list)
                     else []):
            if not isinstance(link, dict):
                continue
            key = frontier.normalized(link.get("name"))
            url = sites.safe_page(link.get("url"))
            if key in named and url:
                hints[key].add((named[key], url))
        # A singular artist's own tour is also a lead, not an authority.
        if (str(lead.get("source") or "").startswith("artist_official_")
                or lead.get("source") == "open_world_artist_tour_research"):
            if len(named) == 1:
                name = next(iter(named.values()))
                url = sites.safe_page(lead.get("sourceUrl"))
                if url:
                    hints[frontier.normalized(name)].add((name, url))
    # Directory results are ONLY additional navigation hints for names
    # present in the live pending registry. Never import community genres.
    # Prefer existing event-attached links; directory suggestions fill gaps,
    # rather than turning a tour page and a homepage into false ambiguity.
    direct_keys = set(hints)
    for _, task in mb.candidate_tasks(registry, today).items():
        name = task[2]
        key = frontier.normalized(name)
        if not key or key in direct_keys:
            continue
        for directory, schema, id_field, valid_id in (
                (musicbrainz, mb.SCHEMA, "mbid", mb.valid_id),
                (wikidata, wd.SCHEMA, "qid", wd.valid_id)):
            if (not isinstance(directory, dict) or directory.get("schema") != schema
                    or directory.get("publicationAllowed") is not False
                    or directory.get("approvalsProposed") != 0
                    or not isinstance(directory.get("entries"), dict)):
                continue
            entry = directory["entries"].get(mb.exact(name))
            if (not isinstance(entry, dict) or entry.get("status") != "hypothesis"
                    or entry.get("identityVerified") is not False
                    or entry.get("publicationAllowed") is not False
                    or mb.exact(entry.get("artistName")) != mb.exact(name)
                    or not valid_id(entry.get(id_field))
                    or not isinstance(entry.get("homepageHints"), list)
                    or len(entry["homepageHints"]) > 20):
                continue
            try:
                age = (today - dt.date.fromisoformat(entry["checkedAt"])).days
            except (KeyError, TypeError, ValueError):
                continue
            if not 0 <= age <= 30:
                continue
            for raw in entry["homepageHints"]:
                url = sites.safe_page(raw)
                if url:
                    hints[key].add((name, url))
    selected, ambiguous = [], 0
    for name_key, values in sorted(hints.items()):
        urls = {u for _, u in values}
        # Multiple unrelated addresses for one text name may be homonyms.
        # Only a supplied, unambiguous homepage on the exact same HTTPS
        # origin can disambiguate navigation paths. Never invent a homepage,
        # merge subdomains, or treat the origin as authenticated identity.
        if len(urls) != 1:
            origins = {urlsplit(u).netloc.casefold() for u in urls}
            homepages = {u for u in urls if urlsplit(u).path in ("", "/")
                         and not urlsplit(u).query and not urlsplit(u).fragment}
            if len(origins) != 1 or not homepages:
                ambiguous += 1
                continue
            if len({u.rstrip("/") for u in homepages}) != 1:
                ambiguous += 1
                continue
            values = {(n, u) for n, u in values if u in homepages}
        display_name, url = sorted(values, key=lambda v: (not v[1].endswith("/"), v))[0]
        selected.append({
            "name": display_name,
            "identityKey": frontier.identity("artist", display_name),
            "url": url,
            "discoveryKind": "event-attached-hint" if name_key in direct_keys else "directory-hint",
        })
    return selected, ambiguous


class MissingStructuredArtistGenre(ValueError):
    """No structured musician genre available for an explicit linked biography."""


def profile_genres(html, name):
    """Exact MusicGroup / musician Person identity, no event-wide genres."""
    if not isinstance(html, str) or not 0 < len(html) <= MAX_HTML:
        raise ValueError("Profile size is unsafe")
    reader = knowledge._StructuredScripts()
    reader.feed(html)
    reader.close()
    if len(reader.scripts) > 30:
        raise ValueError("Too many profile scripts")
    target = words(name)
    if not target:
        raise ValueError("Missing artist name")
    found = set()
    structured_claim = False
    for script in reader.scripts:
        try:
            parsed = json.loads(script)
        except (TypeError, ValueError):
            continue
        for node in knowledge._nodes(parsed):
            kinds = knowledge._node_types(node)
            if ("MusicGroup" not in kinds
                    and not ("Person" in kinds and
                             words(node.get("jobTitle")) in {
                                 "musician", "musicien", "singer", "chanteur"})):
                continue
            if words(node.get("name")) != target:
                structured_claim = True
                continue
            if node.get("genre") not in (None, "", []):
                structured_claim = True
            genres = knowledge._genre_labels(node.get("genre"))
            if genres:
                found.add(tuple(sorted(genres, key=str.casefold)))
    if not found and not structured_claim:
        raise MissingStructuredArtistGenre("No structured individual genre")
    if len(found) != 1:
        raise ValueError("Absent or conflicting individual profile genre")
    return list(next(iter(found)))


def _memory(prior):
    if prior is None:
        return {}
    if (not isinstance(prior, dict)
            or prior.get("schema") != SCHEMA
            or prior.get("publicationAllowed") is not False
            or prior.get("approvalsProposed") != 0
            or not isinstance(prior.get("facts"), dict)):
        raise ValueError("Untrusted previous artist research memory")
    return {k: dict(v) for k, v in prior["facts"].items()
            if (isinstance(k, str) and isinstance(v, dict)
                and v.get("evidenceKind") in {
                    "unverified-origin-artist-structured-profile",
                    "unverified-origin-artist-visible-linked-bio",
                    "unverified-origin-artist-visible-direct-description",
                }
                and v.get("officialDomainVerified") is False
                and v.get("publicationAllowed") is False)}


# Fresh profiles need not be downloaded three times a day. Failed profiles
# remain due the next day; neither result is a publication qualification.
PROFILE_REFRESH_DAYS = 14
PROFILE_RETRY_DAYS = 1


def _source_key(source):
    return hashlib.sha256(
        (source["identityKey"] + "|" + source["url"]).encode("utf-8")).hexdigest()[:24]


def _attempt_memory(prior, sources, facts, today):
    active = {_source_key(source) for source in sources}
    saved = prior.get("profileAttempts") if isinstance(prior, dict) else None
    attempts = {}
    if isinstance(saved, dict):
        for key in active:
            row = saved.get(key)
            if not isinstance(row, dict) or row.get("status") not in ("read", "held"):
                continue
            try:
                day = dt.date.fromisoformat(row.get("checkedAt"))
            except (TypeError, ValueError):
                continue
            if day <= today:
                attempts[key] = {"checkedAt": day.isoformat(), "status": row["status"]}
    elif saved is None:
        # Legacy migration: only a previously read exact profile can seed
        # scheduling. No genre, identity or authority is inferred from this.
        for key in active:
            fact = facts.get(key)
            if not isinstance(fact, dict):
                continue
            try:
                day = dt.date.fromisoformat(fact.get("lastVerifiedAt"))
            except (TypeError, ValueError):
                continue
            if day <= today:
                attempts[key] = {"checkedAt": day.isoformat(), "status": "read"}
    return attempts


def _due_sources(sources, attempts, today, slot, limit):
    if not sources:
        return [], 0
    offset = ((today.toordinal() * 3 + slot) * limit) % len(sources)
    rotated = sources[offset:] + sources[:offset]
    due = []
    for source in rotated:
        attempt = attempts.get(_source_key(source))
        if attempt is None:
            due.append((-1, source))
            continue
        day = dt.date.fromisoformat(attempt["checkedAt"])
        refresh = PROFILE_REFRESH_DAYS if attempt["status"] == "read" else PROFILE_RETRY_DAYS
        if (today - day).days >= refresh:
            due.append((day.toordinal(), source))
    # Never-visited sources first, then least recently attempted. Rotation
    # breaks ties without favoring specific artist names or official sites.
    due.sort(key=lambda row: row[0])
    return [source for _, source in due[:limit]], len(due)


def build(registry, today, *, prior=None, slot=0, limit=18,
          fetch=probe.safe_fetch, musicbrainz=None, wikidata=None):
    if (slot not in (0, 1, 2) or type(limit) is not int
            or not 1 <= limit <= MAX_SOURCES):
        raise ValueError("Invalid bounded artist research cohort")
    sources, ambiguous = candidate_sources(registry, today, musicbrainz=musicbrainz, wikidata=wikidata)
    facts = _memory(prior)
    attempts = _attempt_memory(prior, sources, facts, today)
    selection, due_count = _due_sources(sources, attempts, today, slot, limit)
    counters, cache, refreshed = Counter(), {}, 0
    for source in selection:
        url = source["url"]
        fact_key = _source_key(source)
        attempts[fact_key] = {"checkedAt": today.isoformat(), "status": "held"}
        try:
            # safe_fetch independently re-resolves every hostname, pins TLS,
            # validates ALL public DNS IPs, obeys robots and rejects redirects.
            html = fetch(url, cache)
            identity_key = source["identityKey"]
            try:
                genres = profile_genres(html, source["name"])
                evidence_kind = "unverified-origin-artist-structured-profile"
                genre_url = url
            except MissingStructuredArtistGenre:
                # Follow ONLY an explicit same-host Bio/About link. Even a
                # convincing first-person biography is untrusted research
                # until domain ownership is independently authenticated.
                link = bio.linked_official_biography(html, url, url)
                if link and sites.safe_page(link) == link:
                    page = fetch(link, cache)
                    synthetic_source = {
                        "artistId": identity_key, "sourceRole": "artist_official",
                        "enabled": True, "url": url,
                    }
                    synthetic_names = {
                        "artists": [{"id": identity_key, "name": source["name"],
                                     "aliases": []}]
                    }
                    fact = bio.verify_official_biography(
                        synthetic_source, synthetic_names, page,
                        link, link, today)
                    genres = fact["genres"]
                    genre_url = link
                    evidence_kind = "unverified-origin-artist-visible-linked-bio"
                else:
                    genres = bio.direct_artist_description(html, source["name"])
                    genre_url = url
                    evidence_kind = "unverified-origin-artist-visible-direct-description"
            previous = facts.get(fact_key, {})
            facts[fact_key] = {
                "identityKey": identity_key,
                "artistName": source["name"],
                "sourceUrl": url,
                "genreEvidenceUrl": genre_url,
                "genres": genres,
                "firstVerifiedAt": previous.get("firstVerifiedAt",
                                                 today.isoformat()),
                "lastVerifiedAt": today.isoformat(),
                "evidenceKind": evidence_kind,
                "officialDomainVerified": False,
                "eventDateLocationAndLineupProved": False,
                "publicationAllowed": False,
            }
            attempts[fact_key]["status"] = "read"
            counters["selfDeclaredProfileRead"] += 1
            refreshed += 1
        except (ValueError, TypeError, KeyError, OSError, TimeoutError,
                RecursionError):
            counters["profileHeld"] += 1
    return {
        "schema": SCHEMA,
        "asOf": today.isoformat(),
        "scanSlot": slot,
        "candidateArtistSources": len(sources),
        "directoryHintSources": sum(s["discoveryKind"] == "directory-hint" for s in sources),
        "directoryHintSourcesChecked": sum(s["discoveryKind"] == "directory-hint" for s in selection),
        "ambiguousArtistSourcesHeld": ambiguous,
        "sourcesChecked": len(selection),
        "dueArtistSources": due_count,
        "profileSourcesInCooldown": len(sources) - due_count,
        "profileAttempts": dict(sorted(attempts.items())),
        "profilesRefreshed": refreshed,
        "memoryFactCount": len(facts),
        "reasonCounts": dict(sorted(counters.items())),
        "facts": dict(sorted(facts.items())),
        "publicationAllowed": False,
        "approvalsProposed": 0,
        "officialDomainsAuthenticated": 0,
        "note": ("Self-declared genre research only. Verify official domain, "
                 "artist identity and event/date/place independently before "
                 "using a genre in approval or Publisher."),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--registry", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--musicbrainz", type=Path)
    p.add_argument("--wikidata", type=Path)
    p.add_argument("--scan-slot", type=int, choices=(0, 1, 2), default=0)
    p.add_argument("--max-sources", type=int, default=18)
    args = p.parse_args()
    day = dt.datetime.now(ZoneInfo("Europe/Paris")).date()
    registry = json.loads(args.registry.read_text("utf-8"))
    prior = json.loads(args.out.read_text("utf-8")) if args.out.exists() else None
    def optional_directory(path):
        try:
            return json.loads(path.read_text("utf-8")) if path else None
        except (OSError, ValueError):
            return None
    result = build(registry, day, prior=prior, slot=args.scan_slot,
                   limit=args.max_sources,
                   musicbrainz=optional_directory(args.musicbrainz),
                   wikidata=optional_directory(args.wikidata))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True)
        + "\n", encoding="utf-8")
    # Public runner logs must not reveal discovered names, URLs or profiles.
    print("Open-world artist research:", result["sourcesChecked"],
          "safe checks;", result["profilesRefreshed"],
          "self-described profiles retained in private untrusted memory; "
          "zero official origins authenticated or concerts approved.")


if __name__ == "__main__":
    main()
