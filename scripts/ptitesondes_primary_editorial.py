"""Primary-activity veto for children's radio-adjacent outings.

A live event can contain the words "lecture" or "concert" in supporting
program details without being a reading or concert. Recognise the event's
MAIN advertised activity first. This is not a source, city, venue, or
organiser whitelist, and never limits the number of genuine sessions.
"""
import re

from proof import norm

SCHOOL_SUPPORT = re.compile(
    r"\b(?:accompagnement scolaire|aide aux devoirs|soutien scolaire|"
    r"remise a niveau scolaire|revision(?:s)? (?:scolaires?|pour (?:les )?examens)|"
    r"preparation (?:aux examens|au brevet|au bac)|cours de soutien)\b"
)
NON_PERFORMANCE_GATHERING = re.compile(
    r"^(?:(?:le |la |un |une )?(?:forum|colloque|conference|"
    r"table ronde|assemblee generale|reunion d information|"
    r"seminaire|debat citoyen))\b"
)
MARKET_GATHERING = re.compile(
    r"^(?:(?:le |la |un |une |grand |petit )?marche(?:s)? "
    r"(?:de noel|de saint nicolas|artisanal|artisans|des artisans|"
    r"de producteurs|des producteurs)|vide grenier|brocante)\b"
)
COMMERCIAL_STUDIO_SERVICE = re.compile(
    r"^(?:(?:location|louez|reservez|reservation) (?:un |une |d un |de |du |d )?"
    r"(?:studio|salle d enregistrement)|"
    r"(?:formule|abonnement) (?:studio|enregistrement))\b"
)


# A multi-activity programme is not an exact occurrence of each component.
# Recognise the umbrella wording and independent mixed formats together;
# an explicitly named show, storytelling or music programme is unaffected.
UMBRELLA_PROGRAMME = re.compile(
    r"^(?:(?:les |la |le |une? )?(?:journees?|semaines?|quinzaines?|"
    r"mois|temps forts?))\b"
)
NAMED_ART_FORMAT = re.compile(
    r"\b(?:musique|musical(?:e|es|s)?|concerts?|spectacles?|"
    r"marionnettes?|contes?|lectures?|comptines?|chansons?|"
    r"jeune public|enfants?|jeunesse)\b"
)


def mixed_umbrella_programme(title, description):
    main, body = norm(title), norm(description)
    if not UMBRELLA_PROGRAMME.search(main) or NAMED_ART_FORMAT.search(main):
        return False
    if not re.search(r"\b(?:au programme|programme des animations)\b", body):
        return False
    arts = re.search(r"\b(?:concerts?|spectacles?|lectures?|contes?)\b", body)
    other_formats = sum(bool(re.search(pattern, body)) for pattern in (
        r"\bexpositions?\b",
        r"\bateliers? d ecriture\b",
        r"\banimations? autour de la culture\b",
        r"\b(?:conferences?|tables rondes?)\b",
    ))
    return bool(arts and other_formats >= 2)


PARK_NAMED_ART_FORMAT = re.compile(
    r"\b(?:musique|musical(?:e|es|s)?|concerts?|spectacles?|"
    r"marionnettes?|contes?|lectures?|comptines?|chansons?)\b"
)


def park_visit_programme(title, description):
    """Do not turn a park's general visitor hours into concert sessions."""
    main, body = norm(title), norm(description)
    if PARK_NAMED_ART_FORMAT.search(main):
        return False
    park = re.search(r"\b(?:parc d attractions?|parc a theme|oenoparc|parc de loisirs)\b", body)
    visit = re.search(r"\b(?:au fil de la visite|parcours de visite|accueillir les visiteurs|horaires d ouverture)\b", body)
    scenery = re.search(r"\b(?:decors?|scenographie|attractions?|animations permanentes)\b", body)
    incidental = re.search(r"\b(?:concerts?|chansons?|chanteurs?|musiciens?|automates?|musique)\b", body)
    return bool(park and visit and scenery and incidental)


def primary_out_of_scope(title, description=""):
    """Return a stable generic reason, or None.

    Explicit child access in the description is NOT a substitute for the
    primary activity being cultural. Conversely, a musical family workshop
    remains eligible even when adults can also attend. Description is
    not used alone to veto based on incidental words like "devoirs"
    or "forum" appearing in an otherwise genuine performance.
    """
    if not isinstance(title, str) or not title.strip():
        return None
    main = norm(title)
    if SCHOOL_SUPPORT.search(main):
        return "school_support_primary"
    if NON_PERFORMANCE_GATHERING.search(main):
        return "non_performance_gathering_primary"
    if MARKET_GATHERING.search(main):
        return "market_gathering_primary"
    if COMMERCIAL_STUDIO_SERVICE.search(main):
        return "commercial_studio_service_primary"
    if park_visit_programme(title, description):
        return "park_visit_programme_primary"
    if mixed_umbrella_programme(title, description):
        return "mixed_umbrella_programme_primary"
    return None
