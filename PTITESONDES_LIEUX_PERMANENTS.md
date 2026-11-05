# Lieux permanents pour enfants — P'tites Ondes

## Pourquoi un catalogue distinct ?

Les sorties dans `docs/ptitesondes/sorties.json` sont des événements datés, dont
les représentations doivent être démontrées individuellement. Un musée,
une ludothèque ou un centre d'éveil artistique ouvert toute l'année est un
**lieu permanent**, et non une représentation quotidienne.

Le fichier public `docs/ptitesondes/lieux.json` contient uniquement des
lieux explicitement revus, accessibles aux familles, avec une page officielle
et un emplacement géographique corroboré par une source indépendante.

La version 1 démarre avec **mille formes Montpellier**, un centre gratuit
pour les 0-6 ans situé au 1 place Paul Bec. Sources :

- Ville : https://www.montpellier.fr/vie-quotidienne/vivre-ici/se-cultiver/jeune-public/mille-formes-centre-dart-pour-les-0-6-ans
- Coordonnées indépendantes OpenStreetMap via Mapcarta : https://mapcarta.com/fr/N13508792408
- Programmation : https://agenda.montpellier.fr/event/110467/mille-formes-saison-2-montpellier

Aucune plage de saison, heure d'ouverture ni séance non explicitement
confirmée n'est transformée en dates d'événement. Les changements
exceptionnels d'horaires et les réservations sont consultables sur le
site officiel ; leurs valeurs ne sont pas figées dans le JSON.

## Règles de publication

`python scripts/ptitesondes_places.py docs/ptitesondes/lieux.json`

L'ajout exige une revue explicite du nom, de l'adresse, de l'âge,
de l'accessibilité familiale et de la localisation GPS indépendante.
Les anciennes fiches sont conservées intactes (append-only) : les
corrections, fermetures ou déménagements demandent une procédure séparée.

Le fichier est livré via GitHub Pages dans
`https://sarogal.github.io/Ondes-Catalogues/ptitesondes/lieux.json`.
Le workflow existant `ptitesondes-cloud-sync.yml` peut publier ce fichier
lorsqu'il change, même si `sorties.json` n'a aucune nouvelle fiche.
Le moteur ne dispose d'aucun droit de publication de lieux issus
directement du backlog privé.

## Affichage sur le site ptitesondes.fr

Le dépôt GitHub de l'application contient le collecteur et la source JSON,
mais **pas le code actif de la carte Infomaniak**.
L'intégration visuelle nécessite de modifier cette carte pour charger
`lieux.json` en parallèle de `sorties.json`, avec une couche
« Lieux pour enfants » et des marqueurs distincts. Elle ne doit
pas se faire en falsifiant des événements dans `sorties.json`.
Tant que le code actif de la carte n'a pas été intégré, la fiche est
disponible sur GitHub Pages mais pas encore visible sur la carte du site.
