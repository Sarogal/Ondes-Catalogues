"""Publication cloud des concerts Grosses Ondes, uniquement après approbation documentée.

Source de vérité : docs/grossesondes/concerts.json (GitHub Pages)
Référence immuable : docs/grossesondes/concerts-reference.json
Approbations : dépôt PRIVE GrossesOndes/automation/concerts/approved.json
Aucun candidat brut de la veille n'est publiable.
"""
from __future__ import annotations

import argparse
import base64
import copy
import datetime as dt
import json
import os
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "docs/grossesondes/concerts.json"
REFERENCE = ROOT / "docs/grossesondes/concerts-reference.json"
APPROVAL_URL = (
    "https://api.github.com/repos/Sarogal/GrossesOndes/contents/"
    "automation/concerts/approved.json?ref=main"
)
SCHEMA = "grossesondes.concert.approvals.v1"
# Capacity for cumulative, still individually signed records. Limit the delta
# per workflow run separately to prevent accidental mass publication.
MAX_CUMULATIVE_EVENT_APPROVALS = 400
MAX_CUMULATIVE_VENUE_APPROVALS = 100
MAX_NEW_EVENTS_PER_SYNC = 16
MAX_NEW_VENUES_PER_SYNC = 6

# Pilot venues explicitly reviewed (first-party address + named OSM node).
# Any future venue requires its own signed source review AND a code review.
PILOT_VENUES = {
    "le-tetris-le-havre": {
        "venue": {
            "id": "le-tetris-le-havre",
            "name": "Le Tetris",
            "address": "Fort de Tourneville, 33 rue du 329e Régiment d'Infanterie",
            "postalCode": "76620",
            "city": "Le Havre",
            "department": "76",
            "region": "Normandie",
            "latitude": 49.5043853,
            "longitude": 0.1206928,
            "geoPrecision": "position GPS indicative du site du Tetris transmise par l'Office de Tourisme Le Havre Etretat Normandie via Cirkwi; point du lieu non assimilé à l'entrée des spectateurs. Les fiches individuelles du Tetris renvoient vers un repère Google Maps proche (49.503852, 0.120886).",
            "geoSource": "https://www.cirkwi.com/fr/point-interet/2508080-le-tetris",
        },
        "officialUrl": "https://letetris.fr/infos-pratiques/venir",
        "locationUrl": "https://www.cirkwi.com/fr/point-interet/2508080-le-tetris",
        "locationProofType": "independent-tourism-gps",
    },
    "le-temps-machine-joue-les-tours": {
        "venue": {
            "id": "le-temps-machine-joue-les-tours",
            "name": "Le Temps Machine",
            "address": "45-49 rue des Martyrs, parvis Miles Davis",
            "postalCode": "37300",
            "city": "Joué-lès-Tours",
            "department": "37",
            "region": "Centre-Val de Loire",
            "latitude": 47.352189,
            "longitude": 0.664716,
            "geoPrecision": "coordonnées géographiques indicatives (lat 47.352189, long 0.664716) publiées par l'annuaire indépendant Aleou; centre approximatif du site, pas repère métrique d'une entrée. Le lien Google Maps officiel de la salle indique un emplacement voisin.",
            "geoSource": "https://www.aleou.fr/salle-seminaire/26731-le-temps-machine",
        },
        "officialUrl": "https://letempsmachine.com/infos-pratiques/contacts",
        "locationUrl": "https://www.aleou.fr/salle-seminaire/26731-le-temps-machine",
        "locationProofType": "independent-venue-gps",
    },
    "le-chatodo-blois": {
        "venue": {
            "id": "le-chatodo-blois",
            "name": "Le Chato'do",
            "address": "113 avenue de Vendôme",
            "postalCode": "41000",
            "city": "Blois",
            "department": "41",
            "region": "Centre-Val de Loire",
            "latitude": 47.60562,
            "longitude": 1.31378,
            "geoPrecision": "centre indicatif du bâtiment Chato’do (OpenStreetMap way 118748447, coordonnées arrondies à 5 décimales), pas l'emplacement exact de l'entrée concerts rue Alexandre Vezin",
            "geoSource": "https://mapcarta.com/fr/W118748447"
        },
        "officialUrl": "https://chatodo.com/infos/venir/",
        "locationUrl": "https://mapcarta.com/fr/W118748447",
        "locationProofType": "openstreetmap-venue-way",
    },
    "hydrophone-lorient": {
        "venue": {
            "id": "hydrophone-lorient",
            "name": "Hydrophone",
            "address": "11 rue Honoré d’Estiennes d’Orves",
            "postalCode": "56100",
            "city": "Lorient",
            "department": "56",
            "region": "Bretagne",
            "latitude": 47.7308333333,
            "longitude": -3.3722222222,
            "geoPrecision": "coordonnées GPS du site fournies par Hydrophone (47°43’51.0 N, 3°22’20.0 W), approximation du site et non seuil exact de la porte Face A",
            "geoSource": "https://www.hydrophone.fr/-Pratique-.html"
        },
        "officialUrl": "https://www.lorient-agglo.bzh/en-actions/hydrophone/",
        "locationUrl": "https://www.hydrophone.fr/-Pratique-.html",
        "locationProofType": "official-venue-gps"
    },
    "atabal-biarritz": {
        "venue": {
            "id": "atabal-biarritz",
            "name": "Atabal",
            "address": "37 allée du Moura",
            "postalCode": "64200",
            "city": "Biarritz",
            "department": "64",
            "region": "Nouvelle-Aquitaine",
            "latitude": 43.4604,
            "longitude": -1.53984,
            "geoPrecision": "coordonnées GPS indicatives publiées par Tourisme 64 pour Atabal (latitude ~11 m, longitude ~1 m de précision numérique)",
            "geoSource": "https://www.tourisme64.com/sur-place/activites/biarritz/LOIAQU064V5BRPFJ-atabal/"
        },
        "officialUrl": "https://www.atabal-biarritz.fr/infos/venir-a-atabal/",
        "locationUrl": "https://www.tourisme64.com/sur-place/activites/biarritz/LOIAQU064V5BRPFJ-atabal/",
        "locationProofType": "official-tourism-geo"
    },
    "la-carene-brest": {
        "venue": {
            "id": "la-carene-brest",
            "name": "La Carène",
            "address": "30 rue Jean-Marie Le Bris",
            "postalCode": "29200",
            "city": "Brest",
            "department": "29",
            "region": "Bretagne",
            "latitude": 48.38479,
            "longitude": -4.48195,
            "geoPrecision": "centre du bâtiment La Carène (OpenStreetMap way 42531718, via Mapcarta, coordonnées arrondies)",
            "geoSource": "https://mapcarta.com/W42531718"
        },
        "officialUrl": "https://www.lacarene.fr/-infos-contacts-.html",
        "locationUrl": "https://mapcarta.com/W42531718",
        "locationProofType": "openstreetmap-venue-way"
    },
    "jokers-pub-angers": {
        "venue": {
            "id": "jokers-pub-angers",
            "name": "Le Joker's Pub",
            "address": "32 rue Saint-Laud",
            "postalCode": "49100",
            "city": "Angers",
            "department": "49",
            "region": "Pays de la Loire",
            "latitude": 47.47219,
            "longitude": -0.55304,
            "geoPrecision": "point du lieu (OpenStreetMap node 4789000416)",
            "geoSource": "https://mapcarta.com/fr/N4789000416"
        },
        "officialUrl": "https://www.jokerspubangers.com/le-pub-jokers-angers.php",
        "locationUrl": "https://mapcarta.com/fr/N4789000416"
    },
    "backstage-by-the-mill-paris": {
        "venue": {
            "id": "backstage-by-the-mill-paris",
            "name": "Backstage By The Mill",
            "address": "92 bis boulevard de Clichy",
            "postalCode": "75018",
            "city": "Paris",
            "department": "75",
            "region": "Île-de-France",
            "latitude": 48.8842402,
            "longitude": 2.3321006,
            "geoPrecision": "point nominatif du théâtre (OpenStreetMap node 4428897899)",
            "geoSource": "https://www.openstreetmap.org/api/0.6/node/4428897899"
        },
        "officialUrl": "https://www.backstage-btm.com/infos-pratiques/",
        "locationUrl": "https://www.openstreetmap.org/api/0.6/node/4428897899"
    },
    "glazart-paris": {
        "venue": {
            "id": "glazart-paris",
            "name": "Glazart",
            "address": "7–15 avenue de la Porte de la Villette",
            "postalCode": "75019",
            "city": "Paris",
            "department": "75",
            "region": "Île-de-France",
            "latitude": 48.899283,
            "longitude": 2.3866102,
            "geoPrecision": "centre du bâtiment nommé Glazart (OpenStreetMap way 64038567, géocodage Nominatim)",
            "geoSource": "https://www.openstreetmap.org/api/0.6/way/64038567"
        },
        "officialUrl": "https://www.glazart.com/infospratiques/",
        "locationUrl": "https://www.openstreetmap.org/api/0.6/way/64038567",
        "locationProofType": "openstreetmap-venue-way"
    },
    "le-trabendo-paris": {
        "venue": {
            "id": "le-trabendo-paris",
            "name": "Le Trabendo",
            "address": "211 avenue Jean Jaurès",
            "postalCode": "75019",
            "city": "Paris",
            "department": "75",
            "region": "Île-de-France",
            "latitude": 48.89265,
            "longitude": 2.39396,
            "geoPrecision": "centre indicatif du bâtiment nommé Le Trabendo (OpenStreetMap way 81704888, coordonnées arrondies)",
            "geoSource": "https://www.openstreetmap.org/api/0.6/way/81704888"
        },
        "officialUrl": "https://www.letrabendo.net/",
        "locationUrl": "https://www.openstreetmap.org/api/0.6/way/81704888",
        "locationProofType": "openstreetmap-venue-way"
    },
    "la-cave-aux-poetes-roubaix": {
        "venue": {
            "id": "la-cave-aux-poetes-roubaix",
            "name": "La Cave aux Poètes",
            "address": "16 rue du Grand Chemin",
            "postalCode": "59100",
            "city": "Roubaix",
            "department": "59",
            "region": "Hauts-de-France",
            "latitude": 50.6921711,
            "longitude": 3.1692704,
            "geoPrecision": "point nominatif de La Cave Aux Poètes (OpenStreetMap node 5902484873, nom adresse site et téléphone concordants)",
            "geoSource": "https://www.openstreetmap.org/api/0.6/node/5902484873"
        },
        "officialUrl": "https://caveauxpoetes.com/pratique/",
        "locationUrl": "https://www.openstreetmap.org/api/0.6/node/5902484873",
        "locationProofType": "openstreetmap-venue-node"
    },
    "le-forum-vaureal": {
        "venue": {
            "id": "le-forum-vaureal",
            "name": "Le Forum",
            "address": "95 boulevard de l'Oise",
            "postalCode": "95490",
            "city": "Vauréal",
            "department": "95",
            "region": "Île-de-France",
            "latitude": 49.0313663,
            "longitude": 2.0218937,
            "geoPrecision": "nœud OpenStreetMap nominatif Le Forum (node 4742610793, adresse et site officiel concordants)",
            "geoSource": "https://www.openstreetmap.org/api/0.6/node/4742610793"
        },
        "officialUrl": "https://leforum.cergypontoise.fr/infos-pratiques/venir-au-forum",
        "locationUrl": "https://www.openstreetmap.org/api/0.6/node/4742610793",
        "locationProofType": "openstreetmap-venue-node"
    },
    "la-maroquinerie-paris": {
        "venue": {
            "id": "la-maroquinerie-paris",
            "name": "La Maroquinerie",
            "address": "23 rue Boyer",
            "postalCode": "75020",
            "city": "Paris",
            "department": "75",
            "region": "Île-de-France",
            "latitude": 48.86853,
            "longitude": 2.39206,
            "geoPrecision": "point nominatif du lieu (OpenStreetMap node 1402597553, coordonnées arrondies)",
            "geoSource": "https://mapcarta.com/fr/N1402597553"
        },
        "officialUrl": "https://www.lamaroquinerie.fr/fr/agenda/view/2212/allt/?of=7",
        "locationUrl": "https://mapcarta.com/fr/N1402597553"
    },
    "la-boule-noire-paris": {
        "venue": {
            "id": "la-boule-noire-paris",
            "name": "La Boule Noire",
            "address": "120 boulevard de Rochechouart",
            "postalCode": "75018",
            "city": "Paris",
            "department": "75",
            "region": "Île-de-France",
            "latitude": 48.88234,
            "longitude": 2.34028,
            "geoPrecision": "point nominatif de La Boule Noire, distinct de La Cigale (OpenStreetMap node 357916037, coordonnées arrondies)",
            "geoSource": "https://mapcarta.com/N357916037"
        },
        "officialUrl": "https://laboule-noire.fr/",
        "locationUrl": "https://mapcarta.com/N357916037"
    },
    "rock-n-eat-lyon": {
        "venue": {
            "id": "rock-n-eat-lyon",
            "name": "Rock n' Eat",
            "address": "32 quai Arloing",
            "postalCode": "69009",
            "city": "Lyon",
            "department": "69",
            "region": "Auvergne-Rhône-Alpes",
            "latitude": 45.7709758,
            "longitude": 4.8114869,
            "geoPrecision": "point nominatif du lieu (OpenStreetMap node 5973017988)",
            "geoSource": "https://www.openstreetmap.org/api/0.6/node/5973017988"
        },
        "officialUrl": "https://www.rockneat.com/Infos",
        "locationUrl": "https://www.openstreetmap.org/api/0.6/node/5973017988"
    },
    "la-maison-bleue-strasbourg": {
        "venue": {
            "id": "la-maison-bleue-strasbourg",
            "name": "La Maison Bleue",
            "address": "3 rue de Guebwiller",
            "postalCode": "67100",
            "city": "Strasbourg",
            "department": "67",
            "region": "Grand Est",
            "latitude": 48.5595349,
            "longitude": 7.7680524,
            "geoPrecision": "point nominatif du lieu (OpenStreetMap node 7812445394)",
            "geoSource": "https://www.openstreetmap.org/api/0.6/node/7812445394"
        },
        "officialUrl": "https://www.lamaisonbleue-stbg.com/contact/",
        "locationUrl": "https://www.openstreetmap.org/api/0.6/node/7812445394"
    },
    "le-brin-de-zinc-barberaz": {
        "venue": {
            "id": "le-brin-de-zinc-barberaz",
            "name": "Le Brin de Zinc",
            "address": "3 route de la Peysse",
            "postalCode": "73000",
            "city": "Barberaz",
            "department": "73",
            "region": "Auvergne-Rhône-Alpes",
            "latitude": 45.5613,
            "longitude": 5.94761,
            "geoPrecision": "point du lieu (OpenStreetMap node 1979372261)",
            "geoSource": "https://mapcarta.com/N1979372261"
        },
        "officialUrl": "https://brindezinc.fr/informations-pratiques/",
        "locationUrl": "https://mapcarta.com/N1979372261"
    },
    "bonjour-minuit-saint-brieuc": {
        "venue": {
            "id": "bonjour-minuit-saint-brieuc",
            "name": "Bonjour Minuit",
            "address": "Place Nina Simone",
            "postalCode": "22000",
            "city": "Saint-Brieuc",
            "department": "22",
            "region": "Bretagne",
            "latitude": 48.5196,
            "longitude": -2.7852,
            "geoPrecision": "point indicatif du lieu sur la fiche gouvernementale Acceslibre, coordonnées arrondies à quatre décimales (~10 m latitude), non assimilées à l'entrée des concerts",
            "geoSource": "https://acceslibre.beta.gouv.fr/app/22-saint-brieuc/a/salle-de-spectacle/erp/bonjour-minuit/",
        },
        "officialUrl": "https://bonjour-minuit.fr/contact/",
        "locationUrl": "https://acceslibre.beta.gouv.fr/app/22-saint-brieuc/a/salle-de-spectacle/erp/bonjour-minuit/",
        "locationProofType": "government-accessibility-location",
    },
    "le-jardin-moderne-rennes": {
        "venue": {
            "id": "le-jardin-moderne-rennes",
            "name": "Le Jardin Moderne",
            "address": "11 rue du Manoir de Servigné",
            "postalCode": "35000",
            "city": "Rennes",
            "department": "35",
            "region": "Bretagne",
            "latitude": 48.10164,
            "longitude": -1.72557,
            "geoPrecision": "centre indicatif du bâtiment Le Jardin Moderne (OpenStreetMap way 80301709, via Mapcarta, coordonnées arrondies à 5 décimales), non assimilé à l'entrée de la salle",
            "geoSource": "https://mapcarta.com/fr/W80301709",
        },
        "officialUrl": "https://www.jardinmoderne.org/acces-2/",
        "locationUrl": "https://mapcarta.com/fr/W80301709",
        "locationProofType": "openstreetmap-venue-way",
    },
}

# Only these exact, individually reviewed organizer-controlled tickets are allowed.
# The venue's generic Billetweb calendar and unrelated organizer tickets remain blocked.
BRIN_ORGANIZER_VERIFIED = {
    "go-c-20261105-barberaz-noveria": {
        "title": "Noveria + Tarchon Fist + Wedingoth",
        "date": "2026-11-05",
        "artistIds": [
            "noveria",
            "tarchon-fist",
            "wedingoth"
        ],
        "genres": [
            "Metal progressif",
            "Power Metal",
            "Heavy Metal"
        ],
        "ticketUrl": "https://www.billetweb.fr/noveria-x-tarchon-fist-x-wedingoth-power-metal-progressif-italie-x-france",
        "partnerUrl": "https://www.culturesducoeur.org/Home/evenement_look?id_evenement=237029"
    },
    "go-c-20261109-barberaz-fvzz-popvli": {
        "title": "Fvzz Popvli",
        "date": "2026-11-09",
        "artistIds": [
            "fvzz-popvli"
        ],
        "genres": [
            "Stoner Rock",
            "Garage Punk",
            "Heavy Psych"
        ],
        "ticketUrl": "https://www.billetweb.fr/fvzz-popvli-heavy-psych-garage-punk-stoner-rock-italie",
        "partnerUrl": "https://www.culturesducoeur.org/Home/evenement_look?id_evenement=237797"
    },
    "go-c-20261112-barberaz-ancient-settlers": {
        "title": "Ancient Settlers",
        "date": "2026-11-12",
        "artistIds": [
            "ancient-settlers"
        ],
        "genres": [
            "Death Metal mélodique",
            "Metalcore"
        ],
        "ticketUrl": "https://www.billetweb.fr/ancient-settlers-death-metal-melodique-metalcore-venezuela-espagne",
        "partnerUrl": "https://www.culturesducoeur.org/Home/evenement_look?id_evenement=237800"
    },
    "go-c-20261115-barberaz-moscow-death-brigade": {
        "title": "Moscow Death Brigade",
        "date": "2026-11-15",
        "artistIds": [
            "moscow-death-brigade"
        ],
        "genres": [
            "Punk",
            "Rap",
            "Electro"
        ],
        "ticketUrl": "https://www.billetweb.fr/moscow-death-brigade1",
        "partnerUrl": "https://www.culturesducoeur.org/Home/evenement_look?id_evenement=237803"
    },
    # Individually verified organizer tickets with narrower, explicitly
    # documented corroboration. A Bandsintown artist listing and a tour
    # announcement are NOT represented as organizer-submitted partners.
    "go-c-20261110-barberaz-wake-the-dead": {
        "title": "Wake the Dead + Ghouldozer",
        "date": "2026-11-10",
        "artistIds": ["wake-the-dead", "ghouldozer"],
        "genres": ["Hardcore", "Death Metal"],
        "ticketUrl": "https://www.billetweb.fr/wake-the-dead-ft-ghouldozer-hardcore-death-metal",
        "partnerUrl": "https://www.bandsintown.com/fr/e/109057220-wake-the-dead-%28hardcore%29-at-le-brin-de-zinc?came_from=253",
        "partnerProofType": "artist-event-listing",
        "partnerCheckedFields": ["artists", "date", "venue"],
    },
    "go-c-20261206-barberaz-xaon": {
        "title": "Xaon + Vortex",
        "date": "2026-12-06",
        "artistIds": ["xaon", "vortex"],
        "genres": ["Death Metal symphonique"],
        "ticketUrl": "https://www.billetweb.fr/xaon-x-vortex-symphonic-death-metal-canada",
        "partnerUrl": "https://www.metal-rules.com/2026/10/25/quebecs-vortex-announces-eu-tour-dates-w-xaon-symphony-for-the-dead-the-last-symphony-europe-tour/",
        "partnerProofType": "independent-tour-report",
        "partnerCheckedFields": ["artists", "date", "venue"],
    }
}


# Backstage By The Mill: only three named first-party event detail pages
# independently reviewed. New generic event URLs do not become publishable
# just because they share the same domain.
BACKSTAGE_VERIFIED = {
    "go-c-20270226-paris-turmion-katilot": {
        "title": "Turmion Kätilöt",
        "date": "2027-02-26",
        "artistIds": ["turmion-katilot"],
        "genres": ["Industrial Metal"],
        "url": "https://www.backstage-btm.com/agenda/turmion-katilot/",
    },
    "go-c-20270315-paris-despairsray": {
        "title": "D’ESPAIRSRAY",
        "date": "2027-03-15",
        "artistIds": ["despairsray"],
        "genres": ["Heavy Metal"],
        "url": "https://www.backstage-btm.com/agenda/despairsray/",
    },
    "go-c-20270325-paris-thulcandra": {
        "title": "Thulcandra + Yoth Iria + Vorga",
        "date": "2027-03-25",
        "artistIds": ["thulcandra", "yoth-iria", "vorga"],
        "genres": ["Melodic Death Metal"],
        "url": "https://www.backstage-btm.com/agenda/thulcandra-yoth-iria-vorga/",
    },
}

# Two individually reviewed organizer-controlled tickets paired with exact
# official venue listings. This is NOT permission to ingest any other event
# from Shotgun, the ticket office, or the generic venue calendar.
REGIONAL_APPROVED = {
    "go-c-20261104-lyon-lagrimas-prestige": {
        "venueId": "rock-n-eat-lyon",
        "title": "Lagrimas + The Prestige",
        "date": "2026-11-04",
        "artistIds": ["lagrimas", "the-prestige"],
        "newArtistIds": ["lagrimas", "the-prestige"],
        "genres": ["Post-hardcore", "Screamo"],
        "officialUrl": "https://shotgun.live/events/lagrimas-the-prestige",
        "venueCalendar": "https://www.rockneat.com/Programmation"
    },
    "go-c-20261113-strasbourg-local-heroes": {
        "venueId": "la-maison-bleue-strasbourg",
        "title": "Dazzling Bravery + BRDN + Curtains + Foggy Froggies",
        "date": "2026-11-13",
        "artistIds": ["dazzling-bravery", "brdn", "curtains", "foggy-froggies"],
        "newArtistIds": ["dazzling-bravery", "brdn", "curtains", "foggy-froggies"],
        "genres": ["Metal"],
        "officialUrl": "https://billetterie.lamaisonbleue-stbg.com/share/event/385-Dirty8-Birthday-LOCAL-HEROES-Dazzling-Bravery-BRDN-Curtains-Foggy-Froggies",
        "venueCalendar": "https://www.lamaisonbleue-stbg.com/agenda/"
    },
    "go-c-20261111-strasbourg-wake-the-dead": {
        "venueId": "la-maison-bleue-strasbourg",
        "title": "Wake the Dead + Toxic Shock + Sick Lame & Lazy",
        "date": "2026-11-11",
        "artistIds": ["wake-the-dead", "toxic-shock", "sick-lame-lazy"],
        "newArtistIds": ["toxic-shock", "sick-lame-lazy"],
        "genres": ["Hardcore", "Screamo"],
        "officialUrl": "https://billetterie.lamaisonbleue-stbg.com/share/event/370-Dirty8-Birthday-WAKE-THE-DEAD-SICK-LAME-LAZY",
        "venueCalendar": "https://www.lamaisonbleue-stbg.com/agenda/"
    }
}

# Glazart: two reviewed individual official pages. Desolated and
# Guttural Slug are in body lineups but not in abbreviated page titles.
# Never accept generic agendas, ticket sites, or inferred show start hours.
GLAZART_VERIFIED = {
    "go-c-20261106-paris-lagrimas": {
        "title": "Lagrimas",
        "date": "2026-11-06",
        "artistIds": ["lagrimas"],
        "newArtistIds": [],
        "genres": ["Hardcore","Screamo"],
        "officialUrl": "https://www.glazart.com/06-11-26-concert-lagrimas/"
    },
    "go-c-20261130-paris-black-sabbitch": {
        "title": "Black Sabbitch",
        "date": "2026-11-30",
        "artistIds": ["black-sabbitch"],
        "newArtistIds": ["black-sabbitch"],
        "genres": ["Doom"],
        "officialUrl": "https://www.glazart.com/30-11-26-concert-black-sabbitch/"
    },
    "go-c-20261128-paris-sunami": {
        "title": "Sunami + Desolated + Missing Link + Extinguish",
        "date": "2026-11-28",
        "artistIds": ["sunami","desolated","missing-link","extinguish"],
        "newArtistIds": [],
        "genres": ["Hardcore"],
        "officialUrl": "https://www.glazart.com/28-11-26-concert-sunami-missing-link-extinguish/"
    },
    "go-c-20270324-paris-party-cannon": {
        "title": "Party Cannon + Internal Bleeding + Guttural Slug",
        "date": "2027-03-24",
        "artistIds": ["party-cannon","internal-bleeding","guttural-slug"],
        "newArtistIds": ["party-cannon","internal-bleeding","guttural-slug"],
        "genres": ["Death Metal","Slam"],
        "officialUrl": "https://www.glazart.com/24-03-27-concert-party-cannon-x-internal-bleeding/"
    },
    "go-c-20261104-paris-eyehategod": {
        "title": "Eyehategod + Deafkids",
        "date": "2026-11-04",
        "artistIds": ["eyehategod", "deafkids"],
        "newArtistIds": ["eyehategod", "deafkids"],
        "genres": ["Sludge", "Avant-Punk"],
        "officialUrl": "https://www.glazart.com/04-11-26-concert-eyehategod-guest/",
        "secondaryUrl": "https://www.eventim.fr/event/eyehategod-glazart-paris-19-21567768/",
        "secondaryProofType": "organizer-ticketing-distribution",
        "secondaryCheckedFields": ["artists", "date", "venue"],
    },
    "go-c-20261114-paris-the-vintage-caravan": {
        "title": "The Vintage Caravan + Damantra",
        "date": "2026-11-14",
        "artistIds": ["the-vintage-caravan", "damantra"],
        "newArtistIds": [],
        "genres": ["Classic Rock"],
        "officialUrl": "https://www.glazart.com/14-11-26-concert-the-vintage-caravan/",
        "primaryCheckedFields": ["leadArtist", "date", "venue", "genre"],
        "secondaryUrl": "https://billetterie.seetickets.fr/the-vintage-caravan-damantra-concert-glazart-paris-19-14-novembre-2026-css5-garmonbozia-pg101-ri11777349.html",
        "secondaryProofType": "organizer-ticketing-detail",
        "secondaryCheckedFields": ["artists", "date", "venue", "genre"],
    }
}

# Two Paris concert venues with FIRST-PARTY event-specific programmes.
# Maroquinerie: the November 2026 official calendar establishes the year
# when an individual gig description omits it. No later month inference.
# La Boule Noire: the show-specific page names headliner, support,
# complete date, metal genres; the separate first-party homepage gives address.
PARIS_CLUB_VERIFIED = {
    "go-c-20261110-paris-allt": {
        "venueId":"la-maroquinerie-paris",
        "title":"Allt + Avralize + Bite Down",
        "date":"2026-11-10",
        "artistIds":["allt","avralize","bite-down"],
        "newArtistIds":["allt","avralize","bite-down"],
        "genres":["Metalcore"],
        "officialUrl":"https://www.lamaroquinerie.fr/fr/agenda/view/2212/allt/?of=7",
        "proofs":[
            ("official-organizer-or-venue",
             "https://www.lamaroquinerie.fr/fr/agenda/view/2212/allt/?of=7",
             ("artists","date","venue","genre"))
        ],
    },
    "go-c-20261121-paris-horskh": {
        "venueId":"la-maroquinerie-paris",
        "title":"Horskh + We Are Magonia",
        "date":"2026-11-21",
        "artistIds":["horskh","we-are-magonia"],
        "newArtistIds":["we-are-magonia"],
        "genres":["Metal industriel"],
        "officialUrl":"https://www.lamaroquinerie.fr/fr/agenda/view/2180/horskh/?of=18",
        "proofs":[
            ("official-organizer-or-venue",
             "https://www.lamaroquinerie.fr/fr/agenda/view/2180/horskh/?of=18",
             ("artists","venue","genre")),
            ("first-party-venue-calendar",
             "https://www.lamaroquinerie.fr/fr/agenda/",
             ("artists","date","venue"))
        ],
    },
    "go-c-20261115-paris-ice-sealed-eyes": {
        "venueId":"la-boule-noire-paris",
        "title":"Ice Sealed Eyes + Eiga",
        "date":"2026-11-15",
        "artistIds":["ice-sealed-eyes","eiga"],
        "newArtistIds":["eiga"],
        "genres":["Newcore","Metalcore"],
        "officialUrl":"https://laboule-noire.fr/ice-sealed-eyes/",
        "proofs":[
            ("official-organizer-or-venue",
             "https://laboule-noire.fr/ice-sealed-eyes/",
             ("artists","date","venue","genre"))
        ],
    },
}

# Exact organizer-controlled Secret Place event details; musical start time
# unknown (Wix 19:00-23:00 denotes event window, not start of the performance).
# Genre is independently documented in a *different* editorial source and
# cannot be attributed to the official Wix event page.
SECRET_PLACE_DECEMBER_VERIFIED = {
    "go-c-20261205-secret-place-cracked-heads": {
        "title": "The Cracked Heads + The Psychotic Unicorns + Noble Rot",
        "date": "2026-12-05",
        "time": None,
        "artistIds": ["the-cracked-heads","the-psychotic-unicorns","noble-rot"],
        "newArtistIds": ["the-cracked-heads","the-psychotic-unicorns","noble-rot"],
        "genres": ["Garage Punk"],
        "officialUrl": "https://www.toutafond.com/event-details/the-cracked-heads-the-psychotic-unicorns-noble-rot",
        "genreUrl": "https://montpellier.concerts-metal.com/",
        "genreProofType": "editorial-genre-context",
    },
    "go-c-20261206-secret-place-the-spitters": {
        "title": "The Spitters + Panic Lights",
        "date": "2026-12-06",
        "time": None,
        "artistIds": ["the-spitters","panic-lights"],
        "newArtistIds": ["the-spitters","panic-lights"],
        "genres": ["Punk Rock"],
        "officialUrl": "https://www.toutafond.com/event-details/la-taf-boomerang-presentent-the-spitters-panic-lights",
        "genreUrl": "https://www.lagazettedenimes.fr/agenda/musiques-2026-12-06-rock-et-punk-secret-place-saint-jean-de-vedas/",
        "genreProofType": "editorial-genre-context",
    },
}

# Independently checked original venue detail and organizer-published OpenAgenda.
# Only this exact 2026 riot-grrrl triple bill can enter from this venue.
CAVE_POETES_VERIFIED = {
    "go-c-20261216-roubaix-joobieseaz-belljars": {
        "title": "Joobieseaz + Belljars",
        "date": "2026-12-16",
        "time": "19:00",
        "artistIds": ["joobieseaz","belljars"],
        "newArtistIds": ["joobieseaz","belljars"],
        "genres": ["Post Punk"],
        "officialUrl": "https://caveauxpoetes.com/evenement/joobieseaz/",
        "organizerCalendar": "https://caveauxpoetes.com/agenda/",
        "calendarProofType": "first-party-venue-calendar",
        "calendarCheckedFields": ["artists","date","venue"]
    },
    "go-c-20261108-roubaix-babe-haven-latter-muddle": {
        "title": "Babe Haven + Latter + Muddle",
        "date": "2026-11-08",
        "time": "18:30",
        "artistIds": ["babe-haven","latter","muddle"],
        "newArtistIds": ["babe-haven","latter","muddle"],
        "genres": ["Punk","Nu Metal"],
        "officialUrl": "https://caveauxpoetes.com/evenement/babe-haven-latter-muddle/",
        "organizerCalendar": "https://openagenda.com/fr/la-cave-aux-poetes/events/32006543_babe-haven-latter-muddle"
    }
}

# Five exact first-party concert details at the newly verified Forum venue.
# Venue OSM node is named Le Forum, has official web/address/phone tags.
# The Wolves in the Throne Room detail contradicts itself on start time
# (18:30 header / 20:30 body); do not publish an inferred start.
FORUM_VERIFIED = {
    "go-c-20270115-vaureal-motocultor-tour": {
        "title": "Rhapsody of Fire + Serious Black + Submasq + Aeon Gods + Rock Out",
        "date": "2027-01-15",
        "artistIds": ["rhapsody-of-fire","serious-black","submasq","aeon-gods","rock-out"],
        "newArtistIds": [],
        "genres": ["Metal"],
        "time": "19:00",
        "officialUrl": "https://leforum.cergypontoise.fr/agenda/motocultor-across-europe-tour-2027",
        "secondaryUrl": "https://www.motocultor-festival.com/motocultor-across-europe-tour-2027/",
        "secondaryProofType": "official-organizer-tour"
    },
    "go-c-20270423-vaureal-sortilege": {
        "title": "Sortilège",
        "date": "2027-04-23",
        "artistIds": ["sortilege"],
        "newArtistIds": ["sortilege"],
        "genres": ["Heavy Metal"],
        "time": "20:30",
        "officialUrl": "https://leforum.cergypontoise.fr/agenda/sortilege",
        "secondaryUrl": "https://sortilege.website/concerts/",
        "secondaryProofType": "official-artist-tour"
    },
    "go-c-20261106-vaureal-senser-psykup": {
        "title": "Senser + Psykup",
        "date": "2026-11-06",
        "artistIds": ["senser","psykup"],
        "newArtistIds": ["senser"],
        "genres": ["Rap Rock"],
        "time": "20:00",
        "officialUrl": "https://leforum.cergypontoise.fr/agenda/senser"
    },
    "go-c-20261107-vaureal-wolves-throne-room": {
        "title": "Wolves in the Throne Room + Worm + Final Dose",
        "date": "2026-11-07",
        "artistIds": ["wolves-in-the-throne-room","worm","final-dose"],
        "newArtistIds": ["wolves-in-the-throne-room","worm","final-dose"],
        "genres": ["Black Metal"],
        "time": None,
        "officialUrl": "https://leforum.cergypontoise.fr/agenda/wolves-throne-room"
    },
    "go-c-20261112-vaureal-mass-hysteria": {
        "title": "Mass Hysteria",
        "date": "2026-11-12",
        "artistIds": ["mass-hysteria"],
        "newArtistIds": [],
        "genres": ["Metal"],
        "time": "20:30",
        "officialUrl": "https://leforum.cergypontoise.fr/agenda/mass-hysteria"
    },
    "go-c-20270317-vaureal-michael-schenker-group": {
        "title": "Michael Schenker Group",
        "date": "2027-03-17",
        "artistIds": ["michael-schenker-group"],
        "newArtistIds": [],
        "genres": ["Hard Rock","Metal"],
        "time": "19:30",
        "officialUrl": "https://leforum.cergypontoise.fr/agenda/michael-schenker-group"
    },
    "go-c-20270522-vaureal-hard-rock-party": {
        "title": "Harsh + Furies + Charcoal",
        "date": "2027-05-22",
        "artistIds": ["harsh","furies","charcoal"],
        "newArtistIds": ["harsh","furies","charcoal"],
        "genres": ["Hard Rock"],
        "time": "20:00",
        "officialUrl": "https://leforum.cergypontoise.fr/agenda/hard-rock-party"
    },
}

# Allowlist of independently reviewed Trabendo official concert pages.
# The daily discovery genre badges NEVER authorize blanket publishing.
TRABENDO_VERIFIED = {
    "go-c-20261112-paris-frankie-witch-fingers": {
        "title": "Frankie and the Witch Fingers + Iguana Death Cult",
        "date": "2026-11-12",
        "artistIds": ["frankie-and-the-witch-fingers","iguana-death-cult"],
        "newArtistIds": ["frankie-and-the-witch-fingers","iguana-death-cult"],
        "genres": ["Punk Rock"],
        "officialUrl": "https://www.letrabendo.net/programmation/frankie-and-the-witch-fingers/"
    },
    "go-c-20261128-paris-kid-kapichi": {
        "title": "Kid Kapichi + Demob Happy",
        "date": "2026-11-28",
        "artistIds": ["kid-kapichi","demob-happy"],
        "newArtistIds": [],
        "genres": ["Punk Rock"],
        "officialUrl": "https://www.letrabendo.net/programmation/kid-kapichi/"
    },
    "go-c-20270119-paris-comeback-kid": {
        "title": "Comeback Kid",
        "date": "2027-01-19",
        "artistIds": ["comeback-kid"],
        "newArtistIds": ["comeback-kid"],
        "genres": ["Punk Rock"],
        "officialUrl": "https://www.letrabendo.net/programmation/comeback-kid/"
    },
    "go-c-20270606-paris-black-flag": {
        "title": "Black Flag",
        "date": "2027-06-06",
        "artistIds": ["black-flag"],
        "newArtistIds": ["black-flag"],
        "genres": ["Punk Hardcore"],
        "officialUrl": "https://www.letrabendo.net/programmation/black-flag/"
    },
    "go-c-20270122-paris-wage-war": {
        "title": "Wage War",
        "date": "2027-01-22",
        "artistIds": ["wage-war"],
        "newArtistIds": ["wage-war"],
        "genres": ["Metalcore"],
        "officialUrl": "https://www.letrabendo.net/programmation/wage-war/"
    },
    "go-c-20270203-paris-whitechapel": {
        "title": "Whitechapel",
        "date": "2027-02-03",
        "artistIds": ["whitechapel"],
        "newArtistIds": ["whitechapel"],
        "genres": ["Metalcore"],
        "officialUrl": "https://www.letrabendo.net/programmation/whitechapel/"
    },
}

# Explicit one-time, source-documented map correction. The original 127-
# event baseline remains immutable. The precise location is the named
# OpenStreetMap venue node (not the midpoint of Nantes).
FERRAILLEUR_LOCATION_FIX = {
    "address": "Quai des Antilles",
    "postalCode": "44200",
    "latitude": 47.20058,
    "longitude": -1.57365,
    "geoPrecision": "point du lieu (OpenStreetMap node 373218467)",
    "geoSource": (
        "Adresse officielle https://www.leferrailleur.fr/contact ; "
        "point de la salle OpenStreetMap node 373218467"
    ),
}
FERRAILLEUR_VENUE_ID = "le-ferrailleur-nantes"


SECRET_PLACE_VENUE_ID = "secret-place-saint-jean-de-vedas"
SECRET_PLACE_LOCATION_FIX = {
    "latitude": 43.5617771,
    "longitude": 3.8419650,
    "geoPrecision": "centre du bâtiment nommé Secret Place (OpenStreetMap way 382485149, géocodage Nominatim)",
    "geoSource": "https://www.openstreetmap.org/api/0.6/way/382485149",
}
SECRET_PLACE_LOCATION_OFFICIAL = "https://www.toutafond.com/acces"
SECRET_PLACE_LOCATION_OSM = "https://www.openstreetmap.org/api/0.6/way/382485149"

# Precise GPS published directly by Le Rex; separate Toulouse Tourisme
# listing corroborates the address, not the GPS. Never call it an entrance.
REX_VENUE_ID = "le-rex-toulouse"
REX_LOCATION_OFFICIAL = "https://www.lerextoulouse.com/fr/contact/acces/"
REX_LOCATION_TOURISM = "https://www.toulouse-tourisme.com/activite/le-rex-de-toulouse/"
REX_LOCATION_FIX = {
    "address": "15 avenue Honoré Serres",
    "postalCode": "31000",
    "latitude": 43.611901,
    "longitude": 1.438364,
    "geoPrecision": "GPS publié par Le Rex (localisation de la salle, entrée non garantie)",
    "geoSource": REX_LOCATION_OFFICIAL,
}




# Three historic venue pins reviewed against the first party and an independent
# named OpenStreetMap feature. Exact patches and evidence only; never guess an
# entrance or modify the immutable baseline concerts-reference.json.
NEW_REFERENCE_GEO_SOURCES = {
    "le-bikini-toulouse": {
        "patch": {
            "address": "Rue Théodore Monod, Parc Technologique du Canal",
            "postalCode": "31520",
            "city": "Ramonville-Saint-Agne",
            "latitude": 43.54795,
            "longitude": 1.48568,
            "geoPrecision": "point OpenStreetMap Le Bikini (node 380889428 ; entrée non garantie)",
            "geoSource": "https://www.openstreetmap.org/node/380889428",
        },
        "officialUrl": "https://lebikini.com/section/infos-pratiques/infos-pratiques",
        "officialProof": "official-venue-address",
        "officialFields": {"name", "address", "postalCode", "city"},
        "geoUrl": "https://www.openstreetmap.org/node/380889428",
        "geoProof": "openstreetmap-venue-node",
        "geoFields": {"venueName", "coordinates"},
        "expectedOriginal": {
            "name": "Le Bikini", "city": "Toulouse",
            "address": "Adresse exacte à vérifier",
            "postalCode": "À vérifier",
            "latitude": 43.604, "longitude": 1.444,
        },
    },
    "rockstore-montpellier": {
        "patch": {
            "address": "20 rue de Verdun",
            "postalCode": "34000",
            "latitude": 43.60624,
            "longitude": 3.88137,
            "geoPrecision": "point OpenStreetMap Rockstore (node 579814541 ; entrée non garantie)",
            "geoSource": "https://www.openstreetmap.org/node/579814541",
        },
        "officialUrl": "https://rockstore.fr/infos-pratiques/",
        "officialProof": "official-venue-address",
        "officialFields": {"name", "address", "postalCode", "city"},
        "geoUrl": "https://www.openstreetmap.org/node/579814541",
        "geoProof": "openstreetmap-venue-node",
        "geoFields": {"venueName", "coordinates"},
        "expectedOriginal": {
            "name": "Rockstore", "city": "Montpellier",
            "address": "Adresse exacte à vérifier",
            "postalCode": "À vérifier",
            "latitude": 43.608, "longitude": 3.878,
        },
    },
    "the-black-lab-wasquehal": {
        "patch": {
            "address": "8 rue des Champs, P.A. de la Pilaterie",
            "postalCode": "59290",
            "latitude": 50.652602,
            "longitude": 3.122069,
            "geoPrecision": "GPS officiel du Black Lab (point du lieu, entrée publique au 12 rue de la Ladrie)",
            "geoSource": "https://theblacklab.fr/adresse/",
        },
        "officialUrl": "https://theblacklab.fr/adresse/",
        "officialProof": "official-venue-gps",
        "officialFields": {"name", "address", "postalCode", "city",
                           "latitude", "longitude"},
        "geoUrl": "https://www.openstreetmap.org/node/9179662650",
        "geoProof": "openstreetmap-venue-node",
        "geoFields": {"venueName", "coordinates"},
        "expectedOriginal": {
            "name": "The Black Lab", "city": "Wasquehal",
            "address": "Adresse exacte à vérifier",
            "postalCode": "À vérifier",
            "latitude": 50.67, "longitude": 3.13,
        },
    },
    "antipode-rennes": {
        "patch": {
            "address": "75 avenue Jules Maniez",
            "postalCode": "35000",
            "latitude": 48.09823,
            "longitude": -1.70464,
            "geoPrecision": "centre du bâtiment nommé Antipode (OpenStreetMap way 943632490), localisation indicative du bâtiment et non de l'entrée spectacles",
            "geoSource": "https://mapcarta.com/fr/W943632490",
        },
        "officialUrl": "https://antipode-rennes.fr/informations-pratiques/acces-et-horaires",
        "officialProof": "official-venue-address",
        "officialFields": {"name", "address", "postalCode", "city"},
        "geoUrl": "https://mapcarta.com/fr/W943632490",
        "geoProof": "openstreetmap-venue-way",
        "geoFields": {"venueName", "coordinates"},
        "expectedOriginal": {
            "name": "Antipode", "city": "Rennes",
            "address": "Adresse exacte à vérifier",
            "postalCode": "À vérifier",
            "latitude": 48.113, "longitude": -1.681,
        },
    },
}


def validate_new_reference_geo(approvals, reference, today):
    """Independently signed, two-source proof for exact historic pins."""
    rows = approvals.get("referenceVenueCorrections", [])
    require(isinstance(rows, list) and len(rows) <= 6,
            "Trop de corrections historiques de salles")
    allowed = {SECRET_PLACE_VENUE_ID, REX_VENUE_ID} | set(NEW_REFERENCE_GEO_SOURCES)
    ids = [x.get("venueId") if isinstance(x, dict) else None for x in rows]
    require(len(set(ids)) == len(ids) and set(ids).issubset(allowed),
            "Identifiant de correction inconnu ou en doublon")
    result = {}
    for row in rows:
        venue_id = row["venueId"]
        if venue_id not in NEW_REFERENCE_GEO_SOURCES:
            continue
        spec = NEW_REFERENCE_GEO_SOURCES[venue_id]
        checked = norm_date(row.get("reviewedAt"))
        require(row.get("reviewDecision") == "approved"
                and row.get("reviewedBy") == "independent-official-verifier"
                and checked == dt.date(2026, 11, 3) and checked <= today
                and row.get("venuePatch") == spec["patch"],
                "Adresse ou coordonnées hors liste blanche : " + venue_id)
        proofs = row.get("officialEvidence")
        expected = {
            spec["officialProof"]: (spec["officialUrl"], spec["officialFields"]),
            spec["geoProof"]: (spec["geoUrl"], spec["geoFields"]),
        }
        require(isinstance(proofs, list) and len(proofs) == 2
                and {p.get("proofType") for p in proofs if isinstance(p, dict)}
                    == set(expected),
                "Deux preuves géographiques indépendantes exigées")
        for p in proofs:
            require(isinstance(p, dict) and p.get("proofType") in expected,
                    "Source de localisation mal formée")
            url, fields = expected[p["proofType"]]
            require(p.get("url") == url
                    and p.get("checkedAt") == checked.isoformat()
                    and fields.issubset(set(p.get("checkedFields") or [])),
                    "Adresse ou repère cartographique absent/incomplet")
        initial = [v for v in reference["venues"] if v["id"] == venue_id]
        require(len(initial) == 1 and
                all(initial[0].get(k) == value
                    for k, value in spec["expectedOriginal"].items()),
                "Référence initiale de salle modifiée : " + venue_id)
        result[venue_id] = row
    return result

def corrected_reference_venues(reference, secret_place=False, le_rex=False,
                               extra_venues=()):
    """Build only exact, signed historic map states; baseline stays immutable."""
    require(set(extra_venues).issubset(NEW_REFERENCE_GEO_SOURCES),
            "Correction géographique supplémentaire non autorisée")
    venues = copy.deepcopy(reference["venues"])
    fixes = [(FERRAILLEUR_VENUE_ID, FERRAILLEUR_LOCATION_FIX)]
    if secret_place:
        fixes.append((SECRET_PLACE_VENUE_ID, SECRET_PLACE_LOCATION_FIX))
    if le_rex:
        fixes.append((REX_VENUE_ID, REX_LOCATION_FIX))
    fixes.extend((v, NEW_REFERENCE_GEO_SOURCES[v]["patch"])
                 for v in sorted(set(extra_venues)))
    for venue_id, patch in fixes:
        rows = [v for v in venues if v["id"] == venue_id]
        require(len(rows) == 1, "Salle historique absente : " + venue_id)
        rows[0].update(copy.deepcopy(patch))
    return venues


def validate_secret_place_location_correction(approvals, reference, today):
    """Require a signed, persistent, double-source correction for an existing venue."""
    corrections = approvals.get("referenceVenueCorrections", [])
    require(isinstance(corrections, list) and len(corrections) <= 6,
            "Corrections géographiques historiques non conformes")
    ids = [c.get("venueId") for c in corrections if isinstance(c, dict)]
    require(len(ids) == len(corrections)
            and len(set(ids)) == len(ids)
            and set(ids).issubset({SECRET_PLACE_VENUE_ID, REX_VENUE_ID} |
                                      set(NEW_REFERENCE_GEO_SOURCES)),
            "Corrections géographiques inattendues ou dupliquées")
    row = next((c for c in corrections if c["venueId"] == SECRET_PLACE_VENUE_ID), None)
    if row is None:
        return None
    require(isinstance(row, dict)
            and row.get("venueId") == SECRET_PLACE_VENUE_ID
            and row.get("reviewDecision") == "approved"
            and row.get("reviewedBy") == "independent-official-verifier"
            and row.get("venuePatch") == SECRET_PLACE_LOCATION_FIX,
            "Correction géographique non autorisée ou hors liste blanche")
    checked = norm_date(row.get("reviewedAt"))
    require(checked <= today and checked == dt.date(2026, 11, 2),
            "Revue géographique sans date validée")
    evidence = row.get("officialEvidence")
    require(isinstance(evidence, list) and len(evidence) == 2,
            "Adresse officielle et bâtiment OSM exigés séparément")
    expected = {
        "official-venue-address": (
            SECRET_PLACE_LOCATION_OFFICIAL, {"name", "address", "postalCode", "city"}),
        "openstreetmap-venue-way": (
            SECRET_PLACE_LOCATION_OSM, {"venueName", "coordinates"}),
    }
    require({p.get("proofType") for p in evidence if isinstance(p, dict)}
            == set(expected), "Preuves géographiques de nature non indépendante")
    for item in evidence:
        require(isinstance(item, dict), "Preuve de localisation mal formée")
        url, fields = expected[item["proofType"]]
        require(item.get("url") == url
                and item.get("checkedAt") == checked.isoformat()
                and fields.issubset(set(item.get("checkedFields") or [])),
                "Source officielle ou OSM incomplète ou remplacée")
    original = next((v for v in reference["venues"]
                     if v["id"] == SECRET_PLACE_VENUE_ID), None)
    require(original is not None
            and original["address"] == "25 rue Saint-Exupéry, ZI de la Lauze"
            and original["postalCode"] == "34430"
            and original["latitude"] == 43.5615
            and original["longitude"] == 3.8424,
            "L'emplacement initial n'est pas la référence préalablement auditée")
    return row


def validate_rex_location_correction(approvals, reference, today):
    """Require exact official GPS and independent tourism-office address."""
    corrections = approvals.get("referenceVenueCorrections", [])
    require(isinstance(corrections, list) and len(corrections) <= 6,
            "Liste géographique inattendue")
    rows = [c for c in corrections if isinstance(c, dict)
            and c.get("venueId") == REX_VENUE_ID]
    require(len(rows) <= 1, "Correction Le Rex en doublon")
    if not rows:
        return None
    row = rows[0]
    require(row.get("reviewDecision") == "approved"
            and row.get("reviewedBy") == "independent-official-verifier"
            and row.get("venuePatch") == REX_LOCATION_FIX,
            "Correction Rex non approuvée ou modifiée hors preuves")
    checked = norm_date(row.get("reviewedAt"))
    require(checked == dt.date(2026, 11, 3) and checked <= today,
            "Revue Le Rex absente ou postérieure à l'exécution")
    evidence = row.get("officialEvidence")
    require(isinstance(evidence, list) and len(evidence) == 2,
            "Site officiel GPS et Office de tourisme exigés")
    expected = {
        "official-venue-gps": (
            REX_LOCATION_OFFICIAL,
            {"name", "address", "postalCode", "city", "latitude", "longitude"}),
        "tourism-office-address": (
            REX_LOCATION_TOURISM, {"name", "address", "postalCode", "city"}),
    }
    require({p.get("proofType") for p in evidence if isinstance(p, dict)}
            == set(expected), "Sources géographiques Rex non indépendantes")
    for item in evidence:
        require(isinstance(item, dict), "Preuve Rex incorrecte")
        url, fields = expected[item["proofType"]]
        require(item.get("url") == url
                and item.get("checkedAt") == checked.isoformat()
                and fields.issubset(set(item.get("checkedFields") or [])),
                "Source Rex manquante, remplacée ou incomplète")
    original = next((v for v in reference["venues"] if v["id"] == REX_VENUE_ID), None)
    require(original is not None
            and original["name"] == "Le Rex"
            and original["city"] == "Toulouse"
            and original["address"] == "Adresse exacte à vérifier"
            and original["postalCode"] == "À vérifier"
            and original["latitude"] == 43.604
            and original["longitude"] == 1.444,
            "La salle Rex de référence a changé : revue nécessaire")
    return row


# Precisely one documented exception for a historic incomplete bill.
# The 127 original records remain untouched in concerts-reference.json.
# Årabrot is already among the reference artists.
LEGACY_LINEUP_ID = "go-c-20261212-nantes-lost-in-kyiv"
LEGACY_LINEUP_SOURCE = "https://www.leferrailleur.fr/evenement/lost-in-kyiv/5307"
LEGACY_LINEUP_PATCH = {
    "title": "Lost in Kyiv + Årabrot",
    "artistIds": ["lost-in-kyiv", "arabrot"],
    "lastVerified": "2026-11-02",
}
LEGACY_LINEUP_HISTORY = {
    "date": "2026-11-02",
    "change": "Årabrot ajouté à l'affiche après relecture du détail officiel Le Ferrailleur",
}


def legacy_corrected_events(reference):
    events = copy.deepcopy(reference["events"])
    rows = [x for x in events if x["id"] == LEGACY_LINEUP_ID]
    require(len(rows) == 1, "Fiche historique Lost in Kyiv absente")
    original = rows[0]
    require(original["artistIds"] == ["lost-in-kyiv"]
            and original["title"] == "Lost in Kyiv"
            and original["date"] == "2026-12-12"
            and original["venueId"] == "le-ferrailleur-nantes"
            and original["officialUrl"] == LEGACY_LINEUP_SOURCE
            and "arabrot" in {a["id"] for a in reference["artists"]},
            "La correction ne correspond pas au référentiel immuable")
    original.update(copy.deepcopy(LEGACY_LINEUP_PATCH))
    original["history"].append(copy.deepcopy(LEGACY_LINEUP_HISTORY))
    return events


# Two strictly documented corrections of original reference events.
# Calendar cards displayed opening-of-doors times, not musical starts.
CARGO_REFERENCE_TIME_FIXES = {
    "go-c-20261113-caen-psykup": {
        "expectedOriginal": {
            "title": "Psykup + 7Weeks", "date": "2026-11-13",
            "time": "20:00", "artistIds": ["psykup", "7weeks"],
            "venueId": "le-cargo-caen",
            "officialUrl": "https://lecargo.fr/programmation/concert/",
        },
        "officialUrl": "https://lecargo.fr/programmation/concert/psykup-7-weeks/",
        "doorTime": "20:00",
        "eventPatch": {
            "time": "20:30", "timeMeaning": "début du concert",
            "officialUrl": "https://lecargo.fr/programmation/concert/psykup-7-weeks/",
            "lastVerified": "2026-11-03",
        },
        "history": {
            "date": "2026-11-03",
            "change": ("Correction officielle Cargö : ouverture des portes 20h00, "
                       "début des concerts 20h30 ; fiche individuelle vérifiée."),
        },
    },
    "go-c-20261121-caen-vulves-assassines": {
        "expectedOriginal": {
            "title": "Vulves Assassines", "date": "2026-11-21",
            "time": "19:30", "artistIds": ["vulves-assassines"],
            "venueId": "le-cargo-caen",
            "officialUrl": "https://lecargo.fr/programmation/concert/",
        },
        "officialUrl": "https://lecargo.fr/programmation/concert/vulves-assassines/",
        "doorTime": "19:30",
        "eventPatch": {
            "time": "20:30", "timeMeaning": "début du concert",
            "officialUrl": "https://lecargo.fr/programmation/concert/vulves-assassines/",
            "lastVerified": "2026-11-03",
        },
        "history": {
            "date": "2026-11-03",
            "change": ("Correction officielle Cargö : ouverture des portes 19h30, "
                       "début des concerts 20h30 ; fiche individuelle vérifiée."),
        },
    },
}


def cargo_corrected_reference_events(reference, events, event_ids=()):
    """Apply only the signed, exact set of historical Cargö time fixes."""
    ids = set(event_ids)
    require(ids.issubset(CARGO_REFERENCE_TIME_FIXES),
            "Correction historique Cargö inconnue")
    fixed = copy.deepcopy(events)
    for event_id in sorted(ids):
        spec = CARGO_REFERENCE_TIME_FIXES[event_id]
        originals = [e for e in reference["events"] if e.get("id") == event_id]
        candidates = [e for e in fixed if e.get("id") == event_id]
        require(len(originals) == 1 and len(candidates) == 1
                and all(originals[0].get(k) == v for k, v in
                        spec["expectedOriginal"].items())
                and originals[0].get("timeMeaning") ==
                    "horaire affiché sur le calendrier officiel, nature exacte (portes ou début) non précisée",
                "Référence d'horaire du Cargö modifiée hors contrôle")
        row = candidates[0]
        expected_new = {**originals[0], **spec["eventPatch"],
                        "history": originals[0]["history"] + [spec["history"]]}
        require(row == originals[0] or row == expected_new,
                "Fiche Cargö déjà modifiée hors exception nominative")
        if row == originals[0]:
            row.update(copy.deepcopy(spec["eventPatch"]))
            row["history"].append(copy.deepcopy(spec["history"]))
    return fixed


def corrected_reference_event_state(reference, legacy=False, cargo_ids=()):
    """Generate only allowable combinations; leave the base reference untouched."""
    events = (legacy_corrected_events(reference) if legacy
              else copy.deepcopy(reference["events"]))
    return cargo_corrected_reference_events(reference, events, cargo_ids)


def validate_cargo_reference_time_corrections(approvals, reference, today):
    """Preserve independent, individual official evidence for both corrections."""
    rows = approvals.get("referenceEventTimeCorrections", [])
    require(isinstance(rows, list)
            and len(rows) <= len(CARGO_REFERENCE_TIME_FIXES),
            "Liste de corrections horaires historiques non conforme")
    ids = [r.get("eventId") if isinstance(r, dict) else None for r in rows]
    require(len(set(ids)) == len(ids)
            and set(ids).issubset(CARGO_REFERENCE_TIME_FIXES),
            "Doublon ou ID de correction horaire non autorisé")
    accepted = {}
    for row in rows:
        event_id = row["eventId"]
        spec = CARGO_REFERENCE_TIME_FIXES[event_id]
        checked = norm_date(row.get("reviewedAt"))
        require(row.get("reviewDecision") == "approved"
                and row.get("reviewedBy") == "independent-official-verifier"
                and checked == dt.date(2026, 11, 3) and checked <= today
                and row.get("eventPatch") == spec["eventPatch"],
                "Modification horaire non approuvée ou hors liste blanche")
        proofs = row.get("officialEvidence")
        require(isinstance(proofs, list) and len(proofs) == 1
                and isinstance(proofs[0], dict),
                "Preuve officielle individuelle Cargö manquante")
        proof = proofs[0]
        require(proof.get("url") == spec["officialUrl"]
                and proof.get("proofType") == "official-venue-detail"
                and proof.get("checkedAt") == checked.isoformat()
                and {"artists", "date", "venue", "doorTime",
                     "concertStartTime"}.issubset(set(
                         proof.get("checkedFields") or []))
                and proof.get("doorTimeConfirmed") == spec["doorTime"]
                and proof.get("concertStartTimeConfirmed") == "20:30",
                "Preuve horaires portes/début insuffisante ou remplacée")
        cargo_corrected_reference_events(reference, reference["events"], (event_id,))
        accepted[event_id] = row
    return accepted


def validate_legacy_correction(approvals, reference, today):
    corrections = approvals.get("referenceCorrections", [])
    require(isinstance(corrections, list) and len(corrections) <= 1,
            "Dossier de correction historique non conforme")
    if not corrections:
        return None
    c = corrections[0]
    require(isinstance(c, dict) and c.get("eventId") == LEGACY_LINEUP_ID
            and c.get("reviewDecision") == "approved"
            and c.get("reviewedBy") == "independent-official-verifier"
            and c.get("eventPatch") == LEGACY_LINEUP_PATCH,
            "Modification historique non approuvée ou hors liste blanche")
    day = norm_date(c.get("reviewedAt"))
    require(day <= today and day == dt.date(2026, 11, 2),
            "Vérification du changement historique invalide")
    evidence = c.get("officialEvidence")
    require(isinstance(evidence, list) and len(evidence) == 1,
            "Preuve officielle unitaire obligatoire")
    p = evidence[0]
    require(isinstance(p,dict) and p.get("url") == LEGACY_LINEUP_SOURCE
            and p.get("proofType") == "official-venue-detail"
            and p.get("checkedAt") == day.isoformat()
            and {"artists","date","venue","startTime"}.issubset(
                set(p.get("checkedFields") or [])),
            "Fiche officielle non vérifiée pour la correction")
    legacy_corrected_events(reference)
    return c




def require(check, message):
    if not check:
        raise ValueError(message)


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    return " ".join(re.findall(r"[a-z0-9]+", value.encode("ascii", "ignore").decode()))


def read_approvals(token):
    require(bool(token), "Jeton privé de lecture absent")
    req = Request(APPROVAL_URL, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "User-Agent": "GrossesOndesConcertsCloud/1.0"
    })
    with urlopen(req, timeout=18) as response:
        require(response.status == 200, "Approbations privées indisponibles")
        payload = json.load(response)
    require(payload.get("encoding") == "base64", "Format réponse GitHub inattendu")
    return json.loads(base64.b64decode(payload["content"]).decode("utf-8"))


def validate_catalogue(data):
    require(data.get("schemaVersion") == 1 and
            data.get("mode") == "preview-public-unlisted",
            "Schéma ou visibilité du catalogue non conforme")
    for kind in ("events", "artists", "venues"):
        items = data.get(kind)
        require(isinstance(items, list) and
                len(items) == len({x.get("id") for x in items}) and
                all(isinstance(x.get("id"), str) and x["id"] for x in items),
                "IDs absents ou doublés dans " + kind)
    venue_ids = {x["id"] for x in data["venues"]}
    artist_ids = {x["id"] for x in data["artists"]}
    for event in data["events"]:
        require(
            event.get("venueId") in venue_ids and
            isinstance(event.get("artistIds"), list) and
            bool(event["artistIds"]) and
            all(a in artist_ids for a in event["artistIds"]) and
            isinstance(event.get("date"), str) and
            isinstance(event.get("officialUrl"), str) and
            event["officialUrl"].startswith("https://"),
            "Fiche concert invalide : " + str(event.get("id"))
        )


def protect_reference(reference, current):
    validate_catalogue(reference)
    validate_catalogue(current)
    for kind in ("events", "venues", "artists"):
        initial = reference[kind]
        now = current[kind]
        require(len(now) >= len(initial),
                "Référence immuable modifiée ou supprimée : " + kind)
        if kind == "events":
            # The only allowed states: original / signed Lost in Kyiv bill,
            # combined independently with either of the two exact time fixes.
            cargo_ids = tuple(sorted(CARGO_REFERENCE_TIME_FIXES))
            permitted = []
            for legacy in (False, True):
                for mask in range(1 << len(cargo_ids)):
                    chosen = tuple(event_id for i, event_id in enumerate(cargo_ids)
                                   if mask & (1 << i))
                    permitted.append(corrected_reference_event_state(
                        reference, legacy=legacy, cargo_ids=chosen))
            require(now[:len(initial)] in permitted,
                    "Concert historique modifié hors exceptions nominatives vérifiées")
        elif kind == "venues":
            # Allow only the two exact, documented geographic correction states.
            # The original 53 venues are never rewritten in the baseline JSON.
            # All and only individually reviewed historic pin combinations are
            # recognized (five named corrections plus immutable original).
            extras = tuple(sorted(NEW_REFERENCE_GEO_SOURCES))
            allowed = [initial]
            for secret in (False, True):
                for rex in (False, True):
                    for mask in range(1 << len(extras)):
                        active = tuple(v for i, v in enumerate(extras)
                                       if mask & (1 << i))
                        allowed.append(corrected_reference_venues(
                            reference, secret_place=secret, le_rex=rex,
                            extra_venues=active))
            require(now[:len(initial)] in allowed,
                    "Salle initiale modifiée hors correction géographique approuvée")
        else:
            require(now[:len(initial)] == initial,
                    "Référence immuable modifiée ou supprimée : " + kind)
    require(all(current.get(k) == reference.get(k)
                for k in ("schemaVersion", "mode", "dataPolicy")),
            "Métadonnées de sécurité altérées")
    require(len(reference["events"]) == 127 and
            len(reference["venues"]) == 53 and
            len(reference["artists"]) == 193,
            "Référence initiale inattendue")


def norm_date(value):
    require(isinstance(value, str) and
            re.fullmatch(r"20\d{2}-\d{2}-\d{2}", value),
            "Date ISO invalide")
    return dt.date.fromisoformat(value)


def validate_venue_approval(row, today):
    """No generic coordinates, no inferred location and no unreviewed venue."""
    require(isinstance(row, dict) and row.get("reviewDecision") == "approved"
            and row.get("reviewedBy") == "independent-official-verifier",
            "Salle non approuvée indépendamment")
    venue = row.get("venue")
    require(isinstance(venue, dict) and venue.get("id") in PILOT_VENUES,
            "Salle non agréée dans la liste blanche")
    approved = PILOT_VENUES[venue["id"]]
    expected = approved["venue"]
    require(venue == expected and set(venue) == set(expected),
            "Coordonnées, identité ou adresse de salle altérées")
    checked = norm_date(row.get("reviewedAt"))
    require(checked <= today, "Vérification de salle datée dans le futur")
    evidence = row.get("officialEvidence")
    require(isinstance(evidence, list) and len(evidence) == 2,
            "Deux preuves indépendantes exigées pour une nouvelle salle")
    first = next((x for x in evidence if isinstance(x, dict) and
                  x.get("url") == approved["officialUrl"] and
                  x.get("proofType") == "official-venue-address"), None)
    geo = next((x for x in evidence if isinstance(x, dict) and
                x.get("url") == approved["locationUrl"] and
                x.get("proofType") == approved.get(
                    "locationProofType","openstreetmap-venue-node")), None)
    require(first is not None and geo is not None,
            "Source officielle ou repère OpenStreetMap absent")
    for source, fields in ((first, {"name", "address", "postalCode", "city"}),
                           (geo, {"venueName", "coordinates"})):
        require(source.get("checkedAt") == checked.isoformat()
                and fields.issubset(set(source.get("checkedFields") or [])),
                "Preuve de salle non datée ou incomplète")
    require(venue["geoSource"] == approved["locationUrl"]
            and isinstance(venue["latitude"], (float, int))
            and isinstance(venue["longitude"], (float, int)),
            "Position du lieu non sourcée")
    return copy.deepcopy(venue)


# Atabal Biarritz: three exact first-party punk/hardcore concert bills.
# Date and artists verified on individual official pages and official calendar.
# No start time inferred from the untitled 20H30 header.
ATABAL_VERIFIED = {
    "go-c-20261128-biarritz-frankie-witch-fingers": {
        "title": "Frankie and the Witch Fingers + Iguana Death Cult + Mafia Sofa",
        "date": "2026-11-28",
        "time": None,
        "artistIds": [
            "frankie-and-the-witch-fingers",
            "iguana-death-cult",
            "mafia-sofa"
        ],
        "newArtistIds": [
            "mafia-sofa"
        ],
        "genres": [
            "Punk"
        ],
        "officialUrl": "https://www.atabal-biarritz.fr/agenda/concerts/frankie-and-the-witch-fingers-mafia-sofa-samedi-28-novembre-2026/"
    },
    "go-c-20261211-biarritz-anestesia-horzdun": {
        "title": "Anestesia + Horzdun",
        "date": "2026-12-11",
        "time": None,
        "artistIds": [
            "anestesia",
            "horzdun"
        ],
        "newArtistIds": [
            "anestesia",
            "horzdun"
        ],
        "genres": [
            "Hardcore",
            "Sludge Metal"
        ],
        "officialUrl": "https://www.atabal-biarritz.fr/agenda/concerts/anestesia-erantzun-30-urte-horzdun-vendredi-11-decembre-2026/"
    },
    "go-c-20270514-biarritz-burning-heads": {
        "title": "Burning Heads + Not Scientists + The Dead Krazukies",
        "date": "2027-05-14",
        "time": None,
        "artistIds": [
            "burning-heads",
            "not-scientists",
            "the-dead-krazukies"
        ],
        "newArtistIds": [
            "burning-heads",
            "not-scientists",
            "the-dead-krazukies"
        ],
        "genres": [
            "Punk Rock"
        ],
        "officialUrl": "https://www.atabal-biarritz.fr/agenda/concerts/burning-heads-not-scientists-dead-krazukies-vendredi-14-mai-2027/"
    }
}

# Hydrophone, Lorient: exact first-party metalcore bill, full year independently
# checked with the authorized ticket distributor; never infer year from SPIP.
HYDROPHONE_VERIFIED = {
    "go-c-20270210-lorient-revnoir-ice-sealed-eyes": {
        "title": "Revnoir + Ice Sealed Eyes",
        "date": "2027-02-10",
        "time": "20:00",
        "artistIds": [
            "revnoir",
            "ice-sealed-eyes"
        ],
        "newArtistIds": [],
        "genres": [
            "Metalcore"
        ],
        "venueId": "hydrophone-lorient",
        "officialUrl": "https://hydrophone.fr/REVNOIR-ICE-SEALED-EYES.html",
        "secondaryProofType": "authorized-ticket-distributor-full-date",
        "secondaryUrl": "https://www.fnacspectacles.com/event/revnoir-sometimes-i-feel-you-sometimes-i-dont-tour-hydrophone-lorient-21627359/"
    }
}

# La Carène Brest: only these 2 nominal, non-festival first-party concert bills.
# The official SPIP agenda and first-party detail must both be checked.
CARENE_VERIFIED = {
    # Approbations privées GrossesOndes #124, revues nominatives 03/11/2026.
    # Les deux concerts doivent être prouvés séparément par la fiche officielle
    # et la programmation de La Carène, jamais par une recherche générique.
    "go-c-20261209-brest-fff-howlin-jaws": {
        "title": "FFF + Howlin’ Jaws",
        "date": "2026-12-09",
        "time": None,
        "artistIds": ["fff", "howlin-jaws"],
        "genres": ["Rock", "Funk Rock"],
        "officialUrl": "https://www.lacarene.fr/fff-howlin-jaws.html",
        "newArtistIds": ["fff"],
    },
    "go-c-20270402-brest-les-fatals-picards": {
        "title": "Les Fatals Picards",
        "date": "2027-04-02",
        "time": None,
        "artistIds": ["les-fatals-picards"],
        "genres": ["Rock"],
        "officialUrl": "https://www.lacarene.fr/les-fatals-picards.html",
        "newArtistIds": ["les-fatals-picards"],
    },
    "go-c-20261107-brest-dame-area-tact": {
        "title": "Dame Area + Tact",
        "date": "2026-11-07",
        "time": "21:00",
        "artistIds": [
            "dame-area",
            "tact"
        ],
        "genres": [
            "Post Punk"
        ],
        "officialUrl": "https://www.lacarene.fr/dame-area-tact.html",
        "newArtistIds": [
            "dame-area",
            "tact"
        ]
    },
    "go-c-20261128-brest-mary-bell-prisonnier-du-temps": {
        "title": "Mary Bell + Prisonnier du temps",
        "date": "2026-11-28",
        "time": "21:00",
        "artistIds": [
            "mary-bell",
            "prisonnier-du-temps"
        ],
        "genres": [
            "Punk"
        ],
        "officialUrl": "https://www.lacarene.fr/mary-bell-prisonnier-du-temps.html",
        "newArtistIds": [
            "mary-bell",
            "prisonnier-du-temps"
        ]
    }
}

TETRIS_VERIFIED = {
    # Quatre concerts nominativement approuvés dans GrossesOndes #131.
    # Le Tetris n'affiche pas l'année sur ses fiches individuelles :
    # chaque millésime est établi par la preuve secondaire exacte.
    "go-c-20261113-lehavre-edging-zonbi": {
        "title": "Edging + Zonbi",
        "date": "2026-11-13",
        "time": None,
        "artistIds": ["edging", "zonbi"],
        "artistNames": ["Edging", "Zonbi"],
        "newArtistIds": ["edging", "zonbi"],
        "genres": ["Punk Rock", "Punk Jazz"],
        "officialUrl": "https://letetris.fr/agenda/edging-zonbi",
        "secondaryUrl": "https://www.relikto.com/event/edging/",
        "secondaryProofType": "event-partner-full-date",
    },
    "go-c-20261127-lehavre-fff-metro-verlaine": {
        "title": "FFF + Metro Verlaine",
        "date": "2026-11-27",
        "time": None,
        "artistIds": ["fff", "metro-verlaine"],
        "artistNames": ["FFF", "Metro Verlaine"],
        "newArtistIds": ["metro-verlaine"],
        "genres": ["Funk Rock", "Rock"],
        "officialUrl": "https://letetris.fr/agenda/fff",
        "secondaryUrl": "https://www.lehavre-etretat-tourisme.com/fr/fiche/le-havre/concert-fff--metro-verlaine_TFOFMANOR076V529ATF/",
        "secondaryProofType": "official-tourism-full-date",
    },
    "go-c-20261205-lehavre-coffin-belek": {
        "title": "C.O.F.F.I.N. + Belek",
        "date": "2026-12-05",
        "time": None,
        "artistIds": ["coffin", "belek"],
        "artistNames": ["C.O.F.F.I.N.", "Belek"],
        "newArtistIds": ["coffin", "belek"],
        "genres": ["Rock", "Hardcore"],
        "officialUrl": "https://letetris.fr/agenda/coffin",
        "secondaryUrl": "https://www.infoconcert.com/salle/le-tetris-la-halle-fort-de-tourneville-31214/concerts",
        "secondaryProofType": "independent-concert-calendar-full-date",
    },
    "go-c-20261212-lehavre-the-inspector-cluzo-grimskunk": {
        "title": "The Inspector Cluzo + GrimSkunk",
        "date": "2026-12-12",
        "time": None,
        "artistIds": ["the-inspector-cluzo", "grimskunk"],
        "artistNames": ["The Inspector Cluzo", "GrimSkunk"],
        "newArtistIds": ["grimskunk"],
        "genres": ["Rock", "Punk Rock"],
        "officialUrl": "https://letetris.fr/agenda/inspector-cluzo",
        "secondaryUrl": "https://theinspectorcluzo.com/ja/news/french-tour-part-2/",
        "secondaryProofType": "official-artist-tour-full-date",
    },
}

TEMPS_MACHINE_VERIFIED = {
    # Une seule affiche approuvée indépendamment dans GrossesOndes #130.
    "go-c-20261119-joue-les-tours-birdstone-marave": {
        "title": "Birdstone + Marave",
        "date": "2026-11-19",
        "time": None,
        "artistIds": ["birdstone", "marave"],
        "artistNames": ["Birdstone", "Marave"],
        "newArtistIds": ["birdstone", "marave"],
        "genres": ["Progressive Rock", "Punk"],
        "officialUrl": "https://letempsmachine.com/agenda/release-party-birdstone-marave",
    },
}

CHATODO_VERIFIED = {
    # Fiches signées GrossesOndes #127, 03/11/2026. Aucune extension implicite.
    "go-c-20261105-blois-the-flying-bones": {
        "title": "The Flying Bones",
        "date": "2026-11-05",
        "time": None,
        "artistIds": ["the-flying-bones"],
        "artistNames": ["The Flying Bones"],
        "newArtistIds": ["the-flying-bones"],
        "genres": ["Garage Rock", "Psych Rock"],
        "officialUrl": "https://chatodo.com/agenda/evenement/the-flying-bones/",
    },
    "go-c-20261112-blois-wicked-vessel": {
        "title": "Wicked Vessel + Ultramoderne",
        "date": "2026-11-12",
        "time": None,
        "artistIds": ["wicked-vessel", "ultramoderne"],
        "artistNames": ["Wicked Vessel", "Ultramoderne"],
        "newArtistIds": ["wicked-vessel", "ultramoderne"],
        "genres": ["Post Rock", "Electro Clash"],
        "officialUrl": "https://chatodo.com/agenda/evenement/wicked-vessel-ultramoderne/",
    },
    "go-c-20261203-blois-7weeks": {
        "title": "7Weeks",
        "date": "2026-12-03",
        "time": None,
        "artistIds": ["7weeks"],
        "artistNames": ["7Weeks"],
        "newArtistIds": [],
        "genres": ["Heavy Rock"],
        "officialUrl": "https://chatodo.com/agenda/evenement/7-weeks/",
    },
}

# Six exact bills confirmed from first-party individual Rocher de Palmer pages on 2026-11-02.
# These are reviewed cases, not an open-ended permission for the venue.
ROCHER_PALMER_VERIFIED = {
    "go-c-20261107-cenon-gwendoline": {
        "title": "Gwendoline",
        "date": "2026-11-07",
        "artistIds": [
            "gwendoline"
        ],
        "genres": [
            "Post Punk"
        ],
        "time": "20:30",
        "officialUrl": "https://lerocherdepalmer.fr/agenda/gwendoline"
    },
    "go-c-20261121-cenon-tagada-jones": {
        "title": "Tagada Jones + Les Tambours du Bronx",
        "date": "2026-11-21",
        "artistIds": [
            "tagada-jones",
            "les-tambours-du-bronx"
        ],
        "genres": [
            "Punk Hardcore",
            "Metal industriel"
        ],
        "time": "20:30",
        "officialUrl": "https://lerocherdepalmer.fr/agenda/tagada-jones-les-tambours-du-bronx"
    },
    "go-c-20270117-cenon-rhapsody-of-fire": {
        "title": "Rhapsody of Fire + Serious Black",
        "date": "2027-01-17",
        "artistIds": [
            "rhapsody-of-fire",
            "serious-black"
        ],
        "genres": [
            "Metal"
        ],
        "time": "19:00",
        "officialUrl": "https://lerocherdepalmer.fr/agenda/rhapsody-fire-serious-black"
    },
    "go-c-20270210-cenon-ugly-kid-joe": {
        "title": "Ugly Kid Joe",
        "date": "2027-02-10",
        "artistIds": [
            "ugly-kid-joe"
        ],
        "genres": [
            "Hard Rock"
        ],
        "time": "20:30",
        "officialUrl": "https://lerocherdepalmer.fr/agenda/ugly-kid-joe"
    },
    "go-c-20270306-cenon-mol": {
        "title": "MØL",
        "date": "2027-03-06",
        "artistIds": [
            "m-l"
        ],
        "genres": [
            "Metal"
        ],
        "time": "20:30",
        "officialUrl": "https://lerocherdepalmer.fr/agenda/mol"
    },
    "go-c-20270324-cenon-die-arzte": {
        "title": "Die Ärzte",
        "date": "2027-03-24",
        "artistIds": [
            "die-arzte"
        ],
        "genres": [
            "Punk Rock"
        ],
        "time": "20:00",
        "officialUrl": "https://lerocherdepalmer.fr/agenda/die-arzte"
    },
    "go-c-20270326-cenon-uuhai": {
        "title": "UUHAI + ACYL",
        "date": "2027-03-26",
        "artistIds": [
            "uuhai",
            "acyl"
        ],
        "genres": [
            "Folk Metal"
        ],
        "time": "19:00",
        "officialUrl": "https://lerocherdepalmer.fr/agenda/uuhai"
    }
}

# Strict one-by-one set of nine first-party La Laiterie concerts audited 2026-11-03.
# The public calendar gives door-opening times, NOT a guaranteed concert start.
# The location remains a venue of the historic catalogue (separate geo audit).
LAITERIE_OFFICIAL_VERIFIED = json.loads(r'''{
  "go-c-20270205-strasbourg-revnoir-ice-sealed-eyes": {
    "title": "Revnoir + Ice Sealed Eyes",
    "date": "2027-02-05",
    "artistIds": [
      "revnoir",
      "ice-sealed-eyes"
    ],
    "artistNames": [
      "Revnoir",
      "Ice Sealed Eyes"
    ],
    "genres": [
      "Metalcore"
    ],
    "time": null,
    "officialUrl": "https://www.artefact.org/la-laiterie/evenements/revnoir-ice-sealed-eyes/",
    "calendarUrl": "https://www.artefact.org/evenements/page/3/"
  },
  "go-c-20270209-strasbourg-enslaved-solstafir": {
    "title": "Enslaved + Sólstafir + Gaahls Wyrd",
    "date": "2027-02-09",
    "artistIds": [
      "enslaved",
      "solstafir",
      "gaahls-wyrd"
    ],
    "artistNames": [
      "Enslaved",
      "Sólstafir",
      "Gaahls Wyrd"
    ],
    "genres": [
      "Black Metal",
      "Metal progressif"
    ],
    "time": null,
    "officialUrl": "https://www.artefact.org/la-laiterie/evenements/enslaved-solstafir-gaahls-wyrd/",
    "calendarUrl": "https://www.artefact.org/evenements/page/3/"
  },
  "go-c-20270214-strasbourg-ugly-kid-joe": {
    "title": "Ugly Kid Joe",
    "date": "2027-02-14",
    "artistIds": [
      "ugly-kid-joe"
    ],
    "artistNames": [
      "Ugly Kid Joe"
    ],
    "genres": [
      "Hard Rock"
    ],
    "time": null,
    "officialUrl": "https://www.artefact.org/la-laiterie/evenements/ugly-kid-joe-2027/",
    "calendarUrl": "https://www.artefact.org/evenements/page/3/"
  },
  "go-c-20270216-strasbourg-eihwar-hindarfjall": {
    "title": "Eihwar + Hindarfjäll",
    "date": "2027-02-16",
    "artistIds": [
      "eihwar",
      "hindarfjall"
    ],
    "artistNames": [
      "Eihwar",
      "Hindarfjäll"
    ],
    "genres": [
      "Pagan Folk"
    ],
    "time": null,
    "officialUrl": "https://www.artefact.org/la-laiterie/evenements/eihwar-hindarfjall/",
    "calendarUrl": "https://www.artefact.org/evenements/page/3/"
  },
  "go-c-20270306-strasbourg-houle-can-bardd": {
    "title": "Houle + Cân Bardd + Galibot",
    "date": "2027-03-06",
    "artistIds": [
      "houle",
      "can-bardd",
      "galibot"
    ],
    "artistNames": [
      "Houle",
      "Cân Bardd",
      "Galibot"
    ],
    "genres": [
      "Black Metal"
    ],
    "time": null,
    "officialUrl": "https://www.artefact.org/la-laiterie/evenements/houle-2027/",
    "calendarUrl": "https://www.artefact.org/evenements/page/3/"
  },
  "go-c-20270309-strasbourg-cult-of-luna": {
    "title": "Cult of Luna + Bruit ≤ + Youth Code",
    "date": "2027-03-09",
    "artistIds": [
      "cult-of-luna",
      "bruit",
      "youth-code"
    ],
    "artistNames": [
      "Cult of Luna",
      "Bruit ≤",
      "Youth Code"
    ],
    "genres": [
      "Post-metal",
      "Sludge Metal"
    ],
    "time": null,
    "officialUrl": "https://www.artefact.org/la-laiterie/evenements/cult-of-luna-bruit-%E2%89%A4-youth-code/",
    "calendarUrl": "https://www.artefact.org/evenements/page/3/"
  },
  "go-c-20270316-strasbourg-die-arzte": {
    "title": "Die Ärzte",
    "date": "2027-03-16",
    "artistIds": [
      "die-arzte"
    ],
    "artistNames": [
      "Die Ärzte"
    ],
    "genres": [
      "Punk Rock"
    ],
    "time": null,
    "officialUrl": "https://www.artefact.org/la-laiterie/evenements/die-arzte-tour-de-france/",
    "calendarUrl": "https://www.artefact.org/evenements/page/4/"
  },
  "go-c-20270326-strasbourg-tagada-jones": {
    "title": "Tagada Jones + Les Tambours du Bronx",
    "date": "2027-03-26",
    "artistIds": [
      "tagada-jones",
      "les-tambours-du-bronx"
    ],
    "artistNames": [
      "Tagada Jones",
      "Les Tambours du Bronx"
    ],
    "genres": [
      "Punk Hardcore",
      "Metal"
    ],
    "time": null,
    "officialUrl": "https://www.artefact.org/la-laiterie/evenements/tagada-jones-les-tambours-du-bronx2027/",
    "calendarUrl": "https://www.artefact.org/evenements/page/4/"
  },
  "go-c-20270909-strasbourg-eisbrecher": {
    "title": "Eisbrecher",
    "date": "2027-09-09",
    "artistIds": [
      "eisbrecher"
    ],
    "artistNames": [
      "Eisbrecher"
    ],
    "genres": [
      "Metal industriel"
    ],
    "time": null,
    "officialUrl": "https://www.artefact.org/la-laiterie/evenements/eisbrecher-2027/",
    "calendarUrl": "https://www.artefact.org/evenements/page/5/"
  },
  "go-c-20261205-strasbourg-lebanon-hanover": {
    "title": "Lebanon Hanover + Clan of Xymox + Kas Product",
    "date": "2026-12-05",
    "artistIds": [
      "lebanon-hanover",
      "clan-of-xymox",
      "kas-product"
    ],
    "artistNames": [
      "Lebanon Hanover",
      "Clan of Xymox",
      "Kas Product"
    ],
    "genres": [
      "Post Punk"
    ],
    "time": null,
    "officialUrl": "https://www.artefact.org/la-laiterie/evenements/lebanon-hanover-clan-of-xymox-guest/",
    "calendarUrl": "https://www.artefact.org/evenements/page/2/",
    "newArtists": [
      {
        "id": "lebanon-hanover",
        "name": "Lebanon Hanover"
      },
      {
        "id": "clan-of-xymox",
        "name": "Clan of Xymox"
      },
      {
        "id": "kas-product",
        "name": "Kas Product"
      }
    ]
  },
  "go-c-20261218-strasbourg-magma": {
    "title": "Magma",
    "date": "2026-12-18",
    "artistIds": [
      "magma"
    ],
    "artistNames": [
      "Magma"
    ],
    "genres": [
      "Rock progressif"
    ],
    "time": null,
    "officialUrl": "https://www.artefact.org/la-laiterie/evenements/magma2027/",
    "calendarUrl": "https://www.artefact.org/evenements/page/2/",
    "newArtists": [
      {
        "id": "magma",
        "name": "Magma"
      }
    ]
  },
  "go-c-20270224-strasbourg-cachemire": {
    "title": "Cachemire + La Phaze + Bob's Not Dead",
    "date": "2027-02-24",
    "artistIds": [
      "cachemire",
      "la-phaze",
      "bobs-not-dead"
    ],
    "artistNames": [
      "Cachemire",
      "La Phaze",
      "Bob's Not Dead"
    ],
    "genres": [
      "Punk Rock"
    ],
    "time": null,
    "officialUrl": "https://www.artefact.org/la-laiterie/evenements/cachemire-la-phaze-bobs-not-dead/",
    "calendarUrl": "https://www.artefact.org/evenements/page/3/",
    "newArtists": [
      {
        "id": "cachemire",
        "name": "Cachemire"
      },
      {
        "id": "la-phaze",
        "name": "La Phaze"
      },
      {
        "id": "bobs-not-dead",
        "name": "Bob's Not Dead"
      }
    ]
  },
  "go-c-20270404-strasbourg-igorrr": {
    "title": "Igorrr + Secret Chiefs 3 + Fange",
    "date": "2027-04-04",
    "artistIds": [
      "igorrr",
      "secret-chiefs-3",
      "fange"
    ],
    "artistNames": [
      "Igorrr",
      "Secret Chiefs 3",
      "Fange"
    ],
    "genres": [
      "Metal expérimental"
    ],
    "time": null,
    "officialUrl": "https://www.artefact.org/la-laiterie/evenements/igorrr-secret-chiefs-3-fange/",
    "calendarUrl": "https://www.artefact.org/evenements/page/4/",
    "newArtists": [
      {
        "id": "igorrr",
        "name": "Igorrr"
      },
      {
        "id": "secret-chiefs-3",
        "name": "Secret Chiefs 3"
      },
      {
        "id": "fange",
        "name": "Fange"
      }
    ]
  },
  "go-c-20270422-strasbourg-the-pineapple-thief": {
    "title": "The Pineapple Thief",
    "date": "2027-04-22",
    "artistIds": [
      "the-pineapple-thief"
    ],
    "artistNames": [
      "The Pineapple Thief"
    ],
    "genres": [
      "Rock progressif"
    ],
    "time": null,
    "officialUrl": "https://www.artefact.org/la-laiterie/evenements/the-pineapple-thief-far-and-wide-european-tour-2027/",
    "calendarUrl": "https://www.artefact.org/evenements/page/4/",
    "newArtists": [
      {
        "id": "the-pineapple-thief",
        "name": "The Pineapple Thief"
      }
    ]
  },
  "go-c-20270217-strasbourg-sleeping-with-sirens": {
    "title": "Sleeping With Sirens + Arm's Length + Like Roses",
    "date": "2027-02-17",
    "artistIds": [
      "sleeping-with-sirens",
      "arms-length",
      "like-roses"
    ],
    "artistNames": [
      "Sleeping With Sirens",
      "Arm's Length",
      "Like Roses"
    ],
    "genres": [
      "Post-hardcore",
      "Pop Punk"
    ],
    "time": null,
    "officialUrl": "https://www.artefact.org/la-laiterie/evenements/sleeping-with-sirens/",
    "calendarUrl": "https://www.artefact.org/evenements/page/3/",
    "organizerUrl": "https://www.livenation.com/event/intl_1673680/sleeping-with-sirens-an-ending-in-itself-tour",
    "newArtists": [
      {
        "id": "sleeping-with-sirens",
        "name": "Sleeping With Sirens"
      },
      {
        "id": "arms-length",
        "name": "Arm's Length"
      },
      {
        "id": "like-roses",
        "name": "Like Roses"
      }
    ]
  }
}''')


# Three independently rechecked first-party Bikini concert bills.
# All times on these listings are DOORS, never concert start times.
LAITERIE_SECOND_WAVE_VERIFIED = json.loads(r'''{
  "go-c-20270226-strasbourg-dynamite-shakers": {
    "title": "Dynamite Shakers + Johnny Mafia",
    "date": "2027-02-26",
    "artistIds": [
      "dynamite-shakers",
      "johnny-mafia"
    ],
    "artistNames": [
      "Dynamite Shakers",
      "Johnny Mafia"
    ],
    "newArtists": [
      {
        "id": "dynamite-shakers",
        "name": "Dynamite Shakers"
      }
    ],
    "genres": [
      "Garage Rock",
      "Indie Rock"
    ],
    "time": null,
    "officialUrl": "https://www.artefact.org/la-laiterie/evenements/dynamite-shakers-johnny-mafia/",
    "calendarUrl": "https://www.artefact.org/la-laiterie/programmation/page/3/"
  },
  "go-c-20270428-strasbourg-howlin-jaws": {
    "title": "Howlin' Jaws + Komodor",
    "date": "2027-04-28",
    "artistIds": [
      "howlin-jaws",
      "komodor"
    ],
    "artistNames": [
      "Howlin' Jaws",
      "Komodor"
    ],
    "newArtists": [
      {
        "id": "howlin-jaws",
        "name": "Howlin' Jaws"
      }
    ],
    "genres": [
      "Rock psychédélique",
      "Rock"
    ],
    "time": null,
    "officialUrl": "https://www.artefact.org/la-laiterie/evenements/howlin-jaws-komodor/",
    "calendarUrl": "https://www.artefact.org/la-laiterie/programmation/page/4/"
  },
  "go-c-20270514-strasbourg-didier-super-metal": {
    "title": "Didier Super Métal",
    "date": "2027-05-14",
    "artistIds": [
      "didier-super-metal"
    ],
    "artistNames": [
      "Didier Super Métal"
    ],
    "newArtists": [
      {
        "id": "didier-super-metal",
        "name": "Didier Super Métal"
      }
    ],
    "genres": [
      "Rock",
      "Metal"
    ],
    "time": null,
    "officialUrl": "https://www.artefact.org/la-laiterie/evenements/didier-super-metal/",
    "calendarUrl": "https://www.artefact.org/la-laiterie/programmation/page/4/"
  },
  "go-c-20271010-strasbourg-europe": {
    "title": "Europe",
    "date": "2027-10-10",
    "artistIds": [
      "europe"
    ],
    "artistNames": [
      "Europe"
    ],
    "newArtists": [
      {
        "id": "europe",
        "name": "Europe"
      }
    ],
    "genres": [
      "Hard Rock"
    ],
    "time": null,
    "officialUrl": "https://www.artefact.org/la-laiterie/evenements/europe-2027/",
    "calendarUrl": "https://www.artefact.org/la-laiterie/programmation/page/5/"
  }
}''')

BIKINI_OFFICIAL_VERIFIED = {
    "go-c-20261111-toulouse-chameleons": {
        "title": "Chameleons + Agonal Gasps",
        "date": "2026-11-11",
        "artistIds": ["chameleons", "agonal-gasps"],
        "artistNames": ["Chameleons", "Agonal Gasps"],
        "newArtists": [{"id": "chameleons", "name": "Chameleons"},
                       {"id": "agonal-gasps", "name": "Agonal Gasps"}],
        "genres": ["Post-Punk", "Rock alternatif"],
        "time": None,
        "officialUrl": "https://lebikini.com/2026/11/11/chameleons",
    },
    "go-c-20261113-toulouse-tagada-jones": {
        "title": "Tagada Jones + Les Tambours du Bronx",
        "date": "2026-11-13",
        "artistIds": ["tagada-jones", "les-tambours-du-bronx"],
        "artistNames": ["Tagada Jones", "Les Tambours du Bronx"],
        "newArtists": [],
        "genres": ["Punk", "Hardcore"],
        "time": None,
        "officialUrl": "https://lebikini.com/2026/11/13/tagada-jones-les-tambours-du-bronx",
    },
    "go-c-20261114-toulouse-beast-in-black": {
        "title": "Beast in Black + Sonata Arctica + Frozen Crown",
        "date": "2026-11-14",
        "artistIds": ["beast-in-black", "sonata-arctica", "frozen-crown"],
        "artistNames": ["Beast in Black", "Sonata Arctica", "Frozen Crown"],
        "newArtists": [
            {"id": "beast-in-black", "name": "Beast in Black"},
            {"id": "sonata-arctica", "name": "Sonata Arctica"},
            {"id": "frozen-crown", "name": "Frozen Crown"},
        ],
        "genres": ["Heavy Metal"],
        "time": None,
        "officialUrl": "https://lebikini.com/2026/11/14/beast-in-black-sonata-arctica-frozen-crown",
    },
    "go-c-20261117-toulouse-slift": {
        "title": "Slift + Heeka",
        "date": "2026-11-17",
        "artistIds": ["slift", "heeka"],
        "artistNames": ["Slift", "Heeka"],
        "newArtists": [{"id": "heeka", "name": "Heeka"}],
        "genres": ["Post-rock", "Rock"],
        "time": None,
        "officialUrl": "https://lebikini.com/2026/11/17/slift",
    },
    "go-c-20261125-toulouse-marillion": {
        "title": "Marillion",
        "date": "2026-11-25",
        "artistIds": ["marillion"],
        "artistNames": ["Marillion"],
        "newArtists": [{"id": "marillion", "name": "Marillion"}],
        "genres": ["Rock progressif"],
        "time": None,
        "officialUrl": "https://lebikini.com/2026/11/25/marillion",
    },
    "go-c-20261126-toulouse-the-stranglers": {
        "title": "The Stranglers",
        "date": "2026-11-26",
        "artistIds": ["the-stranglers"],
        "artistNames": ["The Stranglers"],
        "newArtists": [{"id": "the-stranglers", "name": "The Stranglers"}],
        "genres": ["Rock"],
        "time": None,
        "officialUrl": "https://lebikini.com/2026/11/26/the-stranglers",
    },
    "go-c-20261129-toulouse-accept": {
        "title": "Accept \"50th Anniversary Tour\" + Dynazty + Enforcer",
        "date": "2026-11-29",
        "artistIds": ["accept", "dynazty", "enforcer"],
        "artistNames": ["Accept", "Dynazty", "Enforcer"],
        "newArtists": [],
        "genres": ["Heavy Metal"],
        "time": None,
        "officialUrl": "https://lebikini.com/2026/11/29/accept-50th-anniversary-tour-dynazty-tailgunner",
    },
}


# Four first-party gig bills, each verified against both an individual page and
# the venue's official listing. Old city-center pins are deliberately unchanged.
# The displayed event clock is not explicitly the live performance start.
ROCKSTORE_BLACKLAB_OFFICIAL_VERIFIED = {
    "go-c-20261119-montpellier-mass-hysteria": {
        "title": "Mass Hysteria",
        "date": "2026-11-19", "time": None,
        "venueId": "rockstore-montpellier",
        "artistIds": ["mass-hysteria"],
        "artistNames": ["Mass Hysteria"],
        "newArtists": [],
        "genres": ["Néo-Metal"],
        "officialUrl": "https://rockstore.fr/mass-hysteria-19-novembre-2026/",
        "calendarUrl": "https://rockstore.fr/concerts/",
    },
    "go-c-20261201-montpellier-shaarghot": {
        "title": "Shaârghot + Solitaris + Ghost Dance",
        "date": "2026-12-01", "time": None,
        "venueId": "rockstore-montpellier",
        "artistIds": ["shaarghot", "solitaris", "ghost-dance"],
        "artistNames": ["Shaârghot", "Solitaris", "Ghost Dance"],
        "newArtists": [],
        "genres": ["Metal industriel"],
        "officialUrl": "https://rockstore.fr/shaarghot-solitaris-ghost-dance-01-decembre-2026/",
        "calendarUrl": "https://rockstore.fr/concerts/",
    },
    "go-c-20270220-wasquehal-colour-haze": {
        "title": "Colour Haze + Smokemaster",
        "date": "2027-02-20", "time": None,
        "venueId": "the-black-lab-wasquehal",
        "artistIds": ["colour-haze", "smokemaster"],
        "artistNames": ["Colour Haze", "Smokemaster"],
        "newArtists": [
            {"id": "colour-haze", "name": "Colour Haze"},
            {"id": "smokemaster", "name": "Smokemaster"},
        ],
        "genres": ["Stoner Rock"],
        "officialUrl": "https://theblacklab.fr/agenda/colour-haze-smokemaster/",
        "calendarUrl": "https://theblacklab.fr/agenda/liste/page/2/",
    },
    "go-c-20270305-wasquehal-houle": {
        "title": "Houle + Cân Bardd + Galibot",
        "date": "2027-03-05", "time": None,
        "venueId": "the-black-lab-wasquehal",
        "artistIds": ["houle", "can-bardd", "galibot"],
        "artistNames": ["Houle", "Cân Bardd", "Galibot"],
        "newArtists": [],
        "genres": ["Black Metal"],
        "officialUrl": "https://theblacklab.fr/agenda/houle-can-bardd-galibot/",
        "calendarUrl": "https://theblacklab.fr/agenda/liste/page/2/",
    },
}

CARGO_VERIFIED = {
    # Le Cargö Caen: one independently checked official named event, no
    # extrapolation from the generic listing. Door time 19:30, musical
    # start explicitly announced as 20:30 on the detailed event page.
    "go-c-20261128-caen-fff-dj-bluff": {
        "title": "FFF + DJ Bluff",
        "date": "2026-11-28",
        "time": "20:30",
        "venueId": "le-cargo-caen",
        "artistIds": ["fff", "dj-bluff"],
        "artistNames": ["FFF", "DJ Bluff"],
        "newArtistIds": ["dj-bluff"],
        "genres": ["Funk Rock"],
        "officialUrl": "https://lecargo.fr/programmation/concert/fff/",
    },
}


ROUEN_DEATH_VALLEY_SIGNED = {
    # Official Le 106 concert detail + first-party full-year calendar,
    # both read independently on 03/11/2026. The displayed 20:00 is not
    # labelled the start of the music, therefore time must remain None.
    "go-c-20261121-rouen-death-valley-girls-bella-bizarre": {
        "title": "Death Valley Girls + Bella & the Bizarre",
        "date": "2026-11-21",
        "time": None,
        "venueId": "le-106-rouen",
        "artistIds": ["death-valley-girls", "bella-and-the-bizarre"],
        "genres": ["Proto-Punk", "Garage Punk"],
        "officialUrl": "https://le106.com/agenda/death-valley-girls-bella-bizarre",
        "calendarUrl": "https://le106.com/agenda",
    },
}


BBC_NORMANDY_VERIFIED = {
    # Official venue pages + the ticket distributor directly linked by BBC.
    # Advertised 20:00 is not labelled a concert-start, so time is None.
    "go-c-20270205-herouville-ugly-kid-joe": {
        "title": "Ugly Kid Joe",
        "date": "2027-02-05",
        "time": None,
        "venueId": "big-band-cafe-herouville",
        "artistIds": ["ugly-kid-joe"],
        "artistNames": ["Ugly Kid Joe"],
        "newArtistIds": [],
        "genres": ["Hard Rock"],
        "officialUrl": "https://bigbandcafe.com/ugly-kid-joe/",
        "ticketUrl": "https://billetterie.bigbandcafe.com/agenda/118-UGLY-KID-JOE?session=118",
    },
    "go-c-20270402-herouville-madam": {
        "title": "MADAM",
        "date": "2027-04-02",
        "time": None,
        "venueId": "big-band-cafe-herouville",
        "artistIds": ["madam"],
        "artistNames": ["MADAM"],
        "newArtistIds": ["madam"],
        "genres": ["Rock"],
        "officialUrl": "https://bigbandcafe.com/madam/",
        "ticketUrl": "https://billetterie.bigbandcafe.com/agenda/121-MADAM?session=121",
    },
}


ROUEN_ROCK_PAGED_VERIFIED = {
    # Le 106 official individual pages show artist/genre, while the official
    # paginated calendar supplies the FULL dates (year included). Printed
    # times are not proven musical starts. Two sold-out flags are recorded
    # in proofs, never interpreted as cancellations or invented start times.
    "go-c-20261210-rouen-the-sheepdogs-steve-hill": {
        "title":"The Sheepdogs + Steve Hill","date":"2026-12-10",
        "time":None,"venueId":"le-106-rouen",
        "artistIds":["the-sheepdogs","steve-hill"],
        "artistNames":["The Sheepdogs","Steve Hill"],
        "newArtistIds":["the-sheepdogs","steve-hill"],
        "genres":["Rock"],
        "officialUrl":"https://le106.com/agenda/sheepdogs",
        "calendarUrl":"https://le106.com/agenda?page=1",
    },
    "go-c-20270121-rouen-skip-the-use-mdns": {
        "title":"Skip The Use + MDNS","date":"2027-01-21",
        "time":None,"venueId":"le-106-rouen",
        "artistIds":["skip-the-use","mdns"],
        "artistNames":["Skip The Use","MDNS"],
        "newArtistIds":["skip-the-use","mdns"],
        "genres":["Rock"],
        "officialUrl":"https://le106.com/agenda/skip-use",
        "calendarUrl":"https://le106.com/agenda?page=1",
    },
    "go-c-20270126-rouen-editors-big-sleep": {
        "title":"Editors + Big Sleep","date":"2027-01-26",
        "time":None,"venueId":"le-106-rouen",
        "artistIds":["editors","big-sleep"],
        "artistNames":["Editors","Big Sleep"],
        "newArtistIds":["editors","big-sleep"],
        "genres":["Rock"],
        "officialUrl":"https://le106.com/agenda/editors",
        "calendarUrl":"https://le106.com/agenda?page=1",
    },
    "go-c-20270311-rouen-steve-n-seagulls": {
        "title":"Steve'n'Seagulls","date":"2027-03-11",
        "time":None,"venueId":"le-106-rouen",
        "artistIds":["steve-n-seagulls"],
        "artistNames":["Steve'n'Seagulls"],
        "newArtistIds":["steve-n-seagulls"],
        "genres":["Rock"],
        "officialUrl":"https://le106.com/agenda/stevenseagulls",
        "calendarUrl":"https://le106.com/agenda?page=2",
    },
    "go-c-20270413-rouen-peter-hook-and-the-light": {
        "title":"Peter Hook and The Light","date":"2027-04-13",
        "time":None,"venueId":"le-106-rouen",
        "artistIds":["peter-hook-and-the-light"],
        "artistNames":["Peter Hook and The Light"],
        "newArtistIds":["peter-hook-and-the-light"],
        "genres":["Rock"],
        "officialUrl":"https://le106.com/agenda/peter-hook-and-light",
        "calendarUrl":"https://le106.com/agenda?page=2",
    },
    "go-c-20270515-rouen-tagada-jones": {
        "title":"Tagada Jones","date":"2027-05-15",
        "time":None,"venueId":"le-106-rouen",
        "artistIds":["tagada-jones"],
        "artistNames":["Tagada Jones"],
        "newArtistIds":[],
        "genres":["Punk Rock"],
        "officialUrl":"https://le106.com/agenda/tagada-jones",
        "calendarUrl":"https://le106.com/agenda?page=2",
    },
    "go-c-20261212-rouen-maustetytot-francis": {
        "title":"Maustetytöt + Francis","date":"2026-12-12",
        "time":None,"venueId":"le-106-rouen",
        "artistIds":["maustetytot","francis"],
        "artistNames":["Maustetytöt","Francis"],
        "newArtistIds":["maustetytot","francis"],
        "genres":["Rock"],
        "officialUrl":"https://le106.com/agenda/maustetytot",
        "calendarUrl":"https://le106.com/agenda?page=1",
    },

}


# The 2026-2027 Antipode official individual details explicitly distinguish
# doors 20:00 from the MUSICAL start 20:30; exact named first-party calendar
# corroborates the full year/date. Festival rows are never imported here.
ANTIPODE_RENNES_VERIFIED = {
    "go-c-20261212-rennes-girls-in-hawaii-chaton-laveur": {
        "title": "Girls in Hawaii + Chaton Laveur", "date": "2026-12-12",
        "time": "20:30", "doorTime": "20:00", "venueId": "antipode-rennes",
        "artistIds": ["girls-in-hawaii", "chaton-laveur"],
        "artistNames": ["Girls in Hawaii", "Chaton Laveur"],
        "newArtistIds": ["girls-in-hawaii", "chaton-laveur"],
        "genres": ["Rock"], "status": "confirmed",
        "organizer": "Antipode", "soldOut": True,
        "officialUrl": "https://antipode-rennes.fr/agenda/girls-hawaii-2026",
        "calendarUrl": "https://antipode-rennes.fr/agenda",
    },
    "go-c-20270127-rennes-altin-gun": {
        "title": "Altın Gün", "date": "2027-01-27",
        "time": "20:30", "doorTime": "20:00", "venueId": "antipode-rennes",
        "artistIds": ["altin-gun"], "artistNames": ["Altın Gün"],
        "newArtistIds": ["altin-gun"], "genres": ["Rock", "Folk Rock"],
        "status": "confirmed", "organizer": "Association Trans Musicales",
        "soldOut": False,
        "officialUrl": "https://antipode-rennes.fr/agenda/altin-gun-2027",
        "calendarUrl": "https://antipode-rennes.fr/agenda",
    },
    "go-c-20270309-rennes-the-pineapple-thief": {
        "title": "The Pineapple Thief", "date": "2027-03-09",
        "time": "20:30", "doorTime": "20:00", "venueId": "antipode-rennes",
        "artistIds": ["the-pineapple-thief"],
        "artistNames": ["The Pineapple Thief"], "newArtistIds": [],
        "genres": ["Rock progressif"], "status": "confirmed",
        "organizer": "Garmonbozia", "soldOut": False,
        "officialUrl": "https://antipode-rennes.fr/agenda/pineapple-thief-2027",
        "calendarUrl": "https://antipode-rennes.fr/agenda",
    },
    "go-c-20270602-rennes-diiv": {
        "title": "DIIV", "date": "2027-06-02",
        "time": "20:30", "doorTime": "20:00", "venueId": "antipode-rennes",
        "artistIds": ["diiv"], "artistNames": ["DIIV"],
        "newArtistIds": ["diiv"], "genres": ["Rock"],
        "status": "confirmed", "organizer": None,
        "soldOut": False,
        "officialUrl": "https://antipode-rennes.fr/agenda/diiv-2027",
        "calendarUrl": "https://antipode-rennes.fr/agenda",
    },
    "go-c-20261216-rennes-hanry": {
        "title": "Apéro-concert avec Hanry", "date": "2026-12-16",
        "time": "19:30", "doorTime": "19:00", "venueId": "antipode-rennes",
        "artistIds": ["hanry"], "artistNames": ["Hanry"],
        "newArtistIds": ["hanry"], "genres": ["Rock"],
        "status": "confirmed", "organizer": "Antipode", "soldOut": False,
        "officialUrl": "https://antipode-rennes.fr/agenda/hanry-2026",
        "calendarUrl": "https://antipode-rennes.fr/agenda",
    },
}

# Bonjour Minuit, Saint-Brieuc: independent first-party event and calendar
# review. On 2 December the printed 20:00 is DOORS; 20:30 is explicitly
# indicative, hence no asserted musical start in the published event.
BONJOUR_MINUIT_VERIFIED = {
    "go-c-20261202-saint-brieuc-magma": {
        "title": "Magma", "date": "2026-12-02", "time": None,
        "venueId": "bonjour-minuit-saint-brieuc", "artistIds": ["magma"],
        "artistNames": ["Magma"], "newArtistIds": [],
        "genres": ["Rock progressif"], "status": "confirmed",
        "officialUrl": "https://bonjour-minuit.fr/evenement/magma-02dec26/",
        "calendarUrl": "https://bonjour-minuit.fr/agenda/",
    },
    "go-c-20270130-saint-brieuc-sbrbs": {
        "title": "SBRBS + Atoem + Sarakiniko + DJ Cup of Tea",
        "date": "2027-01-30", "time": None,
        "venueId": "bonjour-minuit-saint-brieuc",
        "artistIds": ["sbrbs", "atoem", "sarakiniko", "dj-cup-of-tea"],
        "artistNames": ["SBRBS", "Atoem", "Sarakiniko", "DJ Cup of Tea"],
        "newArtistIds": ["sbrbs", "atoem", "sarakiniko", "dj-cup-of-tea"],
        "genres": ["Rock indépendant"], "status": "confirmed",
        "officialUrl": "https://bonjour-minuit.fr/evenement/sbrbs-30janv27/",
        "calendarUrl": "https://bonjour-minuit.fr/agenda/",
    }
}

# Exact official first-party event — Le Jardin Moderne, Rennes.
# Displayed "20h > 1h" is a programme interval, NOT a proven music start.
JARDIN_MODERNE_VERIFIED = {
    "go-c-20261107-rennes-excellento": {
        "title": "Excellento + Joey Glüten + Bâtarde",
        "date": "2026-11-07",
        "time": None,
        "venueId": "le-jardin-moderne-rennes",
        "artistIds": ["excellento", "joey-gluten", "batarde"],
        "artistNames": ["Excellento", "Joey Glüten", "Bâtarde"],
        "newArtistIds": ["excellento", "joey-gluten", "batarde"],
        "genres": ["Rock"],
        "status": "confirmed",
        "officialUrl": "https://www.jardinmoderne.org/agenda/excellento-joey-gluten-batarde/",
        "calendarUrl": "https://www.jardinmoderne.org/agenda/",
    }
}




# Quatre affiches vérifiées le 04/11/2026 sur fiches nominatives officielles.
# Ces preuves ne peuvent pas être réutilisées sous un autre ID ou une autre salle.
NANTES_TOULOUSE_NOV2026_VERIFIED = {
    "go-c-20270220-nantes-hipskor": {
        "title": "Hipskör + Lifeboats + Polybius",
        "date": "2027-02-20", "time": "20:30",
        "venueId": "le-ferrailleur-nantes",
        "artistIds": ["hipskor", "lifeboats", "polybius"],
        "artistNames": ["Hipskör", "Lifeboats", "Polybius"],
        "genres": ["Metalcore", "Punk Hardcore", "Darkwave"],
        "newArtists": [{"id": "hipskor", "name": "Hipskör"},
                       {"id": "polybius", "name": "Polybius"}],
        "officialUrl": "https://www.leferrailleur.fr/evenement/hipskor-lifeboats-polybius/5375",
    },
    "go-c-20270408-nantes-antimatter": {
        "title": "Antimatter",
        "date": "2027-04-08", "time": "20:30",
        "venueId": "le-ferrailleur-nantes",
        "artistIds": ["antimatter"], "artistNames": ["Antimatter"],
        "genres": ["Doom", "Goth Rock"],
        "newArtists": [{"id": "antimatter", "name": "Antimatter"}],
        "officialUrl": "https://www.leferrailleur.fr/evenement/antimatter/5404",
    },
    "go-c-20261205-toulouse-changeline": {
        "title": "Changeline",
        "date": "2026-12-05", "time": None,
        "venueId": "le-rex-toulouse",
        "artistIds": ["changeline"], "artistNames": ["Changeline"],
        "genres": ["Metal", "Trap Metal"],
        "newArtists": [{"id": "changeline", "name": "Changeline"}],
        "officialUrl": "https://www.lerextoulouse.com/fr/programmation/changeline/",
    },
    "go-c-20270307-toulouse-mol": {
        "title": "MØL & Guest",
        "date": "2027-03-07", "time": None,
        "venueId": "le-rex-toulouse",
        "artistIds": ["m-l"], "artistNames": ["MØL"],
        "genres": ["Metal", "Blackgaze"],
        "newArtists": [],
        "officialUrl": "https://www.lerextoulouse.com/fr/programmation/mol-et-guest/",
    },
}



# Lot signé sur fiches officielles le 4 novembre : sept affiches exactes, sans publication brute.
SEVEN_OFFICIAL_NOV2026_VERIFIED = {
    "go-c-20270114-wasquehal-rhapsody-of-fire": {
        "title": "Rhapsody of Fire + Serious Black + Submasq + Aeon Gods + Rock Out",
        "date": "2027-01-14",
        "time": None,
        "venueId": "the-black-lab-wasquehal",
        "artistIds": [
            "rhapsody-of-fire",
            "serious-black",
            "submasq",
            "aeon-gods",
            "rock-out"
        ],
        "artistNames": [
            "Rhapsody of Fire",
            "Serious Black",
            "Submasq",
            "Aeon Gods",
            "Rock Out"
        ],
        "genres": [
            "Power Metal"
        ],
        "newArtists": [],
        "officialUrl": "https://theblacklab.fr/agenda/rhapsody-of-fire/",
        "calendarUrl": "https://theblacklab.fr/agenda/liste/"
    },
    "go-c-20270206-wasquehal-revnoir": {
        "title": "Revnoir + Ice Sealed Eyes",
        "date": "2027-02-06",
        "time": None,
        "venueId": "the-black-lab-wasquehal",
        "artistIds": [
            "revnoir",
            "ice-sealed-eyes"
        ],
        "artistNames": [
            "Revnoir",
            "Ice Sealed Eyes"
        ],
        "genres": [
            "Metalcore"
        ],
        "newArtists": [],
        "officialUrl": "https://theblacklab.fr/agenda/revnoir-ice-sealed-eyes/",
        "calendarUrl": "https://theblacklab.fr/agenda/liste/page/2/"
    },
    "go-c-20270115-biarritz-svinkels": {
        "title": "Svinkels + Voizins Vigilants",
        "date": "2027-01-15",
        "time": None,
        "venueId": "atabal-biarritz",
        "artistIds": [
            "svinkels",
            "voizins-vigilants"
        ],
        "artistNames": [
            "Svinkels",
            "Voizins Vigilants"
        ],
        "genres": [
            "Hip-Hop",
            "Electro Punk"
        ],
        "newArtists": [
            {
                "id": "svinkels",
                "name": "Svinkels"
            },
            {
                "id": "voizins-vigilants",
                "name": "Voizins Vigilants"
            }
        ],
        "officialUrl": "https://www.atabal-biarritz.fr/agenda/concerts/svinkels-family-friends-voizins-vigilants-vendredi-15-janvier-2027/",
        "calendarUrl": "https://www.atabal-biarritz.fr/agenda/"
    },
    "go-c-20261126-blois-carmen-sea": {
        "title": "Carmen Sea",
        "date": "2026-11-26",
        "time": "19:30",
        "venueId": "le-chatodo-blois",
        "artistIds": [
            "carmen-sea"
        ],
        "artistNames": [
            "Carmen Sea"
        ],
        "genres": [
            "Electro Rock"
        ],
        "newArtists": [
            {
                "id": "carmen-sea",
                "name": "Carmen Sea"
            }
        ],
        "officialUrl": "https://chatodo.com/agenda/evenement/carmen-sea/",
        "calendarUrl": "https://chatodo.com/agenda/"
    },
    "go-c-20261111-strasbourg-mogwai": {
        "title": "Mogwai + Forest Swords",
        "date": "2026-11-11",
        "time": "20:00",
        "venueId": "la-laiterie-strasbourg",
        "artistIds": [
            "mogwai",
            "forest-swords"
        ],
        "artistNames": [
            "Mogwai",
            "Forest Swords"
        ],
        "genres": [
            "Post Rock",
            "Art Rock"
        ],
        "newArtists": [
            {
                "id": "mogwai",
                "name": "Mogwai"
            },
            {
                "id": "forest-swords",
                "name": "Forest Swords"
            }
        ],
        "officialUrl": "https://www.artefact.org/la-laiterie/evenements/mogwai30/",
        "calendarUrl": "https://www.artefact.org/la-laiterie/"
    },
    "go-c-20261127-paris-lugosi": {
        "title": "LUGOSi + L’Idylle + Chiennes",
        "date": "2026-11-27",
        "time": None,
        "venueId": "glazart-paris",
        "artistIds": [
            "lugosi",
            "l-idylle",
            "chiennes"
        ],
        "artistNames": [
            "LUGOSi",
            "L’Idylle",
            "Chiennes"
        ],
        "genres": [
            "Post Hardcore",
            "Screamo",
            "Stoner Rock"
        ],
        "newArtists": [
            {
                "id": "lugosi",
                "name": "LUGOSi"
            },
            {
                "id": "l-idylle",
                "name": "L’Idylle"
            },
            {
                "id": "chiennes",
                "name": "Chiennes"
            }
        ],
        "officialUrl": "https://www.glazart.com/27-11-26-concert-lugosi-lidylle-chiennes/",
        "calendarUrl": None
    },
    "go-c-20270209-paris-melrose-avenue": {
        "title": "Melrose Avenue",
        "date": "2027-02-09",
        "time": None,
        "venueId": "le-trabendo-paris",
        "artistIds": [
            "melrose-avenue"
        ],
        "artistNames": [
            "Melrose Avenue"
        ],
        "genres": [
            "Metalcore"
        ],
        "newArtists": [
            {
                "id": "melrose-avenue",
                "name": "Melrose Avenue"
            }
        ],
        "officialUrl": "https://www.letrabendo.net/programmation/melrose-avenue/",
        "calendarUrl": "https://www.letrabendo.net/programmation/"
    }
}

# Dix fiches nominatives, explicitement revues dans trois départements sous-couverts.
UNDERCOVERED_REGIONS_NOV2026_VERIFIED = {
    # Lot national signé le 04/11/2026 ; uniquement ces quinze fiches officielles.
    "go-c-20261113-nancy-michel-cloup-trio": {"title": "Michel Cloup Trio + Arnaud Fournier + Dééfait", "date": "2026-11-13", "time": None, "venueId": "l-autre-canal-nancy", "artistIds": ["michel-cloup-trio", "arnaud-fournier", "deefait"], "artistNames": ["Michel Cloup Trio", "Arnaud Fournier", "Dééfait"], "genres": ["Rock", "Noise Rock"], "newArtists": [{"id": "michel-cloup-trio", "name": "Michel Cloup Trio"}, {"id": "arnaud-fournier", "name": "Arnaud Fournier"}, {"id": "deefait", "name": "Dééfait"}], "officialUrl": "https://lautrecanalnancy.fr/agenda/michel-cloup-trio-arnaud-fournier-deefait", "calendarUrl": "https://lautrecanalnancy.fr/agenda"},
    "go-c-20261121-nancy-les-fatals-picards": {"title": "Les Fatals Picards + Charcoal", "date": "2026-11-21", "time": None, "venueId": "l-autre-canal-nancy", "artistIds": ["les-fatals-picards", "charcoal"], "artistNames": ["Les Fatals Picards", "Charcoal"], "genres": ["Rock", "Hard Rock"], "newArtists": [], "officialUrl": "https://lautrecanalnancy.fr/agenda/les-fatals-picards-charcoal", "calendarUrl": "https://lautrecanalnancy.fr/agenda"},
    "go-c-20261212-nancy-benighted": {"title": "Benighted + Necroscum", "date": "2026-12-12", "time": None, "venueId": "l-autre-canal-nancy", "artistIds": ["benighted", "necroscum"], "artistNames": ["Benighted", "Necroscum"], "genres": ["Metal"], "newArtists": [{"id": "necroscum", "name": "Necroscum"}], "officialUrl": "https://lautrecanalnancy.fr/agenda/benighted-necroscum", "calendarUrl": "https://lautrecanalnancy.fr/agenda"},
    "go-c-20270205-nancy-skip-the-use": {"title": "Skip The Use", "date": "2027-02-05", "time": None, "venueId": "l-autre-canal-nancy", "artistIds": ["skip-the-use"], "artistNames": ["Skip The Use"], "genres": ["Rock"], "newArtists": [], "officialUrl": "https://lautrecanalnancy.fr/agenda/skip-use-1", "calendarUrl": "https://lautrecanalnancy.fr/agenda"},
    "go-c-20270216-nancy-laibach": {"title": "Laibach", "date": "2027-02-16", "time": None, "venueId": "l-autre-canal-nancy", "artistIds": ["laibach"], "artistNames": ["Laibach"], "genres": ["Industrial"], "newArtists": [{"id": "laibach", "name": "Laibach"}], "officialUrl": "https://lautrecanalnancy.fr/agenda/laibach", "calendarUrl": "https://lautrecanalnancy.fr/agenda"},
    "go-c-20270224-nancy-maquina": {"title": "MAQUINA.", "date": "2027-02-24", "time": None, "venueId": "l-autre-canal-nancy", "artistIds": ["maquina"], "artistNames": ["MAQUINA."], "genres": ["Krautrock", "Industrial Rock"], "newArtists": [{"id": "maquina", "name": "MAQUINA."}], "officialUrl": "https://lautrecanalnancy.fr/agenda/maquina", "calendarUrl": "https://lautrecanalnancy.fr/agenda"},
    "go-c-20270206-reims-skip-the-use": {"title": "Skip The Use + Imparfait", "date": "2027-02-06", "time": None, "venueId": "la-cartonnerie-reims", "artistIds": ["skip-the-use", "imparfait"], "artistNames": ["Skip The Use", "Imparfait"], "genres": ["Pop Rock", "Rock alternatif"], "newArtists": [], "officialUrl": "https://www.cartonnerie.fr/evenement/skip-the-use/", "calendarUrl": "https://www.cartonnerie.fr/agenda/"},
    "go-c-20270211-reims-pamela": {"title": "PAMELA + The Last Internationale", "date": "2027-02-11", "time": None, "venueId": "la-cartonnerie-reims", "artistIds": ["pamela", "the-last-internationale"], "artistNames": ["PAMELA", "The Last Internationale"], "genres": ["Rock"], "newArtists": [{"id": "pamela", "name": "PAMELA"}, {"id": "the-last-internationale", "name": "The Last Internationale"}], "officialUrl": "https://www.cartonnerie.fr/evenement/pamela-the-last-internationale/", "calendarUrl": "https://www.cartonnerie.fr/agenda/"},
    "go-c-20270218-reims-revnoir": {"title": "Revnoir + Ice Sealed Eyes + BLYGHT", "date": "2027-02-18", "time": None, "venueId": "la-cartonnerie-reims", "artistIds": ["revnoir", "ice-sealed-eyes", "blyght"], "artistNames": ["Revnoir", "Ice Sealed Eyes", "BLYGHT"], "genres": ["Metal", "Metalcore"], "newArtists": [{"id": "blyght", "name": "BLYGHT"}], "officialUrl": "https://www.cartonnerie.fr/evenement/revnoir/", "calendarUrl": "https://www.cartonnerie.fr/agenda/"},
    "go-c-20270219-reims-la-jungle": {"title": "La Jungle", "date": "2027-02-19", "time": None, "venueId": "la-cartonnerie-reims", "artistIds": ["la-jungle"], "artistNames": ["La Jungle"], "genres": ["Rock"], "newArtists": [], "officialUrl": "https://www.cartonnerie.fr/evenement/la-jungle/", "calendarUrl": "https://www.cartonnerie.fr/agenda/"},
    "go-c-20270319-reims-ayron-jones": {"title": "Ayron Jones", "date": "2027-03-19", "time": None, "venueId": "la-cartonnerie-reims", "artistIds": ["ayron-jones"], "artistNames": ["Ayron Jones"], "genres": ["Rock"], "newArtists": [{"id": "ayron-jones", "name": "Ayron Jones"}], "officialUrl": "https://www.cartonnerie.fr/evenement/ayron-jones/", "calendarUrl": "https://www.cartonnerie.fr/agenda/"},
    "go-c-20270403-reims-igorrr": {"title": "Igorrr + Secret Chiefs 3 + Fange", "date": "2027-04-03", "time": None, "venueId": "la-cartonnerie-reims", "artistIds": ["igorrr", "secret-chiefs-3", "fange"], "artistNames": ["Igorrr", "Secret Chiefs 3", "Fange"], "genres": ["Metal"], "newArtists": [], "officialUrl": "https://www.cartonnerie.fr/evenement/igorrr-secret-chiefs-3-fange/", "calendarUrl": "https://www.cartonnerie.fr/agenda/"},
    "go-c-20270409-reims-rodrigo-y-gabriela": {"title": "Rodrigo y Gabriela + midori jaeger", "date": "2027-04-09", "time": None, "venueId": "la-cartonnerie-reims", "artistIds": ["rodrigo-y-gabriela", "midori-jaeger"], "artistNames": ["Rodrigo y Gabriela", "midori jaeger"], "genres": ["Rock"], "newArtists": [{"id": "rodrigo-y-gabriela", "name": "Rodrigo y Gabriela"}, {"id": "midori-jaeger", "name": "midori jaeger"}], "officialUrl": "https://www.cartonnerie.fr/evenement/rodrigo-y-gabriela/", "calendarUrl": "https://www.cartonnerie.fr/agenda/"},
    "go-c-20270312-poitiers-tramhaus": {"title": "Tramhaus + Chevreuil", "date": "2027-03-12", "time": None, "venueId": "confort-moderne-poitiers", "artistIds": ["tramhaus", "chevreuil"], "artistNames": ["Tramhaus", "Chevreuil"], "genres": ["Post Punk", "Rock"], "newArtists": [{"id": "tramhaus", "name": "Tramhaus"}, {"id": "chevreuil", "name": "Chevreuil"}], "officialUrl": "https://www.confort-moderne.fr/fr/agenda/event/Tramhaus-Chevreuil/3128", "calendarUrl": "https://www.confort-moderne.fr/fr/agenda/details"},
    "go-c-20261115-wasquehal-cage-fight": {"title": "Cage Fight + Soul Splitter + Kabbel", "date": "2026-11-15", "time": None, "venueId": "the-black-lab-wasquehal", "artistIds": ["cage-fight", "soul-splitter", "kabbel"], "artistNames": ["Cage Fight", "Soul Splitter", "Kabbel"], "genres": ["Hardcore", "Metal"], "newArtists": [], "officialUrl": "https://theblacklab.fr/agenda/cage-fight-soul-splitter-kabbel/", "calendarUrl": "https://theblacklab.fr/agenda/"},
    "go-c-20261120-saint-etienne-inspector-cluzo": {
        "title": "The Inspector Cluzo + Grant Haua",
        "date": "2026-11-20",
        "time": "20:30",
        "venueId": "le-fil-saint-etienne",
        "artistIds": [
            "the-inspector-cluzo",
            "grant-haua"
        ],
        "artistNames": [
            "The Inspector Cluzo",
            "Grant Haua"
        ],
        "genres": [
            "Rock",
            "Blues"
        ],
        "newArtists": [
            {
                "id": "grant-haua",
                "name": "Grant Haua"
            }
        ],
        "officialUrl": "https://www.le-fil.com/evenement/the-inspector-cluzo/",
        "calendarUrl": "https://www.le-fil.com/agenda/"
    },
    "go-c-20261211-saint-etienne-guadal-tejaz": {
        "title": "Guadal Tejaz + 111",
        "date": "2026-12-11",
        "time": "20:30",
        "venueId": "le-fil-saint-etienne",
        "artistIds": [
            "guadal-tejaz",
            "111"
        ],
        "artistNames": [
            "Guadal Tejaz",
            "111"
        ],
        "genres": [
            "Post Punk",
            "Noise Rock"
        ],
        "newArtists": [
            {
                "id": "guadal-tejaz",
                "name": "Guadal Tejaz"
            },
            {
                "id": "111",
                "name": "111"
            }
        ],
        "officialUrl": "https://www.le-fil.com/evenement/guadal-tejaz/",
        "calendarUrl": "https://www.le-fil.com/agenda/"
    },
    "go-c-20270129-saint-etienne-skip-the-use": {
        "title": "Skip The Use + Imparfait",
        "date": "2027-01-29",
        "time": "20:30",
        "venueId": "le-fil-saint-etienne",
        "artistIds": [
            "skip-the-use",
            "imparfait"
        ],
        "artistNames": [
            "Skip The Use",
            "Imparfait"
        ],
        "genres": [
            "Rock",
            "Rock alternatif"
        ],
        "newArtists": [
            {
                "id": "imparfait",
                "name": "Imparfait"
            }
        ],
        "officialUrl": "https://www.le-fil.com/evenement/skip-the-use/",
        "calendarUrl": "https://www.le-fil.com/agenda/"
    },
    "go-c-20270130-saint-etienne-ultra-vomit": {
        "title": "Ultra Vomit",
        "date": "2027-01-30",
        "time": "20:30",
        "venueId": "le-fil-saint-etienne",
        "artistIds": [
            "ultra-vomit"
        ],
        "artistNames": [
            "Ultra Vomit"
        ],
        "genres": [
            "Metal"
        ],
        "newArtists": [
            {
                "id": "ultra-vomit",
                "name": "Ultra Vomit"
            }
        ],
        "officialUrl": "https://www.le-fil.com/evenement/ultra-vomit/",
        "calendarUrl": "https://www.le-fil.com/agenda/"
    },
    "go-c-20270227-saint-etienne-vulves-assassines": {
        "title": "Vulves Assassines",
        "date": "2027-02-27",
        "time": "20:30",
        "venueId": "le-fil-saint-etienne",
        "artistIds": [
            "vulves-assassines"
        ],
        "artistNames": [
            "Vulves Assassines"
        ],
        "genres": [
            "Punk"
        ],
        "newArtists": [],
        "officialUrl": "https://www.le-fil.com/evenement/vulves-assassines/",
        "calendarUrl": "https://www.le-fil.com/agenda/"
    },
    "go-c-20270401-saint-etienne-howlin-jaws": {
        "title": "Howlin' Jaws",
        "date": "2027-04-01",
        "time": "20:30",
        "venueId": "le-fil-saint-etienne",
        "artistIds": [
            "howlin-jaws"
        ],
        "artistNames": [
            "Howlin' Jaws"
        ],
        "genres": [
            "Rock"
        ],
        "newArtists": [],
        "officialUrl": "https://www.le-fil.com/evenement/howlin-jaws/",
        "calendarUrl": "https://www.le-fil.com/agenda/"
    },
    "go-c-20261118-nimes-fff": {
        "title": "FFF + Bleu Satellite",
        "date": "2026-11-18",
        "time": None,
        "venueId": "paloma-nimes",
        "artistIds": [
            "fff",
            "bleu-satellite"
        ],
        "artistNames": [
            "FFF",
            "Bleu Satellite"
        ],
        "genres": [
            "Rock",
            "Funk"
        ],
        "newArtists": [
            {
                "id": "bleu-satellite",
                "name": "Bleu Satellite"
            }
        ],
        "officialUrl": "https://paloma-nimes.fr/agenda/fff-2-event-36412/",
        "calendarUrl": "https://paloma-nimes.fr/agenda/2026-11/"
    },
    "go-c-20261124-nimes-marillion": {
        "title": "Marillion + Lazuli",
        "date": "2026-11-24",
        "time": None,
        "venueId": "paloma-nimes",
        "artistIds": [
            "marillion",
            "lazuli"
        ],
        "artistNames": [
            "Marillion",
            "Lazuli"
        ],
        "genres": [
            "Rock progressif"
        ],
        "newArtists": [
            {
                "id": "lazuli",
                "name": "Lazuli"
            }
        ],
        "officialUrl": "https://paloma-nimes.fr/agenda/marillion-event-36582/",
        "calendarUrl": "https://paloma-nimes.fr/agenda/2026-11/"
    },
    "go-c-20270312-nimes-skip-the-use": {
        "title": "Skip The Use + Supreme Nightclub",
        "date": "2027-03-12",
        "time": None,
        "venueId": "paloma-nimes",
        "artistIds": [
            "skip-the-use",
            "supreme-nightclub"
        ],
        "artistNames": [
            "Skip The Use",
            "Supreme Nightclub"
        ],
        "genres": [
            "Rock",
            "Indie Rock"
        ],
        "newArtists": [],
        "officialUrl": "https://paloma-nimes.fr/agenda/skip-the-use-4-event-37167/",
        "calendarUrl": "https://paloma-nimes.fr/agenda/2027-03/"
    },
    "go-c-20261204-tarbes-inspector-cluzo": {
        "title": "The Inspector Cluzo",
        "date": "2026-12-04",
        "time": None,
        "venueId": "la-gespe-tarbes",
        "artistIds": [
            "the-inspector-cluzo"
        ],
        "artistNames": [
            "The Inspector Cluzo"
        ],
        "genres": [
            "Rock"
        ],
        "newArtists": [],
        "officialUrl": "https://www.lagespe.com/p23-concert-c588-the-inspector-cluzo.html",
        "calendarUrl": "https://www.lagespe.com/?q=4"
    }
}

# Quatre affiches Colmar/Limoges du 04/11/2026 : aucune autre URL, concert,
# date ou salle n'est admise via ces justificatifs. Le type dayMonth N'ATTESTE
# PAS l'année : elle provient de la preuve calendrier datée séparément.
COLMAR_LIMOGES_VERIFIED_20261104 = {
    "go-c-20261209-colmar-darvaza": {"title": "Darvaza + Merrimack + Helleruin + Détresse", "date": "2026-12-09", "time": None, "venueId": "le-grillen-colmar", "artistIds": ["darvaza", "merrimack", "helleruin", "detresse"], "artistNames": ["Darvaza", "Merrimack", "Helleruin", "Détresse"], "genres": ["Black Metal"], "newArtists": [{"id": "darvaza", "name": "Darvaza"}, {"id": "merrimack", "name": "Merrimack"}, {"id": "helleruin", "name": "Helleruin"}, {"id": "detresse", "name": "Détresse"}], "officialUrl": "https://www.headbang.eu/events/concert-black-metal-darvaza-merrimack-helleruin-grillen-colmar-decembre-2026/", "proofs": [{"url": "https://www.headbang.eu/events/concert-black-metal-darvaza-merrimack-helleruin-grillen-colmar-decembre-2026/", "proofType": "official-organizer-or-venue", "requiredFields": ["artists", "date", "venue", "genre"]}, {"url": "https://grillen.colmar.fr/programmation/darvaza-merrimack-helleruin-detresse", "proofType": "first-party-venue-detail", "requiredFields": ["artists", "date", "venue", "genre"]}]},
    "go-c-20270213-colmar-8-6-crew": {"title": "8'6 Crew + Wunderbach + Hors Contrôle", "date": "2027-02-13", "time": None, "venueId": "le-grillen-colmar", "artistIds": ["8-6-crew", "wunderbach", "hors-controle"], "artistNames": ["8'6 Crew", "Wunderbach", "Hors Contrôle"], "genres": ["Punk Rock", "Ska"], "newArtists": [{"id": "8-6-crew", "name": "8'6 Crew"}, {"id": "wunderbach", "name": "Wunderbach"}, {"id": "hors-controle", "name": "Hors Contrôle"}], "officialUrl": "https://agenda.colmar.fr/86-crew-wunderbach-hors-controle", "proofs": [{"url": "https://agenda.colmar.fr/86-crew-wunderbach-hors-controle", "proofType": "official-organizer-or-venue", "requiredFields": ["artists", "date", "venue", "genre"]}, {"url": "https://grillen.colmar.fr/programmation/86-crew-wunderbach-hors-controle", "proofType": "first-party-venue-detail", "requiredFields": ["artists", "dayMonth", "venue", "genre"]}]},
    "go-c-20261106-limoges-7weeks": {"title": "7Weeks + Dirty Deep + Earth Inc.", "date": "2026-11-06", "time": None, "venueId": "espace-john-lennon-limoges", "artistIds": ["7weeks", "dirty-deep", "earth-inc"], "artistNames": ["7Weeks", "Dirty Deep", "Earth Inc."], "genres": ["Heavy Rock", "Heavy Blues"], "newArtists": [{"id": "earth-inc", "name": "Earth Inc."}], "officialUrl": "https://centresculturels.limoges.fr/agenda/release-party-7-weeks-dirty-deep-earth-inc", "proofs": [{"url": "https://centresculturels.limoges.fr/agenda/release-party-7-weeks-dirty-deep-earth-inc", "proofType": "official-organizer-or-venue", "requiredFields": ["artists", "dayMonth", "venue", "genre"]}, {"url": "https://centresculturels.limoges.fr/agenda?keys=hiero", "proofType": "first-party-venue-calendar", "requiredFields": ["artists", "date", "venue"]}]},
    "go-c-20261127-limoges-gwendoline": {"title": "Gwendoline + Jessica93", "date": "2026-11-27", "time": None, "venueId": "espace-john-lennon-limoges", "artistIds": ["gwendoline", "jessica93"], "artistNames": ["Gwendoline", "Jessica93"], "genres": ["Rock", "Cold Wave"], "newArtists": [{"id": "jessica93", "name": "Jessica93"}], "officialUrl": "https://centresculturels.limoges.fr/agenda/gwendoline-jessica93", "proofs": [{"url": "https://centresculturels.limoges.fr/agenda/gwendoline-jessica93", "proofType": "official-organizer-or-venue", "requiredFields": ["artists", "dayMonth", "venue", "genre"]}, {"url": "https://centresculturels.limoges.fr/agenda?keys=hiero", "proofType": "first-party-venue-calendar", "requiredFields": ["artists", "date", "venue"]}]},
    "go-c-20270219-colmar-colour-haze": {"title": "Colour Haze + Smokemaster", "date": "2027-02-19", "time": None, "venueId": "le-grillen-colmar", "artistIds": ["colour-haze", "smokemaster"], "artistNames": ["Colour Haze", "Smokemaster"], "genres": ["Stoner Rock"], "newArtists": [], "officialUrl": "https://grillen.colmar.fr/programmation/colour-haze-smokemaster", "proofs": [{"url": "https://grillen.colmar.fr/programmation/colour-haze-smokemaster", "proofType": "official-organizer-or-venue", "requiredFields": ["artists", "date", "venue", "genre"]}, {"url": "https://www.soundofliberation.com/artists/colour-haze", "proofType": "independent-tour-agent", "requiredFields": ["artists", "date", "venue"]}]},
}

def validate_approval(approval, venues, known_artist_ids, today):
    require(approval.get("reviewDecision") == "approved",
            "Événement non approuvé")
    reviewer = approval.get("reviewedBy")
    require(reviewer in ("human", "independent-official-verifier", "automated-official-recheck"),
            "Validateur indépendant absent")
    evidence = approval.get("officialEvidence")
    require(isinstance(evidence, list) and evidence,
            "Aucune preuve officielle indépendante")
    event = approval.get("event")
    require(isinstance(event, dict), "Fiche absente")
    event_id = event.get("id", "")
    require(isinstance(event_id, str) and re.fullmatch(r"go-c-[a-z0-9-]{7,150}", event_id),
            "Identifiant d'événement invalide")
    require(event.get("venueId") in venues,
            "Lieu non connu : nouvel emplacement à vérifier avant publication")
    # An exact approved event ID cannot be transplanted to another existing
    # venue to bypass its venue-specific proof and hostname rules.
    if event_id in ROUEN_DEATH_VALLEY_SIGNED:
        require(event.get("venueId") == "le-106-rouen",
                "Concert Rouen déplacé vers une autre salle")
    if event_id in LAITERIE_OFFICIAL_VERIFIED or event_id in LAITERIE_SECOND_WAVE_VERIFIED:
        require(event.get("venueId") == "la-laiterie-strasbourg",
                "Identifiant de concert La Laiterie affecté à une autre salle")
    if event_id in BIKINI_OFFICIAL_VERIFIED:
        require(event.get("venueId") == "le-bikini-toulouse",
                "Identifiant de concert Bikini affecté à une autre salle")
    if event_id in ROCKSTORE_BLACKLAB_OFFICIAL_VERIFIED:
        require(event.get("venueId") ==
                ROCKSTORE_BLACKLAB_OFFICIAL_VERIFIED[event_id]["venueId"],
                "Rockstore/Black Lab : ID transféré dans une autre salle")
    require(norm_date(event.get("date")) >= today,
            "Concert passé ou non daté")
    require(isinstance(event.get("title"), str) and
            3 <= len(event["title"]) <= 220,
            "Titre invalide")
    official_url = event.get("officialUrl")
    require(isinstance(official_url, str) and
            urlsplit(official_url).scheme == "https" and
            bool(urlsplit(official_url).hostname),
            "Lien officiel HTTPS absent")
    # Exact event identity and official first-party URL are reserved
    # together: neither a new ID nor a different venue may reuse this proof.
    # Les quatre URLs officielles du lot Nantes/Toulouse ne sont pas recyclables.
    nantes_toulouse_by_url = {
        spec["officialUrl"]: ident
        for ident, spec in NANTES_TOULOUSE_NOV2026_VERIFIED.items()
    }
    if official_url in nantes_toulouse_by_url:
        require(event_id == nantes_toulouse_by_url[official_url],
                "Nantes/Toulouse : URL officielle réaffectée à un autre concert")
    if event_id in NANTES_TOULOUSE_NOV2026_VERIFIED:
        require(event.get("venueId") ==
                NANTES_TOULOUSE_NOV2026_VERIFIED[event_id]["venueId"],
                "Nantes/Toulouse : identifiant transféré dans une autre salle")
    regional_by_url = {spec["officialUrl"]: ident
                       for ident, spec in UNDERCOVERED_REGIONS_NOV2026_VERIFIED.items()}
    if official_url in regional_by_url:
        require(event_id == regional_by_url[official_url],
                "Lot régional : URL officielle réservée à son concert signé")
    if event_id in UNDERCOVERED_REGIONS_NOV2026_VERIFIED:
        require(event.get("venueId") ==
                UNDERCOVERED_REGIONS_NOV2026_VERIFIED[event_id]["venueId"],
                "Lot régional : identifiant déplacé hors de la salle")
    seven_by_url = {spec["officialUrl"]: ident
                    for ident, spec in SEVEN_OFFICIAL_NOV2026_VERIFIED.items()}
    if official_url in seven_by_url:
        require(event_id == seven_by_url[official_url],
                "Lot national : URL officielle réservée à son concert signé")
    if event_id in SEVEN_OFFICIAL_NOV2026_VERIFIED:
        require(event.get("venueId") ==
                SEVEN_OFFICIAL_NOV2026_VERIFIED[event_id]["venueId"],
                "Lot national : identifiant déplacé vers une autre salle")
    jardin_by_url={spec["officialUrl"]: ident
                   for ident,spec in JARDIN_MODERNE_VERIFIED.items()}
    if official_url in jardin_by_url:
        require(event_id==jardin_by_url[official_url],
                "Jardin Moderne : URL officielle déjà réservée à cette affiche")
    if event_id in JARDIN_MODERNE_VERIFIED:
        require(event.get("venueId")=="le-jardin-moderne-rennes",
                "Jardin Moderne : identifiant déplacé hors de la salle")
    antipode_urls = {row["officialUrl"]: key for key, row in
                     ANTIPODE_RENNES_VERIFIED.items()}
    if official_url in antipode_urls:
        require(event_id == antipode_urls[official_url],
                "Antipode : l'URL du concert est réservée à son identifiant")
    if event_id in ANTIPODE_RENNES_VERIFIED:
        require(event.get("venueId") == "antipode-rennes",
                "Antipode : concert transféré vers une autre salle")
    reserved_rouen_url = {spec["officialUrl"]: key for key, spec in {
        **ROUEN_DEATH_VALLEY_SIGNED, **ROUEN_ROCK_PAGED_VERIFIED
    }.items()}
    if official_url in reserved_rouen_url:
        require(event_id == reserved_rouen_url[official_url],
                "URL individuelle Le 106 réservée à son identifiant signé")
    if event_id in ROUEN_ROCK_PAGED_VERIFIED:
        require(event.get("venueId") == "le-106-rouen",
                "Identifiant de l'affiche Le 106 transféré hors salle")
    reserved_bbc_urls = {spec["officialUrl"]: ident
                         for ident, spec in BBC_NORMANDY_VERIFIED.items()}
    if official_url in reserved_bbc_urls:
        require(event_id == reserved_bbc_urls[official_url],
                "Big Band Café : cette fiche est réservée à son concert signé")
    if event_id in BBC_NORMANDY_VERIFIED:
        require(event.get("venueId") == "big-band-cafe-herouville",
                "Big Band Café : identifiant réservé à sa salle")
    require(any(
        item.get("url") == official_url and
        item.get("proofType") == "official-organizer-or-venue" and
        isinstance(item.get("checkedAt"), str) and item["checkedAt"]
        for item in evidence if isinstance(item, dict)
    ), "Preuve officielle portant sur l'URL exacte absente")
    if reviewer == "automated-official-recheck":
        # An automated recheck is not a human signature. Only explicitly
        # allowlisted FIRST-PARTY event detail paths and their exact venue
        # IDs qualify. Aggregator, generic agenda and Le Dodu cannot pass.
        venue = event.get("venueId")
        parsed_url = urlsplit(official_url)
        rex = (venue == "le-rex-toulouse" and
               parsed_url.hostname == "www.lerextoulouse.com" and
               re.fullmatch(r"/fr/programmation/[^/]+/?", parsed_url.path))
        molotov = (venue == "le-molotov-marseille" and
                   parsed_url.hostname == "lemolotov.com" and
                   re.fullmatch(r"/events/[^/]+/?", parsed_url.path) and
                   not (approval.get("newArtists") or []))
        ferrailleur = (
            venue == FERRAILLEUR_VENUE_ID and
            parsed_url.hostname in ("www.leferrailleur.fr", "leferrailleur.fr") and
            re.fullmatch(r"/evenement/[^/?#]+/\d+/?", parsed_url.path) and
            not parsed_url.username and not parsed_url.password and
            not parsed_url.query and not parsed_url.fragment and
            isinstance(venues[venue], dict) and
            all(venues[venue].get(k) == v for k,v in FERRAILLEUR_LOCATION_FIX.items())
        )
        require(bool(rex or molotov or ferrailleur) and event.get("sourceType") == "salle",
                "Approbation automatique hors périmètre de salle agréée")
        reviewed_at = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=7) <= reviewed_at <= today,
                "Preuve automatique trop ancienne ou future")
        require(any(
            item.get("url") == official_url and
            item.get("proofType") == "official-organizer-or-venue" and
            item.get("checkedAt") == reviewed_at.isoformat() and
            {"artists", "date", "venue", "genre"}.issubset(
                set(item.get("checkedFields") or []))
            for item in evidence if isinstance(item, dict)
        ), "Revérification automatique sans preuves de champs complètes")
    ids = event.get("artistIds")
    require(isinstance(ids, list) and ids and
            len(ids) == len(set(ids)) and
            all(isinstance(x, str) and re.fullmatch(r"[a-z0-9-]+", x)
                for x in ids),
            "Artistes non identifiés")
    new_artists = approval.get("newArtists") or []
    require(isinstance(new_artists, list) and len(new_artists) <= 15,
            "Trop d'artistes nouveaux")
    added = {}
    for artist in new_artists:
        aid = artist.get("id")
        name = artist.get("name")
        require(isinstance(aid, str) and re.fullmatch(r"[a-z0-9-]{3,100}", aid)
                and isinstance(name, str) and 2 <= len(name) <= 120,
                "Artiste nouveau non identifié")
        require(aid not in known_artist_ids and aid not in added,
                "Identifiant d'artiste déjà utilisé")
        added[aid] = {"id": aid, "name": name, "aliases": []}
    require(all(x in known_artist_ids or x in added for x in ids),
            "Artiste non reconnu par le catalogue")
    if reviewer == "automated-official-recheck" and ferrailleur:
        proof = next((item for item in evidence if isinstance(item,dict)
                      and item.get("url")==official_url and
                      item.get("checkedAt")==reviewed_at.isoformat() and
                      {"artists","date","venue","genre"}.issubset(
                          set(item.get("checkedFields") or []))), None)
        require(proof is not None, "Liste officielle d'artistes non vérifiée")
        names = proof.get("officialArtistNames")
        require(isinstance(names,list) and len(names)==len(ids) and
                1<=len(names)<=5 and
                all(isinstance(n,str) and 3<=len(norm(n))<=100 for n in names) and
                len({norm(n) for n in names})==len(names),
                "Liste officielle d'artistes absente ou ambiguë")
        displayed = re.split(r"\s+\+\s+", event["title"])
        require(len(displayed)==len(names) and
                all(norm(a)==norm(b) for a,b in zip(displayed,names)),
                "Affiche différente de la liste officielle")
        require(len(added)<=2 and
                proof.get("verifiedNewArtists")==[x["name"] for x in new_artists],
                "Artistes nouveaux non documentés exactement")
        # Each ID has to point to the exact named act, not another known act.
        for aid,name in zip(ids,names):
            resolved = added.get(aid) or known_artist_ids.get(aid)
            require(bool(resolved) and norm(resolved["name"])==norm(name),
                    "Artiste officiel ne correspond pas à son identifiant")
        # An artist alias can be a duplicate identity, even when the slug is free.
        existing = {norm(x["name"]) for x in known_artist_ids.values()}
        aliases = {norm(alias)
                   for x in known_artist_ids.values()
                   for alias in (x.get("aliases") or []) if isinstance(alias,str)}
        require(all(norm(x["name"]) not in existing|aliases and
                    x["id"]==norm(x["name"]).replace(" ","-")[:72].strip("-")
                    for x in new_artists),
                "Artiste nouveau en conflit avec identité existante")
        require(any(re.search(r"(?<![a-z0-9])(metal|punk|hardcore|grind|doom|sludge|stoner|hard rock)(?![a-z0-9])",
                              norm(g)) for g in event.get("genres",[])),
                "Genre métal ou punk officiel absent")
    # Salles historiquement géolocalisées de façon indicative : une nouvelle
    # affiche ne peut passer qu'avec sa propre signature nominative. Aucune
    # approbation générique fondée sur le seul domaine du site.
    if (event_id in COLMAR_LIMOGES_VERIFIED_20261104 or
            event.get("venueId") in ("le-grillen-colmar", "espace-john-lennon-limoges")):
        spec = COLMAR_LIMOGES_VERIFIED_20261104.get(event_id)
        require(spec is not None and reviewer == "independent-official-verifier"
                and event.get("sourceType") == "salle"
                and all(event.get(k) == spec[k] for k in
                        ("title", "date", "time", "venueId", "artistIds", "genres"))
                and event.get("status") == "confirmed"
                and official_url == spec["officialUrl"],
                "Colmar/Limoges : affiche hors liste officielle signée")
        checked_at = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= checked_at <= today,
                "Colmar/Limoges : preuve expirée ou future")
        expected = spec["proofs"]
        require(len(evidence) == len(expected) == 2
                and all(isinstance(p, dict) for p in evidence),
                "Colmar/Limoges : deux sources officielles nominatives obligatoires")
        for actual, proof in zip(evidence, expected):
            got_fields = set(actual.get("checkedFields") or [])
            require(actual.get("url") == proof["url"]
                    and actual.get("proofType") == proof["proofType"]
                    and actual.get("checkedAt") == checked_at.isoformat()
                    and actual.get("checkedFields") == proof["requiredFields"]
                    and len(got_fields) == len(proof["requiredFields"])
                    and not ({"startTime", "concertStartTime", "doorTime"} & got_fields),
                    "Colmar/Limoges : année, artistes, provenance ou heure surdéclarés")
        require(event.get("time") is None,
                "Colmar/Limoges : horaire musical non confirmé")
        require(new_artists == spec["newArtists"],
                "Colmar/Limoges : artistes nouveaux altérés")
        resolved = dict(known_artist_ids)
        resolved.update(added)
        require(len(ids) == len(spec["artistNames"])
                and all(aid in resolved and norm(resolved[aid]["name"]) == norm(name)
                        for aid, name in zip(ids, spec["artistNames"])),
                "Colmar/Limoges : groupes différents des affiches officielles")
    require(isinstance(event.get("genres"), list) and
            1 <= len(event["genres"]) <= 10 and
            all(isinstance(x, str) and x for x in event["genres"]),
            "Genres non documentés")
    require(event.get("status") == "confirmed", "Concert annulé ou incertain")
    time_value = event.get("time")
    require(time_value is None or
            (isinstance(time_value, str) and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", time_value)),
            "Heure non valide")
    require(event.get("sourceType") in ("organisateur", "salle"),
            "Source tierce seule non admise")
    # Two pilot venues: Joker individual first-party detail pages, or four
    # explicit organizer-controlled Brin ticket pages with a second venue-
    # submitted listing. Never approve tickets from a generic event calendar.
    # Lot revu indépendamment : identité, artistes, temps et preuve exacte figés.
    if event_id in NANTES_TOULOUSE_NOV2026_VERIFIED:
        spec = NANTES_TOULOUSE_NOV2026_VERIFIED[event_id]
        require(reviewer == "independent-official-verifier"
                and event.get("sourceType") == "salle"
                and all(event.get(key) == spec[key] for key in
                        ("title", "date", "time", "venueId", "artistIds", "genres"))
                and event.get("status") == "confirmed"
                and official_url == spec["officialUrl"],
                "Nantes/Toulouse : affiche ou salle hors dossier approuvé")
        checked = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= checked <= today,
                "Nantes/Toulouse : vérification officielle périmée")
        require(len(evidence) == 1 and isinstance(evidence[0], dict),
                "Nantes/Toulouse : fiche officielle nominative exigée")
        proof = evidence[0]
        fields = set(proof.get("checkedFields") or [])
        require(proof.get("url") == spec["officialUrl"]
                and proof.get("proofType") == "official-organizer-or-venue"
                and proof.get("checkedAt") == checked.isoformat()
                and {"artists", "date", "venue", "genre"}.issubset(fields)
                and (("concertStartTime" in fields) == (spec["time"] is not None))
                and "startTime" not in fields
                and "doorTime" not in fields,
                "Nantes/Toulouse : preuves ou horaires non corroborés")
        resolved = dict(known_artist_ids)
        resolved.update(added)
        require(new_artists == spec["newArtists"]
                and len(ids) == len(spec["artistNames"])
                and all(aid in resolved
                        and norm(resolved[aid]["name"]) == norm(name)
                        for aid, name in zip(ids, spec["artistNames"])),
                "Nantes/Toulouse : groupe inventé ou identité incohérente")
    # Ces sept entrées franchissent uniquement leur revue nominative signée.
    # Les règles fermées des salles pour les autres concerts restent inchangées.
    # Les autres concerts des trois salles restent hors de ce lot signé.
    if event_id in UNDERCOVERED_REGIONS_NOV2026_VERIFIED:
        spec = UNDERCOVERED_REGIONS_NOV2026_VERIFIED[event_id]
        require(reviewer == "independent-official-verifier"
                and event.get("sourceType") == "salle"
                and event.get("status") == "confirmed"
                and all(event.get(key) == spec[key] for key in
                        ("title", "date", "time", "venueId", "artistIds", "genres"))
                and official_url == spec["officialUrl"],
                "Lot régional : identité, salle, jour ou genre altéré")
        url = urlsplit(official_url)
        approved_url = urlsplit(spec["officialUrl"])
        require(url.scheme == "https"
                and url.hostname == approved_url.hostname
                and url.path == approved_url.path
                and not url.username and not url.password and not url.port
                and not url.query and not url.fragment,
                "Lot régional : fiche officielle individuelle HTTPS exigée")
        reviewed = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= reviewed <= today,
                "Lot régional : revue trop ancienne ou future")
        required = {
            "official-organizer-or-venue":
                (spec["officialUrl"], {"artists","date","venue","genre"}),
            "first-party-venue-calendar":
                (spec["calendarUrl"], {"artists","date","venue"}),
        }
        require(isinstance(evidence,list) and len(evidence) == 2
                and all(isinstance(p,dict) for p in evidence)
                and {p.get("proofType") for p in evidence} == set(required),
                "Lot régional : deux preuves officielles indépendantes requises")
        for p in evidence:
            kind = p["proofType"]
            expected_url, checked = required[kind]
            fields = set(p.get("checkedFields") or [])
            require(p.get("url") == expected_url
                    and p.get("checkedAt") == reviewed.isoformat()
                    and checked.issubset(fields)
                    and "startTime" not in fields
                    and (kind != "official-organizer-or-venue"
                         or (("concertStartTime" in fields) ==
                             (spec["time"] is not None)))
                    and (kind != "first-party-venue-calendar"
                         or "concertStartTime" not in fields),
                    "Lot régional : preuve officielle ou heure de scène absente")
        resolved = dict(known_artist_ids)
        resolved.update(added)
        require(new_artists == spec["newArtists"]
                and len(ids) == len(spec["artistNames"])
                and all(aid in resolved
                        and norm(resolved[aid]["name"]) == norm(name)
                        for aid,name in zip(ids,spec["artistNames"])),
                "Lot régional : groupe ou première partie non vérifiés")
        existing_aliases = {norm(alias) for artist in known_artist_ids.values()
                            for alias in (artist.get("aliases") or [])
                            if isinstance(alias,str)}
        require(all(norm(artist["name"]) not in existing_aliases
                    for artist in new_artists),
                "Lot régional : alias d'artiste potentiellement déjà référencé")
    elif event_id in SEVEN_OFFICIAL_NOV2026_VERIFIED:
        spec = SEVEN_OFFICIAL_NOV2026_VERIFIED[event_id]
        require(reviewer == "independent-official-verifier"
                and event.get("sourceType") == "salle"
                and event.get("status") == "confirmed"
                and all(event.get(key) == spec[key] for key in
                        ("title", "date", "time", "venueId", "artistIds", "genres"))
                and official_url == spec["officialUrl"],
                "Lot national : affiche non identique à la preuve signée")
        uri = urlsplit(official_url)
        expected_url = urlsplit(spec["officialUrl"])
        require(uri.scheme == "https" and uri.hostname == expected_url.hostname
                and uri.path == expected_url.path
                and not uri.username and not uri.password and not uri.port
                and not uri.query and not uri.fragment,
                "Lot national : fiche officielle individuelle HTTPS exigée")
        reviewed = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= reviewed <= today,
                "Lot national : preuve trop ancienne ou datée dans le futur")
        required = {
            "official-organizer-or-venue": (
                spec["officialUrl"], {"artists", "date", "venue", "genre"})
        }
        if spec["calendarUrl"]:
            required["first-party-venue-calendar"] = (
                spec["calendarUrl"], {"artists", "date", "venue"})
        require(len(evidence) == len(required)
                and all(isinstance(p, dict) for p in evidence)
                and {p.get("proofType") for p in evidence} == set(required),
                "Lot national : mauvais nombre ou type de preuves")
        for proof in evidence:
            kind = proof.get("proofType")
            path, fields = required[kind]
            observed = set(proof.get("checkedFields") or [])
            require(proof.get("url") == path
                    and proof.get("checkedAt") == reviewed.isoformat()
                    and fields.issubset(observed)
                    and "startTime" not in observed
                    and (kind != "official-organizer-or-venue"
                         or (("concertStartTime" in observed) == (spec["time"] is not None)))
                    and (kind != "first-party-venue-calendar"
                         or "concertStartTime" not in observed),
                    "Lot national : preuve de champ ou horaire non démontré")
        resolved = dict(known_artist_ids)
        resolved.update(added)
        require(new_artists == spec["newArtists"]
                and len(ids) == len(spec["artistNames"])
                and all(aid in resolved and
                        norm(resolved[aid]["name"]) == norm(name)
                        for aid, name in zip(ids, spec["artistNames"])),
                "Lot national : identité ou première partie non vérifiée")
        aliases = {norm(a) for artist in known_artist_ids.values()
                   for a in (artist.get("aliases") or [])
                   if isinstance(a, str)}
        require(all(norm(a["name"]) not in aliases
                    for a in new_artists),
                "Lot national : nouveau groupe possiblement déjà référencé")
    elif event.get("venueId") == "la-laiterie-strasbourg":
        spec = (LAITERIE_OFFICIAL_VERIFIED.get(event_id)
                or LAITERIE_SECOND_WAVE_VERIFIED.get(event_id))
        require(spec is not None and reviewer == "independent-official-verifier"
                and event.get("sourceType") == "salle"
                and all(event.get(k) == spec[k] for k in
                        ("title", "date", "artistIds", "genres", "time"))
                and official_url == spec["officialUrl"]
                and event.get("time") is None,
                "La Laiterie : affiche hors liste officielle ou horaire des portes abusivement pris pour le concert")
        u = urlsplit(official_url)
        require(u.scheme == "https" and u.hostname == "www.artefact.org"
                and u.path == urlsplit(spec["officialUrl"]).path
                and u.path.startswith("/la-laiterie/evenements/")
                and not u.username and not u.password and not u.port
                and not u.query and not u.fragment,
                "La Laiterie : lien direct officiel de la salle exigé")
        reviewed = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= reviewed <= today,
                "La Laiterie : revue nominative périmée ou datée dans le futur")
        expected = {
            "official-organizer-or-venue": (spec["officialUrl"],
                {"artists", "date", "venue", "genre"}),
            "first-party-venue-calendar": (spec["calendarUrl"],
                {"artists", "date", "venue", "genre"}),
        }
        if spec.get("organizerUrl"):
            # The venue spells "Arm's Lenght"; Live Nation independently
            # confirms the canonical band name Arm's Length and full lineup.
            expected["independent-organizer-confirmation"] = (
                spec["organizerUrl"], {"artists", "date", "venue"})
        require(len(evidence) == len(expected)
                and {x.get("proofType") for x in evidence if isinstance(x,dict)}
                    == set(expected),
                "La Laiterie : justificatif officiel ou correctif nom artiste manquant")
        for p in evidence:
            typ = p.get("proofType") if isinstance(p, dict) else None
            need = expected.get(typ)
            require(need is not None and p.get("url") == need[0]
                    and p.get("checkedAt") == reviewed.isoformat()
                    and need[1].issubset(set(p.get("checkedFields") or []))
                    and "startTime" not in (p.get("checkedFields") or []),
                    "La Laiterie : preuve datée ou champ début non corroboré")
        resolved = dict(known_artist_ids)
        resolved.update(added)
        require(new_artists == spec.get("newArtists", [])
                and len(ids) == len(spec["artistNames"])
                and all(aid in resolved and norm(resolved[aid]["name"]) == norm(name)
                        for aid,name in zip(ids,spec["artistNames"]))
                and all(norm(x["name"]) not in {norm(y["name"]) for y in known_artist_ids.values()}
                        for x in new_artists),
                "La Laiterie : nouveaux artistes non vérifiés ou identité discordante")
    elif event.get("venueId") in ("rockstore-montpellier",
                                   "the-black-lab-wasquehal"):
        # Existing venue IDs may have coarse historic pins, but never reuse
        # that fact to admit an unchecked lineup, date, start or URL.
        spec = ROCKSTORE_BLACKLAB_OFFICIAL_VERIFIED.get(event_id)
        require(spec is not None
                and event.get("venueId") == spec["venueId"]
                and reviewer == "independent-official-verifier"
                and event.get("sourceType") == "salle"
                and all(event.get(k) == spec[k] for k in
                        ("title", "date", "artistIds", "genres", "time"))
                and official_url == spec["officialUrl"],
                "Rockstore/Black Lab : affiche non agréée ou détails altérés")
        uri = urlsplit(official_url)
        allowed_host = ("rockstore.fr" if spec["venueId"] ==
                        "rockstore-montpellier" else "theblacklab.fr")
        require(uri.scheme == "https" and uri.hostname == allowed_host
                and uri.path == urlsplit(spec["officialUrl"]).path
                and not uri.username and not uri.password and not uri.port
                and not uri.query and not uri.fragment,
                "Rockstore/Black Lab : URL individuelle officielle exacte exigée")
        reviewed_at = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= reviewed_at <= today,
                "Rockstore/Black Lab : vérification périmée ou future")
        requirements = {
            "official-organizer-or-venue": (
                spec["officialUrl"], {"artists", "date", "venue", "genre"}),
            "first-party-venue-calendar": (
                spec["calendarUrl"], {"artists", "date", "venue"}),
        }
        require(len(evidence) == 2 and
                {e.get("proofType") for e in evidence if isinstance(e, dict)}
                == set(requirements),
                "Rockstore/Black Lab : détail et calendrier officiels requis")
        for proof in evidence:
            typ = proof.get("proofType") if isinstance(proof, dict) else None
            req = requirements.get(typ)
            require(req is not None and proof.get("url") == req[0]
                    and proof.get("checkedAt") == reviewed_at.isoformat()
                    and req[1].issubset(set(proof.get("checkedFields") or []))
                    and "startTime" not in (proof.get("checkedFields") or []),
                    "Rockstore/Black Lab : preuves ou heure du début invalides")
        resolved = dict(known_artist_ids)
        resolved.update(added)
        require(new_artists == spec["newArtists"]
                and len(ids) == len(spec["artistNames"])
                and all(aid in resolved
                    and norm(resolved[aid]["name"]) == norm(name)
                    for aid, name in zip(ids, spec["artistNames"]))
                and all(norm(x["name"]) not in
                        {norm(y["name"]) for y in known_artist_ids.values()}
                        for x in new_artists),
                "Rockstore/Black Lab : groupes ou identités non documentés")
        require(event.get("time") is None,
                "Rockstore/Black Lab : heure de début non confirmée")
    elif event.get("venueId") == "le-jardin-moderne-rennes":
        spec = JARDIN_MODERNE_VERIFIED.get(event_id)
        require(spec is not None
                and reviewer == "independent-official-verifier"
                and event.get("sourceType") == "salle"
                and all(event.get(k) == spec[k] for k in
                        ("title", "date", "time", "venueId", "artistIds",
                         "genres", "status"))
                and event.get("organizer") is None
                and official_url == spec["officialUrl"],
                "Jardin Moderne : seule l'affiche nominative signée est autorisée")
        u=urlsplit(official_url)
        require(u.scheme == "https" and u.hostname == "www.jardinmoderne.org"
                and u.path == urlsplit(spec["officialUrl"]).path
                and re.fullmatch(r"/agenda/[a-z0-9-]+/",u.path)
                and not u.query and not u.fragment and not u.username
                and not u.password and not u.port,
                "Jardin Moderne : URL first-party du concert exacte exigée")
        checked=norm_date(approval.get("reviewedAt"))
        require(today-dt.timedelta(days=14)<=checked<=today,
                "Jardin Moderne : preuve privée trop ancienne ou future")
        require(isinstance(evidence,list) and len(evidence)==2
                and all(isinstance(p,dict) for p in evidence),
                "Jardin Moderne : fiche officielle et agenda séparés obligatoires")
        detail=next((p for p in evidence
                     if p.get("proofType")=="official-organizer-or-venue"),None)
        calendar=next((p for p in evidence
                       if p.get("proofType")=="first-party-venue-calendar"),None)
        require(detail is not None and calendar is not None
                and detail.get("url")==spec["officialUrl"]
                and calendar.get("url")==spec["calendarUrl"]
                and detail.get("checkedAt")==checked.isoformat()
                and calendar.get("checkedAt")==checked.isoformat()
                and {"artists","date","venue","genre"}.issubset(
                    set(detail.get("checkedFields") or []))
                and {"artists","date","venue"}.issubset(
                    set(calendar.get("checkedFields") or []))
                and not ({"concertStartTime","startTime","doorTime"} &
                         set(detail.get("checkedFields") or []))
                and not ({"concertStartTime","startTime","doorTime"} &
                         set(calendar.get("checkedFields") or [])),
                "Jardin Moderne : preuves indépendantes ou horaires non fiables")
        resolved=dict(known_artist_ids)
        resolved.update(added)
        require(ids==spec["artistIds"]
                and [x["id"] for x in new_artists]==spec["newArtistIds"]
                and new_artists==[
                    {"id":aid,"name":spec["artistNames"][i]}
                    for i,aid in enumerate(ids) if aid in spec["newArtistIds"]]
                and len(ids)==len(spec["artistNames"])
                and all(aid in resolved and
                        norm(resolved[aid]["name"])==norm(name)
                        for aid,name in zip(ids,spec["artistNames"]))
                and all(norm(x["name"]) not in {
                    norm(y["name"]) for y in known_artist_ids.values()}
                        for x in new_artists),
                "Jardin Moderne : groupe nouveau non corroboré ou doublonné")
    elif event.get("venueId") == "bonjour-minuit-saint-brieuc":
        spec = BONJOUR_MINUIT_VERIFIED.get(event_id)
        require(spec is not None
                and reviewer == "independent-official-verifier"
                and event.get("sourceType") == "salle"
                and all(event.get(key) == spec[key] for key in
                        ("title", "date", "time", "venueId",
                         "artistIds", "genres", "status"))
                and event.get("organizer") is None
                and official_url == spec["officialUrl"],
                "Bonjour Minuit : affiche non homologuée, heure ou salle modifiée")
        u = urlsplit(official_url)
        require(u.scheme == "https" and u.hostname == "bonjour-minuit.fr"
                and u.path == urlsplit(spec["officialUrl"]).path
                and not u.query and not u.fragment and not u.username
                and not u.password and not u.port,
                "Bonjour Minuit : URL individuelle non conforme")
        checked = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= checked <= today,
                "Bonjour Minuit : preuve privée trop ancienne ou future")
        require(isinstance(evidence, list) and len(evidence) == 2
                and all(isinstance(p, dict) for p in evidence),
                "Bonjour Minuit : détail et agenda officiels obligatoires")
        proof = next((p for p in evidence
                      if p.get("proofType") == "official-organizer-or-venue"), None)
        calendar = next((p for p in evidence
                         if p.get("proofType") == "first-party-venue-calendar"), None)
        require(proof is not None and calendar is not None
                and proof.get("url") == spec["officialUrl"]
                and calendar.get("url") == spec["calendarUrl"]
                and proof.get("checkedAt") == checked.isoformat()
                and calendar.get("checkedAt") == checked.isoformat()
                and {"artists", "date", "venue", "genre"}.issubset(
                    set(proof.get("checkedFields") or []))
                and {"artists", "date", "venue"}.issubset(
                    set(calendar.get("checkedFields") or []))
                and not ({"concertStartTime", "startTime", "doorTime"} &
                         set(proof.get("checkedFields") or []))
                and not ({"concertStartTime", "startTime", "doorTime"} &
                         set(calendar.get("checkedFields") or [])),
                "Bonjour Minuit : source officielle non recoupée ou horaire inféré")
        # Only the four *named* artists on the individually signed SBRBS
        # page (or the already-published Magma) are permitted. Genre badges
        # and collector candidates alone cannot create artist identities.
        resolved = dict(known_artist_ids)
        resolved.update(added)
        require(ids == spec["artistIds"]
                and [a["id"] for a in new_artists] == spec["newArtistIds"]
                and new_artists == [
                    {"id":aid, "name":spec["artistNames"][i]}
                    for i,aid in enumerate(spec["artistIds"])
                    if aid in spec["newArtistIds"]]
                and len(ids) == len(spec["artistNames"])
                and all(aid in resolved
                        and norm(resolved[aid]["name"]) == norm(name)
                        for aid,name in zip(ids,spec["artistNames"]))
                and all(norm(x["name"]) not in {
                    norm(y["name"]) for y in known_artist_ids.values()}
                        for x in new_artists),
                "Bonjour Minuit : artistes, premières parties ou identifiants non prouvés")
    elif event.get("venueId") == "antipode-rennes":
        spec = ANTIPODE_RENNES_VERIFIED.get(event_id)
        require(spec is not None
                and reviewer == "independent-official-verifier"
                and event.get("sourceType") == "salle"
                and all(event.get(field) == spec[field] for field in
                        ("title","date","time","venueId","artistIds",
                         "genres","status","organizer"))
                and official_url == spec["officialUrl"],
                "Antipode : affiche, statut, horaire ou organisateur non agréé")
        u = urlsplit(official_url)
        require(u.scheme == "https" and u.hostname == "antipode-rennes.fr"
                and u.path == urlsplit(spec["officialUrl"]).path
                and re.fullmatch(r"/agenda/[a-z0-9-]+", u.path)
                and not u.query and not u.fragment and not u.username
                and not u.password and not u.port,
                "Antipode : fiche officielle individuelle nominative exigée")
        checked = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= checked <= today,
                "Antipode : revue indépendante périmée ou future")
        require(isinstance(evidence,list) and len(evidence)==2
                and all(isinstance(p,dict) for p in evidence),
                "Antipode : fiche et calendrier officiels distincts exigés")
        by_kind = {p.get("proofType"):p for p in evidence}
        require(set(by_kind)=={"official-organizer-or-venue",
                              "first-party-venue-calendar"},
                "Antipode : provenance des deux preuves non conforme")
        detail=by_kind["official-organizer-or-venue"]
        cal=by_kind["first-party-venue-calendar"]
        require(detail.get("url")==official_url
                and detail.get("checkedAt")==checked.isoformat()
                and {"artists","date","venue","genre","concertStartTime",
                     "doorTime"}.issubset(set(detail.get("checkedFields") or []))
                and detail.get("concertStartTimeConfirmed")==spec["time"]
                and detail.get("doorTimeConfirmed")==spec["doorTime"]
                and detail.get("soldOutOnDetailAtReview") is spec["soldOut"],
                "Antipode : début musical/portes ou complet non prouvé")
        require(cal.get("url")==spec["calendarUrl"]
                and cal.get("checkedAt")==checked.isoformat()
                and {"artists","date","venue"}.issubset(
                    set(cal.get("checkedFields") or []))
                and not ({"concertStartTime","doorTime","startTime"} &
                         set(cal.get("checkedFields") or [])),
                "Antipode : agenda nominatif ou année non corroborés")
        resolved=dict(known_artist_ids)
        resolved.update(added)
        require([a["id"] for a in new_artists]==spec["newArtistIds"]
                and new_artists==[
                    {"id":aid,"name":spec["artistNames"][i]}
                    for i,aid in enumerate(spec["artistIds"])
                    if aid in spec["newArtistIds"]]
                and len(ids)==len(spec["artistNames"])
                and all(aid in resolved
                        and norm(resolved[aid]["name"])==norm(name)
                        for aid,name in zip(ids,spec["artistNames"]))
                and all(norm(x["name"]) not in {
                    norm(y["name"]) for y in known_artist_ids.values()}
                        for x in new_artists),
                "Antipode : artistes, doublons ou premières parties invalides")
    elif event.get("venueId") == "le-bikini-toulouse":
        # New bills are only accepted after an independent, date-specific
        # verification against the venue detail AND first-party programme.
        spec = BIKINI_OFFICIAL_VERIFIED.get(event_id)
        require(spec is not None
                and reviewer == "independent-official-verifier"
                and event.get("sourceType") == "salle"
                and all(event.get(k) == spec[k] for k in
                        ("title", "date", "artistIds", "genres", "time"))
                and official_url == spec["officialUrl"],
                "Bikini : affiche non agréée ou champs modifiés")
        link = urlsplit(official_url)
        require(link.scheme == "https" and link.hostname == "lebikini.com"
                and re.fullmatch(r"/2026/11/(11|13|14|17|25|26|29)/[a-z0-9-]+", link.path)
                and not link.query and not link.fragment and not link.username
                and not link.password and not link.port,
                "Bikini : fiche individuelle officielle HTTPS exigée")
        checked = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= checked <= today,
                "Bikini : signature indépendante trop ancienne ou future")
        expected = {
            "official-organizer-or-venue": official_url,
            "first-party-venue-calendar": "https://lebikini.com/programmation/-/concert",
        }
        require(len(evidence) == 2
                and {p.get("proofType") for p in evidence if isinstance(p, dict)}
                    == set(expected),
                "Bikini : fiche et programmation officielles exigées")
        for proof in evidence:
            typ = proof.get("proofType") if isinstance(proof, dict) else None
            require(typ in expected and proof.get("url") == expected[typ]
                    and proof.get("checkedAt") == checked.isoformat()
                    and {"artists", "date", "venue", "genre"}.issubset(
                        set(proof.get("checkedFields") or []))
                    and "startTime" not in (proof.get("checkedFields") or []),
                    "Bikini : preuve officielle datée incomplète ou heure inventée")
        resolved = dict(known_artist_ids)
        resolved.update(added)
        require(new_artists == spec["newArtists"]
                and len(ids) == len(spec["artistNames"])
                and all(aid in resolved
                    and norm(resolved[aid]["name"]) == norm(name)
                    for aid, name in zip(ids, spec["artistNames"])),
                "Bikini : programmation ou identité d'artiste incohérente")
        require(event.get("time") is None,
                "Bikini : ouverture des portes ne prouve pas le début")
    elif event.get("venueId") == "secret-place-saint-jean-de-vedas":
        spec=SECRET_PLACE_DECEMBER_VERIFIED[event_id]
        require(reviewer=="independent-official-verifier"
                and event.get("sourceType")=="salle"
                and all(event.get(k)==spec[k] for k in
                        ("title","date","artistIds","genres","time"))
                and official_url==spec["officialUrl"],
                "Secret Place : seules deux affiches exactement vérifiées sont agréées")
        target=urlsplit(official_url)
        require(target.scheme=="https" and target.hostname=="www.toutafond.com"
                and target.path==urlsplit(spec["officialUrl"]).path
                and re.fullmatch(r"/event-details/[a-z0-9-]+",target.path)
                and not target.query and not target.fragment
                and not target.username and not target.password and not target.port,
                "Secret Place : URL officielle individuelle obligatoire")
        checked=norm_date(approval.get("reviewedAt"))
        require(today-dt.timedelta(days=14)<=checked<=today,
                "Secret Place : vérification dépassée")
        require(len(evidence)==2 and any(
            isinstance(p,dict)
            and p.get("url")==spec["officialUrl"]
            and p.get("proofType")=="official-organizer-or-venue"
            and p.get("checkedAt")==checked.isoformat()
            and {"artists","date","venue"}.issubset(set(p.get("checkedFields") or []))
            and "genre" not in (p.get("checkedFields") or [])
            and "startTime" not in (p.get("checkedFields") or [])
            for p in evidence) and any(
            isinstance(p,dict)
            and p.get("url")==spec["genreUrl"]
            and p.get("proofType")==spec["genreProofType"]
            and p.get("checkedAt")==checked.isoformat()
            and {"artists","date","venue","genre"}.issubset(
                set(p.get("checkedFields") or []))
            for p in evidence),
                "Secret Place : preuve de date/affiche ou genre indépendante insuffisante")
        require(event.get("time") is None,
                "Secret Place : créneau du calendrier n'est pas l'heure de début")
        resolved=dict(known_artist_ids)
        resolved.update(added)
        require([x["id"] for x in new_artists]==spec["newArtistIds"]
                and all(aid in resolved
                        and norm(resolved[aid]["name"]).replace(" ","-")==aid
                        for aid in ids),
                "Secret Place : artiste inventé ou mal orthographié")
    elif event.get("venueId") == "atabal-biarritz":
        spec=ATABAL_VERIFIED.get(event_id)
        require(spec is not None and reviewer=="independent-official-verifier"
                and event.get("sourceType")=="salle"
                and all(event.get(k)==spec[k] for k in
                        ("title","date","time","artistIds","genres"))
                and official_url==spec["officialUrl"],
                "Atabal : affiche non agréée, annulation, doublon ou date modifiée")
        u=urlsplit(official_url)
        require(u.scheme=="https" and u.hostname=="www.atabal-biarritz.fr"
                and re.fullmatch(r"/agenda/concerts/[a-z0-9-]{16,220}/",u.path)
                and u.path==urlsplit(spec["officialUrl"]).path
                and not u.username and not u.password and not u.port
                and not u.query and not u.fragment,
                "Atabal : URL officielle individuelle exacte obligatoire")
        checked=norm_date(approval.get("reviewedAt"))
        require(today-dt.timedelta(days=14)<=checked<=today,
                "Atabal : revue nominative trop ancienne")
        require(len(evidence)==2 and any(
                isinstance(p,dict) and p.get("url")==spec["officialUrl"]
                and p.get("proofType")=="official-organizer-or-venue"
                and p.get("checkedAt")==checked.isoformat()
                and {"artists","date","venue","genre"}.issubset(
                    set(p.get("checkedFields") or []))
                for p in evidence) and any(
                isinstance(p,dict) and p.get("url")==
                    "https://www.atabal-biarritz.fr/agenda/concerts/"
                and p.get("proofType")=="first-party-venue-calendar"
                and p.get("checkedAt")==checked.isoformat()
                and {"artists","date","venue"}.issubset(
                    set(p.get("checkedFields") or []))
                for p in evidence),
                "Atabal : fiche individuelle et agenda datés exigés")
        resolved=dict(known_artist_ids)
        resolved.update(added)
        require([a["id"] for a in new_artists]==spec["newArtistIds"]
                and all(i in resolved and norm(resolved[i]["name"]).replace(" ","-")==i
                        for i in ids),
                "Atabal : groupes ou nouvelles identités non conformes")
    elif event.get("venueId") == "hydrophone-lorient":
        spec=HYDROPHONE_VERIFIED.get(event_id)
        require(spec is not None and reviewer=="independent-official-verifier"
                and event.get("venueId")==spec["venueId"]
                and event.get("sourceType")=="salle"
                and all(event.get(k)==spec[k] for k in
                        ("title","date","time","artistIds","genres"))
                and official_url==spec["officialUrl"],
                "Hydrophone : affiche non homologuée ou festival")
        u=urlsplit(official_url)
        ticket=urlsplit(spec["secondaryUrl"])
        require(u.scheme=="https" and u.hostname=="hydrophone.fr"
                and u.path=="/REVNOIR-ICE-SEALED-EYES.html"
                and not u.query and not u.fragment and
                not u.username and not u.password and not u.port
                and ticket.scheme=="https"
                and ticket.hostname=="www.fnacspectacles.com"
                and ticket.path.endswith(
                    "/revnoir-sometimes-i-feel-you-sometimes-i-dont-tour-hydrophone-lorient-21627359/"),
                "Hydrophone : URL individuelle ou justificatif année changé")
        reviewed=norm_date(approval.get("reviewedAt"))
        require(today-dt.timedelta(days=14)<=reviewed<=today,
                "Hydrophone : recoupement trop ancien ou futur")
        require(len(evidence)==2
                and {p.get("proofType") for p in evidence if isinstance(p,dict)}
                    == {"official-organizer-or-venue",
                        spec["secondaryProofType"]},
                "Hydrophone : deux sources distinctes datées nécessaires")
        primary=next((p for p in evidence
            if isinstance(p,dict) and p.get("proofType")==
            "official-organizer-or-venue"),{})
        secondary=next((p for p in evidence
            if isinstance(p,dict) and p.get("proofType")==
            spec["secondaryProofType"]),{})
        require(primary.get("url")==spec["officialUrl"]
                and primary.get("checkedAt")==reviewed.isoformat()
                and {"artists","day","month","venue","genre","startTime"}.issubset(set(primary.get("checkedFields") or [])),
                "Hydrophone : preuve première source incomplète")
        require(secondary.get("url")==spec["secondaryUrl"]
                and secondary.get("checkedAt")==reviewed.isoformat()
                and {"artists","date","year","venue","startTime"}.issubset(set(secondary.get("checkedFields") or []))
                and secondary.get("dateConfirmed")==spec["date"]
                and secondary.get("startTimeConfirmed")==spec["time"],
                "Hydrophone : année 2027 et heure non recoupées sur billetterie")
        require(new_artists==[] and all(i in known_artist_ids for i in ids)
                and all(norm(known_artist_ids[i]["name"]).replace(" ","-")==i
                        for i in ids),
                "Hydrophone : artistes existants ou noms incohérents")
    elif event.get("venueId") == "la-carene-brest":
        spec=CARENE_VERIFIED.get(event_id)
        require(spec is not None
                and reviewer=="independent-official-verifier"
                and event.get("sourceType")=="salle"
                and all(event.get(k)==spec[k] for k in
                        ("title","date","time","artistIds","genres"))
                and official_url==spec["officialUrl"],
                "La Carène : seule une affiche hors festival vérifiée est admissible")
        u=urlsplit(official_url)
        require(u.scheme=="https" and u.hostname=="www.lacarene.fr"
                and u.path==urlsplit(spec["officialUrl"]).path
                and re.fullmatch(r"/[a-z0-9-]+\.html",u.path)
                and not u.username and not u.password and not u.port
                and not u.query and not u.fragment,
                "La Carène : URL individuelle officielle non conforme")
        checked=norm_date(approval.get("reviewedAt"))
        require(today-dt.timedelta(days=14)<=checked<=today,
                "La Carène : vérification nominative expirée ou future")
        require(len(evidence)==2 and any(
                isinstance(p,dict) and p.get("url")==spec["officialUrl"]
                and p.get("proofType")=="official-organizer-or-venue"
                and p.get("checkedAt")==checked.isoformat()
                and {"artists","date","venue","genre","startTime"}.issubset(
                    set(p.get("checkedFields") or []))
                for p in evidence) and any(
                isinstance(p,dict) and p.get("url")=="https://www.lacarene.fr/-agenda-.html"
                and p.get("proofType")=="first-party-venue-calendar"
                and p.get("checkedAt")==checked.isoformat()
                and {"artists","date","venue"}.issubset(
                    set(p.get("checkedFields") or []))
                for p in evidence),
                "La Carène : agenda et fiche individuelle contrôlés à part requis")
        resolved=dict(known_artist_ids)
        resolved.update(added)
        require([x["id"] for x in new_artists]==spec["newArtistIds"]
                and all(i in resolved and norm(resolved[i]["name"]).replace(" ","-")==i
                        for i in ids),
                "La Carène : noms des artistes incompatibles")
    elif event.get("venueId") == "la-cave-aux-poetes-roubaix":
        spec=CAVE_POETES_VERIFIED.get(event_id)
        require(spec is not None
                and reviewer=="independent-official-verifier"
                and event.get("sourceType")=="salle"
                and all(event.get(k)==spec[k] for k in
                        ("title","date","time","artistIds","genres"))
                and official_url==spec["officialUrl"],
                "Cave aux Poètes : affiche non explicitement vérifiée")
        u=urlsplit(official_url)
        require(u.scheme=="https" and u.hostname=="caveauxpoetes.com"
                and u.path==urlsplit(spec["officialUrl"]).path
                and not u.username and not u.password and not u.port
                and not u.query and not u.fragment,
                "Cave aux Poètes : page officielle exacte exigée")
        checked=norm_date(approval.get("reviewedAt"))
        require(today-dt.timedelta(days=14)<=checked<=today,
                "Cave aux Poètes : preuve trop ancienne")
        require(len(evidence)==2 and any(
            isinstance(p,dict)
            and p.get("url")==spec["officialUrl"]
            and p.get("proofType")=="official-organizer-or-venue"
            and p.get("checkedAt")==checked.isoformat()
            and {"artists","date","venue","genre","startTime"}.issubset(
                set(p.get("checkedFields") or []))
            for p in evidence) and any(
            isinstance(p,dict)
            and p.get("url")==spec["organizerCalendar"]
            and p.get("proofType")==spec.get("calendarProofType","organizer-submitted-calendar")
            and p.get("checkedAt")==checked.isoformat()
            and set(spec.get("calendarCheckedFields",
                         ["artists","date","venue","startTime"])).issubset(
                set(p.get("checkedFields") or []))
            for p in evidence),
                "Cave aux Poètes : fiche officielle et recoupement de programmation requis")
        resolved=dict(known_artist_ids)
        resolved.update(added)
        require([x["id"] for x in new_artists]==spec["newArtistIds"]
                and all(aid in resolved for aid in ids)
                and all(norm(resolved[aid]["name"]).replace(" ","-")==aid
                        for aid in ids),
                "Cave aux Poètes : noms ou identifiants d'artistes non corroborés")
    elif event.get("venueId") == "le-forum-vaureal":
        spec=FORUM_VERIFIED.get(event_id)
        require(spec is not None
                and reviewer=="independent-official-verifier"
                and event.get("sourceType")=="salle"
                and all(event.get(k)==spec[k] for k in
                        ("title","date","artistIds","genres","time"))
                and official_url==spec["officialUrl"],
                "Le Forum : seule une affiche officielle nominative agréée est admise")
        u=urlsplit(official_url)
        require(u.scheme=="https" and u.hostname=="leforum.cergypontoise.fr"
                and re.fullmatch(r"/agenda/[a-z0-9-]+",u.path)
                and u.path==urlsplit(spec["officialUrl"]).path
                and not u.username and not u.password and not u.port
                and not u.query and not u.fragment,
                "Le Forum : fiche individuelle sous domaine officiel obligatoire")
        checked=norm_date(approval.get("reviewedAt"))
        require(today-dt.timedelta(days=14)<=checked<=today,
                "Le Forum : vérification humaine trop ancienne")
        fields={"artists","date","venue","genre"}
        if spec["time"] is not None:
            fields.add("startTime")
        secondary_url=spec.get("secondaryUrl")
        secondary_type=spec.get("secondaryProofType")
        require(len(evidence)==(2 if secondary_url else 1) and any(
            isinstance(p,dict)
            and p.get("url")==spec["officialUrl"]
            and p.get("proofType")=="official-organizer-or-venue"
            and p.get("checkedAt")==checked.isoformat()
            and fields.issubset(set(p.get("checkedFields") or []))
            for p in evidence),
                "Le Forum : preuve exacte d'affiche et début manquante")
        if secondary_url:
            # Tour/artist source corroborates venue, exact date and every
            # artist; it must not be mistaken for venue clock verification.
            require(any(
                isinstance(p,dict)
                and p.get("url")==secondary_url
                and p.get("proofType")==secondary_type
                and p.get("checkedAt")==checked.isoformat()
                and {"artists","date","venue"}.issubset(
                    set(p.get("checkedFields") or []))
                for p in evidence),
                    "Le Forum : preuve indépendante du festival ou artiste manquante")
        resolved=dict(known_artist_ids)
        resolved.update(added)
        require([a["id"] for a in new_artists]==spec["newArtistIds"]
                and all(aid in resolved for aid in ids)
                and all(norm(resolved[aid]["name"]).replace(" ","-")==aid
                        for aid in ids),
                "Le Forum : artiste manquant ou identité non fiable")
        if event_id=="go-c-20261107-vaureal-wolves-throne-room":
            require(event["time"] is None,
                    "Le Forum : deux heures contradictoires pour Wolves")
    elif event.get("venueId") in ("la-maroquinerie-paris","la-boule-noire-paris"):
        spec=PARIS_CLUB_VERIFIED.get(event_id)
        require(spec is not None
                and spec["venueId"]==event["venueId"]
                and reviewer=="independent-official-verifier"
                and event.get("sourceType")=="salle"
                and all(event.get(k)==spec[k] for k in
                        ("title","date","artistIds","genres"))
                and event.get("time") is None
                and official_url==spec["officialUrl"],
                "Clubs parisiens : programme, date ou heure hors liste blanche")
        target=urlsplit(official_url)
        domain=("www.lamaroquinerie.fr" if event["venueId"]=="la-maroquinerie-paris"
                else "laboule-noire.fr")
        require(target.scheme=="https" and target.hostname==domain
                and target.username is None and target.password is None
                and target.port is None and target.fragment==""
                and (target.query in ("","of=7","of=18"))
                and target.path==urlsplit(spec["officialUrl"]).path,
                "Clubs parisiens : origine et page individuelle non agréées")
        reviewed_at=norm_date(approval.get("reviewedAt"))
        require(today-dt.timedelta(days=14)<=reviewed_at<=today,
                "Clubs parisiens : revue humaine trop ancienne")
        proofs=spec["proofs"]
        require(len(evidence)==len(proofs), "Nombre de preuves insuffisant")
        for kind,url,fields in proofs:
            require(any(isinstance(p,dict)
                and p.get("proofType")==kind and p.get("url")==url
                and p.get("checkedAt")==reviewed_at.isoformat()
                and set(fields).issubset(set(p.get("checkedFields") or []))
                for p in evidence),
                "Clubs parisiens : preuve manquante ou champs exagérés")
        resolved=dict(known_artist_ids)
        resolved.update(added)
        require([a["id"] for a in new_artists]==spec["newArtistIds"]
                and all(i in resolved and
                        norm(resolved[i]["name"]).replace(" ","-")==i
                        for i in ids),
                "Clubs parisiens : nouveaux artistes ou identités ambigus")
    elif event.get("venueId") == "le-trabendo-paris":
        spec = TRABENDO_VERIFIED.get(event_id)
        require(spec is not None
                and reviewer == "independent-official-verifier"
                and event.get("sourceType") == "salle"
                and all(event.get(k) == spec[k] for k in
                        ("title","date","artistIds","genres"))
                and event.get("time") is None
                and official_url == spec["officialUrl"],
                "Trabendo : seul un concert explicitement inscrit dans la liste blanche est admis")
        u = urlsplit(official_url)
        require(u.scheme == "https" and u.hostname == "www.letrabendo.net"
                and u.path in {
                    urlsplit(approved["officialUrl"]).path
                    for approved in TRABENDO_VERIFIED.values()
                }
                and not u.username and not u.password and not u.port
                and not u.query and not u.fragment,
                "Trabendo : fiche individuelle de salle exigée")
        reviewed_at = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= reviewed_at <= today,
                "Trabendo : preuve trop ancienne ou future")
        require(len(evidence) == 1 and any(
                isinstance(p,dict)
                and p.get("url") == official_url
                and p.get("proofType") == "official-organizer-or-venue"
                and p.get("checkedAt") == reviewed_at.isoformat()
                and {"artists","date","venue","genre"}.issubset(
                    set(p.get("checkedFields") or []))
                for p in evidence),
                "Trabendo : preuve nominative officielle incomplète")
        resolved=dict(known_artist_ids)
        resolved.update(added)
        require([a["id"] for a in new_artists] == spec["newArtistIds"]
                and all(i in resolved and
                        norm(resolved[i]["name"]).replace(" ","-") == i
                        for i in ids),
                "Trabendo : artistes ou identités non vérifiés")
    elif event.get("venueId") == "glazart-paris":
        spec = GLAZART_VERIFIED.get(event_id)
        require(spec is not None
                and reviewer == "independent-official-verifier"
                and event.get("sourceType") == "salle"
                and all(event.get(k) == spec[k] for k in
                        ("title","date","artistIds","genres"))
                and official_url == spec["officialUrl"]
                and event.get("time") is None,
                "Glazart : concert non compris dans les preuves nominatives agréées")
        parsed = urlsplit(official_url)
        require(parsed.scheme=="https" and parsed.hostname=="www.glazart.com"
                and not parsed.username and not parsed.password
                and not parsed.port and not parsed.query and not parsed.fragment
                and re.fullmatch(r"/(?:04-11-26|06-11-26|14-11-26|30-11-26|28-11-26|24-03-27)-concert-[a-z0-9-]+/",
                                 parsed.path),
                "Glazart : page individuelle ou domaine non agréés")
        reviewed_at = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= reviewed_at <= today,
                "Glazart : validation indépendante trop ancienne")
        primary_fields=set(spec.get("primaryCheckedFields",
                                     ["artists","date","venue","genre"]))
        require(any(isinstance(p,dict)
                and p.get("url")==spec["officialUrl"]
                and p.get("proofType")=="official-organizer-or-venue"
                and p.get("checkedAt")==reviewed_at.isoformat()
                and primary_fields.issubset(set(p.get("checkedFields") or []))
                for p in evidence),
                "Glazart : preuve officielle du programme manquante ou exagérée")
        if spec.get("secondaryUrl"):
            # No source inflation: an abbreviated Glazart headline cannot
            # prove the named supporting artist. Verify the exact promoter
            # ticket (specific host, path and named programme) independently.
            other=[p for p in evidence if isinstance(p,dict) and
                   p.get("proofType")==spec["secondaryProofType"]]
            require(len(evidence)==2 and len(other)==1 and
                    other[0].get("url")==spec["secondaryUrl"] and
                    other[0].get("checkedAt")==reviewed_at.isoformat() and
                    set(spec["secondaryCheckedFields"]).issubset(
                        set(other[0].get("checkedFields") or [])),
                    "Glazart : billetterie nominative secondaire absente ou remplacée")
        else:
            require(len(evidence)==1,
                    "Glazart : preuves inattendues sur fiche pleinement nominative")
        resolved=dict(known_artist_ids)
        resolved.update(added)
        require([a["id"] for a in new_artists]==spec["newArtistIds"]
                and all(i in resolved for i in ids)
                and all(norm(resolved[i]["name"]).replace(" ","-")==i
                        for i in ids),
                "Glazart : identité de groupe ou nouvel artiste incohérent")
    elif event.get("venueId") in ("rock-n-eat-lyon",
                                   "la-maison-bleue-strasbourg"):
        spec = REGIONAL_APPROVED.get(event_id)
        require(spec is not None
                and event.get("venueId") == spec["venueId"]
                and reviewer == "independent-official-verifier"
                and event.get("sourceType") == "organisateur"
                and all(event.get(k) == spec[k] for k in
                        ("title", "date", "artistIds", "genres"))
                and official_url == spec["officialUrl"]
                and event.get("ticketUrl") == spec["officialUrl"]
                and event.get("time") is None,
                "Salles régionales : seules les deux affiches vérifiées sont admises")
        reviewed_at = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= reviewed_at <= today,
                "Salles régionales : recoupement trop ancien")
        require(len(evidence) == 2
                and {p.get("proofType") for p in evidence if isinstance(p,dict)}
                    == {"official-organizer-or-venue","first-party-venue-calendar"},
                "Salles régionales : billetterie organisateur et agenda officiel requis")
        expected_proofs = {
            "official-organizer-or-venue": spec["officialUrl"],
            "first-party-venue-calendar": spec["venueCalendar"]
        }
        # Local Heroes: the ticket names all four artists but does not tag a
        # music genre; Maison Bleue's own calendar tags the listing "Métal"
        # but does not list those four names. Keep provenance separate.
        def required_fields(proof_type):
            if event_id == "go-c-20261113-strasbourg-local-heroes":
                if proof_type == "official-organizer-or-venue":
                    return {"artists","date","venue"}
                return {"date","venue","genre"}
            if (event["venueId"] == "rock-n-eat-lyon" and
                    proof_type == "first-party-venue-calendar"):
                return {"artists","date","venue"}
            return {"artists","date","venue","genre"}
        require(all(
            isinstance(p,dict)
            and p.get("url") == expected_proofs.get(p.get("proofType"))
            and p.get("checkedAt") == reviewed_at.isoformat()
            and required_fields(p.get("proofType")).issubset(
                set(p.get("checkedFields") or []))
            for p in evidence),
            "Salles régionales : origine ou contenu de preuve modifiés")
        target = urlsplit(official_url)
        allow_rock=(event["venueId"]=="rock-n-eat-lyon"
                    and target.hostname=="shotgun.live"
                    and target.path=="/events/lagrimas-the-prestige")
        allow_maison=(event["venueId"]=="la-maison-bleue-strasbourg"
                      and target.hostname=="billetterie.lamaisonbleue-stbg.com"
                      and target.path in (
                        "/share/event/370-Dirty8-Birthday-WAKE-THE-DEAD-SICK-LAME-LAZY",
                        "/share/event/385-Dirty8-Birthday-LOCAL-HEROES-Dazzling-Bravery-BRDN-Curtains-Foggy-Froggies"))
        require(target.scheme=="https" and (allow_rock or allow_maison)
                and not target.username and not target.password
                and not target.port and not target.query and not target.fragment,
                "Salles régionales : lien de preuve exact requis")
        resolved=dict(known_artist_ids)
        resolved.update(added)
        require([a["id"] for a in new_artists]==spec["newArtistIds"]
                and all(artist_id in resolved for artist_id in ids)
                and all(norm(resolved[artist_id]["name"]).replace(" ","-")==artist_id
                        for artist_id in ids),
                "Salles régionales : artistes inconnus ou identités ambiguës")
    elif event.get("venueId") == "le-rocher-de-palmer-cenon":
        # Event-by-event first-party verification. Do NOT allow unreviewed
        # generic venue agenda listings, third-party tickets or other bills.
        spec = ROCHER_PALMER_VERIFIED.get(event_id)
        require(spec is not None and reviewer == "independent-official-verifier"
                and event.get("sourceType") == "salle"
                and all(event.get(field) == spec[field] for field in
                        ("title", "date", "artistIds", "genres", "time"))
                and official_url == spec["officialUrl"],
                "Rocher de Palmer : affiche non vérifiée ou altérée")
        parsed = urlsplit(official_url)
        require(parsed.scheme == "https" and parsed.hostname == "lerocherdepalmer.fr"
                and re.fullmatch(r"/agenda/[a-z0-9-]+", parsed.path)
                and not parsed.username and not parsed.password and not parsed.port
                and not parsed.query and not parsed.fragment,
                "Rocher de Palmer : lien individuel officiel exact requis")
        reviewed_at = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= reviewed_at <= today,
                "Rocher de Palmer : vérification ancienne ou future")
        require(len(evidence) == 1 and all(
            p.get("url") == official_url
            and p.get("proofType") == "official-organizer-or-venue"
            and p.get("checkedAt") == reviewed_at.isoformat()
            and {"artists", "date", "venue", "genre", "startTime"}.issubset(
                set(p.get("checkedFields") or []))
            for p in evidence if isinstance(p, dict)),
            "Rocher de Palmer : preuve primaire nominative complète requise")
        resolved = dict(known_artist_ids)
        resolved.update(added)
        require(all(aid in resolved for aid in ids)
                and all(norm(resolved[aid]["name"]).replace(" ", "-") == aid
                        or (aid == "m-l" and resolved[aid]["name"] == "MØL")
                        for aid in ids)
                and all(norm(a["name"]).replace(" ", "-") == a["id"]
                        for a in new_artists),
                "Rocher de Palmer : identité d'artiste incertaine")
    elif event.get("venueId") == "backstage-by-the-mill-paris":
        # For this pilot venue, an independent reviewer must explicitly sign
        # one of the three EXACT official bills and the artist identities.
        spec = BACKSTAGE_VERIFIED.get(event_id)
        require(spec is not None and reviewer == "independent-official-verifier"
                and event.get("sourceType") == "salle"
                and all(event.get(k) == spec[k] for k in
                        ("title", "date", "artistIds", "genres"))
                and official_url == spec["url"] and event.get("time") is None,
                "Backstage : concert hors liste blanche ou heure non documentée")
        target = urlsplit(official_url)
        require(target.scheme == "https" and
                target.hostname == "www.backstage-btm.com"
                and not target.username and not target.password
                and not target.port and not target.query and not target.fragment
                and re.fullmatch(r"/agenda/[a-z0-9-]+/", target.path),
                "Backstage : fiche événement individuelle HTTPS obligatoire")
        reviewed_at = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= reviewed_at <= today,
                "Backstage : relecture trop ancienne ou future")
        require(any(
            isinstance(p, dict) and p.get("url") == spec["url"]
            and p.get("proofType") == "official-organizer-or-venue"
            and p.get("checkedAt") == reviewed_at.isoformat()
            and {"artists","date","venue","genre"}.issubset(
                set(p.get("checkedFields") or []))
            for p in evidence),
            "Backstage : preuve officielle datée et détaillée manquante")
        resolved = dict(known_artist_ids)
        resolved.update(added)
        require(len(ids) == len(spec["artistIds"])
                and all(a in resolved for a in ids)
                and all(norm(resolved[a]["name"]).replace(" ", "-") == a
                        for a in ids)
                and all(norm(a["name"]).replace(" ", "-") == a["id"]
                        for a in new_artists),
                "Backstage : artiste absent, identité ou slug incohérents")
    elif event.get("venueId") == "jokers-pub-angers":
        require(reviewer == "independent-official-verifier"
                and reviewer == "independent-official-verifier"
                and event.get("sourceType") == "salle",
                "Nouvelle salle : validation concert manuelle indépendante requise")
        parsed = urlsplit(official_url)
        require(parsed.hostname == "www.jokerspubangers.com"
                and parsed.scheme == "https" and not parsed.username
                and not parsed.password and not parsed.query and not parsed.fragment
                and re.fullmatch(
                    r"/jokers-concert-programmation-[a-z0-9+_.-]+\.html",
                    parsed.path, flags=re.I),
                "Page individuelle du Joker's Pub obligatoire")
        reviewed_at = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= reviewed_at <= today,
                "Validation indépendante du concert trop ancienne")
        require(any(
            item.get("url") == official_url and
            item.get("proofType") == "official-organizer-or-venue" and
            item.get("checkedAt") == reviewed_at.isoformat() and
            {"artists", "date", "venue", "genre", "startTime"}.issubset(
                set(item.get("checkedFields") or []))
            for item in evidence if isinstance(item, dict)),
            "Page officielle Joker sans preuve datée des champs nécessaires")
        require(bool(event.get("time")), "Heure de début officielle non attestée")
        # A previously known artist must resolve to the exact named act.
        resolved = dict(known_artist_ids)
        resolved.update(added)
        require(all(x in resolved for x in ids)
                and all(x["id"] == norm(x["name"]).replace(" ", "-")
                        and x["id"] in ids for x in new_artists),
                "Identité des artistes de la nouvelle salle non sûre")
        require(any(re.search(r"\b(punk|hardcore|metal|doom|stoner)\b",
                              norm(label))
                    for label in event["genres"]),
                "Genre punk/métal de la nouvelle salle non documenté")
    elif event.get("venueId") == "le-brin-de-zinc-barberaz":
        # This is a manual, event-specific exception, not an aggregator rule.
        # Both channels explicitly attribute their event to BRIN DE ZINC.
        require(reviewer == "independent-official-verifier"
                and event.get("sourceType") == "organisateur",
                "Brin de Zinc : signature de vérification indépendante exigée")
        expected = BRIN_ORGANIZER_VERIFIED.get(event_id)
        require(expected is not None and
                all(event.get(field) == expected[field] for field in
                    ("title", "date", "artistIds", "genres"))
                and official_url == expected["ticketUrl"]
                and event.get("ticketUrl") == official_url,
                "Brin de Zinc : concert ou billet hors liste blanche vérifiée")
        parsed = urlsplit(official_url)
        require(parsed.scheme == "https" and
                parsed.hostname == "www.billetweb.fr" and not parsed.username
                and not parsed.password and not parsed.query
                and not parsed.fragment and parsed.path != "/multi_event.php",
                "Brin de Zinc : fiche de billetterie individuelle exigée")
        reviewed_at = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= reviewed_at <= today,
                "Brin de Zinc : recoupement trop ancien")
        require(event.get("time") is None,
                "Créneau Billetweb ne prouve pas le début du concert")
        partner_kind = expected.get("partnerProofType", "organizer-submitted-partner")
        partner_fields = set(expected.get("partnerCheckedFields",
                                          ["artists", "date", "venue", "genre"]))
        require(len(evidence) == 2 and
                {p.get("proofType") for p in evidence if isinstance(p,dict)}
                == {"official-organizer-or-venue", partner_kind},
                "Brin de Zinc : deux preuves individuellement autorisées requises")
        checks = {
            "official-organizer-or-venue": (expected["ticketUrl"],
                                             {"artists", "date", "venue", "genre"}),
            partner_kind: (expected["partnerUrl"], partner_fields),
        }
        for proof in evidence:
            spec = checks.get(proof.get("proofType")) if isinstance(proof,dict) else None
            require(spec is not None and
                    proof.get("url") == spec[0] and
                    proof.get("checkedAt") == reviewed_at.isoformat() and
                    spec[1].issubset(set(proof.get("checkedFields") or [])),
                    "Brin de Zinc : preuve de partenaire incomplète ou substituée")
        resolved = dict(known_artist_ids)
        resolved.update(added)
        require(all(aid in resolved for aid in ids)
                and all(norm(resolved[aid]["name"]).replace(" ","-") == aid
                        for aid in ids)
                and all(norm(a["name"]).replace(" ","-") == a["id"]
                        for a in new_artists),
                "Brin de Zinc : identités d'artistes incohérentes")
        require(any(re.search(r"\b(punk|hardcore|metal|doom|stoner)\b",
                              norm(genre)) for genre in event["genres"]),
                "Brin de Zinc : genre métal/punk officiel absent")
    elif event.get("venueId") in ("l-astrolabe-orleans", "le-106-rouen"):
        # Two regional venues: require a named first-party event and exact
        # field-level supporting evidence. Neither clock nor generic event
        # listing is enough to invent a musical start time.
        venue_id = event["venueId"]
        host, pattern = (
            ("www.lastrolabe.org", r"/agenda/[a-z0-9-]+/")
            if venue_id == "l-astrolabe-orleans"
            else ("le106.com", r"/agenda/[a-z0-9-]+")
        )
        u = urlsplit(official_url)
        require(reviewer == "independent-official-verifier"
                and event["sourceType"] == "salle" and event.get("time") is None
                and u.hostname == host and re.fullmatch(pattern, u.path)
                and not u.username and not u.password and not u.port
                and not u.query and not u.fragment,
                "Astrolabe/106 : vérificateur, fiche officielle ou horaire invalides")
        reviewed = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= reviewed <= today,
                "Astrolabe/106 : date de vérification invalide")
        require(len(evidence) == 2 and all(isinstance(p, dict) for p in evidence),
                "Astrolabe/106 : deux preuves documentaires distinctes nécessaires")
        primary, secondary = evidence
        fields = set(primary.get("checkedFields") or [])
        require(primary.get("url") == official_url
                and primary.get("proofType") == "official-organizer-or-venue"
                and primary.get("checkedAt") == reviewed.isoformat()
                and ({"artists", "venue", "genre"}.issubset(fields)
                     and "date" not in fields
                     if event_id in ROUEN_ROCK_PAGED_VERIFIED
                     else {"date", "venue", "genre"}.issubset(fields)
                          and ("artists" in fields or "leadArtist" in fields))
                and "startTime" not in fields,
                "Astrolabe/106 : fiche individuelle ou attribution de date incorrecte")
        allowed_second = ({
            "first-party-venue-calendar": "https://www.lastrolabe.org/agenda/",
            "independent-organizer-confirmation":
                "https://www.helloasso.com/associations/slaptrack/evenements/final-show-orpheum-black",
            "independent-local-radio-announcement":
                "https://www.intensite.net/orleans-45-concert-la-jungle-sodom-sagesse",
        } if venue_id == "l-astrolabe-orleans" else {
            "first-party-venue-calendar": (
                ROUEN_ROCK_PAGED_VERIFIED[event_id]["calendarUrl"]
                if event_id in ROUEN_ROCK_PAGED_VERIFIED
                else "https://le106.com/agenda"
            ),
            "authorized-ticket-distributor":
                "https://www.eventim.fr/eventseries/cosmic-trip-tour-4197731/",
            "independent-organizer-tour":
                "https://www.aegpresents.fr/event/dynamite-shakers/",
        })
        secondary_fields = set(secondary.get("checkedFields") or [])
        require(secondary.get("proofType") in allowed_second
                and secondary.get("url") == allowed_second.get(secondary.get("proofType"))
                and secondary.get("url") != official_url
                and secondary.get("checkedAt") == reviewed.isoformat()
                and {"artists", "date", "venue"}.issubset(secondary_fields)
                and "startTime" not in secondary_fields,
                "Astrolabe/106 : deuxième preuve ou liste d'artistes non conforme")
        resolved = dict(known_artist_ids)
        resolved.update(added)
        require(all(
            aid in resolved and (
                norm(resolved[aid]["name"]).replace(" ", "-") == aid
                or (venue_id == "le-106-rouen" and aid == "yu-band"
                    and resolved[aid]["name"] == "YÜ")
            ) for aid in ids),
                "Astrolabe/106 : identité des groupes non corroborée")
        if event_id in ROUEN_DEATH_VALLEY_SIGNED:
            spec = ROUEN_DEATH_VALLEY_SIGNED[event_id]
            require(all(event.get(field) == spec[field] for field in (
                    "title", "date", "time", "venueId", "artistIds", "genres"))
                    and official_url == spec["officialUrl"]
                    and event.get("sourceType") == "salle"
                    and new_artists == [],
                    "Le 106 : affiche Death Valley Girls altérée ou non approuvée")
            require(primary.get("url") == spec["officialUrl"]
                    and primary.get("proofType") == "official-organizer-or-venue"
                    and {"artists", "date", "venue", "genre"}.issubset(fields)
                    and secondary.get("url") == spec["calendarUrl"]
                    and secondary.get("proofType") == "first-party-venue-calendar"
                    and {"artists", "date", "venue"}.issubset(secondary_fields),
                    "Le 106 : preuves individuelles et agenda nominatif obligatoires")
            require(len(ids) == 2
                    and norm(resolved[ids[0]]["name"]) == "death valley girls"
                    and norm(resolved[ids[1]]["name"]) == "bella and the bizarre",
                    "Le 106 : noms de groupe non conformes aux deux artistes publiés")

        if event_id in ROUEN_ROCK_PAGED_VERIFIED:
            spec = ROUEN_ROCK_PAGED_VERIFIED[event_id]
            require(reviewer == "independent-official-verifier"
                    and event.get("sourceType") == "salle"
                    and event.get("time") is None
                    and all(event.get(field) == spec[field] for field in (
                        "title","date","time","venueId","artistIds","genres"))
                    and official_url == spec["officialUrl"],
                    "Le 106 : nouvelle affiche rock hors liste nominative")
            require(primary.get("url") == spec["officialUrl"]
                    and primary.get("proofType") == "official-organizer-or-venue"
                    and {"artists", "venue", "genre"}.issubset(fields)
                    and "date" not in fields
                    and secondary.get("url") == spec["calendarUrl"]
                    and secondary.get("proofType") == "first-party-venue-calendar"
                    and {"artists", "date", "venue"}.issubset(secondary_fields),
                    "Le 106 : preuve officielle + page datée de l'agenda exigées")
            require(new_artists == [
                {"id":aid,"name":spec["artistNames"][i]}
                for i,aid in enumerate(spec["artistIds"])
                if aid in spec["newArtistIds"]],
                "Le 106 : nouveaux artistes ou têtes d'affiche altérés")
            require(len(ids) == len(spec["artistNames"]) and all(
                aid in resolved
                and norm(resolved[aid]["name"]) == norm(name)
                for aid,name in zip(ids,spec["artistNames"])),
                "Le 106 : noms réels des deux groupes non vérifiés")
    elif event.get("venueId") == "le-chatodo-blois":
        # A valid venue pin is NEVER sufficient to approve an unchecked bill.
        # Both venue and three exact event dates were individually signed.
        spec = CHATODO_VERIFIED.get(event_id)
        require(spec is not None
                and reviewer == "independent-official-verifier"
                and event.get("sourceType") == "salle"
                and event.get("time") is None
                and all(event.get(k) == spec[k] for k in
                        ("title", "date", "time", "artistIds", "genres"))
                and official_url == spec["officialUrl"],
                "Chato'do : date ou artistes hors liste nominative")
        url = urlsplit(official_url)
        require(url.scheme == "https" and url.hostname == "chatodo.com"
                and re.fullmatch(r"/agenda/evenement/[a-z0-9-]+/", url.path)
                and url.path == urlsplit(spec["officialUrl"]).path
                and not url.username and not url.password and not url.port
                and not url.query and not url.fragment,
                "Chato'do : URL officielle individuelle exacte exigée")
        reviewed = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= reviewed <= today,
                "Chato'do : preuve périmée ou future")
        require(len(evidence) == 2
                and {p.get("proofType") for p in evidence if isinstance(p, dict)}
                == {"official-organizer-or-venue", "first-party-venue-calendar"},
                "Chato'do : détail et agenda officiels distincts requis")
        checks = {
            "official-organizer-or-venue": (
                spec["officialUrl"], {"artists", "date", "venue", "genre"}),
            "first-party-venue-calendar": (
                "https://chatodo.com/agenda/",
                {"leadArtist", "dayMonth", "genre"}),
        }
        for proof in evidence:
            requested = checks.get(proof.get("proofType"))
            require(requested is not None
                    and proof.get("url") == requested[0]
                    and proof.get("checkedAt") == reviewed.isoformat()
                    and requested[1].issubset(set(proof.get("checkedFields") or [])),
                    "Chato'do : preuve de détail ou agenda invalide")
            if proof.get("proofType") == "first-party-venue-calendar":
                require("date" not in (proof.get("checkedFields") or [])
                        and "startTime" not in (proof.get("checkedFields") or []),
                        "Chato'do : l'agenda sans année ne prouve ni l'année ni l'heure")
        resolved = dict(known_artist_ids)
        resolved.update(added)
        require([x["id"] for x in new_artists] == spec["newArtistIds"]
                and len(ids) == len(spec["artistNames"])
                and all(aid in resolved
                        and norm(resolved[aid]["name"]) ==
                        norm(name)
                        for aid, name in zip(ids, spec["artistNames"])),
                "Chato'do : identité des groupes incompatible")
        require(event.get("time") is None,
                "Chato'do : ne pas transformer le créneau de portes en début")
    elif event.get("venueId") == "le-temps-machine-joue-les-tours":
        # A calendar card is not an event approval. The official venue
        # explicitly states that ticket times are DOOR times.
        spec = TEMPS_MACHINE_VERIFIED.get(event_id)
        require(spec is not None
                and reviewer == "independent-official-verifier"
                and event.get("sourceType") == "salle"
                and event.get("time") is None
                and all(event.get(k) == spec[k] for k in
                        ("title", "date", "time", "artistIds", "genres"))
                and official_url == spec["officialUrl"],
                "Le Temps Machine : concert ou programmation hors liste signée")
        url = urlsplit(official_url)
        require(url.scheme == "https" and url.hostname == "letempsmachine.com"
                and url.path == urlsplit(spec["officialUrl"]).path
                and re.fullmatch(r"/agenda/[a-z0-9-]+", url.path)
                and not url.username and not url.password and not url.port
                and not url.query and not url.fragment,
                "Le Temps Machine : fiche individuelle officielle requise")
        reviewed = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= reviewed <= today,
                "Le Temps Machine : preuve périmée ou future")
        require(len(evidence) == 2
                and {p.get("proofType") for p in evidence if isinstance(p, dict)}
                == {"official-organizer-or-venue", "first-party-venue-calendar"},
                "Le Temps Machine : détail et agenda séparés obligatoires")
        checks = {
            "official-organizer-or-venue": (
                spec["officialUrl"], {"artists", "date", "venue", "genre"}),
            "first-party-venue-calendar": (
                "https://letempsmachine.com/agenda?category=All&location=All",
                {"artists", "date", "genre"}),
        }
        for proof in evidence:
            expected = checks.get(proof.get("proofType"))
            require(expected is not None
                    and proof.get("url") == expected[0]
                    and proof.get("checkedAt") == reviewed.isoformat()
                    and expected[1].issubset(set(proof.get("checkedFields") or [])),
                    "Le Temps Machine : preuve absente ou incomplète")
            require("concertStartTime" not in (proof.get("checkedFields") or []),
                    "Le Temps Machine : horaire de portes différent du concert")
        resolved = dict(known_artist_ids)
        resolved.update(added)
        require([x["id"] for x in new_artists] == spec["newArtistIds"]
                and len(ids) == len(spec["artistNames"])
                and all(aid in resolved and
                        norm(resolved[aid]["name"]) == norm(name)
                        for aid, name in zip(ids, spec["artistNames"])),
                "Le Temps Machine : groupe ou identité non vérifié")
        require(event.get("time") is None,
                "Le Temps Machine : heure musicale non établie")
    elif event.get("venueId") == "le-tetris-le-havre":
        # Precise, dated evidence outside the venue is indispensable:
        # the official Le Tetris individual pages show day/month WITHOUT year.
        spec = TETRIS_VERIFIED.get(event_id)
        require(spec is not None
                and reviewer == "independent-official-verifier"
                and event.get("sourceType") == "salle"
                and event.get("time") is None
                and all(event.get(k) == spec[k] for k in
                        ("title", "date", "time", "artistIds", "genres"))
                and official_url == spec["officialUrl"],
                "Le Tetris : affiche, artistes ou millésime hors liste signée")
        url = urlsplit(official_url)
        require(url.scheme == "https" and url.hostname == "letetris.fr"
                and url.path == urlsplit(spec["officialUrl"]).path
                and re.fullmatch(r"/agenda/[a-z0-9-]+", url.path)
                and not url.username and not url.password and not url.port
                and not url.query and not url.fragment,
                "Le Tetris : fiche officielle nominative exacte exigée")
        reviewed = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= reviewed <= today,
                "Le Tetris : revue périmée ou future")
        require(len(evidence) == 2
                and {p.get("proofType") for p in evidence if isinstance(p, dict)}
                == {"official-organizer-or-venue", spec["secondaryProofType"]},
                "Le Tetris : deux preuves distinctes de la date obligatoires")
        fields = {
            "official-organizer-or-venue": (
                spec["officialUrl"], {"artists", "venue", "genre", "dayMonth"}),
            spec["secondaryProofType"]: (
                spec["secondaryUrl"], {"artists", "venue", "fullDate"}),
        }
        for proof in evidence:
            want = fields.get(proof.get("proofType"))
            require(want is not None
                    and proof.get("url") == want[0]
                    and proof.get("checkedAt") == reviewed.isoformat()
                    and want[1].issubset(set(proof.get("checkedFields") or [])),
                    "Le Tetris : détail et corroboration de l'année invalides")
            if proof.get("proofType") == "official-organizer-or-venue":
                require("date" not in (proof.get("checkedFields") or [])
                        and "fullDate" not in (proof.get("checkedFields") or [])
                        and "concertStartTime" not in
                            (proof.get("checkedFields") or []),
                        "Le Tetris : la fiche ne prouve ni année ni début musical")
        resolved = dict(known_artist_ids)
        resolved.update(added)
        require([a["id"] for a in new_artists] == spec["newArtistIds"]
                and len(ids) == len(spec["artistNames"])
                and all(aid in resolved
                        and norm(resolved[aid]["name"]) == norm(name)
                        for aid, name in zip(ids, spec["artistNames"])),
                "Le Tetris : identité de groupe altérée")
        require(event.get("time") is None,
                "Le Tetris : aucune heure musicale confirmée")
    elif event.get("venueId") == "le-cargo-caen":
        # Only this exact, documented Cargö event is allowlisted.
        # Calendar 19:30 = DOORS, never the musical start. The official
        # individual page explicitly confirms 20:30 as start time.
        spec = CARGO_VERIFIED.get(event_id)
        require(spec is not None and reviewer == "independent-official-verifier"
                and event.get("sourceType") == "salle"
                and all(event.get(k) == spec[k] for k in
                        ("title", "date", "time", "venueId", "artistIds", "genres"))
                and official_url == spec["officialUrl"],
                "Le Cargö : événement ou heure hors liste blanche nominative")
        url = urlsplit(official_url)
        require(url.scheme == "https" and url.hostname == "lecargo.fr"
                and re.fullmatch(r"/programmation/concert/[a-z0-9-]+/", url.path)
                and not url.query and not url.fragment and not url.username
                and not url.password and not url.port,
                "Le Cargö : fiche officielle individuelle exigée")
        reviewed = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= reviewed <= today,
                "Le Cargö : contrôle officiel périmé ou futur")
        require(len(evidence) == 1 and isinstance(evidence[0], dict),
                "Le Cargö : preuve de fiche nominative absente")
        proof = evidence[0]
        require(proof.get("url") == official_url
                and proof.get("proofType") == "official-organizer-or-venue"
                and proof.get("checkedAt") == reviewed.isoformat()
                and {"artists", "date", "venue", "genre", "concertStartTime",
                     "doorTime"}.issubset(set(proof.get("checkedFields") or []))
                and proof.get("doorTimeConfirmed") == "19:30"
                and proof.get("concertStartTimeConfirmed") == spec["time"],
                "Le Cargö : distinction ouverture des portes/début non prouvée")
        resolved = dict(known_artist_ids)
        resolved.update(added)
        require([a["id"] for a in new_artists] == spec["newArtistIds"]
                and len(ids) == len(spec["artistNames"])
                and all(aid in resolved
                        and norm(resolved[aid]["name"]) == norm(name)
                        for aid, name in zip(ids, spec["artistNames"])),
                "Le Cargö : artiste ou première partie différent de l'officiel")
    elif event.get("venueId") == "big-band-cafe-herouville":
        # New BBC events require independent exact first-party + official
        # ticket provenance. No arbitrary band's page can self-approve.
        spec = BBC_NORMANDY_VERIFIED.get(event_id)
        require(spec is not None
                and reviewer == "independent-official-verifier"
                and event.get("sourceType") == "salle"
                and official_url == spec["officialUrl"]
                and all(event.get(field) == spec[field] for field in (
                    "title", "date", "time", "venueId", "artistIds", "genres")),
                "Big Band Café : concert hors liste nominative vérifiée")
        u = urlsplit(official_url)
        require(u.scheme == "https" and u.hostname == "bigbandcafe.com"
                and re.fullmatch(r"/[a-z0-9-]+/", u.path)
                and not u.query and not u.fragment
                and not u.username and not u.password and not u.port,
                "Big Band Café : URL de fiche officielle incorrecte")
        checked = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= checked <= today,
                "Big Band Café : preuve périmée ou postérieure")
        require(len(evidence) == 2
                and all(isinstance(p, dict) for p in evidence)
                and {p.get("proofType") for p in evidence} ==
                    {"official-organizer-or-venue",
                     "authorized-ticket-distributor-full-date"},
                "Big Band Café : fiche nominative et billetterie requises")
        proofs_by_kind = {p["proofType"]: p for p in evidence}
        for kind, url, fields in (
            ("official-organizer-or-venue", spec["officialUrl"],
             {"artists", "date", "venue", "genre"}),
            ("authorized-ticket-distributor-full-date", spec["ticketUrl"],
             {"artists", "date", "venue"})):
            p = proofs_by_kind[kind]
            checked_fields = set(p.get("checkedFields") or [])
            require(p.get("url") == url
                    and p.get("checkedAt") == checked.isoformat()
                    and fields.issubset(checked_fields)
                    and not ({"startTime", "concertStartTime"} & checked_fields),
                    "Big Band Café : provenance ou horaire non démontré")
        require(new_artists == [
            {"id": artist_id, "name": spec["artistNames"][i]}
            for i, artist_id in enumerate(spec["artistIds"])
            if artist_id in spec["newArtistIds"]],
            "Big Band Café : noms d'artistes ajoutés non vérifiés")
        resolved = dict(known_artist_ids)
        resolved.update(added)
        require(len(ids) == len(spec["artistNames"]) and all(
            aid in resolved and norm(resolved[aid]["name"]) == norm(name)
            for aid, name in zip(ids, spec["artistNames"])),
            "Big Band Café : artiste différent de l'annonce officielle")
        require(event.get("time") is None,
                "Big Band Café : 20h affiché ne prouve pas le début musical")
    return event, added


def merge(reference, current, approvals, today):
    protect_reference(reference, current)
    require(approvals.get("schema") == SCHEMA and
            isinstance(approvals.get("approvals"), list),
            "Approbations privées non conformes")
    require(len(approvals["approvals"]) <= MAX_CUMULATIVE_EVENT_APPROVALS,
            "Trop d’approbations cumulées")
    # Une modification manuelle d'un concert CLOUD ne peut contourner
    # la file privée des approbations et les champs documentés.
    approved_ids = {
        a.get("event", {}).get("id"): a
        for a in approvals["approvals"] if a.get("reviewDecision") == "approved"
    }
    for existing in current["events"][len(reference["events"]):]:
        approval = approved_ids.get(existing["id"])
        require(bool(approval), "Concert cloud publié sans approbation privée")
        expected = approval["event"]
        require(all(existing.get(k) == expected.get(k) for k in
                    ("id", "title", "date", "artistIds", "venueId", "genres",
                     "status", "officialUrl", "sourceType")),
                "Concert cloud modifié hors de son approbation : " + existing["id"])
    result = copy.deepcopy(current)
    location_review = validate_secret_place_location_correction(
        approvals, reference, today)
    rex_review = validate_rex_location_correction(approvals, reference, today)
    new_geo_review = validate_new_reference_geo(approvals, reference, today)
    current_venues = current["venues"][:len(reference["venues"])]
    reference_by_id = {v["id"]: v for v in reference["venues"]}
    venue_corrected_count = 0
    # A correction must never disappear when the approval queue advances.
    # Only the single approved venue fields may be changed.
    correction_plan = {
        SECRET_PLACE_VENUE_ID: (
            SECRET_PLACE_LOCATION_FIX, location_review),
        REX_VENUE_ID: (
            REX_LOCATION_FIX, rex_review),
    }
    correction_plan.update({
        venue_id: (spec["patch"], new_geo_review.get(venue_id))
        for venue_id, spec in NEW_REFERENCE_GEO_SOURCES.items()
    })
    for venue_id, (patch, signed) in correction_plan.items():
        index = next(
            (n for n, v in enumerate(reference["venues"])
             if v["id"] == venue_id), None)
        require(index is not None, "Salle historique perdue : " + venue_id)
        original = reference_by_id[venue_id]
        approved_venue = copy.deepcopy(original)
        approved_venue.update(copy.deepcopy(patch))
        current_venue = current_venues[index]
        require(current_venue in (original, approved_venue),
                "Salle initiale hors correction nominative : " + venue_id)
        if current_venue == approved_venue:
            require(signed is not None,
                    "Salle déjà corrigée sans approbation persistante : " + venue_id)
        elif signed is not None:
            result["venues"][index] = approved_venue
            venue_corrected_count += 1
    correction = validate_legacy_correction(approvals, reference, today)
    cargo_time_corrections = validate_cargo_reference_time_corrections(
        approvals, reference, today)
    current_prefix = current["events"][:len(reference["events"])]
    # Previously applied changes also need a persistent signed private proof.
    signed_ids = sorted(cargo_time_corrections)
    permissible_prior = []
    for legacy in ((False, True) if correction else (False,)):
        for mask in range(1 << len(signed_ids)):
            subset = tuple(event_id for i, event_id in enumerate(signed_ids)
                           if mask & (1 << i))
            permissible_prior.append(corrected_reference_event_state(
                reference, legacy=legacy, cargo_ids=subset))
    require(current_prefix in permissible_prior,
            "Concert historique corrigé sans preuve privée persistante")
    desired = corrected_reference_event_state(
        reference, legacy=bool(correction), cargo_ids=signed_ids)
    corrected_count = sum(old != new for old, new
                          in zip(current_prefix, desired))
    if corrected_count:
        result["events"][:len(reference["events"])] = desired
    ids = {x["id"] for x in result["events"]}
    venues = {x["id"]: x for x in result["venues"]}
    artists = {x["id"]: x for x in result["artists"]}
    venue_approvals = approvals.get("venueApprovals", [])
    require(isinstance(venue_approvals, list) and len(venue_approvals) <= MAX_CUMULATIVE_VENUE_APPROVALS,
            "Liste d'approbations de salles inattendue ou excessive")
    approved_venues = {x["venue"]["id"]: x for x in venue_approvals
                       if isinstance(x,dict) and isinstance(x.get("venue"),dict)
                       and isinstance(x["venue"].get("id"), str)}
    require(len(approved_venues) == len(venue_approvals),
            "Doublon ou dossier de salle incomplet")
    # Every previously appended venue must still match its private approval.
    # As with events, no ad-hoc catalogue edit can bypass the approval queue.
    for prior in current["venues"][len(reference["venues"]):]:
        approval = approved_venues.get(prior["id"])
        require(approval is not None and prior == validate_venue_approval(approval, today),
                "Salle cloud ajoutée/modifiée sans approbation privée")
    counts = {"newEvents": 0, "newArtists": 0, "newVenues": 0,
              "correctedEvents": corrected_count, "correctedVenues": venue_corrected_count,
              "alreadyPublished": 0, "alreadyRegisteredVenues": 0, "held": []}
    for entry in venue_approvals:
        try:
            incoming = validate_venue_approval(entry, today)
            v_id = incoming["id"]
            if v_id in venues:
                require(venues[v_id] == incoming, "Conflit de fiche salle déjà présente")
                counts["alreadyRegisteredVenues"] += 1
                continue
            require(not any(norm(v["name"]) == norm(incoming["name"]) and
                            norm(v["city"]) == norm(incoming["city"])
                            for v in venues.values()),
                    "Salle déjà connue sous un autre identifiant")
            result["venues"].append(incoming)
            venues[v_id] = incoming
            counts["newVenues"] += 1
        except (ValueError, KeyError, TypeError) as ex:
            counts["held"].append({"candidateId": entry.get("venue", {}).get("id"),
                                   "reason": str(ex)})
    # Approved records are cumulative, not a single deployment batch.
    for entry in approvals["approvals"]:
        try:
            incoming = entry.get("event") or {}
            prior_id = incoming.get("id")
            if prior_id in ids:
                previous = next(e for e in result["events"] if e["id"] == prior_id)
                require(entry.get("reviewDecision") == "approved" and
                        all(previous.get(k) == incoming.get(k) for k in
                            ("id", "title", "date", "artistIds", "venueId", "genres",
                             "status", "officialUrl", "sourceType")),
                        "Approbation existante ne correspond pas à la fiche publiée")
                counts["alreadyPublished"] += 1
                continue
            evt, new_artists = validate_approval(entry, venues, artists, today)
            # Aucune collision non déclarée sur le même lieu, jour et artiste.
            clash = next((other["id"] for other in result["events"]
                          if other["date"] == evt["date"] and
                          other["venueId"] == evt["venueId"] and
                          set(other["artistIds"]).intersection(evt["artistIds"])), None)
            require(not clash, "Doublon potentiel existant : " + str(clash))
            for aid, artist in new_artists.items():
                result["artists"].append(artist)
                artists[aid] = artist
                counts["newArtists"] += 1
            # Champs autorisés explicitement : aucune latitude/longitude inventée.
            item = {k: evt[k] for k in
                    ("id", "title", "date", "artistIds", "venueId", "genres",
                     "status", "officialUrl", "sourceType")}
            item.update({
                "time": evt.get("time"), "timeMeaning": "début du concert" if evt.get("time") else "non confirmé",
                "organizer": evt.get("organizer") or venues[evt["venueId"]]["name"],
                "ticketUrl": evt.get("ticketUrl"),
                "lastVerified": entry.get("reviewedAt") or today.isoformat(),
                "confidence": "Annonce officielle contrôlée; référence vérifiée avant publication",
                "sourceLabel": "Programmation officielle (salle / organisateur)",
                "locationPrecision": "Position connue du catalogue, précision à confirmer",
                "history": [{"date": today.isoformat(),
                             "change": "Ajout après revue des preuves officielles"}]
            })
            result["events"].append(item)
            ids.add(evt["id"])
            counts["newEvents"] += 1
        except (ValueError, KeyError, TypeError) as ex:
            counts["held"].append({"candidateId": entry.get("event", {}).get("id"),
                                   "reason": str(ex)})
    # A large first-party intake must be split into reviewed batches.
    # If the delta is unexpectedly high, stop rather than silently truncate.
    require(counts["newEvents"] <= MAX_NEW_EVENTS_PER_SYNC,
            "Trop de nouveaux concerts en une seule synchronisation")
    require(counts["newVenues"] <= MAX_NEW_VENUES_PER_SYNC,
            "Trop de nouvelles salles en une seule synchronisation")
    if (counts["newEvents"] or counts["newVenues"] or counts["correctedEvents"] or counts["correctedVenues"]):
        result["updatedAt"] = today.isoformat()
        result["edition"] = "v0.6+cloud — vérifications officielles"
    protect_reference(reference, result)
    validate_catalogue(result)
    return result, counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preview", "publish"), required=True)
    parser.add_argument("--output", default="/tmp/grossesondes_concerts")
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    current = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    token = os.environ.get("GROSSES_ONDES_INTAKE_READ_TOKEN", "")
    approvals = read_approvals(token) if token else {
        "schema": SCHEMA, "approvals": []
    }
    today = dt.datetime.now(dt.timezone.utc).date()
    candidate, stats = merge(reference, current, approvals, today)
    stats["mode"] = args.mode
    stats["baselineEvents"] = len(reference["events"])
    stats["publicEventsBefore"] = len(current["events"])
    stats["publicEventsAfter"] = len(candidate["events"])
    stats["privateApprovalFeedReadable"] = bool(token)
    (out / "rapport.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "concerts-candidat.json").write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.mode == "publish" and (stats["newEvents"] or stats["newVenues"] or stats["correctedEvents"] or stats["correctedVenues"]):
        require(bool(token), "Interdiction de publier sans accès aux validations privées")
        CATALOGUE.write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Concerts GitHub:", stats["publicEventsBefore"], "→",
          stats["publicEventsAfter"], "publiables en mode", args.mode)


if __name__ == "__main__":
    main()
