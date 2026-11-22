"""Lieux revus indépendamment : source de coordonnées identifiée, sans géocodage deviné.

Ajouts au registre uniquement après confrontation de l'adresse officielle et d'une
source cartographique indépendante. La détection ne publie rien à elle seule.
"""
from proof import norm, meters
from ptitesondes_public_place_venues import lookup_public_venue

VENUES = [
    {
        # Salle L'Impromptu : 8 cours de la Marne, 33800 Bordeaux.
        # Agenda officiel Bordeaux Métropole : identité du lieu et adresse.
        # https://www.bordeaux-metropole.fr/agenda/31198327_cine-concert-sur-des-films-de-charlie-chaplin-8305480
        # OpenStreetMap node 13175174077 (amenity=theatre), même adresse.
        # https://mapcarta.com/N13175174077
        # Ce registre ne vaut jamais preuve de date, d'horaire ou d'âge.
        "city": "Bordeaux", "aliases": ["L'Impromptu"],
        "lat": 44.83066, "lng": -0.57144,
        "official": "https://www.bordeaux-metropole.fr/agenda/31198327_cine-concert-sur-des-films-de-charlie-chaplin-8305480",
        "geo_source": "https://mapcarta.com/N13175174077",
    },
    {
        # Bibliothèque municipale Pierre Veilletet : 21 rue Domion, Bordeaux.
        # Annuaire institutionnel Gironde : adresse, nom et géolocalisation.
        # https://mednum.gironde.fr/site/showInfos/341
        # OSM way 604935301 : emprise exacte de la bibliothèque.
        # https://mapcarta.com/fr/W604935301
        # Aucune séance déduite du statut permanent du bâtiment.
        "city": "Bordeaux", "aliases": ["Bibliothèque Pierre Veilletet"],
        "lat": 44.85744, "lng": -0.62340,
        "official": "https://mednum.gironde.fr/site/showInfos/341",
        "geo_source": "https://mapcarta.com/fr/W604935301",
    },
    {
        # Réseau municipal : 26 rue Famelart, 59200 Tourcoing.
        # https://mediatheques.tourcoing.fr/les-mediatheques/mediatheque-andre-malraux
        # IGN BAN : adresse exacte n°26, score 0.972, 50.716502 / 3.160323.
        # https://data.geopf.fr/geocodage/search?q=26%20rue%20Famelart%2C%2059200%20Tourcoing&limit=1
        # Index OA UID 54303466 : 50.716504 / 3.159680 ; écart ~45 m.
        # Deux intitulés exacts répertoriés ; ne pas les généraliser.
        "city": "Tourcoing",
        "aliases": ["Médiathèque André Malraux",
                    "Tourcoing/Médiathèque André Malraux"],
        "lat": 50.716502, "lng": 3.160323,
        "official": "https://mediatheques.tourcoing.fr/les-mediatheques/mediatheque-andre-malraux",
        "geo_source": "https://data.geopf.fr/geocodage/search?q=26%20rue%20Famelart%2C%2059200%20Tourcoing&limit=1",
    },
    {
        # Accoord : 2A rue de Saint-Brévin, 44100 Nantes.
        # https://www.accoord.fr/lieux/centre-socioculturel-bourderies/
        # Nantes Métropole Open Data : coordonnées du CSC à cette adresse :
        # 47.206759863397714 / -1.5961453442574385.
        # https://data.nantesmetropole.fr/explore/dataset/244400404_lieux-mediation-numerique-nantes-metropole/
        # BAN : 2A rue de Saint-Brévin à ~20 m ; OA UID 813941 à ~6 m.
        "city": "Nantes",
        "aliases": ["Centre socioculturel des Bourderies - ACCOORD"],
        "lat": 47.206759863397714, "lng": -1.5961453442574385,
        "official": "https://www.accoord.fr/lieux/centre-socioculturel-bourderies/",
        "geo_source": "https://data.nantesmetropole.fr/explore/dataset/244400404_lieux-mediation-numerique-nantes-metropole/",
    },
    {
        # Réseau municipal : médiathèque Aimé-Césaire, 285 bd Descat.
        # https://mediatheques.tourcoing.fr/les-mediatheques/mediatheque-aime-cesaire
        # IGN BAN : numéro exact 285 bd Constantin Descat,
        # 50.695480 / 3.151547 ; OA UID 16515082 ~9 m de ce point.
        # https://data.geopf.fr/geocodage/search?q=285%20boulevard%20Descat%2C%2059200%20Tourcoing&limit=1
        "city": "Tourcoing",
        "aliases": ["Médiathèque Aimé Césaire",
                    "Tourcoing/Médiathèque Aimé Césaire"],
        "lat": 50.695480, "lng": 3.151547,
        "official": "https://mediatheques.tourcoing.fr/les-mediatheques/mediatheque-aime-cesaire",
        "geo_source": "https://data.geopf.fr/geocodage/search?q=285%20boulevard%20Descat%2C%2059200%20Tourcoing&limit=1",
    },
    {
        # Adresse officielle 1 rue Eugene Thomas, 44300 Nantes :
        # https://metropole.nantes.fr/lieu/mediatheque-luce-courville
        # OSM way 84294254 (amenity=library, building=civic) :
        # https://mapcarta.com/fr/W84294254
        "city": "Nantes", "aliases": ["Médiathèque Luce Courville"],
        "lat": 47.26184, "lng": -1.57400,
        "official": "https://metropole.nantes.fr/lieu/mediatheque-luce-courville",
        "geo_source": "https://mapcarta.com/fr/W84294254",
    },
    {
        # Adresse du Centre urbain du Merlan, avenue Raimu (ville de Marseille) :
        # https://www.marseille-tourisme.com/offres/bibliotheque-du-merlan-marseille-14eme-fr-3381351/
        # OSM node 1920263029, amenity=library et non théâtre voisin :
        # https://mapcarta.com/fr/N1920263029
        "city": "Marseille", "aliases": ["Bibliothèque du Merlan"],
        "lat": 43.33056, "lng": 5.39888,
        "official": "https://www.marseille-tourisme.com/offres/bibliotheque-du-merlan-marseille-14eme-fr-3381351/",
        "geo_source": "https://mapcarta.com/fr/N1920263029",
    },
    {
        # Adresse municipale 6 boulevard Jean Salducci, 13016 Marseille :
        # https://www.marseille-tourisme.com/offres/bibliotheque-saint-andre-marseille-16eme-fr-3382594/
        # Geolocalisation indépendante à l'adresse exacte, sans confusion
        # avec la Maison municipale d'arrondissement Saint-André :
        # https://tofromfrance.com/en/lieu/bibliotheque-saint-andre
        "city": "Marseille", "aliases": ["Bibliothèque Saint-André"],
        "lat": 43.35741, "lng": 5.34259,
        "official": "https://www.marseille-tourisme.com/offres/bibliotheque-saint-andre-marseille-16eme-fr-3382594/",
        "geo_source": "https://tofromfrance.com/en/lieu/bibliotheque-saint-andre",
    },
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
    {
        # Identité officielle et adresse : réseau municipal de Tourcoing,
        # 156 avenue de la Fin de la Guerre, 59200 Tourcoing.
        # https://mediatheques.tourcoing.fr/les-mediatheques/mediatheque-andree-chedid
        # Point indépendant : OpenStreetMap way 78512642, amenity=library,
        # même numéro/avenue et nom du lieu.
        # https://mapcarta.com/fr/W78512642
        "city": "Tourcoing", "aliases": ["Médiathèque Andrée Chedid"],
        "lat": 50.72973, "lng": 3.14418,
        "official": "https://mediatheques.tourcoing.fr/les-mediatheques/mediatheque-andree-chedid",
        "geo_source": "https://mapcarta.com/fr/W78512642",
    },
    {
        # Adresse de l'organisateur : Centre Mandapa, 6 rue Wurtz,
        # 75013 Paris. La salle est également appelée Théâtre Mandapa.
        # https://www.centre-mandapa.fr/infos-pratiques
        # OSM node 4405707193 : Centre Mandapa, amenity=theatre.
        # https://mapcarta.com/N4405707193
        "city": "Paris", "aliases": ["Théâtre Mandapa"],
        "lat": 48.82762, "lng": 2.34518,
        "official": "https://www.centre-mandapa.fr/infos-pratiques",
        "geo_source": "https://mapcarta.com/N4405707193",
    },
    {
        # Paul B = Centre culturel Paul Bailliart, 6 allée de Québec,
        # 91300 Massy, identité et adresse confirmées par la salle.
        # https://paul-b.fr/infos-pratiques/
        # OSM way 70691345, arts_centre et nom alternatif exact « Paul B ».
        # https://mapcarta.com/fr/W70691345
        "city": "Massy", "aliases": ["Paul B"],
        "lat": 48.73090, "lng": 2.28287,
        "official": "https://paul-b.fr/infos-pratiques/",
        "geo_source": "https://mapcarta.com/fr/W70691345",
    },
    {
        # BnF Catalogue collectif de France: Mediatheque Raoul Georges Nicolo,
        # Boulevard Amedee Clara, 97190 Le Gosier (Guadeloupe).
        # https://ccfr.bnf.fr/portailccfr/ark:/16871/0027125
        # Official municipal programme independently names the same library:
        # https://www.villedugosier.fr/actualites/evenement/programme-des-animations-du-mois-de-la-mediatheque-raoul-georges-nicolo?date_event=2026-11-04
        # OSM way 125054083: exact named library building, amenity=library.
        # https://mapcarta.com/fr/W125054083
        # GPS proves this building only, NEVER a specific children's session.
        "city": "Le Gosier",
        "aliases": ["Médiathèque Raoul Georges Nicolo"],
        "lat": 16.20547, "lng": -61.48950,
        "official": "https://ccfr.bnf.fr/portailccfr/ark:/16871/0027125",
        "geo_source": "https://mapcarta.com/fr/W125054083",
    },
    {
        # CINOR public library network: 1 allee des Pierres de Lune,
        # 97400 Saint-Denis, Reunion; same building on OSM way 543425791.
        # https://lecturepublique.cinor.org/cms/www.main.cls?surl=reseau-horaires
        # https://mapcarta.com/fr/W543425791
        # OpenAgenda's CINOR programme names this venue but each individual
        # child session must still pass all independent publication checks.
        "city": "Saint-Denis",
        "aliases": [
            "Bibliothèque Intercommunale Alain Lorraine",
            "Bibliothèque Alain Lorraine",
        ],
        "lat": -20.89270, "lng": 55.45130,
        "official": "https://lecturepublique.cinor.org/cms/www.main.cls?surl=reseau-horaires",
        "geo_source": "https://mapcarta.com/fr/W543425791",
    },
    {
        # Municipal directory: 24 rue Emile Decorps, 69100 Villeurbanne.
        # https://www.villeurbanne.fr/annuaire/culture-loisirs/cinema-et-theatres/le-studio-24
        # Independent IGN/BAN housenumber, score 0.9765:
        # https://data.geopf.fr/geocodage/search?q=24%20rue%20Emile%20Decorps%2069100%20Villeurbanne&limit=2
        # Location ONLY; the 29 private leads are NOT individually verified.
        "city": "Villeurbanne", "aliases": ["Studio 24"],
        "lat": 45.757956, "lng": 4.899764,
        "official": "https://www.villeurbanne.fr/annuaire/culture-loisirs/cinema-et-theatres/le-studio-24",
        "geo_source": "https://data.geopf.fr/geocodage/search?q=24%20rue%20Emile%20Decorps%2069100%20Villeurbanne&limit=2",
    },
    {
        # Rouen changed the name of Bibliotheque Saint-Sever in 2026.
        # Exact municipal venue name and address: 65 avenue de Bretagne.
        # https://rouen.fr/fr/agenda/82031901_inauguration-aretha-franklin
        # Independent IGN/BAN housenumber, score 0.9747:
        # https://data.geopf.fr/geocodage/search?q=65%20avenue%20de%20Bretagne%2076100%20Rouen&limit=2
        # No automatic legacy alias "Saint-Sever": different historic venue
        # labels require dedicated review of each event's official location.
        "city": "Rouen", "aliases": ["Bibliothèque Aretha-Franklin"],
        "lat": 49.431261, "lng": 1.082660,
        "official": "https://rouen.fr/fr/agenda/82031901_inauguration-aretha-franklin",
        "geo_source": "https://data.geopf.fr/geocodage/search?q=65%20avenue%20de%20Bretagne%2076100%20Rouen&limit=2",
    },
    {
        # Rouen municipal venue and venue-specific event page jointly locate
        # the library at 42 rue Henri-II-de-Plantagenet, 76100 Rouen.
        # https://rouen.fr/fr/agenda/76031960_je-suis-venue-vous-lire-simone-de-beauvoir
        # Independent IGN/BAN housenumber, score 0.9742:
        # https://data.geopf.fr/geocodage/search?q=42%20rue%20Henri%20II%20Plantagenet%2076100%20Rouen&limit=2
        "city": "Rouen", "aliases": ["Bibliothèque Simone de Beauvoir"],
        "lat": 49.426213, "lng": 1.096972,
        "official": "https://rouen.fr/fr/agenda/76031960_je-suis-venue-vous-lire-simone-de-beauvoir",
        "geo_source": "https://data.geopf.fr/geocodage/search?q=42%20rue%20Henri%20II%20Plantagenet%2076100%20Rouen&limit=2",
    },
    {
        # The City of Roubaix lists the central library at 2 rue Pierre Motte.
        # https://www.ville-roubaix.fr/services-infos-pratiques/culture-et-patrimoine/livre-et-lecture/
        # Independent IGN/BAN housenumber, score 0.9720:
        # https://data.geopf.fr/geocodage/search?q=2%20rue%20Pierre%20Motte%2059100%20Roubaix&limit=2
        "city": "Roubaix",
        "aliases": ["Médiathèque de Roubaix - La Grand-Plage"],
        "lat": 50.690508, "lng": 3.175283,
        "official": "https://www.ville-roubaix.fr/services-infos-pratiques/culture-et-patrimoine/livre-et-lecture/",
        "geo_source": "https://data.geopf.fr/geocodage/search?q=2%20rue%20Pierre%20Motte%2059100%20Roubaix&limit=2",
    },
]

def verified_location(event, evidence=None, on_day=None):
    """Exact static or independently approved public-places GPS; never guess."""
    static_identity = False
    for place in VENUES:
        if norm(place["city"]) != norm(event.get("city", "")):
            continue
        if norm(event.get("venue", "")) not in {norm(a) for a in place["aliases"]}:
            continue
        static_identity = True
        try:
            d = meters((float(event["lat"]), float(event["lng"])),
                       (place["lat"], place["lng"]))
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
        if d <= 65:
            return True, "registre de lieu documenté (écart %.0f m)" % d
    # A conflicting legacy registry location must not be overridden by a
    # different public-place point without a dedicated source review.
    if not static_identity:
        approved = lookup_public_venue(event.get("city"), event.get("venue"))
        if approved is not None:
            try:
                d = meters((float(event["lat"]), float(event["lng"])),
                           (approved["lat"], approved["lng"]))
            except (ValueError, TypeError, KeyError, OverflowError):
                d = float("inf")
            if d <= 65:
                return True, "lieu permanent public indépendamment vérifié (écart %.0f m)" % d
    # Evidence is never imported from a self-asserted backlog flag.
    # Existing conflicting static registry identities always take precedence.
    if not static_identity and evidence is not None and on_day is not None:
        from ptitesondes_shared_venue_location_evidence import (
            location_from_proof,
        )
        if isinstance(event, dict):
            location = location_from_proof(
                evidence, event.get("city"), event.get("venue"), on_day,
                (event.get("lat"), event.get("lng")))
            if location is not None:
                return True, "preuve géographique indépendante privée"
    return False, "lieu absent du registre ou GPS différent de plus de 65 m"
