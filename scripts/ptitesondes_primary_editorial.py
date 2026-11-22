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
COMMERCIAL_STUDIO_SERVICE = re.compile(
    r"^(?:(?:location|louez|reservez|reservation) (?:un |une |d un |de |du |d )?"
    r"(?:studio|salle d enregistrement)|"
    r"(?:formule|abonnement) (?:studio|enregistrement))\b"
)


def primary_out_of_scope(title, description=""):
    """Return a stable generic reason, or None.

    Explicit child access in the description is NOT a substitute for the
    primary activity being cultural. Conversely, a musical family workshop
    remains eligible even when adults can also attend. Description is
    intentionally not used to veto based on incidental words like "devoirs"
    or "forum" appearing in an otherwise genuine performance.
    """
    if not isinstance(title, str) or not title.strip():
        return None
    main = norm(title)
    if SCHOOL_SUPPORT.search(main):
        return "school_support_primary"
    if NON_PERFORMANCE_GATHERING.search(main):
        return "non_performance_gathering_primary"
    if COMMERCIAL_STUDIO_SERVICE.search(main):
        return "commercial_studio_service_primary"
    return None
