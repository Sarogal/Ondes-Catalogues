#!/usr/bin/env python3
"""Stage TWO exact owner channel artworks only in immutable unsigned TEST v8.

Proof: GitHub Actions #45269669910, double SHA from owner pages and exact NTS
mixtape API binding. Re-download bytes independently and fail closed.
Never mutate signed v7, active TEST pointer, production, APK, main or Play Store.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit
from audit_open_radio_artwork_inventory import _request, inspect_bytes, MAX_IMAGE, MAX_HTML

ROOT = Path(__file__).resolve().parents[2]
BEFORE = ROOT / "radio-catalog-lab/full-staging/UNSIGNED-radio-v8-68-official-sha-logos-20261123.json"
AFTER = ROOT / "radio-catalog-lab/full-staging/UNSIGNED-radio-v8-70-official-sha-logos-20261123.json"
ART = ROOT / "grossesondes/radio-test-v2/artwork/staging-nts-rockirk-v8"
PREFIX = ("https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
          "feature/go-radio-v8-metalon-3-logos-20261123/"
          "grossesondes/radio-test-v2/artwork/staging-nts-rockirk-v8/")
SOURCES = {
    "go-station-000042": {
        "name": "The Pit | NTS",
        "homepage": "https://www.nts.live/infinite-mixtapes/the-pit",
        "stream": "stream-mixtape-geo.ntslive.net/mixtape34",
        "url": "https://media2.ntslive.co.uk/resize/1600x1600/9c9efb53-ce34-4a5e-997b-f8251be464a1_1668038400.jpeg",
        "sha256": "ae244e934186b8d3a9f406d8ce8af36c257952c7134d46c717c88f9801293d74",
        "host": "media2.ntslive.co.uk",
    },
    "go-station-000111": {
        "name": "rock.irk.ru :: main-mix",
        "homepage": "https://rock.irk.ru/radio",
        "stream": "live.rock.irk.ru/hls/main-mix",
        "url": "https://rock.irk.ru/wp-content/uploads/2025/01/tnidr8hnvcm.jpg",
        "sha256": "bc33c5de9a403eededb9b0d72d97439370a001284db5d6d27f4840c4f5bd3838",
        "host": "rock.irk.ru",
    },
}
EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def source_check() -> None:
    api_bytes, _, final = _request(
        "https://www.nts.live/api/v2/mixtapes/the-pit", max_bytes=MAX_HTML,
        accept="application/json,application/vnd.mixtape+json")
    nts = json.loads(api_bytes)
    if (urlsplit(final).hostname != "www.nts.live"
        or nts.get("mixtape_alias") != "the-pit"
        or nts.get("title") != "The Pit"
        or nts.get("audio_stream_endpoint") != "https://stream-mixtape-geo.ntslive.net/mixtape34"
        or nts.get("media", {}).get("picture_large") != SOURCES["go-station-000042"]["url"]):
        raise ValueError("NTS owner API no longer binds The Pit/mixtape34/picture_large")

    rock_html, _, final = _request("https://rock.irk.ru/radio",
                                   max_bytes=MAX_HTML, accept="text/html")
    if (urlsplit(final).hostname != "rock.irk.ru"
        or b"tnidr8hnvcm.jpg" not in rock_html
        or b"main-mix" not in rock_html):
        raise ValueError("Official rock.irk.ru radio page no longer links its channel image")


def main() -> None:
    if AFTER.exists() or ART.exists():
        raise ValueError("Unsigned v8-70 and immutable artwork already exist")
    before = json.loads(BEFORE.read_bytes())
    active = [s for s in before["stations"] if s["status"]["state"] == "active"]
    if (before["release_sequence"] != 8 or len(before["stations"]) != 296
            or len(active) != 285 or len(before["tombstones"]) != 24
            or sum(s["logo"] is None for s in active) != 28):
        raise ValueError("Wrong unsigned 68-artwork predecessor")
    by_id = {s["go_station_id"]: s for s in active}
    for sid, spec in SOURCES.items():
        row = by_id[sid]
        if (row["logo"] is not None or row["display_name"] != spec["name"]
                or row["homepage"] != spec["homepage"]
                or not any(spec["stream"] in r["url"] for r in row["streams"])):
            raise ValueError("Radio name/stream/source identity mismatch: " + sid)
    source_check()
    checked = {}
    for sid, spec in SOURCES.items():
        records = []
        for _ in range(2):
            data, content_type, final = _request(
                spec["url"], max_bytes=MAX_IMAGE,
                accept="image/jpeg,image/png,image/webp")
            if urlsplit(final).hostname != spec["host"]:
                raise ValueError("Official image redirect escaped allowed owner domain")
            info = inspect_bytes(data, content_type=content_type)
            if (info["sha256"] != spec["sha256"] or
                    hashlib.sha256(data).hexdigest() != spec["sha256"] or
                    info["mime_type"] not in EXT):
                raise ValueError("Staged image bytes differ from independent original audit")
            records.append((data, info))
        if records[0][0] != records[1][0]:
            raise ValueError("Image bytes changed on repeated source download")
        checked[sid] = records[0]
    if len({i["sha256"] for _, i in checked.values()}) != 2:
        raise ValueError("Two stations must use separate authentic images")

    after = deepcopy(before)
    for row in after["stations"]:
        if row["go_station_id"] not in checked:
            continue
        data, info = checked[row["go_station_id"]]
        row["logo"] = {
            "asset_id": "sha256:" + info["sha256"],
            "sha256": info["sha256"],
            "revision": 1,
            "url": PREFIX + info["sha256"] + EXT[info["mime_type"]],
            "byte_size": info["byte_size"],
            "width": info["width"],
            "height": info["height"],
            "mime_type": info["mime_type"],
        }
    original = {s["go_station_id"]: s for s in before["stations"]}
    for row in after["stations"]:
        prior = original[row["go_station_id"]]
        if row["go_station_id"] in SOURCES:
            test = deepcopy(row)
            test["logo"] = None
            if test != prior:
                raise ValueError("Attempted mutation outside logo: " + row["go_station_id"])
        elif row != prior:
            raise ValueError("Unrelated station changed")

    if (after["tombstones"] != before["tombstones"]
        or sum(s["status"]["state"] == "active" and s["logo"] is None
               for s in after["stations"]) != 26):
        raise ValueError("Redirects changed or wrong new logo coverage")
    ART.mkdir(parents=True, exist_ok=False)
    for data, info in checked.values():
        (ART / (info["sha256"] + EXT[info["mime_type"]])).write_bytes(data)
    AFTER.write_text(json.dumps(after, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "GO_TEST_V8_70_OWNER_IMAGES_STAGED_UNSIGNED",
        "active": 285, "with_logo": 259, "without_logo": 26,
        "new_original_sha_objects": 70, "signed": False, "published": False,
        "active_TEST_v7_unchanged": True}, sort_keys=True))


if __name__ == "__main__":
    main()
