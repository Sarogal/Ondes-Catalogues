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

## Vérification réutilisable (18 novembre 2026)

Le module `scripts/ptitesondes_independent_ign_venue_recheck.py` est indépendant du collecteur et de la ville : une entrée **déjà documentée dans le registre** est recoupée avec une réponse IGN/BAN fournie séparément, en imposant HTTPS, domaine et chemin exacts, requête épinglée contenant un numéro et un code postal, retour de type `housenumber`, identité exacte (numéro, ville, code postal, libellé), score ≥ 0,95, coordonnées situées à 15 m maximum du point préalablement revu et **un seul résultat concordant**. Une réponse de type `street`, des similitudes de nom ou un centroïde ne sont jamais suffisants.

Il s'agit d'un **recontrôle générique d'un lieu préalablement homologué**, et non d'un géocodeur qui inventerait l'adresse d'une nouvelle salle. Le module ne valide ni séance, ni public, ni âge, ni prix, ni inscription et ne touche pas aux catalogues.

Le `scripts/ptitesondes_ign_geo_live_smoke.py` effectue une lecture HTTPS bornée en taille et délai, sans redirection ni secret, sur les quatre URLs IGN déjà documentées. Il n'affiche que des compteurs. Les tests spécialisés reproduisent les homonymes, duplications, adresses inexactes, coordonnées fausses, URLs usurpées, points de rue et réponses ambiguës. Le workflow en PR conserve ses permissions `contents: read`, sans cron.

### Portée calculée sur le backlog privé du 18 novembre

Les quatre lieux correspondent exactement à **40 pistes futures** de la branche privée d'intake : 29 Studio 24 Villeurbanne, 4 Aretha-Franklin Rouen, 4 Simone de Beauvoir Rouen et 3 La Grand-Plage Roubaix. Toutes possèdent un format `collector` reconnu et un UID de forme valide. Après dédoublonnage strict par couple UID/date, il reste **37 occurrences distinctes** (29 Villeurbanne, 3 Aretha-Franklin, 2 Simone de Beauvoir, 3 Roubaix). **Ce ne sont pas 37 sorties automatiquement approuvées.** Les contrôles ODS UID, véritable source organisatrice, date/heure, public familial et doublons restent nécessaires. Cette statistique n'est pas intégrée aux logs publics du workflow et ne divulgue aucune piste privée supplémentaire.

La prochaine étape consistera, après revue et intégration autorisée du registre, à **mesurer combien des 40 franchissent le nouveau premier filtre puis le prévalidateur complet**, et à sélectionner les prochains lieux selon le volume de pistes réelles et l'existence d'une adresse officielle de bâtiment.

### Diagnostic secondaire d'identité / temporalité (18 novembre)

Le rapprochement des **40 pistes** ne représente pas 40 événements différents : elles se répartissent sur **9 UID OpenAgenda distincts** (1 pour Studio 24, 3 pour Aretha-Franklin, 2 pour Simone de Beauvoir, 3 pour La Grand-Plage). Les 29 pistes du Studio 24 appartiennent **toutes au même UID d'exposition** « Saint-Saëns, le Carnaval Immersif ». La page officielle annonce une exposition familiale du 5 décembre 2026 au 3 janvier 2027, mais ne confirme pas chacune des 29 heures quotidiennes proposées. L'interrogation du miroir ODS pour cet UID renvoie actuellement `total_count=0`. **Aucune publication, déduction d'une séance quotidienne ou dérogation à la vérification de source ne doit en découler.**

Le recontrôle GPS est donc une amélioration du **premier filtre**. Le prochain chantier distinct doit rendre le contrôle source OpenAgenda indépendant du miroir ODS lorsqu'une preuve d'origine officielle suffisante existe, puis distinguer une exposition en plage de dates d'un ensemble de séances effectivement horodatées, sans inventer d'horaires ni confondre municipalité, organisateur et agrégateur. Les 3 autres lieux testés disposent au moins d'un UID représentatif dans le miroir ODS ; cela ne certifie pas les autres preuves.
