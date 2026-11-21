"""Independent national-address → named OSM → source WEBSITE research.

A published venue's street/postcode is ONLY a candidate. The French government
address index must return exactly one matching precise address and the OSM map
at that coordinate must identify exactly ONE named, tagged physical site.
The OSM element must then independently declare an HTTPS website. These data
do not grant official-source authority or publication rights; they only seed
a safe first-party discovery fetch.

Uses the existing security-reviewed named-site matcher and TLS-pinned fetch.
Neither a municipal centroid, postcode-only guess nor a venue manifest can
pass this source-origin research route.
"""
from __future__ import annotations

import re
from xml.etree import ElementTree
from urllib.parse import urlsplit

import independent_named_site_geo as geo
import osm_read_only_fallback as readonly
import source_admission_intake as intake
import source_evidence_probe as probe
import triage

OSM_FEATURE=re.compile(r"https://www[.]openstreetmap[.]org/(node|way)/([1-9][0-9]*)\Z")
BANNED_ADDR=re.compile(r"(?:^adresse\b|[àa]\s+v[ée]rifier|inconnue|non\s+communiqu)",re.I)


def require(ok, reason):
    if not ok:
        raise ValueError("BAN/OSM independent venue website: "+reason)


def eligible_address(site):
    return (isinstance(site,dict)
        and all(isinstance(site.get(k),str) and site[k].strip()
                for k in ("name","city","address","postalCode","region"))
        and re.fullmatch(r"\d{5}",site["postalCode"]) is not None
        and len(site["address"])>=6
        and BANNED_ADDR.search(site["address"]) is None)


def website_from_address(site, *, fetch=probe.safe_fetch, cache=None):
    """Return (first-party website URL, independent OSM feature URL).

    fetch(url, cache) returns body; secure production client uses pinned TLS,
    HTTP redirect refusal and robots. BAN and OSM feature are independent
    datasets; neither relies on discovery labels or preapproved organizers.
    """
    require(eligible_address(site),"catalogue has no precise named address")
    cache={} if cache is None else cache

    def bounded(url, cap):
        # The secure network layer enforces its own lower 400k cap.
        response=fetch(url,cache)
        require(isinstance(response,str) and 0<len(response)<=min(cap,probe.MAX_BYTES),
                "government/OSM evidence unavailable or oversized")
        return response,url

    # The governmental search score is a ranking signal, NOT location proof.
    # Precise postcode, municipality, street and house-number still have
    # exact equality checks in geo._ban_result; a SECOND named OSM feature
    # must also agree, and OSM must independently attribute the HTTPS site.
    # Never pass this relaxed research score to Publisher site approval.
    feature_url, lat, lon, precision=geo.verify(
        site,bounded,min_score=0.78)
    require(precision in {"named-site-point","named-site-area"},
            "named physical site not independently confirmed")
    feature=OSM_FEATURE.fullmatch(feature_url)
    require(bool(feature),"OSM feature identity ambiguous")
    api_url="https://api.openstreetmap.org/api/0.6/"+feature.group(1)+"/"+feature.group(2)
    try:
        xml=fetch(api_url,cache)
    except (ValueError,OSError,TimeoutError):
        # The read-only provider supplies the EXACT same OSM feature id;
        # do not skip a robots refusal or use unverified cached OSM tags.
        api_url=readonly.element(feature.group(1),feature.group(2))
        xml=fetch(api_url,cache)
    require(isinstance(xml,str) and len(xml)<=probe.MAX_BYTES
            and "<!DOCTYPE" not in xml.upper()
            and "<!ENTITY" not in xml.upper(),
            "OSM element XML invalid")
    root=ElementTree.fromstring(xml)
    require(root.tag=="osm","unexpected OSM response")
    elements=root.findall(feature.group(1))
    require(len(elements)==1 and elements[0].get("id")==feature.group(2),
            "OSM element identity changed")
    tags={t.get("k"):t.get("v") for t in elements[0].findall("tag")
          if t.get("k") and t.get("v")}
    require(triage.words(tags.get("name"))==triage.words(site["name"]),
            "OSM website belongs to another named venue")
    require(triage.words(tags.get("addr:city"))==triage.words(site["city"])
            and tags.get("addr:postcode")==site["postalCode"]
            and tags.get("addr:country","FR").upper()=="FR",
            "OSM postal identity differs from government-matched venue")
    urls=[tags[k].strip() for k in ("website","contact:website")
          if isinstance(tags.get(k),str) and tags[k].strip()]
    require(bool(urls),"OSM venue has no website evidence")
    domains={intake.valid_https(u) for u in urls}
    require(len(domains)==1 and None not in domains,
            "OSM websites are unsafe or contradictory")
    require(all(urlsplit(url).scheme=="https" for url in urls),
            "OSM site website is not HTTPS")
    return urls[0],feature_url
