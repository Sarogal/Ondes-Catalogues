"""Secondary, independently reviewed organizer programs for JS-only OpenAgenda pages.

Never treats an OpenAgenda index alone as evidence of an occurrence. This
allowlist links *exact* OpenAgenda canonical URLs to an official venue page.
Each run fetches that page afresh and checks title, venue, year, listed days,
times and child suitability. Unknown sources fail closed.

Adding a new entry requires manual source inspection and regression tests.
"""
from datetime import date
import re

from proof import norm

PROGRAMS = {
    "https://openagenda.com/contributions-evenements-culturels-nantes-et-metropole-nantaise/events/jeune-public-concert-quand-le-chat-nest-pas-laca-part-en-live": {
        "organizer_url": "https://www.theatre-jeanne.com/spectacle/quand-le-chat-nest-pas-laca-part-en-live/2027-01-13/",
        "official_title": "QUAND LE CHAT N’EST PAS LÀ…ça part en LIVE !",
        "city": "Nantes", "venue": "Théâtre de Jeanne",
        "category": "concert", "rule": "jan-2027-chat",
        "age": "conseille de 3 a 8 ans",
    },
    "https://openagenda.com/contributions-evenements-culturels-nantes-et-metropole-nantaise/events/jeune-public-concertconte-musical-un-animal-des-amis-mots": {
        "organizer_url": "https://www.theatre-jeanne.com/spectacle/un-animal-des-amis-mots/2027-02-10/",
        "official_title": "UN ANIMAL, DES AMIS MOTS",
        "city": "Nantes", "venue": "Théâtre de Jeanne",
        "category": "conte-musical", "rule": "feb-2027-animal",
        "age": "conseille de 3 a 10 ans",
    },
    # Exact OpenAgenda canonical URLs independently corroborated by the
    # first-party public family programme of Opéra National de Bordeaux.
    "https://openagenda.com/ville-de-bordeaux/events/momo-lenfant-peche-3216479": {
        "organizer_url": "https://www.opera-bordeaux.com/famille-orchestre-momo-lenfant-peche-86301",
        "official_title": "Momo, l'enfant pêche",
        "city": "Bordeaux", "venue": "Auditorium de Bordeaux",
        "official_venue_label": "Auditorium",
        "category": "conte-musical", "category_label": "Conte musical",
        "rule": "bordeaux-momo-2027", "age": "a partir de 6 ans",
        "uid": "54065371", "reviewed_family_category": True,
    },
    "https://openagenda.com/ville-de-bordeaux/events/les-droles-de-petites-betes-8323158": {
        "organizer_url": "https://www.opera-bordeaux.com/famille-orchestre-les-droles-de-petites-betes-86441",
        "official_title": "Les Drôles de petites bêtes",
        "city": "Bordeaux", "venue": "Auditorium de Bordeaux",
        "official_venue_label": "Auditorium",
        "category": "cine-concert", "category_label": "Ciné-concert",
        "rule": "bordeaux-droles-2027", "age": "a partir de 4 ans",
        "uid": "66367832", "reviewed_family_category": True,
    },
}


def reviewed_family_category(uid, canonical_url, title, city, venue):
    """Classify only an exact source-backed work, never approve its session.

    The independent organizer schedule remains mandatory in verify_event.
    """
    info = PROGRAMS.get(canonical_url)
    if (not info or not info.get("reviewed_family_category") or
            str(uid) != info.get("uid") or
            norm(title) != norm(info["official_title"]) or
            norm(city) != norm(info["city"]) or
            norm(venue) != norm(info["venue"])):
        return None
    return info["category"], info["category_label"]


def organizer_url(event):
    """Only exact, reviewed source URLs with matching venue/title are eligible."""
    info = PROGRAMS.get(event.get("source_url"))
    if not info:
        return None
    if (norm(event.get("city")) != norm(info["city"]) or
            norm(event.get("venue")) != norm(info["venue"]) or
            event.get("category") != info["category"]):
        return None
    wanted = norm(info["official_title"])
    if wanted not in norm(event.get("title")):
        return None
    return info["organizer_url"]



def canonical_event_title(event):
    """Canonicalize only preapproved organizer matches, not arbitrary fuzzy titles.

    OpenAgenda often prefixes an original show title with "Jeune public - Concert".
    The reviewed organizer title is used solely for cross-source deduplication.
    """
    approved = PROGRAMS.get(event.get("source_url"))
    if approved and organizer_url(event) is not None:
        return norm(approved["official_title"])
    return norm(event.get("title"))

def reviewed_schedule(event, heading, text):
    """Verify exact organizer schedule; do not extrapolate undisclosed dates."""
    info = PROGRAMS.get(event.get("source_url"))
    if not info or organizer_url(event) is None:
        return False, "source secondaire non homologuée"
    head = norm(heading)
    body = norm(text)
    expected = norm(info["official_title"])
    if expected not in head:
        return False, "titre du spectacle absent de la page organisateur"
    if norm(info.get("official_venue_label", info["venue"])) not in body or norm(info["city"]) not in body:
        return False, "ville ou lieu non confirmé par l'organisateur"
    if info["age"] not in body or "enfant" not in body:
        return False, "destination jeune public non prouvée"
    if re.search(r"\b(?:annule|annulee|annules|reporte|reportee|reportes)\b", body):
        return False, "annulation ou report mentionné sur la page organisateur"
    if event.get("date_start") != event.get("date_end"):
        return False, "regroupement de jours interdit par la preuve secondaire"
    try:
        day = date.fromisoformat(event["date_start"])
    except (ValueError, TypeError, KeyError):
        return False, "date de séance invalide"
    time = event.get("time")
    if not isinstance(time, str) or not re.fullmatch(r"\d{2}:\d{2}", time):
        return False, "heure de séance ambiguë"
    if info["rule"] == "bordeaux-momo-2027":
        if (day, time) not in {
                (date(2027, 1, 21), "19:00"),
                (date(2027, 1, 22), "19:00")}:
            return False, "séance familiale bordelaise absente du programme"
        if "famille conte musical a partir de 6 ans" not in body:
            return False, "destination jeune public non confirmée"
        if f" {day.day} jan 2027 a 19h00 " not in " " + body + " ":
            return False, "séance et heure officielles non confirmées"
    elif info["rule"] == "bordeaux-droles-2027":
        # The 28/01 and 29/01 sessions at 14:30 are reserved for schools.
        if (day, time) != (date(2027, 1, 29), "19:00"):
            return False, "séance uniquement scolaire ou réservée"
        if ("famille concert illustre a partir de 4 ans" not in body or
                "cine concert" not in body or
                " 29 jan 2027 a 19h00 " not in " " + body + " "):
            return False, "séance familiale bordelaise non confirmée"
    elif info["rule"] == "jan-2027-chat":
        if day not in (date(2027, 1, 13), date(2027, 1, 14),
                       date(2027, 1, 20)):
            return False, "séance de janvier absente du programme homologué"
        if not re.search(r"\bles 13 et 20 janvier 2027\b", body):
            return False, "année ou dates de janvier non confirmées"
        if day.day in (13, 20):
            if time != "14:30" or "les mercredis a 14h30" not in body:
                return False, "horaire des mercredis non confirmé"
            if not re.search(r"\bmercredi " + str(day.day) +
                             r" janv a 14h30\b", body):
                return False, "séance du mercredi non listée individuellement"
        else:
            if time != "10:30" or not re.search(
                    r"\bjeudi 14 janv a 10h30\b", body):
                return False, "séance supplémentaire du jeudi non prouvée"
    elif info["rule"] == "feb-2027-animal":
        if day not in (date(2027, 2, 10), date(2027, 2, 14),
                       date(2027, 2, 17)):
            return False, "séance de février absente du programme homologué"
        if not re.search(r"\bdu 10 au 17 fevrier 2027\b", body):
            return False, "année ou plage réelle de février non confirmée"
        if day.weekday() == 2:
            if time != "14:30" or "les mercredis a 14h30" not in body:
                return False, "horaire du mercredi absent"
        elif day.weekday() == 6:
            if time != "15:00" or "les dimanches a 15h" not in body:
                return False, "horaire du dimanche absent"
        else:
            return False, "jour de semaine non programmé"
    else:
        return False, "règle de programme inconnue"
    return True, "programme organisateur indépendant : titre, âge, lieu, séance exacte et horaire"
