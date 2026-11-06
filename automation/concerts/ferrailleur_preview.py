#!/usr/bin/env python3
"""Read-only real-source dry run for Ferrailleur verified concert proposals.

Never writes approved.json and never modifies Git. The independent cloud gate
does NOT yet accept automatic Ferrailleur approvals.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from urllib.parse import urlsplit
from html.parser import HTMLParser
from urllib.request import Request, urlopen

import discover
import ferrailleur_official as verifier

CLOUD = "https://sarogal.github.io/Ondes-Catalogues/grossesondes/concerts.json"
CLOUD_RAW = "https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/main/docs/grossesondes/concerts.json"

class PublicTextNodes(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0
    def handle_starttag(self, tag, attrs):
        if tag in ("script","style","noscript","svg"):
            self.hidden += 1
    def handle_endtag(self, tag):
        if tag in ("script","style","noscript","svg"):
            self.hidden = max(0,self.hidden-1)
    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(verifier.norm(data))



def retrieve(url, robots):
    if not discover.robots_allow(url, robots):
        raise ValueError("Consultation interdite par robots.txt")
    request = Request(url, headers={"User-Agent": discover.AGENT})
    with urlopen(request, timeout=12) as response:
        landed = urlsplit(response.geturl())
        if landed.scheme != "https" or landed.hostname not in verifier.HOSTS:
            raise ValueError("Redirection hors de la salle officielle")
        data = response.read(500_001)
        if len(data) > 500_000:
            raise ValueError("Fiche trop volumineuse")
        return data.decode(response.headers.get_content_charset() or "utf-8",
                           errors="replace")


def inspect(registry, catalogue, today, fetch=retrieve, limit=12):
    items = registry.get("items", {}).values()
    eligible = [
        x for x in items
        if x.get("observations", 0) >= 2 and
        x.get("candidate", {}).get("source") == "agenda_officiel_ferrailleur_genre" and
        x.get("candidate", {}).get("reviewBucket") == "genre_tag_review" and
        x.get("candidate", {}).get("officialDetailFound") is True
    ]
    eligible.sort(key=lambda x: (x["candidate"].get("date",""),
                                 x["candidate"].get("candidateId","")))
    results, robots = [], {}
    for row in eligible[:limit]:
        c = row["candidate"]
        page = None
        try:
            page = fetch(c["sourceUrl"], robots)
            proof = verifier.verify(c, page, catalogue, today)
            results.append({
                "candidateId": c["candidateId"], "date": proof["event"]["date"],
                "title": proof["event"]["title"], "status": "verified-preview-only",
                "officialUrl": proof["event"]["officialUrl"],
                "publish": False
            })
        except Exception as exc:
            row = {"candidateId": c.get("candidateId"), "status": "held",
                   "reason": str(exc)[:180], "publish": False}
            if page is not None:
                parser = verifier.Details()
                parser.feed(page)
                paragraph_sample = parser.before + parser.after
                row["publicMarkupDiagnostic"] = {
                    "paragraphCount": len(paragraph_sample),
                    "firstParagraphs": [verifier.norm(s)[:90]
                                        for s in paragraph_sample[:6]],
                    "monthMentions": [verifier.norm(s)[:90]
                                      for s in paragraph_sample
                                      if "decembre" in verifier.norm(s)
                                      or "novembre" in verifier.norm(s)][:3],
                    "eventHeaderNodes": []

                }
            if page is not None:
                nodes = PublicTextNodes()
                nodes.feed(page)
                needles = ("novembre","decembre","janvier","fevrier","mars","mai")
                hits = [i for i,s in enumerate(nodes.parts) if any(x in s for x in needles)]
                if hits:
                    i = hits[0]
                    row["publicMarkupDiagnostic"]["eventHeaderNodes"] = nodes.parts[
                        max(0,i-2):i+18]
            results.append(row)
    return {
        "schema": "grossesondes.concert.ferrailleur.preview.v1",
        "mode": "read-only",
        "venueId": verifier.VENUE_ID,
        "evaluated": len(results),
        "eligible": len(eligible),
        "verifiedPreviewOnly": sum(x["status"] == "verified-preview-only" for x in results),
        "held": sum(x["status"] == "held" for x in results),
        "publicationAllowed": False,
        "results": results
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--registry", required=True)
    p.add_argument("--catalogue", default=CLOUD)
    p.add_argument("--report", required=True)
    args = p.parse_args()
    registry=json.loads(Path(args.registry).read_text(encoding="utf-8"))
    catalogue = None
    for url in (args.catalogue, CLOUD_RAW):
        try:
            with urlopen(url,timeout=18) as response:
                catalogue=json.load(response)
            if catalogue.get("schemaVersion") != 1 or (
                catalogue.get("mode") != "preview-public-unlisted"
            ):
                raise ValueError("Catalogue public inattendu")
            break
        except (OSError,TimeoutError,ValueError,TypeError):
            catalogue=None
    if catalogue is None:
        result={"schema":"grossesondes.concert.ferrailleur.preview.v1",
                "status":"cloud_catalogue_unavailable","mode":"read-only",
                "evaluated":0,"eligible":0,"verifiedPreviewOnly":0,"held":0,
                "publicationAllowed":False,"results":[]}
    else:
        result=inspect(registry,catalogue,discover.today_fr())
    Path(args.report).write_text(
        json.dumps(result,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )
    print(json.dumps({
        "evaluated":result["evaluated"],
        "verifiedPreviewOnly":result["verifiedPreviewOnly"],
        "held":result["held"],
        "heldReasons":[{"candidateId":x["candidateId"],"reason":x["reason"],
                         "diagnostic":x.get("publicMarkupDiagnostic")}
                       for x in result["results"] if x["status"]=="held"][:3],
        "publicationAllowed":False
    },ensure_ascii=False))


if __name__ == "__main__":
    main()
