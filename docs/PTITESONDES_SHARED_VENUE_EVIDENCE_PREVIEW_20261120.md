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
2. Ni `permitted()` ni `evaluate()` ni le publisher ne reçoivent cette
   preuve par défaut. Les admissions et publications demeurent inchangées.
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
