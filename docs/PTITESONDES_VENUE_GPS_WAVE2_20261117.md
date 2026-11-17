# P'tites Ondes — second lot de points GPS indépendants (17/11/2026)

**DRAFT, code de préparation uniquement : aucun événement, lieu public, patch ou publisher modifié.**

## Objet

Réduire les refus `venue_gps_unverified` de la chaîne historique OpenAgenda sans transformer un point de bâtiment en preuve d'activité familiale. Ce lot ajoute **quatre points nominatifs** au registre de lieux privés/publics strictement géographique de `scripts/venue_registry.py`. La décision de publier une séance reste distincte.

## Concordance des sources

| Lieu | Autorité d'identité / adresse | Fournisseur géographique indépendant | Point WGS84 (lat, lon) |
|---|---|---|---|
| Studio 24 — Villeurbanne | [Annuaire municipal](https://www.villeurbanne.fr/annuaire/culture-loisirs/cinema-et-theatres/le-studio-24) : 24 rue Émile-Decorps | [IGN / BAN, numéro 24, score 0,9765](https://data.geopf.fr/geocodage/search?q=24%20rue%20Emile%20Decorps%2069100%20Villeurbanne&limit=2) | 45.757956, 4.899764 |
| Bibliothèque Aretha-Franklin — Rouen | [Municipalité de Rouen](https://rouen.fr/fr/agenda/82031901_inauguration-aretha-franklin) : 65 avenue de Bretagne ; ancien nom Saint-Sever | [IGN / BAN, numéro 65, score 0,9747](https://data.geopf.fr/geocodage/search?q=65%20avenue%20de%20Bretagne%2076100%20Rouen&limit=2) | 49.431261, 1.082660 |
| Bibliothèque Simone de Beauvoir — Rouen | [Agenda municipal du lieu](https://rouen.fr/fr/agenda/76031960_je-suis-venue-vous-lire-simone-de-beauvoir) : 42 rue Henri-II-de-Plantagenêt | [IGN / BAN, numéro 42, score 0,9742](https://data.geopf.fr/geocodage/search?q=42%20rue%20Henri%20II%20Plantagenet%2076100%20Rouen&limit=2) | 49.426213, 1.096972 |
| Médiathèque de Roubaix — La Grand-Plage | [Ville de Roubaix](https://www.ville-roubaix.fr/services-infos-pratiques/culture-et-patrimoine/livre-et-lecture/) : 2 rue Pierre-Motte | [IGN / BAN, numéro 2, score 0,9720](https://data.geopf.fr/geocodage/search?q=2%20rue%20Pierre%20Motte%2059100%20Roubaix&limit=2) | 50.690508, 3.175283 |

Vérification faite par lecture des fiches institutionnelles et réponses de géocodage le 17 novembre 2026. La position d'un numéro de voirie n'est pas toujours exactement l'entrée du bâtiment : le prévalidateur existant conserve **65 mètres de tolérance** et doit confronter ces points à ceux de l'index de l'événement, sans déduction d'identité.

## Cas bloqués volontairement

- **L'Atelier Media de Carvin**, place de la Gare : la requête BAN retrouvée renvoie un point de rue (`type: street`), pas un numéro de bâtiment vérifié. Aucune nouvelle coordonnée n'est ajoutée, malgré des événements de médiathèque.
- **Basse-Pointe** : `city=Basse-Pointe, venue=Basse-Pointe` ne suffit pas à identifier un bâtiment. Aucun point de centre-ville ou de mairie n'est accepté.
- Le nom historique **Bibliothèque Saint-Sever** n'est pas ajouté comme alias automatique d'Aretha-Franklin : sa correspondance avec les événements passés mérite une décision indépendante.
- Les noms géographiques voisins et annexes ne sont pas des alias du lieu certifié.

## Contrôles intacts

- Identité du lieu = ville exacte ET nom/alias explicitement validé, une seule correspondance.
- Le point officiel de l'événement doit être à **65 m maximum** du bâtiment revu.
- Impossible de créer une activité avec la seule existence d'un bâtiment : dates, heures, prix, statut, âge, public familial et source officielle sont toujours contrôlés par la chaîne existante.
- Aucune autre catégorie n'est réorientée. Les prévalidations nationales non musicales restent séparées d'OpenAgenda musical.
- Aucune modification `docs/ptitesondes/sorties.json`, `lieux.json`, runners privés, catalogues Grosses Ondes, OpenAgenda, Infomaniak, de GitHub Pages ou de leurs crons.
- Workflow CI de cette branche : runner GitHub Actions public, secrets absents, `contents: read`, tests hors réseau uniquement, aucune approbation ni publication.

## Suite avant fusion

1. Examiner les quatre paires de preuves et confirmer les coordonnées auprès de l'IGN/OSM si nécessaire.
2. Comparer au moins un événement original de chaque lieu à son point géographique, puis vérifier les éventuelles divergences supérieures à 65 m.
3. Contrôler les suites spécialisées et les régressions du moteur complet.
4. Attendre l'autorisation explicite pour toute fusion. Même après fusion, aucun événement ne contourne le contrôle organisateur/public/âge.

**Ce lot ne prouve aucune nouvelle activité et n'autorise aucune publication.**
