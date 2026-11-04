# Vérification automatique des candidats P'tites Ondes

Workflow `.github/workflows/ptitesondes-evidence-preview.yml`.

La tâche existante de prévalidation indépendante est conservée comme **unique**
contrôleur de promotion, avec **quatre vérifications en lecture seule** à
08 h 40, 11 h 40, 15 h 40 et 19 h 40 UTC, après les quatre collectes privées
à 07 h 05, 10 h 05, 14 h 05 et 18 h 05 UTC. Le synchroniseur de la carte
contrôle ensuite à 09 h 20, 12 h 20, 16 h 20 et 20 h 20 UTC.
Le déclenchement manuel et le contrôle sur changement du moteur restent disponibles.

Le contrôleur **existant**
`scripts/ptitesondes_candidate_promotion.py` est réutilisé (pas de second moteur).
Il relit les découvertes privées via le secret existant
`PRIVATE_INTAKE_READ_TOKEN`, exige une référence historique intacte,
vérifie les sources, les séances exactes, la destination familiale, les
lieux documentés et le schéma compatible avec le synchroniseur.

Les résultats sont calculés dans `/tmp` sur le runner GitHub :
`preview-patch.json` et `report.json`. Ils ne sont jamais commités ni
déployés. Le résumé Actions ne contient que les compteurs, et les liens
détaillés privés ne sont pas publiés en artifacts.

**Validation restante :** vérifier les résultats des runs réels, fiabiliser
la preuve des lieux non enregistrés, puis seulement décider d'un mécanisme
d'ingestion du patch privé validé. Ne pas désactiver la veille ChatGPT
avant une preuve de publication publique sans perte de données.
