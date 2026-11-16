# Grosses Ondes — secours indépendant des veilles Concerts manquées (proposition)

**Statut : PR brouillon, NON DÉPLOYÉ, NON ACTIVÉ.** Aucune action ni
autorisation n'est donnée à un Worker Cloudflare par ce document.

## Constat du 16 novembre 2026

Le workflow public existant `grossesondes-concerts-private-intake-on-public-runners.yml`
est programmé à **07:18, 13:11 et 20:11 UTC**, pas à ces heures locales.
Son exécution #38 (GitHub Actions `43777527739`, terminée 16/11
00:09 UTC) a effectivement collecté et archivé des dossiers privés puis
échoué **volontairement** sur la prévalidation de publication (lot mixte,
voir PR indépendante #316). Il ne faut pas confondre cet échec sécuritaire
et une collecte totalement absente.

La page du workflow consultée le 16/11 en fin de matinée CET indiquait
38 exécutions et ne montrait **aucune nouvelle exécution à 07:18 UTC**.
Le watchdog existant `monitoring/ondes_watchdog.php` est en lecture seule
et accorde 9 heures de retard à GitHub. Son déclenchement
`ondes-public-watchdog.yml` ne relance pas les collectes.

## Modèle proposé

Fichier : `scripts/grossesondes_concerts_external_rescue_worker.mjs`.
C'est un Cloudflare Worker **HTTP inerte (404)**, activable uniquement
par trois Cron Triggers indépendants de GitHub Actions :

| Veille principale GitHub (UTC) | Secours Cloudflare (UTC) |
|---|---|
| 07:18 | **16:28** le même jour |
| 13:11 | **22:21** le même jour |
| 20:11 | **05:21** le lendemain |

Les 9 h 10 min de marge donnent au cron GitHub largement le temps de
démarrer. Les crons étant en UTC, il n'existe pas de décalage DST non
documenté. Ces **3 déclencheurs** consomment trois emplacements parmi la
limite du plan gratuit Cloudflare Workers à confirmer dans le compte ;
deux déclencheurs sont déjà réservés par le projet indépendant
P'tites Ondes si son secours est mis en service.

Le Worker utilise le jeton limité `GITHUB_DISPATCH_TOKEN` pour **lire
uniquement les métadonnées de runs** du workflow public, jamais le dépôt
privé. Il refuse d'appeler l'API de relance si :

- une exécution `schedule` existe déjà pour le créneau, même en
  conclusion `failure` ; un refus de preuve est un garde-fou, pas une
  raison de consommer des runners en boucle ;
- une exécution manuelle ou un rattrapage `workflow_dispatch` de
  `main` a démarré après l'heure attendue ;
- l'API des runs est indisponible, incomplète, non datée, malformée ou
  retourne 100 résultats sur une seule page.

Seulement si aucun run correspondant n'existe, le Worker envoie **une
requête** `workflow_dispatch` avec `ref=main`, `phase=catchup` au
workflow **public existant**, jamais à un dépôt privé. Cela lance
**une nouvelle collecte nationale**, pas une simulation ni une garantie
de reconstitution de tous les instantanés historiques. Le publisher
et les validations privées existants restent intacts. Un HTTP 204
signale seulement la prise en compte de la demande d'exécution par
GitHub, pas le succès de la veille.

Le verrou `concurrency` du workflow actuel limite les chevauchements
mais ne garantit pas une reprise parfaite si GitHub délivre très tard
un cron initial. Cette architecture réduit le risque de passage nul
sans le supprimer totalement. Ne jamais introduire de minute planifiée
dans le dépôt privé.

## Installation et validation demandant l'accord du propriétaire

1. Examiner et valider le code, les tests et les permissions ; aucune
   activation automatique de GitHub Actions ou Cloudflare n'est faite
   par cette PR.
2. Vérifier dans Cloudflare que Workers Free permet trois Cron Triggers
   supplémentaires dans le compte, sans abonnement.
3. Créer un PAT finement limité au seul dépôt **public**
   `Sarogal/Ondes-Catalogues` avec la permission dépôt
   **Actions: Read and write**, sans `Contents: write`, aucun droit
   sur `Sarogal/GrossesOndes`.
4. Mettre ce jeton uniquement dans les **Secrets** du Worker
   (`GITHUB_DISPATCH_TOKEN`) ; ne jamais le partager dans le chat, une
   issue Git, le code, un URL ni les journaux.
5. Déployer le Worker avec les **trois crons ci-dessus** depuis
   Cloudflare et vérifier dans GitHub l'événement
   `workflow_dispatch` attendu en cas de schedule absent, sans
   désactiver les trois horaires GitHub existants.
6. Vérifier ensuite dans le dépôt privé que le registre et le rapport
   sont actualisés ; le Worker n'accède pas au registre lui-même.
7. Désactivation : supprimer les Cron Triggers et révoquer le PAT ; la
   veille GitHub normale n'est pas touchée.

**Tests hors réseau** :
`node --test tests/test_grossesondes_concerts_external_rescue_worker.mjs`.

Cette PR n'active pas ce mécanisme et n'altère aucun JSON de concert,
aucune approbation privée et aucun déploiement Infomaniak.
