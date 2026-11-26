"""Admission of an UNLISTED first-party concert venue source.

The existing published venue is an identity anchor, NOT an allowlist of domains.
On every initial publication, the independent publisher fetches the fresh
individual MusicEvent and the named OpenStreetMap feature. The OSM feature
must explicitly link to the event site's actual HTTPS origin. A forged source
label, unknown organizer manifest entry, ticket listing, or merely matching
venue name cannot establish source authority.

Only for events at EXISTING catalogue venues with an OSM NODE source. New site
and organizer/producer cases use separate contracts and remain pending.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit, urlencode
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "automation/concerts"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))
import discover
import official_rss_jsonld_bridge as bridge
import source_admission_intake as intake
import source_evidence_probe as probe
import source_cross_domain_live_recheck as cross_live
import source_cross_domain_corroboration as cross
import triage
import official_venue_single_source as official_source
import openagenda_official_concert as openagenda
from independent_named_site_geo import _distance_meters

PROFILE = "dynamic-existing-venue-first-party-v1"
# A verified OSM node is independent location+website authority. A concert
# on that attributed HTTPS domain can stand on its own after a fresh exact
# MusicEvent recheck by the publisher; a second event domain is optional.
OSM_SINGLE_PROFILE = "dynamic-existing-venue-osm-official-v1"
# Existing published venues with historical non-OSM geoSource may be
# independently checked via their EXACT French street + named OSM feature.
# A city centroid or venue name alone never creates source authority.
OSM_ADDRESS_PROFILE = "dynamic-existing-venue-address-official-v1"
# Once a venue's official agenda is explicitly bound to the published site,
# ONE first-party event page suffices. No second concert witness or live OSM.
OFFICIAL_SOURCE_PROFILE = "dynamic-existing-venue-official-single-source-v1"
OPENAGENDA_PROFILE = "dynamic-existing-venue-openagenda-single-source-v1"
OPENAGENDA_CHECKED = ["artists", "date", "venue", "genre", "openAgendaPage"]
OPENAGENDA_PROOF_FIELDS = frozenset({
    "url", "proofType", "checkedAt", "checkedFields",
    "officialArtistNames", "officialGenreLabels", "officialOpenAgendaEventUrl",
})
OPENAGENDA_EXPORT_PROOF_FIELDS = OPENAGENDA_PROOF_FIELDS | frozenset({
    "officialOpenAgendaUid", "officialOpenAgendaEventUid",
})
OFFICIAL_SOURCE_PROOF_FIELDS = frozenset({
    "url", "proofType", "checkedAt", "checkedFields",
    "officialArtistNames", "officialGenreLabels", "officialVenueSourceUrl",
})
PROOF_FIELDS = frozenset({
    "url", "proofType", "checkedAt", "checkedFields",
    "officialArtistNames", "officialGenreLabels", "namedOsmUrl",
    "corroboratingEventUrl",
})
OSM_SINGLE_PROOF_FIELDS = PROOF_FIELDS - {"corroboratingEventUrl"}
OSM_ADDRESS_PROOF_FIELDS = OSM_SINGLE_PROOF_FIELDS | {
    "publishedVenueGeoSource", "sourceWebsite"}
CHECKED = ["artists", "date", "venue", "genre", "sourceWebsite"]
ADDRESS_CHECKED = CHECKED + ["independentLocation"]
# Publicly signed venue coordinates may reference either the human-friendly
# node page or the canonical API node path. Both encode the SAME immutable
# numeric OSM object ID; neither provides a network destination.
OSM_NODE = re.compile(
    r"https://(?:www[.]openstreetmap[.]org/(?:api/0[.]6/)?node/|"
    r"api[.]openstreetmap[.]org/api/0[.]6/node/)([1-9][0-9]*)\Z"
)
MAX_DISTANCE = 125
MAX_ARTIST_NAME = 120


def require(ok, message):
    if not ok:
        raise ValueError("Unlisted official source: " + message)


def normal(value):
    if not isinstance(value, str):
        return ""
    return triage.words(value.translate(str.maketrans({
        "’": "'", "‘": "'", "ʼ": "'", "＇": "'",
    })))


def url_host(value):
    host = intake.valid_https(value)
    require(bool(host), "unsafe HTTPS URL")
    parts = urlsplit(value)
    require(bool(parts.path and parts.path != "/") and
            not parts.fragment, "individual event detail required")
    return host


def origin_match(url_a, url_b):
    """Only an identical HTTPS origin, with an optional www prefix, matches."""
    try:
        a, b = url_host(url_a), intake.valid_https(url_b)
        require(bool(b), "OSM website is not a valid HTTPS source")
    except (TypeError, ValueError):
        return False
    return a.removeprefix("www.") == b.removeprefix("www.")


def safe_fetch(url, cache):
    return probe.safe_fetch(url, cache)


def osm_identity(venue, event_url, fetch, cache):
    """Independently read OSM feature identity; never trust venue.geoSource only."""
    raw = venue.get("geoSource")
    require(isinstance(raw, str), "venue has no independent OSM feature")
    matched = OSM_NODE.fullmatch(raw)
    require(bool(matched), "named OSM node (web/API) required for this admission route")
    # Both hosts are official OpenStreetMap API origins. Some public runners
    # cannot reach one origin reliably. Retry ONLY a network failure, never
    # a successfully fetched but contradictory/malformed OSM identity.
    # The numeric node is still taken solely from the published venue ref.
    api_paths = (
        "https://api.openstreetmap.org/api/0.6/node/",
        "https://www.openstreetmap.org/api/0.6/node/",
    )
    body = None
    for prefix in api_paths:
        try:
            body = fetch(prefix + matched.group(1), cache)
            break
        except (ValueError, OSError, TimeoutError):
            continue
    if body is None:
        # OpenStreetMap's Editing API is not a dependable READ-ONLY data
        # source for national concert research. Use a dedicated Overpass
        # read-only provider with a FIXED bounded, single-node query.
        # No candidate-controlled URL, user-supplied query or redirect.
        # This still uses the robots-aware, DNS-pinned HTTPS fetcher.
        import osm_read_only_fallback as readonly
        last_transport_error = None
        for provider in (0, 1):
            # Both transports read the SAME immutable numeric OSM node.
            # Never retry a successful but contradictory identity response.
            overpass_url = readonly.element(
                "node", matched.group(1), provider=provider)
            try:
                body = fetch(overpass_url, cache)
                break
            except (ValueError, OSError, TimeoutError) as exc:
                last_transport_error = exc
        if body is None:
            raise ValueError(
                "Unlisted official source: all OSM read-only transports unavailable"
            ) from last_transport_error
    require(body is not None, "OSM feature not independently fetched")
    require(isinstance(body, str) and len(body) <= probe.MAX_BYTES
            and "<!DOCTYPE" not in body.upper()
            and "<!ENTITY" not in body.upper(), "OSM answer invalid")
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise ValueError("Unlisted official source: malformed OSM XML") from exc
    require(root.tag == "osm", "OSM document invalid")
    nodes = root.findall("node")
    require(len(nodes) == 1 and nodes[0].get("id") == matched.group(1),
            "named OSM node mismatched")
    node = nodes[0]
    tags = {tag.get("k"): tag.get("v") for tag in node.findall("tag")
            if isinstance(tag.get("k"), str)
            and isinstance(tag.get("v"), str)}
    require(normal(tags.get("name")) == normal(venue.get("name")),
            "OSM node does not identify published venue")
    for tag, field in (("addr:city", "city"), ("addr:postcode", "postalCode"),
                       ("addr:country", "country")):
        if tag == "addr:country":
            require(tags.get(tag, "FR").upper() == "FR", "OSM site outside France")
        elif tags.get(tag):
            require(normal(tags[tag]) == normal(venue.get(field)),
                    "OSM place/address differs from catalogue")
    try:
        lat, lon = float(node.get("lat")), float(node.get("lon"))
        require(_distance_meters(lat, lon,
                float(venue["latitude"]), float(venue["longitude"]))
                <= MAX_DISTANCE, "OSM point differs from signed published map")
    except (ValueError, TypeError, OverflowError):
        raise ValueError("Unlisted official source: invalid OSM coordinates")
    websites = [tags[key] for key in ("website", "contact:website")
                if isinstance(tags.get(key), str) and tags[key].strip()]
    require(len(websites) >= 1 and
            all(origin_match(event_url, value) for value in websites),
            "OSM does not independently attribute event domain to this venue")
    return raw



def address_identity(venue, event_url, fetch, cache):
    """Authenticate existing published venue by exact BAN/OSM + HTTPS website.

    All external geography requests use fixed government/OSM origins.
    Neither a discovery claim nor the venue's historical geoSource hostname
    is trusted as proof of the currently attributed official event website.
    """
    import independent_named_site_geo as named_geo
    import venue_address_osm_source as address_osm
    require(address_osm.eligible_address(venue),
            "published venue has no exact geocodable street address")

    def bounded(url, limit):
        response = fetch(url, cache)
        require(isinstance(response, str) and
                0 < len(response) <= min(limit, probe.MAX_BYTES),
                "independent French address or OSM proof unavailable")
        return response, url

    # The publisher enforces BAN score >= 0.78 plus exact house number,
    # street, municipality and postcode, then a single named OSM point/way.
    # A search ranking score cannot grant first-party domain authority.
    feature, lat, lon, precision = named_geo.verify(venue, bounded)
    require(precision in {"named-site-point", "named-site-area"},
            "independent OSM feature is not a physical named location")
    try:
        distance = _distance_meters(
            lat, lon, float(venue["latitude"]), float(venue["longitude"]))
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise ValueError(
            "Unlisted official source: published venue has no map coordinates") from exc
    require(distance <= MAX_DISTANCE,
            "published venue map pin differs from independently named site")

    # Re-fetch the exact named OSM feature and its own website tags.
    homepage, independently_named = address_osm.website_from_address(
        venue, fetch=fetch, cache=cache)
    require(independently_named == feature,
            "independent named OSM feature changed across fresh checks")
    require(origin_match(event_url, homepage),
            "named OSM site does not attribute the event's HTTPS domain")
    return feature, homepage


def individual_event_nodes(html, *, accept_generic=False):
    """Read isolated official event facts; never borrow fields from other cards.

    Only the independently OSM-attributed source-unique profile may use
    generic schema.org Event or visible HTML microdata. If JSON-LD already
    declares an Event, bad or contradictory structured claims must not be
    masked by falling back to another HTML representation.
    """
    types = {"MusicEvent", "Event"} if accept_generic else {"MusicEvent"}
    nodes = [n for n in discover.read_ld(html)
             if isinstance(n, dict)
             and bridge._event_types(n.get("@type")) & types]
    if accept_generic and not nodes:
        import event_site_microdata
        nodes = event_site_microdata.read_microdata_events(html)
    return nodes


def sparse_visible_event_detail(html, nodes, url, when, venue, *, tour_only=False):
    """Replay the complete visible card for one incomplete structured event.

    An incomplete schema is not a contradictory schema. Only a single
    canonical Event with no structured roster or genre can use this path.
    Keep any stated date, location and status constraints; require the same
    exact named visible bill and full date, event genre and venue card.
    The caller must independently authenticate the official source first.
    """
    if len(nodes) != 1:
        return None
    node = nodes[0]
    if (not isinstance(node, dict) or node.get("url") != url
            or not normal(node.get("name"))
            or discover.reject_listing(node.get("name"))
            or node.get("performer") not in (None, "", [])
            or node.get("genre") not in (None, "", [])
            or node.get("startDate") not in (None, "")
            and discover.iso_day(node.get("startDate")) != when):
        return None
    status = node.get("eventStatus")
    if status not in (None, ""):
        if isinstance(status, dict):
            status = status.get("@id")
        if not isinstance(status, str) or status.rsplit("/", 1)[-1] != "EventScheduled":
            return None
    location = node.get("location")
    if location not in (None, "", {}):
        # Only truly sparse Place objects. A substantive or contradictory
        # structured address must go through the normal structured verifier.
        if (not isinstance(location, dict)
                or set(location) - {"@type", "name", "country"}
                or bridge._event_types(location.get("@type")) != {"Place"}
                or location.get("name") not in (None, "")
                and normal(location.get("name")) != normal(venue["name"])):
            return None
        country = location.get("country")
        if country not in (None, ""):
            if isinstance(country, dict):
                country = country.get("name") or country.get("@id")
            if normal(country) not in {"fr", "france", "republique francaise"}:
                return None
    # The title may identify a TOUR rather than its participating artists.
    # Verify its independently named roster in the same official detail.
    # Do not use this new path to publish against a known municipal centroid.
    from automation.concerts import official_visible_tour_bill
    precision = normal(venue.get("geoPrecision"))
    if "centre de commune" not in precision and "position indicative" not in precision:
        tour = official_visible_tour_bill.verified_tour(
            html, node["name"], venue["name"], venue["city"], when)
        if tour is not None:
            return tour
    if tour_only:
        return None
    from automation.concerts import open_world_visible_cards
    detail = open_world_visible_cards.verified_detail(
        html, venue["name"], venue["city"], when,
        address=venue.get("address"), postal=venue.get("postalCode"))
    if detail is None:
        return None
    names, genres = detail
    if normal(" + ".join(names)) != normal(node.get("name")):
        return None
    return names, genres


def _direct_artist_description(name, description):
    """Accept a literal named subject + musical identity, not influences."""
    from automation.concerts import artist_official_bio as biographies

    if (not isinstance(description, str) or not 0 < len(description) <= 8000
            or not isinstance(name, str) or not normal(name)
            or "<" in description or ">" in description):
        return []
    first = re.split(r"[.!?;\n](?:\s|$)", description.strip(), maxsplit=1)[0]
    text = normal(first)
    subject = re.escape(normal(name))
    # Restrict to the opening assertion, not mere proximity of a genre
    # to a name. No influence, comparison, support act or negation inference.
    if re.search(r"\b(?:not|never|pas|sans|rather|tribute|hommage|"
                 r"influence|influenced|influences|inspire|inspiree)\b", text):
        return []
    suffix = r"(?: (?:from|based in|formed in|originaire de|forme en|base a) [a-z0-9 ]{1,100})?"
    for genre in sorted(biographies.BIO_GENRES, key=len, reverse=True):
        label = re.escape(normal(genre))
        patterns = (
            subject + r" (?:is|are) (?:an? )?" + label
            + r" (?:band|group|duo|trio|artist|musician|singer)" + suffix,
            subject + r" (?:est|sont) (?:un|une) (?:groupe|duo|trio|artiste|musicien|musicienne|chanteur|chanteuse) (?:de|du|d) "
            + label + suffix,
            subject + r" (?:plays|play|joue|jouent|pratique|pratiquent) (?:du |de la )?"
            + label,
        )
        if any(re.fullmatch(pattern, text) for pattern in patterns):
            return [genre.title()]
    return []


def _visible_artist_sections(html, title):
    """Only the exact individual event's visible content, not suggestions."""
    import official_html_evidence as visible

    if not isinstance(html, str) or not 0 < len(html) <= probe.MAX_BYTES:
        return []
    parsed = visible.VisibleBlocks()
    parsed.feed(html)
    parsed.close()
    headings = [(i, text) for i, (kind, text) in enumerate(parsed.blocks)
                if kind == "h1"]
    if len(headings) != 1 or not normal(title) or normal(headings[0][1]) != normal(title):
        return []
    section = []
    for kind, text in parsed.blocks[headings[0][0] + 1:]:
        if normal(text) in visible.END_SECTION or normal(text) in {
                "vous devriez aimer", "nous vous recommandons egalement",
                "we also recommend"}:
            break
        section.append((kind, text))
    return section


def _visible_artist_labels(section, name):
    """Exact standalone subgenre labels immediately under an artist heading."""
    from automation.concerts import artist_official_bio as biographies

    matches = [i for i, (kind, text) in enumerate(section)
               if kind in ("h2", "h3", "h4") and normal(text) == normal(name)]
    if len(matches) != 1:
        return []
    # Exact vocabulary, not substring hits such as 'influenced by metal'.
    allowed = {normal(g): g.title() for g in
               (*triage.POSITIVE_GENRES, *biographies.BIO_GENRES)
               if normal(g) not in {"hardcore", "rock"}}
    labels = []
    for kind, text in section[matches[0] + 1:matches[0] + 7]:
        if kind not in ("p", "span", "strong", "text"):
            break
        label = allowed.get(normal(text))
        if label:
            if label not in labels:
                labels.append(label)
            continue
        # A neutral genre badge may precede a relevant one. Unknown short
        # fragments (including "not", "influences", etc.) end the label group.
        if normal(text) in {"pop", "synth pop", "synthpop", "darkwave",
                           "dark wave", "coldwave", "cold wave", "new wave",
                           "electro", "electronic", "jazz", "folk", "goth",
                           "cinematic", "indie", "dream pop", "rap", "hip hop"}:
            continue
        if not labels and kind == "p":
            return _direct_artist_description(name, text)
        break
    return labels


def _visible_artist_description(html, title, name):
    return _visible_artist_labels(_visible_artist_sections(html, title), name)


def _prose_artist_credit(prefix):
    """Recognize a bounded musical credit immediately before an exact name.

    A role-only credit proves a roster entry, not its genre. Genre claims
    require a literal style in a possessive credit or named musical role.
    No general event labels, comparisons, influence or other acts' genres.
    """
    from automation.concerts import artist_official_bio as biographies

    relevant = {normal(g): g.title() for g in
                (*triage.POSITIVE_GENRES, *biographies.BIO_GENRES)
                if normal(g) not in {"hardcore", "rock"}}
    neutral = {"rock", "rock alternatif", "alternative rock", "pop", "jazz",
               "electro", "electronique", "techno", "folk", "chanson",
               "hip hop", "rap", "indie pop", "synth pop", "darkwave"}
    role = (r"(?:groupe|trio|duo|quatuor|collectif|artiste|musicien|"
            r"musicienne|chanteur|chanteuse|band|singer)")
    modifiers = {"feministe", "anarchiste", "melodique", "atmospherique",
                 "progressif", "progressive", "experimental", "experimentale",
                 "brut", "brute", "energetique", "tres", "riot", "grrrl",
                 "grrrls", "grunge", "melodic", "raw", "feminist",
                 "anarchist", "alternatif", "alternative"}

    def styles(value, *, qualified=False):
        result = []
        for part in re.split(r" (?:et|and) ", value):
            if part in relevant:
                result.append(relevant[part])
                continue
            if part in neutral:
                continue
            label = next((g for g in sorted(relevant, key=lambda x: (-len(x), x))
                          if part.startswith(g + " ")
                          and set(part[len(g) + 1:].split()) <= modifiers), None)
            if not qualified or label is None:
                return None
            result.append(relevant[label])
        return list(dict.fromkeys(result))

    prefix = prefix.strip()
    # Read the closest valid grammatical credit, not an earlier artist's
    # description. Articles may also occur in the introductory prose.
    for article in reversed(list(re.finditer(
            r"\b(?:le|la|les|un|une|du|des|the|a|an) ", prefix))):
        body = prefix[article.end():]
        if re.fullmatch(role, body):
            return []
        song = re.fullmatch(r"(?:chansons|songs)(?: [a-z]+){0,6} (?:de|by)", body)
        if song:
            return []
        group = re.fullmatch(role + r" (?:de|du|d|of) (.+)", body)
        if group:
            style = re.sub(r" (?:originaire de|from) [a-z0-9]+(?: [a-z0-9]+){0,5}$",
                           "", group[1])
            labels = styles(style, qualified=True)
            if labels is not None:
                return labels
        possessive = re.fullmatch(r"(.+) (?:de|du|d|by)", body)
        if possessive:
            labels = styles(possessive[1], qualified=True)
            if labels is not None and labels:
                return labels
    return None


def _visible_prose_bill(section, names):
    """Recover a title roster from one independently named musical paragraph."""
    keys = [normal(n) for n in names]
    matches = {}
    for kind, paragraph in section:
        if kind != "p" or len(paragraph) > 1000:
            continue
        text = normal(paragraph)
        # This is an announced lineup, not an arbitrary biography or prose
        # mentioning artists. The caller has already checked source, date,
        # exact event heading and venue independently.
        if (not re.match(r"^(?:au programme\b|on the bill\b|line up\b|"
                         r"(?:un|une|le|la) (?:concert|soiree|session)\b"
                         r".{0,120}\bavec\b|(?:a|the) (?:concert|show)\b"
                         r".{0,120}\b(?:with|featuring)\b)", text)
                or triage.NONCONCERT.search(text)
                or re.search(r"\b(?:rencontre|discussion|interview|projection)\b", text)):
            continue
        # Reject comparisons, tribute/support descriptions and negation rather
        # than treating proximity to a musical keyword as positive evidence.
        if re.search(r"\b(?:not|no|never|pas|sans|ne|ni|tribute|hommage|"
                     r"influence|influences|influenced|inspire|inspires|inspiree|"
                     r"inspires|reprise|cover|support|annule|annulee|reporte|"
                     r"reportee|cancelled|postponed)\b", text):
            continue
        people = []
        position = 0
        for name, key in zip(names, keys):
            occurrences = list(re.finditer(
                r"(?<!\w)" + re.escape(key) + r"(?!\w)", text))
            if len(occurrences) != 1 or occurrences[0].start() < position:
                break
            occurrence = occurrences[0]
            labels = _prose_artist_credit(text[position:occurrence.start()])
            if labels is None:
                break
            person = {"@type": "MusicGroup", "name": name}
            if labels:
                person["genre"] = labels
            people.append(person)
            position = occurrence.end()
        if len(people) == len(names) and any(p.get("genre") for p in people):
            # Some sites duplicate their description in the event markup.
            # Identical visible paragraphs are one witness; distinct competing
            # descriptions are not a reason to choose one arbitrarily.
            matches[text] = people
    return next(iter(matches.values())) if len(matches) == 1 else None


def _recover_visible_bill(section, names):
    guest = names.pop() if names and bridge.is_unnamed_performer(names[-1]) else None
    keys = [normal(s) for s in names]
    if (not names or not all(2 <= len(s) <= 120 for s in names) or not all(keys)
            or len(set(keys)) != len(keys)
            or any(bridge.is_unnamed_performer(n) for n in names)):
        return None
    matched = [normal(t) for k, t in section
               if k in ("h2", "h3", "h4") and normal(t) in keys]
    if matched == keys:
        people = []
        for name in names:
            labels = _visible_artist_labels(section, name)
            person = {"@type": "MusicGroup", "name": name}
            if labels:
                person["genre"] = labels
            people.append(person)
    elif not matched:
        people = _visible_prose_bill(section, names)
    else:
        return None  # Partial/contradictory artist headings stay held.
    if not people or not any(p.get("genre") for p in people):
        return None
    if guest:
        people.append({"@type": "MusicGroup", "name": guest})
    return people if bridge.official_named_bill(people) else None


def visible_named_bill(html, title):
    """Recover an absent bill from its exact H1 and individual credits.

    Every title artist must be independently named in order, either by
    exact headings or by one explicit musical roster paragraph. A trailing
    unnamed guest is never published as an artist. No event genre inheritance.
    A slash may also be part of an artist name; never split it without
    corroboration of each individual credit and reject competing readings.
    """
    if not isinstance(title, str):
        return None
    section = _visible_artist_sections(html, title)
    legacy = [s.strip() for s in re.split(r"\s+\+\s+", title)]
    slash = [s.strip() for s in re.split(r"\s+(?:\+|/)\s+", title)]
    readings = [legacy] if slash == legacy else [legacy, slash]
    recovered = [_recover_visible_bill(section, list(names)) for names in readings]
    valid = [people for people in recovered if people is not None]
    return valid[0] if len(valid) == 1 else None


def event_genres(raw, official_url, *, fetch=None, cache=None, html=None):
    """Replay a venue-attributed performer identity, never a name-only match.

    The authenticated individual MusicEvent may describe its named performer
    directly or explicitly link to a fresh external profile describing that
    same MusicGroup or musician and a relevant genre. No registry tags,
    MusicBrainz match, unrelated Event, or general venue genre is authority.
    """
    genres, scope = bridge.event_genres_from_own_bill(raw)
    if triage.genre_evidence({
            "classification": genres, "genreEvidenceScope": scope,
            "officialDetailFound": True}):
        return genres, scope
    if fetch is None or not bridge._event_types(raw.get("@type")) & {"MusicEvent", "Event"}:
        return genres, scope
    from automation.concerts import open_world_artist_genre as profiles
    from automation.concerts import artist_official_bio as biographies
    bill = bridge.official_named_bill(raw.get("performer"))
    if not bill:
        return genres, scope
    names = set(bill[0])
    people = raw.get("performer")
    people = people if isinstance(people, list) else [people]
    # The authenticated event may describe a named artist directly, with
    # no artist URL or external directory. Structured genre conflicts cannot
    # be replaced by prose. All fields are replayed by the Publisher.
    linked = []
    for person in people:
        if not isinstance(person, dict):
            continue
        name = person.get("name")
        if (not isinstance(name, str) or name.strip() not in names
                or not bridge._event_types(person.get("@type")) & {"MusicGroup", "Person"}
                or person.get("genre") not in (None, "", [])):
            continue
        inline_labels = _direct_artist_description(name, person.get("description"))
        if not inline_labels:
            inline_labels = _visible_artist_description(html, raw.get("name"), name)
        if inline_labels:
            return inline_labels, "official_artist_in_event_detail"
        if "MusicEvent" not in bridge._event_types(raw.get("@type")):
            continue  # External profile navigation retains its original scope.
        target = person.get("url")
        host = intake.valid_https(target)
        if not host or host == intake.valid_https(official_url):
            continue
        try:
            probe.checked_uri(target, host)
        except (ValueError, TypeError):
            continue
        linked.append((name.strip(), target))
    # Bound requests, not lineup size. Unlinked performers do not consume
    # the budget; an eligible act can be anywhere on the official bill.
    shared = cache if cache is not None else {}
    for name, target in list(dict.fromkeys(linked))[:4]:
        try:
            html = fetch(target, shared)
            try:
                labels = profiles.profile_genres(html, name)
            except profiles.MissingStructuredArtistGenre:
                # Only a biography explicitly linked from the venue-attributed
                # performer page, on that same HTTPS host. At most one extra
                # fetch per linked performer. Never search by name or trust
                # cached directory hints here.
                bio_url = biographies.linked_official_biography(html, target, target)
                if bio_url:
                    probe.checked_uri(bio_url, intake.valid_https(target))
                    bio_html = fetch(bio_url, shared)
                    source = {"artistId": "linked-performer", "sourceRole": "artist_official",
                              "enabled": True, "url": target}
                    roster = {"artists": [{"id": "linked-performer", "name": name,
                                           "aliases": []}]}
                    fact = biographies.verify_official_biography(
                        source, roster, bio_html, bio_url, bio_url, dt.date.today())
                    labels = fact["genres"]
                else:
                    # The venue's exact MusicEvent explicitly links this
                    # performer. Re-fetch its named self-description directly,
                    # without trusting directory or cached research claims.
                    labels = biographies.direct_artist_description(html, name)
        except (ValueError, TypeError, KeyError, OSError, TimeoutError, RecursionError):
            continue
        if triage.genre_evidence({"classification": labels}):
            return labels, "official_artist_in_event_detail"
    return genres, scope


def _exact_location_description(location, venue):
    """Accept an exact published French address in THIS Event's Place.

    Some schema.org producers serialize an empty PostalAddress and put the
    complete address in Place.description. Never use page-wide prose, another
    Event, a city centroid, or contradict populated structured address fields.
    Called only after the source's independent venue identity is verified.
    """
    from html import unescape

    addr = location.get("address")
    if not isinstance(addr, dict):
        return False
    street, postal, city = (venue.get(k) for k in
                            ("address", "postalCode", "city"))
    if (not isinstance(street, str) or len(normal(street)) < 5
            or not isinstance(postal, str) or not re.fullmatch(r"[0-9]{5}", postal)
            or not isinstance(city, str) or not normal(city)):
        return False
    for field, expected in (("streetAddress", street), ("postalCode", postal),
                            ("addressLocality", city)):
        value = addr.get(field)
        if value not in (None, "") and normal(value) != normal(expected):
            return False
    for country in (addr.get("addressCountry"), location.get("country"),
                    location.get("addressCountry")):
        if country in (None, ""):
            continue
        if isinstance(country, dict):
            country = country.get("name") or country.get("@id")
        if normal(country) not in {"fr", "france", "republique francaise"}:
            return False
    description = location.get("description")
    if not isinstance(description, str) or not 5 <= len(description) <= 1000:
        return False
    value = normal(unescape(description))
    expected = normal(street + " " + postal + " " + city)
    # The venue address must be the leading, contiguous complete address.
    # A second postal code makes the physical location ambiguous.
    return (value == expected or value.startswith(expected + " ")) and (
        re.findall(r"(?<![0-9])[0-9]{5}(?![0-9])", value) == [postal])


def _event(raw, event, venue, artists, *, accept_generic=False,
           fetch=None, cache=None, html=None):
    """Verify one complete first-party concert event; never join evidence."""
    types = bridge._event_types(raw.get("@type")) if isinstance(raw, dict) else set()
    require("MusicEvent" in types or (accept_generic and "Event" in types),
            "first-party music event schema required")
    require(not discover.reject_listing(raw.get("name")),
            "festival, cancelled or non-concert title is not a concert")
    canonical = raw.get("url")
    require(canonical is None or canonical == event["officialUrl"],
            "individual event canonical URL differs")
    require(discover.iso_day(raw.get("startDate")) == event["date"],
            "official event date differs")
    status = str(raw.get("eventStatus") or "").casefold()
    require(not any(s in status for s in (
        "cancel", "postpon", "resched", "report", "annul")),
        "official concert not confirmed")
    lineup = bridge.official_named_bill(raw.get("performer"))
    require(lineup is not None and bool(lineup[0]), "named official artists missing")
    names, _unnamed = lineup
    require(normal(" + ".join(names)) == normal(event.get("title")),
            "signed title differs from individual MusicEvent bill")
    require([normal(x) for x in names] ==
            [normal(artists[aid]["name"]) for aid in event.get("artistIds", [])],
            "artist IDs or names differ from individual official MusicEvent")
    location = raw.get("location")
    require(isinstance(location, dict) and
            normal(location.get("name")) == normal(venue["name"]),
            "first-party event names another venue")
    addr = location.get("address")
    require(isinstance(addr, dict), "physical venue address absent")
    country = addr.get("addressCountry")
    if isinstance(country, dict):
        country = country.get("name") or country.get("@id")
    if not (accept_generic and _exact_location_description(location, venue)):
        require(normal(country) in {"fr", "france", "republique francaise"},
                "event takes place outside France")
        require(normal(addr.get("addressLocality")) == normal(venue["city"]) and
                str(addr.get("postalCode")) == venue.get("postalCode"),
                "first-party postal address differs from published venue")
        # Missing street number is acceptable. It must still identify the site.
        require(normal(addr.get("streetAddress")) == normal(venue.get("address")),
                "official street conflicts with published venue")
    genres, scope = event_genres(raw, event["officialUrl"],
                                 fetch=fetch if accept_generic else None,
                                 cache=cache, html=html)
    require(bool(triage.genre_evidence({
        "classification": genres,
        "genreEvidenceScope": scope,
        "officialDetailFound": True,
    })), "no explicit metal/rock/punk event-or-artist genre")
    # Different support artists may have different styles. Do not infer that
    # all performers belong to a single genre or require individual tags.
    require(all(normal(g) in {normal(x) for x in genres}
                for g in event.get("genres", [])),
            "signed genre differs from first-party MusicEvent")
    return names, genres


def validate(approval, venues, artists, today, *, fetch=None):
    """Publisher-bound source admission: fully re-fetch and compare the signed bill."""
    if fetch is None:
        fetch = safe_fetch
    require(isinstance(approval, dict)
            and approval.get("reviewDecision") == "approved"
            and approval.get("reviewedBy") == "independent-official-verifier",
            "independent event review missing")
    event = approval.get("event")
    require(isinstance(event, dict)
            and event.get("sourceType") == "salle"
            and event.get("status") == "confirmed"
            and event.get("time") is None,
            "only confirmed venue concerts without invented start time")
    require(event.get("date") >= today.isoformat(), "event expired")
    try:
        checked = dt.date.fromisoformat(approval.get("reviewedAt"))
        require(dt.timedelta(days=0) <= today - checked <= dt.timedelta(days=7),
                "first-party verification stale or future")
    except (ValueError, TypeError):
        raise ValueError("Unlisted official source: invalid review date")
    require(isinstance(event.get("artistIds"), list)
            and event["artistIds"]
            and len(set(event["artistIds"])) == len(event["artistIds"]),
            "named artist bill malformed")
    new = approval.get("newArtists") or []
    require(isinstance(new, list) and
            all(isinstance(row, dict) and row.get("id") not in artists
                and isinstance(row.get("name"), str) for row in new),
            "unverified new artist")
    resolved = dict(artists)
    resolved.update({a["id"]: a for a in new})
    require(len(resolved) == len(artists) + len(new)
            and all(aid in resolved for aid in event["artistIds"]),
            "unknown or duplicated new artist identity")
    venue = venues.get(event.get("venueId"))
    require(isinstance(venue, dict)
            and venue.get("id") == event["venueId"],
            "event physical venue is not published")
    proofset = approval.get("officialEvidence")
    require(isinstance(proofset, list) and len(proofset) == 1
            and isinstance(proofset[0], dict),
            "exact source-identity proof required")
    proof = proofset[0]
    is_single_osm = proof.get("proofType") == OSM_SINGLE_PROFILE
    is_address = proof.get("proofType") == OSM_ADDRESS_PROFILE
    is_official = proof.get("proofType") == OFFICIAL_SOURCE_PROFILE
    is_openagenda = proof.get("proofType") == OPENAGENDA_PROFILE
    has_openagenda_export = (is_openagenda and
                             "officialOpenAgendaUid" in proof)
    required_fields = (OPENAGENDA_EXPORT_PROOF_FIELDS
                       if has_openagenda_export else
                       OPENAGENDA_PROOF_FIELDS if is_openagenda else
                       OFFICIAL_SOURCE_PROOF_FIELDS if is_official else
                       OSM_ADDRESS_PROOF_FIELDS if is_address else
                       OSM_SINGLE_PROOF_FIELDS if is_single_osm else
                       PROOF_FIELDS)
    require(set(proof) == required_fields,
            "wrong first-party source evidence fields")
    require(proof["url"] == event.get("officialUrl")
            and proof["proofType"] in {
                PROFILE, OSM_SINGLE_PROFILE, OSM_ADDRESS_PROFILE,
                OFFICIAL_SOURCE_PROFILE, OPENAGENDA_PROFILE}
            and proof["checkedAt"] == approval.get("reviewedAt")
            and proof["checkedFields"] == (
                OPENAGENDA_CHECKED if is_openagenda else
                ADDRESS_CHECKED if is_address else CHECKED)
            and (proof["officialOpenAgendaEventUrl"] == event.get("officialUrl")
                 and openagenda.is_openagenda_event_url(
                     proof["officialOpenAgendaEventUrl"])
                 if is_openagenda else
                 proof["officialVenueSourceUrl"] ==
                 official_source.official_origin(venue, event["officialUrl"])
                 and bool(proof["officialVenueSourceUrl"])
                 if is_official else
                 proof["publishedVenueGeoSource"] == venue.get("geoSource")
                 if is_address else
                 proof["namedOsmUrl"] == venue.get("geoSource")),
            "first-party source evidence differs")
    origin = url_host(event["officialUrl"])
    witness = proof.get("corroboratingEventUrl")
    if not (is_single_osm or is_address or is_official or is_openagenda):
        witness_host = url_host(witness)
        require(cross.domain(witness_host) != cross.domain(origin),
                "cross-domain witness is controlled by the same source apex")
    cache = {}
    # Verify named public OSM feature AND its website attribution on each
    # prospective publication. This also detects later ownership changes.
    if is_openagenda:
        # OpenAgenda itself is the one public source of this exact event.
        # Never require an unrelated site to repeat the announcement.
        pass
    elif is_official:
        # Source identity is bound to a published venue's own official agenda;
        # OSM is not an event witness and must not be re-fetched for each show.
        pass
    elif is_address:
        feature, homepage = address_identity(
            venue, event["officialUrl"], fetch, cache)
        require(feature == proof["namedOsmUrl"]
                and homepage == proof["sourceWebsite"],
                "fresh named-site OSM identity or official website changed")
    else:
        osm_identity(venue, event["officialUrl"], fetch, cache)
    if has_openagenda_export:
        body = fetch(openagenda.official_export_url(
            proof["officialOpenAgendaUid"],
            proof["officialOpenAgendaEventUid"]), cache)
        names, genres = openagenda.verified_export(
            body, event["officialUrl"], event["date"], venue,
            agenda_uid=proof["officialOpenAgendaUid"],
            event_uid=proof["officialOpenAgendaEventUid"])
    else:
        html = fetch(event["officialUrl"], cache)
        require(isinstance(html, str) and
                100 <= len(html) <= probe.MAX_BYTES,
                "individual first-party HTML missing")
    if is_openagenda:
        if not has_openagenda_export:
            names, genres = openagenda.verified_bill(
                html, event["officialUrl"], event["date"], venue)
        require([normal(x) for x in names] ==
                [normal(resolved[aid]["name"])
                 for aid in event.get("artistIds", [])]
                and normal(" + ".join(names)) == normal(event.get("title"))
                and genres == proof["officialGenreLabels"]
                and names == proof["officialArtistNames"]
                and all(normal(label) in {normal(g) for g in genres}
                        for label in event.get("genres", [])),
                "fresh OpenAgenda concert differs from signed official page")
        return True
    events = individual_event_nodes(
        html, accept_generic=(is_single_osm or is_address or is_official))
    # Reconstruct the same first-party visible evidence during the LIVE
    # Publisher recheck, AFTER OSM attribution was verified afresh.
    sparse_detail = None
    if is_single_osm or is_address or is_official:
        sparse_detail = sparse_visible_event_detail(
            html, events, event["officialUrl"], event["date"], venue)
    if (is_single_osm or is_address or is_official) and sparse_detail is None:
        import event_site_pair_recheck as paired
        attested = []
        for raw in events:
            if raw.get("performer") in (None, "", []):
                names = paired._visible_artist_genres_from_this_event(
                    html, raw.get("name"))
                if names is None:
                    names = visible_named_bill(html, raw.get("name"))
                if names is not None:
                    raw = {**raw, "performer": names}
            attested.append(raw)
        events = attested
    valid = []
    if (not events or sparse_detail is not None) and (is_single_osm or is_address or is_official):
        from automation.concerts import open_world_visible_cards
        detail = sparse_detail
        if not events:
            detail = open_world_visible_cards.verified_detail(
                html, venue['name'], venue['city'], event['date'],
                address=venue.get('address'), postal=venue.get('postalCode'))
        if detail is not None:
            names, genres = detail
            require(normal(' + '.join(names)) == normal(event.get('title'))
                    and [normal(n) for n in names] ==
                    [normal(resolved[aid]['name']) for aid in event['artistIds']]
                    and all(normal(g) in {normal(x) for x in genres}
                            for g in event.get('genres', [])),
                    'fresh visible concert differs from signed event')
            valid.append(detail)
    for raw in ([] if sparse_detail is not None else events):
        try:
            valid.append(_event(raw, event, venue, resolved,
                                accept_generic=(is_single_osm or is_address or is_official),
                                fetch=fetch, cache=cache, html=html))
        except (ValueError, KeyError, TypeError):
            continue
    require(len(valid) == 1, "no unique exact first-party MusicEvent")
    names, genres = valid[0]
    require(names == proof["officialArtistNames"]
            and genres == proof["officialGenreLabels"],
            "independent live event differs from signed first-party proof")
    if not (is_single_osm or is_address or is_official):
        # The legacy two-domain proof still requires its fresh witness.
        corroboration = fetch(witness, cache)
        matched = cross_live.event_page_witness(
            corroboration, url=witness, date=event["date"],
            lead_artist=names[0], city=venue["city"], venue=venue["name"])
        require(normal(names[0]) in {normal(x) for x in matched["names"]},
                "independent event witness does not include named lead artist")
    # For OSM_SINGLE_PROFILE, trust comes from the freshly re-fetched,
    # independently named OSM feature AND this exact attributed venue-origin
    # MusicEvent. Neither a registry claim nor an OSM hostname by itself is
    # an event-level or artist-genre proof.
    return True
