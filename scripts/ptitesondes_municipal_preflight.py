"""Independent municipal outing preflight, strictly READ ONLY.

Only examines Le Gosier sessions from the reviewed private Gosier pipeline.
Uses its own official page and municipal calendar checks rather than trusting
private report flags. NEVER creates patches, approvals or public writes.
"""
from datetime import date
from html.parser import HTMLParser
import json
import re
from urllib.request import Request, HTTPRedirectHandler, build_opener

from ptitesondes_nonmusic_release_contract import audit, safe_event_url
from proof import norm

SCHEMA = "ptitesondes.municipal_independent_preflight.v1"
HOST = "https://www.villedugosier.fr"
MONTHS = ("", "janvier", "fevrier", "mars", "avril", "mai", "juin",
          "juillet", "aout", "septembre", "octobre", "novembre", "decembre")
WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MAX_HTML = 900_000
TIME = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d\Z")


def municipal_calendar_url(day):
    if type(day) is not date:
        raise ValueError("invalid_calendar_day")
    return (HOST + "/spip.php?date_event=" + day.isoformat()
            + "&lang=fr&page=agenda")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_official(url):
    """Bounded HTTPS read; no redirects and no third-party hosts."""
    if not isinstance(url, str):
        raise ValueError("invalid_official_url")
    if not (safe_event_url(url) or re.fullmatch(
            re.escape(HOST + "/spip.php?date_event=")
            + r"\d{4}-\d{2}-\d{2}&lang=fr&page=agenda", url)):
        raise ValueError("official_host_not_allowed")
    req = Request(url, headers={"User-Agent": "PtitesOndesMunicipalPreflight/1.0",
                                "Accept": "text/html"})
    with build_opener(NoRedirect).open(req, timeout=15) as response:
        if response.geturl() != url:
            raise ValueError("redirect_not_allowed")
        if "text/html" not in response.headers.get("Content-Type", "").lower():
            raise ValueError("invalid_official_content_type")
        payload = response.read(MAX_HTML + 1)
    if len(payload) > MAX_HTML:
        raise ValueError("official_page_too_large")
    return payload.decode("utf-8-sig")


class OfficialPage(HTMLParser):
    """Scope text to an event H1 and stop at the next Calendrier heading."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.titles = []
        self.words = []
        self.in_h1 = False
        self.after_h1 = False
        self.finished = False
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        elif not self.skip and tag == "h1":
            self.in_h1 = True
            self.titles.append([])

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1
        elif not self.skip and tag == "h1" and self.in_h1:
            self.in_h1 = False
            self.after_h1 = True

    def handle_data(self, data):
        if self.skip or self.finished or not data.strip():
            return
        if self.in_h1:
            self.titles[-1].append(data.strip())
        elif self.after_h1:
            if norm(data) == "calendrier":
                self.finished = True
            else:
                self.words.append(data.strip())


class CalendarCards(HTMLParser):
    """Retain only individual SPIP media-eve cards, not adjacent activities."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards = []
        self.depth = 0
        self.card = None
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
            return
        if self.skip:
            return
        classes = (dict(attrs).get("class") or "").split()
        if self.card is None:
            if tag == "div" and "media-eve" in classes:
                self.card = {"words": [], "title_ids": [], "venue_ids": []}
                self.depth = 1
            return
        if tag == "div":
            self.depth += 1
        for name, key in (("evenement-titre-", "title_ids"),
                          ("evenement-lieu-", "venue_ids")):
            for cls in classes:
                if cls.startswith(name) and re.fullmatch(r"[1-9]\d{0,11}", cls[len(name):]):
                    self.card[key].append(cls[len(name):])

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1
            return
        if self.skip or self.card is None:
            return
        if tag == "div":
            self.depth -= 1
            if self.depth == 0:
                self.cards.append(self.card)
                self.card = None

    def handle_data(self, data):
        if self.card is not None and not self.skip and data.strip():
            self.card["words"].append(data.strip())


def local_time_present(text, clock):
    if not isinstance(clock, str) or not TIME.fullmatch(clock):
        return False
    hour, minute = map(int, clock.split(":"))
    body = norm(text)
    if minute == 0:
        # The official site writes both 9h and 09h00.
        expression = rf"\b0?{hour}\s*h(?:\s*00)?\b"
    else:
        expression = rf"\b0?{hour}\s*h\s*{minute:02d}\b"
    return bool(re.search(expression, body))

def official_event_verified(candidate, html):
    if not isinstance(html, str) or len(html.encode("utf-8")) > MAX_HTML:
        return False
    page = OfficialPage()
    page.feed(html)
    if len(page.titles) != 1 or not page.finished:
        return False
    heading = norm(" ".join(page.titles[0]))
    body = norm(" ".join(page.words))
    if heading != norm(candidate.get("title")):
        return False
    if norm(candidate.get("venue")) not in body:
        return False
    try:
        day = date.fromisoformat(candidate["date_start"])
        cue = (WEEKDAYS[day.weekday()] + " " + str(day.day) + " " + MONTHS[day.month])
        if cue not in body:
            return False
    except (ValueError, KeyError, TypeError):
        return False
    # Do not pick hours from a different event's page or from a global calendar.
    if not (local_time_present(body, candidate.get("start_local"))
            and local_time_present(body, candidate.get("end_local"))):
        return False
    audience = candidate.get("audience_evidence")
    if audience == "tous_ages_familles":
        allowed = "tous les ages" in body and "famille" in body
    elif isinstance(audience, str) and re.fullmatch(r"des_\d{1,2}_ans", audience):
        n = audience.split("_")[1]
        allowed = bool(re.search(rf"\b(?:des|de|a partir de) {n} ans\b", body))
    elif isinstance(audience, str) and re.fullmatch(r"jusqua_\d{1,2}_ans", audience):
        n = audience.split("_")[1]
        allowed = bool(re.search(rf"\benfants? jusqu a {n} ans\b", body))
    else:
        allowed = False
    if not allowed:
        return False
    if re.search(r"\b(?:annule|annulee|reporte|reportee|complet|reserve aux scolaires)\b", body):
        return False
    return True


def official_calendar_verified(candidate, html):
    if not isinstance(html, str) or len(html.encode("utf-8")) > MAX_HTML:
        return False
    cards = CalendarCards()
    cards.feed(html)
    try:
        day = date.fromisoformat(candidate["date_start"])
    except (KeyError, TypeError, ValueError):
        return False
    wanted_id = candidate.get("source_event_id")
    matching = [c for c in cards.cards
                if c["title_ids"] == [wanted_id] and c["venue_ids"] == [wanted_id]]
    if len(matching) != 1:
        return False
    content = norm(" ".join(matching[0]["words"]))
    # Day, month AND year must be in the very same SPIP card.
    if not (re.search(rf"\b{day.day}\b", content)
            and str(day.year) in content
            and (MONTHS[day.month] in content or
                 MONTHS[day.month][:3] in content)):
        return False
    if (norm(candidate.get("title")) not in content or
            norm(candidate.get("venue")) not in content):
        return False
    return (local_time_present(content, candidate.get("start_local"))
            and local_time_present(content, candidate.get("end_local")))


def access_is_honest(candidate, condition, html):
    page = OfficialPage()
    page.feed(html)
    if len(page.titles) != 1 or not page.finished:
        return False, "unreadable"
    text = norm(" ".join(page.words))
    has_free = bool(re.search(r"\bgratuit(?:e|ement)?\b", text))
    has_price = bool(re.search(r"\b(?:tarif|prix|entree|participation)\s+\d+", text))
    requires = bool(re.search(r"\b(?:sur inscription|inscription obligatoire|sur reservation|reservation obligatoire)\b", text))
    without = bool(re.search(r"\b(?:sans inscription|sans reservation)\b", text))
    price = condition.get("price_evidence")
    reg = condition.get("registration_evidence")
    if price == "explicit_free" and not has_free:
        return False, "unverified_free"
    if price == "explicit_price" and not has_price:
        return False, "unverified_price"
    if price == "not_stated" and (has_free or has_price):
        return False, "price_changed"
    if reg == "explicit_required" and not requires:
        return False, "registration_changed"
    if reg == "explicit_not_required" and not without:
        return False, "registration_changed"
    if reg == "not_stated" and (requires or without):
        return False, "registration_changed"
    if price in ("ambiguous", "contradictory") or reg in ("ambiguous", "contradictory"):
        return False, "ambiguous_access"
    # No inference from silence; showing 'Voir conditions' remains editorial.
    if price == "not_stated" or reg == "not_stated":
        return True, "editorial_conditions_required"
    return True, "conditions_explicit_recheck_required"


def audit_municipal(review, access, catalogue, today, get=read_official):
    """An independent evidence gate, NEVER a publisher or approval path."""
    base = audit(review, access, catalogue, today)
    access_by_id = {row["review_id"]: row for row in access["reviewed"]}
    previous_by_id = {row["review_id"]: row for row in base["details_for_private_review_only"]}
    results = []
    for candidate in review["candidates"]:
        uid = candidate["review_id"]
        expected_day = date.fromisoformat(candidate["date_start"])
        evidence = previous_by_id[uid]
        reasons = []
        if candidate.get("calendar_url") != municipal_calendar_url(expected_day):
            reasons.append("wrong_municipal_calendar")
        if not safe_event_url(candidate.get("official_event_url")):
            reasons.append("untrusted_event_host")
        if not reasons:
            try:
                event_html = get(candidate["official_event_url"])
                calendar_html = get(candidate["calendar_url"])
                if not official_event_verified(candidate, event_html):
                    reasons.append("official_event_not_reconfirmed")
                if not official_calendar_verified(candidate, calendar_html):
                    reasons.append("calendar_occurrence_not_reconfirmed")
                if not reasons:
                    ok, state = access_is_honest(candidate, access_by_id[uid], event_html)
                    if not ok:
                        reasons.append(state)
                    else:
                        reasons.append(state)
            except (OSError, ValueError, UnicodeError) as exc:
                reasons.append("municipal_source_unavailable")
        reasons.extend(evidence["blockers"])
        results.append({"review_id": uid, "reasons": sorted(set(reasons)),
                        "private_approval": False, "public_writes": 0})
    return {"schema": SCHEMA, "mode": "independent_readonly_no_patch",
            "examined": len(results),
            "source_checks_executed": len(results),
            "needs_private_review": len(results),
            "approved": 0, "publication_ready": 0, "public_writes": 0,
            "details_private_only": results}


def main():
    import argparse
    from pathlib import Path
    p = argparse.ArgumentParser()
    for key in ("review", "access", "catalogue", "output"):
        p.add_argument("--" + key, type=Path, required=True)
    p.add_argument("--date", type=date.fromisoformat, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError("refuse_to_overwrite_existing_report")
    docs = [json.loads(getattr(args, k).read_text(encoding="utf-8"))
            for k in ("review", "access", "catalogue")]
    result = audit_municipal(*docs, today=args.date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps({"examined": result["examined"],
                      "private_review_required": result["needs_private_review"],
                      "approved": 0, "publication_ready": 0, "public_writes": 0}))


if __name__ == "__main__":
    main()
