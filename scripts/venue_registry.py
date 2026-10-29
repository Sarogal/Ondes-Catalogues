"""Lieux revus indépendamment : source de coordonnées identifiée, sans géocodage deviné.

Ajouts au registre uniquement après confrontation de l'adresse officielle et d'une
source cartographique indépendante. La détection ne publie rien à elle seule.
"""
from proof import norm, meters

VENUES = [
    {
        "city": "Montpellier", "aliases": ["Maison pour tous Marcel Pagnol"],
        "lat": 43.60149, "lng": 3.85025,
        "official": "https://mpt.montpellier.fr/maisons/marcel-pagnol",
        "geo_source": "https://mapcarta.com/fr/W75841141",
    },
    {
        "city": "Bordeaux", "aliases": ["Grand-Théâtre – Foyer rouge"],
        "lat": 44.84258, "lng": -0.57364,
        "official": "https://www.opera-bordeaux.com/famille-sons-dessus-dessous-86131",
        "geo_source": "catalogue public P'tites Ondes (Boîte à gazouillis, Grand-Théâtre)",
    },
    {
        "city": "Bordeaux", "aliases": ["Auditorium de Bordeaux",
                                  "Auditorium de Bordeaux – salle Sauguet"],
        "lat": 44.8421883, "lng": -0.5801358,
        "official": "https://www.opera-bordeaux.com/famille-voyage-en-inde-88091",
        "geo_source": "https://www.sortiraujourdhui.fr/index.php?com=location&lID=2080",
    },
    {
        "city": "Paris", "aliases": ["Théâtre du Châtelet"],
        "lat": 48.85777, "lng": 2.34613,
        "official": "https://www.paris.fr/evenements/univers-112690",
        "geo_source": "https://www.geonames.org/10279008/theatre-du-chatelet.html",
    },
    {
        "city": "Paris", "aliases": ["Philharmonie de Paris – Salle de conférence"],
        "lat": 48.89191, "lng": 2.39419,
        "official": "https://philharmoniedeparis.fr/fr/activite/atelier-concert-pour-les-tout-petits/29704-loiseau-multicolore",
        "geo_source": "catalogue public P'tites Ondes (plusieurs fiches même salle)",
    },
]

def verified_location(event):
    for place in VENUES:
        if norm(place["city"]) != norm(event.get("city", "")):
            continue
        if norm(event.get("venue", "")) not in {norm(a) for a in place["aliases"]}:
            continue
        try:
            d = meters((float(event["lat"]), float(event["lng"])),
                       (place["lat"], place["lng"]))
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
        if d <= 65:
            return True, "registre de lieu documenté (écart %.0f m)" % d
    return False, "lieu absent du registre ou GPS différent de plus de 65 m"
