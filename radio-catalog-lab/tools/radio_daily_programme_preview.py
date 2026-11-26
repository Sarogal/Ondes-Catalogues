#!/usr/bin/env python3
"""Describe observed radio programme evidence; never infer admission or airtime."""
import argparse
import datetime as dt
import json
from collections import Counter
from pathlib import Path

from radio_daily_artist_research import key, safe_name, valid_id
from radio_daily_wikidata_preview import validate_entry as validate_wikidata
from radio_daily_qualification_dossiers import safe_digest
from radio_daily_metadata_preview import valid_hint
from radio_daily_discovery import normalize, genre_evidence, editorial_signal
from radio_daily_qualification_dossiers import index
from radio_stream_recheck_ledger import parse_day, SHA256_RE

MAX_BYTES = 12 * 1024 * 1024
FRESH_DAYS = 30
# Positive evidence of another genre, not a blacklist or a rejection rule.
OTHER_LABELS = {"pop", "sophisti pop", "new wave", "hip hop", "rap", "country",
                "jazz", "classical", "reggae", "techno", "house", "disco",
                "electronic", "indie pop", "dance pop", "synth pop", "r b"}
BUCKETS = ("target_hint", "other_hint", "mixed_hint", "unclassified_hint")

def label_bucket(genres):
    labels = [normalize(g) for g in genres]
    target = any(editorial_signal("", g, genre_evidence("", g)) == "target_genre_indication"
                 for g in labels)
    other = any(g in OTHER_LABELS for g in labels)
    if target and other:
        return "mixed_hint"
    if target:
        return "target_hint"
    if other:
        return "other_hint"
    return "unclassified_hint"

def build(metadata, research, decisions, *, wikidata=None, recordings=None):
    day = parse_day(metadata["scanDate"])
    today = dt.date.fromisoformat(day)
    for report in (metadata, research, decisions):
        if (report.get("schemaVersion") != 1 or report.get("scanDate") != day
                or report.get("publicationAllowed") is not False or report.get("approvedCount") != 0):
            raise ValueError("untrusted programme input")
    entries = research.get("entries")
    if not isinstance(entries, dict):
        raise ValueError("invalid artist cache")
    for k, e in entries.items():
        if (not isinstance(e, dict) or not safe_name(e.get("artistName"))
                or key(e["artistName"]) != k or e.get("identityVerified") is not False
                or e.get("publicationAllowed") is not False or e.get("source") != "musicbrainz"
                or parse_day(e["checkedAt"]) > day):
            raise ValueError("untrusted artist entry")
        if e.get("status") == "name_hypothesis":
            mid = e.get("mbid")
            if (not valid_id(mid) or e.get("genreSource") != "musicbrainz-community"
                    or e.get("sourceUrl") != "https://musicbrainz.org/artist/" + mid
                    or not isinstance(e.get("genres"), list) or len(e["genres"]) > 200
                    or any(not safe_name(g) for g in e["genres"])):
                raise ValueError("invalid genre provenance")
    directory, credits = {}, {}
    for report in (wikidata, recordings):
        if report is not None and (report.get("schemaVersion") != 1 or report.get("scanDate") != day
                or report.get("publicationAllowed") is not False or report.get("approvedCount") != 0
                or not isinstance(report.get("entries"), dict)):
            raise ValueError("untrusted supplementary research")
    if wikidata is not None:
        directory = wikidata["entries"]
        for k,e in directory.items():
            validate_wikidata(k,e,day)
    if recordings is not None:
        credits = recordings["entries"]
        for k,e in credits.items():
            if (not isinstance(e,dict) or not safe_name(e.get("artistHint"))
                    or not SHA256_RE.fullmatch(e.get("titleSha256") or "")
                    or k != safe_digest(e["artistHint"]+"\n"+e["titleSha256"])
                    or e.get("identityVerified") is not False or e.get("publicationAllowed") is not False
                    or parse_day(e["checkedAt"]) > day or e.get("source") != "musicbrainz-recording-search"):
                raise ValueError("untrusted recording entry")
            if e.get("status") == "recording_credit_hypothesis":
                for field, maximum in (("artistMbids",20),("recordingMbids",50)):
                    v=e.get(field)
                    if not isinstance(v,list) or not 1 <= len(v) <= maximum or any(not valid_id(x) for x in v):
                        raise ValueError("invalid recording identity")
    def fresh(e, name, field, status):
        return (e.get("status")==status and e.get(field)==name
                and (today-dt.date.fromisoformat(e["checkedAt"])).days < FRESH_DAYS)
    decisions_by_id = index(decisions, "records")
    records = []
    for uid, row in sorted(index(metadata, "records").items()):
        if (row.get("approved") is not False or row.get("publicationAllowed") is not False
                or not SHA256_RE.fullmatch(row.get("streamSha256") or "")
                or parse_day(row["observedDate"]) > day
                or not isinstance(row.get("observations"), list) or len(row["observations"]) > 90):
            raise ValueError("untrusted metadata row")
        decision = decisions_by_id.get(uid)
        if decision and (decision.get("approved") is not False or decision.get("publicationAllowed") is not False):
            raise ValueError("untrusted decision row")
        bound = bool(decision and decision.get("streamSha256") == row["streamSha256"])
        seen, days, stale = set(), set(), set()
        spellings = {}
        for obs in row["observations"]:
            if not valid_hint(obs) or parse_day(obs["date"]) > day:
                raise ValueError("invalid observation")
            age = (today - dt.date.fromisoformat(obs["date"])).days
            artist = obs["artistHint"].strip()
            pair = (artist, obs["titleSha256"])
            if age >= FRESH_DAYS:
                stale.add(pair)
                continue
            days.add(obs["date"])
            seen.add(pair)
            spellings.setdefault(key(artist), set()).add(artist)
        counts = Counter({k:0 for k in BUCKETS})
        artists = Counter({k:0 for k in BUCKETS})
        source_counts=Counter()
        def classify(artist,title_hash):
            k=key(artist)
            if not bound or len(spellings[k])!=1:
                return "unclassified_hint","no_usable_source"
            m=entries.get(k,{})
            w=directory.get(k,{})
            r=credits.get(safe_digest(artist+"\n"+title_hash),{})
            mb=fresh(m,artist,"artistName","name_hypothesis")
            wd=fresh(w,artist,"artistName","name_hypothesis")
            rc=fresh(r,artist,"artistHint","recording_credit_hypothesis")
            if rc and len(r["artistMbids"])!=1:
                return "unclassified_hint","collaboration_held"
            mid=m["mbid"] if mb else None
            links=set(w["musicbrainzIds"]) if wd else set()
            rid=r["artistMbids"][0] if rc else None
            if (mid and links and mid not in links) or (rid and mid and rid!=mid) or (rid and links and rid not in links):
                return "unclassified_hint","identity_conflict"
            if mb and wd and (len(links)!=1 or mid not in links):
                return "unclassified_hint","cross_source_identity_unlinked"
            if rid and wd and links!={rid} and not mb:
                return "unclassified_hint","cross_source_identity_unlinked"
            mg=m["genres"] if mb else []
            wg=list(w["genresById"].values()) if wd else []
            m_bucket,w_bucket=label_bucket(mg),label_bucket(wg)
            if mb and wd:
                if {m_bucket,w_bucket}=={"target_hint","other_hint"}:
                    return "unclassified_hint","genre_conflict"
                bucket=label_bucket(mg+wg)
                return bucket,"recording_linked_sources" if rc else "linked_sources"
            if mb:
                return m_bucket,"recording_musicbrainz" if rc else "musicbrainz_only"
            if wd:
                return w_bucket,"recording_wikidata" if rc else "wikidata_only"
            return "unclassified_hint","recording_only" if rc else "no_usable_source"
        by_artist={}
        for artist,title_hash in sorted(seen):
            bucket,source=classify(artist,title_hash)
            counts[bucket]+=1
            source_counts[source]+=1
            by_artist.setdefault(artist,set()).add(bucket)
        for values in by_artist.values():
            artists[next(iter(values)) if len(values)==1 else "unclassified_hint"]+=1
        records.append({"stationuuid":uid, "streamSha256":row["streamSha256"],
                        "matchesDecisionStream":bound, "observedInScan":row.get("observedInScan") is True,
                        "distinctArtistHints":len({a for a,_ in seen}),
                        "distinctArtistTitleHints":len(seen), "distinctTitleHashes":len({h for _,h in seen}),
                        "observationDates":sorted(days), "stalePairCount":len(stale-seen),
                        "artistHintCounts":dict(artists), "artistTitleHintCounts":dict(counts),
                        "sourceHintCounts":dict(sorted(source_counts.items())),
                        "verifiedArtistCount":0, "approved":False, "publicationAllowed":False})
    return {"schemaVersion":1, "scanDate":day, "publicationAllowed":False, "approvedCount":0,
            "freshnessDays":FRESH_DAYS, "stationCount":len(records),
            "stationsWithWikidataHints":sum(any(r["sourceHintCounts"].get(k,0) for k in ("wikidata_only","recording_wikidata","linked_sources","recording_linked_sources")) for r in records),
            "stationsWithSourceConflicts":sum(any(r["sourceHintCounts"].get(k,0) for k in ("identity_conflict","genre_conflict","cross_source_identity_unlinked")) for r in records),
            "stationsWithMultipleObservationDays":sum(len(r["observationDates"])>1 for r in records),
            "stationsWithGenreHints":sum(any(r["artistHintCounts"][k] for k in BUCKETS[:-1]) for r in records),
            "verifiedArtistCount":0, "records":records}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("metadata","research","decisions","output"):
        p.add_argument("--"+name, required=True, type=Path)
    p.add_argument("--wikidata",type=Path)
    p.add_argument("--recordings",type=Path)
    a = p.parse_args()
    def load(path):
        if path.stat().st_size > MAX_BYTES:
            raise ValueError("oversize input")
        return json.loads(path.read_text("utf-8"))
    result = build(load(a.metadata), load(a.research), load(a.decisions),
                   wikidata=load(a.wikidata) if a.wikidata else None,
                   recordings=load(a.recordings) if a.recordings else None)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if len(payload.encode()) > MAX_BYTES:
        raise ValueError("oversize output")
    a.output.write_text(payload, encoding="utf-8")
    print("RADIO_PROGRAMME_HINTS_ONLY", {k:v for k,v in result.items() if k!="records"})

if __name__ == "__main__":
    main()
