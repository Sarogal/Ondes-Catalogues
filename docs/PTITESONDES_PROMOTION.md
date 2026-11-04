# P'tites Ondes — prévalidation des propositions privées (4 novembre 2026)

## Portée

Workflow `.github/workflows/ptitesondes-evidence-preview.yml`, exécutable sur
`main` à 09:15 UTC chaque jour et manuellement. **Lecture seule** sur le
catalogue public, sur GitHub Pages et sur la branche privée de collecte.

Le rapport quotidien résume uniquement les quantités : propositions privées,
candidats disposant d'un lieu documenté, fiches examinées, refus et
prévalidations. Les détails source par source sont écrits en mémoire du runner
dans `/tmp/ptitesondes-promotion` pendant le job ; ils ne sont ni committés,
ni téléversés comme artifacts dans le dépôt public, ni affichés en log.

## Validation indépendante

Une proposition ne peut accéder à la prévalidation que si :

1. son UID OpenAgenda est numérique, son URL canonique HTTPS est sur
   `openagenda.com`, la date est dans l'horizon et sa séance est unique ;
2. la commune et le nom exact du lieu correspondent au
   `scripts/venue_registry.py` (lieux déjà documentés) ;
3. une requête **bornée** à l'index OpenDataSoft pour le même UID confirme
   titre, URL canonique, commune, salle, séance locale horodatée, statut
   programmé et département/région ;
4. les coordonnées de l'index et celles du registre du lieu sont à 65 m ou
   moins ; les coordonnées publiables viennent du registre documenté,
   jamais d'une prédiction ni de l'index seul ;
5. une catégorie *musicale et familiale* est explicite ; aucune fiche
   adulte « concert » ou « ciné-concert » n'est sélectionnée sur le seul genre ;
6. le contrôleur existant `proof_text.verify_event` vérifie indépendamment
   la page officielle, ses heures, date, titre, salle et restrictions ;
7. les mêmes validations structurales que `merge_policy.valid` s'appliquent ;
8. identifiants historiques, signatures, URL/date des fiches publiées ne
   doivent présenter aucune collision.

Les jours non consécutifs restent des fiches distinctes. Les tarifs/âges
absents des champs structurés ne sont pas inventés. Aucun autre champ des
fiches existantes n'est écrasé.

## Exploitation et limites

- Maximum **15 propositions vérifiées par passage**, **10 enregistrements
  maximum** par UID et réponse réseau bornée.
- Une page inaccessible, une différence de date, une source non officielle,
  une géographie non documentée ou un statut inconnu bloquent la promotion.
- Les candidates absentes du registre de lieux restent dans le backlog privé ;
  elles ne sont pas supprimées ni faussement géolocalisées.
- Le schéma de patch v1 est respecté ; le projet n'active **pas encore**
  l'écriture automatique de ces patches dans `automation/ptitesondes-intake`
  ni la publication publique.
- Aucun secret OpenAI/ChatGPT requis. Seul
  `PRIVATE_INTAKE_READ_TOKEN` doit disposer du droit **lecture seule**
  sur le dépôt `Sarogal/PtitesOndes`.
- Avant d'activer une promotion publique ultérieure, contrôler plusieurs
  exécutions, examiner les résultats de preuve et réaliser un test de
  synchronisation en `preview`.

Les alertes de report/annulation et la correction d'une fiche déjà publiée
restent hors de ce prévalidateur. Une procédure séparée avec traces
de preuves et interdiction de supprimer l'historique sera nécessaire.

**Ne pas arrêter la veille ChatGPT** avant plusieurs publications réellement
constatées sur GitHub Pages et le site.
