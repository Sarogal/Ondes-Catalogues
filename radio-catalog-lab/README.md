# Grosses Ondes — laboratoire public des contrats du catalogue radio

**Branche isolée uniquement :** audit/radio-catalog-contract-ci-20261115.

Ce répertoire héberge uniquement les outils Python génériques de validation de données, les schémas JSON v1 et leurs tests synthétiques. Il sert à exécuter les contrôles sur les runners gratuits du dépôt public, car les Actions du dépôt privé peuvent ne pas démarrer.

**Il ne contient pas** le catalogue radio privé, les flux préparés, les preuves éditoriales, les favoris, des données d'un téléphone, de secrets, ni les sources Flutter privées.

- tests Python sans réseau pour le cache et les logs de logos ;
- contrôles d'identité, d'alias, de stream et de statuts du catalogue central ;
- import reproductible d'un ancien catalogue de secours vers des **candidats non qualifiés** ;
- simulateur de projection des anciens favoris, sans écriture dans l'application ;
- schémas JSON et scénarios synthétiques.

Workflow dédié : .github/workflows/radio-catalog-contract-ci.yml, déclenché uniquement pour les modifications radio-catalog-lab/** de cette branche. Permissions contents: read. **Aucun job de déploiement, aucun transfert Infomaniak et aucune modification de main.**

Résultat constaté le 15/11/2026 : **25 tests unitaires et deux JSON Schema validés** sur GitHub Actions :
https://github.com/Sarogal/Ondes-Catalogues/actions/runs/43700292564

Le projet et le premier import en staging restent exclusivement dans Sarogal/GrossesOndes, branche design/radio-catalog-central-20261114. Toute publication nécessite une validation ultérieure explicite.
