# Ondes — Catalogues publics (pilote)

Dépôt **public** de données déjà visibles sur les sites [P'tites Ondes](https://ptitesondes.fr/) et [Grosses Ondes](https://grosses-ondes.fr/). Il est distinct des dépôts privés de développement et des lots de veille ChatGPT.

## État actuel

- Copie de référence : `docs/ptitesondes/sorties.json` provenant de `https://ptitesondes.fr/config/sorties.json`.
- **Aucun des nouveaux événements candidats** de la veille quotidienne n'est publié ici.
- Le workflow Pages est **manuel uniquement**, exige la confirmation `OUI` et ne publie que les fichiers contenus dans `docs/`.
- Aucune modification du site Infomaniak n'est effectuée depuis ce dépôt.
- Tant que le pilote n'est pas validé, les sites lisent leurs JSON habituels.

## Origine et intégrité

Les données publiques sont recopiées sans enrichissement, après contrôle du JSON et du schéma. La prochaine étape consistera à vérifier séparément l'exactitude des sources et des coordonnées GPS avant d'autoriser de nouveaux événements. Aucun jeton, secret GitHub, donnée interne de veille ou configuration d'hébergement ne doit être commité.

### Déploiement Pages

Dans GitHub : `Settings > Pages > Build and deployment > Source: GitHub Actions`, puis `Actions > GitHub Pages — copie de référence > Run workflow` et choisir **OUI**. Vérifier ensuite la disponibilité du JSON sur `https://sarogal.github.io/Ondes-Catalogues/ptitesondes/sorties.json`. Ne pas modifier les sites P'tites Ondes ou Grosses Ondes avant la fin des tests CORS, de schéma, de chargement et de repli.

Ce dépôt n'est **pas encore une source de vérité** pour les veilles. Pour l'instant, `https://ptitesondes.fr/config/sorties.json` reste la référence.
