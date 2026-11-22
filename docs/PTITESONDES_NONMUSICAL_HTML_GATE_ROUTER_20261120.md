# P'tites Ondes — Routeur générique d'admission HTML non musicale, lecture seule

**20 novembre 2026 — chantier isolé.** Aucune fusion, aucun changement de production, aucun transfert vers le backlog ni le publisher.

## Ce qui est vérifié

Le routage `scripts/ptitesondes_nonmusical_html_gate_router.py` rassemble les **contrôles déjà présents** et produit une action privée précise pour les sorties familiales non musicales :

- Séance exacte sur une fiche institutionnelle `HTTPS` reliée à l'index officiel déjà épinglé ;
- catégorie parmi `FAMILY_TYPES` (les catégories musicales gardent leur pipeline) ;
- mention explicite du public enfants/famille/mixte, sans inventer de tranche d'âge ;
- conditions tarifaires et d'inscription visibles, inconnues autorisées comme *non précisées*, contradictions bloquées ;
- brouillon factuel original en mémoire, jamais affiché dans le journal public ;
- rapprochement avec un registre de lieux **indépendant du collecteur** et un instantané historique **de trois jours au maximum** ;
- détection des doublons exacts et des collisions ambiguës (même titre/lieu/date mais horaires distincts).

Le routeur renvoie uniquement un **code de blocage stable** et une action correspondante : retrouver la fiche exacte, préciser le public, éclaircir les tarifs, documenter le lieu, actualiser l'historique, examiner les séries, ou avancer vers les contrôles indépendants GPS/droits.

Même si tous les éléments de source, d'audience, d'accès et d'historique sont cohérents, le résultat est `independent_geo_rights_review_required`, **jamais** une autorisation.

## Ce qui reste obligatoirement à contrôler

1. propriété institutionnelle et organisateur actuel indépendamment établis ;
2. adresse/GPS indépendamment revérifiés auprès du lieu et IGN/BAN ;
3. politique de réutilisation des faits et de la base de données **pour chaque source**, pas chaque événement ;
4. absence de collision dans le **catalogue public actuel** (un ancien instantané n'est pas la preuve de non-duplication en direct) ;
5. schéma éditorial des catégories non musicales et vérificateur indépendant du publisher.

Ces barrières ne peuvent pas être franchies par un champ `verified`, une URL du candidat, une métadonnée de licence auto-déclarée ou une preuve agrégée.

## Limitation importante du catalogue existant

Sur la branche `main` consultée le 19 novembre, le fichier `docs/ptitesondes/sorties.json` contient 549 fiches et 7 catégories uniquement musicales. Le `merge_policy.valid()` existant calcule les catégories admises à partir du catalogue de référence. Les nouvelles catégories non musicales échouent donc. De plus `ptitesondes_candidate_promotion.permitted()` exige un UID OpenAgenda et `openagenda.com`.

La future architecture devra ajouter une **voie non musicale séparée** (source institutionnelle épinglée, revue GPS/droits et schéma explicite), pas supprimer l'exigence de confiance du circuit musical. Aucun `patch.v1` n'est créé dans cette PR.

## Sécurité des rapports

Le diagnostic HTML `scripts/ptitesondes_html_index_detail_funnel.py` ajoute seulement des compteurs `router_<code>`, à partir d'une liste fixe définie dans le code, sans événement, titre, commune, coordonnées ni URL. Un filtre refuse les champs arbitraires ou les faux indicateurs de réussite. Les compteurs n'ajoutent aucune preuve nouvelle et ne sont pas une file d'attente.

## Tests de non-régression

Tests synthétiques hors réseau : famille/mixte, adulte seul, inscriptions contradictoires, tranche d'âge absente, mauvaise séance et redirection, domaine usurpé, doublons horaires, registre absent ou ambigu, GPS non attesté, historique périmé, tentatives d'injection `rights_reviewed=true`, fuite de données dans un rapport et conservation des circuits musicaux.

Le pilote officiel MPT reste borné à 30 pages, en lecture seule. Aucun événement découvert n'est publié. Les compteurs réels constituent un indicateur d'amélioration de la prévalidation, pas un chiffre d'événements admis.

## Feuille de route

Le prochain lot isolé devra concevoir la **politique de sources institutionnelles et de droits** (revue une fois par source vérifiée, révocable) et le **contrat de schéma non musical**. Ensuite seulement, brancher un validateur indépendant sur une simulation de publisher, sans mutation de production. Une activation de production nécessitera une validation complète des tests et de l'historique.

**Interdictions :** aucun merge, aucun push sur main, aucune modification du backlog privé, de GitHub Pages, d'Infomaniak ni de la carte en ligne.
