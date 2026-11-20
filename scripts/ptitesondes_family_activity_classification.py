"""Read-only national classifier for nonmusical family outings.

This module only suggests an editorial category. It never authenticates an
organizer, age, price, venue, session, licence or publication permission.
No unknown venue, city, institution, agenda or organizer is blacklisted.
"""
import re

from proof import norm
from ptitesondes_family_national_scope import FAMILY_TYPES

# All patterns describe the *activity*, not an approved venue or a source.
# When more than one family activity matches, defer rather than guessing.
ACTIVITY_PATTERNS = {
    "lecture-jeunesse": (
        r"\b(?<!cine )lecture(?:s)?(?: d histoires| jeunesse| pour enfants| a voix haute)\b",
        r"\bheure du conte\b", r"\bcontes? pour enfants\b",
    ),
    "atelier-numerique": (
        r"\batelier(?: de)? (?:codage|programmation|numerique|robotique)\b",
        r"\binitiation (?:au code|a la programmation|au numerique)\b",
    ),
    "lecture-cinema": (
        r"\bcine lecture\b", r"\blecture et cinema\b",
        r"\blecture suivie d une projection\b",
    ),
    "jeux-famille": (
        r"\bjeux? de societe\b", r"\bapres midi jeux\b",
        r"\bjeux en famille\b", r"\bludotheque itin[ée]rante\b",
    ),
    "atelier-creatif": (
        r"\batelier(?: de)? (?:peinture|dessin|poterie|origami|bricolage|modelage|creatif)\b",
        r"\bfabrication de marionnettes\b",
    ),
    "atelier-sensoriel": (
        r"\batelier sensoriel\b", r"\bparcours sensoriel\b",
        r"\beveil sensoriel\b",
    ),
    "atelier-scientifique": (
        r"\batelier(?: de)? (?:sciences|scientifique|astronomie|chimie)\b",
        r"\bexperiences scientifiques\b",
    ),
    "spectacle-jeunesse": (
        r"\bspectacle de (?:marionnettes|magie|cirque)\b",
        r"\btheatre (?:jeune public|pour enfants)\b",
        r"\bpiece de theatre pour enfants\b",
    ),
    "cinema-jeunesse": (
        r"\bseance (?:de )?cinema\b",
        r"\bprojection (?:de )?(?:film|dessin anime)\b",
        r"\bfilm d animation\b",
    ),
    "sortie-nature": (
        r"\bbalade nature\b", r"\brandonnee (?:familiale|nature)\b",
        r"\bdecouverte de la foret\b",
        r"\bobservation des oiseaux\b",
    ),
    "animaux-ferme": (
        r"\bferme pedagogique\b", r"\bvisite de ferme\b",
        r"\brencontre avec les animaux\b",
    ),
    "musee-patrimoine": (
        r"\bvisite(?: guidee)? (?:du musee|d un musee|du patrimoine|du chateau|d un chateau)\b",
        r"\batelier au musee\b", r"\bvisite patrimoine\b",
    ),
    "fete-familiale": (
        r"\bcarnaval\b", r"\bfete (?:des enfants|familiale|de quartier)\b",
        r"\banimation familiale\b",
    ),
    "activite-sportive": (
        r"\binitiation (?:au sport|a l escalade|au judo|au basket)\b",
        r"\batelier (?:sportif|de motricite)\b",
        r"\bparcours de motricite\b",
    ),
}

AUDIENCE = re.compile(
    r"\b(?:enfants?|jeune public|tout petits?|bebes?|familles?|"
    r"parents enfants|de \d{1,2} a \d{1,2} ans|des \d{1,2} ans)\b"
)
ADULT_ONLY = re.compile(
    r"\b(?:reserve aux adultes|adultes uniquement|"
    r"interdit aux enfants|sans enfants|interdit aux mineurs)\b"
)
MUSICAL = re.compile(
    r"\b(?:concert|conte musical|eveil musical|atelier musical|"
    r"spectacle musical|cine concert)\b"
)

if not set(FAMILY_TYPES).issubset(ACTIVITY_PATTERNS):
    raise RuntimeError("national_family_category_taxonomy_drift")


def _category_matches(text):
    return sorted(
        key for key, patterns in ACTIVITY_PATTERNS.items()
        if key in FAMILY_TYPES
        and any(re.search(pattern, text) for pattern in patterns)
    )


def propose_family_activity(title, description):
    """Suggest at most one nonmusical category without approving an event.

    Exact match on the activity in the title takes priority over supporting
    descriptive context. The presence of contradictory activity signals in
    the same tier never makes a random first-match winner acceptable.
    """
    outcome = {
        "category_proposal": None, "category_label_proposal": None,
        "decision": "no_safe_category_proposal",
        "requires_independent_event_proof": True,
        "audience_claim_not_verified": True,
        "official_source_not_verified": True,
        "location_not_verified": True,
        "licence_not_verified": True,
        "publication_ready": False,
        "public_writes": 0,
    }
    if (not isinstance(title, str) or not isinstance(description, str)
            or not title.strip() or len(title) > 300
            or len(description) > 5000):
        outcome["decision"] = "invalid_activity_text"
        return outcome
    name, body = norm(title), norm(title + " " + description)
    if ADULT_ONLY.search(body):
        outcome["decision"] = "adult_only_or_contradictory_audience"
        return outcome
    if not AUDIENCE.search(body):
        outcome["decision"] = "no_explicit_family_audience_cue"
        return outcome
    if MUSICAL.search(name):
        outcome["decision"] = "existing_musical_path_only"
        return outcome
    found = _category_matches(name) or _category_matches(body)
    if len(found) != 1:
        outcome["decision"] = (
            "ambiguous_activity_category" if found else
            "activity_type_not_established"
        )
        return outcome
    key = found[0]
    outcome["category_proposal"] = key
    outcome["category_label_proposal"] = FAMILY_TYPES[key][0]
    outcome["decision"] = "read_only_proposal_requires_full_proof"
    return outcome
