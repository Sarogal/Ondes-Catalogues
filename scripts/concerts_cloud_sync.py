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

# Pilot venues explicitly reviewed (first-party address + named OSM node).
# Any future venue requires its own signed source review AND a code review.
PILOT_VENUES = {
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
    }
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


def corrected_reference_venues(reference, secret_place=False):
    """Only the exact, source-reviewed geographic corrections are permitted."""
    venues = copy.deepcopy(reference["venues"])
    fixes = [(FERRAILLEUR_VENUE_ID, FERRAILLEUR_LOCATION_FIX)]
    if secret_place:
        fixes.append((SECRET_PLACE_VENUE_ID, SECRET_PLACE_LOCATION_FIX))
    for venue_id, patch in fixes:
        rows = [v for v in venues if v["id"] == venue_id]
        require(len(rows) == 1, "Salle historique absente : " + venue_id)
        rows[0].update(copy.deepcopy(patch))
    return venues


def validate_secret_place_location_correction(approvals, reference, today):
    """Require a signed, persistent, double-source correction for an existing venue."""
    corrections = approvals.get("referenceVenueCorrections", [])
    require(isinstance(corrections, list) and len(corrections) <= 1,
            "Corrections géographiques historiques non conformes")
    if not corrections:
        return None
    row = corrections[0]
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
            require(now[:len(initial)] in (initial, legacy_corrected_events(reference)),
                    "Concert historique modifié hors exception de programmation approuvée")
        elif kind == "venues":
            # Allow only the two exact, documented geographic correction states.
            # The original 53 venues are never rewritten in the baseline JSON.
            allowed = (initial, corrected_reference_venues(reference),
                       corrected_reference_venues(reference, secret_place=True))
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


# Six exact bills confirmed from first-party individual Rocher de Palmer pages on 2026-11-02.
# These are reviewed cases, not an open-ended permission for the venue.
ROCHER_PALMER_VERIFIED = {
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
    if event.get("venueId") == "secret-place-saint-jean-de-vedas":
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
    elif event.get("venueId") == "la-cave-aux-poetes-roubaix":
        spec=CAVE_POETES_VERIFIED.get(event_id)
        require(spec is not None
                and reviewer=="independent-official-verifier"
                and event.get("sourceType")=="salle"
                and all(event.get(k)==spec[k] for k in
                        ("title","date","time","artistIds","genres"))
                and official_url==spec["officialUrl"],
                "Cave aux Poètes : seule l'affiche punk du 8 novembre est agréée")
        u=urlsplit(official_url)
        require(u.scheme=="https" and u.hostname=="caveauxpoetes.com"
                and u.path=="/evenement/babe-haven-latter-muddle/"
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
            and p.get("proofType")=="organizer-submitted-calendar"
            and p.get("checkedAt")==checked.isoformat()
            and {"artists","date","venue","startTime"}.issubset(
                set(p.get("checkedFields") or []))
            for p in evidence),
                "Cave aux Poètes : fiche officielle et agenda soumis par salle requis")
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
    return event, added


def merge(reference, current, approvals, today):
    protect_reference(reference, current)
    require(approvals.get("schema") == SCHEMA and
            isinstance(approvals.get("approvals"), list),
            "Approbations privées non conformes")
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
    location_review = validate_secret_place_location_correction(approvals, reference, today)
    current_venues = current["venues"][:len(reference["venues"])]
    corrected_venues = corrected_reference_venues(reference, secret_place=True)
    venue_corrected_count = 0
    if current_venues == corrected_venues:
        require(location_review is not None,
                "Secret Place géolocalisée sans revue privée persistante")
    elif location_review is not None:
        require(current_venues == corrected_reference_venues(reference),
                "Référence des salles inattendue avant correction Secret Place")
        result["venues"][:len(reference["venues"])] = corrected_venues
        venue_corrected_count = 1
    correction = validate_legacy_correction(approvals, reference, today)
    current_prefix = current["events"][:len(reference["events"])]
    if current_prefix != reference["events"]:
        require(correction is not None
                and current_prefix == legacy_corrected_events(reference),
                "Concert historique modifié sans validation privée persistante")
    corrected_count = 0
    if correction and current_prefix == reference["events"]:
        result["events"][:len(reference["events"])] = legacy_corrected_events(reference)
        corrected_count = 1
    ids = {x["id"] for x in result["events"]}
    venues = {x["id"]: x for x in result["venues"]}
    artists = {x["id"]: x for x in result["artists"]}
    venue_approvals = approvals.get("venueApprovals", [])
    require(isinstance(venue_approvals, list) and len(venue_approvals) <= 25,
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
    require(len(approvals["approvals"]) <= 100, "Trop d’approbations en un seul lot")
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
    require(len(approvals["approvals"]) <= 100, "Trop d'approbations par lot")
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
