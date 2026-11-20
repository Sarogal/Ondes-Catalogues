# P'tites Ondes — contrat de preuve géographique mutualisée (brouillon)

Date : 20 novembre 2026. Dépend de la PR #506 (elle-même dépendante de #503).
**Prévisualisation isolée uniquement ; aucune activation du pipeline de publication.**

## Correction proposée

Une preuve de lieu n'est plus définie par la présence de son nom dans `VENUES`.
Un même lieu physique peut être attesté par une **fiche municipale authentifiée
par DILA**, mentionnant une **identité et une adresse explicites**, recoupées avec
un **unique résultat IGN/BAN au numéro exact** et de score suffisant.

Le nouveau module `scripts/ptitesondes_shared_venue_location_evidence.py` fournit :

- `mint_private_location_proof(group, directory, page_url, html, ign_fetch,
  checked_on, source_center=None)` : création **en mémoire seulement** d'une
  preuve géographique, si les vérifications officielles et indépendantes
  réussissent. `source_center` est facultatif pour un **lieu permanent**
  sans événement ; lorsqu'il est présent, les coordonnées source doivent
  correspondre au point indépendant à 65 mètres maximum.
- `location_from_proof(proof, city, venue, checked_on, source_point=None)` :
  réutilisation limitée à **30 jours**, sur identité ville+lieu exacte et
  éventuellement coordonnées source compatibles. Les preuves sont
  immuables, non inventées à partir de drapeaux JSON.
- Deux portes existantes acceptent **uniquement en option** cette preuve :
  `ptitesondes_candidate_promotion.registry_location(..., evidence, on_day)`
  et `venue_registry.verified_location(..., evidence, on_day)`.
  **Sans paramètres supplémentaires, la production conserve exactement sa
  logique existante.** Un registre statique contradictoire reste prioritaire.

## Chaîne de confiance

Le code suppose que `directory`, `page_url`, `html` et le callback BAN
proviennent de lecteurs **réseau authentifiés séparément** (DILA / page officielle
/ IGN). Ne pas accepter un document DILA ou une réponse BAN provenant du
backlog ou de la déclaration d'un organisateur. Les tests hors réseau injectent
des réponses fictives pour vérifier le contrat ; **ils n'attestent aucun lieu
réel**.

Une preuve géographique ne prouve **jamais** la date, l'heure, l'annulation,
l'organisateur, le public familial, les âges, les droits de reprise ni
l'absence de doublon. Ce module ne vérifie pas les séances et ne sait pas
écrire dans le catalogue. La décision finale doit conserver tous les autres
contrôles de publication.

Le chemin actuel exige un numéro de rue sur la page officielle et dans BAN.
Il **ne couvre pas encore** les parcs, places et emplacements temporaires sans
adresse postale numérotée. Un autre modèle indépendant (emprise de place,
identité et coordonnées officielles) sera requis ; pas d'adresse inventée.

## Ce qui n'est pas encore raccordé

1. Aucun adaptateur de runner privé n'alimente automatiquement ce contrat
   avec les résultats live DILA+site municipal+BAN : le module est
   injectable, pas encore actif.
2. `permitted(lead, today, evidence=preuve)` accepte maintenant une
   preuve explicitement injectée pour **préfiltrer en lecture seule**.
   Ses appels habituels, `evaluate()` et le publisher ne fournissent
   toujours aucune preuve nouvelle par défaut. Les décisions de
   production demeurent inchangées.
3. Une preuve géographique obtenue pour le moteur Lieux n'est pas une
   preuve d'événement ; une preuve d'événement n'autorise pas
   automatiquement un lieu permanent.
4. Aucun registre national persistant, ni cache de preuves renouvelable,
   ni passerelle pour lieux extérieurs n'existe encore dans ce lot.

## Mesures et prochain essai réel

Backlog privé constaté le 20/11 : 449 dossiers, 149 classés `venue_gps_unverified`,
79 lieux, 52 communes. DILA : 35 communes avec site HTTPS potentiellement utile,
couvrant 60 lieux et 116 dossiers. **Ce ne sont pas 116 admissions**.
42 dossiers de 21 lieux recoupent le moteur Lieux, mais aucun de ces 21 lieux
ne possède encore la preuve complète. Les catégories se chevauchent.

Pour mesurer les gains, exécuter le mode `--live-probe --official-municipal-pages
--official-address-geocode` déjà prévu en PR #506 depuis un **contexte privé
authentifié**, sans artifact ni journal contenant des lieux/UID, puis séparer
les preuves complètes, les séances admissibles, les doublons, les droits, et
les publications réellement effectuées.

**Statut ici : zéro lieu nouveau prouvé en production, zéro séance
supplémentaire approuvée, zéro écriture publique.**


## 20/11 — Déverrouillage du point de recherche direct OpenAgenda

Une lacune concrète empêchait la recherche de nouveaux lieux : le préflight
demandait systématiquement `api_record(uid)` (miroir OpenDataSoft), même
lorsque l'entrée était issue directement d'OpenAgenda v2. Ainsi, une panne
ou absence de la fiche ODS bloquait **avant toute recherche officielle**.

La classe `MunicipalOfficialPageReader` expose désormais
`source_record_for_group(group, uid)` :
- pour **OpenAgenda v2**, confirmation de l'agenda par UID/slug auprès de
  l'API directe, puis lecture de l'événement exact, de son état public,
  de son lieu, sa commune et ses coordonnées ;
- pour **ODS**, conservation de la vérification UID + URL canonique + lieu
  via `ods_immutable_source_match` ;
- si plusieurs collecteurs/slugs contradictoires désignent le même UID,
  échec fermé plutôt qu'un choix arbitraire ;
- aucune coordonnée OA ou ODS n'est considérée comme une preuve GPS.

La liaison dans `ptitesondes_generic_venue_osm_preflight.py` ne s'active
que si le lecteur privé est instancié explicitement. Elle ne modifie pas
`permitted()` ni le publisher.

Le mode supplémentaire `--shared-location-evidence`, strictement réservé
à `--live-probe --official-municipal-pages --official-address-geocode`,
effectue une **seconde corroboration IGN/BAN indépendante** et peut produire
en mémoire une `VenueLocationProof`. Il n'ajoute au rapport privé que
`private_reusable_location_proofs` et
`leads_with_private_reusable_proof`.
Les preuves ne sont pas sérialisées et les indicateurs
`verified_venue_leads=0`, `publication_ready=false` et
`public_writes=0` sont inchangés.

Exemple de commande dans un runner disposant déjà de l'accès au checkout
privé, à la clé publique OA de lecture et d'un répertoire de sortie privé :

```bash
python scripts/ptitesondes_generic_venue_osm_preflight.py \
  --backlog /espace-prive/automation-intake/ptitesondes/backlog.json \
  --private-source-config /espace-prive/automation/sources.json \
  --output-private-report /espace-prive/venue-evidence-preview.json \
  --day 2026-11-20 --live-probe --official-municipal-pages \
  --official-address-geocode --shared-location-evidence
```

Ne pas committer le rapport, ses noms de lieux, UID, coordonnées ou URL
sur un dépôt public, ni le déposer en artifact Actions public.
Les logs de CLI contiennent uniquement des compteurs admissibles.

### Statut de preuve

Ce lot teste **le fonctionnement du contrat et l'échec fermé en cas de
contradiction**. Il ne démontre pas encore combien des 149 dossiers privés
atteignent la vérification complète en conditions réseau réelles. Ce
nombre demeure inconnu jusqu'à l'exécution privée autorisée.

### Contrôle de préadmission facultatif (sans publication)

Le préfiltre `ptitesondes_candidate_promotion.permitted()` prend maintenant
un paramètre `evidence=None`. En l'absence de preuve, son comportement est
celui de la branche de référence. Avec une `VenueLocationProof` valide,
seul le verrou d'identité et de géographie du lieu peut être franchi :
la date reste dans sa fenêtre de 184 jours, l'UID et le domaine de source
doivent rester valides. Il ne s'agit **ni d'une séance vérifiée, ni d'un
événement publiable**. Les tests confirment que les preuves fictives,
expirées ou attachées à un autre lieu échouent.


## Complément : réconciliation de deux collecteurs pour un même événement

Le backlog privé du 20/11 contient **31 groupes exacts UID+commune+lieu
présents sur plusieurs collecteurs**, soit **62 entrées de collecte** au
total. Cette statistique est une mesure de répétition, **pas** 62
événements bloqués ou 62 événements prêts à publier.

Pour la **recherche géographique privée**, `source_record_for_group()`
accepte deux sources pour un UID uniquement si elles correspondent
à **un lien OA v2 et un lien ODS au même slug d'agenda**. Il confirme
l'identité dans les données publiques directes et le miroir (UID, URL,
commune, lieu, statut, latitude/longitude à 65 m maximum). Plusieurs
URLs du même type, deux slugs, un état ou une adresse contradictoires
sont toujours refusés. Les pages de lieu examinent au maximum trois
UID **distincts**, et non trois occurrences du même UID dans plusieurs
collecteurs.

Si ODS est temporairement indisponible (exception réseau), la fiche
**OpenAgenda v2 au même UID** peut servir de simple point de départ
uniquement si son agenda UID/slug a été lié indépendamment dans la
configuration privée. Un enregistrement ODS effectivement retourné,
mais incorrect, vide ou contradictoire, ne bénéficie d'aucun
contournement. Cela ne prouve pas un GPS ni un événement.

Les nouveaux compteurs `unknown_candidate_sessions` et
`duplicate_collector_or_repeated_leads` distinguent les entrées
du backlog des **séances UID + date**. Le compteur
`candidate_sessions_with_private_reusable_proof` est un maximum
de séances susceptibles de progresser sur le verrou géographique
dans la prévisualisation. Aucune vérification de séance ou de
publication n'en est déduite.

**Toujours aucune exécution privée live OA + DILA + BAN sur les 149
dossiers**, et aucune écriture de production.


## Campagne complète de prévalidation privée — lots sans doublon

Le lot de recherche précédent ne sélectionnait que 12 lieux, sans
moyen de choisir un second lot pour la même journée. Les exécutions
répétées auraient retravaillé les mêmes lieux.

La nouvelle option `--batch-index` (zéro par défaut) permet une campagne
**déterministe, bornée et sans doublon** pour un jour et un backlog
identiques. `private_rotation()` refuse les indices hors plage. Le nombre
total de lots est publié dans le rapport privé (`batch_count`), avec
`batch_index` et `selected_venues`. Les rapports ne peuvent pas être
utilisés comme justificatifs de publication.

Pour le **snapshot privé du 20/11** (449 entrées), les contrôles de
préadmission identifient **149 entrées sans géographie connue**, soit
**138 séances UID + date distinctes** réparties sur **79 lieux**. Onze
entrées sont répétées ; neuf de ces lieux figurent dans plusieurs
collecteurs. Cela nécessite 7 lots (12 + 12 + 12 + 12 + 12 + 12 + 7)
pour passer une fois sur chaque lieu. Ces valeurs sont des mesures de
préfiltre, non une preuve de séance ni un bilan de vérifications réseau.

Un opérateur disposant des secrets et des chemins privés peut lancer
séquentiellement les sept lots avec **le même jour** et le même
backlog figé, en renseignant `--batch-index 0`, puis `1`, …, `6`
et **un chemin privé distinct pour chaque rapport**. Il ne doit
pas uploader ces rapports comme artefacts publics GitHub Actions.
Le préflight n'inclut aucune planification, écriture de catalogue ou
activation de workflow de production.

Pour exploiter les résultats de façon fiable, distinguer :
- `unknown_venue_leads` : copies brutes par collecteur, pas des séances ;
- `unknown_candidate_sessions` : identités de séance UID + date par lieu ;
- `private_reusable_location_proofs` : lieux pouvant bénéficier d'une
  corroboration géographique privée (uniquement après exécution réseau) ;
- `candidate_sessions_with_private_reusable_proof` : séances distinctes
  dont le lieu a une preuve réutilisable, **sans vérification de leur
  date, public cible, organisateur, droits ou doublons de publication**.

Ne pas additionner plusieurs rapports issus de backlogs différents,
ni prétendre que les 138 séances peuvent toutes être publiées.


## Lieux sans adresse postale numérotée — piste générique privée

Les parcs, places publiques, jardins, esplanades et autres lieux
temporaires n'ont pas toujours de numéro de rue. Le vérificateur
`extract_official_address()` ne doit **pas inventer de numéro** ni
substituer l'adresse de la mairie à celle de la sortie.

Le module `ptitesondes_unnumbered_venue_osm_official_hint.py` fournit
un contrôle **en lecture seule, uniquement pour la recherche** :
1. obtenir un point OA/ODS lié à l'UID et à une commune (indice non fiable) ;
2. identifier un **seul objet OSM au nom exact** à 65 m maximum,
   avec information contradictoire de commune écartée ;
3. obtenir une **page précise** (pas l'accueil générique d'une mairie)
   sur le domaine municipal corroboré indépendamment par DILA ;
4. retrouver le **nom exact du lieu** dans une structure `Place`
   unique ou un H1 visible unique, sans autre lieu structuré contradictoire ;
5. comparer toute coordonnée officiellement déclarée avec l'objet OSM
   sans exiger d'adresse numérotée.

Il n'y a **pas de liste fermée de types de lieux** : un OSM
`leisure=park`, `highway=pedestrian` ou un autre objet nommé peut
fournir une piste. Un OSM sans étiquette de commune reste une piste
avec `city_osm_tag_confirmed=false`, pas une preuve.

Le rapport privé distingue :
- `unnumbered_named_venue_private_hints` : lieux ayant une piste
  à corroborer ;
- `candidate_sessions_with_unnumbered_private_hint` : séances UID+date
  concernées ;
- `private_reusable_location_proofs` : **inchangé**, ces indices ne
  créent aucune preuve réutilisable, et n'ouvrent pas le préfiltre
  `permitted(evidence=...)`.

Les drapeaux `gps_verified`, `official_venue_verified`,
`event_sessions_verified` et `publication_ready` restent tous
à `false`, avec `public_writes=0`.

**Un contrôle indépendant de géographie est encore nécessaire**
avant qu'un tel lieu puisse être approuvé. Les horaires, âges, droits,
organisateurs, dates et doublons de chaque séance restent distincts.
