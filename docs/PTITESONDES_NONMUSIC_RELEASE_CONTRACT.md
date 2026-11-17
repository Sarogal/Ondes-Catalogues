# P’tites Ondes — Contrat de publication des sorties jeunesse non musicales (préparation)

**Date : 16 novembre 2026. Statut : PROPOSITION, non active.**

## 1. Problème réellement constaté

Le catalogue public actuel est en schéma `version: 3`, avec sept catégories exclusivement musicales ou festival. Le code `scripts/merge_policy.py` restreint les catégories à celles observées dans la **référence historique** ; `scripts/ptitesondes_candidate_promotion.py` et `automation/merge_verified.py` (dépôt privé) sont conçus pour les événements OpenAgenda. Les URL officielles du Gosier ne peuvent pas être « maquillées » en OpenAgenda. La carte v172 est déployée hors du dépôt public, ses contrôles de catégories doivent faire l'objet d'un audit et d'une validation spécifiques. Aucun changement du site n'est inclus ici.

## 2. Taxonomie proposée

| ID candidat | Libellé proposé | Séances vérifiées (16/11) |
|---|---|---:|
| `lecture-jeunesse` | Lecture jeunesse | 4 |
| `atelier-numerique` | Atelier numérique | 2 |
| `jeux-famille` | Jeux en famille | 2 |
| `lecture-cinema` | Lecture et cinéma | 1 |

**Ne pas** convertir artificiellement ces sorties en `conte-musical`, `atelier-musical` ou `ciné-concert`. Le filtre existant « Lecture & histoire », vu dans l'interface, ne prouve pas à lui seul que ces quatre IDs sont gérés. L'ajout de catégories devra utiliser une table de référence explicite indépendante des catégories de la référence historique, et un rendu testé dans la carte v172 ou sa future version approuvée.

## 3. Chaîne de preuve obligatoire

1. **Découverte** : une occurrence datée par calendrier officiel (identifiant municipal SPIP, titre, jour, année, heures, même carte HTML, origine HTTPS fixe et réponse bornée). Pas de récurrence inférée.
2. **Qualification** : fiche événement de la mairie avec identité strictement concordante (même titre, date locale, heures, lieu, destinataire enfant explicite), statut programmé ; refaire cette vérification avant toute approbation.
3. **Géographie** : bâtiment exact Médiathèque Raoul Georges Nicolo, identité par BnF CCFr, position OSM (PR publique #305) ; ne jamais géocoder le centre-ville, une annexe, ni réutiliser les coordonnées d'un autre lieu.
4. **Conditions d'accès** : détecter annulations, reports, complet/scolaire ; tarif explicite ou **absent**, inscription obligatoire/explicitement sans inscription ou **non précisée**. Un silence ne signifie jamais « gratuit » ni « accès sans inscription ». Une mention de prix inconnue peut être masquée au profit de « Voir conditions », sous réserve d'une validation éditoriale ; ne pas inventer de champ.
5. **Doublons** : identité stable `municipal-gosier-{spip_event_id}-{YYYY-MM-DD}`, URL/date et titre/lieu/date, inclus les regroupements déjà publiés. Aucun UID OpenAgenda inventé.
6. **Admission privée** : un responsable identifié valide ou refuse séparément le dossier **après** la vérification du prix et des modalités de participation ; les rapports de collecte et d'accès ne suffisent jamais et ne peuvent s'autovalider.
7. **Prévalidation publique** : contrat dédié municipal distinct de l'admission OA, vérifie de nouveau la fiche officielle, l'identité, les conditions et le GPS ; format patch de publication conforme à `ptitesondes.patch.v1` seulement après cet examen, jamais généré par les scripts de découverte.
8. **Synchronisation** : `merge_policy.valid` et `proof_text.verify_event` devront accepter les nouvelles catégories et l'origine municipale avec une preuve d'événement explicite, **sans** assouplir l'historique append-only ni autoriser des corrections automatiques ; aucun nouveau cron privé.
9. **Interface** : filtres, libellés, marqueurs, fenêtres d'information, recherche, horaires `America/Guadeloupe` et le sélecteur géographique v172 doivent être validés visuellement et dans des tests de non-régression sur tous les territoires avant activation.

Les pages calendrier et événement provenant de la même mairie **ne constituent pas deux organisateurs indépendants** ; l'identité du bâtiment et les coordonnées sont vérifiées séparément.

## 4. Résultat de vérification réel du 16/11

Le contrôleur privé `automation/gosier_access_conditions.py`, testé sur un runner public en lecture seule dans [#43940217493](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/43940217493), retrouve **9/9** séances, **9/9** tarifs non indiqués et **9/9** modalités d'inscription non indiquées, aucune prétention de gratuité, zéro approbation et zéro publication. Après correction des tests, 12/12 tests de conditions d'accès ont réussi.

Le module isolé `scripts/ptitesondes_nonmusic_release_contract.py` est un **audit de préparation**, non un éditeur de catalogue : il rend explicitement visibles les bloqueurs (catégorie historique, compatibilité frontend non contrôlée, absence de circuit public municipal et d'approbation privée). Ses sorties ne possèdent ni `additions`, ni `updates`, ni capacité d'écriture publique.

## 5. Déploiement et ordre d'approbation

- Conserver les PR ultramarines #64/#65/#66 (privées), #305/#310/#322 (publiques) en DRAFT.
- La présente PR prépare la politique et des tests **sans changer les fichiers JSON, les cinq crons ou le site**.
- Ne pas fusionner avant validation de la compatibilité de la carte v172 et de l'architecture de prévalidation municipale.
- Ne jamais confondre « preuve rapprochée » / « revue d'accès » / « approuvé en privé » / « publié ». À ce stade, **9 dossiers de revue, 0 fiche ajoutée**.

CINOR reste séparé : son événement du 18 novembre présente un UID OpenAgenda officiel et des âges documentés mais requiert toujours l'admission spécifique des activités jeunesse non musicales, la preuve organisatrice et la contre-vérification de publication. Les occurrences Basse-Pointe demeurent bloquées. La collecte métropolitaine et corse reste inchangée.
