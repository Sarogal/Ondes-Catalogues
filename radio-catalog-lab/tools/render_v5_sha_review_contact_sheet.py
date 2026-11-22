#!/usr/bin/env python3
"""SHA-locked contact sheets of v5 logo candidates for human review only.

Only reads a previously assembled unsigned editorial queue. Uses the existing
bounded, DNS-checked, public-HTTPS image reader. Rechecks the ORIGINAL SHA,
length, MIME and dimensions before rendering a small preview. Never publishes
originals, signs catalogues, replaces assets, or approves a station identity.
"""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path

from PIL import Image, ImageDraw
from audit_open_radio_artwork_inventory import _request, inspect_bytes, MAX_IMAGE

COLUMNS = 4
CELL_W, CELL_H, THUMB = 260, 274, 170


class ContactReviewError(ValueError):
    pass


def pick_candidates(queue: dict, *, shard_index: int,
                    shard_count: int) -> list[dict]:
    if (queue.get("scope") != "GO_ARTWORK_V5_EDITORIAL_TRIAGE_ONLY"
            or queue.get("publication_allowed") is not False
            or queue.get("signed_catalog_created") is not False
            or queue.get("discovery_is_open") is not True):
        raise ContactReviewError("Requires unsigned editorial queue")
    if not (type(shard_index) is int and type(shard_count) is int
            and 1 <= shard_count <= 16 and 0 <= shard_index < shard_count):
        raise ContactReviewError("Invalid review shard")
    all_candidates = queue.get("priority_no_initial_logo")
    if not isinstance(all_candidates, list) or len(all_candidates) > 500:
        raise ContactReviewError("Missing/oversized priority queue")
    chosen = []
    seen_ids = set()
    for row in all_candidates:
        sid, url = row.get("legacy_media_id"), row.get("source_url")
        if (not isinstance(sid, str) or sid in seen_ids
                or not isinstance(url, str)
                or row.get("editorial_review_status")
                   not in ("IDENTITY_VISUAL_REVIEW_REQUIRED",
                           "PREVIOUS_TEST_VISUAL_SHA_MATCH",
                           "PILOT_SHA_MISMATCH_HOLD")
                or row.get("publication_allowed") is not False
                or row.get("replace_existing_logo") is not False):
            raise ContactReviewError("Invalid/duplicated review candidate")
        seen_ids.add(sid)
        if row["editorial_review_status"] != "IDENTITY_VISUAL_REVIEW_REQUIRED":
            continue
        if row.get("probe_verified") is not True:
            continue
        stable_shard = int(hashlib.sha256(url.encode("utf-8")).hexdigest()[:8],
                           16) % shard_count
        if stable_shard == shard_index:
            chosen.append(row)
    if len(chosen) > 80:
        raise ContactReviewError("Too many images in a review shard")
    return chosen


def retrieve_sha_locked(row: dict) -> tuple[Image.Image | None, str]:
    try:
        data, declared_mime, _ = _request(
            row["source_url"], max_bytes=MAX_IMAGE,
            accept="image/png,image/jpeg,image/webp")
        inspected = inspect_bytes(data, content_type=declared_mime)
        for field, previous in (("sha256", row.get("sha256")),
                                ("byte_size", row.get("byte_size")),
                                ("width", row.get("width")),
                                ("height", row.get("height")),
                                ("mime_type", row.get("mime_type"))):
            if inspected[field] != previous:
                return None, "CHANGED_AFTER_PREVIOUS_SHA:" + field
        with Image.open(BytesIO(data)) as picture:
            picture.load()
            return picture.convert("RGBA"), "SHA_MATCH"
    except Exception as error:
        return None, "UNAVAILABLE:" + type(error).__name__


def render(queue: dict, image_path: Path, report_path: Path, *,
           shard_index: int, shard_count: int,
           fetcher=retrieve_sha_locked) -> dict:
    selected = pick_candidates(queue, shard_index=shard_index,
                               shard_count=shard_count)
    count = len(selected)
    rows = max(1, (count + COLUMNS - 1) // COLUMNS)
    sheet = Image.new("RGB", (CELL_W * COLUMNS, rows * CELL_H + 64), "#f7f7f7")
    draw = ImageDraw.Draw(sheet)
    draw.text((16, 10),
              f"GROSSES ONDES / v5 review candidates / shard {shard_index+1}/{shard_count}",
              fill="#151515")
    draw.text((16, 34),
              "SHA-locked previews only - NOT approved logos, NOT published.",
              fill="#a32828")
    cache = {}
    details = []
    for i, row in enumerate(selected):
        url = row["source_url"]
        if url not in cache:
            cache[url] = fetcher(row)
        artwork, status = cache[url]
        x, y = (i % COLUMNS) * CELL_W + 12, (i // COLUMNS) * CELL_H + 70
        draw.rectangle((x-5, y-6, x + CELL_W-16, y + CELL_H-12),
                       outline="#a5a5a5", width=1)
        if artwork is not None:
            image = artwork.copy()
            image.thumbnail((THUMB, THUMB))
            tile = Image.new("RGBA", (THUMB, THUMB), "white")
            tile.alpha_composite(image, ((THUMB-image.width)//2,
                                         (THUMB-image.height)//2))
            sheet.paste(tile.convert("RGB"), (x+32, y+4))
        draw.text((x, y+179), row["station_name"][:37], fill="#111111")
        draw.text((x, y+200), row["source_host"][:38], fill="#555555")
        draw.text((x, y+220),
                  f'{row["width"]}x{row["height"]} | {status[:22]}',
                  fill="#146e42" if status == "SHA_MATCH" else "#a32828")
        draw.text((x, y+241), row["legacy_media_id"][:27],
                  fill="#666666")
        details.append({
            "legacy_media_id": row["legacy_media_id"],
            "station_name": row["station_name"],
            "sha256": row["sha256"],
            "source_url": url,
            "status": status,
            "editorial_identity_approved": False,
            "publication_allowed": False,
        })
    image_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(image_path, "PNG", optimize=True)
    result = {
        "scope": "GO_V5_SHA_CONTACT_SHEET_REVIEW_ONLY",
        "publication_allowed": False,
        "editorial_identity_approved": False,
        "shard_index": shard_index, "shard_count": shard_count,
        "candidate_rows": len(details),
        "unique_urls_fetched": len(cache),
        "sha_matching_previews": sum(
            row["status"] == "SHA_MATCH" for row in details),
        "records": details,
    }
    report_path.write_text(json.dumps(
        result, sort_keys=True, ensure_ascii=False, indent=2)+"\n",
        encoding="utf-8")
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--queue", type=Path, required=True)
    p.add_argument("--shard-index", type=int, required=True)
    p.add_argument("--shard-count", type=int, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    a = p.parse_args()
    summary = render(json.loads(a.queue.read_text(encoding="utf-8")),
                     a.output, a.report,
                     shard_index=a.shard_index, shard_count=a.shard_count)
    print(json.dumps({k: v for k, v in summary.items() if k != "records"},
                     sort_keys=True))


if __name__ == "__main__":
    main()
