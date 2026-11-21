#!/usr/bin/env python3
"""Render SHA-rechecked official OG previews for editorial inspection only.

Reuses the same bounded, DNS-checked, HTTPS-only decoder and SHA verifier as
the original v5 contact sheets. No source image file is published, no radio
identity or station logo is approved, and no active artwork pointer is written.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

from render_v5_sha_review_contact_sheet import retrieve_sha_locked

SCOPE="GO_NO_V5_HOMEPAGE_IMAGE_SHA_REVIEW_ONLY"
COLUMNS=3
CELL_W,CELL_H=292,270
THUMB=185


class OGVisualError(ValueError):
    pass


def select(doc: dict) -> list[dict]:
    if (doc.get("scope") != SCOPE
            or doc.get("publication_allowed") is not False
            or doc.get("signed_catalog_created") is not False
            or doc.get("identity_visual_approved") is not False
            or doc.get("historical_scanned") != doc.get("historical_missing_v5")):
        raise OGVisualError("Invalid or publishable SHA evidence")
    entries=doc.get("records")
    if not isinstance(entries,list) or len(entries)>80:
        raise OGVisualError("Invalid number of SHA candidate rows")
    selections=[]
    seen=set()
    for row in entries:
        proof=row.get("byte_evidence")
        if (row.get("publication_allowed") is not False
                or row.get("identity_visual_approved") is not False
                or row.get("replace_existing_logo") is not False
                or not isinstance(proof,dict)):
            raise OGVisualError("Unexpected approval or malformed probe")
        if (row.get("sha_and_decoder_verified") is not True
                or row.get("large_enough_to_review") is not True):
            continue
        sid,sha=row.get("legacy_media_id"),proof.get("sha256")
        if not isinstance(sid,str) or not isinstance(sha,str) or len(sha)!=64:
            raise OGVisualError("No signed-looking SHA reference")
        key=(sid,sha)
        if key in seen:
            continue
        seen.add(key)
        selections.append({
            "legacy_media_id":sid,
            "station_name":row["station_name"],
            "source_url":row["candidate_url"],
            "source_host":row["candidate_url"].split("/")[2],
            "sha256":sha,
            "byte_size":proof["byte_size"],
            "width":proof["width"],
            "height":proof["height"],
            "mime_type":proof["mime_type"],
            "publication_allowed":False,
            "identity_visual_approved":False,
        })
    if len(selections)>30:
        raise OGVisualError("Too many images for one bounded preview")
    return sorted(selections,key=lambda x:x["station_name"].casefold())


def render(doc: dict, png_path:Path, report_path:Path,
           *, fetcher=retrieve_sha_locked) -> dict:
    selected=select(doc)
    nr=max(1,(len(selected)+COLUMNS-1)//COLUMNS)
    sheet=Image.new("RGB",(CELL_W*COLUMNS,nr*CELL_H+70),"#f7f7f7")
    draw=ImageDraw.Draw(sheet)
    draw.text((14,12),"GROSSES ONDES / historical no-v5 / SHA-locked editorial contact sheet",
              fill="#111111")
    draw.text((14,38),
              "Technical candidate preview only - not an approved logo, not published",
              fill="#a02d2d")
    unique={}
    results=[]
    for n,item in enumerate(selected):
        url=item["source_url"]
        if url not in unique:
            unique[url]=fetcher(item)
        image,status=unique[url]
        x=n%COLUMNS*CELL_W+14
        y=n//COLUMNS*CELL_H+78
        draw.rectangle((x-6,y-7,x+CELL_W-18,y+CELL_H-13),
                       outline="#a7a7a7",width=1)
        if image is not None:
            thumb=image.copy()
            thumb.thumbnail((THUMB,THUMB))
            tile=Image.new("RGBA",(THUMB,THUMB),"white")
            if thumb.mode!="RGBA":
                thumb=thumb.convert("RGBA")
            tile.alpha_composite(thumb,((THUMB-thumb.width)//2,
                                        (THUMB-thumb.height)//2))
            sheet.paste(tile.convert("RGB"),(x+30,y+4))
        draw.text((x,y+189),item["station_name"][:41],fill="#222222")
        draw.text((x,y+207),item["source_host"][:44],fill="#666666")
        draw.text((x,y+225),
                  f'{item["width"]}x{item["height"]} {status[:29]}',
                  fill="#177348" if status=="SHA_MATCH" else "#a02d2d")
        draw.text((x,y+244),item["sha256"][:20],fill="#777777")
        results.append({
            "legacy_media_id":item["legacy_media_id"],
            "station_name":item["station_name"],
            "sha256":item["sha256"],
            "source_url":url,
            "status":status,
            "editorial_identity_approved":False,
            "publication_allowed":False,
        })
    png_path.parent.mkdir(parents=True,exist_ok=True)
    report_path.parent.mkdir(parents=True,exist_ok=True)
    sheet.save(png_path,"PNG",optimize=True)
    out={
        "scope":"GO_NO_V5_SHA_LOCKED_OG_CONTACT_SHEET_REVIEW_ONLY",
        "candidate_stations":len(results),
        "unique_urls_fetched":len(unique),
        "sha_matching_previews":sum(r["status"]=="SHA_MATCH" for r in results),
        "editorial_identity_approved":False,
        "publication_allowed":False,
        "signed_catalog_created":False,
        "records":results,
    }
    report_path.write_text(json.dumps(out,ensure_ascii=False,
                           sort_keys=True,indent=2)+"\n",encoding="utf-8")
    return out


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sha-report",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args()
    result=render(json.loads(a.sha_report.read_text(encoding="utf-8")),
                  a.output,a.report)
    print(json.dumps({k:v for k,v in result.items() if k!="records"},
                     ensure_ascii=False))


if __name__=="__main__":
    main()
