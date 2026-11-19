"""Generic institutional festival date preflight, PRIVATE / non-publishing only.

Never trust a discovered URL as an independent publisher destination.
Only candidate details that the existing national queue proved to be linked
from a code-reviewed regional index are revisited. The live index must link
the exact titled edition again. An observation is stable only after two
consecutive calendar days; none of these hints is an authorized public row.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from grossesondes_archived_html_intake import official_date
from grossesondes_structured_edition import no_same_edition_jsonld_contradiction

from national_detail_qualification import _eligible_sources, _seen_again
from official_watch import get_page

STATE_KEY = "national_institutional_dates_private"
SCHEMA = "grossesondes.national-institutional-edition-preflight-private.v1"
MAX_CHECKS = 2


def _exact_edition(html, source, today):
    """No year guesses, artist, venue or GPS inferred from the index page."""
    title, year = source.get("title"), source.get("year")
    if not isinstance(title, str) or type(year) is not int:
        return None
    match = re.fullmatch(r"(.{8,150}?)\s+(20[2-4][0-9])", title.strip())
    if not match or int(match.group(2)) != year or year not in (2027, 2028):
        return None
    base = match.group(1)
    dates = official_date(html, {"name": base}, year)
    if dates is None:
        return None
    first, last = dates
    if (not date.fromisoformat(today) <= first
            or first.year != year or last.year != year
            or not no_same_edition_jsonld_contradiction(
                html, title, first, last)):
        return None
    return first.isoformat(), last.isoformat()


def run(state, queue, today, fetch=get_page, limit=MAX_CHECKS):
    if (not isinstance(state, dict)
            or state.get("schema") != "grossesondes.source-watch.v1"
            or type(limit) is not int or not 0 <= limit <= MAX_CHECKS):
        raise ValueError("Invalid institutional date preflight")
    today_date = date.fromisoformat(today)
    eligible = _eligible_sources(state, queue, today, due_only=False)
    observed = state.setdefault(STATE_KEY, {})
    if not isinstance(observed, dict):
        raise ValueError("Unsafe private institutional observation registry")
    allowed = {x["url"] for x in eligible}
    for url in tuple(observed):
        if url not in allowed:
            del observed[url]
    yesterday = (today_date - timedelta(days=1)).isoformat()
    eligible.sort(key=lambda src: (
        0 if isinstance(observed.get(src["url"]), dict)
             and observed[src["url"]].get("lastSeen") == yesterday else 1,
        src["dossier_id"], src["url"]))
    output = []
    for source in eligible[:limit]:
        url = source["url"]
        # Stale positives cannot survive a failed live index or detail fetch.
        old = observed.pop(url, None)
        result = {
            "dossier_id": source["dossier_id"],
            "status": "INSTITUTIONAL_DATE_NOT_RECHECKED",
            "review_only": True, "safe_to_publish": False,
            "publication_authorized": False,
            "publisher_gate_connected": False,
            "start_date_hint": None, "end_date_hint": None,
            "two_day_observation": False,
        }
        try:
            index_html = fetch(source["index_page"])
            if not _seen_again(index_html, source):
                result["status"] = "LIVE_INDEX_LINK_MISSING"
            else:
                html = fetch(url)
                dates = _exact_edition(html, source, today)
                if dates is None:
                    result["status"] = "EXACT_DATES_NOT_RECONFIRMED"
                else:
                    fingerprint = sha256(json.dumps({
                        "index": source["index_url"],
                        "page": source["index_page"], "detail": url,
                        "name": source["title"], "year": source["year"],
                        "dates": dates,
                    }, sort_keys=True).encode("utf-8")).hexdigest()
                    continuous = False
                    if (isinstance(old, dict) and old.get("digest") == fingerprint
                            and old.get("lastSeen") in (today, yesterday)
                            and isinstance(old.get("firstSeen"), str)):
                        first_seen = date.fromisoformat(old["firstSeen"])
                        continuous = (old["lastSeen"] == yesterday
                                      and first_seen < today_date)
                        if old["lastSeen"] == today:
                            continuous = first_seen < today_date
                    observed[url] = {
                        "digest": fingerprint,
                        "firstSeen": old["firstSeen"] if (
                            isinstance(old, dict)
                            and old.get("digest") == fingerprint
                            and (old.get("lastSeen") in (today, yesterday))
                            and isinstance(old.get("firstSeen"), str)
                        ) else today,
                        "lastSeen": today,
                    }
                    result["status"] = (
                        "TWO_DAY_INSTITUTIONAL_DATE_RECHECKED_PRIVATE"
                        if continuous else "FIRST_DAY_INSTITUTIONAL_DATE_REVIEW_ONLY")
                    result["start_date_hint"], result["end_date_hint"] = dates
                    result["two_day_observation"] = continuous
        except (OSError, ValueError, TypeError, UnicodeError):
            result["status"] = "INSTITUTIONAL_SOURCE_UNAVAILABLE"
        output.append(result)
    return {
        "schema": SCHEMA, "as_of": today,
        "review_only": True, "safe_to_publish": False,
        "publication_authorized": False, "publisher_gate_connected": False,
        "publications": 0, "checked_count": len(output),
        "two_day_observations_count": sum(
            x["two_day_observation"] for x in output),
        "rows": output,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", required=True, type=Path)
    args = parser.parse_args()
    folder = args.intake
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    state_path = folder / "source-watch-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    queue = json.loads((folder / "national-festival-discovery-review.json")
                       .read_text(encoding="utf-8"))
    result = run(state, queue, today)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    (folder / "national-institutional-edition-preflight.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print("Institutional date preflight: review only, no publication; checked="
          + str(result["checked_count"]) + ", stable="
          + str(result["two_day_observations_count"]))


if __name__ == "__main__":
    main()
