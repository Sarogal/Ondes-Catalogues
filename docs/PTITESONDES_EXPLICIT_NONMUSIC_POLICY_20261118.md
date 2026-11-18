# P'tites Ondes — Contrat explicite des catégories familiales non musicales

18 novembre 2026 — Proposition isolée et non activée.

## Constat
Le catalogue public `docs/ptitesondes/sorties.json` compte actuellement 549 fiches
réparties entre **sept catégories historiques musicales seulement**. La fonction
`ptitesondes_candidate_promotion.category_for()` ne classe que les sorties musicales.
De plus, `merge_policy.valid()` interdit toute catégorie absente du catalogue historique.

La proposition nationale `ptitesondes_family_national_scope.FAMILY_TYPES` dispose déjà de
**13 catégories familiales** couvrant lectures, ateliers, nature, musées, patrimoine,
cinéma, spectacles, jeux, sport et famille, mais leur validation reste expérimentale.

## Modification strictement isolée
`merge_policy.valid(..., reviewed_family_categories=None)` reçoit un argument
**facultatif de politique explicite**. Aucune catégorie nouvelle n'est acceptée par
défaut. Un appelant revu séparément peut fournir un tuple/frozenset de codes issus
exclusivement des 13 catégories déjà déclarées. Leur libellé doit correspondre
exactement au contrat, et tous les contrôles structurels précédents restent actifs.

L'appel productif `merge()` n'est **pas modifié** et n'envoie aucun
`reviewed_family_categories` : par conséquent aucune nouvelle catégorie
n'est autorisée par le publisher actuel, même si cette PR était fusionnée.

Cette fonction est un **contrat de structure**, pas la preuve que le contenu
officiel est bien du type déclaré. Les règles d'âge, de public, d'horaire, de
sources officielles, d'accès, de GPS, d'historique et de droits de réutilisation
doivent être satisfaites par des preuves indépendantes avant toute activation.

## Étapes indispensables avant bascule
1. Preuve officielle indépendante et classification de l'activité depuis
   l'organisateur (et non une catégorie choisie par la piste collectée).
2. Groupe UID/date et contrôle du public famille, vérification exacte des séances.
3. Validation GPS et droits de réutilisation.
4. Contrôle de déduplication historique pour la catégorie nouvelle.
5. Revue explicite du schéma et des facettes d'affichage sur la carte.
6. PR distincte et autorisation de l'activation dans le publisher,
   avec préproduction et surveillance d'une première sortie réellement publiée.

**Aucune fusion ni modification de production n'est autorisée par cette PR.**
