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

Une carte de prévisualisation combinant les sorties datées et les lieux est
servie à l'adresse :

https://sarogal.github.io/Ondes-Catalogues/ptitesondes/carte-lieux.html

Les lieux y possèdent des marqueurs verts distincts des sorties.
Cette carte est une **prévisualisation**, et non la page officielle
`ptitesondes.fr/sorties.html` hébergée sur Infomaniak.

Le fichier est livré via GitHub Pages dans
`https://sarogal.github.io/Ondes-Catalogues/ptitesondes/lieux.json`.
Le workflow existant `ptitesondes-cloud-sync.yml` peut publier le fichier
`lieux.json` et la prévisualisation de carte lorsqu'ils changent, même si
`sorties.json` n'a aucune nouvelle fiche. Il **n'essaie pas de faire un
commit de sorties** quand seul un lieu change.
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


## Veille des programmations officielles (pilote, novembre 2026)

Les lieux permanents et leurs rendez-vous datés restent **deux objets distincts**.
Le moteur public `scripts/ptitesondes_place_agenda_watch.py` suit des URLs
officielles exactes décrites dans
`scripts/ptitesondes_place_agenda_sources.json`, sans parcourir librement
les liens, sans suivre de redirection et sans publier de données.

La surveillance est branchée dans le cycle **Lieux** du pont existant
`.github/workflows/ptitesondes-private-intake-on-public-runners.yml`,
à **21:37 UTC** (22:37 en hiver, 23:37 en été en France), sous réserve
que GitHub exécute effectivement le cron. Elle ne crée aucun déclencheur
ni runner privé supplémentaire.

Le pilote recense sept pages officielles liées à quatre lieux :
- mille formes Montpellier : programme de la Ville et agenda de saison ;
- médiathèque Pourquoi pas ? à Toulouse : page institutionnelle et
  programmation officielle des « Bébés explorateurs » ;
- Totems à Pacé : page municipale et véritable agenda de la ville ;
- ludothèque Bellevue à Nantes : page de l'organisme public familial.

Les pages institutionnelles des trois dernières villes sont des
**pages de lieu**, pas des agendas événementiels directs : leur surveillance détecte des modifications mais
ne justifie aucune séance. Les pages marseillaises connues renvoient
actuellement un squelette demandant JavaScript au lecteur automatisé :
il faut trouver une programmation officielle directement accessible
avant de pouvoir en surveiller les événements.

La sortie du moteur va **exclusivement** dans la branche privée
`Sarogal/PtitesOndes:automation/ptitesondes-intake` :
- `automation-intake/ptitesondes/lieux-agenda-watch.json` :
  empreintes des contenus lisibles ;
- `automation-intake/ptitesondes/lieux-agenda-candidates.json` :
  changements et pistes de séances à requalifier.

Même si une page annonce un atelier, une séance n'est admise comme
*piste* que lorsqu'un objet JSON-LD Event indique clairement un horaire,
une date, le lieu exact et une URL officielle. Les dates d'ouverture,
plages de saisons, horaires récurrents, pages sans preuve et indices
douteux ne génèrent **jamais** d'événements. La vérification indépendante
d'une séance, des âges, de son lieu et d'éventuelles annulations reste
obligatoire avant toute future publication dans `sorties.json`.

**État fonctionnel :** surveillance et signalement des changements ;
l'injection automatisée des pistes d'agenda dans la prévalidation
indépendante des événements reste une étape ultérieure. Ne pas présenter
ce pilote comme une publication automatique déjà opérationnelle.


## Extraction de séances institutionnelles (pilote complémentaire)

Le module `scripts/ptitesondes_place_agenda_curated.py` prépare, dans la
même veille des lieux, des **pistes de séances datées** lorsque les programmes
officiels contiennent une preuve suffisamment explicite. Il prend en charge
pour l'instant :
- le programme détaillé du centre mille formes de Montpellier, par sections
  datées et public enfant clairement annoncé ;
- une fiche de la médiathèque jeunesse du Muséum de Toulouse sur les
  « Bébés explorateurs : formes et matières », avec les dates individuelles
  et heures corroborées par le calendrier de la fiche.

Les séances sont toujours de simples objets
`requires_independent_session_proof` conservés en privé ; les fiches
publiques `sorties.json` restent inchangées. Une activité adulte, des
heures d'ouverture, un calendrier général, un intitulé sans horaire, une
séance annulée, une date dépassée ou un événement dans un autre lieu sont
écartés. La saison complète de mille formes est surveillée comme
information générale mais non interprétée comme des événements quotidiens.

Ces deux adaptateurs sont des **pilotes bornés** : ils ne remplacent pas
l'analyse indépendante de l'index OpenAgenda et de la page officielle,
ni la recherche de prochains programmes sur de nouvelles URLs. Les
événements de Totems nécessitent encore la lecture et le contrôle de leurs
fiches détaillées avant d'être traités comme des séances pour enfants.


## Totems (Pacé) : depuis l'agenda général jusqu'à la fiche détaillée

Le collecteur `scripts/ptitesondes_place_agenda_pace.py` est appelé par
le cycle Lieux existant pour la source municipale approuvée
`https://www.ville-pace.bzh/mes-loisirs/agenda/` :
1. repérer uniquement des titres indicateurs d'activités pour enfants ;
2. restreindre strictement chaque URL candidate à une fiche
   `https://www.ville-pace.bzh/evenement/…/`, sans query, fragment,
   sous-domaine externe, redirection, port spécial, etc. ;
3. consulter un **maximum de six** fiches par passage, par rotation
   déterministe pour couvrir davantage de fiches au fil des jours ;
4. n'ajouter une piste que si la fiche individuelle indique le lieu Totems
   et son adresse exacte, une année/jour/mois cohérents, des horaires
   explicites et une tranche d'âge pour enfants, en excluant les fiches
   périmées, annulées, reportées, complètes ou destinées aux adultes.

Une même URL peut être réutilisée par l'organisateur pour plusieurs
éditions : les dates de l'index ne prouvent **jamais** les dates des
séances. Les fiches extraites sont des candidats privés non publiables,
et sont toujours soumises à la prévalidation indépendante avant
toute modification de la carte. Aucun nouveau déclencheur GitHub Actions
n'est ajouté.
