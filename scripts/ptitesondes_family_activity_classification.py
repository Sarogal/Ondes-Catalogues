"""Read-only editorial discovery for P'tites Ondes' radio/children universe.

Only storytelling and performing-arts proposals complement the existing
musical pipeline. Ordinary leisure, sport, science, nature, meals and crafts
are NOT relevant merely because the audience includes children.

No city, venue, organizer or agenda whitelist. A proposed category NEVER
provides evidence of an actual event or permission to publish.
"""
import re

from proof import norm
from ptitesondes_primary_editorial import primary_out_of_scope, audience_text
from ptitesondes_family_national_scope import FAMILY_TYPES

# Deliberately narrow: the product remains an app for children's radio.
# Separate musical formats keep their existing independent verifier.
ACTIVITY_PATTERNS = {
    "lecture-jeunesse": (
        r"\b(?<!cine )lecture(?:s)?(?: d histoires| jeunesse| pour enfants| a voix haute)\b",
        r"\bheure du conte\b",
        r"\bconte(?:s)? (?:pour enfants|jeune public|pour les petits)\b",
        r"\bhistoires racontees?\b",
        r"\bseance de contes\b",
        # Baby/toddler story-time is a live storytelling event, not a
        # generic library opening or an unrestricted reading room.
        r"\bbebes? lecteurs?\b",
        r"\blectures? (?:de contes|d histoires|pour les tout petits)\b",
    ),
    "spectacle-jeunesse": (
        r"\bspectacle (?:de )?(?:marionnettes|magie|cirque|clown)\b",
        r"\bspectacle (?:jeune public|pour enfants|pour les petits)\b",
        r"\btheatre (?:jeune public|pour enfants)\b",
        r"\bpiece de theatre pour enfants\b",
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
    r"spectacle musical|cine concert|atelier sonore|comptines)\b"
)

if not set(ACTIVITY_PATTERNS).issubset(FAMILY_TYPES):
    raise RuntimeError("radio_editorial_categories_missing_in_national_taxonomy")


def _category_matches(text):
    return sorted(
        key for key, patterns in ACTIVITY_PATTERNS.items()
        if any(re.search(pattern, text) for pattern in patterns)
    )


def propose_family_activity(title, description):
    """Suggest one relevant event type; never verify or publish anything.

    Unknown venue or city is not an editorial rejection. Recognition of a
    spectacle/reading is insufficient to prove schedule, age, access or source.
    """
    outcome = {
        "category_proposal": None,
        "category_label_proposal": None,
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
    if primary_out_of_scope(title, description):
        outcome["decision"] = "primary_activity_outside_editorial_scope"
        return outcome
    name, body = norm(title), norm(title + " " + description)
    if ADULT_ONLY.search(body):
        outcome["decision"] = "adult_only_or_contradictory_audience"
        return outcome
    if not AUDIENCE.search(audience_text(title, description)):
        outcome["decision"] = "no_explicit_family_audience_cue"
        return outcome
    if MUSICAL.search(name):
        outcome["decision"] = "existing_musical_path_only"
        return outcome
    found = _category_matches(name) or _category_matches(body)
    if not found:
        # An exact child-audience claim elsewhere in the same official event
        # can establish the youth scope. The title need not literally say
        # "conte pour enfants" or "spectacle pour enfants": e.g. "Contes
        # avec Aïdée" with a description "pour enfants de tous âges".
        # Use the main TITLE here, not an incidental body reference.
        if re.search(r"\bcontes?\b", name):
            found = ["lecture-jeunesse"]
        elif re.search(r"\bspectacles?\b", name):
            found = ["spectacle-jeunesse"]
    if len(found) != 1:
        outcome["decision"] = (
            "ambiguous_activity_category" if found else
            "out_of_radio_editorial_scope"
        )
        return outcome
    category = found[0]
    outcome["category_proposal"] = category
    outcome["category_label_proposal"] = FAMILY_TYPES[category][0]
    outcome["decision"] = "read_only_proposal_requires_full_proof"
    return outcome
