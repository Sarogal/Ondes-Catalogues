# P’tites Ondes — audit de compatibilité carte v172 / catégories jeunesse
**16 novembre 2026 — rapport de lecture seule, aucun correctif Infomaniak déployé.**

## Vérifications de l’interface actuelle

Page : https://ptitesondes.fr/sorties.html ; script actif :
https://ptitesondes.fr/sorties-v172.js

- La carte déjà validée possède un sélecteur géographique Métropole + Corse /
  Guadeloupe / Martinique / Guyane / La Réunion / Mayotte. **Ne jamais retirer
  cette fonctionnalité** ni remplacer le JS actuel par une copie antérieure.
- Le filtre **Type** compare strictement le slug `event.category` avec la
  valeur de l’option choisie. `category_label` sert à l’affichage et à la
  recherche textuelle ; un libellé nouveau ne rend pas automatiquement
  sélectionnable sa catégorie.
- Aucun des quatre slugs `lecture-jeunesse`, `atelier-numerique`,
  `jeux-famille`, `lecture-cinema` n’est exposé comme option distincte
  dans la version observée. Le bouton « Toutes les sorties » peut être
  compatible avec un événement nouveau, mais cela **ne prouve pas** le
  fonctionnement complet du filtre, des couleurs et des pictogrammes.
- Les groupes de marqueurs actuels sont dédiés aux événements musicaux et
  l’activité inconnue retombe sur un pictogramme spectacle générique.
  Une représentation jeunesse non musicale doit être explicitement choisie
  et testée, sans réutiliser un pictogramme musical trompeur.
- Les cartes de fiches et les popups échappent leurs textes avant injection ;
  la présence de `category_label` convient au libellé proposé. L’affichage
  de la carte utilise `event.price || 'Voir conditions'` et offre un lien
  source : une source sans prix peut afficher un renvoi honnête, mais jamais
  une gratuité inventée.
- L’interface affiche directement la chaîne `time` et le jour
  `date_start` ; les propositions ultramarines doivent donc conserver des
  **horaires locaux explicitement vérifiés**, sans les convertir
  automatiquement en heure de Paris.
- Les filtres d’âge, la recherche et le zoom doivent être testés sur des
  exemples ultramarins réels et sur les sorties musicales historiques.
  Le calque des lieux permanents (`sorties-lieux-v1.js`) doit rester intact.

## Contrainte d’intégration

Une copie antérieure de `sorties-v172.js` trouvée dans les fichiers du projet
(15 novembre) **n’inclut pas** le sélecteur géographique actuellement présent
sur Infomaniak. Elle ne constitue donc pas une base de correctif sûre.
Avant toute proposition de fichier à déployer, récupérer les octets exacts
de la version actuellement servie, préserver le comportement territorial,
et réaliser une comparaison ciblée ainsi qu’une revue de diff.

## Plan de test de non-régression sur copie

1. Contrats de catégories (exactement les 7 historiques + les 4 nouveaux
   slugs documentés, sans classer une lecture dans `conte-musical`).
2. Option Type « Toutes », puis sélection individuelle de chacune des
   quatre nouvelles catégories et retour à toutes les sorties.
3. Recherche accentuée/non accentuée, titre, ville, `category_label`.
4. Tranches d’âge (incluant une borne maximale `Jusqu’à 3 ans`,
   une borne minimale `Dès 8 ans`, et `En famille`).
5. Icônes, clusters, popups, liste visible, clic source, bouton retour.
6. Géographie : d’abord Le Gosier puis La Réunion, passage à la métropole,
   conservation des fonds de carte et des lieux permanents.
7. Jour/heure locale : 18 novembre 14h à Saint-Denis (+04) et
   18 novembre 9h au Gosier (UTC−04), sans utiliser l’heure du navigateur
   pour modifier les horaires de séance.
8. Prix et inscription absents : « Voir conditions », source officielle
   cliquable ; aucune assertion « Gratuit » ou « Sans inscription ».
9. Non-régression : conserver les 548 fiches historiques, toutes les
   catégories musicales, tous les marqueurs et le fichier des lieux.

## Critères de sortie

- Diff JavaScript isolé sur **la version de production exacte**,
  avec tests JavaScript ou tests navigateur automatisés et revue humaine.
- Publication des catégories seulement après activation contrôlée du
  schéma de validation et du prévalidateur municipal.
- **Autorisation explicite de l’utilisateur** avant déploiement Infomaniak,
  fusion de PR et premier ajout au catalogue public.

**Statut :** audit/documentation uniquement. `sorties-v172.js` public inchangé.
