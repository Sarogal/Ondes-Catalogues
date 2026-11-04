# P'tites Ondes — promotion contrôlée des propositions privées

## Chaîne en cours (4 novembre 2026)

1. `Sarogal/PtitesOndes` effectue la découverte nationale sur GitHub Actions,
   puis conserve les nouvelles pistes dans
   `automation/ptitesondes-intake/automation-intake/ptitesondes/backlog.json`.
2. La tâche `ptitesondes-promotion-preview.yml` du dépôt public interroge ce
   backlog via `PRIVATE_INTAKE_READ_TOKEN`, **en lecture seule**.
3. Seules les propositions OpenAgenda dont la salle et la commune figurent
   dans le registre **géolocalisé indépendamment** sont examinées.
4. Leur fiche indexée est relue par UID exact ; titre, URL, commune, lieu,
   séance, horaires, statut, région et département doivent concorder.
   Les coordonnées de la source doivent être cohérentes avec le registre.
5. Une preuve **indépendante** du titre, de la date, des horaires et du lieu
   est recherchée sur la page officielle grâce au vérificateur existant.
6. Les résultats sont consignés dans le résumé GitHub Actions. Aucun commit,
   push, déploiement ni ajout au patch privé ne sont produits à ce stade.

## Garde-fous

- Un ciné-concert adulte n'est pas un événement enfant.
- Les dates discontinues demeurent des fiches distinctes.
- Un événement annulé, reporté ou à statut non interprétable est exclu.
- Aucune localisation GPS n'est inventée à partir du nom d'une commune.
- Les nouvelles salles ne peuvent être enregistrées qu'après rapprochement
  d'une adresse officielle et d'une preuve cartographique indépendante.
- Les tarifs et âges non confirmés ne sont pas inventés.
- Les fiches déjà publiques sont reconnues par ID **et** par signature.
- La vérification n'est pas une autorisation de publication : le
  synchroniseur public `merge_policy.merge` conserve tous ses contrôles.
- Les erreurs réseau sont comptées, sans autoriser une publication.
- Les jetons restent exclusivement dans les secrets GitHub.

## Travail restant avant publication automatique

Valider plusieurs exécutions de prévisualisation, approfondir les preuves des
nouvelles salles, puis établir la conversion des candidats contrôlés en
patch privé `ptitesondes.patch.v1` conservant la référence historique
(487 fiches). La publication ne devra avoir lieu qu'après vérification
finale par `merge_policy.merge` et absence de modification/suppression des
fiches historiques. Prévoir séparément des corrections de fiches existantes
avec preuves avant/après et conservation de l'identifiant.

**La veille ChatGPT reste active** tant que la publication en conditions
réelles n'est pas démontrée sur plusieurs jours.
