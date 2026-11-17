# P'tites Ondes — Prévisualisation isolée v174, agenda familial élargi

**17 novembre 2026 — DRAFT, aucun déploiement.**

## Socle et dépendances

Cette PR est **empilée sur la PR #327 (v173 en brouillon)**. Elle n'affecte
pas sa copie v172 ni son fichier candidat v173, et ne modifie pas la carte
actuellement en ligne, `sorties-v172.js`. Le catalogue public version 3
est inchangé : ses 548 fiches et ses **7 catégories musicales** sont
intégralement conservées.

La catégorie nationale de référence est préparée en parallèle dans
**#342**, et le prévalidateur indépendant dans **#346**. Ces deux PR ne
sont pas des prérequis fusionnés de cette prévisualisation : leurs contrats
doivent être revérifiés ensemble avant un éventuel déploiement.

## Ce que le candidat v174 ajoute

Fichier isolé :
`previews/ptitesondes/sorties-v174-family-facets-preview.js`

Les 4 options jeunesse individuelles de v173 restent disponibles, tandis
que **9 options de filtre transversal** sont ajoutées au menu existant :

1. Lecture jeunesse
2. Ateliers créatifs, numériques et sciences
3. Cinéma et lecture
4. Jeux en famille
5. Spectacles jeune public
6. Nature, animaux et fermes
7. Musées et patrimoine
8. Fêtes et animations familiales
9. Sport jeunesse

Ces options ont des valeurs préfixées `family:`, et filtrent uniquement
les **13 identifiants non musicaux** prévus dans la PR #342.
Exemple : `family:atelier` sélectionne `atelier-numerique`,
`atelier-creatif` et `atelier-scientifique`, **jamais**
`atelier-musical`.

Un ensemble de marqueurs lisibles est également préparé : création 🎨,
science 🔬, nature 🌳, animaux 🐾, culture 🏛️, fête 🎈,
sport ⚽, avec réutilisation des icônes cinéma 🎬 et spectacle 🎭.
Ces visuels complètent les marqueurs musicaux et les quatre marqueurs
déjà préparés en v173 sans les supprimer.

## Sécurité et ergonomie

- Ne remplace pas le sélecteur géographique à six zones
  (métropole avec Corse, Guadeloupe, Martinique, Guyane, La Réunion, Mayotte).
- Les contrôles d'âge, de dates, de zoom et de territoires restent identiques
  à v173 ; un nouveau filtre familial ne change pas la localisation.
- La recherche, les cartes individuelles et les fenêtres d'informations
  réutilisent le titre, le lieu, la date et la source **déjà présents dans
  les fiches publiées**.
- Aucune catégorie déclarée sans vérification ne crée une fiche. Aucune
  donnée n'est écrite ; aucun `patch.v1` n'est produit.
- Les animations ponctuelles de lieux permanents restent des **sorties
  datées** et n'impactent pas la case existante « Lieux pour enfants ».

## Tests

`node --test tests/ptitesondes_v174_family_facets_preview.test.mjs`

Exécutés sans accès privé ni publication sur des runners **publics**
en lecture seule : initialisation idempotente, filtrage exact des 13
catégories et des 9 facettes, exclusion des événements musicaux
des facettes familiales, marqueurs, tests réels de géométrie et d'âge
sur des **fixtures inventées**, invariants de l'ancienne v173.
La suite cartographique v173 reste indépendante sur sa PR d'origine.

## Suite

Avant toute mise en ligne : revue visuelle de la carte avec vraies fiches
qualifiées, vérification du menu sur mobile, source officielle par territoire,
compatibilité avec le catalogue final, homologation du circuit de publication
et **autorisation explicite** de fusion et déploiement. Ce prototype ne doit
pas être copié à la racine du site Infomaniak.

Retour arrière : abandonner la PR sans toucher au site ni au catalogue.
