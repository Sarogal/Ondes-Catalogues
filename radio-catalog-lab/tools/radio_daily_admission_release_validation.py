"""Strict additive admission gate, offline lab with explicit evidence services.

Rebuild the allowed addition from discovery, dossier decisions, fresh
directory and official HTML, and a fresh audio observation. Never invoke
the staging generator or trust its report. No external key or default network.
"""
import copy
import re
from urllib.parse import urlsplit
from radio_daily_baseline_verify import verify_baseline
from radio_daily_lab_signing import validate_candidate
from radio_daily_decision_preview import decide
from radio_catalog_daily_candidate_reconcile import review_candidates, checked_uuid
from radio_daily_discovery import candidate as directory_candidate, normalize
from radio_daily_editorial_preview import (homepage_url, related_host, inspect_site,
    followup_links, MAX_BYTES)
from radio_daily_repair_confirmation import confirm_page
from radio_stream_technical_probe import validate_endpoint
from radio_daily_v9_generator import GENRES, digest, encode

from radio_daily_proposal_subset import select_proposals

MAX_ADMISSIONS = 4
DIRECTORY_LIMIT = 100


def qualify_admission(prior_pointer, prior_body, *, anchor, day, discovery, dossiers,
                      search, fetch, probe, continuity, hls, selected=None):
    old = verify_baseline(prior_pointer, prior_body, **anchor)
    sha = anchor["expected_sha"]
    if discovery.get("scanDate") != day or dossiers.get("scanDate") != day:
        raise ValueError("admission evidence date mismatch")
    if any(not callable(x) for x in (search, fetch, probe, continuity, hls)):
        raise ValueError("explicit fresh evidence services required")
    decisions = decide(discovery, dossiers, sha)
    ready = [r for r in decisions["records"] if r["decision"] == "ready_for_staging_review"]
    if not ready:
        raise ValueError("no qualified admission or admission budget exceeded")
    ready = select_proposals(ready, "stationuuid", selected, MAX_ADMISSIONS)
    reconciliation = {r["stationuuid"]: r["classification"]
        for r in review_candidates(old, discovery)["candidates"]}
    sources = {checked_uuid(r["stationuuid"]): r for r in discovery["candidates"]}
    records = {checked_uuid(r["stationuuid"]): r for r in dossiers["records"]}
    occupied = {r["go_station_id"] for r in old["stations"]+old["tombstones"]}
    aliases = {a for r in old["stations"]+old["tombstones"] for a in r["legacy_aliases"]}
    urls = {u for r in old["stations"] for s in r["streams"]
            for u in [s["url"], *s.get("previous_urls", [])]}
    names = {(normalize(r["display_name"]), r["country_code"] or "") for r in old["stations"]}
    expected = copy.deepcopy(old)
    timestamp = day+"T00:00:00Z"
    appended = []
    for decision in ready:
        uid = checked_uuid(decision["stationuuid"])
        source, evidence = sources[uid], records[uid]
        url, page = source.get("streamUrl"), source.get("homepage")
        parsed = validate_endpoint(url)
        name = source.get("name")
        country = source.get("countrycode") or None
        if country and not re.fullmatch("[A-Z]{2}", country):
            raise ValueError("invalid candidate country")
        if (reconciliation.get(uid) != "unmapped_candidate" or uid in aliases
                or url in urls or parsed.query or parsed.fragment
                or not isinstance(name,str) or not 0 < len(name.strip()) <= 180
                or (normalize(name),country or "") in names
                or homepage_url(page) != page):
            raise ValueError("candidate identity or endpoint held")
        directory = search(name)
        if (not isinstance(directory,list) or len(directory) >= DIRECTORY_LIMIT
                or any(not isinstance(r,dict) for r in directory)):
            raise ValueError("incomplete directory response")
        rows = [directory_candidate(r,set()) for r in directory]
        matches = [r for r in rows if r and r["stationuuid"] == uid]
        if (len(matches) != 1 or matches[0]["name"] != name.strip()
                or matches[0]["streamUrl"] != url or homepage_url(matches[0]["homepage"]) != page
                or (matches[0]["countrycode"] or None) != country
                or matches[0]["status"] != "candidate_requires_qualification"
                or matches[0]["editorialSignal"] != "target_genre_indication"
                or any(r and r["stationuuid"] != uid and
                       (r["streamUrl"] == url or (normalize(r["name"]),r["countrycode"]) ==
                        (normalize(name),country or "")) for r in rows)):
            raise ValueError("fresh directory identity mismatch or ambiguity")
        final, data = fetch(page)
        if (homepage_url(final) != final or not related_host(final,page)
                or not isinstance(data,bytes) or not 0 < len(data) <= MAX_BYTES):
            raise ValueError("unsafe broadcaster response")
        children = []
        for link in followup_links(final,data):
            child, body = fetch(link)
            if (homepage_url(child) == child and related_host(child,final)
                    and isinstance(body,bytes) and 0 < len(body) <= MAX_BYTES):
                children.append((child,body))
        fresh = inspect_site(name,final,data,url,children)
        if (not fresh["identityNameMatch"] or fresh["signal"] != "identity_and_target_indication"
                or not fresh["declaredStreamLinked"] or not fresh["programmeScopeEvidence"]
                or fresh["primaryElectronicTerms"] or fresh["otherFormatTerms"]):
            raise ValueError("fresh station format or stream binding missing")
        # A station-specific declaration is stronger than a generic audio tag.
        mode, _, _ = confirm_page({"display_name":name},page,url,fetch)
        if not mode:
            raise ValueError("fresh station-specific stream declaration missing")
        genres = sorted({GENRES[t.lower()] for t in fresh["programmeScopeTerms"] if t.lower() in GENRES})
        old_genres = sorted({GENRES[t.lower()] for t in evidence["homepageEvidence"]["programmeScopeTerms"] if t.lower() in GENRES})
        if not genres or genres != old_genres:
            raise ValueError("programme scope changed")
        sample = probe(url)
        if sample.get("streamSha256") != digest(url.encode()):
            raise ValueError("fresh probe fingerprint mismatch")
        if sample.get("verdict") == "audio_sample_ok" and sample.get("frameChain"):
            observed = continuity(url)
            codec = observed.get("frameCodec")
            if observed.get("verdict") != "continuous_icy_frame_indication" or codec != sample["frameChain"]:
                raise ValueError("fresh direct continuity required")
        elif sample.get("verdict") == "playlist_pending":
            observed = hls(url)
            codec = observed.get("frameCodec")
            if observed.get("verdict") != "advancing_hls_audio_frame_indication" or not codec:
                raise ValueError("fresh advancing HLS audio required")
        else:
            raise ValueError("fresh audio sample required")
        if not isinstance(codec,str) or not 0 < len(codec) <= 40:
            raise ValueError("invalid observed codec")
        goid = "go-station-"+str(10**14+int(digest(uid.encode())[:14],16)%(9*10**14))
        if goid in occupied:
            raise ValueError("stable GO ID collision")
        appended.append(dict(go_station_id=goid, display_name=name.strip(),
            country_code=country, genres=genres, homepage=page,
            radio_browser_uuids=[dict(uuid=uid,state="current")], legacy_aliases=[uid],
            status=dict(state="active",reason_code="verified_discovery",changed_at=timestamp),
            streams=[dict(stream_id="discovered-stream-001",url=url,priority=0,
                protocol=parsed.scheme,state="verified",codec=codec,bitrate_kbps=None,
                last_checked_at=timestamp,previous_urls=[])],logo=None,
            editorial=dict(admission_state="approved",reviewed_at=timestamp,
                evidence_refs=["experimental-decision:"+digest(encode(decision)),
                    "experimental-dossier:"+digest(encode(evidence)),
                    "go-admission-page-v1:"+fresh["pageSha256"]])))
        occupied.add(goid)
        aliases.add(uid)
        urls.add(url)
        names.add((normalize(name),country or ""))
    expected["stations"].extend(sorted(appended,key=lambda r:r["go_station_id"]))
    expected.update(release_sequence=anchor["expected_sequence"]+1,generated_at=timestamp)
    body = encode(expected)
    validate_candidate(prior_pointer,prior_body,body,
        expected_candidate_sha=digest(body),day=day,**anchor)
    return body


def validate_admission_release(prior_pointer,prior_body,candidate,**kwargs):
    if candidate != qualify_admission(prior_pointer,prior_body,**kwargs):
        raise ValueError("unauthorized admission delta")
    return digest(candidate)
