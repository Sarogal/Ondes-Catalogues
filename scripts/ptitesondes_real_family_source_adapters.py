"""Read-only adapters for real family-outing discovery, never publisher input.

Supported shapes: Paris Opendatasoft Explore 2.1, reviewed MPT Montpellier
event HTML, and explicit iCalendar VEVENT occurrences. These are discovery
leads only. No geocoding, trusted-host registration, organiser attestation,
private approval, network I/O, catalogue write, or publishing in this module.
"""
from collections import Counter
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from ptitesondes_family_national_scope import FAMILY_TYPES, audit_family_scope

SCHEMA = "ptitesondes.real_family_source_discovery.v1"
PARIS_HOST = "www.paris.fr"
MPT_HOST = "mpt.montpellier.fr"
PARIS_DATA_URL = ("https://opendata.paris.fr/explore/dataset/"
                  "que-faire-a-paris-/")
MPT_AGENDA_URL = "https://mpt.montpellier.fr/evenements"
MAX_BATCH = 200
# Region timezone is an externally curated source property, never inferred.
TERRITORY_TIMEZONES = frozenset({
    "Europe/Paris", "America/Guadeloupe", "America/Martinique",
    "America/Cayenne", "Indian/Reunion", "Indian/Mayotte",
})
MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
}
DATE_FR = re.compile(
    r"\b([0-3]?\d)\s+(janvier|fevrier|mars|avril|mai|juin|juillet|aout|"
    r"septembre|octobre|novembre|decembre)\s+(20\d\d)\s*[-|]\s*"
    r"([0-2]\d:[0-5]\d)\s*>\s*([0-2]\d:[0-5]\d)\b"
)
CHILD = re.compile(
    r"\b(enfants?|tout.petit[s]?|bebes?|premiers ages|familles?|"
    r"parents.enfants|jeune public|ados?|adolescents?)\b"
)
BLOCKED = re.compile(r"\b(annul[eé]e?s?|report[eé]e?s?|complet[eè]s?)\b")


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "").casefold())
    return " ".join(re.sub(r"[^a-z0-9]+", " ", "".join(
        c for c in s if not unicodedata.combining(c)
    )).split())


def fold_accents(s):
    """Preserve date/time punctuation while removing French accents."""
    s = unicodedata.normalize("NFKD", str(s or "").casefold())
    return "".join(c for c in s if not unicodedata.combining(c))


def safe_https(url, host, prefix="/"):
    if not isinstance(url, str) or len(url) > 700:
        return False
    try:
        p = urlsplit(url)
        return (p.scheme == "https" and p.hostname == host
                and not p.username and not p.password
                and p.port in (None, 443) and not p.fragment
                and p.path.startswith(prefix))
    except ValueError:
        return False


def classify(title, labels=""):
    """Only unambiguous explicit themes; all others need editorial review."""
    value = norm(title + " " + labels)
    # Never re-route the existing seven musical categories into the
    # experimental non-musical family contract.
    if re.search(r"\b(musique|musical|concert|chant|chorale|percussions)\b", value):
        return None
    patterns = (
        ("atelier-scientifique", r"\b(scientifique|astronomi|robotique|experiences de science)\b"),
        ("atelier-numerique", r"\b(numerique|programmation informatique|codage)\b"),
        ("lecture-jeunesse", r"\b(conte|lecture|histoires|bebes lecteurs)\b"),
        ("atelier-creatif", r"\b(creatif|arts plastiques|cyanotype|peinture|dessin)\b"),
        ("atelier-sensoriel", r"\b(snoezelen|ateliers? sensoriels?|eveil sensoriel|experience sensorielle|espace sensoriel)\b"),
        ("cinema-jeunesse", r"\b(cinema|court metrage|film jeunesse)\b"),
        ("activite-sportive", r"\b(motricite|sport|parcours sensorimoteur|piscine)\b"),
        ("sortie-nature", r"\b(nature|foret|biodiversite|balade botanique)\b"),
        ("animaux-ferme", r"\b(ferme pedagogique|animaux de ferme)\b"),
        ("musee-patrimoine", r"\b(musee|patrimoine|visite du chateau)\b"),
        ("jeux-famille", r"\b(ludotheque|jeux de societe)\b"),
        ("spectacle-jeunesse", r"\b(marionnettes|cirque|magie|theatre jeunesse)\b"),
        ("fete-familiale", r"\b(fete des enfants|fete familiale)\b"),
    )
    matched = {category for category, pat in patterns if re.search(pat, value)}
    return next(iter(matched)) if len(matched) == 1 else None


def _lead(provider, title, url, day, clock, venue, city, audience, category,
          price="not_stated", registration="not_stated", source_id=None):
    return {
        "provider": provider, "title": title, "source_url": url,
        "date_start": day, "date_end": day, "start_local": clock,
        "venue": venue, "city": city, "audience_claim": audience,
        "category": category, "price_evidence": price,
        "registration_evidence": registration, "source_id": source_id,
        "verification": "discovery_only_needs_official_and_independent_proof",
    }


def _in_window(day, today):
    try:
        d = date.fromisoformat(day)
        return today <= d <= today + timedelta(days=183)
    except (TypeError, ValueError):
        return False


def _dt(raw):
    if not isinstance(raw, str):
        return None
    try:
        x = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return x if x.tzinfo is not None and x.utcoffset() is not None else None
    except ValueError:
        return None


def parse_paris_explore(response, today):
    """Extract only explicitly scheduled, youth-identified Paris API records.

    URL example: https://opendata.paris.fr/api/explore/v2.1/catalog/
    datasets/que-faire-a-paris-/records?limit=100 (paged upstream).
    Records' "occurrences" list is authoritative for individual sessions;
    a date_start/date_end RANGE is NOT expanded into invented dates.
    """
    if type(today) is not date or not isinstance(response, dict):
        raise ValueError("invalid_paris_payload")
    records = response.get("results")
    if not isinstance(records, list) or len(records) > MAX_BATCH:
        raise ValueError("invalid_paris_records")
    out = []
    for row in records:
        if not isinstance(row, dict):
            continue
        title, url = row.get("title"), row.get("url")
        if not isinstance(title, str) or not safe_https(
                url, PARIS_HOST, "/evenements/"):
            continue
        audience = norm(str(row.get("audience") or "") + " " +
                        str(row.get("childrens") or "") + " " +
                        str(row.get("qfap_tags") or ""))
        if not CHILD.search(audience):
            continue
        if BLOCKED.search(norm(str(row.get("status") or ""))):
            continue
        venue, city = row.get("address_name"), row.get("address_city")
        if not isinstance(venue, str) or not isinstance(city, str):
            continue
        if not venue.strip() or not city.strip():
            continue
        raw = row.get("occurrences")
        if not isinstance(raw, str) or len(raw) > 20000:
            continue
        category = classify(title, str(row.get("qfap_tags") or ""))
        # A participation flag is not a precise age or price claim.
        price = "not_stated"
        registration = "not_stated"
        ident = str(row.get("id") or "")[:80]
        for token in raw.split(";")[:100]:
            if "_" not in token:
                continue
            a, b = token.split("_", 1)
            start, end = _dt(a), _dt(b)
            if start is None or end is None or end <= start:
                continue
            start = start.astimezone(ZoneInfo("Europe/Paris"))
            end = end.astimezone(ZoneInfo("Europe/Paris"))
            if start.date() != end.date() or not _in_window(
                    start.date().isoformat(), today):
                continue
            out.append(_lead("paris_opendatasoft", title.strip(), url,
                             start.date().isoformat(), start.strftime("%H:%M"),
                             venue.strip(), city.strip(), "explicit_child",
                             category, price, registration, ident))
    return _distinct(out)


class _MptVisible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.heading = []
        self.in_h1 = False
        self.h1_seen = False
        self.in_h2 = False
        self.h2_text = []
        self.parts = []
        self.stopped = False
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.hidden += 1
        if tag == "h1" and not self.h1_seen:
            self.in_h1 = True
        if tag == "h2" and self.h1_seen:
            self.in_h2 = True
            self.h2_text = []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.hidden:
            self.hidden -= 1
        if tag == "h1" and self.in_h1:
            self.in_h1 = False
            self.h1_seen = True
        if tag == "h2" and self.in_h2:
            self.in_h2 = False
            if "autres evenements" in norm(" ".join(self.h2_text)):
                self.stopped = True

    def handle_data(self, data):
        if self.hidden or self.stopped or not data.strip():
            return
        if self.in_h1:
            self.heading.append(data.strip())
        elif self.in_h2:
            self.h2_text.append(data.strip())
        elif self.h1_seen:
            self.parts.append(data.strip())



def _mpt_first_party_venue(parts):
    """Named venue on the detail page, never copied from related events.

    The current MPT template displays 'Maison pour tous <name>' followed by
    'Organisé par la maison <name>'. Both cues must agree. This is only a
    source-asserted venue string, NOT an independently geocoded place.
    """
    for i, raw in enumerate(parts):
        if norm(raw) in ("lieu", "lieu :"):
            return parts[i + 1] if i + 1 < len(parts) else None
        if raw.casefold().startswith("lieu :"):
            return raw.split(":", 1)[1].strip() or (
                parts[i + 1] if i + 1 < len(parts) else None
            )
    for i, raw in enumerate(parts):
        label = norm(raw)
        if not label.startswith("maison pour tous "):
            continue
        organizer_name = label[len("maison pour tous "):].strip()
        if not 3 <= len(organizer_name) <= 80:
            continue
        # Exact site-template crosscheck, not a city/venue guess.
        # The marker and organizer name are often separate text nodes.
        following = [norm(chunk) for chunk in parts[i + 1:i + 18]]
        for j, item in enumerate(following):
            if item == "organise par la maison" and (
                    j + 1 < len(following)
                    and following[j + 1] == organizer_name):
                return raw
            if item == "organise par la maison " + organizer_name:
                return raw
    return None


def _mpt_adult_only_declared(parts):
    """Use explicit template audience *labels*, not descriptive child words.

    A description about a young child is not evidence that the workshop
    welcomes children. A genuine mixed label such as 'Enfants, Adultes'
    must remain eligible for later independent review.
    """
    vocabulary = frozenset((
        "enfant", "enfants", "adultes", "adulte", "seniors", "senior",
        "famille", "familles", "tout", "tous", "public", "petit", "petits",
        "bebe", "bebes", "premiers", "ages", "adolescent", "adolescents",
        "seulement", "uniquement",
    ))
    audience_rows = []
    for chunk in parts[:10]:
        if not isinstance(chunk, str) or len(chunk) > 80:
            continue
        tokens = norm(chunk).split()
        if 1 <= len(tokens) <= 6 and set(tokens) <= vocabulary:
            audience_rows.append(set(tokens))
    if not any(row & {"adultes", "adulte", "seniors", "senior"}
               for row in audience_rows):
        return False
    child_cues = {
        "enfant", "enfants", "famille", "familles", "bebe", "bebes",
        "petit", "petits", "premiers", "adolescent", "adolescents",
    }
    return not any((row & child_cues or
                    {"tout", "public"} <= row)
                   for row in audience_rows)


def parse_montpellier_mpt_detail(html, url, today):
    """Read a *detail page*, not list cards; never copy unrelated events."""
    if (type(today) is not date or not safe_https(
            url, MPT_HOST, "/evenement/") or not isinstance(html, str)
            or not 50 <= len(html) <= 1_500_000):
        raise ValueError("invalid_mpt_detail")
    p = _MptVisible()
    p.feed(html)
    title = " ".join(p.heading)
    if not title or len(title) > 180:
        return []
    contents = " ".join(p.parts)
    normal = norm(contents)
    if (BLOCKED.search(normal) or not CHILD.search(normal)
            or _mpt_adult_only_declared(p.parts)):
        return []
    # Explicit first-party venue only; independent venue/GPS proof is later.
    venue = _mpt_first_party_venue(p.parts)
    if not venue:
        return []
    venue = venue.split("(", 1)[0].strip()
    if not 3 <= len(venue) <= 150:
        return []
    audience = "explicit_child" if re.search(
        r"\b(enfants?|tout.petit|bebes?|premiers ages|adolescents?)\b", normal
    ) else "explicit_family"
    price = "explicit_free" if "gratuit" in normal else "not_stated"
    if "€" in contents or re.search(r"\b[0-9]+\s*euros?\b", normal):
        price = "explicit_price" if price == "not_stated" else "contradictory"
    if price == "explicit_free" and any(
            condition in normal for condition in ("carte mpt obligatoire",
                                                "adhesion obligatoire")):
        price = "ambiguous"  # free session != necessarily free access
    registration = ("explicit_required" if "sur inscription" in normal or
                    "inscription obligatoire" in normal else "not_stated")
    category = classify(title)
    out = []
    for day, month, year, clock, ending in DATE_FR.findall(fold_accents(contents)):
        try:
            d = date(int(year), MONTHS[month], int(day))
            hh, mm = map(int, clock.split(":"))
            eh, em = map(int, ending.split(":"))
            if hh > 23 or eh > 23 or (eh, em) <= (hh, mm):
                continue
        except (ValueError, KeyError):
            continue
        if _in_window(d.isoformat(), today):
            out.append(_lead("montpellier_mpt", title, url, d.isoformat(),
                             clock, venue, "Montpellier", audience, category,
                             price, registration))
    return _distinct(out)


def _unfold_ics(value):
    return re.sub(r"\r?\n[ \t]", "", value)


def parse_ical(text, feed_url, today, *, target_timezone="Europe/Paris"):
    """Cross-municipality iCalendar adapter: strictly explicit clock timestamps.

    Requires DTSTART UTC Z or explicit matching TZID, never naive clocks.
    target_timezone must be a reviewed French territory IANA zone.
    RRULE/RDATE/EXDATE never expanded. Location cannot supply GPS or city.
    """
    if target_timezone not in TERRITORY_TIMEZONES:
        raise ValueError("unreviewed_feed_timezone")
    if (type(today) is not date or not isinstance(text, str)
            or not text.startswith("BEGIN:VCALENDAR")
            or not 50 <= len(text) <= 2_000_000
            or not isinstance(feed_url, str) or
            urlsplit(feed_url).scheme != "https"):
        raise ValueError("invalid_ical_feed")
    if "\nBEGIN:VEVENT" not in _unfold_ics(text):
        return []
    out = []
    for chunk in _unfold_ics(text).split("BEGIN:VEVENT")[1:201]:
        if "END:VEVENT" not in chunk:
            continue
        lines = chunk.split("END:VEVENT", 1)[0].splitlines()
        props = {}
        for ln in lines:
            if ":" in ln and len(ln) <= 2000:
                key, val = ln.split(":", 1)
                k = key.split(";", 1)
                normalized_key = k[0].upper() + (";" + k[1] if len(k) == 2 else "")
                props.setdefault(normalized_key, val.replace(r"\,", ",")
                                 .replace(r"\n", " ").strip())
        if any(k.startswith(("RRULE", "RDATE", "EXDATE")) for k in props):
            continue  # never invent recurrence instances
        if norm(props.get("STATUS", "")) in ("cancelled", "canceled"):
            continue
        key = next((k for k in props if k == "DTSTART" or
                    k.upper().startswith("DTSTART;TZID=")), None)
        if not key:
            continue
        raw = props[key]
        dt = None
        try:
            if key == "DTSTART" and re.fullmatch(r"\d{8}T\d{6}Z", raw):
                dt = datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(
                    tzinfo=ZoneInfo("UTC"))
            elif (key.upper().startswith("DTSTART;TZID=")
                  and key.split("=", 1)[1] == target_timezone
                  and re.fullmatch(r"\d{8}T\d{6}", raw)):
                # TZID values are case-sensitive IANA names.
                dt = datetime.strptime(raw, "%Y%m%dT%H%M%S").replace(
                    tzinfo=ZoneInfo(target_timezone))
        except ValueError:
            continue
        if dt is None:
            continue
        local = dt.astimezone(ZoneInfo(target_timezone))
        if not _in_window(local.date().isoformat(), today):
            continue
        title = props.get("SUMMARY", "")
        url = props.get("URL", "")
        descr = norm(title + " " + props.get("DESCRIPTION", ""))
        if (not CHILD.search(descr) or
                not isinstance(title, str) or not 5 <= len(title) <= 180):
            continue
        if not safe_https(url, urlsplit(feed_url).hostname or "", "/"):
            continue
        venue = props.get("LOCATION")
        if not venue or len(venue) > 160:
            continue
        out.append(_lead("ical", title, url, local.date().isoformat(),
                         local.strftime("%H:%M"), venue, None,
                         "explicit_child", classify(title),
                         source_id=props.get("UID", "")[:80]))
    return _distinct(out)


def _distinct(leads):
    unique = {}
    for row in leads:
        signature = (norm(row["title"]), norm(row["venue"]),
                     row["date_start"], row["start_local"], row["source_url"])
        unique[signature] = row
    return sorted(unique.values(), key=lambda x: (
        x["date_start"], x["start_local"], x["title"]))


def scope_proposals(leads, today):
    """Existing #342 scope contract; never generate a preflight SOURCE/GPS.

    The independent #346 stage still requires separate verified host/venue
    registries and page fetch, not anything copied from the collector.
    """
    proposals = []
    for item in leads:
        category = item.get("category")
        if (category not in FAMILY_TYPES or not item.get("city")
                or not item.get("venue")):
            continue
        proposals.append({
            "record_kind": "dated_event", "title": item["title"],
            "city": item["city"], "venue": item["venue"],
            "source_url": item["source_url"],
            "audience_claim": item["audience_claim"],
            "age_min": None, "age_max": None,
            "price_evidence": item["price_evidence"],
            "registration_evidence": item["registration_evidence"],
            "category": category, "category_label": FAMILY_TYPES[category][0],
            "date_start": item["date_start"], "date_end": item["date_end"],
        })
    # 100 is the existing #342 per-call bound; chunks cannot confer approval.
    outcomes = []
    for n in range(0, len(proposals), 100):
        outcomes.append(audit_family_scope(proposals[n:n+100], today))
    return outcomes


def coverage_report(batch_by_provider, today):
    """Anonymous metrics only; synthetic fixtures must not be reported as live."""
    if type(today) is not date or not isinstance(batch_by_provider, dict):
        raise ValueError("invalid_coverage_request")
    providers, categories = {}, Counter()
    total, with_venue, classified = 0, 0, 0
    for provider, leads in batch_by_provider.items():
        if provider not in {"paris_opendatasoft", "montpellier_mpt", "ical"}:
            raise ValueError("unknown_provider")
        if not isinstance(leads, list) or len(leads) > 500:
            raise ValueError("invalid_lead_batch")
        providers[provider] = len(leads)
        total += len(leads)
        with_venue += sum(bool(x.get("venue") and x.get("city")) for x in leads)
        classified += sum(x.get("category") in FAMILY_TYPES for x in leads)
        categories.update(x["category"] for x in leads if
                          x.get("category") in FAMILY_TYPES)
    return {
        "schema": SCHEMA, "mode": "read_only_discovery_not_admission",
        "source_counts": providers, "discovered_occurrences": total,
        "with_explicit_city_and_venue": with_venue,
        "classified_proposals": classified,
        "category_counts": dict(sorted(categories.items())),
        "official_source_cues_independently_validated": 0,
        "organiser_identity_authenticated": False,
        "external_geo_verified": 0, "private_approvals": 0,
        "published_fiches": 0, "publisher_not_connected": True,
        "publication_ready": False, "approval_granted_to_publisher": False,
        "public_writes": 0,
    }
