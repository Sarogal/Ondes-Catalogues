"""Lieux revus indépendamment : source de coordonnées identifiée, sans géocodage deviné.

Ajouts au registre uniquement après confrontation de l'adresse officielle et d'une
source cartographique indépendante. La détection ne publie rien à elle seule.
"""
from proof import norm, meters

VENUES = [
    {
        "city": "Nantes", "aliases": ["Théâtre de Jeanne"],
        "lat": 47.20457, "lng": -1.57551,
        "official": "https://www.theatre-jeanne.com/infos-pratiques/",
        "geo_source": "https://mapcarta.com/fr/N576891555",
    },
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
        "geo_source": "https://mapcarta.com/fr/W79734107",
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
        "geo_source": "https://mapcarta.com/fr/W21502894",
    },
    {
        "city": "Montpellier", "aliases": ["Maison pour tous Rosa Parks"],
        "lat": 43.63367, "lng": 3.83351,
        "official": "https://mpt.montpellier.fr/maisons/rosa-parks",
        "geo_source": "https://mapcarta.com/fr/W411408575",
    },
    {
        "city": "Montpellier", "aliases": ["Maison pour tous George Sand"],
        "lat": 43.61888, "lng": 3.89398,
        "official": "https://mpt.eolas-58.montpellier.fr/maisons/george-sand",
        "geo_source": "https://mapcarta.com/W60218330",
    },
    {
        "city": "Montpellier", "aliases": ["Maison pour tous Michel Colucci"],
        "lat": 43.5937, "lng": 3.84013,
        "official": "https://mpt.montpellier.fr/maisons/michel-colucci",
        "geo_source": "https://mapcarta.com/W76490345",
    },
    {
        "city": "Le Haillan", "aliases": ["L'Entrepôt"],
        "lat": 44.8743, "lng": -0.677071,
        "official": "https://www.ville-lehaillan.fr/ma-ville-bouge/culture-et-loisirs/lentrepot-coeur-culturel-et-artistique/",
        "geo_source": "https://33.kidiklik.fr/spectacles/236501-lentrepot-salle-de-spectacle-au-haillan.html",
    },
    {
        "city": "Versailles", "aliases": ["Hôtel des Menus-Plaisirs"],
        "lat": 48.800397, "lng": 2.133727,
        "official": "https://www.versailles-tourisme.com/l-hotel-des-menus-plaisirs.html",
        "geo_source": "https://mapcarta.com/W74630485",
    },
    {
        "city": "Goussainville",
        "aliases": ["Médiathèque municipale François Mauriac",
                    "Médiathèque intercommunale François Mauriac"],
        "lat": 49.0355, "lng": 2.461,
        "official": "https://www.ville-goussainville.fr/17070-la-mediatheque-francois-mauriac.htm",
        "geo_source": "https://mapcarta.com/fr/W27470092",
    },
    {
        "city": "Cabriès", "aliases": ["Auditorium Pierre Malbosc"],
        "lat": 43.44065, "lng": 5.38173,
        "official": "https://www.cabries.fr/lieux/auditorium-pierre-malbosc/",
        "geo_source": "https://mapcarta.com/fr/W67540122",
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
