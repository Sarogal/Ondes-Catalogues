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
    "la-vapeur-dijon": {
        "venue": {
            "id": "la-vapeur-dijon",
            "name": "La Vapeur",
            "address": "42 avenue de Stalingrad",
            "postalCode": "21000",
            "city": "Dijon",
            "department": "21",
            "region": "Bourgogne-Franche-Comté",
            "latitude": 47.34569,
            "longitude": 5.05964,
            "geoPrecision": "point nominatif de La Vapeur sur OpenStreetMap node 3474725036 via Mapcarta, coordonnées arrondies à 5 décimales ; position indicative de la salle, pas son entrée",
            "geoSource": "https://mapcarta.com/fr/N3474725036"
        },
        "officialUrl": "https://www.lavapeur.com/infos-pratiques/acces",
        "locationUrl": "https://mapcarta.com/fr/N3474725036",
        "locationProofType": "openstreetmap-venue-node"
    },
    "le-bateau-ivre-tours": {
        "venue": {
            "id": "le-bateau-ivre-tours",
            "name": "Le Bateau Ivre",
            "address": "146 rue Édouard Vaillant",
            "postalCode": "37000",
            "city": "Tours",
            "department": "37",
            "region": "Centre-Val de Loire",
            "latitude": 47.3844669,
            "longitude": 0.7013784,
            "geoPrecision": "point indicatif associé à un événement organisé au Bateau Ivre, publié par l'ADT 37 via DATAtourisme; recoupé avec l'adresse officielle 146 rue Édouard Vaillant; ne représente pas l'entrée exacte",
            "geoSource": "https://www.loisirs-divertissements.com/sortir-en-france/sortir-visiter-indre-et-loire-37/jam-7880"
        },
        "officialUrl": "https://www.bateauivre.coop/contact/",
        "locationUrl": "https://www.loisirs-divertissements.com/sortir-en-france/sortir-visiter-indre-et-loire-37/jam-7880",
        "locationProofType": "independent-tourism-event-gps"
    },
    "l-echonova-saint-ave": {
        "venue": {"id":"l-echonova-saint-ave","name":"L'Echonova","address":"1 rue Léon Griffon","postalCode":"56890","city":"Saint-Avé","department":"56","region":"Bretagne","latitude":47.67468,"longitude":-2.74379,"geoPrecision":"point indicatif du site L'Echonova d'après Fandefest (coordonnées initiales 47.67468064,-2.7437943027), cohérent avec la localisation générale du lieu; non assimilé à l'entrée publique","geoSource":"https://www.fandefest.com/salle/l-echonova-saint-ave"},
        "officialUrl": "https://lechonova.com/infos-pratiques/",
        "locationUrl": "https://www.fandefest.com/salle/l-echonova-saint-ave",
        "locationProofType": "independent-venue-coordinate-listing",
    },
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
    "casino-de-paris": {"venue":{"id":"casino-de-paris","name":"Casino de Paris","address":"16 rue de Clichy","postalCode":"75009","city":"Paris","department":"75","region":"Île-de-France","latitude":48.87845,"longitude":2.33051,"geoPrecision":"centre indicatif du bâtiment Casino de Paris sur OpenStreetMap way 69257631, reproduit par Mapcarta (5 décimales) ; ni l'entrée spectateurs ni une précision métrique garanties","geoSource":"https://mapcarta.com/fr/26253924"},"officialUrl":"https://www.casinodeparis.fr/fr/infos-pratiques","locationUrl":"https://mapcarta.com/fr/26253924","locationProofType":"openstreetmap-venue-way"},
    "radiant-bellevue-caluire": {"venue":{"id":"radiant-bellevue-caluire","name":"Radiant-Bellevue","address":"1 rue Jean Moulin","postalCode":"69300","city":"Caluire-et-Cuire","department":"69","region":"Auvergne-Rhône-Alpes","latitude":45.79795,"longitude":4.84301,"geoPrecision":"centre indicatif du bâtiment Radiant-Bellevue sur OpenStreetMap way 299047133 via Mapcarta (5 décimales), non l'entrée exacte ; la tournée annonce Lyon mais la salle est située à Caluire-et-Cuire","geoSource":"https://mapcarta.com/fr/W299047133"},"officialUrl":"https://radiant-bellevue.fr/contact-acces/","locationUrl":"https://mapcarta.com/fr/W299047133","locationProofType":"openstreetmap-venue-way"},
    "cepac-silo-marseille": {"venue":{"id":"cepac-silo-marseille","name":"CEPAC Silo","address":"35 quai du Lazaret","postalCode":"13002","city":"Marseille","department":"13","region":"Provence-Alpes-Côte d’Azur","latitude":43.310475,"longitude":5.366558,"geoPrecision":"point de repère touristique de la salle Le Silo/CEPAC Silo, publié via Cirkwi par l'Office de Tourisme et des Congrès de Marseille (43.310475, 5.366558) ; point indicatif du site, pas l'entrée ni une précision métrique","geoSource":"https://www.cirkwi.com/en/point-interet/4687013-le-silo"},"officialUrl":"https://www.cepacsilo-marseille.fr/infos-pratiques/","locationUrl":"https://www.cirkwi.com/en/point-interet/4687013-le-silo","locationProofType":"independent-tourism-gps"},

    "le-mem-rennes": {"venue":{"id":"le-mem-rennes","name":"Le MeM","address":"La Piverdière, accès route de Sainte-Foix","postalCode":"35000","city":"Rennes","department":"35","region":"Bretagne","latitude":48.1032992,"longitude":-1.7184605,"geoPrecision":"point Google Maps nominatif 'Le MeM - Magic Mirror' relié depuis la page officielle du MeM en 2026 (48.1032992,-1.7184605), cohérent avec une photo géolocalisée le 18/10/2026 près du nouveau bâtiment ; repère indicatif du site rénové, pas la porte exacte et sans précision métrique garantie","geoSource":"https://www.google.com/maps/place/Le+MeM+-+Magic+Mirror/@48.1033028,-1.7210354,17z/data=!3m1!4b1!4m6!3m5!1s0x480ee199e0031c8f:0xe9f3c5422f9585e3!8m2!3d48.1032992!4d-1.7184605!16s%2Fg%2F11h5_1c5zn?entry=ttu&g_ep=EgoyMDI2MDQwNS4wIKXMDSoASAFQAw%3D%3D"},"officialUrl":"https://www.lemem.fr/pratique/","locationUrl":"https://www.google.com/maps/place/Le+MeM+-+Magic+Mirror/@48.1033028,-1.7210354,17z/data=!3m1!4b1!4m6!3m5!1s0x480ee199e0031c8f:0xe9f3c5422f9585e3!8m2!3d48.1032992!4d-1.7184605!16s%2Fg%2F11h5_1c5zn?entry=ttu&g_ep=EgoyMDI2MDQwNS4wIKXMDSoASAFQAw%3D%3D","locationProofType":"first-party-venue-map"},

}

# Stereolux Nantes / 6MIC Aix : dossiers signés 05/11/2026.
# Whitelist STRICTEMENT nominative ; toute autre salle reste refusée.
PILOT_VENUES.update(json.loads(r'''{"stereolux-nantes":{"venue":{"id":"stereolux-nantes","name":"Stereolux","address":"4 boulevard Léon-Bureau","postalCode":"44200","city":"Nantes","department":"44","region":"Pays de la Loire","latitude":47.205119,"longitude":-1.563498,"geoPrecision":"point GPS nominatif Stereolux publié par Nantes Université (47.205119, -1.563498), cohérent avec le point OpenStreetMap node 2434544471 voisin ; repère indicatif de l'établissement, pas l'entrée exacte de la salle Maxi","geoSource":"https://www.univ-nantes.fr/plans-des-campus/stereolux"},"officialUrl":"https://stereolux.org/infos-pratiques/accessibilite","locationUrl":"https://www.univ-nantes.fr/plans-des-campus/stereolux","locationProofType":"independent-institutional-venue-gps"},"6mic-aix-en-provence":{"venue":{"id":"6mic-aix-en-provence","name":"6MIC","address":"160 rue Pascal Duverger","postalCode":"13090","city":"Aix-en-Provence","department":"13","region":"Provence-Alpes-Côte d’Azur","latitude":43.5193,"longitude":5.42182,"geoPrecision":"centre indicatif du bâtiment 6MIC identifié sur OpenStreetMap way 701032991 via Mapcarta (coordonnées arrondies à cinq décimales), pas son entrée exacte","geoSource":"https://mapcarta.com/fr/W701032991"},"officialUrl":"https://www.6mic-aix.fr/comment-venir-au-6mic/","locationUrl":"https://mapcarta.com/fr/W701032991","locationProofType":"openstreetmap-venue-way"}}'''))

# Concerts nominatifs vérifiés : aucun autre événement ne peut emprunter les
# deux nouvelles salles ou réutiliser leurs URLs sans revue de code.
HOWLIN_TWO_SIGNED_20261105 = json.loads(r'''{"go-c-20261208-nantes-fff-howlin-jaws":{"event":{"id":"go-c-20261208-nantes-fff-howlin-jaws","title":"FFF + Howlin’ Jaws","date":"2026-12-08","time":null,"artistIds":["fff","howlin-jaws"],"venueId":"stereolux-nantes","genres":["Funk Rock","Rock"],"status":"confirmed","officialUrl":"https://stereolux.org/agenda/fff","sourceType":"salle","organizer":"O Spectacles"},"newArtists":[],"proofs":[{"url":"https://stereolux.org/agenda/fff","proofType":"official-organizer-or-venue","checkedFields":["leadArtist","date","venue","supportUnspecified"],"confirmedArtists":["FFF"]},{"url":"https://radical-production.fr/artistes/howlin-jaws/","proofType":"independent-official-support-agent","checkedFields":["artists","date","venue","supportRole"],"confirmedArtists":["FFF","Howlin' Jaws"]}]},"go-c-20270402-aix-howlin-jaws-gloria":{"event":{"id":"go-c-20270402-aix-howlin-jaws-gloria","title":"Howlin’ Jaws + Gloria","date":"2027-04-02","time":null,"artistIds":["howlin-jaws","gloria"],"venueId":"6mic-aix-en-provence","genres":["Rock"],"status":"confirmed","officialUrl":"https://www.6mic-aix.fr/evenements/club-indle-club-inde-w-howlin-jaws-gloria/","sourceType":"salle","organizer":"6MIC"},"newArtists":[{"id":"gloria","name":"Gloria"}],"proofs":[{"url":"https://www.6mic-aix.fr/evenements/club-indle-club-inde-w-howlin-jaws-gloria/","proofType":"official-organizer-or-venue","checkedFields":["artists","date","venue","genre"],"confirmedArtists":["Howlin' Jaws","Gloria"]},{"url":"https://radical-production.fr/artistes/howlin-jaws/","proofType":"independent-official-artist-agent","checkedFields":["leadArtist","date","venue","otherArtistNamed"],"confirmedArtists":["Howlin' Jaws","Gloria"]}]}}''')
HOWLIN_TWO_VENUES = {"stereolux-nantes", "6mic-aix-en-provence"}

# Cap Caval Penmarc'h: preuve officielle et bâtiment OSM nominatif,
# jamais le nœud de parking à vélos homonyme.
PILOT_VENUES["salle-cap-caval-penmarch"] = json.loads(r'''{"venue":{"id":"salle-cap-caval-penmarch","name":"Salle Cap Caval","address":"Avenue de Skibbereen","postalCode":"29760","city":"Penmarc’h","department":"29","region":"Bretagne","latitude":47.81333,"longitude":-4.33766,"geoPrecision":"centre arrondi du bâtiment Salle Cap Caval désigné nominativement sur OpenStreetMap way 66608817 (amenity=music_venue, building=yes) via Mapcarta ; pas son entrée exacte ni un parking Cap Caval voisin","geoSource":"https://mapcarta.com/W66608817"},"officialUrl":"https://www.cap-caval.fr/infos-pratiques/","locationUrl":"https://mapcarta.com/W66608817","locationProofType":"openstreetmap-venue-way"}''')
CAP_CAVAL_SIGNED_20261105 = json.loads(r'''{"event":{"id":"go-c-20270227-penmarch-howlin-jaws-komodor","title":"Howlin’ Jaws + Komodor","date":"2027-02-27","time":null,"artistIds":["howlin-jaws","komodor"],"venueId":"salle-cap-caval-penmarch","genres":["Psych Rock","Hard Rock"],"status":"confirmed","officialUrl":"https://www.cap-caval.fr/evenements/howlin-jaws-komodor/","sourceType":"salle","organizer":"Salle Cap Caval"},"newArtists":[],"proofs":[{"url":"https://www.cap-caval.fr/evenements/howlin-jaws-komodor/","proofType":"official-organizer-or-venue","checkedFields":["artists","date","venue","genre","eventStartTime"],"confirmedArtists":["Howlin’ Jaws","Komodor"]},{"url":"https://radical-production.fr/artistes/howlin-jaws/","proofType":"independent-official-artist-agent","checkedFields":["artists","date","venue","supportRole"],"confirmedArtists":["Howlin’ Jaws","Komodor"]}]}''')

# Marché Gare Lyon : unique salle nominative, et non le parking LPA.
PILOT_VENUES["marche-gare-lyon"] = json.loads(r'''{"venue":{"id":"marche-gare-lyon","name":"Marché Gare","address":"4–6 place Hubert Mounier","postalCode":"69002","city":"Lyon","department":"69","region":"Auvergne-Rhône-Alpes","latitude":45.74135,"longitude":4.82265,"geoPrecision":"centre indicatif du bâtiment Marché Gare (OpenStreetMap way 82189851 via Mapcarta), bâtiment arts_centre et building=yes avec site marchegare.fr ; la fiche OSM conserve l'ancienne adresse rue Casimir Périer, tandis que le site officiel 2026 indique l'accès actuel 4–6 place Hubert Mounier ; ni entrée précise ni parking LPA","geoSource":"https://mapcarta.com/W82189851"},"officialUrl":"https://marchegare.fr/infos-pratiques/acces-accessibilite","locationUrl":"https://mapcarta.com/W82189851","locationProofType":"openstreetmap-venue-way"}''')

# Dernières quatre dates FR Howlin’ Jaws, fiches et preuves bornées.
HOWLIN_FINAL_FOUR_SIGNED_20261105 = json.loads(r'''{"go-c-20261110-roubaix-howlin-jaws-moundrag":{"event":{"id":"go-c-20261110-roubaix-howlin-jaws-moundrag","title":"Howlin’ Jaws + Moundrag","date":"2026-11-10","time":"20:00","artistIds":["howlin-jaws","moundrag"],"venueId":"la-cave-aux-poetes-roubaix","genres":["Psych Rock"],"status":"confirmed","officialUrl":"https://caveauxpoetes.com/evenement/howlinjaws-moundrag/","sourceType":"salle","organizer":"La Cave aux Poètes"},"newArtists":[{"id":"moundrag","name":"Moundrag"}],"proofs":[{"url":"https://caveauxpoetes.com/evenement/howlinjaws-moundrag/","proofType":"official-organizer-or-venue","checkedFields":["artists","date","venue","genre","startTime"],"confirmedArtists":["Howlin' Jaws","Moundrag"]},{"url":"https://caveauxpoetes.com/agenda/","proofType":"first-party-venue-calendar","checkedFields":["artists","date","venue"],"confirmedArtists":null}]},"go-c-20261118-paris-howlin-jaws-theo-charaf":{"event":{"id":"go-c-20261118-paris-howlin-jaws-theo-charaf","title":"Howlin’ Jaws + Théo Charaf","date":"2026-11-18","time":null,"artistIds":["howlin-jaws","theo-charaf"],"venueId":"le-trabendo-paris","genres":["Rock"],"status":"confirmed","officialUrl":"https://www.letrabendo.net/programmation/howlin-jaws/","sourceType":"salle","organizer":"Radical Production"},"newArtists":[{"id":"theo-charaf","name":"Théo Charaf"}],"proofs":[{"url":"https://www.letrabendo.net/programmation/howlin-jaws/","proofType":"official-organizer-or-venue","checkedFields":["artists","date","venue","genre","doorTime"],"confirmedArtists":["Howlin' Jaws","Théo Charaf"]}]},"go-c-20261121-lyon-howlin-jaws-hayko":{"event":{"id":"go-c-20261121-lyon-howlin-jaws-hayko","title":"Howlin’ Jaws + Hayko","date":"2026-11-21","time":"20:00","artistIds":["howlin-jaws","hayko"],"venueId":"marche-gare-lyon","genres":["Rock","Indie Rock"],"status":"confirmed","officialUrl":"https://marchegare.fr/agenda/howlin-jaws","sourceType":"salle","organizer":"Marché Gare"},"newArtists":[{"id":"hayko","name":"Hayko"}],"proofs":[{"url":"https://marchegare.fr/agenda/howlin-jaws","proofType":"official-organizer-or-venue","checkedFields":["artists","date","venue","genre","concertStartTime"],"confirmedArtists":["Howlin' Jaws","Hayko"]},{"url":"https://www.fnacspectacles.com/event/howlin-jaws-le-marche-gare-lyon-02-21848689/","proofType":"authorized-ticket-distributor-full-date","checkedFields":["artists","date","venue"],"confirmedArtists":["Howlin' Jaws","Hayko"]}]},"go-c-20270429-nancy-howlin-jaws-komodor":{"event":{"id":"go-c-20270429-nancy-howlin-jaws-komodor","title":"Howlin’ Jaws + Komodor","date":"2027-04-29","time":null,"artistIds":["howlin-jaws","komodor"],"venueId":"l-autre-canal-nancy","genres":["Psych Rock","Rock"],"status":"confirmed","officialUrl":"https://lautrecanalnancy.fr/agenda/howlin-jaws-komodor","sourceType":"salle","organizer":"L’Autre Canal"},"newArtists":[],"proofs":[{"url":"https://lautrecanalnancy.fr/agenda/howlin-jaws-komodor","proofType":"official-organizer-or-venue","checkedFields":["artists","date","venue","genre","eventTime"],"confirmedArtists":["Howlin' Jaws","Komodor"]},{"url":"https://radical-production.fr/artistes/howlin-jaws/","proofType":"independent-official-artist-agent","checkedFields":["artists","date","venue","coHeadline"],"confirmedArtists":["Howlin' Jaws","Komodor"]}]}}''')

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

# Salle Cave aux Poètes : concert nominatif du 10/11, calendrier officiel distinct.
CAVE_POETES_VERIFIED.update(json.loads(r'''{"go-c-20261110-roubaix-howlin-jaws-moundrag":{"title":"Howlin’ Jaws + Moundrag","date":"2026-11-10","time":"20:00","artistIds":["howlin-jaws","moundrag"],"newArtistIds":["moundrag"],"genres":["Psych Rock"],"officialUrl":"https://caveauxpoetes.com/evenement/howlinjaws-moundrag/","organizerCalendar":"https://caveauxpoetes.com/agenda/","calendarProofType":"first-party-venue-calendar","calendarCheckedFields":["artists","date","venue"]}}'''))

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

# Le Trabendo nomme explicitement Howlin’ Jaws + Théo Charaf : détail officiel.
TRABENDO_VERIFIED.update(json.loads(r'''{"go-c-20261118-paris-howlin-jaws-theo-charaf":{"title":"Howlin’ Jaws + Théo Charaf","date":"2026-11-18","artistIds":["howlin-jaws","theo-charaf"],"newArtistIds":["theo-charaf"],"genres":["Rock"],"officialUrl":"https://www.letrabendo.net/programmation/howlin-jaws/"}}'''))

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
    "zenith-paris-la-villette-paris": {
        "patch": {
            "address": "211 avenue Jean Jaurès",
            "postalCode": "75019",
            "latitude": 48.89418,
            "longitude": 2.39317,
            "geoPrecision": "position indicative du bâtiment Zénith Paris – La Villette (OpenStreetMap way 63971432), et non entrée garantie",
            "geoSource": "https://mapcarta.com/fr/W63971432"
        },
        "officialUrl": "https://le-zenith.com/contact",
        "officialProof": "official-venue-address",
        "officialFields": [
            "venueName",
            "address",
            "postalCode",
            "city"
        ],
        "geoUrl": "https://mapcarta.com/fr/W63971432",
        "geoProof": "openstreetmap-venue-way",
        "geoFields": [
            "venueName",
            "coordinates"
        ],
        "expectedOriginal": {
            "name": "Zénith Paris – La Villette",
            "city": "Paris",
            "address": "Adresse exacte à vérifier",
            "postalCode": "À vérifier",
            "latitude": 48.866,
            "longitude": 2.343
        },
        "checkedAt": "2026-11-05"
    },
    "le-transbordeur-villeurbanne": {
        "patch": {
            "address": "3 boulevard de la Bataille de Stalingrad",
            "postalCode": "69100",
            "latitude": 45.78401,
            "longitude": 4.86079,
            "geoPrecision": "position indicative du bâtiment Le Transbordeur (OpenStreetMap way 85000536), pas l'entrée exacte du Club Transbo",
            "geoSource": "https://mapcarta.com/fr/W85000536"
        },
        "officialUrl": "https://www.transbordeur.fr/acces/",
        "officialProof": "official-venue-address",
        "officialFields": [
            "venueName",
            "address",
            "postalCode",
            "city"
        ],
        "geoUrl": "https://mapcarta.com/fr/W85000536",
        "geoProof": "openstreetmap-venue-way",
        "geoFields": [
            "venueName",
            "coordinates"
        ],
        "expectedOriginal": {
            "name": "Le Transbordeur",
            "city": "Villeurbanne",
            "address": "Adresse exacte à vérifier",
            "postalCode": "À vérifier",
            "latitude": 45.757,
            "longitude": 4.917
        },
        "checkedAt": "2026-11-05"
    },
    "la-belle-electrique-grenoble": {
        "patch": {
            "address": "12 esplanade Andry-Farcy",
            "postalCode": "38000",
            "latitude": 45.18718,
            "longitude": 5.70419,
            "geoPrecision": "position indicative du bâtiment La Belle Électrique (OpenStreetMap way 299631312), non l'entrée exacte",
            "geoSource": "https://mapcarta.com/fr/W299631312"
        },
        "officialUrl": "https://www.la-belle-electrique.com/fr/",
        "officialProof": "official-venue-address",
        "officialFields": [
            "venueName",
            "address",
            "postalCode",
            "city"
        ],
        "geoUrl": "https://mapcarta.com/fr/W299631312",
        "geoProof": "openstreetmap-venue-way",
        "geoFields": [
            "venueName",
            "coordinates"
        ],
        "expectedOriginal": {
            "name": "La Belle Électrique",
            "city": "Grenoble",
            "address": "Adresse exacte à vérifier",
            "postalCode": "À vérifier",
            "latitude": 45.186,
            "longitude": 5.729
        },
        "checkedAt": "2026-11-05"
    },
}

# L'Autre Canal : remplacement du centre de Nancy par le GPS officiel.
# Source indépendante : bâtiment OSM way 115010861. Référence immuable préservée.
NEW_REFERENCE_GEO_SOURCES["l-autre-canal-nancy"] = json.loads(r'''{"patch":{"address":"45 boulevard d'Austrasie","postalCode":"54000","latitude":48.694175,"longitude":6.198269,"geoPrecision":"coordonnées GPS publiées par L'Autre Canal dans son dossier technique de 2023 (48.694175, 6.198269), concordant avec le bâtiment OSM way 115010861 à proximité; localisation indicative du site, pas une entrée garantie","geoSource":"https://lautrecanalnancy.fr/sites/default/files/lautrecanal/fichiers/dossier_technique_2023_fr.pdf"},"officialUrl":"https://lautrecanalnancy.fr/sites/default/files/lautrecanal/fichiers/dossier_technique_2023_fr.pdf","officialProof":"official-venue-gps","officialFields":["name","address","postalCode","city","latitude","longitude"],"geoUrl":"https://mapcarta.com/W115010861","geoProof":"openstreetmap-venue-way","geoFields":["venueName","coordinates"],"expectedOriginal":{"name":"L’Autre Canal","city":"Nancy","address":"Adresse exacte à vérifier","postalCode":"À vérifier","latitude":48.692,"longitude":6.185},"checkedAt":"2026-11-05"}''')


def validate_new_reference_geo(approvals, reference, today):
    """Independently signed, two-source proof for exact historic pins."""
    rows = approvals.get("referenceVenueCorrections", [])
    require(isinstance(rows, list) and len(rows) <= 10,
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
                and checked == dt.date.fromisoformat(spec.get("checkedAt", "2026-11-03")) and checked <= today
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
                    and set(fields).issubset(set(p.get("checkedFields") or [])),
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
    require(isinstance(corrections, list) and len(corrections) <= 10,
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
    require(isinstance(corrections, list) and len(corrections) <= 10,
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
    # Le MeM 2026 a été reconstruit et déplacé : vérification renforcée
    # par photo géolocalisée du site actuel, pas uniquement une carte ancienne.
    expected_count = 3 if venue["id"] == "le-mem-rennes" else 2
    require(isinstance(evidence, list) and len(evidence) == expected_count,
            "Preuves nominatives indépendantes manquantes pour la salle")
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
    if venue["id"] == "le-mem-rennes":
        photo_url = "https://commons.wikimedia.org/wiki/File:Le_MeM_Rennes_-_Vue_de_l%27entr%C3%A9e_principale.jpg"
        photo = next((p for p in evidence if isinstance(p, dict)
                      and p.get("proofType") == "independent-geotagged-photo-2026"), None)
        require(photo is not None
                and photo.get("url") == photo_url
                and photo.get("checkedAt") == checked.isoformat()
                and set(photo.get("checkedFields") or []) ==
                    {"venueName", "photoDate", "geotaggedSite"}
                and photo.get("photoDate") == "2026-10-18"
                and photo.get("photoLat") == 48.10283
                and photo.get("photoLon") == -1.718835
                and venue["latitude"] == 48.1032992
                and venue["longitude"] == -1.7184605
                and abs(venue["latitude"] - photo["photoLat"]) < 0.0007
                and abs(venue["longitude"] - photo["photoLon"]) < 0.0007,
                "Le MeM : salle déplacée ; photo indépendante récente ou GPS actuel absent")
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

# Four independently checked 2026 Stranglers shows at ALREADY listed venues.
# Each signed venue/artist/genre/music-start is immutable, and none of these
# exact signatures grants access to any other concerts at those venues.
STRANGLERS_FOUR_SIGNED_20261106 = json.loads(r'''{"go-c-20261121-penmarch-the-stranglers":{"event":{"id":"go-c-20261121-penmarch-the-stranglers","title":"The Stranglers","date":"2026-11-21","time":"20:30","artistIds":["the-stranglers"],"venueId":"salle-cap-caval-penmarch","genres":["Rock"],"status":"confirmed","officialUrl":"https://www.cap-caval.fr/evenements/the-stranglers-2/","sourceType":"salle","organizer":"Salle Cap Caval"},"proofs":[{"url":"https://www.cap-caval.fr/evenements/the-stranglers-2/","proofType":"official-organizer-or-venue","checkedFields":["artists","date","venue","genre","concertStartTime"],"officialArtistNames":["The Stranglers"],"concertStartTimeConfirmed":"20:30"},{"url":"https://thestranglers.co.uk/the-stranglers-announce-french-tour-2026/","proofType":"official-artist-tour-calendar","checkedFields":["leadArtist","date","venue","city"],"officialArtistNames":["The Stranglers"]}]},"go-c-20261128-aix-the-stranglers":{"event":{"id":"go-c-20261128-aix-the-stranglers","title":"The Stranglers","date":"2026-11-28","time":"20:30","artistIds":["the-stranglers"],"venueId":"6mic-aix-en-provence","genres":["Rock"],"status":"confirmed","officialUrl":"https://www.6mic-aix.fr/evenements/the-stranglers/","sourceType":"salle","organizer":"6MIC"},"proofs":[{"url":"https://www.6mic-aix.fr/evenements/the-stranglers/","proofType":"official-organizer-or-venue","checkedFields":["artists","date","venue","genre","scheduledTime"],"officialArtistNames":["The Stranglers"]},{"url":"https://www.fnacspectacles.com/event/the-stranglers-6mic-aix-en-provence-21714726/","proofType":"authorized-ticket-distributor-full-date","checkedFields":["artists","date","venue","concertStartTime","doorTime"],"officialArtistNames":["The Stranglers"],"concertStartTimeConfirmed":"20:30","doorTimeConfirmed":"18:30"}]},"go-c-20261130-villeurbanne-the-stranglers":{"event":{"id":"go-c-20261130-villeurbanne-the-stranglers","title":"The Stranglers + Brother Junior","date":"2026-11-30","time":"20:00","artistIds":["the-stranglers","brother-junior"],"venueId":"le-transbordeur-villeurbanne","genres":["Punk Rock"],"status":"confirmed","officialUrl":"https://www.transbordeur.fr/evenement/the-stranglers-brother-junior-30112026/","sourceType":"salle","organizer":"Mediatone"},"proofs":[{"url":"https://www.transbordeur.fr/evenement/the-stranglers-brother-junior-30112026/","proofType":"official-organizer-or-venue","checkedFields":["artists","date","venue","genre","concertStartTime","doorTime"],"officialArtistNames":["The Stranglers","Brother Junior"],"concertStartTimeConfirmed":"20:00","doorTimeConfirmed":"18:30"},{"url":"https://thestranglers.co.uk/the-stranglers-announce-french-tour-2026/","proofType":"official-artist-tour-calendar","checkedFields":["leadArtist","date","venue","city"],"officialArtistNames":["The Stranglers"]}]},"go-c-20261203-vaureal-the-stranglers":{"event":{"id":"go-c-20261203-vaureal-the-stranglers","title":"The Stranglers + Brother Junior","date":"2026-12-03","time":"20:30","artistIds":["the-stranglers","brother-junior"],"venueId":"le-forum-vaureal","genres":["Rock Alternatif"],"status":"confirmed","officialUrl":"https://leforum.cergypontoise.fr/agenda/thestranglers","sourceType":"salle","organizer":"Le Forum"},"proofs":[{"url":"https://leforum.cergypontoise.fr/agenda/thestranglers","proofType":"official-organizer-or-venue","checkedFields":["artists","date","venue","genre","concertStartTime","doorTime"],"officialArtistNames":["The Stranglers","Brother Junior"],"concertStartTimeConfirmed":"20:30","doorTimeConfirmed":"20:00"},{"url":"https://thestranglers.co.uk/the-stranglers-announce-french-tour-2026/","proofType":"official-artist-tour-calendar","checkedFields":["leadArtist","date","venue","city"],"officialArtistNames":["The Stranglers"]}]}}''')

# Eight exact Rocher de Palmer bills; Gwendoline and The Stranglers lineups rechecked 2026-11-06.
# These are reviewed cases, not an open-ended permission for the venue.
ROCHER_PALMER_VERIFIED = {
    "go-c-20261124-cenon-the-stranglers": {
        "title": "The Stranglers + Brother Junior",
        "date": "2026-11-24",
        "artistIds": ["the-stranglers", "brother-junior"],
        "genres": ["Rock"],
        "time": "20:30",
        "officialUrl": "https://lerocherdepalmer.fr/agenda/stranglers"
    },
    "go-c-20261107-cenon-gwendoline": {
        "title": "Gwendoline + Bleu Panique",
        "date": "2026-11-07",
        "artistIds": [
            "gwendoline",
            "bleu-panique"
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
    # Two additional Colmar shows with first-party named bills and independent
    # full-year recoupments (Coze), no concert start inferred.
    "go-c-20261211-colmar-wake-the-dead": {"title":"Wake the Dead + Wrecked Culture + Lueur","date":"2026-12-11","time":None,"venueId":"le-grillen-colmar","artistIds":["wake-the-dead","wrecked-culture","lueur"],"artistNames":["Wake the Dead","Wrecked Culture","Lueur"],"genres":["Hardcore"],"newArtists":[{"id":"wrecked-culture","name":"Wrecked Culture"},{"id":"lueur","name":"Lueur"}],"officialUrl":"https://grillen.colmar.fr/programmation/wake-the-dead-wrecked-culture-lueur","proofs":[{"url":"https://grillen.colmar.fr/programmation/wake-the-dead-wrecked-culture-lueur","proofType":"official-organizer-or-venue","requiredFields":["artists","dayMonth","venue","genre"]},{"url":"https://www.coze.fr/agenda/wake-the-dead-wrecked-culture-lueur/","proofType":"independent-event-listing","requiredFields":["artists","date","venue"]}]},
    "go-c-20270130-colmar-easy-cure": {"title":"EASY CURE The CURE Tribute since 1996","date":"2027-01-30","time":None,"venueId":"le-grillen-colmar","artistIds":["easy-cure"],"artistNames":["Easy Cure"],"genres":["Rock"],"newArtists":[{"id":"easy-cure","name":"Easy Cure"}],"officialUrl":"https://grillen.colmar.fr/programmation/easy-cure-the-cure-tribute-since-1996","proofs":[{"url":"https://grillen.colmar.fr/programmation/easy-cure-the-cure-tribute-since-1996","proofType":"official-organizer-or-venue","requiredFields":["artists","dayMonth","venue","genre"]},{"url":"https://www.coze.fr/agenda/easy-cure-the-cure-tribute-since-1996/","proofType":"independent-event-listing","requiredFields":["artists","date","venue","genre"]}]},
    "go-c-20270219-colmar-colour-haze": {"title": "Colour Haze + Smokemaster", "date": "2027-02-19", "time": None, "venueId": "le-grillen-colmar", "artistIds": ["colour-haze", "smokemaster"], "artistNames": ["Colour Haze", "Smokemaster"], "genres": ["Stoner Rock"], "newArtists": [], "officialUrl": "https://grillen.colmar.fr/programmation/colour-haze-smokemaster", "proofs": [{"url": "https://grillen.colmar.fr/programmation/colour-haze-smokemaster", "proofType": "official-organizer-or-venue", "requiredFields": ["artists", "date", "venue", "genre"]}, {"url": "https://www.soundofliberation.com/artists/colour-haze", "proofType": "independent-tour-agent", "requiredFields": ["artists", "date", "venue"]}]},
}

# Exactly two independently reviewed first-party bills at a newly located
# Morbihan venue. Fnac lists their dates and acts; ONLY Eiffel has an explicit
# named musical start on the official detail page. Unnamed guests are omitted.
ECHONOVA_SIGNED_20261104 = {
    "go-c-20261203-saint-ave-eiffel": {"title":"Eiffel","date":"2026-12-03","time":"20:30","venueId":"l-echonova-saint-ave","artistIds":["eiffel"],"artistNames":["Eiffel"],"genres":["Rock"],"newArtists":[{"id":"eiffel","name":"Eiffel"}],"officialUrl":"https://lechonova.com/evenement/eiffel-premiere-partie/","ticketingUrl":"https://www.fnacspectacles.com/venue/lechonova-81096/","firstPartyFields":["artists","date","venue","genre","concertStartTime"],"ticketingFields":["artists","date","venue"]},
    "go-c-20270206-saint-ave-meteora-systemize": {"title":"Meteora + Systemize","date":"2027-02-06","time":None,"venueId":"l-echonova-saint-ave","artistIds":["meteora-tribute","systemize"],"artistNames":["Meteora","Systemize"],"genres":["Metal"],"newArtists":[{"id":"meteora-tribute","name":"Meteora"},{"id":"systemize","name":"Systemize"}],"officialUrl":"https://lechonova.com/evenement/meteora-linkin-park-tribute/","ticketingUrl":"https://www.fnacspectacles.com/venue/lechonova-81096/","firstPartyFields":["artists","date","venue","genre"],"ticketingFields":["artists","date","venue"]},
}

# Tours: five individual dated first-party bills plus their official programme.
# Site times are DOOR times (per venue contact page), never concert starts.
BATEAU_IVRE_SIGNED_20261104 = {
    "go-c-20261106-tours-les-sheriff-auxiliaire": {
        "title": "Les Sheriff + Auxiliaire",
        "date": "2026-11-06",
        "time": None,
        "venueId": "le-bateau-ivre-tours",
        "artistIds": [
            "les-sheriff",
            "auxiliaire"
        ],
        "artistNames": [
            "Les Sheriff",
            "Auxiliaire"
        ],
        "newArtistIds": [
            "les-sheriff",
            "auxiliaire"
        ],
        "genres": [
            "Punk Rock"
        ],
        "officialUrl": "https://www.bateauivre.coop/%C3%A9v%C3%A8nements/les-sheriff/",
        "calendarUrl": "https://www.bateauivre.coop/agenda-2/",
        "calendarFields": [
            "leadArtist",
            "date",
            "venue"
        ]
    },
    "go-c-20261107-tours-lofofora-akiavel-gravity": {
        "title": "Lofofora + Akiavel + Gravity",
        "date": "2026-11-07",
        "time": None,
        "venueId": "le-bateau-ivre-tours",
        "artistIds": [
            "lofofora",
            "akiavel",
            "gravity"
        ],
        "artistNames": [
            "Lofofora",
            "Akiavel",
            "Gravity"
        ],
        "newArtistIds": [
            "lofofora",
            "gravity"
        ],
        "genres": [
            "Metal"
        ],
        "officialUrl": "https://www.bateauivre.coop/%C3%A9v%C3%A8nements/lofofora-akiavel-gravity/",
        "calendarUrl": "https://www.bateauivre.coop/agenda-2/",
        "calendarFields": [
            "leadArtist",
            "date",
            "venue"
        ]
    },
    "go-c-20261113-tours-inspector-cluzo-grant-haua": {
        "title": "The Inspector Cluzo + Grant Haua",
        "date": "2026-11-13",
        "time": None,
        "venueId": "le-bateau-ivre-tours",
        "artistIds": [
            "the-inspector-cluzo",
            "grant-haua"
        ],
        "artistNames": [
            "The Inspector Cluzo",
            "Grant Haua"
        ],
        "newArtistIds": [],
        "genres": [
            "Rock"
        ],
        "officialUrl": "https://www.bateauivre.coop/%C3%A9v%C3%A8nements/the-inspector-cluzo/",
        "calendarUrl": "https://www.bateauivre.coop/agenda-2/",
        "calendarFields": [
            "leadArtist",
            "date",
            "venue"
        ]
    },
    "go-c-20261126-tours-feldup-trainfantome": {
        "title": "Feldup & The Showerheads + Trainfantome",
        "date": "2026-11-26",
        "time": None,
        "venueId": "le-bateau-ivre-tours",
        "artistIds": [
            "feldup-the-showerheads",
            "trainfantome"
        ],
        "artistNames": [
            "Feldup & The Showerheads",
            "Trainfantome"
        ],
        "newArtistIds": [
            "feldup-the-showerheads",
            "trainfantome"
        ],
        "genres": [
            "Rock",
            "Shoegaze"
        ],
        "officialUrl": "https://www.bateauivre.coop/%C3%A9v%C3%A8nements/feldup-the-showerheads-trainfantome/",
        "calendarUrl": "https://www.bateauivre.coop/agenda-2/",
        "calendarFields": [
            "leadArtist",
            "date",
            "venue"
        ]
    },
    "go-c-20270128-tours-cachemire-la-phaze-bobs-not-dead": {
        "title": "Cachemire + La Phaze + Bob's Not Dead",
        "date": "2027-01-28",
        "time": None,
        "venueId": "le-bateau-ivre-tours",
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
        "newArtistIds": [],
        "genres": [
            "Rock",
            "Punk"
        ],
        "officialUrl": "https://www.bateauivre.coop/%C3%A9v%C3%A8nements/cachemire-la-phaze-bobs-not-dead/",
        "calendarUrl": "https://www.bateauivre.coop/2027/?post_type=events",
        "calendarFields": [
            "leadArtist",
            "dayMonth",
            "yearIndex",
            "venue"
        ]
    }
}

BATEAU_IVRE_URL_IDS = {
    spec["officialUrl"]: ident for ident, spec in BATEAU_IVRE_SIGNED_20261104.items()
}


# La Vapeur Dijon, official first-party calendar + organizer's ticketing page
# linked directly from it. Weezevent event range 19h30-23h != musical start.
VAPEUR_DIJON_SIGNED_20261104 = {
    "go-c-20270123-dijon-misanthrope-obsession-slapdown": {
        "title": "Misanthrope + Obsession + Slapdown",
        "date": "2027-01-23",
        "time": None,
        "venueId": "la-vapeur-dijon",
        "artistIds": [
            "misanthrope",
            "obsession",
            "slapdown"
        ],
        "artistNames": [
            "Misanthrope",
            "Obsession",
            "Slapdown"
        ],
        "newArtistIds": [
            "obsession",
            "slapdown"
        ],
        "genres": [
            "Metal"
        ],
        "officialUrl": "https://my.weezevent.com/thrash-til-death-2-misanthrope-obsession-slapdown",
        "calendarUrl": "https://www.lavapeur.com/programme/"
    }
}
VAPEUR_DIJON_RESERVED_URLS = {
    spec["officialUrl"]: ident for ident, spec in VAPEUR_DIJON_SIGNED_20261104.items()
}


# Dijon / Skip The Use : fiche organisateur nominative et agenda salle rock,
# sans début musical prouvé. La salle est déjà agréée (Thrash 'til Death 2).
LA_VAPEUR_SKIP_SIGNED_20261104 = {
  "id": "go-c-20270211-dijon-skip-the-use",
  "title": "Skip The Use",
  "date": "2027-02-11",
  "time": None,
  "venueId": "la-vapeur-dijon",
  "artistIds": [
    "skip-the-use"
  ],
  "genres": [
    "Rock"
  ],
  "officialUrl": "https://www.livenation.fr/event/skip-the-use-love-and-anxiety-dijon-tickets-edp1674591",
  "calendarUrl": "https://www.lavapeur.com/programme/"
}

# Dijon : affiche datée et nominative de la salle, recoupée par sa billetterie.
# 19h = portes. Le créneau 20h n'est pas automatiquement une heure musicale.
LA_VAPEUR_RODRIGO_MIDORI_SIGNED_20261104 = {
    "id": "go-c-20270407-dijon-rodrigo-y-gabriela-midori-jaeger",
    "title": "Rodrigo y Gabriela + midori jaeger",
    "date": "2027-04-07",
    "time": None,
    "venueId": "la-vapeur-dijon",
    "artistIds": ["rodrigo-y-gabriela", "midori-jaeger"],
    "artistNames": ["Rodrigo y Gabriela", "midori jaeger"],
    "genres": ["Rock instrumental"],
    "officialUrl": "https://www.lavapeur.com/programme/rodrigo-y-gabriela",
    "ticketUrl": "https://billetterie.lavapeur.com/agenda/840-Rodrigo-y-Gabriela?session=840",
}

TOUR_FIVE_SIGNED_20261105 = json.loads(r'''{"go-c-20261118-grenoble-inspector-cluzo":{"event":{"id":"go-c-20261118-grenoble-inspector-cluzo","title":"The Inspector Cluzo","date":"2026-11-18","time":null,"artistIds":["the-inspector-cluzo"],"venueId":"la-belle-electrique-grenoble","genres":["Rock"],"status":"confirmed","officialUrl":"https://www.la-belle-electrique.com/fr/agenda/the-inspector-cluzo?from=2026-12","sourceType":"salle"},"proofs":[{"url":"https://www.la-belle-electrique.com/fr/agenda/the-inspector-cluzo?from=2026-12","proofType":"official-organizer-or-venue","checkedFields":["artists","date","venue","genre","address"]},{"url":"https://billetterie.la-belle-electrique.com/agenda/741-The-Inspector-Cluzo?session=741","proofType":"official-venue-ticketing-detail","checkedFields":["artists","date","venue"]}]},"go-c-20261205-paris-skip-the-use":{"event":{"id":"go-c-20261205-paris-skip-the-use","title":"Skip The Use","date":"2026-12-05","time":null,"artistIds":["skip-the-use"],"venueId":"zenith-paris-la-villette-paris","genres":["Rock"],"status":"confirmed","officialUrl":"https://le-zenith.com/shows/Skip%20The%20Use-20507","sourceType":"salle"},"proofs":[{"url":"https://le-zenith.com/shows/Skip%20The%20Use-20507","proofType":"official-organizer-or-venue","checkedFields":["artists","date","venue","genre","doorTime"]},{"url":"https://www.livenation.fr/event/skip-the-use-love-and-anxiety-paris-tickets-edp1632116","proofType":"official-promoter-tour-detail","checkedFields":["artists","date","venue"]}]},"go-c-20270122-paris-7weeks":{"event":{"id":"go-c-20270122-paris-7weeks","title":"7Weeks","date":"2027-01-22","time":null,"artistIds":["7weeks"],"venueId":"la-maroquinerie-paris","genres":["Heavy Rock"],"status":"confirmed","officialUrl":"https://7weeks.fr/concerts/","sourceType":"organisateur"},"proofs":[{"url":"https://7weeks.fr/concerts/","proofType":"official-artist-tour-calendar","checkedFields":["artists","date","venue"]},{"url":"https://www.eventim.fr/event/7-weeks-la-maroquinerie-paris-20-21549826/","proofType":"authorized-ticket-distributor-full-date","checkedFields":["artists","date","venue"]}]},"go-c-20270204-villeurbanne-revnoir-ice-sealed-eyes":{"event":{"id":"go-c-20270204-villeurbanne-revnoir-ice-sealed-eyes","title":"Revnoir + Ice Sealed Eyes","date":"2027-02-04","time":"20:00","timeMeaning":"début du concert","artistIds":["revnoir","ice-sealed-eyes"],"venueId":"le-transbordeur-villeurbanne","genres":["Metalcore"],"status":"confirmed","officialUrl":"https://www.transbordeur.fr/evenement/revnoir-ice-sealed-eyes-04022027/","sourceType":"salle"},"proofs":[{"url":"https://www.transbordeur.fr/evenement/revnoir-ice-sealed-eyes-04022027/","proofType":"official-organizer-or-venue","checkedFields":["artists","date","venue","genre","doorTime","concertStartTime"]},{"url":"https://slhproductions.fr/agenda/revnoir2027/","proofType":"official-promoter-event-detail","checkedFields":["artists","date","venue"]}]},"go-c-20270318-ramonville-skip-the-use":{"event":{"id":"go-c-20270318-ramonville-skip-the-use","title":"Skip The Use","date":"2027-03-18","time":null,"artistIds":["skip-the-use"],"venueId":"le-bikini-toulouse","genres":["Rock"],"status":"confirmed","officialUrl":"https://lebikini.com/2027/03/18/skip-the-use","sourceType":"salle"},"proofs":[{"url":"https://lebikini.com/2027/03/18/skip-the-use","proofType":"official-organizer-or-venue","checkedFields":["artists","date","venue","genre","doorTime","address"]},{"url":"https://www.livenation.fr/event/skip-the-use-love-and-anxiety-ramonville-st-agne-tickets-edp1665831","proofType":"official-promoter-tour-detail","checkedFields":["artists","date","venue"]}]}}''')

TOUR_THREE_VERIFIED_20261105 = json.loads(r'''{"go-c-20261122-strasbourg-marillion-lazuli":{"event":{"id":"go-c-20261122-strasbourg-marillion-lazuli","title":"Marillion + Lazuli","date":"2026-11-22","time":null,"artistIds":["marillion","lazuli"],"venueId":"la-laiterie-strasbourg","genres":["Rock progressif"],"status":"confirmed","officialUrl":"https://www.artefact.org/la-laiterie/evenements/marillion/","sourceType":"salle"},"newArtists":[],"proofs":[{"url":"https://www.artefact.org/la-laiterie/evenements/marillion/","proofType":"official-organizer-or-venue","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","genre"],"notes":"Fiche officielle: dimanche 22/11/2026 Marillion + Lazuli, rock progressif. 18h30 = ouverture des portes."},{"url":"https://www.artefact.org/la-laiterie/programmation/","proofType":"first-party-venue-calendar","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","genre"],"notes":"Programmation officielle recoupant date, affiche, salle et genre. Billetterie indiquée complet."}]},"go-c-20261212-toulouse-psykup-manimal":{"event":{"id":"go-c-20261212-toulouse-psykup-manimal","title":"Psykup + Manimal","date":"2026-12-12","time":null,"artistIds":["psykup","manimal"],"venueId":"le-metronum","genres":["Metal"],"status":"confirmed","officialUrl":"https://lemetronum.fr/evenement/psykup/","sourceType":"salle"},"newArtists":[{"id":"manimal","name":"Manimal"}],"proofs":[{"url":"https://lemetronum.fr/evenement/psykup/","proofType":"official-organizer-or-venue","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","genre"],"notes":"Fiche du Metronum: samedi 12/12/2026, Psykup + Manimal, catégorie metal; 20h n'est pas explicitement une heure de début musical."}]},"go-c-20270223-paris-movements-shoreline":{"event":{"id":"go-c-20270223-paris-movements-shoreline","title":"Movements + Shoreline","date":"2027-02-23","time":null,"artistIds":["movements","shoreline"],"venueId":"le-trabendo-paris","genres":["Post-Hardcore"],"status":"confirmed","officialUrl":"https://www.letrabendo.net/programmation/movements/","sourceType":"salle"},"newArtists":[{"id":"movements","name":"Movements"},{"id":"shoreline","name":"Shoreline"}],"proofs":[{"url":"https://www.letrabendo.net/programmation/movements/","proofType":"official-organizer-or-venue","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","genre"],"notes":"Fiche individuelle du Trabendo: 23/02/2027 Movements + Shoreline, post-hardcore. Les portes ouvrent à 19h; aucun début musical déduit."}]}}''')


AERONEF_LILLE_MARILLION_SIGNED_20261105 = json.loads(r'''{"event":{"id":"go-c-20261119-lille-marillion-lazuli","title":"Marillion + Lazuli","date":"2026-11-19","time":null,"artistIds":["marillion","lazuli"],"venueId":"l-aeronef-lille","genres":["Rock progressif"],"status":"confirmed","officialUrl":"https://aeronef.fr/agenda/marillion2026","sourceType":"salle"},"proofs":[{"url":"https://aeronef.fr/agenda/marillion2026","proofType":"official-organizer-or-venue","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","genre"],"notes":"Fiche officielle L'Aéronef : Marillion + Lazuli, jeudi 19 novembre ; titre URL marillion2026 et présentation d'automne 2026, date complète recoupée par l'agenda officiel et le tour du groupe ; 20h00 n'est pas un début musical explicitement attesté."},{"url":"https://aeronef.fr/agenda","proofType":"first-party-venue-calendar","checkedAt":"2026-11-05","checkedFields":["artists","date","venue"],"notes":"Agenda officiel de L'Aéronef, ligne jeudi 19 novembre 2026 : MARILLION + Lazuli, Lille. Année 2026 explicite."},{"url":"https://www.marillion.com/tour/","proofType":"independent-official-artist-tour","checkedAt":"2026-11-05","checkedFields":["artists","date","city","venue","country"],"notes":"Tour officiel Marillion : Thursday 19 November 2026, L'Aeronef, Lille, France ; en-tête France 2026 indique Support - Lazuli. Aucune indication de début musical."}]}''')


NATIONAL_MARILLION_TWO_SIGNED_20261105 = json.loads(r'''{"go-c-20261121-paris-marillion-lazuli":{"event":{"id":"go-c-20261121-paris-marillion-lazuli","title":"Marillion + Lazuli","date":"2026-11-21","time":null,"artistIds":["marillion","lazuli"],"venueId":"casino-de-paris","genres":["Rock progressif"],"status":"confirmed","officialUrl":"https://www.casinodeparis.fr/fr/Marillion-En-Concert-21-Novembre-2026-Billetterie-Paris","sourceType":"salle"},"proofs":[{"url":"https://www.casinodeparis.fr/fr/Marillion-En-Concert-21-Novembre-2026-Billetterie-Paris","proofType":"official-organizer-or-venue","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","genre"],"officialConfirmedArtists":["Marillion"],"notes":"Annonce nominative de la salle Casino de Paris : Marillion, samedi 21/11/2026, rock néo-progressif. Ne nomme pas la première partie. La preuve 'artists' porte ici sur Marillion uniquement ; Lazuli vérifié sur ses propres dates de tournée. 19:00 est une heure de séance, pas un début musical prouvé."},{"url":"https://www.marillion.com/tour/","proofType":"official-artist-tour-calendar","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","country","tourSupport"],"officialConfirmedArtists":["Marillion","Lazuli"],"notes":"Tour officiel Marillion, section Live In France 2026 : Support - Lazuli ; samedi 21 novembre 2026 Casino De Paris, Paris, France."},{"url":"https://lazuli-music.com/tour/","proofType":"independent-official-support-tour","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","country","supportRole"],"officialConfirmedArtists":["Marillion","Lazuli"],"notes":"Tour officiel Lazuli : 21.11.2026 Casino de Paris, Lazuli special guest with Marillion. Indépendant de la salle et du groupe principal."}]},"go-c-20261129-caluire-marillion-lazuli":{"event":{"id":"go-c-20261129-caluire-marillion-lazuli","title":"Marillion + Lazuli","date":"2026-11-29","time":null,"artistIds":["marillion","lazuli"],"venueId":"radiant-bellevue-caluire","genres":["Rock progressif"],"status":"confirmed","officialUrl":"https://radiant-bellevue.fr/spectacles/marillion/","sourceType":"salle"},"proofs":[{"url":"https://radiant-bellevue.fr/spectacles/marillion/","proofType":"official-organizer-or-venue","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","genre"],"officialConfirmedArtists":["Marillion"],"notes":"Fiche Radiant-Bellevue : Marillion, dimanche 29 novembre 2026, rock néo-progressif. La salle est en réalité à Caluire-et-Cuire ; première partie Lazuli attestée séparément. 19:00 est une horaire annoncé sans qualification du début musical."},{"url":"https://www.marillion.com/tour/","proofType":"official-artist-tour-calendar","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","country","tourSupport"],"officialConfirmedArtists":["Marillion","Lazuli"],"notes":"Tour officiel Marillion, section France 2026 : Support - Lazuli ; dimanche 29 novembre 2026 Radiant-Bellevue, Lyon (agglomération), France."},{"url":"https://lazuli-music.com/tour/","proofType":"independent-official-support-tour","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","country","supportRole"],"officialConfirmedArtists":["Marillion","Lazuli"],"notes":"Tour officiel Lazuli : 29.11.2026 Radiant-Bellevue (Lyon), Lazuli special guest with Marillion."}]}}''')


MEM_RENNES_MARILLION_SIGNED_20261105 = json.loads(r'''{"event":{"id":"go-c-20261118-rennes-marillion-lazuli","title":"Marillion + Lazuli","date":"2026-11-18","time":null,"artistIds":["marillion","lazuli"],"venueId":"le-mem-rennes","genres":["Rock progressif"],"status":"confirmed","officialUrl":"https://www.lemem.fr/programmation/marillion/","sourceType":"salle"},"proofs":[{"url":"https://www.lemem.fr/programmation/marillion/","proofType":"official-organizer-or-venue","checkedAt":"2026-11-05","checkedFields":["leadArtist","date","venue","genre"],"confirmedArtists":["Marillion"],"notes":"Fiche 2026 du MeM, 18/11/2026, Le Magic Mirrors, 20h00 affiché et portes à 19h00. Page ne cite que Marillion ; aucune inférence sur la première partie ou sur une heure de début musical garantie."},{"url":"https://lazuli-music.com/tour/","proofType":"independent-official-support-tour","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","supportRole"],"confirmedArtists":["Marillion","Lazuli"],"notes":"Tournée officielle Lazuli : 18.11.2026 Le Mem Rennes, Lazuli special guest with Marillion ; cette source indépendante prouve Lazuli."},{"url":"https://www.marillion.com/tour/","proofType":"official-artist-tour-calendar","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","country","tourSupport"],"confirmedArtists":["Marillion","Lazuli"],"notes":"Marillion - Live In France 2026, section Support - Lazuli : Wednesday 18 November 2026, Le Mem, Rennes, France."},{"url":"https://www.aegpresents.fr/event/marillion/","proofType":"independent-official-organizer-tour","checkedAt":"2026-11-05","checkedFields":["leadArtist","date","venue"],"confirmedArtists":["Marillion"],"notes":"Organisateur AEG Presents France : Marillion 18 novembre au MeM Rennes, vérification de l'annonce sans attribution d'heure musicale."}]}''')


FFF_BRETAGNE_ANJOU_TWO_SIGNED_20261105 = json.loads(r'''{"go-c-20261210-rennes-fff-howlin-jaws":{"event":{"id":"go-c-20261210-rennes-fff-howlin-jaws","title":"FFF + Howlin’ Jaws","date":"2026-12-10","time":null,"artistIds":["fff","howlin-jaws"],"venueId":"le-mem-rennes","genres":["Rock"],"status":"confirmed","officialUrl":"https://www.lemem.fr/programmation/fff/","sourceType":"salle"},"proofs":[{"url":"https://www.lemem.fr/programmation/fff/","proofType":"official-organizer-or-venue","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","genre"],"confirmedArtists":["FFF","Howlin' Jaws"],"notes":"Fiche officielle du Magic Mirrors : FFF + Howlin' Jaws, jeudi 10 décembre 2026, rock, première partie citée explicitement ; 20h avec portes à 19h non déclaré début musical."},{"url":"https://diogene.fr/artistes/fff/","proofType":"independent-official-promoter","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","supportRole"],"confirmedArtists":["FFF","Howlin' Jaws"],"notes":"Diogène Productions : jeudi 10 décembre 2026 Rennes Le MeM, première partie Howlin' Jaws nommée."},{"url":"https://radical-production.fr/artistes/howlin-jaws/","proofType":"independent-official-support-agent","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","supportRole"],"confirmedArtists":["FFF","Howlin' Jaws"],"notes":"Tour officiel Howlin' Jaws/Radical Production : 10 déc. 2026 Rennes, MeM, en première partie de FFF."}]},"go-c-20261211-angers-fff-howlin-jaws":{"event":{"id":"go-c-20261211-angers-fff-howlin-jaws","title":"FFF + Howlin’ Jaws","date":"2026-12-11","time":"20:30","artistIds":["fff","howlin-jaws"],"venueId":"le-chabada-angers","genres":["Funk Rock"],"status":"confirmed","officialUrl":"https://lechabada.com/evenement/fff/","sourceType":"salle"},"proofs":[{"url":"https://lechabada.com/evenement/fff/","proofType":"official-organizer-or-venue","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","genre","concertStartTime"],"confirmedArtists":["FFF","Howlin' Jaws"],"concertStartTimeConfirmed":"20:30","notes":"Fiche salle Chabada vendredi 11 décembre 2026 : F.F.F. + Howlin' Jaws, rock/funk, ouverture des portes 19h45 et *Début des concerts : 20h30* explicitement."},{"url":"https://billetterie.lechabada.com/agenda/947-F-F-F?session=947","proofType":"official-venue-ticketing","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","concertStartTime"],"confirmedArtists":["FFF","Howlin' Jaws"],"concertStartTimeConfirmed":"20:30","notes":"Billetterie nominative du Chabada : F.F.F. + Howlin' Jaws, ouverture 19h45, début concerts 20h30. Horaire attesté explicitement."},{"url":"https://radical-production.fr/artistes/howlin-jaws/","proofType":"independent-official-support-agent","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","supportRole"],"confirmedArtists":["FFF","Howlin' Jaws"],"notes":"Tourneur Howlin' Jaws annonce vendredi 11 décembre 2026 Angers, Chabada, en première partie de FFF."}]}}''')


# Autorisation strictement nominative du 27/02/2027, pas une ouverture
# générale de La Belle Électrique ni de la Tournée du Cœur.
TOURNEE_DU_COEUR_GRENOBLE_SIGNED_20261105 = {
    "event": {
        "id": "go-c-20270227-grenoble-cachemire-la-phaze-bobs-not-dead",
        "title": "Cachemire + La Phaze + Bob's Not Dead",
        "date": "2027-02-27",
        "time": None,
        "artistIds": ["cachemire", "la-phaze", "bobs-not-dead"],
        "venueId": "la-belle-electrique-grenoble",
        "genres": ["Rock", "Punk"],
        "status": "confirmed",
        "officialUrl": "https://www.la-belle-electrique.com/fr/agenda/tournee-du-coeur",
        "sourceType": "salle",
        "organizer": "Rage Tour",
    },
    "proofs": [
        {
            "url": "https://www.la-belle-electrique.com/fr/agenda/tournee-du-coeur",
            "proofType": "official-organizer-or-venue",
            "checkedFields": ["artists", "date", "venue", "genre",
                              "address", "eventTime"],
            "confirmedArtists": ["Cachemire", "La Phaze", "Bob's Not Dead"],
        },
        {
            "url": "https://tourneeducoeur.ragetour.com/",
            "proofType": "official-promoter-tour-calendar",
            "checkedFields": ["date", "city", "venue"],
        },
    ],
}

# Signatures nominatives : deux concerts et une salle, aucune ouverture globale.
PILOT_VENUES["le-sew-morlaix"] = json.loads(r'''{"venue":{"id":"le-sew-morlaix","name":"Le SEW","address":"39 quai du Léon","postalCode":"29600","city":"Morlaix","department":"29","region":"Bretagne","latitude":48.58309,"longitude":-3.83484,"geoPrecision":"Point indicatif de la salle SEW – La Manu publié par MusiTree (48.58309, -3.83484), cohérent avec le repère nommé ToFromFrance 48.58313, -3.83481 ; pas l'entrée exacte du SEW","geoSource":"https://musitree.fr/concerts/salles/sew-la-manu-morlaix/"},"officialUrl":"https://sew-morlaix.com/infos","locationUrl":"https://musitree.fr/concerts/salles/sew-la-manu-morlaix/","locationProofType":"independent-named-venue-geolocation"}''')
TOURNEE_DU_COEUR_MOLOCO_SEW_SIGNED_20261105 = json.loads(r'''{"go-c-20270225-audincourt-cachemire-la-phaze-bobs-not-dead":{"event":{"id":"go-c-20270225-audincourt-cachemire-la-phaze-bobs-not-dead","title":"Cachemire + La Phaze + Bob's Not Dead","date":"2027-02-25","time":null,"artistIds":["cachemire","la-phaze","bobs-not-dead"],"venueId":"le-moloco-audincourt","genres":["Rock","Punk"],"status":"confirmed","officialUrl":"https://www.lemoloco.com/agenda/cachemire-la-phaze-bobs-not-dead/","sourceType":"salle","organizer":"Le Moloco"},"newArtists":[],"proofs":[{"url":"https://www.lemoloco.com/agenda/cachemire-la-phaze-bobs-not-dead/","proofType":"official-organizer-or-venue","checkedFields":["artists","date","venue","genre","doorTime"],"confirmedArtists":["Cachemire","La Phaze","Bob's Not Dead"]},{"url":"https://tourneeducoeur.ragetour.com/","proofType":"official-promoter-tour-calendar","checkedFields":["date","city","venue"]}]},"go-c-20270211-morlaix-cachemire-la-phaze-bobs-not-dead":{"event":{"id":"go-c-20270211-morlaix-cachemire-la-phaze-bobs-not-dead","title":"Cachemire + La Phaze + Bob's Not Dead","date":"2027-02-11","time":"20:00","artistIds":["cachemire","la-phaze","bobs-not-dead"],"venueId":"le-sew-morlaix","genres":["Rock","Punk"],"status":"confirmed","officialUrl":"https://sew-morlaix.com/evenements/la-tournee-du-coeur","sourceType":"salle","organizer":"WART / Le SEW"},"newArtists":[],"proofs":[{"url":"https://sew-morlaix.com/evenements/la-tournee-du-coeur","proofType":"official-organizer-or-venue","checkedFields":["artists","date","venue","genre","doorTime","concertStartTime"],"confirmedArtists":["Cachemire","La Phaze","Bob's Not Dead"],"concertStartTimeConfirmed":"20:00"},{"url":"https://tourneeducoeur.ragetour.com/","proofType":"official-promoter-tour-calendar","checkedFields":["date","city","venue"]}]}}''')


# Éditions nominatives du 4 et 5 février 2027 : deux salles et deux fiches exactes.
TOURNEE_DU_COEUR_SAINT_QUENTIN_VITRY_VENUES_20261105 = json.loads(r'''{"la-manufacture-saint-quentin":{"venue":{"id":"la-manufacture-saint-quentin","name":"La Manufacture","address":"8 rue Paul Codos","postalCode":"02100","city":"Saint-Quentin","department":"02","region":"Hauts-de-France","latitude":49.85444,"longitude":3.27029,"geoPrecision":"Point nominatif indicatif de la Manufacture sur ToFromFrance (49.85444, 3.27029), cohérent avec une fiche événement 49.8544659, 3.2701279 ; entrée exacte non garantie","geoSource":"https://tofromfrance.com/lieu/le-concert-des-deux-pianos-a-la-manufacture"},"officialUrl":"https://www.saint-quentin.fr/1674-la-manufacture.htm","locationUrl":"https://tofromfrance.com/lieu/le-concert-des-deux-pianos-a-la-manufacture","locationProofType":"independent-named-venue-geolocation"},"l-orange-bleue-vitry-le-francois":{"venue":{"id":"l-orange-bleue-vitry-le-francois","name":"L'Orange Bleue","address":"4 rue Auguste Choisy","postalCode":"51300","city":"Vitry-le-François","department":"51","region":"Grand Est","latitude":48.72668,"longitude":4.57955,"geoPrecision":"Point indicatif de la salle L'Orange Bleue publié par MusiTree (48.72668, 4.57955), à proximité du GPS de la fiche technique L'Orange Bleue (48.7264026, 4.5791939) ; entrée exacte non garantie","geoSource":"https://musitree.fr/concerts/salles/bords-2-scenes-lorange-bleue-vitry-le-francois/"},"officialUrl":"https://bords2scenes.fr/infos-pratiques/accueil-billetterie","locationUrl":"https://musitree.fr/concerts/salles/bords-2-scenes-lorange-bleue-vitry-le-francois/","locationProofType":"independent-named-venue-geolocation"}}''')
PILOT_VENUES.update(TOURNEE_DU_COEUR_SAINT_QUENTIN_VITRY_VENUES_20261105)
TOURNEE_DU_COEUR_SAINT_QUENTIN_VITRY_SIGNED_20261105 = json.loads(r'''{"go-c-20270204-saint-quentin-cachemire-la-phaze-bobs-not-dead":{"event":{"id":"go-c-20270204-saint-quentin-cachemire-la-phaze-bobs-not-dead","title":"Cachemire + La Phaze + Bob's Not Dead","date":"2027-02-04","time":null,"artistIds":["cachemire","la-phaze","bobs-not-dead"],"venueId":"la-manufacture-saint-quentin","genres":["Rock","Punk"],"status":"confirmed","officialUrl":"https://billetterie-saint-quentin.mapado.com/en/event/756872-la-tournee-du-coeur","sourceType":"salle","organizer":"Rage Tour / Ville de Saint-Quentin"},"newArtists":[],"proofs":[{"url":"https://billetterie-saint-quentin.mapado.com/en/event/756872-la-tournee-du-coeur","proofType":"official-organizer-or-venue","checkedFields":["artists","date","venue","genre","ticketTime"],"confirmedArtists":["Cachemire","La Phaze","Bob's Not Dead"]},{"url":"https://tourneeducoeur.ragetour.com/","proofType":"official-promoter-tour-calendar","checkedFields":["date","city","venue"]}]},"go-c-20270205-vitry-le-francois-cachemire-la-phaze-bobs-not-dead":{"event":{"id":"go-c-20270205-vitry-le-francois-cachemire-la-phaze-bobs-not-dead","title":"Cachemire + La Phaze + Bob's Not Dead","date":"2027-02-05","time":"21:00","artistIds":["cachemire","la-phaze","bobs-not-dead"],"venueId":"l-orange-bleue-vitry-le-francois","genres":["Rock","Punk"],"status":"confirmed","officialUrl":"https://bords2scenes.fr/agenda/la-tournee-du-coeur-3","sourceType":"salle","organizer":"Bords 2 Scènes"},"newArtists":[],"proofs":[{"url":"https://bords2scenes.fr/agenda/la-tournee-du-coeur-3","proofType":"official-organizer-or-venue","checkedFields":["artists","date","venue","genre","doorTime","concertStartTime"],"confirmedArtists":["Cachemire","La Phaze","Bob's Not Dead"],"concertStartTimeConfirmed":"21:00"},{"url":"https://tourneeducoeur.ragetour.com/","proofType":"official-promoter-tour-calendar","checkedFields":["date","city","venue"]}]}}''')


# La CLEF (date confirmée par l'artiste malgré 'à venir' du promoteur),
# et l'Espace Bel Air, tous deux sourcés et signés indépendamment.
TOURNEE_DU_COEUR_CLEF_BELAIR_VENUES_20261105 = json.loads(r'''{"la-clef-saint-germain-en-laye":{"venue":{"id":"la-clef-saint-germain-en-laye","name":"La CLEF","address":"46 rue de Mareil","postalCode":"78100","city":"Saint-Germain-en-Laye","department":"78","region":"Île-de-France","latitude":48.89409,"longitude":2.08842,"geoPrecision":"Point indicatif nominatif de La CLEF (MusiTree 48.89409,2.08842), confirmé à quelques mètres par Party2Night 48.894068,2.088503; entrée exacte non garantie","geoSource":"https://musitree.fr/concerts/salles/la-clef-saint-germain-en-laye-saint-germain-en-laye/"},"officialUrl":"https://laclef.asso.fr/infos-pratiques/comment-venir/","locationUrl":"https://musitree.fr/concerts/salles/la-clef-saint-germain-en-laye-saint-germain-en-laye/","locationProofType":"independent-named-venue-geolocation"},"espace-bel-air-saint-aubin-du-cormier":{"venue":{"id":"espace-bel-air-saint-aubin-du-cormier","name":"Espace Bel Air","address":"rue des Rochers","postalCode":"35140","city":"Saint-Aubin-du-Cormier","department":"35","region":"Bretagne","latitude":48.25787,"longitude":-1.38968,"geoPrecision":"Point indicatif nominatif du bâtiment Espace Bel Air, OSM way W117002146 via Mapcarta (48.25787,-1.38968), cohérent avec le repère 7J56+44 du plan municipal","geoSource":"https://mapcarta.com/fr/W117002146"},"officialUrl":"https://espacebelair.net/info-pratiques/","locationUrl":"https://mapcarta.com/fr/W117002146","locationProofType":"openstreetmap-venue-way"}}''')
PILOT_VENUES.update(TOURNEE_DU_COEUR_CLEF_BELAIR_VENUES_20261105)
TOURNEE_DU_COEUR_CLEF_BELAIR_SIGNED_20261105 = json.loads(r'''{"go-c-20270129-saint-germain-en-laye-cachemire-la-phaze-bobs-not-dead":{"event":{"id":"go-c-20270129-saint-germain-en-laye-cachemire-la-phaze-bobs-not-dead","title":"Cachemire + La Phaze + Bob's Not Dead","date":"2027-01-29","time":"20:30","artistIds":["cachemire","la-phaze","bobs-not-dead"],"venueId":"la-clef-saint-germain-en-laye","genres":["Rock","Punk"],"status":"confirmed","officialUrl":"https://laclef.asso.fr/evenement/la-tournee-du-coeur-cachemire-la-phaze-bobs-not-dead/","sourceType":"salle","organizer":"La CLEF"},"newArtists":[],"proofs":[{"url":"https://laclef.asso.fr/evenement/la-tournee-du-coeur-cachemire-la-phaze-bobs-not-dead/","proofType":"official-organizer-or-venue","checkedFields":["artists","date","venue","genre","doorTime","concertStartTime"],"confirmedArtists":["Cachemire","La Phaze","Bob's Not Dead"],"concertStartTimeConfirmed":"20:30"},{"url":"https://www.cachemiremusic.fr/concerts.html","proofType":"official-artist-tour-calendar","checkedFields":["artist","date","city","venue"]}]},"go-c-20270212-saint-aubin-du-cormier-cachemire-la-phaze-bobs-not-dead":{"event":{"id":"go-c-20270212-saint-aubin-du-cormier-cachemire-la-phaze-bobs-not-dead","title":"Cachemire + La Phaze + Bob's Not Dead","date":"2027-02-12","time":"20:30","artistIds":["cachemire","la-phaze","bobs-not-dead"],"venueId":"espace-bel-air-saint-aubin-du-cormier","genres":["Rock","Punk"],"status":"confirmed","officialUrl":"https://espacebelair.net/laffiche/saison-culturelle-2026-2027/","sourceType":"salle","organizer":"Espace Bel Air / Saint-Aubin-du-Cormier"},"newArtists":[],"proofs":[{"url":"https://espacebelair.net/laffiche/saison-culturelle-2026-2027/","proofType":"official-organizer-or-venue","checkedFields":["artists","date","venue","genre","concertStartTime"],"confirmedArtists":["Cachemire","La Phaze","Bob's Not Dead"],"concertStartTimeConfirmed":"20:30"},{"url":"https://www.saint-aubin-du-cormier.bzh/evenement/tournee-du-coeur-iii-cachemire-la-phaze-bobs-not-dead/","proofType":"first-party-municipal-event-calendar","checkedFields":["artists","date","city","venue","genre"]}]}}''')


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
    # 29/01 Saint-Germain-en-Laye + 12/02 Saint-Aubin-du-Cormier.
    # Aucune autorisation fondée sur l'inconnu 'À venir' de Rage Tour.
    clef_belair = TOURNEE_DU_COEUR_CLEF_BELAIR_SIGNED_20261105
    locked_urls = {a["event"]["officialUrl"] for a in clef_belair.values()}
    locked_venues = set(TOURNEE_DU_COEUR_CLEF_BELAIR_VENUES_20261105)
    if (event_id in clef_belair or event.get("venueId") in locked_venues
            or event.get("officialUrl") in locked_urls):
        signed_bill = clef_belair.get(event_id)
        require(signed_bill is not None
                and event == signed_bill["event"]
                and approval.get("newArtists", []) == signed_bill["newArtists"]
                and reviewer == "independent-official-verifier",
                "CLEF/Bel Air : événement ou salle non approuvés")
        checked = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= checked <= today,
                "CLEF/Bel Air : signature officielle périmée")
        proofs = signed_bill["proofs"]
        require(isinstance(evidence, list)
                and len(evidence) == len(proofs) == 2
                and all(isinstance(p, dict) for p in evidence),
                "CLEF/Bel Air : sources officielles incomplètes")
        for proof, expected in zip(evidence, proofs):
            require(proof.get("url") == expected["url"]
                    and proof.get("proofType") == expected["proofType"]
                    and proof.get("checkedAt") == checked.isoformat()
                    and proof.get("checkedFields") == expected["checkedFields"]
                    and proof.get("confirmedArtists") == expected.get("confirmedArtists")
                    and proof.get("concertStartTimeConfirmed")
                        == expected.get("concertStartTimeConfirmed"),
                    "CLEF/Bel Air : plateau, horaire ou provenance altérés")
        require(event.get("time") == "20:30"
                and "concertStartTime" in (evidence[0].get("checkedFields") or [])
                and "startTime" not in (evidence[0].get("checkedFields") or []),
                "CLEF/Bel Air : début musical non attesté")

    # 04/02 Saint-Quentin et 05/02 Vitry : aucune autre affiche
    # autorisée dans ces deux salles avant une approbation nominative.
    signed = TOURNEE_DU_COEUR_SAINT_QUENTIN_VITRY_SIGNED_20261105
    protected_urls = {r["event"]["officialUrl"] for r in signed.values()}
    protected_venues = set(TOURNEE_DU_COEUR_SAINT_QUENTIN_VITRY_VENUES_20261105)
    if (event_id in signed or event.get("venueId") in protected_venues
            or event.get("officialUrl") in protected_urls):
        expected = signed.get(event_id)
        require(expected is not None
                and event == expected["event"]
                and approval.get("newArtists", []) == expected["newArtists"]
                and reviewer == "independent-official-verifier",
                "Saint-Quentin/Vitry : affiche non signée ou modifiée")
        checked = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= checked <= today,
                "Saint-Quentin/Vitry : date de vérification ancienne/future")
        proofset = expected["proofs"]
        require(isinstance(evidence, list)
                and len(evidence) == len(proofset) == 2
                and all(isinstance(p, dict) for p in evidence),
                "Saint-Quentin/Vitry : deux preuves indépendantes requises")
        for proof, target in zip(evidence, proofset):
            require(proof.get("url") == target["url"]
                    and proof.get("proofType") == target["proofType"]
                    and proof.get("checkedAt") == checked.isoformat()
                    and proof.get("checkedFields") == target["checkedFields"]
                    and proof.get("confirmedArtists") == target.get("confirmedArtists")
                    and proof.get("concertStartTimeConfirmed")
                        == target.get("concertStartTimeConfirmed"),
                    "Saint-Quentin/Vitry : source, affiche ou heure altérée")
        first_fields = set(evidence[0].get("checkedFields") or [])
        require("startTime" not in first_fields
                and (("concertStartTime" in first_fields)
                     == (event.get("time") is not None)),
                "Saint-Quentin/Vitry : horaire de billetterie confondu avec début musical")

    # Une seule affiche officielle Cachemire/La Phaze/Bob's Not Dead
    # acceptée, et uniquement après revue récente avec deux sources.
    coeur = TOURNEE_DU_COEUR_GRENOBLE_SIGNED_20261105
    if (event_id == coeur["event"]["id"]
            or event.get("officialUrl") == coeur["event"]["officialUrl"]):
        require(event == coeur["event"]
                and approval.get("newArtists", []) == []
                and reviewer == "independent-official-verifier",
                "Tournée du Cœur Grenoble : identité ou validateur altéré")
        reviewed = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= reviewed <= today,
                "Tournée du Cœur Grenoble : revue trop ancienne ou future")
        require(len(evidence) == 2 and all(isinstance(p, dict) for p in evidence),
                "Tournée du Cœur Grenoble : deux sources requises")
        for proof, expected in zip(evidence, coeur["proofs"]):
            require(proof.get("url") == expected["url"]
                    and proof.get("proofType") == expected["proofType"]
                    and proof.get("checkedAt") == reviewed.isoformat()
                    and proof.get("checkedFields") == expected["checkedFields"],
                    "Tournée du Cœur Grenoble : provenance ou champs altérés")
            if "confirmedArtists" in expected:
                require(proof.get("confirmedArtists") ==
                        expected["confirmedArtists"],
                        "Tournée du Cœur Grenoble : affiche officielle altérée")
            require(not ({"concertStartTime", "startTime"}
                         & set(proof.get("checkedFields") or [])),
                    "Tournée du Cœur Grenoble : heure musicale non attestée")
        require(event.get("time") is None,
                "Tournée du Cœur Grenoble : heure inférée interdite")

    # Liste blanche exclusivement pour ces deux affiches datées ; les autres
    # concerts du Moloco restent soumis aux règles existantes, et la salle SEW
    # ne peut être utilisée par une affiche encore non revue.
    coeur_signed = TOURNEE_DU_COEUR_MOLOCO_SEW_SIGNED_20261105
    coeur_urls = {v["event"]["officialUrl"]: key
                  for key, v in coeur_signed.items()}
    if (event_id in coeur_signed
            or event.get("officialUrl") in coeur_urls
            or event.get("venueId") == "le-sew-morlaix"):
        signed = coeur_signed.get(event_id)
        require(signed is not None and event == signed["event"]
                and approval.get("newArtists", []) == signed["newArtists"]
                and reviewer == "independent-official-verifier",
                "Tournée du Cœur Moloco/SEW : affiche ou salle non signée")
        checked = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= checked <= today,
                "Tournée du Cœur Moloco/SEW : revue ancienne ou future")
        expected_proofs = signed["proofs"]
        require(isinstance(evidence, list)
                and len(evidence) == len(expected_proofs) == 2
                and all(isinstance(p, dict) for p in evidence),
                "Tournée du Cœur Moloco/SEW : deux preuves indépendantes exigées")
        for actual, proof in zip(evidence, expected_proofs):
            require(actual.get("url") == proof["url"]
                    and actual.get("proofType") == proof["proofType"]
                    and actual.get("checkedAt") == checked.isoformat()
                    and actual.get("checkedFields") == proof["checkedFields"]
                    and actual.get("confirmedArtists") == proof.get("confirmedArtists")
                    and actual.get("concertStartTimeConfirmed")
                        == proof.get("concertStartTimeConfirmed"),
                    "Tournée du Cœur Moloco/SEW : provenance, heure ou plateau altérés")
        start_fields = set(evidence[0].get("checkedFields") or [])
        require("startTime" not in start_fields
                and (("concertStartTime" in start_fields)
                     == (event.get("time") is not None)),
                "Tournée du Cœur Moloco/SEW : horaires de portes pris pour scène")

    require(event.get("venueId") in venues,
            "Lieu non connu : nouvel emplacement à vérifier avant publication")
    # Aucun candidat de tournée brut ne peut hériter d'une validation de salle.
    # Les deux nouveaux lieux ne sont ouverts qu'aux affiches signées ci-dessus.
    signed_urls = {x["event"]["officialUrl"]: key for key, x in
                   HOWLIN_TWO_SIGNED_20261105.items()}
    if ((event.get("venueId") in HOWLIN_TWO_VENUES
          and event_id not in STRANGLERS_FOUR_SIGNED_20261106) or
            event_id in HOWLIN_TWO_SIGNED_20261105 or
            event.get("officialUrl") in signed_urls):
        spec = HOWLIN_TWO_SIGNED_20261105.get(event_id)
        require(spec is not None and
                event == spec["event"] and
                approval.get("newArtists", []) == spec["newArtists"] and
                approval.get("reviewedBy") == "independent-official-verifier",
                "Howlin’ Jaws Nantes/Aix : identité signée, salle ou artiste modifiés")
        checked = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= checked <= today,
                "Howlin’ Jaws Nantes/Aix : vérification ancienne ou future")
        proofs = spec["proofs"]
        require(len(evidence) == len(proofs) == 2 and
                all(isinstance(p, dict) for p in evidence),
                "Howlin’ Jaws Nantes/Aix : preuves nominatives incomplètes")
        for actual, expected in zip(evidence, proofs):
            require(actual.get("url") == expected["url"] and
                    actual.get("proofType") == expected["proofType"] and
                    actual.get("checkedAt") == checked.isoformat() and
                    actual.get("checkedFields") == expected["checkedFields"] and
                    actual.get("confirmedArtists") == expected["confirmedArtists"],
                    "Howlin’ Jaws Nantes/Aix : champs ou provenance altérés")

    # Cap Caval : URL, artiste, scène et preuve protégés par une signature
    # nominative (pas d'approbation générale de tous ses futurs concerts).
    signed_cap = CAP_CAVAL_SIGNED_20261105["event"]
    if ((event.get("venueId") == "salle-cap-caval-penmarch"
          and event_id not in STRANGLERS_FOUR_SIGNED_20261106) or
            event_id == signed_cap["id"] or
            event.get("officialUrl") == signed_cap["officialUrl"]):
        require(event == signed_cap and
                approval.get("newArtists", []) == [] and
                reviewer == "independent-official-verifier",
                "Cap Caval : concert, salle ou identité modifiés")
        reviewed = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= reviewed <= today,
                "Cap Caval : preuve de revue trop ancienne ou future")
        expected_proofs = CAP_CAVAL_SIGNED_20261105["proofs"]
        require(len(evidence) == len(expected_proofs) == 2 and
                all(isinstance(p,dict) for p in evidence),
                "Cap Caval : deux preuves indépendantes obligatoires")
        for actual, expected in zip(evidence, expected_proofs):
            require(actual.get("url") == expected["url"] and
                    actual.get("proofType") == expected["proofType"] and
                    actual.get("checkedAt") == reviewed.isoformat() and
                    actual.get("checkedFields") == expected["checkedFields"] and
                    actual.get("confirmedArtists") == expected["confirmedArtists"],
                    "Cap Caval : provenance, champs vérifiés ou artistes altérés")
        require(event.get("time") is None,
                "Cap Caval : heure musicale non attestée explicitement")

    # Quatre tournées Howlin’ Jaws terminent la couverture officielle.
    # Toute réutilisation d'ID, de source, d'une nouvelle salle ou changement de
    # plateau, horaire, genre, preuve bloque la publication.
    howlin_four_urls = {p["event"]["officialUrl"]: eid
                        for eid,p in HOWLIN_FINAL_FOUR_SIGNED_20261105.items()}
    if (event_id in HOWLIN_FINAL_FOUR_SIGNED_20261105 or
            event.get("officialUrl") in howlin_four_urls or
            event.get("venueId") == "marche-gare-lyon"):
        spec = HOWLIN_FINAL_FOUR_SIGNED_20261105.get(event_id)
        require(spec is not None
                and event == spec["event"]
                and approval.get("newArtists", []) == spec["newArtists"]
                and reviewer == "independent-official-verifier",
                "Howlin’ Jaws final : fiche, salle, artiste ou URL altérés")
        checked = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= checked <= today,
                "Howlin’ Jaws final : preuve trop ancienne ou future")
        proofs = spec["proofs"]
        require(len(evidence) == len(proofs) and
                all(isinstance(x, dict) for x in evidence),
                "Howlin’ Jaws final : preuves nominatives non complètes")
        for p,q in zip(evidence,proofs):
            require(p.get("url") == q["url"]
                    and p.get("proofType") == q["proofType"]
                    and p.get("checkedAt") == checked.isoformat()
                    and p.get("checkedFields") == q["checkedFields"]
                    and p.get("confirmedArtists") == q["confirmedArtists"],
                    "Howlin’ Jaws final : preuve, provenance ou artistes altérés")
        if event_id in ("go-c-20261118-paris-howlin-jaws-theo-charaf",
                        "go-c-20270429-nancy-howlin-jaws-komodor"):
            require(event.get("time") is None,
                    "Howlin’ Jaws final : heure musicale inférée")
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
    if official_url in BATEAU_IVRE_URL_IDS:
        require(event_id == BATEAU_IVRE_URL_IDS[official_url],
                "Bateau Ivre : URL de concert réservée à son identifiant exact")
    if event_id in BATEAU_IVRE_SIGNED_20261104:
        require(event.get("venueId") == "le-bateau-ivre-tours",
                "Bateau Ivre : identifiant déplacé hors de Tours")
    if official_url in VAPEUR_DIJON_RESERVED_URLS:
        require(event_id == VAPEUR_DIJON_RESERVED_URLS[official_url],
                "La Vapeur : billet nominatif réservé à son concert signé")
    if event_id in VAPEUR_DIJON_SIGNED_20261104:
        require(event.get("venueId") == "la-vapeur-dijon",
                "La Vapeur : identifiant déplacé hors de Dijon")
    if (event_id == LA_VAPEUR_SKIP_SIGNED_20261104["id"]
            or official_url == LA_VAPEUR_SKIP_SIGNED_20261104["officialUrl"]):
        require(event_id == LA_VAPEUR_SKIP_SIGNED_20261104["id"]
                and event.get("venueId") == "la-vapeur-dijon"
                and official_url == LA_VAPEUR_SKIP_SIGNED_20261104["officialUrl"],
                "La Vapeur / Skip : identifiant, URL ou salle réaffectés")
    # Trois fiches nominatives nouvelles. Les URL sont attachées à leurs ID.
    reserved_three = {r["event"]["officialUrl"]: k
                      for k, r in TOUR_THREE_VERIFIED_20261105.items()}
    if official_url in reserved_three:
        require(event_id == reserved_three[official_url],
                "Lot 05/11 : URL nominative déjà réservée")
    if event_id in TOUR_THREE_VERIFIED_20261105:
        pinned = TOUR_THREE_VERIFIED_20261105[event_id]["event"]
        require(event.get("venueId") == pinned["venueId"]
                and official_url == pinned["officialUrl"],
                "Lot 05/11 : ID, salle ou URL non concordants")

    # Marillion Lille : un même lien officiel ne peut homologuer un autre événement.
    aeronef_signed = AERONEF_LILLE_MARILLION_SIGNED_20261105["event"]
    if (event_id == aeronef_signed["id"]
            or official_url == aeronef_signed["officialUrl"]):
        require(event_id == aeronef_signed["id"]
                and event.get("venueId") == aeronef_signed["venueId"]
                and official_url == aeronef_signed["officialUrl"],
                "Marillion Lille : URL, ID et salle réservés")

    # Paris et Caluire : réserver chaque URL de salle à un seul événement signé.
    national_marillion_urls = {v["event"]["officialUrl"]: k
                             for k,v in NATIONAL_MARILLION_TWO_SIGNED_20261105.items()}
    if official_url in national_marillion_urls:
        require(event_id == national_marillion_urls[official_url],
                "Marillion national : URL officielle déjà réservée")
    if event_id in NATIONAL_MARILLION_TWO_SIGNED_20261105:
        pinned = NATIONAL_MARILLION_TWO_SIGNED_20261105[event_id]["event"]
        require(official_url == pinned["officialUrl"]
                and event["venueId"] == pinned["venueId"],
                "Marillion national : ID, salle ou URL déplacés")
    # Marillion Rennes : l'URL nominative du Magic Mirrors ne valide
    # aucune autre date, scène ni artiste que la signature indépendante.
    mem_signed = MEM_RENNES_MARILLION_SIGNED_20261105["event"]
    if event_id == mem_signed["id"] or official_url == mem_signed["officialUrl"]:
        require(event_id == mem_signed["id"]
                and official_url == mem_signed["officialUrl"]
                and event.get("venueId") == "le-mem-rennes",
                "Le MeM : identifiant, salle ou URL de concert réaffectés")
    # FFF/Howlin' Jaws : chaque URL officielle prouve une seule affiche.
    reserved_fff_urls = {x["event"]["officialUrl"]: k
                         for k,x in FFF_BRETAGNE_ANJOU_TWO_SIGNED_20261105.items()}
    if official_url in reserved_fff_urls:
        require(event_id == reserved_fff_urls[official_url],
                "FFF/Howlin' Jaws : URL officielle réutilisée")
    if event_id in FFF_BRETAGNE_ANJOU_TWO_SIGNED_20261105:
        pinned = FFF_BRETAGNE_ANJOU_TWO_SIGNED_20261105[event_id]["event"]
        require(event.get("venueId") == pinned["venueId"]
                and official_url == pinned["officialUrl"],
                "FFF/Howlin' Jaws : identité de salle, titre ou source détournés")
    # Une URL de tournée nominative ne peut servir à publier une autre affiche.
    tour_signed_by_url = {v["event"]["officialUrl"]: k
                          for k, v in TOUR_FIVE_SIGNED_20261105.items()}
    if official_url in tour_signed_by_url:
        require(event_id == tour_signed_by_url[official_url],
                "Tournée vérifiée : URL officielle réaffectée à une autre fiche")
    if event_id in TOUR_FIVE_SIGNED_20261105:
        expected = TOUR_FIVE_SIGNED_20261105[event_id]["event"]
        require(event.get("venueId") == expected["venueId"]
                and official_url == expected["officialUrl"],
                "Tournée vérifiée : identifiant/salle/URL divergents")
    if (event_id == LA_VAPEUR_RODRIGO_MIDORI_SIGNED_20261104["id"]
            or official_url == LA_VAPEUR_RODRIGO_MIDORI_SIGNED_20261104["officialUrl"]):
        require(event_id == LA_VAPEUR_RODRIGO_MIDORI_SIGNED_20261104["id"]
                and official_url == LA_VAPEUR_RODRIGO_MIDORI_SIGNED_20261104["officialUrl"]
                and event.get("venueId") == "la-vapeur-dijon",
                "Dijon/Rodrigo : URL, salle et identifiant signés indissociables")
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
        (item.get("proofType") == "official-organizer-or-venue"
         or (event_id == "go-c-20270122-paris-7weeks"
             and item.get("proofType") == "official-artist-tour-calendar")) and
        isinstance(item.get("checkedAt"), str) and item["checkedAt"]
        for item in evidence if isinstance(item, dict)
    ), "Preuve officielle portant sur l'URL exacte absente")
    blacklab_auto = False
    laiterie_auto = False
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
        backstage = (
            venue == "backstage-by-the-mill-paris" and
            parsed_url.scheme == "https" and
            parsed_url.hostname == "www.backstage-btm.com" and
            re.fullmatch(r"/agenda/[a-z0-9-]{3,100}/", parsed_url.path) and
            not parsed_url.username and not parsed_url.password and
            not parsed_url.port and not parsed_url.query and
            not parsed_url.fragment and
            event.get("time") is None
        )
        atabal_pilot = (
            venue == "atabal-biarritz" and
            event_id == "go-c-20270408-biarritz-peter-hook-and-the-light" and
            official_url == (
                "https://www.atabal-biarritz.fr/agenda/concerts/"
                "peter-hook-the-light-a-joy-division-celebration-jeudi-08-avril-2027/") and
            parsed_url.scheme == "https" and
            parsed_url.hostname == "www.atabal-biarritz.fr" and
            not parsed_url.username and not parsed_url.password and
            not parsed_url.port and not parsed_url.query and
            not parsed_url.fragment and
            event.get("time") is None and
            not (approval.get("newArtists") or [])
        )
        atabal_multi = (
            venue == "atabal-biarritz" and
            parsed_url.scheme == "https" and
            parsed_url.hostname == "www.atabal-biarritz.fr" and
            re.fullmatch(r"/agenda/concerts/[a-z0-9-]{16,220}/",
                         parsed_url.path) and
            not parsed_url.username and not parsed_url.password and
            not parsed_url.port and not parsed_url.query and
            not parsed_url.fragment and
            event_id != "go-c-20270408-biarritz-peter-hook-and-the-light" and
            event.get("time") is None
        )
        blacklab_auto = (
            venue == "the-black-lab-wasquehal" and
            event_id not in ROCKSTORE_BLACKLAB_OFFICIAL_VERIFIED and
            parsed_url.scheme == "https" and
            parsed_url.hostname == "theblacklab.fr" and
            bool(re.fullmatch(r"/agenda/[a-z0-9-]{3,140}/?", parsed_url.path)) and
            not parsed_url.username and not parsed_url.password and
            not parsed_url.port and not parsed_url.query and
            not parsed_url.fragment and
            event.get("time") is None and
            not (approval.get("newArtists") or [])
        )
        laiterie_auto = (
            venue == "la-laiterie-strasbourg" and
            event_id not in LAITERIE_OFFICIAL_VERIFIED and
            event_id not in LAITERIE_SECOND_WAVE_VERIFIED and
            parsed_url.scheme == "https" and
            parsed_url.hostname == "www.artefact.org" and
            bool(re.fullmatch(
                r"/la-laiterie/evenements/[a-z0-9-]{3,140}/",
                parsed_url.path)) and
            not parsed_url.username and not parsed_url.password and
            not parsed_url.port and not parsed_url.query and
            not parsed_url.fragment and
            event.get("time") is None and
            not (approval.get("newArtists") or [])
        )
        require(bool(rex or molotov or ferrailleur or backstage
                     or atabal_pilot or atabal_multi or blacklab_auto
                     or laiterie_auto)
                and event.get("sourceType") == "salle",
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
    # New Morbihan venue: only the two signed first-party concert pages.
    # A generic programme, a different date or a renamed artist cannot pass.
    if (event_id in ECHONOVA_SIGNED_20261104
            or event.get("venueId") == "l-echonova-saint-ave"):
        spec = ECHONOVA_SIGNED_20261104.get(event_id)
        require(spec is not None and reviewer == "independent-official-verifier"
                and event.get("venueId") == "l-echonova-saint-ave"
                and event.get("sourceType") == "salle"
                and event.get("status") == "confirmed"
                and all(event.get(k) == spec[k] for k in
                        ("title", "date", "time", "venueId", "artistIds", "genres"))
                and official_url == spec["officialUrl"],
                "Echonova : fiche hors signature nominative exacte")
        u = urlsplit(official_url)
        require(u.scheme == "https" and u.hostname == "lechonova.com"
                and u.path == urlsplit(spec["officialUrl"]).path
                and re.fullmatch(r"/evenement/[a-z0-9-]+/",u.path)
                and not u.query and not u.fragment
                and not u.username and not u.password and not u.port,
                "Echonova : fiche first-party individuelle requise")
        reviewed = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= reviewed <= today,
                "Echonova : preuve d'événement périmée ou future")
        required = {
            "official-organizer-or-venue":
                (spec["officialUrl"], spec["firstPartyFields"]),
            "independent-ticketing-venue-list":
                (spec["ticketingUrl"], spec["ticketingFields"]),
        }
        require(len(evidence) == 2 and all(isinstance(p,dict) for p in evidence)
                and {p.get("proofType") for p in evidence} == set(required),
                "Echonova : deux sources indépendantes obligatoires")
        for p in evidence:
            expected_url, fields = required[p["proofType"]]
            require(p.get("url") == expected_url
                    and p.get("checkedAt") == reviewed.isoformat()
                    and p.get("checkedFields") == fields
                    and "startTime" not in fields and "doorTime" not in fields,
                    "Echonova : date, artistes, origine ou heure exagérés")
        resolved = dict(known_artist_ids)
        resolved.update(added)
        require(new_artists == spec["newArtists"]
                and len(ids) == len(spec["artistNames"])
                and all(aid in resolved
                        and norm(resolved[aid]["name"]) == norm(name)
                        for aid, name in zip(ids, spec["artistNames"])),
                "Echonova : nouveaux artistes fictifs ou mauvais homonymes")
        if spec["time"] is None:
            require(event.get("time") is None,
                    "Echonova : début musical non confirmé (Meteora)")
    # Validation stricte du lot 05/11, sans jamais inférer les horaires affichés.
    if event_id in TOUR_THREE_VERIFIED_20261105:
        spec = TOUR_THREE_VERIFIED_20261105[event_id]
        require(reviewer == "independent-official-verifier"
                and event == spec["event"]
                and event.get("time") is None
                and new_artists == spec["newArtists"],
                "Lot 05/11 : affiche, identité ou heure de début altérées")
        review_day = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= review_day <= today,
                "Lot 05/11 : revue trop ancienne ou future")
        require(isinstance(evidence, list) and len(evidence) == len(spec["proofs"])
                and all(isinstance(proof, dict) for proof in evidence),
                "Lot 05/11 : nombre de preuves erroné")
        for proof, expected_proof in zip(evidence, spec["proofs"]):
            require(all(proof.get(field) == expected_proof[field] for field in
                        ("url", "proofType", "checkedAt", "checkedFields"))
                    and proof.get("checkedAt") == review_day.isoformat()
                    and not ({"concertStartTime", "startTime", "doorTime"}
                             & set(proof.get("checkedFields") or [])),
                    "Lot 05/11 : preuves, date ou horaire non documentés")
        resolved = dict(known_artist_ids)
        resolved.update(added)
        require(all(aid in resolved for aid in ids)
                and all(a["id"] in ids and
                        norm(resolved[a["id"]]["name"]) == norm(a["name"])
                        for a in new_artists),
                "Lot 05/11 : groupe fictif ou homonyme non revu")

    # Lille : double confirmation de L'Aéronef + source indépendante du groupe.
    # Aucune heure musicalement démontrée ; garder explicitement time=null.
    if event_id == AERONEF_LILLE_MARILLION_SIGNED_20261105["event"]["id"]:
        signed = AERONEF_LILLE_MARILLION_SIGNED_20261105
        require(reviewer == "independent-official-verifier"
                and event == signed["event"]
                and new_artists == [],
                "Marillion Lille : affiche, date ou groupe hors signature")
        checked = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= checked <= today,
                "Marillion Lille : vérification périmée ou future")
        require(isinstance(evidence, list) and len(evidence) == 3
                and all(isinstance(p, dict) for p in evidence),
                "Marillion Lille : trois preuves officielles obligatoires")
        for actual, signed_proof in zip(evidence, signed["proofs"]):
            require(all(actual.get(field) == signed_proof[field] for field in
                        ("url", "proofType", "checkedAt", "checkedFields"))
                    and actual.get("checkedAt") == checked.isoformat()
                    and not ({"startTime", "concertStartTime", "doorTime"} &
                             set(actual.get("checkedFields") or [])),
                    "Marillion Lille : preuve ou heure musicalement non vérifiée")
        require(ids == ["marillion", "lazuli"]
                and all(aid in known_artist_ids for aid in ids)
                and norm(known_artist_ids["marillion"]["name"]) == norm("Marillion")
                and norm(known_artist_ids["lazuli"]["name"]) == norm("Lazuli")
                and event.get("time") is None,
                "Marillion Lille : artiste absent ou heure inventée")

    # Deux concerts Marillion + Lazuli, signés individuellement sans inférer l'heure.
    if event_id in NATIONAL_MARILLION_TWO_SIGNED_20261105:
        spec = NATIONAL_MARILLION_TWO_SIGNED_20261105[event_id]
        expected = spec["event"]
        require(reviewer == "independent-official-verifier"
                and event == expected and event.get("time") is None
                and new_artists == [],
                "Marillion national : affiche, salle, heure ou artiste non signé")
        reviewed_day = norm_date(approval.get("reviewedAt"))
        require(reviewed_day == dt.date(2026, 11, 5)
                and reviewed_day <= today
                and today - reviewed_day <= dt.timedelta(days=14),
                "Marillion national : revue officielle périmée ou future")
        require(isinstance(evidence, list) and len(evidence) == 3
                and all(isinstance(p,dict) for p in evidence),
                "Marillion national : trois preuves officielles indépendantes requises")
        for actual, pinned in zip(evidence, spec["proofs"]):
            require(all(actual.get(field) == pinned[field] for field in
                        ("url","proofType","checkedAt","checkedFields","officialConfirmedArtists"))
                    and actual.get("checkedAt") == reviewed_day.isoformat()
                    and not ({"concertStartTime","startTime","doorTime"}
                             & set(actual.get("checkedFields") or [])),
                    "Marillion national : preuve modifiée ou horaire de scène non prouvé")
        require(evidence[0]["officialConfirmedArtists"] == ["Marillion"]
                and all(p["officialConfirmedArtists"] == ["Marillion","Lazuli"]
                        for p in evidence[1:])
                and ids == ["marillion","lazuli"]
                and norm(known_artist_ids["marillion"]["name"]) == "marillion"
                and norm(known_artist_ids["lazuli"]["name"]) == "lazuli",
                "Marillion national : invité non vérifié indépendamment")
    # Marillion + Lazuli au nouveau MeM : la salle n'annonce que Marillion ;
    # Lazuli est attesté par son propre agenda, sans heure musicale inférée.
    if event_id == MEM_RENNES_MARILLION_SIGNED_20261105["event"]["id"]:
        signed = MEM_RENNES_MARILLION_SIGNED_20261105
        require(reviewer == "independent-official-verifier"
                and event == signed["event"]
                and new_artists == []
                and ids == ["marillion", "lazuli"]
                and event.get("time") is None,
                "Le MeM/Marillion : affiche ou horaire hors revue indépendante")
        checked = norm_date(approval.get("reviewedAt"))
        require(checked == dt.date(2026, 11, 5)
                and checked <= today and today - checked <= dt.timedelta(days=14),
                "Le MeM/Marillion : revue non datée ou périmée")
        require(isinstance(evidence, list) and len(evidence) == 4
                and all(isinstance(p, dict) for p in evidence),
                "Le MeM/Marillion : quatre documents officiels requis")
        for actual, pinned in zip(evidence, signed["proofs"]):
            require(all(actual.get(k) == pinned[k] for k in
                        ("url", "proofType", "checkedAt",
                         "checkedFields", "confirmedArtists"))
                    and actual.get("checkedAt") == checked.isoformat()
                    and not ({"concertStartTime", "startTime", "doorTime"}
                             & set(actual.get("checkedFields") or [])),
                    "Le MeM/Marillion : preuve, rôle ou horaire modifié")
        require(evidence[0]["confirmedArtists"] == ["Marillion"]
                and evidence[1]["confirmedArtists"] == ["Marillion", "Lazuli"]
                and evidence[2]["confirmedArtists"] == ["Marillion", "Lazuli"]
                and evidence[3]["confirmedArtists"] == ["Marillion"]
                and all(aid in known_artist_ids for aid in ids)
                and norm(known_artist_ids["marillion"]["name"]) == "marillion"
                and norm(known_artist_ids["lazuli"]["name"]) == "lazuli",
                "Le MeM/Marillion : première partie inventée ou artiste inconnu")
    # FFF + Howlin' Jaws, Rennes / Angers : horaires distincts documentés.
    if event_id in FFF_BRETAGNE_ANJOU_TWO_SIGNED_20261105:
        spec = FFF_BRETAGNE_ANJOU_TWO_SIGNED_20261105[event_id]
        require(reviewer == "independent-official-verifier"
                and event == spec["event"] and new_artists == []
                and ids == ["fff", "howlin-jaws"]
                and all(aid in known_artist_ids for aid in ids)
                and norm(known_artist_ids["fff"]["name"]) == "fff"
                and norm(known_artist_ids["howlin-jaws"]["name"]) == "howlin jaws",
                "FFF : affiche, groupe, jour, horaire ou lieu non signé")
        reviewed = norm_date(approval.get("reviewedAt"))
        require(reviewed == dt.date(2026, 11, 5)
                and reviewed <= today and today - reviewed <= dt.timedelta(days=14),
                "FFF : preuve non datée ou périmée")
        require(isinstance(evidence,list) and len(evidence) == 3
                and all(isinstance(p, dict) for p in evidence),
                "FFF : trois preuves nominatives officielles exigées")
        for actual, pin in zip(evidence, spec["proofs"]):
            require(all(actual.get(field) == pin[field] for field in
                        ("url","proofType","checkedAt",
                         "checkedFields","confirmedArtists"))
                    and actual.get("checkedAt") == reviewed.isoformat()
                    and actual.get("confirmedArtists") == ["FFF","Howlin' Jaws"],
                    "FFF : source, première partie ou date modifiée")
        if event_id == "go-c-20261210-rennes-fff-howlin-jaws":
            require(event["time"] is None
                    and all(not ({"startTime","doorTime","concertStartTime"} &
                                set(p["checkedFields"])) for p in evidence)
                    and all("concertStartTimeConfirmed" not in p
                            for p in evidence),
                    "FFF Rennes : 20h00 ne prouve pas le début musical")
        else:
            require(event["time"] == "20:30"
                    and evidence[0].get("concertStartTimeConfirmed") == "20:30"
                    and evidence[1].get("concertStartTimeConfirmed") == "20:30"
                    and all("concertStartTime" in p["checkedFields"]
                            for p in evidence[:2])
                    and "concertStartTime" not in evidence[2]["checkedFields"],
                    "FFF Angers : début à 20h30 non attesté par salle et billetterie")
    # Cinq affiches recoupées, signatures exactes et non réutilisables.
    if event_id in TOUR_FIVE_SIGNED_20261105:
        spec = TOUR_FIVE_SIGNED_20261105[event_id]
        expected = spec["event"]
        require(reviewer == "independent-official-verifier"
                and event == expected and event.get("status") == "confirmed"
                and not new_artists,
                "Tournée : identité, plateau, heure ou source non identiques à la revue")
        checked = norm_date(approval.get("reviewedAt"))
        require(checked == dt.date(2026, 11, 5)
                and today - dt.timedelta(days=14) <= checked <= today,
                "Tournée : revue non datée ou preuve expirée")
        require(len(evidence) == len(spec["proofs"]) == 2
                and all(isinstance(p,dict) for p in evidence),
                "Tournée : deux preuves distinctes exigées")
        for observed, pinned in zip(evidence, spec["proofs"]):
            require(observed.get("url") == pinned["url"]
                    and observed.get("proofType") == pinned["proofType"]
                    and observed.get("checkedFields") == pinned["checkedFields"]
                    and observed.get("checkedAt") == checked.isoformat(),
                    "Tournée : source, date, lieu, genre ou heure non vérifiés")
        require(event.get("time") is None or (
            event_id == "go-c-20270204-villeurbanne-revnoir-ice-sealed-eyes"
            and event.get("time") == "20:00"
            and event.get("timeMeaning") == "début du concert"
            and "concertStartTime" in evidence[0]["checkedFields"]),
            "Tournée : début musical non documenté")
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
    # Les cinq concerts sont vérifiés ci-dessus par leurs identités complètes.
    # Ce branchement ne modifie pas les whitelists générales de chaque salle.
    if (event_id in TOUR_FIVE_SIGNED_20261105
            or event_id in TOUR_THREE_VERIFIED_20261105
            or event_id == AERONEF_LILLE_MARILLION_SIGNED_20261105["event"]["id"]
            or event_id in NATIONAL_MARILLION_TWO_SIGNED_20261105
            or event_id == MEM_RENNES_MARILLION_SIGNED_20261105["event"]["id"]
            or event_id in FFF_BRETAGNE_ANJOU_TWO_SIGNED_20261105):
        pass
    elif event_id in UNDERCOVERED_REGIONS_NOV2026_VERIFIED:
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
    elif (event.get("venueId") == "la-laiterie-strasbourg"
          and reviewer == "automated-official-recheck"):
        # Do not weaken the historic individually signed La Laiterie lists.
        # This independent official recheck only accepts ONE previously known
        # canonical artist and its exact Artefact concert detail page.
        require(laiterie_auto and event.get("status") == "confirmed"
                and event.get("organizer") == "La Laiterie"
                and len(ids) == 1 and new_artists == []
                and len(evidence) == 1 and isinstance(evidence[0], dict),
                "La Laiterie automatique : concert hors périmètre")
        proof = evidence[0]
        require(proof.get("url") == official_url
                and proof.get("proofType") == "official-organizer-or-venue"
                and proof.get("checkedAt") == reviewed_at.isoformat()
                and proof.get("checkedFields") ==
                    ["artists", "date", "venue", "genre"]
                and proof.get("sourceStructure") ==
                    "artefact-single-artist-header-and-artist-section"
                and proof.get("officialArtistNames") == [event.get("title")],
                "La Laiterie automatique : artiste ou fiche non corroborés")
        artist = known_artist_ids.get(ids[0])
        require(isinstance(artist, dict) and
                norm(artist.get("name")) == norm(event.get("title"))
                and event_id == (
                    "go-c-" + event["date"].replace("-", "") +
                    "-strasbourg-" + ids[0]),
                "La Laiterie automatique : identité artiste ou ID incohérent")
        require(norm_date(event.get("date")) > today
                and event.get("time") is None
                and len(event.get("genres") or []) == 1
                and event["genres"][0] in {
                    "Post Punk", "Black Metal", "Death Metal",
                    "Hard Rock", "Stoner Rock", "Sludge", "Doom Metal",
                    "Thrash Metal", "Metal", "Punk", "Grunge",
                    "Shoegaze", "Noise Rock", "Math Rock", "Post Rock",
                },
                "La Laiterie automatique : genre, date ou heure non admissibles")
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
    elif (event.get("venueId") == "the-black-lab-wasquehal"
          and reviewer == "automated-official-recheck"):
        # This independent gate mirrors the Black Lab's only permitted
        # verifier: one existing canonical artist, a stable first-party
        # event, no inferred guest, venue, or concert start.
        require(blacklab_auto and event.get("status") == "confirmed"
                and event.get("organizer") == "The Black Lab"
                and len(ids) == 1 and new_artists == []
                and len(evidence) == 1 and isinstance(evidence[0], dict),
                "Black Lab automatique : profil de concert non autorisé")
        p = evidence[0]
        require(p.get("url") == official_url
                and p.get("proofType") == "official-organizer-or-venue"
                and p.get("checkedAt") == reviewed_at.isoformat()
                and p.get("checkedFields") ==
                    ["artists", "date", "venue", "genre"]
                and p.get("sourceStructure") ==
                    "official-event-single-known-artist-recheck"
                and p.get("officialArtistNames") == [event.get("title")],
                "Black Lab automatique : preuve nominative insuffisante")
        artist = known_artist_ids.get(ids[0])
        require(isinstance(artist, dict)
                and norm(artist.get("name")) == norm(event.get("title"))
                and norm(event.get("title")) != ""
                and event_id == ("go-c-" + event["date"].replace("-", "") +
                                 "-wasquehal-" + ids[0]),
                "Black Lab automatique : artiste inconnu ou titre ambigu")
        require(norm_date(event.get("date")) > today
                and event.get("time") is None,
                "Black Lab automatique : date passée ou heure inférée")
        require(len(event.get("genres") or []) == 1 and
                norm(event["genres"][0]) in {
                    "metal", "metalcore", "deathcore", "hardcore", "punk",
                    "stoner", "sludge", "doom", "thrash", "grind",
                    "hard rock", "grunge", "noise rock", "post punk",
                    "rock psychedelique",
                },
                "Black Lab automatique : genre de concert non explicite")
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
        if (reviewer == "automated-official-recheck" and
                event_id == "go-c-20270408-biarritz-peter-hook-and-the-light"):
            # Entirely separate from the signed human Atabal bills: permit
            # ONLY this specific official headliner already present in artists.
            target = (
                "https://www.atabal-biarritz.fr/agenda/concerts/"
                "peter-hook-the-light-a-joy-division-celebration-jeudi-08-avril-2027/")
            checked = norm_date(approval.get("reviewedAt"))
            require(
                event_id == "go-c-20270408-biarritz-peter-hook-and-the-light"
                and event_id not in ATABAL_VERIFIED
                and official_url == target
                and event.get("title") == "PETER HOOK & THE LIGHT"
                and event.get("date") == "2027-04-08"
                and event.get("time") is None
                and event.get("artistIds") == ["peter-hook-and-the-light"]
                and event.get("genres") == ["Post Punk"]
                and event.get("status") == "confirmed"
                and event.get("sourceType") == "salle"
                and event.get("organizer") == "Atabal"
                and new_artists == []
                and today - dt.timedelta(days=7) <= checked <= today,
                "Atabal auto : événement, artiste, statut ou preuve périmée"
            )
            u=urlsplit(official_url)
            require(
                u.scheme == "https" and u.hostname == "www.atabal-biarritz.fr"
                and re.fullmatch(r"/agenda/concerts/[a-z0-9-]{16,220}/", u.path)
                and not u.username and not u.password and not u.port
                and not u.query and not u.fragment,
                "Atabal auto : seule une URL individuelle officielle HTTPS est admise"
            )
            require(len(evidence) == 1 and isinstance(evidence[0],dict),
                    "Atabal auto : une seule preuve nominative exigée")
            proof=evidence[0]
            require(
                proof.get("url") == target
                and proof.get("proofType") == "official-organizer-or-venue"
                and proof.get("checkedAt") == checked.isoformat()
                and proof.get("checkedFields") == ["artists","date","venue","genre"]
                and proof.get("officialArtistNames") == ["PETER HOOK & THE LIGHT"],
                "Atabal auto : preuve première main nominative complète requise"
            )
            known=known_artist_ids.get("peter-hook-and-the-light")
            require(
                isinstance(known, dict)
                and known.get("id") == "peter-hook-and-the-light"
                and norm(known.get("name")) == "peter hook and the light",
                "Atabal auto : identité de l'artiste canonique non démontrée"
            )
        elif reviewer == "automated-official-recheck":
            # Unlike the exact Peter Hook pilot, only first-party programmes
            # with THREE OR FOUR acts repeated as separate named sections
            # qualify. The producer enforces page structure; this independent
            # publisher checks all identity, URL, time, genre and proof fields.
            checked = norm_date(approval.get("reviewedAt"))
            require(today - dt.timedelta(days=7) <= checked <= today,
                    "Atabal multi : revue trop ancienne ou future")
            require(event_id not in ATABAL_VERIFIED and
                    official_url not in {v["officialUrl"]
                                         for v in ATABAL_VERIFIED.values()},
                    "Atabal multi : affiche déjà réservée à une signature humaine")
            u = urlsplit(official_url)
            date_slug = re.search(
                r"-(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)-"
                r"(\d{1,2})-(janvier|fevrier|mars|avril|mai|juin|juillet|"
                r"aout|septembre|octobre|novembre|decembre)-(20\d{2})/$",
                u.path)
            require(date_slug is not None,
                    "Atabal multi : URL sans date complète")
            month_map = {name: n for n, name in enumerate(
                ("janvier", "fevrier", "mars", "avril", "mai", "juin",
                 "juillet", "aout", "septembre", "octobre",
                 "novembre", "decembre"), 1)}
            try:
                url_day = dt.date(int(date_slug.group(3)),
                                  month_map[date_slug.group(2)],
                                  int(date_slug.group(1)))
            except (ValueError, TypeError) as exc:
                raise ValueError("Atabal multi : date URL invalide") from exc
            require(event.get("date") == url_day.isoformat()
                    and url_day > today,
                    "Atabal multi : date URL et concert divergents")
            require(len(evidence) == 1 and isinstance(evidence[0], dict),
                    "Atabal multi : une preuve nominative exacte exigée")
            proof = evidence[0]
            names = proof.get("officialArtistNames")
            require(isinstance(names, list) and
                    3 <= len(names) <= 4 and
                    all(isinstance(n, str) and
                        3 <= len(norm(n)) <= 100 for n in names) and
                    len({norm(n) for n in names}) == len(names),
                    "Atabal multi : artistes non documentés et non distincts")
            require(proof.get("url") == official_url
                    and proof.get("proofType") == "official-organizer-or-venue"
                    and proof.get("checkedAt") == checked.isoformat()
                    and proof.get("checkedFields") == [
                        "artists", "date", "venue", "genre"]
                    and proof.get("sourceStructure") ==
                        "event-header-and-named-artist-sections"
                    and proof.get("verifiedNewArtists") ==
                        [a["name"] for a in new_artists],
                    "Atabal multi : source ou artistes nouveaux non corroborés")
            require(event.get("title") == " + ".join(names)
                    and event.get("status") == "confirmed"
                    and event.get("sourceType") == "salle"
                    and event.get("organizer") == "Atabal"
                    and event.get("time") is None
                    and event.get("genres") in (
                        ["Hardcore"], ["Post Punk"], ["Punk Rock"],
                        ["Punk"], ["Metal"], ["Sludge Metal"],
                        ["Metalcore"], ["Hard Rock"], ["Deathcore"],
                        ["Heavy Metal"], ["Grindcore"], ["Stoner"],
                        ["Doom"], ["Thrash"]),
                    "Atabal multi : affiche, genre, heure ou statut non approuvés")
            expected_id = ("go-c-" + url_day.strftime("%Y%m%d") +
                           "-biarritz-" + "-".join(
                               norm(n).replace(" ", "-")[:72].strip("-")
                               for n in names))
            require(event_id == expected_id and len(ids) == len(names),
                    "Atabal multi : ID d'affiche ou nombre d'artistes divergent")
            resolved = dict(known_artist_ids)
            resolved.update(added)
            require(all(aid in resolved and
                        norm(resolved[aid]["name"]) == norm(name)
                        for aid, name in zip(ids, names)),
                    "Atabal multi : identité d'artiste falsifiée")
            existing = {norm(a["name"]) for a in known_artist_ids.values()}
            existing_aliases = {
                norm(alias) for a in known_artist_ids.values()
                for alias in (a.get("aliases") or [])
                if isinstance(alias, str)
            }
            require(all(norm(a["name"]) not in existing | existing_aliases
                        and a["id"] ==
                        norm(a["name"]).replace(" ", "-")[:72].strip("-")
                        for a in new_artists),
                    "Atabal multi : nouvel artiste ou alias en collision")
        else:
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
    elif (event_id in STRANGLERS_FOUR_SIGNED_20261106
          or official_url in {
              r["event"]["officialUrl"] for r in
              STRANGLERS_FOUR_SIGNED_20261106.values()}):
        # Per-event exact signatures; a published venue is not a blanket grant.
        signed = STRANGLERS_FOUR_SIGNED_20261106.get(event_id)
        require(signed is not None
                and reviewer == "independent-official-verifier"
                and event == signed["event"]
                and event.get("sourceType") == "salle"
                and new_artists == [],
                "The Stranglers : affiche, salle ou identité hors signature")
        reviewed = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= reviewed <= today,
                "The Stranglers : revue officielle ancienne ou future")
        pinned = signed["proofs"]
        require(len(evidence) == len(pinned) == 2
                and all(isinstance(p, dict) for p in evidence),
                "The Stranglers : deux preuves de provenance obligatoires")
        for actual, expected in zip(evidence, pinned):
            require(all(actual.get(k) == expected[k] for k in
                        ("url", "proofType", "checkedFields",
                         "officialArtistNames"))
                    and actual.get("checkedAt") == reviewed.isoformat()
                    and actual.get("concertStartTimeConfirmed")
                        == expected.get("concertStartTimeConfirmed")
                    and actual.get("doorTimeConfirmed")
                        == expected.get("doorTimeConfirmed"),
                    "The Stranglers : preuves, artistes ou horaires modifiés")
        require(
            all((known_artist_ids.get(ident) or {}).get("name") == name
                for ident, name in zip(event["artistIds"],
                   ["The Stranglers", "Brother Junior"][:len(event["artistIds"])]))
            and event["artistIds"][0] == "the-stranglers"
            and (len(event["artistIds"]) == 1
                 or event["artistIds"] == ["the-stranglers", "brother-junior"]),
            "The Stranglers : réutilisation canonique des artistes invalide")
        require(any(p.get("concertStartTimeConfirmed") == event["time"]
                    and "concertStartTime" in p["checkedFields"]
                    for p in evidence),
                "The Stranglers : horaire du billet ou des portes non prouvé")
        official = urlsplit(official_url)
        require(official.scheme == "https"
                and official.hostname == urlsplit(signed["event"]["officialUrl"]).hostname
                and official.path == urlsplit(signed["event"]["officialUrl"]).path
                and not official.username and not official.password
                and not official.port and not official.query
                and not official.fragment,
                "The Stranglers : URL de salle officielle invalide")
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
        if event_id == "go-c-20261124-cenon-the-stranglers":
            # Venue event detail and its own ticketing page agree on a complete
            # named bill. The ticketing is NOT a second independent organizer.
            # Never infer the music start from doors or from ticket availability.
            require(len(evidence) == 2
                    and all(isinstance(p, dict) for p in evidence),
                    "Rocher/Stranglers : fiche et billetterie officielles requises")
            proof, ticket = evidence
            require(proof.get("url") == official_url
                    and proof.get("proofType") == "official-organizer-or-venue"
                    and proof.get("checkedAt") == reviewed_at.isoformat()
                    and proof.get("checkedFields") ==
                       ["artists", "date", "venue", "genre", "startTime", "doorTime"]
                    and proof.get("officialArtistNames") ==
                       ["The Stranglers", "Brother Junior"]
                    and proof.get("concertStartTimeConfirmed") == "20:30"
                    and proof.get("doorTimeConfirmed") == "19:30",
                    "Rocher/Stranglers : affiche, genre ou heures non attestés")
            require(ticket.get("url") ==
                       "https://billetterie.lerocherdepalmer.fr/agenda/1862-THE-STRANGLERS?session=1862"
                    and ticket.get("proofType") == "first-party-venue-ticketing"
                    and ticket.get("checkedAt") == reviewed_at.isoformat()
                    and ticket.get("checkedFields") ==
                       ["artists", "date", "venue"]
                    and ticket.get("officialArtistNames") ==
                       ["The Stranglers", "Brother Junior"],
                    "Rocher/Stranglers : seconde fiche de billetterie non conforme")
            require(new_artists == [
                        {"id": "brother-junior", "name": "Brother Junior"}]
                    and known_artist_ids.get("the-stranglers", {}).get("name") ==
                        "The Stranglers"
                    and event.get("organizer") == "Le Rocher de Palmer",
                    "Rocher/Stranglers : identité canonique ou organisateur incorrect")
        else:
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
        target = urlsplit(official_url)
        require(target.scheme == "https" and
                target.hostname == "www.backstage-btm.com"
                and not target.username and not target.password
                and not target.port and not target.query and not target.fragment
                and re.fullmatch(r"/agenda/[a-z0-9-]{3,100}/", target.path),
                "Backstage : fiche événement individuelle HTTPS obligatoire")
        reviewed_at = norm_date(approval.get("reviewedAt"))
        if reviewer == "automated-official-recheck":
            # This is a DIFFERENT trust route from the signed historic bills.
            # It accepts only a fresh first-party H1/date/category/venue
            # recheck, with all band names recorded explicitly in the proof.
            require(event_id not in BACKSTAGE_VERIFIED
                    and event.get("sourceType") == "salle"
                    and event.get("status") == "confirmed"
                    and event.get("time") is None
                    and today - dt.timedelta(days=7) <= reviewed_at <= today,
                    "Backstage auto : signature réservée, horaire ou preuve périmée")
            require(len(evidence) == 1 and isinstance(evidence[0], dict),
                    "Backstage auto : une preuve officielle individuelle exigée")
            proof = evidence[0]
            require(proof.get("url") == official_url
                    and proof.get("proofType") == "official-organizer-or-venue"
                    and proof.get("checkedAt") == reviewed_at.isoformat()
                    and proof.get("checkedFields") == ["artists","date","venue","genre"],
                    "Backstage auto : date, genre, lieu ou origine non attestés")
            names = proof.get("officialArtistNames")
            displayed = re.split(r"\s+\+\s+", event.get("title", ""))
            require(isinstance(names, list) and 1 <= len(names) <= 5
                    and all(isinstance(n, str) and len(norm(n)) >= 3 for n in names)
                    and len({norm(n) for n in names}) == len(names)
                    and len(displayed) == len(names)
                    and all(norm(x) == norm(y) for x,y in zip(displayed,names)),
                    "Backstage auto : plateau non nominatif ou mal décomposé")
            require(event_id == ("go-c-" + event["date"].replace("-", "")
                                + "-paris-" + norm(names[0]).replace(" ","-")[:72]),
                    "Backstage auto : identité/date du concert non déterministe")
            safe_genres = {"Groove Metal","Black Metal","Death Metal",
                "Melodic Death Metal","Metalcore","Industrial Metal",
                "Progressive Metal","Heavy Metal","Thrash Metal","Hardcore",
                "Post Hardcore","Post Metal","Doom Metal","Stoner Rock",
                "Punk Rock","Punk","Metal","Hard Rock"}
            require(isinstance(event.get("genres"), list)
                    and len(event["genres"]) == 1
                    and event["genres"][0] in safe_genres,
                    "Backstage auto : genre non qualifié par le détail officiel")
            resolved = dict(known_artist_ids)
            resolved.update(added)
            require(len(ids) == len(names)
                    and all(aid in resolved and norm(resolved[aid]["name"]) == norm(name)
                            for aid,name in zip(ids,names))
                    and all(a["id"] == norm(a["name"]).replace(" ","-")[:72]
                            for a in new_artists),
                    "Backstage auto : identité d'artiste ou alias non corroboré")
            aliases = {norm(alias)
                       for obj in known_artist_ids.values()
                       for alias in (obj.get("aliases") or [])
                       if isinstance(alias,str)}
            require(all(norm(a["name"]) not in aliases
                        and a["id"] not in known_artist_ids
                        for a in new_artists),
                    "Backstage auto : nouvel artiste déjà référencé comme alias")
        else:
            # Legacy nominated human reviews remain untouched.
            spec = BACKSTAGE_VERIFIED.get(event_id)
            require(spec is not None and reviewer == "independent-official-verifier"
                    and event.get("sourceType") == "salle"
                    and all(event.get(k) == spec[k] for k in
                            ("title", "date", "artistIds", "genres"))
                    and official_url == spec["url"] and event.get("time") is None,
                    "Backstage : concert hors liste blanche ou heure non documentée")
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
    # Tours: a named official page AND the year-aware first-party index.
    # The 19h30/20h printed by the venue is DOOR time, never music start.
    if (event_id in BATEAU_IVRE_SIGNED_20261104
            or event.get("venueId") == "le-bateau-ivre-tours"
            or official_url in BATEAU_IVRE_URL_IDS):
        spec = BATEAU_IVRE_SIGNED_20261104.get(event_id)
        require(spec is not None and reviewer == "independent-official-verifier"
                and event.get("venueId") == "le-bateau-ivre-tours"
                and event.get("sourceType") == "salle"
                and event.get("status") == "confirmed"
                and all(event.get(field) == spec[field] for field in
                        ("title","date","time","venueId","artistIds","genres"))
                and official_url == spec["officialUrl"],
                "Bateau Ivre : affiche hors liste nominative examinée")
        url = urlsplit(official_url)
        require(url.scheme == "https" and url.hostname == "www.bateauivre.coop"
                and re.fullmatch(r"/%C3%A9v%C3%A8nements/[a-z0-9-]+/",url.path)
                and not url.username and not url.password and not url.port
                and not url.query and not url.fragment,
                "Bateau Ivre : fiche individuelle de la salle obligatoire")
        reviewed = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= reviewed <= today,
                "Bateau Ivre : preuve ancienne ou postérieure")
        require(len(evidence) == 2 and all(isinstance(p,dict) for p in evidence)
                and {p.get("proofType") for p in evidence} ==
                    {"official-organizer-or-venue","first-party-venue-calendar"},
                "Bateau Ivre : détail officiel et index daté exigés")
        proofs = {p["proofType"]: p for p in evidence}
        expected_proofs = (
            ("official-organizer-or-venue",spec["officialUrl"],
             ["artists","date","venue","genre"]),
            ("first-party-venue-calendar",spec["calendarUrl"],
             spec["calendarFields"]),
        )
        for kind, expected_url, fields in expected_proofs:
            proof = proofs[kind]
            require(proof.get("url") == expected_url
                    and proof.get("checkedAt") == reviewed.isoformat()
                    and proof.get("checkedFields") == fields,
                    "Bateau Ivre : source officielle, année ou champs altérés")
            require(not ({"startTime","concertStartTime","doorTime"} &
                         set(proof["checkedFields"])),
                    "Bateau Ivre : horaire d'ouverture surdéclaré")
        require(new_artists == [
            {"id": aid, "name": spec["artistNames"][i]}
            for i,aid in enumerate(spec["artistIds"])
            if aid in spec["newArtistIds"]],
            "Bateau Ivre : nouveaux artistes non conformes")
        resolved = dict(known_artist_ids)
        resolved.update(added)
        require(len(ids) == len(spec["artistNames"]) and all(
            aid in resolved and norm(resolved[aid]["name"]) == norm(name)
            for aid,name in zip(ids,spec["artistNames"])),
            "Bateau Ivre : artistes non identiques à l'affiche")
        require(event.get("time") is None,
                "Bateau Ivre : heure de début musical non attestée")
    # Dijon: authorization derives from the venue's exact public listing,
    # linked to the named organizer booking page bearing the complete year.
    # Dijon / La Vapeur: official organizer event page proves 11 Feb 2027,
    # the venue programme independently proves genre. Both are necessary.
    # Generic cards, moved events, an unnamed guest or door-time fail closed.
    if (event.get("venueId") == "la-vapeur-dijon"
            and event_id == LA_VAPEUR_SKIP_SIGNED_20261104["id"]):
        spec = LA_VAPEUR_SKIP_SIGNED_20261104
        require(event_id == spec["id"] and reviewer == "independent-official-verifier"
                and event.get("sourceType") == "organisateur"
                and event.get("status") == "confirmed"
                and all(event.get(field) == spec[field] for field in
                        ("title", "date", "time", "venueId", "artistIds", "genres"))
                and official_url == spec["officialUrl"],
                "La Vapeur : affiche non incluse dans la signature de Dijon")
        u = urlsplit(official_url)
        require(u.scheme == "https" and u.hostname == "www.livenation.fr"
                and u.path == "/event/skip-the-use-love-and-anxiety-dijon-tickets-edp1674591"
                and not u.query and not u.fragment and not u.username
                and not u.password and not u.port,
                "La Vapeur : fiche nominative organisateur exacte requise")
        reviewed = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= reviewed <= today,
                "La Vapeur : preuve périmée ou future")
        require(len(evidence) == 2 and all(isinstance(p,dict) for p in evidence)
                and {p.get("proofType") for p in evidence} ==
                    {"official-organizer-or-venue", "first-party-venue-calendar"},
                "La Vapeur : deux preuves de provenance indépendante exigées")
        proofs = {p["proofType"]: p for p in evidence}
        for kind, url, fields in (
            ("official-organizer-or-venue",spec["officialUrl"],
             ["artists","date","venue"]),
            ("first-party-venue-calendar",spec["calendarUrl"],
             ["artists","venue","genre","dayMonth"]),
        ):
            proof = proofs[kind]
            require(proof.get("url") == url
                    and proof.get("checkedAt") == reviewed.isoformat()
                    and proof.get("checkedFields") == fields,
                    "La Vapeur : date, genre ou URL de preuve surdéclarés")
            require(not ({"startTime", "concertStartTime", "doorTime"}
                         & set(proof["checkedFields"])),
                    "La Vapeur : aucune heure musicale officiellement prouvée")
        require(new_artists == [] and ids == ["skip-the-use"]
                and norm(known_artist_ids["skip-the-use"]["name"]) == norm("Skip The Use")
                and event.get("time") is None,
                "La Vapeur : artistes ajoutés ou horaire musical inventé")
        return event, added
    # La Vapeur / Rodrigo y Gabriela : contrôle intégral avant le verrou
    # historique de Dijon. Seul cet identifiant exact peut utiliser la page
    # nominative ; toutes les autres affiches restent soumises au verrou ancien.
    if event_id == LA_VAPEUR_RODRIGO_MIDORI_SIGNED_20261104["id"]:
        spec = LA_VAPEUR_RODRIGO_MIDORI_SIGNED_20261104
        require(reviewer == "independent-official-verifier"
                and event.get("sourceType") == "salle"
                and event.get("status") == "confirmed"
                and all(event.get(field) == spec[field] for field in
                        ("id", "title", "date", "time", "venueId",
                         "artistIds", "genres", "officialUrl")),
                "La Vapeur/Rodrigo : date, artistes ou salle hors signature")
        source_url = urlsplit(official_url)
        require(source_url.scheme == "https"
                and source_url.hostname == "www.lavapeur.com"
                and source_url.path == "/programme/rodrigo-y-gabriela"
                and not source_url.query and not source_url.fragment
                and not source_url.username and not source_url.password
                and not source_url.port,
                "La Vapeur/Rodrigo : fiche nominative officielle exacte exigée")
        checked = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= checked <= today,
                "La Vapeur/Rodrigo : contrôle officiel périmé ou futur")
        require(len(evidence) == 2 and all(isinstance(p, dict) for p in evidence)
                and {p.get("proofType") for p in evidence} ==
                {"official-organizer-or-venue", "official-venue-ticketing-detail"},
                "La Vapeur/Rodrigo : fiche et billetterie officielles obligatoires")
        proofs = {p["proofType"]: p for p in evidence}
        for kind, expected_url, fields in (
            ("official-organizer-or-venue", spec["officialUrl"],
             ["artists", "date", "venue", "genre"]),
            ("official-venue-ticketing-detail", spec["ticketUrl"],
             ["artists", "date", "venue"]),
        ):
            p = proofs[kind]
            require(p.get("url") == expected_url
                    and p.get("checkedAt") == checked.isoformat()
                    and p.get("checkedFields") == fields,
                    "La Vapeur/Rodrigo : preuve nominative ou date altérée")
            require(not ({"doorTime", "concertStartTime", "startTime"}
                         & set(p["checkedFields"])),
                    "La Vapeur/Rodrigo : horaire non confirmé")
        p = urlsplit(spec["ticketUrl"])
        require(p.hostname == "billetterie.lavapeur.com"
                and p.path == "/agenda/840-Rodrigo-y-Gabriela"
                and p.query == "session=840",
                "La Vapeur/Rodrigo : billetterie non associée à cette affiche")
        resolved = dict(known_artist_ids)
        resolved.update(added)
        require(new_artists == []
                and len(ids) == len(spec["artistNames"])
                and all(aid in resolved and norm(resolved[aid]["name"]) == norm(name)
                        for aid, name in zip(ids, spec["artistNames"])),
                "La Vapeur/Rodrigo : participants fictifs ou identités remplacées")
        require(event.get("time") is None,
                "La Vapeur/Rodrigo : portes transformées en heure musicale")
        return event, added
    if (event_id in VAPEUR_DIJON_SIGNED_20261104
            or event.get("venueId") == "la-vapeur-dijon"
            or official_url in VAPEUR_DIJON_RESERVED_URLS):
        spec = VAPEUR_DIJON_SIGNED_20261104.get(event_id)
        require(spec is not None and reviewer == "independent-official-verifier"
                and event.get("sourceType") == "organisateur"
                and event.get("status") == "confirmed"
                and event.get("venueId") == "la-vapeur-dijon"
                and official_url == spec["officialUrl"]
                and all(event.get(k) == spec[k] for k in
                        ("title","date","time","venueId","artistIds","genres")),
                "La Vapeur : affiche non signée ou nom/date falsifiés")
        url = urlsplit(official_url)
        require(url.scheme == "https" and url.hostname == "my.weezevent.com"
                and url.path == "/thrash-til-death-2-misanthrope-obsession-slapdown"
                and not url.username and not url.password and not url.port
                and not url.query and not url.fragment,
                "La Vapeur : billetterie de l'organisateur nominative requise")
        reviewed = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=14) <= reviewed <= today,
                "La Vapeur : preuve ancienne ou future")
        require(len(evidence) == 2 and all(isinstance(p,dict) for p in evidence)
                and {p.get("proofType") for p in evidence} ==
                    {"official-organizer-or-venue","first-party-venue-calendar"},
                "La Vapeur : billetterie reliée à la salle et programme exigés")
        ticket = next(p for p in evidence if p["proofType"] == "official-organizer-or-venue")
        calendar = next(p for p in evidence if p["proofType"] == "first-party-venue-calendar")
        require(ticket.get("url") == spec["officialUrl"]
                and ticket.get("checkedAt") == reviewed.isoformat()
                and ticket.get("checkedFields") == ["artists","date","venue","genre"]
                and ticket.get("officialOrganizer") == "Association Phoenix Rising",
                "La Vapeur : autorisation, année ou organisateur Weezevent non attestés")
        require(calendar.get("url") == spec["calendarUrl"]
                and calendar.get("checkedAt") == reviewed.isoformat()
                and calendar.get("checkedFields") == ["artists","dayMonth","venue","genre"]
                and calendar.get("linkedBookingUrl") == spec["officialUrl"],
                "La Vapeur : programme officiel ou lien vers la billetterie absent")
        resolved = dict(known_artist_ids)
        resolved.update(added)
        require(new_artists == [{"id":aid,"name":spec["artistNames"][i]}
                for i,aid in enumerate(spec["artistIds"])
                if aid in spec["newArtistIds"]]
                and len(ids) == len(spec["artistNames"])
                and all(aid in resolved and norm(resolved[aid]["name"]) == norm(name)
                        for aid,name in zip(ids,spec["artistNames"])),
                "La Vapeur : groupe ajouté ou identité remplacée")
        require(event.get("time") is None,
                "La Vapeur : 19h30–23h est un créneau de billetterie, pas un début musical")
    return event, added



GWENDOLINE_CORRECTION_ID = "go-c-20261107-cenon-gwendoline"
GWENDOLINE_CORRECTION_DATE = "2026-11-06"
GWENDOLINE_CORRECTION_URL = "https://lerocherdepalmer.fr/agenda/gwendoline"
GWENDOLINE_CORRECTION_CHANGE = (
    "Première partie Bleu Panique ajoutée après vérification officielle "
    "du programme du Rocher de Palmer"
)


def validate_gwendoline_signed_correction(existing, approval):
    """Narrow, signed, persistent correction of one previously published bill.

    Return True only when the original one-artist event still needs the edit.
    This does not authorize generic changes to events or reference records.
    """
    spec = ROCHER_PALMER_VERIFIED[GWENDOLINE_CORRECTION_ID]
    signed = approval.get("event") or {}
    require(approval.get("reviewDecision") == "approved"
            and approval.get("reviewedBy") == "independent-official-verifier"
            and approval.get("reviewedAt") == GWENDOLINE_CORRECTION_DATE,
            "Gwendoline : approbation indépendante actualisée absente")
    proof = approval.get("officialEvidence")
    require(isinstance(proof, list) and len(proof) == 1
            and isinstance(proof[0], dict)
            and proof[0].get("url") == GWENDOLINE_CORRECTION_URL
            and proof[0].get("proofType") == "official-organizer-or-venue"
            and proof[0].get("checkedAt") == GWENDOLINE_CORRECTION_DATE
            and {"artists", "date", "venue", "genre", "startTime"}.issubset(
                set(proof[0].get("checkedFields") or [])),
            "Gwendoline : preuve officielle actualisée insuffisante")
    require(approval.get("newArtists") == [
                {"id": "gwendoline", "name": "Gwendoline"},
                {"id": "bleu-panique", "name": "Bleu Panique"}],
            "Gwendoline : identité d'artiste non attestée")
    require(all(signed.get(k) == spec[k] for k in
                ("title", "date", "time", "artistIds", "genres", "officialUrl"))
            and signed.get("id") == GWENDOLINE_CORRECTION_ID
            and signed.get("venueId") == "le-rocher-de-palmer-cenon"
            and signed.get("status") == "confirmed"
            and signed.get("sourceType") == "salle"
            and signed.get("organizer") == "Le Rocher de Palmer",
            "Gwendoline : champs approuvés altérés")
    require(existing.get("id") == GWENDOLINE_CORRECTION_ID
            and existing.get("date") == spec["date"]
            and existing.get("time") == spec["time"]
            and existing.get("timeMeaning") == "début du concert"
            and existing.get("venueId") == "le-rocher-de-palmer-cenon"
            and existing.get("genres") == spec["genres"]
            and existing.get("officialUrl") == spec["officialUrl"]
            and existing.get("status") == "confirmed"
            and existing.get("sourceType") == "salle"
            and existing.get("organizer") == "Le Rocher de Palmer",
            "Gwendoline : événement de référence modifié")
    history = existing.get("history")
    require(isinstance(history, list) and history and
            history[0] == {"date": "2026-11-02",
                           "change": "Ajout après revue des preuves officielles"},
            "Gwendoline : origine de la fiche non conservée")
    if existing.get("title") == "Gwendoline":
        require(existing.get("artistIds") == ["gwendoline"]
                and existing.get("lastVerified") == "2026-11-02"
                and len(history) == 1,
                "Gwendoline : état original altéré")
        return True
    require(existing.get("title") == spec["title"]
            and existing.get("artistIds") == spec["artistIds"]
            and existing.get("lastVerified") == GWENDOLINE_CORRECTION_DATE
            and history == [
                {"date": "2026-11-02",
                 "change": "Ajout après revue des preuves officielles"},
                {"date": GWENDOLINE_CORRECTION_DATE,
                 "change": GWENDOLINE_CORRECTION_CHANGE}],
            "Gwendoline : correction déjà publiée non conforme")
    return False


def apply_gwendoline_signed_correction(result, approval):
    """Apply exactly one signed existing-event lineup edit, retaining its ID."""
    positions = [i for i, event in enumerate(result["events"])
                 if event.get("id") == GWENDOLINE_CORRECTION_ID]
    require(len(positions) == 1, "Gwendoline : fiche absente ou dupliquée")
    event = result["events"][positions[0]]
    require(validate_gwendoline_signed_correction(event, approval),
            "Gwendoline : cette correction est déjà appliquée")
    require(not any(a.get("id") == "bleu-panique"
                    or norm(a.get("name", "")) == norm("Bleu Panique")
                    for a in result["artists"]),
            "Gwendoline : Bleu Panique déjà présent sous un autre identifiant")
    require(any(a.get("id") == "gwendoline"
                and a.get("name") == "Gwendoline"
                for a in result["artists"]),
            "Gwendoline : artiste historique introuvable")
    spec = ROCHER_PALMER_VERIFIED[GWENDOLINE_CORRECTION_ID]
    event["title"] = spec["title"]
    event["artistIds"] = list(spec["artistIds"])
    event["lastVerified"] = GWENDOLINE_CORRECTION_DATE
    event["history"].append({
        "date": GWENDOLINE_CORRECTION_DATE,
        "change": GWENDOLINE_CORRECTION_CHANGE})
    result["artists"].append({
        "id": "bleu-panique", "name": "Bleu Panique", "aliases": []})


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
    gwendoline_approval = None
    for existing in current["events"][len(reference["events"]):]:
        approval = approved_ids.get(existing["id"])
        require(bool(approval), "Concert cloud publié sans approbation privée")
        expected = approval["event"]
        if existing["id"] == GWENDOLINE_CORRECTION_ID:
            if existing.get("title") == "Gwendoline" and expected.get("title") != "Gwendoline":
                require(validate_gwendoline_signed_correction(existing, approval),
                        "Gwendoline : nouvelle approbation non applicable")
                gwendoline_approval = approval
                continue
            if existing.get("title") == ROCHER_PALMER_VERIFIED[GWENDOLINE_CORRECTION_ID]["title"]:
                require(not validate_gwendoline_signed_correction(existing, approval),
                        "Gwendoline : approbation incohérente")
        require(all(existing.get(k) == expected.get(k) for k in
                    ("id", "title", "date", "artistIds", "venueId", "genres",
                     "status", "officialUrl", "sourceType")),
                "Concert cloud modifié hors de son approbation : " + existing["id"])
    result = copy.deepcopy(current)
    if gwendoline_approval is not None:
        apply_gwendoline_signed_correction(result, gwendoline_approval)
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
    counts = {"newEvents": 0, "newArtists": int(gwendoline_approval is not None), "newVenues": 0,
              "correctedEvents": corrected_count + int(gwendoline_approval is not None), "correctedVenues": venue_corrected_count,
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
