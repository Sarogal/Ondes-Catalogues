#!/usr/bin/env python3
"""Find station-bound artwork on catalogue homepages, without publishing.

Typed station logos are stronger than page OpenGraph artwork. Generic icons,
unrelated network logos, scripts, and arbitrary image links are not evidence.
"""
import argparse
import datetime as dt
import hashlib
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin,urlsplit
import http.client

from radio_daily_v9_generator import BASELINE,encode
from radio_daily_baseline_verify import strict_json,validate_shape
from radio_daily_maintenance_preview import catalogue_rows,digest,age
from radio_daily_editorial_preview import Page,station_nodes,homepage_url,fetch_html,related_host
from radio_daily_repair_preview import name_key,page_key
from radio_daily_logo_maintenance import valid_metadata,source_policy
from radio_catalog_logo_pilot_probe import fetch_strict_https,decode_image,MAX_LOGO_BYTES
from radio_daily_qualification_dossiers import MAX_BYTES
from radio_stream_recheck_ledger import parse_day,SHA256_RE

MAX_STATIONS=4
MAX_IMAGES=2
ANALYZER_VERSION=2
MAX_ALTERNATIVES=2
LOGO_KINDS={"typed_station_logo","named_player_html_logo"}
KINDS=LOGO_KINDS|{"typed_station_image","named_page_og_image"}
STATUSES={"page_held","no_bound_image","ambiguous_images","image_held","decoded_review"}
GENERIC={"radio","metal","punk","hard rock"}

class ArtworkPage(Page):
    def __init__(self):
        super().__init__()
        self.og_titles=[]
        self.og_images=[]
        self.visible_identity=[]
        self.identity_tag=None
        self.logo_images=[]
    def handle_starttag(self,tag,attrs):
        if tag=="meta" and not self.ignored:
            a=dict(attrs)
            k=(a.get("property") or a.get("name") or "").lower()
            v=a.get("content") or ""
            if k=="og:title" and len(self.og_titles)<8:
                self.og_titles.append(v)
            if k in ("og:image","og:image:secure_url") and len(self.og_images)<8:
                self.og_images.append(v)
        if tag=="img" and not self.ignored and len(self.logo_images)<32:
            a=dict(attrs)
            src=a.get("src") or ""
            alt=a.get("alt") or ""
            # Explicit named logo, not an arbitrary image, favicon or banner.
            if src and alt and not any(k in a for k in ("hidden","aria-hidden","srcset","data-src")):
                self.logo_images.append((src,alt))
        if tag in ("title","h1") and not self.ignored:
            self.identity_tag=tag
            self.visible_identity.append("")
        super().handle_starttag(tag,attrs)
    def handle_data(self,data):
        if self.identity_tag and not self.ignored:
            self.visible_identity[-1]=(self.visible_identity[-1]+data)[:500]
        super().handle_data(data)
    def handle_endtag(self,tag):
        if tag==self.identity_tag:
            self.identity_tag=None
        super().handle_endtag(tag)

def image_values(value):
    if isinstance(value,str):
        return [value]
    if isinstance(value,dict):
        kinds=value.get("@type",[])
        if isinstance(kinds,str):
            kinds=[kinds]
        if "ImageObject" in kinds:
            return [v for k in ("contentUrl","url") if isinstance(v:=value.get(k),str)]
    if isinstance(value,list):
        return [v for item in value[:8] if isinstance(item,(str,dict)) for v in image_values(item)]
    return []

def candidates(station,final,body):
    p=ArtworkPage()
    p.feed(body.decode("utf-8",errors="replace"))
    name=name_key(station["display_name"])
    if len(name)<4 or name in GENERIC:
        return {}
    # Alternative paths need an exact registered player even for typed logos.
    # Same-host alone is not sufficient on a multi-station broadcaster.
    home=homepage_url(station.get("homepage"))
    alternate=bool(home and page_key(final)!=page_key(home))
    if alternate:
        players={urljoin(final,u) for u in p.audio_urls}
        known={v["url"] for v in station.get("streams",[])}
        if not (len(players)==1 and players<=known):
            return {}
    nodes=list(station_nodes(p.structured))
    matched=[n for n in nodes if name_key(n.get("name"))==name]
    typed={}
    for key,kind in (("logo","typed_station_logo"),("image","typed_station_image")):
        for n in matched:
            for v in image_values(n.get(key)):
                typed.setdefault(urljoin(final,v),kind)
    # A logo declared for another station on the same page is ambiguous.
    other={urljoin(final,v) for n in nodes if n not in matched for key in ("logo","image")
           for v in image_values(n.get(key))}
    if set(typed)&other:
        return {}
    if typed:
        # Prefer explicit logos to illustrations, but preserve conflicts
        # between multiple declared logo addresses.
        return {u:k for u,k in typed.items() if k=="typed_station_logo"} or typed
    # A visible station logo on a named page with one actual catalogue
    # player provides a second, station-specific proof independent of JSON-LD.
    # Shared broadcaster/network pages and generic or unbound HTML are held.
    if (not nodes and len(name)>=5 and any(name_key(t)==name for t in p.visible_identity)):
        players={urljoin(final,u) for u in p.audio_urls}
        known={v["url"] for v in station.get("streams",[])}
        if len(players)==1 and players<=known:
            labels={name+" logo","logo "+name}
            found={urljoin(final,src):"named_player_html_logo" for src,alt in p.logo_images
                   if name_key(alt) in labels}
            # Named HTML is kept same-host; CDN support requires typed proof.
            if found and all(related_host(u,final) for u in found):
                return found
    if (not alternate and not nodes and p.og_titles and all(name_key(t)==name for t in p.og_titles)
            and any(name_key(t)==name for t in p.visible_identity)):
        # No favicon fallback; OG image is a lower-confidence hypothesis.
        return {urljoin(final,v):"named_page_og_image" for v in p.og_images if v}
    return {}

def bound_page(station, requested, final, body):
    home=homepage_url(station.get("homepage"))
    if (not home or homepage_url(final)!=final or not related_host(final,home)
            or not related_host(requested,home)
            or not isinstance(body,bytes) or not 0<len(body)<=256*1024):
        raise ValueError("unbound page")
    return candidates(station,final,body)


def discover_page(station, fetch_page):
    """Follow at most two explicitly named station links from its declared site."""
    home=homepage_url(station.get("homepage"))
    if not home:
        raise ValueError("no homepage")
    final,body=fetch_page(home)
    found=bound_page(station,home,final,body)
    if found:
        return final,body,found
    p=ArtworkPage()
    p.feed(body.decode("utf-8",errors="replace"))
    name=name_key(station["display_name"])
    links=set()
    for href,label in p.links:
        try:
            url=urljoin(final,href)
            if (len(name)>=5 and name_key(label)==name and homepage_url(url)==url
                    and related_host(url,home) and page_key(url)!=page_key(final)):
                links.add(url)
        except (ValueError,TypeError):
            continue
    matches=[]
    for url in sorted(links)[:MAX_ALTERNATIVES]:
        try:
            child,content=fetch_page(url)
            choices=bound_page(station,url,child,content)
            if choices:
                matches.append((child,content,choices))
        except (OSError,ValueError,http.client.HTTPException,TypeError,AttributeError):
            continue
    if not matches:
        return final,body,{}
    # Conflicting page declarations are not resolved by arbitrary link order.
    if any(x[2]!=matches[0][2] for x in matches[1:]):
        raise ValueError("conflicting station artwork pages")
    return matches[0]


def confirmation_status(row,dates):
    if row.get("reviewStatus")!="decoded_review":
        return "no_current_image"
    if row.get("sourceKind") not in LOGO_KINDS:
        return "illustration_review_only"
    return "stable_typed_logo_review" if len(dates)==2 else "await_distinct_day"

def build(raw,day,*,expected=BASELINE,prior=None,limit=0,fetch_page=fetch_html,
          fetch_image=fetch_strict_https,decode=decode_image):
    day=parse_day(day)
    catalogue_rows(raw,expected)
    doc=strict_json(raw)
    validate_shape(doc)
    if type(limit) is not int or not 0<=limit<=MAX_STATIONS:
        raise ValueError("invalid missing artwork budget")
    missing={s["go_station_id"]:s for s in doc["stations"] if s["logo"] is None}
    eligible={sid:s for sid,s in missing.items() if s["status"].get("reason_code")!="synthetic_diagnostic_not_for_playback"}
    old={}
    if prior is not None:
        if (prior.get("schemaVersion")!=1 or prior.get("catalogBaselineSha256")!=expected
                or prior.get("publicationAllowed") is not False or prior.get("approvedLogoCount")!=0
                or parse_day(prior["scanDate"])>day or not isinstance(prior.get("records"),list)):
            raise ValueError("invalid missing artwork history")
        for row in prior["records"]:
            sid=row.get("goStationId")
            status=row.get("reviewStatus")
            if (sid not in missing or sid in old or row.get("logoApproved") is not False
                    or row.get("publicationAllowed") is not False or status not in STATUSES|{"awaiting_search","synthetic_held"}):
                raise ValueError("invalid prior artwork row")
            if "analyzerVersion" in row and (type(row["analyzerVersion"]) is not int or not 1<=row["analyzerVersion"]<=ANALYZER_VERSION):
                raise ValueError("invalid artwork analyzer version")
            date=row.get("observedDate")
            if date is not None and parse_day(date)>day:
                raise ValueError("future artwork observation")
            if status=="decoded_review":
                if (not valid_metadata(row.get("image")) or row.get("sourceKind") not in KINDS
                        or not SHA256_RE.fullmatch(row.get("sourceSha256") or "")
                        or not SHA256_RE.fullmatch(row.get("pageSha256") or "") or date is None):
                    raise ValueError("invalid decoded artwork")
            elif any(row.get(k) is not None for k in ("image","sourceKind","sourceSha256","pageSha256")):
                raise ValueError("unexpected prior artwork")
            dates=row.get("logoEvidenceDates",[])
            if (not isinstance(dates,list) or len(dates)>2 or dates!=sorted(set(dates))
                    or any(parse_day(d)>day for d in dates)
                    or (dates and (status!="decoded_review" or row.get("sourceKind") not in LOGO_KINDS or dates[-1]!=date))):
                raise ValueError("invalid artwork confirmation dates")
            if "confirmationStatus" in row and row["confirmationStatus"] != confirmation_status(row,dates):
                raise ValueError("invalid artwork confirmation status")
            if sid not in eligible and status!="synthetic_held":
                raise ValueError("synthetic artwork history")
            old[sid]=row
    def order(sid):
        previous=old.get(sid,{})
        return (previous.get("observedDate") or "",eligible[sid]["status"]["state"]!="active",sid)
    queue=sorted((sid for sid in eligible if not old.get(sid,{}).get("observedDate")
                  or (old[sid].get("reviewStatus") in {"page_held","no_bound_image","ambiguous_images","image_held"}
                      and old[sid].get("analyzerVersion",1)<ANALYZER_VERSION)
                  or age(day,old[sid]["observedDate"]) >= (7 if old[sid].get("confirmationStatus")=="stable_typed_logo_review" else 1)),key=order)
    rows={}
    for sid in missing:
        rows[sid]={"goStationId":sid,"catalogueStatus":missing[sid]["status"]["state"],
                   "reviewStatus":"awaiting_search" if sid in eligible else "synthetic_held",
                   "observedDate":None,"sourceKind":None,"sourceSha256":None,"pageSha256":None,"image":None,
                   "logoEvidenceDates":[],"confirmationStatus":"no_current_image",
                   "logoApproved":False,"publicationAllowed":False}
        if sid in old:
            for k in ("reviewStatus","observedDate","sourceKind","sourceSha256","pageSha256","image"):
                rows[sid][k]=old[sid].get(k)
            previous=old[sid]
            if "analyzerVersion" in previous:
                rows[sid]["analyzerVersion"]=previous["analyzerVersion"]
            dates=previous.get("logoEvidenceDates",[])
            if "logoEvidenceDates" not in previous and previous.get("sourceKind") in LOGO_KINDS:
                dates=[previous["observedDate"]]
            rows[sid]["logoEvidenceDates"]=dates
            rows[sid]["confirmationStatus"]=confirmation_status(rows[sid],dates)
    images={}
    image_attempts=0
    selected=queue[:limit]
    for sid in selected:
        s=eligible[sid]
        row=rows[sid]
        row.update(observedDate=day,analyzerVersion=ANALYZER_VERSION,reviewStatus="page_held",sourceKind=None,sourceSha256=None,pageSha256=None,image=None,
                   logoEvidenceDates=[],confirmationStatus="no_current_image")
        page=homepage_url(s.get("homepage"))
        if not page:
            continue
        try:
            final,body,found=discover_page(s,fetch_page)
        except (OSError,ValueError,http.client.HTTPException,TypeError,AttributeError):
            continue
        if not found:
            row["reviewStatus"]="no_bound_image"
            continue
        if len(found)!=1:
            row["reviewStatus"]="ambiguous_images"
            continue
        url,kind=next(iter(found.items()))
        row["reviewStatus"]="image_held"
        if source_policy(url)!="eligible":
            continue
        # A station-specific typed declaration may point to a CDN.
        # Page-level OG images remain limited to the reported host.
        if kind=="named_page_og_image" and not related_host(url,final):
            continue
        if url not in images:
            if image_attempts>=MAX_IMAGES:
                # Budget deferral is not a failed observation.
                if sid in old:
                    for k in ("reviewStatus","observedDate","sourceKind","sourceSha256","pageSha256","image"):
                        row[k]=old[sid].get(k)
                    row.pop("analyzerVersion",None)
                    if "analyzerVersion" in old[sid]:
                        row["analyzerVersion"]=old[sid]["analyzerVersion"]
                    row["logoEvidenceDates"]=old[sid].get("logoEvidenceDates",[])
                    row["confirmationStatus"]=confirmation_status(row,row["logoEvidenceDates"])
                else:
                    row.pop("analyzerVersion",None)
                    row.update(observedDate=None,reviewStatus="awaiting_search")
                continue
            image_attempts+=1
            try:
                data,mime=fetch_image(url,urlsplit(url).hostname)
                if not isinstance(data,bytes) or not 0<len(data)<=MAX_LOGO_BYTES:
                    raise ValueError("image size")
                decoded,width,height=decode(data)
                image={"imageSha256":hashlib.sha256(data).hexdigest(),"mime":decoded,
                       "width":width,"height":height,"byteLength":len(data)}
                if mime!=decoded or not valid_metadata(image):
                    raise ValueError("invalid image")
                images[url]=image
            except Exception:
                images[url]=None
        if images[url]:
            row.update(reviewStatus="decoded_review",sourceKind=kind,sourceSha256=digest(url),
                       pageSha256=hashlib.sha256(body).hexdigest(),image=images[url])
            previous=old.get(sid,{})
            dates=[]
            if kind in LOGO_KINDS:
                if (previous.get("reviewStatus")=="decoded_review" and previous.get("sourceKind")==kind
                        and previous.get("sourceSha256")==row["sourceSha256"] and previous.get("image")==row["image"]):
                    dates=previous.get("logoEvidenceDates",[previous["observedDate"]])
                dates=sorted(set([d for d in dates if age(day,d)<=30]+[day]))[-2:]
            row["logoEvidenceDates"]=dates
            row["confirmationStatus"]=confirmation_status(row,dates)
    records=[rows[sid] for sid in sorted(rows)]
    return {"schemaVersion":1,"scanDate":day,"catalogBaselineSha256":expected,"publicationAllowed":False,
            "approvedLogoCount":0,"catalogChanged":False,"missingCount":len(missing),"eligibleCount":len(eligible),
            "attemptedStationCount":len(selected),"attemptedImageCount":image_attempts,
            "counts":dict(sorted(Counter(x["reviewStatus"] for x in records).items())),
            "confirmationCounts":dict(sorted(Counter(x["confirmationStatus"] for x in records).items())),
            "records":records}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline",type=Path,required=True)
    p.add_argument("--previous",type=Path)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--limit",type=int,default=0)
    p.add_argument("--allow-network",action="store_true")
    p.add_argument("--baseline-sha256",default=BASELINE)
    a=p.parse_args()
    if a.limit and not a.allow_network:
        p.error("network must be explicit")
    def read(path):
        if path.stat().st_size>MAX_BYTES:
            raise ValueError("oversize missing artwork input")
        return path.read_bytes()
    report=build(read(a.baseline),dt.datetime.now(dt.timezone.utc).date().isoformat(),
                 expected=a.baseline_sha256,prior=strict_json(read(a.previous)) if a.previous else None,limit=a.limit)
    payload=encode(report)
    if len(payload)>MAX_BYTES:
        raise ValueError("oversize missing artwork report")
    a.output.write_bytes(payload)
    print("RADIO_MISSING_LOGO_PREVIEW_ONLY",{k:v for k,v in report.items() if k!="records"})

if __name__=="__main__":
    main()
