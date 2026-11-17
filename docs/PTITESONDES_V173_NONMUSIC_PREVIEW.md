# P’tites Ondes — prévisualisation v173 des sorties non musicales

**16 novembre 2026. DRAFT seulement. Aucune fusion, publication, ni modification Infomaniak.**

## Origine et non-régression

L'instantané previews/ptitesondes/sorties-v172-live-snapshot.js a été téléchargé en HTTPS sur un runner public, depuis https://ptitesondes.fr/sorties-v172.js.

- 34 970 octets UTF-8.
- SHA-256 : fc561030dcc07bdc375dedce2c204897c57197a5714c14b4ed39b1e0eb44729a.
- Huit marqueurs de la version v172 vérifiés : sélection de territoires, catégories, carte et filtres.
- La tâche temporaire disposant d'un droit d'écriture a été supprimée après la capture.

La copie source est un **instantané**, pas une vérité permanente. Avant un déploiement, comparer ses octets au script alors réellement servi ; si celui-ci a changé, rebaser.

## Candidat isolé de la carte

Le fichier previews/ptitesondes/sorties-v173-nonmusic-preview.js conserve la carte ultramarine existante et ajoute uniquement :

- Quatre nouvelles options au filtre de type, de manière idempotente : lecture-jeunesse (Lecture jeunesse), atelier-numerique (Atelier numérique), lecture-cinema (Lecture et cinéma), jeux-famille (Jeux en famille).
- Quatre groupes MapLibre et pictogrammes distincts : 📚, 💻, 🎬 et 🎲.
- Le filtre d'âge, les six zones, l'historique musical, les popups, les cartes des lieux permanents, la recherche et la mention « Voir conditions » sont conservés.

**Le contrat d'admission n'est pas modifié** : aucun candidat privé n'entre sur la carte en l'absence d'une fiche officiellement publiée.

## Tests et statut

Le workflow public sans secret ni écriture .github/workflows/ptitesondes-v173-preview-tests.yml lance les tests Node sans dépendance externe sous tests/ptitesondes_v173_frontend_preview.test.mjs.

Il vérifie la syntaxe, les 4 options, les icônes, la recherche, les âges, les territoires (Guadeloupe / Réunion / métropole), l'ancien classement musical et la conservation à l'identique des fonctions géographiques de v172.

Première CI verte : https://github.com/Sarogal/Ondes-Catalogues/actions/runs/43955659152 — 5/5 tests.

Les tests automatisés ne remplacent pas une validation graphique de la carte avec MapLibre.

## Conditions avant un déploiement

1. Accord explicite du propriétaire du site.
2. Admission publique sûre des quatre slugs et du circuit municipal de preuves.
3. Approbation privée et authentifiée de chaque occurrence.
4. Tests navigateur de la carte, des six zones et des lieux permanents.
5. Correspondance stricte avec le JavaScript réellement servi au moment du déploiement.
6. Si toutes les étapes réussissent, remplacement explicitement autorisé du script sur Infomaniak et mise à jour du lien dans sorties.html.
7. Vérification du non-écrasement de toutes les fiches historiques (548 à la vérification initiale du 16 novembre).

**Aucun déploiement de production n'est inclus dans cette PR.** Le candidat reste dans previews/ et n'est pas ajouté au JSON public.
