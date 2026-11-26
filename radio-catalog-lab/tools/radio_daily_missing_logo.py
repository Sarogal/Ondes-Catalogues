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
KINDS={"typed_station_logo","typed_station_image","named_page_og_image"}
STATUSES={"page_held","no_bound_image","ambiguous_images","image_held","decoded_review"}
GENERIC={"radio","metal","punk","hard rock"}

class ArtworkPage(Page):
    def __init__(self):
        super().__init__()
        self.og_titles=[]
        self.og_images=[]
    def handle_starttag(self,tag,attrs):
        if tag=="meta" and not self.ignored:
            a=dict(attrs)
            k=(a.get("property") or a.get("name") or "").lower()
            v=a.get("content") or ""
            if k=="og:title" and len(self.og_titles)<8:
                self.og_titles.append(v)
            if k in ("og:image","og:image:secure_url") and len(self.og_images)<8:
                self.og_images.append(v)
        super().handle_starttag(tag,attrs)

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
    nodes=list(station_nodes(p.structured))
    matched=[n for n in nodes if name_key(n.get("name"))==name]
    typed={}
    for key,kind in (("logo","typed_station_logo"),("image","typed_station_image")):
        for n in matched:
            for v in image_values(n.get(key)):
                typed.setdefault(urljoin(final,v),kind)
    if typed:
        # Prefer explicit logos to illustrations, but preserve conflicts
        # between multiple declared logo addresses.
        return {u:k for u,k in typed.items() if k=="typed_station_logo"} or typed
    if (not nodes and p.og_titles and all(name_key(t)==name for t in p.og_titles)
            and any(name_key(t)==name for t in p.identity)):
        # No favicon fallback; OG image is a lower-confidence hypothesis.
        return {urljoin(final,v):"named_page_og_image" for v in p.og_images if v}
    return {}

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
            old[sid]=row
    def order(sid):
        previous=old.get(sid,{})
        return (eligible[sid]["status"]["state"]!="active",previous.get("observedDate") or "",sid)
    queue=sorted((sid for sid in eligible if not old.get(sid,{}).get("observedDate")
                  or age(day,old[sid]["observedDate"]) >= (7 if old[sid]["reviewStatus"]=="decoded_review" else 1)),key=order)
    rows={}
    for sid in missing:
        rows[sid]={"goStationId":sid,"catalogueStatus":missing[sid]["status"]["state"],
                   "reviewStatus":"awaiting_search" if sid in eligible else "synthetic_held",
                   "observedDate":None,"sourceKind":None,"sourceSha256":None,"pageSha256":None,"image":None,
                   "logoApproved":False,"publicationAllowed":False}
        if sid in old:
            for k in ("reviewStatus","observedDate","sourceKind","sourceSha256","pageSha256","image"):
                rows[sid][k]=old[sid].get(k)
    images={}
    image_attempts=0
    selected=queue[:limit]
    for sid in selected:
        s=eligible[sid]
        row=rows[sid]
        row.update(observedDate=day,reviewStatus="page_held",sourceKind=None,sourceSha256=None,pageSha256=None,image=None)
        page=homepage_url(s.get("homepage"))
        if not page:
            continue
        try:
            final,body=fetch_page(page)
            if (not related_host(final,page) or homepage_url(final)!=final or page_key(final)!=page_key(page)
                    or not isinstance(body,bytes) or not 0<len(body)<=256*1024):
                raise ValueError("unbound page")
            found=candidates(s,final,body)
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
                row["observedDate"]=None
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
    records=[rows[sid] for sid in sorted(rows)]
    return {"schemaVersion":1,"scanDate":day,"catalogBaselineSha256":expected,"publicationAllowed":False,
            "approvedLogoCount":0,"catalogChanged":False,"missingCount":len(missing),"eligibleCount":len(eligible),
            "attemptedStationCount":len(selected),"attemptedImageCount":image_attempts,
            "counts":dict(sorted(Counter(x["reviewStatus"] for x in records).items())),"records":records}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline",type=Path,required=True)
    p.add_argument("--previous",type=Path)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--limit",type=int,default=0)
    p.add_argument("--allow-network",action="store_true")
    a=p.parse_args()
    if a.limit and not a.allow_network:
        p.error("network must be explicit")
    def read(path):
        if path.stat().st_size>MAX_BYTES:
            raise ValueError("oversize missing artwork input")
        return path.read_bytes()
    report=build(read(a.baseline),dt.datetime.now(dt.timezone.utc).date().isoformat(),
                 prior=strict_json(read(a.previous)) if a.previous else None,limit=a.limit)
    payload=encode(report)
    if len(payload)>MAX_BYTES:
        raise ValueError("oversize missing artwork report")
    a.output.write_bytes(payload)
    print("RADIO_MISSING_LOGO_PREVIEW_ONLY",{k:v for k,v in report.items() if k!="records"})

if __name__=="__main__":
    main()
