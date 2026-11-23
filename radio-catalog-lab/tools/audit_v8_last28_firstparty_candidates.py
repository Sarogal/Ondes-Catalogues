#!/usr/bin/env python3
"""READ-ONLY test of first-party artwork for remaining GO TEST v8 stations.

Candidates were identified on broadcaster-owned rendered pages on 2026-11-23.
No acceptance based on URL alone: broadcaster/station identity, page reference,
two bounded binary downloads, decoded dimensions and SHA equality are reported.
No staging, signature, publication, pointer, APK or Android changes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from audit_open_radio_artwork_inventory import _request, inspect_bytes, MAX_IMAGE, MAX_HTML

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "radio-catalog-lab/full-staging/UNSIGNED-radio-v8-68-official-sha-logos-20261123.json"
SOURCES = {
    "go-station-000017": {
        "name": "ARfm", "homepage": "http://arfm.co.uk/",
        "stream": "108.163.245.230:9016",
        "page": "https://arfm.co.uk/",
        "image_urls": [
            "https://arfm.co.uk/wp-content/uploads/2021/10/ARFM-White-Logo-2024-2.png",
            "https://arfm.co.uk/wp-content/uploads/2021/10/ARFM-LOGO-2024-Final-Black.png",
            "https://arfm.co.uk/wp-content/uploads/2021/10/ARFM-LOGO-2024-Final-WHITE-LINE.png",
        ],
        "allowed_hosts": ["arfm.co.uk", "www.arfm.co.uk"],
        "association": "station-logo image published by owner",
    },
    "go-station-000042": {
        "name": "The Pit | NTS", "homepage": "https://www.nts.live/infinite-mixtapes/the-pit",
        "stream": "ntslive.net/mixtape34",
        "page": "https://www.nts.live/infinite-mixtapes/the-pit",
        "image_urls": [
            "https://media2.ntslive.co.uk/resize/1600x1600/9c9efb53-ce34-4a5e-997b-f8251be464a1_1668038400.jpeg",
            "https://media.ntslive.co.uk/crop/128x128/8c638d1c-8728-4f9b-9ae2-2f1975d61cf6_1668038400.png",
            "https://media.ntslive.co.uk/crop/128x128/069b6b6c-dd48-4ee2-8e35-2c2ca6b831cc_1668038400.png",
            "https://media.ntslive.co.uk/resize/400x400/9c9efb53-ce34-4a5e-997b-f8251be464a1_1668038400.jpeg",
            "https://media3.ntslive.co.uk/resize/200x200/9c9efb53-ce34-4a5e-997b-f8251be464a1_1668038400.jpeg",
        ],
        "allowed_hosts": ["media.ntslive.co.uk", "media2.ntslive.co.uk", "media3.ntslive.co.uk"],
        "association": "owner The Pit page OpenGraph image / mixtape channel icon",
    },
    "go-station-000216": {
        "name": "Pure Rock KNAC.COM", "homepage": "https://knac.com/",
        "stream": "stream.rcast.net/71987", "page": "https://knac.com/",
        "image_urls": ["https://mmo.aiircdn.com/2595/6a020bcf87eab.jpg"],
        "allowed_hosts": ["mmo.aiircdn.com"],
        "association": "owner site favicon CDN (publisher branding, not a show image)",
    },
    "go-station-000090": {
        "name": "Femmetal Classics Radio",
        "homepage": "https://femmetal.net/",
        "stream": "cast2.my-control-panel.com/proxy/femmetal/stream",
        "page": "https://femmetal.net/",
        "image_urls": ["https://cast2.my-control-panel.com/static/femmetal/covers/rsz_emb_femmetalguy_femmetal_classics_id1_67d851f2.jpg"],
        "allowed_hosts": ["cast2.my-control-panel.com"],
        "association": "owner radio page embeds candidate Femmetal Classics ID1 image; inspect if artwork vs cover before staging",
    },
    "go-station-000067": {
        "name": "True Black Metal Radio",
        "homepage": "http://trueblackmetalradio.com/#/home",
        "stream": "trueblackmetalradio.com:666/radio",
        "page": "https://trueblackmetalradio.com/",
        "image_urls": ["https://trueblackmetalradio.com/assets/images/tbmr.png"],
        "allowed_hosts": ["trueblackmetalradio.com", "www.trueblackmetalradio.com"],
        "association": "owner station's own tbmr.png; review actual graphic",
    },
    "go-station-000111": {
        "name": "rock.irk.ru :: main-mix",
        "homepage": "https://rock.irk.ru/radio",
        "stream": "live.rock.irk.ru/hls/main-mix",
        "page": "https://rock.irk.ru/radio",
        "image_urls": ["https://rock.irk.ru/wp-content/uploads/2025/01/tnidr8hnvcm.jpg"],
        "allowed_hosts": ["rock.irk.ru"],
        "association": "owner page OpenGraph image alt Radio rock.irk.ru; visual editorial check needed",
    },
    "go-station-000155": {
        "name": "idobi Howl", "homepage": "http://idobi.com/",
        "stream": "idobihowl.idobi.com", "page": "https://idobi.com/idobi-howl/",
        "image_urls": ["https://idobi.com/wp-content/themes/idobi-2022/assets/img/idobiHowl_2022logo_Dark.png"],
        "allowed_hosts": ["idobi.com", "www.idobi.com"],
        "association": "possible specific station logo; owner page association needs confirming",
    },
}


def audit(network: bool) -> dict:
    source = json.loads(BASE.read_bytes())
    active = [s for s in source["stations"] if s["status"]["state"] == "active"]
    if source["release_sequence"] != 8 or len(active) != 285 or sum(s["logo"] is None for s in active) != 28:
        raise ValueError("Expected unsigned 68-logo TEST v8 with exactly 28 missing")
    stations = {s["go_station_id"]: s for s in active}
    reports = []
    for sid, spec in SOURCES.items():
        station = stations[sid]
        if (station["logo"] is not None or station["display_name"] != spec["name"]
                or station["homepage"] != spec["homepage"]
                or not any(spec["stream"] in st["url"] for st in station["streams"])):
            raise ValueError("Station identity/stream no longer matches: " + sid)
        page_html = ""
        page_info = {"page_url": spec["page"], "page_read": False}
        if network:
            try:
                payload, media_type, final = _request(spec["page"], max_bytes=MAX_HTML, accept="text/html")
                if urlsplit(final).hostname != urlsplit(spec["page"]).hostname:
                    raise ValueError("Unexpected broadcaster page host")
                page_html = payload.decode("utf-8", errors="replace")
                page_info["page_read"] = True
                page_info["page_content_sha256"] = hashlib.sha256(payload).hexdigest()
            except Exception as exc:
                page_info["page_error"] = type(exc).__name__
        api_media = set()
        api_stream_verified = False
        if sid == "go-station-000042" and network:
            try:
                api_data, _, api_final = _request(
                    "https://www.nts.live/api/v2/mixtapes/the-pit", max_bytes=MAX_HTML,
                    accept="application/json")
                obj = json.loads(api_data)
                api_stream_verified = (
                    obj["mixtape_alias"] == "the-pit" and
                    obj["title"] == "The Pit" and
                    obj["audio_stream_endpoint"] == "https://stream-mixtape-geo.ntslive.net/mixtape34" and
                    urlsplit(api_final).hostname == "www.nts.live")
                if api_stream_verified:
                    api_media = {v for v in obj["media"].values() if isinstance(v, str)}
            except Exception:
                pass
        for url in spec["image_urls"]:
            host = urlsplit(url).hostname
            if urlsplit(url).scheme != "https" or host not in spec["allowed_hosts"]:
                raise ValueError("Unapproved official image host: " + url)
            # The exact file token must be present on the origin page, not only
            # on a third-party aggregator. Page read failures do not imply a match.
            token = urlsplit(url).path.rsplit("/", 1)[-1]
            referenced = bool(page_html and token in page_html)
            official_api_match = api_stream_verified and url in api_media
            row = {
                "id": sid, "name": spec["name"], "image_url": url,
                "source_page": page_info, "source_association": spec["association"],
                "referenced_on_owner_html": referenced,
                "matched_exact_station_owner_api": official_api_match,
                "image_bytes_verified_twice": False,
                "eligible_for_staging": False,
                "signed": False, "published": False,
            }
            if network:
                try:
                    inspections = []
                    for attempt in range(2):
                        image, content_type, final = _request(
                            url, max_bytes=MAX_IMAGE,
                            accept="image/png,image/jpeg,image/webp")
                        if urlsplit(final).hostname not in spec["allowed_hosts"]:
                            raise ValueError("Image redirected beyond approved broadcaster/CDN")
                        meta = inspect_bytes(image, content_type=content_type)
                        inspections.append(meta)
                    if inspections[0] != inspections[1]:
                        raise ValueError("Image checksum/dimensions changed between downloads")
                    row.update(inspections[0])
                    row["image_bytes_verified_twice"] = True
                    row["status"] = "STABLE_ORIGINAL_SHA"
                    row["eligible_for_staging"] = (referenced or official_api_match) and sid != "go-station-000155"
                except Exception as exc:
                    row["status"] = "ORIGINAL_IMAGE_UNVERIFIED"
                    row["image_error"] = type(exc).__name__
            else:
                row["status"] = "OFFLINE_CANDIDATE_ONLY"
            reports.append(row)
    shas = [r["sha256"] for r in reports if r["image_bytes_verified_twice"]]
    return {
        "scope": "GO_V8_LAST28_OWNER_IMAGE_CANDIDATES_DOUBLE_SHA_READONLY",
        "source_catalog": str(BASE.relative_to(ROOT)),
        "active": len(active), "missing_before": 28,
        "candidate_stations": len(SOURCES),
        "candidate_urls": len(reports),
        "verified_image_urls": len(shas),
        "proven_owner_html_matches": sum(r["referenced_on_owner_html"] for r in reports),
        "eligible_for_staging_count": sum(r["eligible_for_staging"] for r in reports),
        "catalog_mutated": False, "signed": False, "published": False,
        "records": reports,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--network", action="store_true")
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    result = audit(args.network)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "records"}, sort_keys=True))
    for r in result["records"]:
        print(r["id"], r["status"], "OWNER_REF="+str(r["referenced_on_owner_html"]),
              "SHA="+r.get("sha256", "NO_SHA"), r["image_url"])


if __name__ == "__main__":
    main()
