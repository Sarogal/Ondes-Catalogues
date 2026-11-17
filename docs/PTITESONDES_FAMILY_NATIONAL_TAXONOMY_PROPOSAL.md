# P'tites Ondes — Taxonomie nationale des sorties familiales

**17 novembre 2026 — Proposition expérimentale, PR en brouillon.**
**Aucune activation d'admission ni publication.**

## 1. Objectif éditorial

Étendre « Les sorties des P'tites Oreilles » aux activités **réellement destinées
aux enfants et aux familles** en métropole, en Corse et dans les territoires
ultramarins (Guadeloupe, Martinique, Guyane, La Réunion et Mayotte).
Conserver l'intégralité des **catégories musicales historiques**, leurs
vérifications et leur circuit OpenAgenda existants.

Une annonce locale sans activité pour les enfants explicitement identifiée
n'est pas une sortie familiale. Un festival généraliste, une fête locale ou
une animation sportive ne devient pas admissible par son seul titre.
Les activités gratuites **et** payantes sont possibles : ne jamais extrapoler
prix, inscription ou âge à partir d'une absence d'information.

## 2. Catégories proposées

| Identifiant | Libellé | Famille de filtre | Statut |
|---|---|---|---|
| `lecture-jeunesse` | Lecture jeunesse | Lecture | Maintien strict de #323 |
| `atelier-numerique` | Atelier numérique | Atelier | Maintien strict de #323 |
| `lecture-cinema` | Lecture et cinéma | Cinéma | Maintien strict de #323 |
| `jeux-famille` | Jeux en famille | Jeux | Maintien strict de #323 |
| `atelier-creatif` | Atelier créatif | Atelier | Nouveau — proposition |
| `atelier-scientifique` | Atelier scientifique | Atelier | Nouveau — proposition |
| `spectacle-jeunesse` | Spectacle jeune public | Spectacle | Nouveau — proposition |
| `cinema-jeunesse` | Cinéma jeune public | Cinéma | Nouveau — proposition |
| `sortie-nature` | Sortie nature | Nature | Nouveau — proposition |
| `animaux-ferme` | Animaux et ferme pédagogique | Nature | Nouveau — proposition |
| `musee-patrimoine` | Musée et patrimoine | Culture | Nouveau — proposition |
| `fete-familiale` | Fête et animation familiale | Événement | Nouveau — proposition |
| `activite-sportive` | Activité sportive jeunesse | Sport | Nouveau — proposition |

Le libellé est une proposition d'affichage, **pas une catégorie acceptée
par le publisher**, ni un futur choix automatique sur base de mots-clés.

### Groupements suggérés pour la carte

Ne pas afficher nécessairement 13 filtres en tête de page :
garder les **9 facettes** (lecture, atelier, cinéma, jeux, spectacle,
nature, culture, événement et sport) pour une navigation claire,
tout en conservant l'ID technique fin pour les détails et les contrôles.
Les catégories musicales sont conservées dans leur circuit indépendant.
Le front-end actuel v172 et la prévisualisation v173 (#327) ne sont pas touchés.

## 3. Sorties ponctuelles et lieux permanents

- `record_kind = dated_event` : **Sorties**, avec date de début/fin
  explicitement prouvée par une source officielle. Exemples : lecture un
  mercredi, atelier au musée, animation à la ferme. Une séance récurrente
  nécessite **sa propre occurrence datée**, jamais une récurrence inventée.
- `record_kind = permanent_place` : **Lieux pour enfants**, sans
  substitution par une pseudo-sortie valable tous les jours. Exemples :
  ferme pédagogique permanente, ludothèque, musée, parc familial.
- Un **atelier daté** dans un lieu permanent peut apparaître en **Sorties**,
  tandis que le lieu reste également présent dans **Lieux pour enfants**.
  Il faudra contrôler la déduplication et les sources de chaque fiche.

## 4. Périmètre du module ajouté

`scripts/ptitesondes_family_national_scope.py` propose uniquement
`audit_family_scope(proposals, today)` :

- schéma expérimental de 13 catégories **non musicales** ;
- forme HTTPS des URL, présence d'un titre, d'une ville, d'un lieu et
  d'une **déclaration** de public enfant/famille ;
- dates valables pour un événement daté, aucune date autorisée pour une
  fiche de lieu permanent ;
- âges chiffrés entre 0 et 17 ans **uniquement lorsqu'ils sont déclarés**,
  sans âge inventé pour une activité « en famille » ;
- états explicites `not_stated`, `ambiguous`, `contradictory`,
  `explicit_free` / `explicit_price` pour l'accès ;
- sortie limitée à des **compteurs agrégés** de pertinence structurelle,
  de catégories, de routes et de refus.

L'URL de forme HTTPS n'est **pas** une preuve qu'un événement est officiel.
Les champs d'audience et d'accès restent des déclarations de collecteurs,
à revérifier auprès des organisateurs. Aucun contrôle géographique externe,
anti-doublons, droits GitHub ou attestation humaine ne sont implémentés ici.
Les résultats « structuriellement plausibles » **ne sont jamais admissibles**
en l'état. Aucune identité, fiche ou nouveau catalogue n'est produit.

### Invariants

Le module retourne toujours :
- `publication_ready = false`
- `approval_granted_to_publisher = false`
- `public_writes = 0`
- `historical_records_modified = 0`
- `historical_records_deleted = 0`

Aucun `patch.v1`, `additions`, donnée d'événement, chemin d'écriture
ou modification d'OpenAgenda, `merge_policy.merge`, `sorties.json`,
`lieux.json`, carte v172/v173, runner planifié, secret ni Infomaniak.

## 5. Chaîne de preuves à créer avant activation

1. **Découverte nationale** : agendas municipaux, lieux culturels et
   institutions publiques, sites des organisateurs identifiés ;
   séparer découverte brute et admission.
2. **Qualification indépendante** : correspondance exacte titre, séance,
   heure locale, âge, organisateur, statut, réservation et prix ; distinguer
   source organisatrice d'un agrégateur. Vérifier lieu, précision GPS,
   région et rattachement ultramarin comme pour #305/#322.
3. **Anti-doublons inter-sources** : même occurrence date/lieu/activité,
   éventuellement déjà publiée par OpenAgenda ou un site partenaire.
4. **Approbation privée** : preuves figées et décision authentifiée,
   révocable, liée au catalogue **actuellement publié**, avec attestation
   individuelle si utilisée. Reprendre les garanties de #341 sans prétendre
   que son circuit municipal du Gosier vaut déjà pour toute la France.
5. **Simulation et contrôle terminal** : politique explicite de nouvelles
   catégories et preuve textuelle propre à chaque famille, tests adversariaux,
   simulation atomique et vérification finale contre le catalogue public.
6. **Interface** : prototype des filtres/facettes et marqueurs, tests en
   métropole/Corse/outre-mer, puis validation indépendante de la carte.
7. **Publication** : uniquement après accord explicite, PR séparée,
   aucune exécution programmée dans les dépôts privés.

## 6. Compatibilité, CI et retour arrière

La PR doit cibler `main`, **indépendamment** de la pile #323 → #341,
afin de ne pas modifier les contrôles spécifiques du Gosier avant leur revue.
La PR #327 (prévisualisation quatre catégories) n'est pas modifiée.

Le workflow public hors ligne exécute uniquement
`tests/test_ptitesondes_family_national_scope.py` sur push de la branche
ou ouverture/mise à jour de PR ; permission `contents: read`, aucun cron,
aucun jeton réel. La suite existante du synchroniseur peut s'exécuter
séparément en CI. Les jeux de tests sont **synthétiques**.

Retour arrière : fermer ou abandonner cette PR, sans changer ni le site
ni une seule fiche du catalogue ni les workflows récurrents.
