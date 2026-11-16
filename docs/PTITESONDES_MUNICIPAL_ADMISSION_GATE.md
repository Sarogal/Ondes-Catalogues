# P'tites Ondes — Admission municipale isolée (16 novembre 2026)

**Statut : DRAFT, diagnostic uniquement. AUCUNE publication activée.**

## Situation, dépendances et bornes

Cette branche dérive de la PR publique **#330** (elle-même empilée sur **#328 → #325 → #323**). La PR frontend **#327** (v173), le registre de lieux vérifiés **#305** et les collectes ultramarines **#310/#322** restent séparés et non fusionnés. Conserver toutes les autres PR ouvertes.

Le synchroniseur de production `scripts/merge_policy.py`, `scripts/proof_text.py`, le promoteur OpenAgenda et les catalogues JSON ne sont **pas modifiés**. La fonction `merge_policy.merge` demeure incompatible avec les quatre catégories non musicales, volontairement. Aucune source municipale n'est maquillée en source OpenAgenda.

## Contrat explicite, sans ensemencer l'historique

`scripts/ptitesondes_municipal_admission.py` utilise `explicit_municipal_category_valid` : quatre identifiants **exactement** (`lecture-jeunesse`, `atelier-numerique`, `lecture-cinema`, `jeux-famille`), libellé strict, série/titre vérifiés et schéma `valid(...)` déjà utilisé. Cette validation n'est **jamais branchée dans `merge_policy.merge`**. Elle refuse toute apparition de ces identifiants dans une référence historique trafiquée.

Pour chaque occurrence du Gosier, `inspect_municipal_admission` :

1. Vérifie le catalogue v3, sa copie exacte et l'unicité des identifiants.
2. Rejoue le prévalidateur #325 sur le calendrier et la fiche municipale HTTPS officielle, jour/année, heures, âge, lieu, annulation, disponibilité et accès.
3. Refuse les nouveaux bloqueurs de preuve : seuls les bloqueurs explicitement listés par les contrôleurs de préparation peuvent être interprétés comme des étapes futures, jamais comme une preuve d'admission.
4. Vérifie que les catégories, âges et champs de publication hypothétiques sont strictement compatibles avec le schéma (sans patch).
5. Recherche les collisions d'ID, source URL, date et similarité exacte titre/ville/lieu sur les fiches déjà publiées, y compris les autres origines.
6. Vérifie le GPS auprès du registre de lieux indépendamment homologués (non auprès des coordonnées d'un collecteur).
7. Relit un accord **humain GitHub privé** sur l'occurrence exacte, lié à la PR ouverte, à son SHA, à la fiche source HTML, au dossier, aux conditions d'accès et à l'empreinte du catalogue. Révocation et preuve modifiée arrêtent le processus.
8. Refuse de considérer un prix ou des modalités d'inscription non précisés comme un accès gratuit/sans inscription. Les dossiers dont ces données sont inconnues restent en revue éditoriale séparée.
9. Confirme en sortie que le catalogue historique n'a pas été modifié.

La sortie est exclusivement un **diagnostic sans patch, sans `additions`, sans `events` et sans écriture**. `technical_admission_diagnostic_passed` n'est pas `publication_ready` : cette dernière valeur est toujours `false`.

Les tests passent des fonctions réseau simulées pour tenter des modifications et prouver le fail-closed. Aucun token ni dossier privé réel ne doit entrer dans les runners publics.

## Blocages réels prévus

- **Neuf séances du Gosier** : fiche et calendrier municipaux vérifiés lors des exécutions précédentes ; **prix et inscription non indiqués**, donc `editorial_unknown_conditions_pending`. Aucune approbation privée réelle par occurrence enregistrée à la date de départ. Ne pas présenter ces séances comme publiables.
- **GPS** : la position proposée est dans les dossiers #305 ; tant que le registre de lieu homologué n'est pas disponible dans le circuit de contrôle, ce garde-fou reste bloquant.
- **Interface** : la v173 reste en prévisualisation #327, pas déployée. Les tests de filtres/cartes doivent être validés avant activation.
- **Publication** : synchroniseur public inchangé, aucun traducteur municipal → patch.v1 raccordé ; aucune date mise en production.
- **La Réunion / CINOR** : événement daté du 18/11 (UID OpenAgenda) soumis à un **circuit distinct** ; il ne doit pas entrer dans le présent contrôleur municipal.

## Tests adversariaux

`python -m unittest discover -s tests -p 'test_ptitesondes_municipal_admission.py' -v`

Les tests sont **hors ligne** : approbation authentique simulée, accord absent/révoqué, empreinte HTML modifiée, accès inconnu, droits insuffisants, séance/dates/horaires contradictoires, annulation/complet, coordonnées rejetées, doublon inter-source, catégorie falsifiée, indisponibilité source, impossibilité de modifier le catalogue et absence de patch.

## Protocole d'activation future (sur accord explicite, jamais automatiquement)

1. Contrôler et fusionner séparément les dépendances et la carte v173 après validation.
2. Homologuer la fiche géographique, la preuve de GPS et sa fraîcheur.
3. Produire **une PR privée par décision** ou dossier signé, avec approbation humaine/revocation et preuve d'accès éditoriale exacte, sans transformer un inconnu en information affirmative.
4. Concevoir et auditer un connecteur municipal indépendant avec vérification supplémentaire côté synchroniseur public. Autoriser les quatre catégories explicitement seulement pour les dossiers municipaux authentifiés, sans ouvrir l'allowlist globale aux collecteurs.
5. Vérifier la publication **append-only**, l'absence de doublons inter-sources, le catalogue exact, les fuseaux et les données d'origine ; lancer la suite complète et valider visuellement tous les territoires.
6. Demander un **accord explicite distinct** pour chaque fusion, première insertion publique et déploiement Infomaniak.

## Retour arrière

Ne rien fusionner pour annuler ce prototype : fermer sa PR ou supprimer sa branche. Le catalogue v3, les cinq horaires de collecte publique et Infomaniak restent identiques. Si une future activation est refusée, débrancher exclusivement le connecteur municipal et revenir au synchroniseur OpenAgenda validé, sans réécrire l'historique. Toute correction déjà publiée devra faire l'objet d'une procédure distincte (jamais une suppression automatique).
