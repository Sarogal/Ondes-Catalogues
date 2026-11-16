# P'tites Ondes — Rapprochement municipal par lot (PR empilée, 16/11/2026)

**Statut : développement isolé / jamais une validation de publication.**

## Dépendances et périmètre

Cette branche est issue du **SHA final de la PR #332**, elle-même empilée sur
#330 → #328 → #325 → #323. Les PR #305 (lieux GPS), #327 (carte v173),
#310/#322 (outre-mer), ainsi que #64/#65/#66 privées restent séparées.

Le nouveau fichier `scripts/ptitesondes_municipal_batch_readiness.py`
n'est invoqué **ni par le synchroniseur, ni par un job de publication**.
Aucune modification de `merge_policy.merge`, de `proof_text`, du promoteur
OpenAgenda, des catalogues JSON, du site, des cinq collectes publiques ou du
dépôt privé. Pas de secret ni de workflow programmé.

## Contrat opérationnel

`inspect_municipal_batch(reference, current, dossiers, today, *, reference_sha256,
current_sha256, token, source_get, github_get, geo_check)` :

1. Exige deux empreintes SHA-256 **apportées indépendamment** par le processus
   de revue. Si l'une est périmée, échoue avant toute qualification.
2. Vérifie que tous les événements historiques de `reference` sont présents
   **à l'identique** dans `current`; un ajout nouveau déjà publié peut rester,
   mais impose un **nouvel accord privé lié au SHA courant**.
3. Pour chaque dossier (maximum 100), exige une occurrence et un manifeste
   corrélés, puis **réexécute** le contrôle #332 : calendrier et fiche
   officielle, date/heure, lieu, catégorie, âge, accès, approbations privées
   réelles (dont SOURCE_ONLY distinct quand nécessaire), GPS indépendant.
4. Détecte les doublons dans le catalogue courant **et** à travers les autres
   dossiers de ce lot : mêmes ID, titre/lieu/date ou URL/date.
   Deux séances de la même animation à des dates distinctes restent distinctes.
5. Recontrôle les empreintes et le contenu des catalogues après chaque dossier,
   et échoue en cas de mutation ou de suppression.
6. Retourne seulement des **compteurs agrégés** et des motifs de blocage.
   Pas d'identifiant privé, de fiche, de patch, de `additions`, de `updates`,
   de `events` ou de contenu réinsérable dans un catalogue.

Les noms des champs sont volontairement explicites :
`isolated_diagnostic_passes` n'accorde AUCUN droit de publication.
`publication_ready` reste **false** ; `publisher_wired` reste **false**.

## Suite de tests

`python -m unittest discover -s tests -p 'test_ptitesondes_municipal_batch_readiness.py' -v`

- Neuf **fixtures synthétiques** : 3 dates le 18/11, 1 le 21/11, 4 le 25/11,
  1 le 28/11, avec les **quatre catégories non musicales**, deux jours
  distincts d'une même série.
- Tous les identifiants municipaux `9001..9009` et URL
  `/evenement/simulation-...` sont **inventés uniquement pour les tests**.
  Les textes `Gratuit / Inscription obligatoire` de ces fixtures sont
  **fictifs** : ils ne doivent pas être attribués aux véritables sorties
  du Gosier, dont les conditions restent inconnues au dernier contrôle.
- Tests adversariaux : jeton absent, approbation privée absente, décision
  SOURCE_ONLY, catégorie inconnue (dans #332), doublon même ID, doublon
  provenant d'une autre source, catalogue remplacé après décision,
  modification historique, mauvais SHA, GPS inexistant, site inaccessible,
  HTML modifié et tentative de mutation pendant la vérification.
- Les sources et appels GitHub sont injectés dans les tests : **aucun
  accès privé et aucun secret réel dans les runners publics**.

## Préparation de la première vague

Le rapport des **neuf véritables séances du Gosier**, et l'atelier CINOR
(OpenAgenda, autre voie), se trouve dans
`docs/PTITESONDES_ULTRAMARINE_FIRST_WAVE_20261116.md` (branche #332).

**Résultat opérationnel du nouveau moteur : 0 occurrence réelle admise.**
La réussite des neuf *fixtures* ne représente pas une preuve vivante :
les vraies données doivent recevoir les approbations privées individuelles,
un contrôle des conditions d'accès, la géolocalisation homologuée #305, et
un rapprochement avec le catalogue servi juste avant publication.

## Étapes restantes avant toute activation

1. Faire vérifier les dépendances et faire arbitrer les PR séparément.
2. Introduire (dans une nouvelle PR ultérieure, sur autorisation) un
   adaptateur **municipal vers publication** indépendant de la voie OA,
   côté public et côté privé. Il devra rejeter tout dossier qui n'a pas
   de preuve et d'accord *en direct*. Aucun jeton privé ne doit passer
   sur un runner public non autorisé.
3. Exiger la compatibilité du frontend v173 et de tous les territoires.
4. Exiger à nouveau la validation explicite de l'utilisateur pour toute
   fusion, première modification publique ou déploiement Infomaniak.

## Retour arrière

Fermer cette PR et supprimer la branche. Aucun rollback du catalogue n'est
nécessaire car aucun outil de publication n'est modifié.
