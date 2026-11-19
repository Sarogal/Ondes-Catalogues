"""Bounded first-party family / age evidence for exact HTML sessions.

This is a generic source-only diagnostic, not independent verification and
never a publisher input. An event description ABOUT children is not proof
that children may attend. Missing age limits remain None, never guessed.
"""
import re

from ptitesondes_family_national_source_preflight import norm_text
from ptitesondes_html_access_conditions import (
    _VisibleEventAccess, MAX_HTML,
)
from ptitesondes_html_first_party_session_proof import (
    corroborate_first_party_session, _audience_from_standalone_labels,
)
from ptitesondes_openagenda_v2_organizer_bridge import ADULT_ONLY

SCHEMA = "ptitesondes.html_family_age_source_triage.v1"
# All regexes apply to normalized VISIBLE event text, after the exact H1,
# before related-event sections. Never inspect invisible markup or metadata.
ADULT_EXCLUSION = re.compile(
    r"\b(?:reserve(?:e|s|es)? aux adultes|adultes uniquement|"
    r"adultes seulement|sans enfants|mineurs non admis|"
    r"enfants non admis|interdit aux mineurs|"
    r"interdit aux enfants|moins de 18 ans interdits|"
    r"a partir de 18 ans|18 ans et plus|parents uniquement|"
    r"pour les parents d enfants)\b"
)
MIXED = re.compile(
    r"\b(?:parents? (?:et|avec) enfants?|enfants? (?:et|avec) adultes?|"
    r"adultes? (?:et|avec) enfants?|"
    r"atelier parents? enfants?|duo parents? enfants?|"
    r"petits et grands)\b"
)
FAMILY = re.compile(
    r"\b(?:familles?|familial(?:e|es|s)?|"
    r"en famille|jeune public|tout public)\b"
)
EXPLICIT_CHILD = re.compile(
    r"\b(?:pour|destine(?:e|s|es)?|reserve(?:e|s|es)?|"
    r"ouvert(?:e|s|es)?|accessible|accueil|public)\s+"
    r"(?:(?:a|aux|au|les|des|de|du|pour)\s+)?"
    r"(?:enfants?|bebes?|tout petits?|adolescents?|ados?|"
    r"jeunes(?! adultes?\b))\b"
)
AGE_RANGE = re.compile(
    r"\b(?:de\s+)?(\d{1,3})\s+(?:a|au)\s+(\d{1,3})\s+ans\b"
)
AGE_MIN = re.compile(
    r"\b(?:a partir de|des|a compter de|minimum)\s+"
    r"(\d{1,3})\s+ans\b"
)
AGE_MAX = re.compile(
    r"\b(?:jusqu a|moins de|maximum)\s+(\d{1,3})\s+ans\b"
)
AGE_CONTEXT = re.compile(
    r"^(?:public(?: cible)?\b|ages?\b|tranche d age\b|"
    r"pour les\b|pour un\b|a partir de\b|des \d|"
    r"jusqu a\b|de \d{1,3} (?:a|au) \d{1,3} ans\b|"
    r"\d{1,3} (?:a|au) \d{1,3} ans\b)"
)


def _empty(reason):
    return {
        "schema": SCHEMA, "reason": reason,
        "audience_state": "unknown",
        "age_state": "not_stated",
        "age_min": None, "age_max": None,
        "explicit_first_party_family_audience": False,
        "age_limit_from_visible_first_party_text": False,
        "family_or_age_review_pending": True,
        "source_is_not_independent_evidence": True,
        "organizer_independently_attested": False,
        "venue_gps_independently_attested": False,
        "rights_reviewed": False, "approval_granted": False,
        "publication_ready": False, "public_writes": 0,
    }


def triage_html_family_age(lead, page, index_pin, child_path):
    """Fixed, redacted facts for an already corroborated exact session."""
    proof = corroborate_first_party_session(
        lead, page, index_pin, child_path)
    if proof.get("visible_exact_session") is not True:
        return _empty("exact_first_party_session_not_verified")
    html = page.get("html")
    if not isinstance(html, str) or not 50 <= len(html) <= MAX_HTML:
        return _empty("invalid_official_page")

    parser = _VisibleEventAccess()
    try:
        parser.feed(html)
        parser.close()
    except (TypeError, ValueError):
        return _empty("visible_family_terms_unreadable")
    if parser.truncated:
        return _empty("visible_family_terms_limit_exceeded")
    if not parser.h1_seen or not parser.parts:
        return _empty("visible_event_description_missing")

    chunks = parser.parts
    text = " ".join(chunks)
    label_positive, label_adult_only = _audience_from_standalone_labels(html)
    adult = bool(label_adult_only or ADULT_ONLY.search(text)
                 or ADULT_EXCLUSION.search(text))
    mixed = bool(MIXED.search(text))
    # A family word anywhere in free prose is not sufficient: require a
    # standalone audience label or an explicit admission/public statement.
    family = label_positive or any(
        FAMILY.fullmatch(p) or
        re.search(r"\b(?:pour (?:les?|toute la)|public(?: cible)?|"
                  r"ouvert (?:aux?|a tous)|activite|sortie|atelier)\s+"
                  r"(?:en\s+)?(?:famille|familles|familial(?:e|es|s)?|"
                  r"jeune public|tout public)\b", p)
        for p in chunks
    )
    child = any(EXPLICIT_CHILD.search(p) for p in chunks)
    age_pairs = set()
    age_mins = set()
    age_maxs = set()
    for p in chunks:
        # Age data from marketing prose about children is NOT an admission
        # statement. Only a short, clearly labeled audience/age phrase counts.
        if len(p) > 260 or not AGE_CONTEXT.search(p):
            continue
        for match in AGE_RANGE.finditer(p):
            age_pairs.add((int(match.group(1)), int(match.group(2))))
        for match in AGE_MIN.finditer(p):
            age_mins.add(int(match.group(1)))
        for match in AGE_MAX.finditer(p):
            age_maxs.add(int(match.group(1)))

    claims = set(age_pairs)
    claims.update((n, None) for n in age_mins)
    claims.update((None, n) for n in age_maxs)
    age_bad = any(
        (lo is not None and lo > 120) or
        (hi is not None and hi > 120) or
        (lo is not None and hi is not None and lo > hi)
        for lo, hi in claims
    )
    distinct_lows = {lo for lo, _ in claims if lo is not None}
    distinct_highs = {hi for _, hi in claims if hi is not None}
    contradictory_age = (age_bad or len(distinct_lows) > 1
                         or len(distinct_highs) > 1)
    low = next(iter(distinct_lows)) if len(distinct_lows) == 1 else None
    high = next(iter(distinct_highs)) if len(distinct_highs) == 1 else None
    # An explicit age statement that includes minors is audience evidence.
    child_age = (low is not None and low < 18 and
                 (high is None or high >= low)) or (
                 high is not None and high < 18)
    positive = bool(family or child or mixed or child_age)
    adult_age = low is not None and low >= 18
    if contradictory_age:
        audience = "contradictory" if positive else "unknown"
    elif adult or adult_age:
        audience = "contradictory" if positive else "adult_only"
    elif mixed:
        audience = "explicit_mixed"
    elif child or child_age:
        audience = "explicit_children"
    elif family:
        audience = "explicit_family"
    else:
        audience = "unknown"
    if contradictory_age:
        age_state = "conflicting"
        low = high = None
    elif low is not None and high is not None:
        age_state = "explicit_range"
    elif low is not None:
        age_state = "explicit_minimum"
    elif high is not None:
        age_state = "explicit_maximum"
    else:
        age_state = "not_stated"

    return dict(
        _empty("visible_first_party_family_age_terms_only"),
        audience_state=audience, age_state=age_state,
        age_min=low, age_max=high,
        explicit_first_party_family_audience=audience in (
            "explicit_mixed", "explicit_children", "explicit_family"),
        age_limit_from_visible_first_party_text=age_state not in (
            "not_stated", "conflicting"),
        family_or_age_review_pending=audience not in (
            "explicit_mixed", "explicit_children", "explicit_family"),
    )
