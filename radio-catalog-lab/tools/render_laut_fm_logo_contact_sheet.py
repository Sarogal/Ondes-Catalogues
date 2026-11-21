#!/usr/bin/env python3
"""Make a visual contact sheet from SHA-checked official-source logo candidates.

Not an approval decision, never saves originals to repository and never signs.
The asset bytes MUST re-match the previous exact SHA and decoder metadata.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from audit_open_radio_artwork_inventory import _request, inspect_bytes

THUMB = 192
CELL_W, CELL_H = 280, 290
COLUMNS = 4


def verify_candidate(source: dict) -> tuple[Image.Image | None, str]:
    spec = source["candidate_logo"]
    try:
        body, mime, final_url = _request(
            spec["url"], max_bytes=2*1024*1024,
            accept="image/png,image/jpeg,image/webp",
        )
        checked = inspect_bytes(body, content_type=mime)
        for key in ("sha256", "byte_size", "width", "height", "mime_type"):
            if checked[key] != spec[key]:
                return None, "REJECTED: changed "+key
        with Image.open(BytesIO(body)) as image:
            image.load()
            result = image.convert("RGBA")
        return result, "SHA verified"
    except Exception as e:
        # Never advertise stale or unverified pixels as matching the signed SHA.
        return None, "UNAVAILABLE: "+type(e).__name__


def render(queue: dict, output: Path, *, fetcher=verify_candidate) -> dict:
    if queue.get("scope") != "LOGO_SHA_PREPUBLICATION_REVIEW_ONLY" or \
       queue.get("publication_allowed") is not False:
        raise ValueError("Only non-publishing source queues are accepted")
    candidates = queue["logo_candidates"]
    if not isinstance(candidates, list) or len(candidates) > 160:
        raise ValueError("Too many candidates")
    rows = (len(candidates)+COLUMNS-1)//COLUMNS
    sheet = Image.new("RGB", (CELL_W*COLUMNS, CELL_H*rows+58), "#f7f7f7")
    draw = ImageDraw.Draw(sheet)
    draw.text((15, 10), "GROSSES ONDES  |  LOGOS LAUT.FM  |  REVIEW ONLY", fill="#151515")
    draw.text((15, 32), "Images are public-source candidates; visual identity NOT approved.", fill="#a13030")
    details=[]
    for i, row in enumerate(candidates):
        c=i%COLUMNS
        r=i//COLUMNS
        x=c*CELL_W+14
        y=r*CELL_H+66
        image, result = fetcher(row)
        draw.rectangle((x-8, y-6, x+CELL_W-25, y+CELL_H-16),
                       outline="#a1a1a1",width=1)
        if image is not None:
            image.thumbnail((THUMB, THUMB))
            tile = Image.new("RGBA", (THUMB, THUMB), (255,255,255,255))
            tile.alpha_composite(image, ((THUMB-image.width)//2,
                                         (THUMB-image.height)//2))
            sheet.paste(tile.convert("RGB"),(x+25,y+5))
        draw.text((x, y+206), row["historical_name"][:35], fill="#111111")
        draw.text((x, y+228), row["station_slug"], fill="#444444")
        draw.text((x, y+248),result[:32],
                  fill="#157142" if result=="SHA verified" else "#a13030")
        details.append({
            "legacy_media_id":row["legacy_media_id"],
            "name":row["historical_name"],
            "sha256":row["candidate_logo"]["sha256"],
            "review_status":result,
            "image_decoded":image is not None,
            "editorial_identity_approved":False,
        })
    output.parent.mkdir(parents=True,exist_ok=True)
    sheet.save(output,format="PNG",optimize=True)
    return {"total":len(candidates),
            "sha_verified":sum(d["image_decoded"] for d in details),
            "publication_allowed":False,
            "records":details}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--queue",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args()
    result=render(json.loads(a.queue.read_text(encoding="utf-8")),a.output)
    a.report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",
                        encoding="utf-8")
    print(json.dumps({"status":"GO_LAUT_FM_CONTACT_SHEET_REVIEW_ONLY",
                      "images":result["total"],
                      "matching_sha_bytes":result["sha_verified"],
                      "publication_allowed":False}))


if __name__=="__main__":
    main()
